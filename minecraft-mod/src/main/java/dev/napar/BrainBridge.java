package dev.napar;

import carpet.fakes.ServerPlayerInterface;
import carpet.patches.EntityPlayerMPFake;
import com.google.gson.*;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.concurrent.*;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.phys.Vec3;

/** Network work is serialized off-thread; world access occurs only on the server thread. */
public final class BrainBridge {
    private final String token = System.getenv("NAPAR_BRIDGE_TOKEN");
    private final String world = System.getenv("NAPAR_WORLD_ID");
    private final HttpClient http = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
        .connectTimeout(Duration.ofSeconds(2)).build();
    private final ScheduledExecutorService worker = Executors.newSingleThreadScheduledExecutor();
    private final ConcurrentLinkedQueue<JsonObject> results = new ConcurrentLinkedQueue<>();
    private final ConcurrentLinkedQueue<JsonObject> events = new ConcurrentLinkedQueue<>();
    private volatile JsonObject state;
    private volatile String session;
    private volatile long lastContact;
    private volatile long observedAt;
    private volatile boolean closed;
    private long sequence;
    private int ticks;
    private long generation = -1;
    private final GroundNavigator navigator;
    private final SurvivalActions actions;
    private final SurvivalReflexes reflexes;
    public BrainBridge(GroundNavigator navigator) { this.navigator = navigator; this.actions = new SurvivalActions(navigator); this.reflexes=new SurvivalReflexes(actions,this); }

    public void event(String kind,String text) {
        if(session==null||events.size()>=32)return;
        JsonObject event=new JsonObject();event.addProperty("session_id",session);event.addProperty("event_id",java.util.UUID.randomUUID().toString());
        event.addProperty("kind",kind);event.addProperty("text",text.substring(0,Math.min(2000,text.length())));events.add(event);
    }

    public boolean ask(String sender, String text) {
        if (session == null || state==null || System.nanoTime()-observedAt>TimeUnit.SECONDS.toNanos(2) || text.isBlank() || text.length() > 2000) return false;
        String owner = System.getenv("NAPAR_OWNER_NAME");
        if (owner == null || !owner.equals(sender)) return false;
        if (text.strip().equalsIgnoreCase("стоп") || text.strip().equalsIgnoreCase("stop")) events.clear();
        if (events.size() >= 32) return false;
        JsonObject event = new JsonObject();
        event.addProperty("session_id", session);
        event.addProperty("event_id", java.util.UUID.randomUUID().toString());
        event.addProperty("kind", "chat"); event.addProperty("sender", sender); event.addProperty("text", text);
        events.add(event); return true;
    }

    public void register() {
        if (token == null || token.length() < 32 || world == null || world.isBlank()) {
            worker.shutdown();
            return;
        }
        ServerLifecycleEvents.SERVER_STARTED.register(server ->
            worker.scheduleWithFixedDelay(() -> exchange(server), 0, 250, TimeUnit.MILLISECONDS));
        ServerLifecycleEvents.SERVER_STOPPING.register(server -> {
            closed = true;
            worker.shutdownNow();
            stop(server);
        });
        ServerTickEvents.END_SERVER_TICK.register(server -> {
            var player = server.getPlayerList().getPlayerByName("Napar");
            if (!(player instanceof EntityPlayerMPFake)) { state = null; reflexes.cancel(); actions.cancel(); return; }
            if (System.nanoTime() - lastContact > TimeUnit.SECONDS.toNanos(3)) stop(server);
            else {
                navigator.tick();
                actions.tick();
                reflexes.tick((EntityPlayerMPFake)player);
            }
            if (++ticks % 10 != 0) return;
            publishState((EntityPlayerMPFake)player);
        });
    }

    private void publishState(EntityPlayerMPFake player){
        JsonObject next=GameSensors.snapshot(player);next.addProperty("sequence",++sequence);next.addProperty("source_sequence",sequence);
        next.addProperty("halt_generation",generation);next.addProperty("activity",reflexes.active()?"emergency":actions.activity());state=next;observedAt=System.nanoTime();
    }

    public void stop(MinecraftServer server) {
        reflexes.cancel();
        actions.cancel();
        var player = server.getPlayerList().getPlayerByName("Napar");
        if (player instanceof EntityPlayerMPFake) ((ServerPlayerInterface) player).getActionPack().stopAll();
    }

