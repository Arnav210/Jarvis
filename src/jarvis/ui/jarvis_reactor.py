"""Deterministic, character-cell reactor driven by real command events."""

# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import math
import time

TAU=math.tau
SPEEDS=(.42,-.88,1.38)

def number(data,key,default=0):
    try:
        value=float(data.get(key,default))
        return value if math.isfinite(value) else default
    except (ValueError,TypeError):return default

def state_of(data):
    if data.get('attention') or data.get('stage') in {'attention','error'}:return 'attention'
    if data.get('result')!='running':return 'standby'
    if data.get('stage') in {'starting','captured','listening'}:return 'listening'
    return 'speaking' if data.get('stage')=='speaking' else 'processing'

def completion_age(data,now):
    if data.get('stage')!='complete' or data.get('result')=='running' or data.get('attention'):return -1
    finished=number(data,'reactor_completed',number(data,'updated',-1))
    return now-finished if finished>=0 else -1

def phase_at(ring,now,completed=-1):
    phase=(now*SPEEDS[ring]+ring*.9)%TAU
    if 0<=completed<1.8:
        initial=((now-completed)*SPEEDS[ring]+ring*.9)%TAU
        delta=(-initial+math.pi)%TAU-math.pi
        progress=min(1,completed/.5)
        phase=(initial+delta*(1-(1-progress)**3))%TAU
    return phase

def ripple(data,now,outer):
    started=number(data,'reactor_tool_started',-1)
    returned=number(data,'reactor_tool_returned',-1)
    # Let a sub-millisecond inspection show both event pulses in order.
    return_start=max(returned,started+.65) if started>=0 and 0<=returned-started<.4 else returned
    if returned>=0 and 0<=now-return_start<.75:
        return outer*(1-(now-return_start)/.75),'+'
    if started>=0 and 0<=now-started<.65:
        return outer*(now-started)/.65,'*'
    return None

def reactor_lines(data,now=None,large=True,state=None):
    now=time.time() if now is None else now
    state=state or state_of(data)
    cols,rows=(49,25) if large else (31,17)
    targets=(10.8,8.0,5.2) if large else (7.0,5.3,3.6)
    core=3.35 if large else 2.35
    breath=(1-math.cos(now*TAU/3.2))/2
    speech=(1-math.cos(now*TAU/1.15))/2
    completed=completion_age(data,now) if state=='standby' else -1
    flourish=0<=completed<1.8
    flash=flourish and .45<=completed<1.1
    wave=ripple(data,now,targets[0]) if state=='processing' else None
    listening_radius=(now%2)/2*targets[0]
    phases=[phase_at(ring,now,completed) for ring in range(3)]
    grid=[]
    for y in range(rows):
        row=[]
        for x in range(cols):
            dx,dy=(x-cols//2)/2,y-rows//2
            radius,angle=math.hypot(dx,dy),math.atan2(dy,dx)
            char=' '
            for ring,target in enumerate(targets):
                if abs(radius-target)>=.30:continue
                char='.' if ring==0 else ':' if ring==1 else '+'
                if state=='processing' or flourish:
                    offset=(angle-phases[ring])%TAU
                    # Two bright heads with segmented trailing energy.
                    for head in (0,math.pi):
                        trail=(offset-head)%TAU
                        if trail<.13:char='*'
                        elif trail<.42:char='#'
                        elif trail<.70 and int(trail*30)%2==0:char='='
                    if flash and abs(math.sin(angle))<.22:char='*'
                elif state=='listening' and abs(radius-listening_radius)<.9:char='*'
                elif state=='speaking' and speech>.5:char='*' if ring==2 else '+'
                elif state=='attention' and breath>.55:char='!'
                elif state=='standby' and breath>.72 and ring==2:char='o'
                break
            core_radius=core+.18*breath
            if abs(radius-core_radius)<.24:
                char='*' if flash or (state=='speaking' and speech>.5) else '+' if breath>.5 else ':'
            if wave and radius>core+1 and abs(radius-wave[0])<.23:char=wave[1]
            if state=='listening' and radius>core+1 and abs(radius-listening_radius)<.20:char=':'
            row.append(char)
        grid.append(row)
    cy=rows//2
    labels=[(cy-2,'   /---------\\   '),(cy-1,'  /           \\  '),(cy,'<    JARVIS     >'),(cy+1,'  \\           /  '),(cy+2,'   \\---------/   ')] if large else [(cy-1,' /---\\ '),(cy,'| JARVIS |'),(cy+1,' \\---/ ')]
    for y,label in labels:
        start=(cols-len(label))//2
        grid[y][start:start+len(label)]=label
    captions={'standby':'WAITING FOR HEY JARVIS','listening':'LISTENING FOR COMMAND','processing':'WORKING ON RESPONSE','speaking':'DELIVERING RESPONSE','attention':'CHECK MESSAGE ON LEFT'}
    title='COMPLETE' if flourish else state.upper()
    if state=='processing':title+='.'*(1+int(now*2)%3)
    lines=[('ARC REACTOR'.center(cols),1),('LOCAL INTELLIGENCE'.center(cols),3),('',0)]
    for y,row in enumerate(grid):
        style=1
        if state=='standby' and not flourish:style=1 if abs(y-cy)<=2 and breath>.55 else 5
        elif state=='attention':style=4 if breath>.55 else 6
        elif state in {'listening','speaking'}:style=1 if (breath if state=='listening' else speech)>.45 else 5
        if flash or (state=='processing' and abs(y-cy)<=1 and breath>.65):style=1
        lines.append((''.join(row),style))
    lines.extend([('',0),(title.center(cols),4 if state=='attention' else 1 if flourish else 2),(captions[state].center(cols),3)])
    return lines
