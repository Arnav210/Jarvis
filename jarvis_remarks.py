"""Rare, text-only asides with one stable probability roll per time threshold."""
import hashlib
import math

THRESHOLDS=((15,.12),(35,.10),(60,.08))
DURATION=6
MAX_REMARKS=2
LINES=(
    'One moment, sir.',
    'A little deliberation, sir.',
    'The answer is taking its time.',
    'Still with you, sir.',
    'Thoroughness takes a moment.',
    'Some assembly required, sir.',
    'Quite the thoughtful pause.',
    'GPU reinforcements, I hear.',
)

def schedule(seed):
    """Derive repeatable random draws, shared by all viewers of this request."""
    selected=[]
    used=set()
    for threshold,chance in THRESHOLDS:
        digest=hashlib.sha256(f'jarvis-remarks-v1:{seed}:{threshold}'.encode()).digest()
        roll=int.from_bytes(digest[:8],'big')/2**64
        if roll>=chance:continue
        available=[line for line in LINES if line not in used]
        line=available[int.from_bytes(digest[8:16],'big')%len(available)]
        selected.append((threshold,line));used.add(line)
        if len(selected)>=MAX_REMARKS:break
    return selected

def current_remark(data,activity,now):
    if activity!='processing' or data.get('result')!='running' or data.get('attention'):
        return None
    if str(data.get('model_pending','0'))!='1' or data.get('reply'):
        return None
    seed=data.get('started')
    if not seed:return None
    try:
        elapsed=float(now)-float(data.get('processing_started',seed))
        if not math.isfinite(elapsed):return None
    except (ValueError,TypeError):return None
    for threshold,line in schedule(str(seed)):
        age=elapsed-threshold
        if 0<=age<DURATION:
            return ('"'+line+'"',1 if age<4 else 3)
    return None
