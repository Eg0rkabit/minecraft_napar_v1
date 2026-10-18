package dev.napar;

import carpet.fakes.ServerPlayerInterface;
import carpet.helpers.EntityPlayerActionPack;
import carpet.patches.EntityPlayerMPFake;
import com.google.gson.JsonObject;
import net.minecraft.core.BlockPos;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.monster.Creeper;
import net.minecraft.world.phys.Vec3;

/** Cheap local reflexes; strategic decisions and long-term plans remain in the brain. */
public final class SurvivalReflexes {
    private final GroundNavigator navigator;
    private final SurvivalActions actions;
    private final BrainBridge bridge;
    private int ticks,lastIncident=-1000,escapeUntil;
    private boolean reflexJump;
    public SurvivalReflexes(GroundNavigator n,SurvivalActions a,BrainBridge b){navigator=n;actions=a;bridge=b;}
    public void tick(EntityPlayerMPFake p){
        ticks++;if(!p.isAlive())return;
        boolean lowAir=p.isInWater()&&p.getAirSupply()<80;
        boolean lava=p.isInLava();
        Creeper creeper=p.level().getEntitiesOfClass(Creeper.class,p.getBoundingBox().inflate(5),e->p.hasLineOfSight(e)&&(e.getSwellDir()>0||e.isIgnited())).stream().findFirst().orElse(null);
        if((lowAir||lava||creeper!=null)&&ticks-lastIncident>=100){
            lastIncident=ticks;actions.cancel();escapeUntil=ticks+60;
            bridge.event("danger",lowAir?"Мало воздуха, всплываю":lava?"Попал в лаву, ищу берег":"Рядом взрывающийся крипер, отступаю");
            Vec3 origin=creeper!=null?creeper.position():p.position();BlockPos best=null;double score=-Double.MAX_VALUE;
            for(BlockPos at:BlockPos.betweenClosed(p.blockPosition().offset(-5,-2,-5),p.blockPosition().offset(5,2,5))){
                if(!p.level().hasChunkAt(at)||!p.level().getBlockState(at).isAir()||!p.level().getBlockState(at.above()).isAir())continue;
                var support=p.level().getBlockState(at.below());String id=BuiltInRegistries.BLOCK.getKey(support.getBlock()).toString();
                if(!support.isCollisionShapeFullBlock(p.level(),at.below())||id.contains("magma")||id.contains("cactus")||id.contains("campfire"))continue;
                double value=creeper!=null?Vec3.atCenterOf(at).distanceToSqr(origin)-p.position().distanceToSqr(Vec3.atCenterOf(at))*.4:-p.position().distanceToSqr(Vec3.atCenterOf(at));
                if(value>score){score=value;best=at.immutable();}
            }
            if(best!=null)navigator.start(p,new Vec3(best.getX()+.5,best.getY(),best.getZ()+.5),3,(s,d)->{});
        }
        if(ticks<escapeUntil&&(lowAir||lava)){((ServerPlayerInterface)p).getActionPack().start(EntityPlayerActionPack.ActionType.JUMP,EntityPlayerActionPack.Action.continuous());reflexJump=true;}
        else if(reflexJump){((ServerPlayerInterface)p).getActionPack().start(EntityPlayerActionPack.ActionType.JUMP,null);reflexJump=false;}
        if(ticks%20==0&&p.getFoodData().getFoodLevel()<=12&&(actions.activity().equals("idle")||actions.followingName()!=null)&&!lava&&creeper==null){
            for(int slot=0;slot<36;slot++){
                var food=p.getInventory().getItem(slot);if(!food.has(DataComponents.FOOD)||food.has(DataComponents.SUSPICIOUS_STEW_EFFECTS)||food.is(net.minecraft.world.item.Items.ROTTEN_FLESH)||food.is(net.minecraft.world.item.Items.SPIDER_EYE)||food.is(net.minecraft.world.item.Items.PUFFERFISH)||food.is(net.minecraft.world.item.Items.POISONOUS_POTATO)||food.is(net.minecraft.world.item.Items.CHORUS_FRUIT)||food.is(net.minecraft.world.item.Items.GOLDEN_APPLE)||food.is(net.minecraft.world.item.Items.ENCHANTED_GOLDEN_APPLE))continue;
                String follow=actions.followingName();JsonObject args=new JsonObject();args.addProperty("item",BuiltInRegistries.ITEM.getKey(food.getItem()).toString());
                actions.start(p,"eat",args,5,result->{if(follow!=null&&result.get("status").getAsString().equals("succeeded")){JsonObject request=new JsonObject();request.addProperty("player",follow);actions.start(p,"follow_player",request,10,ignored->{});}});break;
            }
        }
    }
}
