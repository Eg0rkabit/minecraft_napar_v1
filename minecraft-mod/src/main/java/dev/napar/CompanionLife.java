package dev.napar;

import carpet.patches.EntityPlayerMPFake;
import com.google.gson.*;
import java.nio.file.*;
import net.fabricmc.fabric.api.entity.event.v1.ServerLivingEntityEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.*;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.level.GameType;
import net.minecraft.world.level.portal.TeleportTransition;
import net.minecraft.world.phys.Vec3;
import org.slf4j.LoggerFactory;

/** Restore the separate player's presence on restart and use native death respawn destinations. */
public final class CompanionLife {
    private final BrainBridge bridge;
    private final Path file=Path.of("napar-runtime.json");
    private final String world=System.getenv("NAPAR_WORLD_ID");
    private JsonObject pending;
    private int delay,ticks;
    private boolean restoreHealth;
    private boolean parked;
    private JsonObject parkedSaved;
    private int idleWithoutOwner;
    private final int idleLogoutTicks=20*Math.max(1,Math.min(3600,Integer.parseInt(System.getenv().getOrDefault("NAPAR_IDLE_LOGOUT_SECONDS","120"))));
    public CompanionLife(BrainBridge bridge){this.bridge=bridge;}
    private JsonObject record(EntityPlayerMPFake p){
        JsonObject out=new JsonObject();out.addProperty("world",world);out.addProperty("dimension",p.level().dimension().identifier().toString());out.add("position",GameSensors.position(p.position()));
        out.addProperty("yaw",p.getYRot());out.addProperty("pitch",p.getXRot());out.addProperty("health",p.getHealth());out.addProperty("parked",parked);return out;
    }
    private void write(JsonObject out){
        try{Path temporary=file.resolveSibling(file.getFileName()+".tmp");Files.writeString(temporary,out.toString());Files.move(temporary,file,StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);}
        catch(Exception failure){LoggerFactory.getLogger("napar").warn("Cannot persist companion presence ({})",failure.getClass().getSimpleName());}
    }
    private void save(MinecraftServer server){var player=server.getPlayerList().getPlayerByName("Napar");if(player instanceof EntityPlayerMPFake fake && pending==null)write(record(fake));}
    public void register(){
        ServerLifecycleEvents.SERVER_STARTED.register(server->{
            if("false".equals(System.getenv("NAPAR_RESTORE_PLAYER")))return;
            try{if(Files.exists(file)){JsonObject saved=JsonParser.parseString(Files.readString(file)).getAsJsonObject();if(world!=null&&world.equals(saved.get("world").getAsString())){parked=saved.has("parked")&&saved.get("parked").getAsBoolean();if(parked)parkedSaved=saved;else{pending=saved;delay=40;restoreHealth=true;}}}}
            catch(Exception failure){LoggerFactory.getLogger("napar").warn("Ignoring invalid saved companion presence");}
        });
        ServerLifecycleEvents.SERVER_STOPPING.register(this::save);
        ServerPlayConnectionEvents.JOIN.register((handler,sender,server)->{
            if(!handler.player.getGameProfile().name().equals(System.getenv("NAPAR_OWNER_NAME")))return;
            idleWithoutOwner=0;
            if(parked&&parkedSaved!=null){pending=parkedSaved;parkedSaved=null;parked=false;delay=1;restoreHealth=true;}
        });
        ServerLivingEntityEvents.AFTER_DEATH.register((entity,source)->{
            if(!(entity instanceof EntityPlayerMPFake p)||!p.getGameProfile().name().equals("Napar"))return;
            bridge.stop(p.level().getServer());
            bridge.event("death","Погиб: "+p.getCombatTracker().getDeathMessage().getString()+"; место: "+p.level().dimension().identifier()+" "+p.blockPosition());
            var respawn=p.findRespawnPositionAndUseSpawnBlock(true,TeleportTransition.DO_NOTHING);
            pending=record(p);pending.addProperty("dimension",respawn.newLevel().dimension().identifier().toString());pending.add("position",GameSensors.position(respawn.position()));
            pending.addProperty("yaw",respawn.yRot());pending.addProperty("pitch",respawn.xRot());pending.addProperty("health",20);
            write(pending);delay=100;restoreHealth=false;
        });
        ServerTickEvents.END_SERVER_TICK.register(server->{
            var online=server.getPlayerList().getPlayerByName("Napar");
            boolean ownerPresent=server.getPlayerList().getPlayerByName(System.getenv().getOrDefault("NAPAR_OWNER_NAME",""))!=null;
            if(online instanceof EntityPlayerMPFake fake){
                if(parked){parked=false;parkedSaved=null;idleWithoutOwner=0;}
                if(ownerPresent||bridge.keepPresent()||bridge.workPending())idleWithoutOwner=0;
                else if(++idleWithoutOwner>=idleLogoutTicks&&pending==null&&fake.isAlive()){
                    parked=true;parkedSaved=record(fake);write(parkedSaved);bridge.stop(server);
                    fake.kill(Component.literal("No pending work; leaving after owner"));
                    idleWithoutOwner=0;return;
                }
            }else if(ownerPresent)idleWithoutOwner=0;
            if(++ticks%600==0)save(server);
            if(pending==null)return;
            if(--delay>0)return;
            var present=server.getPlayerList().getPlayerByName("Napar");
            if(present instanceof EntityPlayerMPFake fake){
                if(restoreHealth)fake.setHealth(Math.max(.5f,Math.min(fake.getHealth(),pending.get("health").getAsFloat())));
                pending=null;save(server);return;
            }
            if(EntityPlayerMPFake.isSpawningPlayer("Napar")){delay=20;return;}
            try{
                var point=pending.getAsJsonObject("position");Vec3 location=new Vec3(point.get("x").getAsDouble(),point.get("y").getAsDouble(),point.get("z").getAsDouble());
                if(!Double.isFinite(location.x)||!Double.isFinite(location.y)||!Double.isFinite(location.z)||Math.abs(location.x)>30_000_000||Math.abs(location.z)>30_000_000)throw new IllegalArgumentException();
                for(var level:server.getAllLevels())if(level.dimension().identifier().toString().equals(pending.get("dimension").getAsString())){
                    EntityPlayerMPFake.createFake("Napar",server,location,pending.get("yaw").getAsFloat(),pending.get("pitch").getAsFloat(),level.dimension(),GameType.SURVIVAL,false);delay=40;return;
                }
                pending=null;
            }catch(Exception failure){pending=null;LoggerFactory.getLogger("napar").warn("Companion restore rejected ({})",failure.getClass().getSimpleName());}
        });
    }
}

