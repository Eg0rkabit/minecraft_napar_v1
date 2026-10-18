package dev.napar;

import carpet.fakes.ServerPlayerInterface;
import carpet.patches.EntityPlayerMPFake;
import com.mojang.brigadier.arguments.IntegerArgumentType;
import com.mojang.brigadier.arguments.StringArgumentType;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.fabricmc.fabric.api.message.v1.ServerMessageEvents;
import net.minecraft.core.BlockPos;
import net.minecraft.world.phys.Vec3;
import java.util.Locale;
import java.util.UUID;
import net.minecraft.commands.Commands;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.GameType;

/** Bounded manual bring-up controls. Never takes control of a human player. */
public final class CompanionController {
    private static final String NAME = "Napar";
    private int remainingTicks;
    private UUID arrivingOwner;
    private int arrivalTicks;
    private final GroundNavigator navigator;
    private final BrainBridge bridge;
    public CompanionController(GroundNavigator navigator, BrainBridge bridge) { this.navigator = navigator; this.bridge = bridge; }

    private EntityPlayerMPFake companion(MinecraftServer server) {
        ServerPlayer player = server.getPlayerList().getPlayerByName(NAME);
        return player instanceof EntityPlayerMPFake fake ? fake : null;
    }

    private void stop(MinecraftServer server) {
        bridge.stop(server);
        remainingTicks = 0;
        var player = companion(server);
        if (player != null) ((ServerPlayerInterface) player).getActionPack().stopAll();
    }

    public void register() {
        ServerPlayConnectionEvents.JOIN.register((handler, sender, server) -> {
            var player = handler.player;
            if (player instanceof EntityPlayerMPFake ||
                !player.getGameProfile().name().equals(System.getenv("NAPAR_OWNER_NAME"))) return;
            arrivingOwner = player.getUUID();
            arrivalTicks = 40;
            player.sendSystemMessage(Component.literal("NAPAR: напиши «Напар, привет» или /napar ask <сообщение>. Остановка: /napar stop."));
        });
        ServerMessageEvents.CHAT_MESSAGE.register((message, sender, params) -> {
            if (sender instanceof EntityPlayerMPFake ||
                !sender.getGameProfile().name().equals(System.getenv("NAPAR_OWNER_NAME"))) return;
            String text = message.signedContent().strip();
            String lower = text.toLowerCase(Locale.ROOT);
            int prefix = lower.startsWith("напар") ? 5 : lower.startsWith("napar") ? 5 : 0;
            if (prefix == 0 || (text.length() > prefix && !" ,:".contains(text.substring(prefix,prefix+1)))) return;
            String request = text.substring(prefix).replaceFirst("^[ ,:]+", "").strip();
            if (request.isBlank()) return;
            sender.level().getServer().execute(() -> {
                if (request.equalsIgnoreCase("стоп") || request.equalsIgnoreCase("stop")) stop(sender.level().getServer());
                if (!bridge.ask(sender.getGameProfile().name(), request))
                    sender.sendSystemMessage(Component.literal("NAPAR ещё подключается. Подожди пару секунд и повтори."));
            });
        });
        CommandRegistrationCallback.EVENT.register((dispatcher, registry, environment) ->
            dispatcher.register(Commands.literal("napar")
                .requires(source -> Commands.LEVEL_GAMEMASTERS.check(source.permissions()) ||
                    (source.getEntity() instanceof ServerPlayer p && p.getGameProfile().name().equals(System.getenv("NAPAR_OWNER_NAME"))))
                .then(Commands.literal("ask").then(Commands.argument("message",StringArgumentType.greedyString()).executes(context -> {
                    var sender = context.getSource().getPlayerOrException();
                    boolean queued = bridge.ask(sender.getGameProfile().name(), StringArgumentType.getString(context,"message"));
                    context.getSource().sendSuccess(() -> Component.literal(queued ? "Сообщение принято." : "Мозг недоступен или владелец не настроен."), false);
                    return queued ? 1 : 0;
                })))
                .then(Commands.literal("spawn").executes(context -> {
                    var source = context.getSource();
                    if (source.getServer().getPlayerList().getPlayerByName(NAME) != null) {
                        source.sendFailure(Component.literal("Napar already exists; no player was replaced."));
                        return 0;
                    }
                    boolean requested = EntityPlayerMPFake.createFake(NAME, source.getServer(),
                        source.getPosition(), 0, 0, source.getLevel().dimension(), GameType.SURVIVAL, false);
                    source.sendSuccess(() -> Component.literal(requested
                        ? "Spawn requested. Use /napar status to verify completion."
                        : "Spawn rejected by Carpet profile/settings checks."), false);
                    return requested ? 1 : 0;
                }))
                .then(Commands.literal("status").executes(context -> {
                    boolean present = companion(context.getSource().getServer()) != null;
                    context.getSource().sendSuccess(() -> Component.literal(
                        present ? "Napar is present (server FakePlayer)." : "Napar is not present."), false);
                    return present ? 1 : 0;
                }))
                .then(Commands.literal("stop").executes(context -> {
                    stop(context.getSource().getServer());
                    bridge.ask(System.getenv("NAPAR_OWNER_NAME"), "стоп");
                    return 1;
                }))
                .then(Commands.literal("step").then(Commands.argument("ticks", IntegerArgumentType.integer(1, 20))
                    .executes(context -> {
                        var player = companion(context.getSource().getServer());
                        if (player == null) return 0;
                        stop(context.getSource().getServer());
                        remainingTicks = IntegerArgumentType.getInteger(context, "ticks");
                        ((ServerPlayerInterface) player).getActionPack().setForward(1);
                        return 1;
                    })))));
        ServerTickEvents.END_SERVER_TICK.register(server -> {
            if (remainingTicks > 0 && --remainingTicks == 0) stop(server);
            if (arrivingOwner != null && --arrivalTicks <= 0) {
                var owner = server.getPlayerList().getPlayer(arrivingOwner);
                arrivingOwner = null;
                if (owner == null || server.getPlayerList().getPlayerByName(NAME) != null) return;
                BlockPos origin = owner.blockPosition();
                for (int radius=1; radius<=3; radius++) for (int dx=-radius; dx<=radius; dx++)
                    for (int dz=-radius; dz<=radius; dz++) {
                        if (Math.max(Math.abs(dx),Math.abs(dz)) != radius) continue;
                        BlockPos at = origin.offset(dx,0,dz);
                        var level = owner.level();
                        if (!level.hasChunkAt(at) || !level.getBlockState(at).isAir() || !level.getBlockState(at.above()).isAir()) continue;
                        var below = at.below();
                        var support = level.getBlockState(below);
                        String block = net.minecraft.core.registries.BuiltInRegistries.BLOCK.getKey(support.getBlock()).toString();
                        if (!support.isCollisionShapeFullBlock(level,below) || block.contains("magma") || block.contains("cactus") || block.contains("campfire")) continue;
                        EntityPlayerMPFake.createFake(NAME, server, new Vec3(at.getX()+.5,at.getY(),at.getZ()+.5),
                            0,0,level.dimension(),GameType.SURVIVAL,false);
                        return;
                    }
                owner.sendSystemMessage(Component.literal("NAPAR: рядом нет безопасного места. Встань на ровную сухую землю и введи /napar spawn."));
            }
        });
        ServerLifecycleEvents.SERVER_STOPPING.register(this::stop);
    }
}
