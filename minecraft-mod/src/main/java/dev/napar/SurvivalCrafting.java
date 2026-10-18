package dev.napar;

import carpet.patches.EntityPlayerMPFake;
import com.google.gson.*;
import java.util.*;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.*;
import net.minecraft.world.level.block.Blocks;

/** Recipe-manager driven inventory transaction. No creative commands or invented recipes. */
public final class SurvivalCrafting {
    private static String id(RecipeHolder<?> holder){return holder.id().identifier().toString();}
    private static List<ItemStack> copyInventory(EntityPlayerMPFake p){
        List<ItemStack> out=new ArrayList<>();for(int i=0;i<36;i++)out.add(p.getInventory().getItem(i).copy());return out;
    }
    static boolean insert(List<ItemStack> items,ItemStack incoming){
        ItemStack remaining=incoming.copy();
        for(ItemStack at:items)if(!at.isEmpty()&&ItemStack.isSameItemSameComponents(at,remaining)){
            int amount=Math.min(remaining.getCount(),Math.max(0,at.getMaxStackSize()-at.getCount()));at.grow(amount);remaining.shrink(amount);if(remaining.isEmpty())return true;
        }
        for(int i=0;i<items.size();i++)if(items.get(i).isEmpty()){
            int amount=Math.min(remaining.getCount(),remaining.getMaxStackSize());items.set(i,remaining.copyWithCount(amount));remaining.shrink(amount);if(remaining.isEmpty())return true;
        }
        return remaining.isEmpty();
    }
    private static boolean table(EntityPlayerMPFake p){
        for(BlockPos at:BlockPos.betweenClosed(p.blockPosition().offset(-4,-3,-4),p.blockPosition().offset(4,3,4)))
            if(p.level().hasChunkAt(at)&&p.level().getBlockState(at).is(Blocks.CRAFTING_TABLE)&&GameSensors.visible(p,at,4.5))return true;
        return false;
    }
    private static int fill(List<Ingredient> requirements,int at,List<ItemStack> available,List<ItemStack> chosen,int[] attempts){
        if(at==requirements.size())return 1;if(++attempts[0]>10000)return 0;
        for(int slot=0;slot<available.size();slot++){
            ItemStack stack=available.get(slot);if(stack.isEmpty()||!net.minecraft.world.entity.player.Inventory.isUsableForCrafting(stack)||!requirements.get(at).test(stack))continue;
            ItemStack one=stack.copyWithCount(1);stack.shrink(1);chosen.add(one);
            if(fill(requirements,at+1,available,chosen,attempts)==1)return 1;
            chosen.removeLast();available.set(slot,one.copyWithCount(stack.getCount()+1));
        }
        return 0;
    }
    public static JsonObject craft(EntityPlayerMPFake p,String recipeId,int times){
        if(times<1||times>16)throw new IllegalArgumentException("Craft count outside 1..16");
        RecipeHolder<?> holder=p.level().getServer().getRecipeManager().getRecipes().stream().filter(r->id(r).equals(recipeId)).findFirst().orElseThrow(()->new IllegalArgumentException("Unknown recipe; inspect recipes first"));
        if(!(holder.value() instanceof CraftingRecipe recipe))throw new IllegalArgumentException("Not a crafting recipe");
        var info=recipe.placementInfo();if(info.isImpossibleToPlace())throw new IllegalArgumentException("Dynamic recipe needs an explicit grid and is not supported by this tool");
        int cells=info.slotsToIngredientIndex().size();
        int width=recipe instanceof ShapedRecipe shaped?shaped.getWidth():(cells<=4?Math.min(2,cells):3);
        int height=recipe instanceof ShapedRecipe shaped?shaped.getHeight():(int)Math.ceil(cells/(double)Math.max(1,width));
        if(width<1||height<1||width*height>9)throw new IllegalArgumentException("Invalid crafting grid");
        boolean needsTable=width>2||height>2||info.slotsToIngredientIndex().size()>4;
        if(needsTable&&!table(p))throw new IllegalArgumentException("A visible crafting table must be within 4.5 blocks");
        List<ItemStack> staged=copyInventory(p),produced=new ArrayList<>();
        for(int repeat=0;repeat<times;repeat++){
            // One requirement per occupied grid cell, including repeated shaped ingredients.
            List<Ingredient> requirements=new ArrayList<>();
            for(int index:info.slotsToIngredientIndex())if(index>=0)requirements.add(info.ingredients().get(index));
            List<ItemStack> chosen=new ArrayList<>();
            if(fill(requirements,0,staged,chosen,new int[]{0})==0)throw new IllegalArgumentException("Missing ingredients; nothing consumed");
            List<ItemStack> grid=new ArrayList<>(Collections.nCopies(width*height,ItemStack.EMPTY));int used=0;
            for(int slot=0;slot<info.slotsToIngredientIndex().size();slot++)if(info.slotsToIngredientIndex().getInt(slot)>=0)grid.set(slot,chosen.get(used++));
            CraftingInput input=CraftingInput.of(width,height,grid);
            if(!recipe.matches(input,p.level()))throw new IllegalArgumentException("Recipe grid did not match; nothing consumed");
            ItemStack output=recipe.assemble(input);if(output.isEmpty())throw new IllegalArgumentException("Empty recipe result");
            if(!insert(staged,output))throw new IllegalArgumentException("Inventory full; nothing consumed");
            for(ItemStack remainder:recipe.getRemainingItems(input))if(!remainder.isEmpty()&&!insert(staged,remainder))throw new IllegalArgumentException("No room for crafting remainders; nothing consumed");
            produced.add(output.copy());
        }
        for(int i=0;i<36;i++)p.getInventory().setItem(i,staged.get(i));
        p.getInventory().setChanged();p.containerMenu.broadcastChanges();p.awardRecipes(List.of(holder));p.triggerRecipeCrafted(holder,produced);
        for(ItemStack output:produced)output.onCraftedBy(p,output.getCount());
        JsonObject out=new JsonObject();JsonArray results=new JsonArray();for(ItemStack item:produced)results.add(GameSensors.item(item,-1));out.add("produced",results);out.addProperty("crafts",times);return out;
    }
    public static JsonObject recipes(EntityPlayerMPFake p,String query){
        JsonArray out=new JsonArray();
        for(var holder:p.level().getServer().getRecipeManager().getRecipes()){
            if(!(holder.value() instanceof CraftingRecipe recipe)||!id(holder).contains(query))continue;
            JsonObject entry=new JsonObject();entry.addProperty("recipe",id(holder));entry.addProperty("automatic_grid",!recipe.placementInfo().isImpossibleToPlace());
            JsonArray ingredients=new JsonArray();
            for(var ingredient:recipe.placementInfo().ingredients()){
                JsonArray options=new JsonArray();ingredient.items().limit(12).forEach(item->options.add(BuiltInRegistries.ITEM.getKey(item.value()).toString()));ingredients.add(options);
            }
            entry.add("ingredient_groups",ingredients);out.add(entry);if(out.size()>=24)break;
        }
        JsonObject result=new JsonObject();result.add("recipes",out);result.addProperty("limit",24);return result;
    }
}
