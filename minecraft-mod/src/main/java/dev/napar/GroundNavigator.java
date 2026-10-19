package dev.napar;

import carpet.fakes.ServerPlayerInterface;
import carpet.helpers.EntityPlayerActionPack;
import carpet.patches.EntityPlayerMPFake;
import java.util.*;
import java.util.function.BiConsumer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.tags.FluidTags;
import net.minecraft.world.phys.*;
import net.minecraft.core.Direction;

/** Bounded A* over collision surfaces, executed through normal survival controls. */
public final class GroundNavigator {
    private record Cell(int x,int z,double y) {
        Vec3 point(){return new Vec3(x+.5,y,z+.5);}
        BlockPos feet(){return BlockPos.containing(point().add(0,.001,0));}
    }
    private EntityPlayerMPFake player;
    private ArrayDeque<Cell> route;
    private BiConsumer<String,String> completion;
    private long deadline;
    private Vec3 lastProgress,finalTarget;
    private int stalled;
    private String dimension;

    private boolean hazard(EntityPlayerMPFake p,BlockPos at){
        if(!p.level().hasChunkAt(at))return true;
        var state=p.level().getBlockState(at);
        String id=BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
        return state.getFluidState().is(FluidTags.LAVA)||id.contains("magma")||id.contains("cactus")
            ||id.contains("campfire")||id.contains("fire")||id.contains("berry_bush")||id.contains("wither_rose")||id.contains("powder_snow");
    }
    private boolean room(EntityPlayerMPFake p,Cell cell){
        BlockPos feet=cell.feet();
        return !hazard(p,feet)&&!hazard(p,feet.above())&&p.level().getWorldBorder().isWithinBounds(feet)
            &&p.level().noCollision(p,new AABB(cell.x+.2,cell.y+.002,cell.z+.2,cell.x+.8,cell.y+1.8,cell.z+.8));
    }
    private Cell surface(EntityPlayerMPFake p,int x,int z,int supportY){
        BlockPos support=new BlockPos(x,supportY,z);
        if(hazard(p,support))return null;
        var state=p.level().getBlockState(support);
        var shape=state.getCollisionShape(p.level(),support);
        if(!shape.isEmpty()){
            Cell cell=new Cell(x,z,supportY+shape.max(Direction.Axis.Y));
            // Surface swimming must not be planned as walking on a deep pool floor.
            if(!p.level().getFluidState(cell.feet()).is(FluidTags.WATER)&&room(p,cell))return cell;
        }
        if(state.getFluidState().is(FluidTags.WATER)&&p.level().getBlockState(support.above()).isAir()){
            Cell cell=new Cell(x,z,supportY);
            if(room(p,cell))return cell;
        }
        return null;
    }
    private Cell near(EntityPlayerMPFake p,int x,int z,double y){
        Cell best=null;
        for(int by=(int)Math.floor(y)-3;by<=(int)Math.floor(y)+1;by++){
            Cell candidate=surface(p,x,z,by);
            double tolerance=candidate!=null&&p.isInWater()&&p.level().getFluidState(candidate.feet()).is(FluidTags.WATER)?2:.7;
            if(candidate!=null&&Math.abs(candidate.y-y)<=tolerance&&(best==null||Math.abs(candidate.y-y)<Math.abs(best.y-y)))best=candidate;
        }
        return best;
    }
    public boolean active(){return completion!=null;}
    public void start(EntityPlayerMPFake p,Vec3 target,double seconds,BiConsumer<String,String> callback){
        cancel();
        if(!Double.isFinite(target.x)||!Double.isFinite(target.y)||!Double.isFinite(target.z)||p.position().distanceTo(target)>32||seconds<=0){callback.accept("failed","Target exceeds local route range (32 blocks)");return;}
        Cell start=near(p,p.blockPosition().getX(),p.blockPosition().getZ(),p.getY());
        Cell goal=near(p,(int)Math.floor(target.x),(int)Math.floor(target.z),target.y);
        if(start==null||goal==null){callback.accept("failed","No safe collision surface near current feet or requested destination; inspect terrain");return;}
        record Node(Cell cell,double score){}
        PriorityQueue<Node> queue=new PriorityQueue<>(Comparator.comparingDouble(Node::score));
        Map<Cell,Cell> parent=new HashMap<>();Map<Cell,Double> cost=new HashMap<>();
        parent.put(start,start);cost.put(start,0.0);queue.add(new Node(start,0));
        int expanded=0;
        while(!queue.isEmpty()&&expanded++<4096&&!parent.containsKey(goal)){
            Cell current=queue.remove().cell();
            for(int[] delta:new int[][]{{0,1},{0,-1},{1,0},{-1,0}}){
                int x=current.x+delta[0],z=current.z+delta[1];
                if(Math.abs(x-start.x)>32||Math.abs(z-start.z)>32)continue;
                for(int dy:new int[]{-1,0,-2,-3,1}){
                    Cell next=surface(p,x,z,(int)Math.floor(current.y)+dy);
                    if(next==null||next.y-current.y>1.05||current.y-next.y>2.05)continue;
                    if(next.y>current.y+.6&&!p.level().noCollision(p,new AABB(current.x+.2,current.y+.45,current.z+.2,current.x+.8,current.y+2.25,current.z+.8)))continue;
                    double nextCost=cost.get(current)+1+Math.abs(next.y-current.y)*.5+(p.level().getFluidState(next.feet()).is(FluidTags.WATER)?2:0);
                    if(nextCost<cost.getOrDefault(next,Double.MAX_VALUE)){cost.put(next,nextCost);parent.put(next,current);queue.add(new Node(next,nextCost+next.point().distanceTo(goal.point())));}
                    break;
                }
            }
        }
        if(!parent.containsKey(goal)){callback.accept("failed","No safe loaded route within 4096 nodes; inspect obstacle or select a nearer waypoint");return;}
        route=new ArrayDeque<>();for(Cell at=goal;!at.equals(start);at=parent.get(at))route.addFirst(at);
        if(route.isEmpty())route.add(goal);
        player=p;completion=callback;deadline=System.nanoTime()+(long)(seconds*1e9);
        finalTarget=new Vec3(target.x,goal.y,target.z);lastProgress=p.position();stalled=0;dimension=p.level().dimension().identifier().toString();
    }
    public void tick(){
        if(completion==null)return;
        if(!player.isAlive()||player.isRemoved()||!dimension.equals(player.level().dimension().identifier().toString())){finish("failed","Companion unavailable or dimension changed");return;}
        if(System.nanoTime()>=deadline){finish("failed","Navigation deadline exceeded");return;}
        Cell next=route.peek();
        Cell fresh=near(player,next.x,next.z,next.y);
        if(fresh==null||Math.abs(fresh.y-next.y)>.05){finish("failed","Route surface changed; replanning required");return;}
        Vec3 target=route.size()==1?finalTarget:next.point();
        double horizontal=Math.hypot(player.getX()-target.x,player.getZ()-target.z);
        if(horizontal<.20&&Math.abs(player.getY()-target.y)<.65){
            route.remove();if(route.isEmpty()){finish("succeeded","Arrived within 0.20 horizontal / 0.65 vertical blocks of collision surface");return;}
            next=route.peek();target=next.point();
        }
        if(player.position().distanceTo(lastProgress)>.12){lastProgress=player.position();stalled=0;}else if(++stalled>50){finish("failed","Movement stalled; inspect obstacle before retrying");return;}
        var actions=((ServerPlayerInterface)player).getActionPack();
        actions.lookAt(new Vec3(target.x,player.getEyeY(),target.z));actions.setForward(horizontal<.5?.4f:1.0f);
        if(player.isInWater())actions.start(EntityPlayerActionPack.ActionType.JUMP,EntityPlayerActionPack.Action.continuous());
        else if(next.y>player.getY()+.3&&player.onGround())actions.start(EntityPlayerActionPack.ActionType.JUMP,EntityPlayerActionPack.Action.once());
        else actions.start(EntityPlayerActionPack.ActionType.JUMP,null);
    }
    public void cancel(){if(completion!=null)finish("cancelled","Navigation cancelled");}
    private void finish(String status,String detail){
        ((ServerPlayerInterface)player).getActionPack().stopAll();var callback=completion;completion=null;route=null;callback.accept(status,detail);
    }
}

