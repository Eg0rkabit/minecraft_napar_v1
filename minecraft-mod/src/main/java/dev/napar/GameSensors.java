package dev.napar;

import carpet.patches.EntityPlayerMPFake;
import com.google.gson.*;
import java.util.*;
import net.minecraft.core.*;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.*;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.phys.*;

/** Bounded, loaded-world perception. Hidden ore and unopened inventories are never scanned. */
public final class GameSensors {
    public static JsonObject position(Vec3 v) {
        JsonObject out=new JsonObject(); out.addProperty("x",v.x); out.addProperty("y",v.y); out.addProperty("z",v.z); return out;
    }
    public static JsonObject item(ItemStack stack,int slot) {
        JsonObject out=new JsonObject(); out.addProperty("item",BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());
        out.addProperty("count",stack.getCount()); out.addProperty("slot",slot);
        if(stack.isDamageableItem()) { out.addProperty("durability",stack.getMaxDamage()-stack.getDamageValue()); out.addProperty("max_durability",stack.getMaxDamage()); }
        out.addProperty("enchanted",stack.isEnchanted()); return out;
    }
    public static JsonArray inventory(EntityPlayerMPFake p) {
        JsonArray out=new JsonArray();
        for(int i=0;i<p.getInventory().getContainerSize();i++) if(!p.getInventory().getItem(i).isEmpty()) out.add(item(p.getInventory().getItem(i),i));
        return out;
    }
    public static JsonObject entity(EntityPlayerMPFake p,Entity e) {
        JsonObject out=new JsonObject(); out.addProperty("id",e.getUUID().toString());
        out.addProperty("kind",BuiltInRegistries.ENTITY_TYPE.getKey(e.getType()).toString());
        String name=e.getName().getString(); out.addProperty("name",name.substring(0,Math.min(80,name.length())));
        out.add("position",position(e.position())); out.addProperty("visible",p.hasLineOfSight(e)); out.addProperty("distance",p.distanceTo(e));
        if(e instanceof LivingEntity living) out.addProperty("health",living.getHealth());
        out.addProperty("targeting_me",e instanceof Mob mob && mob.getTarget()==p); return out;
    }
    public static BlockHitResult ray(EntityPlayerMPFake p,BlockPos at) {
        var fluids=p.level().getFluidState(at).isEmpty()?ClipContext.Fluid.NONE:ClipContext.Fluid.ANY;
        return p.level().clip(new ClipContext(p.getEyePosition(),Vec3.atCenterOf(at),ClipContext.Block.OUTLINE,fluids,p));
    }
    public static boolean visible(EntityPlayerMPFake p,BlockPos at,double range) {
        return p.level().hasChunkAt(at) && p.getEyePosition().distanceTo(Vec3.atCenterOf(at))<=range
            && ray(p,at).getBlockPos().equals(at) && ray(p,at).getType()==HitResult.Type.BLOCK;
    }
    public static void reachable(EntityPlayerMPFake p,BlockPos at) {
        if(!visible(p,at,4.5)) throw new IllegalArgumentException("Block must be visible and within 4.5 blocks; move closer first");
    }
    public static BlockPos parsePosition(String value) {
        String[] parts=value.split(","); if(parts.length!=3) throw new IllegalArgumentException("Target must be x,y,z");
        return new BlockPos(Integer.parseInt(parts[0].strip()),Integer.parseInt(parts[1].strip()),Integer.parseInt(parts[2].strip()));
    }
    public static JsonObject block(EntityPlayerMPFake p,BlockPos at) {
        JsonObject out=new JsonObject(); out.add("position",position(Vec3.atLowerCornerOf(at)));
        var state=p.level().getBlockState(at); out.addProperty("block",BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString());
        out.addProperty("state",state.toString()); out.addProperty("break_progress_per_tick",state.getDestroyProgress(p,p.level(),at));
        out.addProperty("fluid",BuiltInRegistries.FLUID.getKey(state.getFluidState().getType()).toString());out.addProperty("replaceable",state.canBeReplaced());
        out.addProperty("correct_tool",p.getMainHandItem().isCorrectToolForDrops(state));
        out.addProperty("has_block_entity",state.hasBlockEntity()); return out;
    }
    public static JsonObject inspect(EntityPlayerMPFake p,JsonObject args) {
        String sensor=args.get("sensor").getAsString();
        String target=args.has("target") && !args.get("target").isJsonNull()?args.get("target").getAsString():"";
        JsonObject out=new JsonObject();
        switch(sensor) {
            case "inventory" -> out.add("inventory",inventory(p));
            case "navigation" -> { out.addProperty("range",32); out.addProperty("terrain","loaded collision surfaces including slabs/stairs, one-block jumps, drops up to two blocks and surface water; destination y may adjust by at most 0.7 to the actual surface; no digging or placement by navigation"); out.add("position",position(p.position())); }
            case "entity" -> {
                Entity found=p.level().getEntities(p,p.getBoundingBox().inflate(24)).stream()
                    .filter(e->(e.getUUID().toString().equals(target)||e.getName().getString().equals(target))&&p.hasLineOfSight(e)).findFirst().orElseThrow(()->new IllegalArgumentException("Entity not visible within 24 blocks"));
                out.add("entity",entity(p,found));
            }
            case "block" -> { BlockPos at=parsePosition(target); if(!visible(p,at,24)) throw new IllegalArgumentException("Block not visible within 24 blocks"); out.add("block",block(p,at)); }
            case "area" -> {
                int radius=Math.min(12,args.get("radius").getAsInt()); JsonArray blocks=new JsonArray();
                List<BlockPos> candidates=new ArrayList<>(); BlockPos origin=p.blockPosition();
                for(BlockPos at:BlockPos.betweenClosed(origin.offset(-radius,-Math.min(4,radius),-radius),origin.offset(radius,Math.min(6,radius),radius))) {
                    if(!p.level().hasChunkAt(at)) continue;
                    var state=p.level().getBlockState(at); if(state.isAir()) continue;
                    String id=BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString(); if(!target.isEmpty()&&!id.contains(target)) continue;
                    boolean exposed=false; for(Direction face:Direction.values()) if(p.level().getBlockState(at.relative(face)).isAir()) { exposed=true; break; }
                    if(exposed) candidates.add(at.immutable());
                }
                candidates.sort(Comparator.comparingDouble(at->at.distSqr(origin)));
                int rays=0;for(BlockPos at:candidates) { if(blocks.size()>=96||++rays>512) break; if(visible(p,at,24)) blocks.add(block(p,at)); }
                out.add("blocks",blocks); out.addProperty("radius",radius); out.addProperty("truncated",rays>512||candidates.size()>96); out.addProperty("visibility","line of sight; no hidden blocks; at most 512 rays");
            }
            default -> throw new IllegalArgumentException("Unknown sensor");
        }
        return out;
    }
    public static JsonObject snapshot(EntityPlayerMPFake p) {
        JsonObject out=new JsonObject(); out.add("position",position(p.position())); out.addProperty("dimension",p.level().dimension().identifier().toString());
        out.addProperty("health",p.getHealth()); out.addProperty("food",p.getFoodData().getFoodLevel()); out.add("inventory",inventory(p));
        JsonArray entities=new JsonArray(),dangers=new JsonArray();
        for(Entity e:p.level().getEntities(p,p.getBoundingBox().inflate(16))) {
            if(entities.size()>=64) break; if(!p.hasLineOfSight(e)) continue; entities.add(entity(p,e));
            if(e instanceof Mob mob && mob.getTarget()==p && dangers.size()<12) dangers.add("targeted_by:"+e.getUUID());
        }
        if(p.isInLava()) dangers.add("lava"); if(p.getAirSupply()<80) dangers.add("low_air"); if(p.isOnFire()) dangers.add("on_fire");
        out.add("entities",entities); out.add("dangers",dangers);
        JsonObject body=new JsonObject(); body.addProperty("max_health",p.getMaxHealth()); body.addProperty("air",p.getAirSupply());
        body.addProperty("saturation",p.getFoodData().getSaturationLevel()); body.addProperty("armor",p.getArmorValue());
        body.addProperty("on_ground",p.onGround()); body.addProperty("in_water",p.isInWater()); body.addProperty("sleeping",p.isSleeping());
        JsonArray effects=new JsonArray(); for(var effect:p.getActiveEffects()) { JsonObject e=new JsonObject(); e.addProperty("effect",effect.getEffect().unwrapKey().orElseThrow().identifier().toString()); e.addProperty("duration",effect.getDuration()); e.addProperty("amplifier",effect.getAmplifier()); effects.add(e); }
        body.add("effects",effects); out.add("physiology",body);
        JsonObject env=new JsonObject(); env.addProperty("day_time",p.level().getDefaultClockTime()); env.addProperty("raining",p.level().isRaining()); env.addProperty("difficulty",p.level().getDifficulty().toString());
        env.addProperty("border_distance",p.level().getWorldBorder().getDistanceToBorder(p)); out.add("environment",env); return out;
    }
}

