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
    private final GroundNavigator navigator = new GroundNavigator();
    private final SurvivalActions actions;
    private final BrainBridge bridge;
    private int ticks,lastIncident=-1000,escapeUntil;
    private float previousHealth=20;
    private EntityPlayerMPFake player;
    private boolean reflexJump;
    public SurvivalReflexes(SurvivalActions a,BrainBridge b){actions=a;bridge=b;}
    public boolean active(){return navigator.active()||ticks<escapeUntil;}
    public void cancel(){navigator.cancel();escapeUntil=0;if(reflexJump&&player!=null)((ServerPlayerInterface)player).getActionPack().start(EntityPlayerActionPack.ActionType.JUMP,null);reflexJump=false;}
    public void tick(EntityPlayerMPFake p){
        ticks++;player=p;if(!p.isAlive()){cancel();previousHealth=20;return;}
        navigator.tick();
        boolean hurt=p.getHealth()<previousHealth-.01f;previousHealth=p.getHealth();
        var attacker=p.getLastAttacker();
        boolean threatened=attacker!=null&&attacker.isAlive()&&p.hasLineOfSight(attacker)&&p.distanceToSqr(attacker)<64;
        boolean critical=p.getHealth()<=6&&threatened;
        boolean lowAir=p.isInWater()&&p.getAirSupply()<80;
        boolean lava=p.isInLava();
        Creeper creeper=p.level().getEntitiesOfClass(Creeper.class,p.getBoundingBox().inflate(5),e->p.hasLineOfSight(e)&&(e.getSwellDir()>0||e.isIgnited())).stream().findFirst().orElse(null);
        if((lowAir||lava||creeper!=null||critical)&&ticks-lastIncident>=100){
            lastIncident=ticks;actions.cancel();escapeUntil=ticks+60;
            bridge.event("danger",lowAir?"Мало воздуха, всплываю":lava?"Попал в лаву, ищу берег":creeper!=null?"Рядом взрывающийся крипер, отступаю":"Критическое здоровье и противник рядом, отступаю");
            Vec3 origin=creeper!=null?creeper.position():critical?attacker.position():p.position();BlockPos best=null;double score=-Double.MAX_VALUE;
            for(BlockPos at:BlockPos.betweenClosed(p.blockPosition().offset(-5,-2,-5),p.blockPosition().offset(5,2,5))){
                if(!p.level().hasChunkAt(at)||!p.level().getBlockState(at).isAir()||!p.level().getBlockState(at.above()).isAir())continue;
                var support=p.level().getBlockState(at.below());String id=BuiltInRegistries.BLOCK.getKey(support.getBlock()).toString();
                if(!support.isCollisionShapeFullBlock(p.level(),at.below())||id.contains("magma")||id.contains("cactus")||id.contains("campfire"))continue;
                double value=(creeper!=null||critical)?Vec3.atCenterOf(at).distanceToSqr(origin)-p.position().distanceToSqr(Vec3.atCenterOf(at))*.4:-p.position().distanceToSqr(Vec3.atCenterOf(at));
                if(value>score){score=value;best=at.immutable();}
            }
            if(best!=null)navigator.start(p,new Vec3(best.getX()+.5,best.getY(),best.getZ()+.5),3,(s,d)->{});
        }
        if(hurt&&!active()&&!actions.activity().equals("attack")&&!actions.activity().equals("eat")&&ticks-lastIncident>=100){
            lastIncident=ticks;actions.cancel();escapeUntil=ticks+20;
            bridge.event("danger",threatened?"Получил урон от видимого противника; нужно оценить обстановку":"Получил урон; нужно проверить причину");
        }
        if(ticks<escapeUntil&&(lowAir||lava)){((ServerPlayerInterface)p).getActionPack().start(EntityPlayerActionPack.ActionType.JUMP,EntityPlayerActionPack.Action.continuous());reflexJump=true;}
        else if(reflexJump){((ServerPlayerInterface)p).getActionPack().start(EntityPlayerActionPack.ActionType.JUMP,null);reflexJump=false;}
        if(!active()&&ticks%20==0&&p.getFoodData().getFoodLevel()<=12&&(actions.activity().equals("idle")||actions.followingName()!=null)&&!lava&&creeper==null){
            for(int slot=0;slot<36;slot++){
                var food=p.getInventory().getItem(slot);if(!food.has(DataComponents.FOOD)||food.has(DataComponents.SUSPICIOUS_STEW_EFFECTS)||food.is(net.minecraft.world.item.Items.ROTTEN_FLESH)||food.is(net.minecraft.world.item.Items.SPIDER_EYE)||food.is(net.minecraft.world.item.Items.PUFFERFISH)||food.is(net.minecraft.world.item.Items.POISONOUS_POTATO)||food.is(net.minecraft.world.item.Items.CHORUS_FRUIT)||food.is(net.minecraft.world.item.Items.GOLDEN_APPLE)||food.is(net.minecraft.world.item.Items.ENCHANTED_GOLDEN_APPLE))continue;
                String follow=actions.followingName();JsonObject args=new JsonObject();args.addProperty("item",BuiltInRegistries.ITEM.getKey(food.getItem()).toString());
                actions.start(p,"eat",args,5,result->{if(follow!=null&&result.get("status").getAsString().equals("succeeded")){JsonObject request=new JsonObject();request.addProperty("player",follow);actions.start(p,"follow_player",request,10,ignored->{});}});break;
            }
        }
    }
}

