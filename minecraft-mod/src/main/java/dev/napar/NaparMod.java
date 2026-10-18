package dev.napar;

import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** Server-only entry point; networking must never block the server tick. */
public final class NaparMod implements ModInitializer {
    private static final Logger LOG = LoggerFactory.getLogger("napar");

    @Override
    public void onInitialize() {
        var navigator = new GroundNavigator();
        var bridge = new BrainBridge(navigator);
        new CompanionController(navigator, bridge).register();
        bridge.register();
        new CompanionLife(bridge).register();
        ServerLifecycleEvents.SERVER_STARTED.register(server ->
            LOG.info("Napar runtime loaded. Use /napar status to inspect the companion."));
        ServerLifecycleEvents.SERVER_STOPPING.register(server ->
            LOG.info("Napar runtime stopping."));
    }
}
