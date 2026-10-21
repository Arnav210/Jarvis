"""An opt-in, date-limited classroom birthday surprise."""
from datetime import date
import json
import math
import os
from pathlib import Path
import re
import time

from jarvis.ui.jarvis_halloween import Canvas

DURATION=45.


def config_path():
    return Path(os.environ.get('JARVIS_HOME',Path.home()/'Jarvis'))/'data/birthday-protocol.json'


def load(today=None):
    with config_path().open('rb') as handle:
        raw=handle.read(8193)
    if len(raw)>8192:raise ValueError('Birthday configuration is too large.')
    data=json.loads(raw.decode('utf-8'))
    if not data.get('enabled') or data.get('date')!=(today or date.today()).isoformat():
        raise ValueError('Birthday protocol is not enabled for today.')
    for key,limit in [('honoree',60),('message',3000)]:
        value=data.get(key)
        if not isinstance(value,str) or not value.strip() or len(value)>limit or any(not c.isprintable() and c!='\n' for c in value):
            raise ValueError('Check the birthday '+key+'.')
    return data


def is_request(text):
    return bool(re.fullmatch(r'(?:hey )?(?:jarvis )?(?:please )?(?:(?:activate|start|run|begin) (?:the )?)?birthday protocol(?: please)?',text))


def disable():
    path=config_path()
    try:
        data=json.loads(path.read_text())
        data['enabled']=False
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data,indent=2)+'\n');temporary.chmod(0o600);temporary.replace(path)
    except FileNotFoundError:
        pass


def active(data,now=None):
    if data.get('show')!='birthday' or data.get('result')!='running' or data.get('attention'):return False
    try:
        age=(time.time() if now is None else now)-float(data['show_started'])
        return math.isfinite(age) and 0<=age<DURATION
    except (KeyError,ValueError,TypeError):return False


def frame(width,height,elapsed,honoree):
    t=max(0,min(DURATION,elapsed))
    c=Canvas(width,height);w,h=c.w,c.h
    for i in range(max(8,min(80,w*h//65))):
        x=(i*31+math.sin(t+i)*2)%w
        y=2+(i*17+t*(.3+i%3*.2))%max(1,h-6)
        c.text(x,y,'.' if i%3 else '+',5 if i%2 else 13)
    # Independent fireworks expand and fall; no whole-screen flashes.
    if t>5:
        for i in range(5):
            age=(t-5+i*.53)%3.6
            if age>2:continue
            cx=w*(.12+.19*i);cy=h*(.25+.11*(i%2))
            for n in range(14):
                angle=n*math.tau/14
                c.text(cx+math.cos(angle)*age*9,cy+math.sin(angle)*age*3+age*age*.6,
                       '*' if age<.4 else '+' if age<1 else '.',(1,13,10)[i%3])
    if h>=20 and w>=38:
        cy=max(9,int(h*.60));cx=w//2
        cake=['  |  |  |  |  |  ', ' .-------------. ',
              ' | ~ ~ ~ ~ ~ ~ | ', ' |  H A P P Y  | ', ' | BIRTHDAY!   | ',
              ' |_____________| ', '=================']
        for row,line in enumerate(cake):c.center(cy+row,line,13 if row%2 else 10)
        if t>=20:
            for n in range(5):c.text(cx-6+n*3,cy-1,'*' if int(t*7+n)%3 else '^',13)
        if 12<t<23 and w>=65 and h>=27:
            # Reuse the real articulated suit, rendered through its depth buffer.
            from jarvis.ui.jarvis_ironman import Film,Camera,armor,add,rotate,mix,clamp
            camera=Camera((0,1,13),(0,1,0),w,h)
            f=Film(width,height,camera)
            u=clamp((t-12)/11)
            x=-13+26*u
            transform=lambda p:add((x,1,0),rotate(p,yaw=-.25,roll=-.12))
            mesh,hands,_=armor(t,18<t<21)
            mesh.draw(f,transform)
            for row,col,text,color,_ in f.output():
                for n,char in enumerate(text):
                    if char!=' ':c.text(col+n,row,char,color)
            if 18<t<20.7:
                q=camera.project(camera.local(transform(hands[1])))
                if q:
                    for n in range(60):
                        a=n/59
                        c.text(q[0]+(cx-q[0])*a,q[1]+(cy-1-q[1])*a,'=' if n%2 else '*',1)
    c.text(0,0,' '*w,0);c.center(0,'JARVIS / BIRTHDAY PROTOCOL',13)
    c.text(0,1,'='*w,5)
    for row in [3,5]:c.text(0,row,' '*w,0)
    c.center(3,'PRIORITY EVENT DETECTED' if t<4 else 'HAPPY BIRTHDAY',1 if t<4 else 13)
    if t>=4:c.center(5,honoree.upper(),7)
    for row in range(max(2,h-3),h):c.text(0,row,' '*w,0)
    caption='A SPECIAL MESSAGE FROM YOUR CLASS' if t<20 else 'MAKE A WISH / FROM ALL OF US'
    c.center(h-3,caption[:w],1)
    c.center(h-2,'R cancel / reset  |  Q close view'[:w],3)
    return c.output()


def present(speak,emit):
    from jarvis.computer.jarvis_reset import generation
    try:data=load()
    except (OSError,ValueError,TypeError):
        speak('Birthday protocol is not enabled for today.')
        return False
    token=generation()
    started=time.monotonic()
    emit('action','Birthday protocol activated.',show='birthday',show_started=str(time.time()),
         show_duration=str(DURATION),show_honoree=data['honoree'],result='running',
         briefing_payload='',activity_caption='Birthday protocol',activity_step='show',model_pending='0')
    try:
        if generation()!=token:return False
        speak(data['message'])
        while time.monotonic()-started<DURATION:
            if generation()!=token:return False
            time.sleep(.05)
        return True
    finally:
        emit(show='',show_started='',show_duration='',show_honoree='',reply='')
