package dev.napar;

import carpet.fakes.ServerPlayerInterface;
import carpet.helpers.EntityPlayerActionPack;
import carpet.patches.EntityPlayerMPFake;
import com.google.gson.*;
import java.util.*;
import java.util.function.Consumer;
import net.minecraft.core.*;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.*;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.BedBlock;
import net.minecraft.world.level.block.entity.AbstractFurnaceBlockEntity;
import net.minecraft.world.phys.*;

/** One cancellable physical job at a time. All methods run on the Minecraft server thread. */
public final class SurvivalActions {
    private final GroundNavigator navigator;
    private EntityPlayerMPFake player;
    private String job="idle",dimension,pickupItem;
    private BlockPos block,openedAt;
    private Entity target;
    private Entity followTarget;
    private boolean shieldCombat;
    private int lostFollowTicks,nextFollowRouteTick,lastFollowNotice=-1000;
    private Vec3 lastFollowSeen,followRouteTarget;
    private final ArrayDeque<Vec3> followTrail=new ArrayDeque<>();
    private long deadline;
    private int ticks,initialCount,initialFood;
    private Object originalBlock;
    private Consumer<JsonObject> completion;
    public SurvivalActions(GroundNavigator navigator){this.navigator=navigator;}
    public String activity(){return followTarget!=null?"following:"+followTarget.getName().getString():job;}
    public String followingName(){return followTarget==null?null:followTarget.getName().getString();}
    private static BlockPos pos(JsonObject a){return new BlockPos(a.get("x").getAsInt(),a.get("y").getAsInt(),a.get("z").getAsInt());}
    private static EntityPlayerActionPack pack(EntityPlayerMPFake p){return ((ServerPlayerInterface)p).getActionPack();}
    private static JsonObject data(String key,Object value){JsonObject out=new JsonObject();if(value instanceof JsonElement e)out.add(key,e);else if(value instanceof Boolean b)out.addProperty(key,b);else if(value instanceof Number n)out.addProperty(key,n);else out.addProperty(key,String.valueOf(value));return out;}
    private static int find(EntityPlayerMPFake p,String item){
        for(int i=0;i<36;i++){var stack=p.getInventory().getItem(i);if(!stack.isEmpty()&&BuiltInRegistries.ITEM.getKey(stack.getItem()).toString().equals(item))return i;}
        throw new IllegalArgumentException("Item unavailable in inventory: "+item);
    }
    private static void select(EntityPlayerMPFake p,String item){int slot=find(p,item);if(slot<9)p.getInventory().setSelectedSlot(slot);else p.getInventory().pickSlot(slot);}
    private static Entity entity(EntityPlayerMPFake p,String id){
        return p.level().getEntities(p,p.getBoundingBox().inflate(32)).stream().filter(e->(e.getUUID().toString().equals(id)||e.getName().getString().equals(id))&&p.hasLineOfSight(e)).findFirst().orElseThrow(()->new IllegalArgumentException("Target not visible within 32 blocks"));
    }
    public void cancel(){
        followTarget=null;followTrail.clear();lastFollowSeen=null;followRouteTarget=null;
        navigator.cancel();
        if(completion!=null)finish("cancelled","Physical action cancelled",new JsonObject());
    }
    public void interruptForReflex(){
        // A short survival response pauses following without forgetting the owner or trail.
        if(followTarget==null){cancel();return;}
        navigator.cancel();followRouteTarget=null;nextFollowRouteTick=0;
    }
    public void start(EntityPlayerMPFake p,String tool,JsonObject args,double seconds,Consumer<JsonObject> callback){
        // Read-only tools may inspect a running action without interrupting it.
        if(tool.equals("inspect")){
            try{
                String sensor=args.get("sensor").getAsString();JsonObject result;
                if(sensor.equals("container"))result=container(p,GameSensors.parsePosition(args.get("target").getAsString()));
                else if(sensor.equals("recipes"))result=SurvivalCrafting.recipes(p,args.get("target").isJsonNull()?"":args.get("target").getAsString());
                else result=GameSensors.inspect(p,args);
                callback.accept(result("succeeded","Observed on server thread",result));
            }catch(RuntimeException e){callback.accept(result("failed",e.getMessage(),new JsonObject()));}return;
        }
        cancel();player=p;completion=callback;job=tool;deadline=System.nanoTime()+(long)(seconds*1e9);ticks=0;dimension=p.level().dimension().identifier().toString();
        try{
            if(!p.isAlive())throw new IllegalArgumentException("Companion is dead");
            switch(tool){
                case "mine" -> {
                    block=pos(args);GameSensors.reachable(p,block);var state=p.level().getBlockState(block);originalBlock=state.getBlock();
                    if(state.isAir()||!state.getFluidState().isEmpty()||state.getDestroySpeed(p.level(),block)<0||state.hasBlockEntity())throw new IllegalArgumentException("Block is absent, fluid, unbreakable or a protected block entity");
                    if(block.equals(p.blockPosition().below()))throw new IllegalArgumentException("Refusing to mine the block supporting my feet");
                    for(Direction face:Direction.values())if(!p.level().getFluidState(block.relative(face)).isEmpty())throw new IllegalArgumentException("Adjacent fluid could flood the mining position");
                    if(p.level().getBlockState(block.above()).getBlock() instanceof net.minecraft.world.level.block.FallingBlock)throw new IllegalArgumentException("Falling block above target");
                    float best=p.getMainHandItem().getDestroySpeed(state);int bestSlot=-1;
                    for(int i=0;i<36;i++){var stack=p.getInventory().getItem(i);if(stack.isDamageableItem()&&stack.getMaxDamage()-stack.getDamageValue()<3)continue;
                        float speed=stack.getDestroySpeed(state);if(speed>best&&(!state.requiresCorrectToolForDrops()||stack.isCorrectToolForDrops(state))){best=speed;bestSlot=i;}}
                    if(bestSlot>=0){if(bestSlot<9)p.getInventory().setSelectedSlot(bestSlot);else p.getInventory().pickSlot(bestSlot);}
                    if(state.requiresCorrectToolForDrops()&&!p.getMainHandItem().isCorrectToolForDrops(state))throw new IllegalArgumentException("A correct tool is required for drops");
                    pack(p).lookAt(GameSensors.ray(p,block).getLocation());pack(p).start(EntityPlayerActionPack.ActionType.ATTACK,EntityPlayerActionPack.Action.continuous());
                }
                case "move_to" -> navigator.start(p,new Vec3(args.get("x").getAsDouble(),args.get("y").getAsDouble(),args.get("z").getAsDouble()),seconds,(status,detail)->finish(status,detail,new JsonObject()));
                case "follow_player" -> {target=entity(p,args.get("player").getAsString());if(!(target instanceof Player))throw new IllegalArgumentException("Target is not a visible player");followTarget=target;lostFollowTicks=0;nextFollowRouteTick=0;lastFollowSeen=target.position();followTrail.add(lastFollowSeen);deadline=Long.MAX_VALUE;finish("succeeded","Following mode established; continues locally until stop, another physical action, logout/dimension change or bridge loss",data("following",target.getName().getString()));}
                case "pickup" -> {target=entity(p,args.get("target").getAsString());if(!(target instanceof ItemEntity item))throw new IllegalArgumentException("Target is not an item drop");pickupItem=BuiltInRegistries.ITEM.getKey(item.getItem().getItem()).toString();initialCount=count(p,pickupItem);}
                case "attack" -> {target=entity(p,args.get("target").getAsString());if(target instanceof Player||!(target instanceof LivingEntity))throw new IllegalArgumentException("Combat tool accepts living non-player targets only");
                    shieldCombat=args.has("tactic")&&args.get("tactic").getAsString().equals("shield");
                    if(shieldCombat&&!p.getOffhandItem().is(net.minecraft.world.item.Items.SHIELD)){int source=find(p,"minecraft:shield");var previous=p.getOffhandItem();p.setItemInHand(InteractionHand.OFF_HAND,p.getInventory().getItem(source));p.getInventory().setItem(source,previous);}}
                case "eat" -> {
                    select(p,args.get("item").getAsString());if(!p.getMainHandItem().has(DataComponents.FOOD))throw new IllegalArgumentException("Selected item is not food");
                    if(!p.getFoodData().needsFood())throw new IllegalArgumentException("Already full");initialFood=p.getFoodData().getFoodLevel();initialCount=p.getMainHandItem().getCount();
                    p.gameMode.useItem(p,p.level(),p.getMainHandItem(),InteractionHand.MAIN_HAND);
                    if(!p.isUsingItem())throw new IllegalArgumentException("Food use did not start");
                }
                case "equip" -> {
                    String slot=args.get("slot").getAsString();String item=args.get("item").getAsString();
                    if(slot.equals("mainhand"))select(p,item);
                    else if(slot.equals("offhand")){
                        int source=find(p,item);var old=p.getOffhandItem();p.setItemInHand(InteractionHand.OFF_HAND,p.getInventory().getItem(source));p.getInventory().setItem(source,old);
                    }else{
                        select(p,item);var wearable=p.getMainHandItem().get(DataComponents.EQUIPPABLE);
                        if(wearable==null||!wearable.slot().getName().equals(slot))throw new IllegalArgumentException("Item does not fit requested equipment slot");
                        var action=p.gameMode.useItem(p,p.level(),p.getMainHandItem(),InteractionHand.MAIN_HAND);
                        if(!action.consumesAction())throw new IllegalArgumentException("Vanilla equipment rules refused the swap");
                    }
                    p.containerMenu.broadcastChanges();finish("succeeded","Equipment changed",data("inventory",GameSensors.inventory(p)));
                }
                case "drop" -> {
                    int source=find(p,args.get("item").getAsString()),amount=args.get("count").getAsInt();var stack=p.getInventory().getItem(source);
                    if(stack.getCount()<amount)throw new IllegalArgumentException("Insufficient item count in source stack");p.drop(p.getInventory().removeItem(source,amount),false);finish("succeeded","Dropped real inventory items",new JsonObject());
                }
                case "place" -> {
                    block=pos(args);GameSensors.reachable(p,block);select(p,args.get("item").getAsString());
                    Direction face=Direction.valueOf(args.get("face").getAsString().toUpperCase(Locale.ROOT));BlockPos destination=block.relative(face);
                    if(!p.level().getBlockState(destination).canBeReplaced())throw new IllegalArgumentException("Destination is occupied");
                    var before=p.level().getBlockState(destination);int count=p.getMainHandItem().getCount();
                    var hit=new BlockHitResult(Vec3.atCenterOf(block).add(Vec3.atLowerCornerOf(face.getUnitVec3i()).scale(.5)),face,block,false);
                    pack(p).lookAt(hit.getLocation());boolean sneaking=p.isShiftKeyDown();p.setShiftKeyDown(true);
                    try{p.gameMode.useItemOn(p,p.level(),p.getMainHandItem(),InteractionHand.MAIN_HAND,hit);}finally{p.setShiftKeyDown(sneaking);}
                    if(before.equals(p.level().getBlockState(destination))||p.getMainHandItem().getCount()>=count)throw new IllegalArgumentException("Vanilla placement did not change destination and consume an item");
                    finish("succeeded","Placed a block using an inventory item",GameSensors.block(p,destination));
                }
                case "use_block" -> {block=pos(args);GameSensors.reachable(p,block);var result=p.gameMode.useItemOn(p,p.level(),p.getMainHandItem(),InteractionHand.MAIN_HAND,GameSensors.ray(p,block));if(!result.consumesAction())throw new IllegalArgumentException("Block did not accept use");finish("succeeded","Used block; inspect to verify the desired outcome",GameSensors.block(p,block));}
                case "craft" -> finish("succeeded","Crafted with registered survival recipe",SurvivalCrafting.craft(p,args.get("recipe").getAsString(),args.get("times").getAsInt()));
                case "open_container" -> {block=pos(args);open(p,block);finish("succeeded","Opened container",container(p,block));}
                case "transfer" -> {block=pos(args);finish("succeeded","Transferred actual inventory items",transfer(p,block,args.get("direction").getAsString(),args.get("slot").getAsInt(),args.get("count").getAsInt(),args.get("item").getAsString()));}
                case "smelt" -> {block=pos(args);GameSensors.reachable(p,block);if(!(p.level().getBlockEntity(block) instanceof AbstractFurnaceBlockEntity))throw new IllegalArgumentException("Target is not a furnace");open(p,block);
                    String input=args.get("input").getAsString(),fuel=args.get("fuel").getAsString();int amount=args.get("count").getAsInt();
                    int source=find(p,input),fuelSource=find(p,fuel);if(source==fuelSource)throw new IllegalArgumentException("Use separate input and fuel items");
                    validatePut(p,0,amount,input);validatePut(p,1,1,fuel);
                    transfer(p,block,"put",0,amount,input);transfer(p,block,"put",1,1,fuel);
                    finish("succeeded","Furnace loaded; processing takes game time. Inspect output slot 2 and take it later; smelting is not yet complete",container(p,block));
                }
                case "sleep" -> {block=pos(args);GameSensors.reachable(p,block);if(!(p.level().getBlockState(block).getBlock() instanceof BedBlock))throw new IllegalArgumentException("Target is not a bed");
                    if(!p.level().dimension().equals(net.minecraft.world.level.Level.OVERWORLD))throw new IllegalArgumentException("Sleep tool currently supports overworld beds only");
                    var bed=p.level().getBlockState(block);if(bed.getValue(BedBlock.PART)==net.minecraft.world.level.block.state.properties.BedPart.FOOT)block=block.relative(bed.getValue(BedBlock.FACING));
                    GameSensors.reachable(p,block);
                    var result=p.startSleepInBed(block);if(result.left().isPresent())throw new IllegalArgumentException("Cannot sleep: "+result.left().get());finish("succeeded","Entered bed using normal sleep rules",data("sleeping",p.isSleeping()));}
                case "jump" -> pack(p).start(EntityPlayerActionPack.ActionType.JUMP,EntityPlayerActionPack.Action.once());
                case "sneak" -> {pack(p).setSneaking(args.get("enabled").getAsBoolean());finish("succeeded","Sneaking changed",new JsonObject());}
                default -> throw new IllegalArgumentException("Unsupported physical action");
            }
        }catch(RuntimeException e){finish("failed",e.getMessage(),new JsonObject());}
    }
    private static int count(EntityPlayerMPFake p,String id){int amount=0;for(int i=0;i<36;i++){var stack=p.getInventory().getItem(i);if(BuiltInRegistries.ITEM.getKey(stack.getItem()).toString().equals(id))amount+=stack.getCount();}return amount;}
    private void open(EntityPlayerMPFake p,BlockPos at){
        GameSensors.reachable(p,at);p.closeContainer();
        var provider=p.level().getBlockState(at).getMenuProvider(p.level(),at);if(provider==null||p.openMenu(provider).isEmpty()||p.containerMenu==p.inventoryMenu)throw new IllegalArgumentException("Container cannot be opened under vanilla rules");openedAt=at.immutable();
    }
    private void checkMenu(EntityPlayerMPFake p,BlockPos at){GameSensors.reachable(p,at);if(!at.equals(openedAt)||p.containerMenu==p.inventoryMenu||!p.containerMenu.stillValid(p))throw new IllegalArgumentException("Open this container first");}
    private JsonObject container(EntityPlayerMPFake p,BlockPos at){
        checkMenu(p,at);JsonArray slots=new JsonArray();for(var slot:p.containerMenu.slots)if(slot.container!=p.getInventory()){
            JsonObject entry=GameSensors.item(slot.getItem(),slot.index);entry.addProperty("may_take",slot.mayPickup(p));slots.add(entry);}
        JsonObject out=new JsonObject();out.add("slots",slots);out.add("position",GameSensors.position(Vec3.atLowerCornerOf(at)));return out;
    }
    private void validatePut(EntityPlayerMPFake p,int index,int amount,String id){
        if(index<0||index>=p.containerMenu.slots.size())throw new IllegalArgumentException("Invalid menu slot");var slot=p.containerMenu.slots.get(index);var stack=p.getInventory().getItem(find(p,id));var old=slot.getItem();
        if(slot.container==p.getInventory()||stack.getCount()<amount||!slot.mayPlace(stack)||(!old.isEmpty()&&!ItemStack.isSameItemSameComponents(stack,old))||old.getCount()+amount>slot.getMaxStackSize(stack))throw new IllegalArgumentException("Source count or destination slot rules refuse transfer");
    }
    private JsonObject transfer(EntityPlayerMPFake p,BlockPos at,String direction,int index,int amount,String id){
        checkMenu(p,at);if(amount<1||amount>64||index<0||index>=p.containerMenu.slots.size())throw new IllegalArgumentException("Invalid transfer");var slot=p.containerMenu.slots.get(index);
        if(slot.container==p.getInventory())throw new IllegalArgumentException("Choose a container menu slot");
        if(direction.equals("put")){
            validatePut(p,index,amount,id);int source=find(p,id);var stack=p.getInventory().getItem(source);var remainder=slot.safeInsert(stack.copyWithCount(amount));int moved=amount-remainder.getCount();stack.shrink(moved);if(moved!=amount)throw new IllegalArgumentException("Only "+moved+" items inserted; inspect updated inventory before retrying");
        }else{
            var stack=slot.getItem();if(!BuiltInRegistries.ITEM.getKey(stack.getItem()).toString().equals(id)||stack.getCount()<amount||!slot.mayPickup(p))throw new IllegalArgumentException("Source slot changed or cannot be taken");
            List<ItemStack> staged=new ArrayList<>();for(int i=0;i<36;i++)staged.add(p.getInventory().getItem(i).copy());if(!SurvivalCrafting.insert(staged,stack.copyWithCount(amount)))throw new IllegalArgumentException("Inventory full");
            var taken=slot.safeTake(amount,amount,p);int moved=taken.getCount();p.getInventory().placeItemBackInInventory(taken);if(moved!=amount)throw new IllegalArgumentException("Only "+moved+" items taken; inspect updated inventory before retrying");
        }
        p.getInventory().setChanged();p.containerMenu.broadcastChanges();return container(p,at);
    }
    public void tick(){
        if(followTarget!=null){tickFollow();return;}
        if(completion==null)return;
        try{
            ticks++;
            if(!player.isAlive()||player.isRemoved()||!dimension.equals(player.level().dimension().identifier().toString())){finish("failed","Companion unavailable or changed dimension",new JsonObject());return;}
            if(System.nanoTime()>=deadline){finish("failed","Physical action deadline exceeded",new JsonObject());return;}
            switch(job){
                case "jump" -> {if(ticks>=2)finish("succeeded","Jump control executed",data("on_ground",player.onGround()));}
                case "mine" -> {
                    if(player.level().getBlockState(block).getBlock()!=originalBlock){finish("succeeded","Target block changed after mining; drops may still need pickup",GameSensors.block(player,block));return;}
                    GameSensors.reachable(player,block);pack(player).lookAt(GameSensors.ray(player,block).getLocation());
                    var hand=player.getMainHandItem();if(hand.isDamageableItem()&&hand.getMaxDamage()-hand.getDamageValue()<2)finish("failed","Stopped to preserve nearly broken tool",new JsonObject());
                }
                case "eat" -> {if(!player.isUsingItem()&&ticks>2){if(player.getFoodData().getFoodLevel()>initialFood)finish("succeeded","Finished eating",data("food",player.getFoodData().getFoodLevel()));else finish("failed","Eating interrupted",new JsonObject());}}
                case "attack" -> {
                    if(!target.isAlive()){finish("succeeded","Target is dead",data("target",target.getUUID()));return;}
                    if(target.isRemoved()||!player.hasLineOfSight(target)){finish("failed","Target lost; combat stopped",new JsonObject());return;}
                    if(player.getHealth()<=6){finish("failed","Health low; combat stopped for replanning",new JsonObject());return;}
                    if(player.distanceTo(target)>2.7){approach(target);}else{navigator.cancel();pack(player).lookAt(target.getEyePosition());if(player.getAttackStrengthScale(0)>=.95f){player.releaseUsingItem();player.attack(target);player.swing(InteractionHand.MAIN_HAND);}}
                    if(shieldCombat&&player.getOffhandItem().is(net.minecraft.world.item.Items.SHIELD)&&!player.isUsingItem())player.gameMode.useItem(player,player.level(),player.getOffhandItem(),InteractionHand.OFF_HAND);
                }
                case "pickup" -> {
                    if(target instanceof ItemEntity item){String id=pickupItem;if(count(player,id)>initialCount){finish("succeeded","Inventory count increased after pickup",data("item",id));return;}
                        if(item.isRemoved()){finish("failed","Drop disappeared without verified inventory gain",new JsonObject());return;}if(player.distanceTo(item)>.8)approach(item);}
                }
            }
        }catch(RuntimeException e){finish("failed",e.getMessage(),new JsonObject());}
    }
    private void tickFollow(){
        ticks++;
        if(!player.isAlive()||followTarget.isRemoved()||!followTarget.isAlive()||player.level()!=followTarget.level()){
            cancel();return;
        }
        boolean visible=player.distanceTo(followTarget)<=32&&player.hasLineOfSight(followTarget);
        if(visible){
            lostFollowTicks=0;
            // Ignore the middle of a jump; it is not a walkable destination.
            if(followTarget.onGround()||followTarget.isInWater()){
                Vec3 seen=followTarget.position();
                if(lastFollowSeen==null||seen.distanceToSqr(lastFollowSeen)>1.4*1.4){
                    lastFollowSeen=seen;followTrail.addLast(seen);
                    while(followTrail.size()>64)followTrail.removeFirst();
                }
            }
            if(player.distanceTo(followTarget)<2.5){
                navigator.cancel();followRouteTarget=null;followTrail.clear();
                if(lastFollowSeen!=null)followTrail.add(lastFollowSeen);
                pack(player).lookAt(followTarget.getEyePosition());return;
            }
        }else lostFollowTicks++;
        while(followTrail.size()>1&&player.position().distanceTo(followTrail.peekFirst())<1.6)followTrail.removeFirst();
        if(navigator.active())pack(player).setSprinting(visible&&player.distanceTo(followTarget)>6&&player.getFoodData().getFoodLevel()>6&&player.onGround()&&!player.isInWater());
        if(ticks<nextFollowRouteTick)return;
        // Follow a recent visible point. Behind a corner, use the recorded trail instead.
        Vec3 point=visible?lastFollowSeen:followTrail.peekFirst();
        if(point==null||player.position().distanceTo(point)<1.2){
            navigator.cancel();followRouteTarget=null;nextFollowRouteTick=ticks+10;
            if(lostFollowTicks>200&&ticks-lastFollowNotice>600){
                lastFollowNotice=ticks;
                player.level().getServer().getPlayerList().broadcastSystemMessage(net.minecraft.network.chat.Component.literal("<Napar> Потерял тебя из виду. Жду здесь, подойди поближе."),false);
            }
            return;
        }
        if(navigator.active()&&followRouteTarget!=null&&point.distanceToSqr(followRouteTarget)<4){
            nextFollowRouteTick=ticks+5;return;
        }
        double distance=player.position().distanceTo(point);
        if(distance>24)point=player.position().add(point.subtract(player.position()).normalize().scale(24));
        followRouteTarget=point;nextFollowRouteTick=ticks+10;
        navigator.start(player,point,8,(status,detail)->{
            if(!status.equals("cancelled"))followRouteTarget=null;
            if(status.equals("failed"))nextFollowRouteTick=ticks+20;
        });
    }
    private void approach(Entity entity){
        if(ticks%20!=1&&navigator.active())return;
        var at=entity.blockPosition();Vec3 next=new Vec3(at.getX()+.5,at.getY(),at.getZ()+.5);
        navigator.start(player,next,followTarget!=null?8:Math.min(8,(deadline-System.nanoTime())/1e9),(status,detail)->{if(status.equals("failed")){if(followTarget!=null){nextFollowRouteTick=ticks+20;}else finish("failed","Approach failed: "+detail,new JsonObject());}});
    }
    private static JsonObject result(String status,String detail,JsonObject data){JsonObject out=new JsonObject();out.addProperty("status",status);out.addProperty("detail",detail==null?"Action rejected":detail.substring(0,Math.min(1000,detail.length())));out.add("data",data);return out;}
    private void finish(String status,String detail,JsonObject data){
        if(completion==null)return;var callback=completion;String previous=job;completion=null;job="idle";navigator.cancel();if(!previous.equals("sneak"))pack(player).stopAll();player.releaseUsingItem();callback.accept(result(status,detail,data));
    }
}