    private JsonObject request(String path, JsonObject body) throws Exception {
        var builder = HttpRequest.newBuilder(URI.create(System.getenv().getOrDefault("NAPAR_BRIDGE_URL", "http://127.0.0.1:8000") + "/v1/bridge/" + path))
            .timeout(Duration.ofSeconds(2)).header("Authorization", "Bearer " + token);
        if (body == null) builder.GET();
        else builder.header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body.toString()));
        var response = http.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        if (path.equals("results") && response.statusCode() == 409) {
            JsonObject ignored = new JsonObject(); ignored.addProperty("accepted",false); return ignored;
        }
        if (response.statusCode() != 200) throw new IllegalStateException("Bridge HTTP " + response.statusCode());
        return JsonParser.parseString(response.body()).getAsJsonObject();
    }

    private void exchange(MinecraftServer server) {
        try {
            if(closed)return;
            if(state==null){
                if(session!=null&&!events.isEmpty()){
                    var event=events.peek();if(session.equals(event.get("session_id").getAsString()))request("events",event);events.remove(event);
                }
                return;
            }
            if(System.nanoTime()-observedAt>TimeUnit.SECONDS.toNanos(2))return;
            if (session == null) {
                JsonObject connect = new JsonObject();
                connect.addProperty("world_id", world); connect.addProperty("agent_name", "Napar");
                connect.add("capabilities", JsonParser.parseString("[\"inspect\",\"look_at\",\"say\",\"stop\",\"move_to\",\"follow_player\",\"mine\",\"place\",\"use_block\",\"equip\",\"eat\",\"drop\",\"pickup\",\"attack\",\"craft\",\"open_container\",\"transfer\",\"smelt\",\"sleep\",\"jump\",\"sneak\"]"));
                session = request("connect", connect).get("session_id").getAsString();
            }
            String sid = session;
            JsonObject snapshot = state.deepCopy();
            snapshot.addProperty("session_id", sid);
            // Python requires strictly increasing sequences, including repeated network polls.
            snapshot.addProperty("sequence", ++wireSequence);
            request("state", snapshot);
            if (!events.isEmpty()) {
                JsonObject event = events.peek();
                if (!sid.equals(event.get("session_id").getAsString())) events.remove(event);
                else { request("events", event); events.remove(event); }
            }
            while (!results.isEmpty()) {
                JsonObject result = results.peek();
                if(result.has("snapshot_sequence")&&result.get("snapshot_sequence").getAsLong()>snapshot.get("source_sequence").getAsLong())break;
                request("results", result); results.poll();
            }
            JsonObject response = request("actions?session_id=" + sid, null);
            long received = System.nanoTime();
            lastContact = received;
            server.execute(() -> {
                if (closed || !sid.equals(session)) return;
                long nextGeneration = response.get("halt_generation").getAsLong();
                if (nextGeneration != generation || response.get("stop").getAsBoolean()) stop(server);
                generation = nextGeneration;
                if (response.get("stop").getAsBoolean()) return;
                for (JsonElement entry : response.getAsJsonArray("actions")) execute(server, sid, entry.getAsJsonObject(), received);
            });
        } catch (Exception failure) {
            session = null; results.clear(); lastContact = 0;
            server.execute(() -> stop(server));
        }
    }
    private long wireSequence;

    private void execute(MinecraftServer server, String sid, JsonObject action, long received) {
        JsonObject result = new JsonObject();
        result.addProperty("session_id", sid);
        result.addProperty("action_id", action.get("action_id").getAsString());
        try {
            if ((System.nanoTime() - received) / 1e9 >= Math.min(3, action.get("ttl_seconds").getAsDouble()))
                throw new IllegalArgumentException("Action expired before execution");
            var player = server.getPlayerList().getPlayerByName("Napar");
            if (!(player instanceof EntityPlayerMPFake)) throw new IllegalStateException("Companion absent");
            JsonObject args = action.getAsJsonObject("arguments");
            String tool=action.get("tool").getAsString();
            if(reflexes.active()&&!tool.equals("inspect")&&!tool.equals("say")&&!tool.equals("look_at"))throw new IllegalStateException("Local emergency controller active; observe and reassess after retreat");
            switch (tool) {
                case "look_at" -> {
                    double x = args.get("x").getAsDouble(), y = args.get("y").getAsDouble(), z = args.get("z").getAsDouble();
                    if (!Double.isFinite(x) || !Double.isFinite(y) || !Double.isFinite(z)) throw new IllegalArgumentException("Invalid position");
                    ((ServerPlayerInterface) player).getActionPack().lookAt(new Vec3(x, y, z));
                }
                case "say" -> {
                    String message = args.get("message").getAsString();
                    if (message.length() > 240) throw new IllegalArgumentException("Message too long");
                    server.getPlayerList().broadcastSystemMessage(Component.literal("<Napar> " + message), false);
                }
                default -> {
                    double remaining = action.get("ttl_seconds").getAsDouble() - (System.nanoTime()-received)/1e9;
                    actions.start((EntityPlayerMPFake)player,action.get("tool").getAsString(),args,remaining, outcome -> {
                        if(player.isAlive()&&server.getPlayerList().getPlayerByName("Napar")==player)publishState((EntityPlayerMPFake)player);
                        outcome.addProperty("snapshot_sequence",sequence);
                        outcome.addProperty("session_id",sid); outcome.addProperty("action_id",action.get("action_id").getAsString()); results.add(outcome);
                    });
                    return;
                }
            }
            result.addProperty("status", "succeeded"); result.addProperty("detail", "Executed on server thread");
        } catch (RuntimeException failure) {
            result.addProperty("status", "failed"); result.addProperty("detail", failure.getMessage() == null ? "Action rejected" : failure.getMessage().substring(0,Math.min(1000,failure.getMessage().length())));
        }
        results.add(result);
    }
}

