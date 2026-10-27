"""Explicit simplified analytical cycles. Not an implementation of FEM 9.860."""
import json
import math
import sys


def positive(value, name, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
        raise ValueError(name+": finite "+("nonnegative" if allow_zero else "positive")+" number required")
    return value


def travel(distance, speed, acceleration, deceleration):
    positive(distance,"distance",True)
    for name,value in [("speed",speed),("acceleration",acceleration),("deceleration",deceleration)]:positive(value,name)
    if distance == 0:return 0
    ramps = speed*speed/(2*acceleration)+speed*speed/(2*deceleration)
    if distance <= ramps:
        peak=math.sqrt(2*distance/(1/acceleration+1/deceleration))
        return peak/acceleration+peak/deceleration
    return speed/acceleration+speed/deceleration+(distance-ramps)/speed


def calculate(data):
    if not isinstance(data,dict) or data.get('format')!='kx-analytical-cycles' or data.get('version')!=1:
        raise ValueError('Unsupported analytical cycle format')
    motion=data.get('motion',{})
    v=positive(motion.get('speedMps'),'speedMps');a=positive(motion.get('accelerationMps2'),'accelerationMps2');b=positive(motion.get('decelerationMps2'),'decelerationMps2')
    pickup=positive(data.get('pickupSeconds'),'pickupSeconds',True);drop=positive(data.get('dropoffSeconds'),'dropoffSeconds',True)
    aux_sc=positive(data.get('singleAuxSeconds'),'singleAuxSeconds',True);aux_dc=positive(data.get('doubleAuxSeconds'),'doubleAuxSeconds',True)
    points=data.get('singlePoints');pairs=data.get('doublePairs')
    if not isinstance(points,list) or not 1<=len(points)<=1000 or not isinstance(pairs,list) or not 1<=len(pairs)<=1000:
        raise ValueError('Explicit singlePoints and doublePairs required, maximum 1000 each')
    for entries in [points,pairs]:
        if any(not isinstance(e,dict) for e in entries):raise ValueError('Point records required')
        if abs(sum(positive(e.get('probability'),'probability',True) for e in entries)-1)>1e-9:raise ValueError('Probabilities must sum to 1; no normalization')
    single=[];double=[]
    for p in points:
        seconds=2*travel(positive(p.get('distanceM'),'distanceM',True),v,a,b)+pickup+drop+aux_sc
        single.append({**p,'seconds':seconds})
    for p in pairs:
        x=positive(p.get('putawayM'),'putawayM',True);y=positive(p.get('retrievalM'),'retrievalM',True)
        seconds=travel(x,v,a,b)+travel(abs(y-x),v,a,b)+travel(y,v,a,b)+2*(pickup+drop)+aux_dc
        double.append({**p,'seconds':seconds})
    sc=sum(p['probability']*p['seconds'] for p in single);dc=sum(p['probability']*p['seconds'] for p in double)
    return {'method':'simplified-explicit-cycle-model','normStatus':'FEM 9.860 requested, original equations not verified','single':{'meanSeconds':sc,'cyclesPerHour':3600/sc if sc else None,'containerMovementsPerHour':3600/sc if sc else None,'points':single},'double':{'meanSeconds':dc,'cyclesPerHour':3600/dc if dc else None,'containerMovementsPerHour':7200/dc if dc else None,'pairs':double},'limits':['Standstill-to-standstill motion, no jerk limit. Explicit joint probabilities, no inferred independent accesses.','Common transfer origin. Single-load cycles only; double cycle moves one inbound and one outbound container.','No physical Z-depth/unbury movements, dual-load lift dispatch, blocking, downtime or system throughput proof.']}


if __name__=='__main__':
    try:print(json.dumps(calculate(json.load(sys.stdin)),ensure_ascii=False,allow_nan=False))
    except (ValueError,TypeError,KeyError) as error:print(str(error),file=sys.stderr);sys.exit(2)
