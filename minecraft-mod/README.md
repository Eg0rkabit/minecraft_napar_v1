# NAPAR server body 0.2

Minecraft 26.2 / Java 25 / Fabric Loader 0.19.5 / Fabric API 0.161.0+26.2 /
Carpet 26.2+v260616. Run bootstrap.ps1, then gradlew build.

GameSensors owns bounded observation. GroundNavigator uses collision surfaces and
normal Carpet movement controls. SurvivalActions serializes cancellable physical
jobs, including mining, equipment, food, melee/shield combat and containers.
SurvivalCrafting validates registered recipes and stages a complete inventory
transaction before committing. SurvivalReflexes provides small local responses;
CompanionLife restores presence and follows native respawn destinations.
BrainBridge does HTTP off-thread and accesses the world on the server thread.

Set NAPAR_BRIDGE_TOKEN, NAPAR_WORLD_ID and NAPAR_OWNER_NAME. NAPAR_BRIDGE_URL defaults
to http://127.0.0.1:8000; use a separate port and world ID for a test brain.
NAPAR_RESTORE_PLAYER=false disables saved presence on a disposable test server.
Production launchers are in deploy/; runtime presence is saved in napar-runtime.json.

Commands: /napar spawn, /napar status, /napar stop, /napar ask <message>.
Owner-addressed chat also works. /napar step <1..20> is a bring-up diagnostic.
No human player's controls are intercepted. The companion remains in survival.

See the root README for tool semantics, navigation bounds, unsupported dynamic
recipes, public-web limits, budget, tests and deployment/rollback instructions.
