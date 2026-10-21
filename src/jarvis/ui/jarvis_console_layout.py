"""Responsive character-cell layout for the Jarvis command console."""

# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import math
import re
import textwrap
import time
import unicodedata
from jarvis.ui.jarvis_remarks import current_remark
from jarvis.audio.jarvis_mic_meter import meter_lines
from jarvis.ui.jarvis_idle_drone import overlay as idle_drone_overlay
from jarvis.ui.jarvis_halloween import active as halloween_active, frame as halloween_frame
from jarvis.ui.jarvis_ironman import active as ironman_active, frame as ironman_frame, FPS as IRONMAN_FPS
from jarvis.ui.jarvis_score import elapsed as ironman_elapsed
from jarvis.ui.jarvis_birthday import active as birthday_active, frame as birthday_frame
from jarvis.assistant.mission_briefing import active as briefing_active, frame as briefing_frame, scroll_limit as briefing_scroll_limit
from jarvis.audio.jarvis_listen_control import listening_paused, toggle_pause, request_finish

MAX_WIDTH = 148


def clean(value):
    return ' '.join(''.join(c for c in str(value) if c.isprintable() or c.isspace()).split())


def cells(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in {'W','F'} else 1 for c in text)


def fit(text, width, ellipsis=False):
    text=''.join(c for c in str(text) if c.isprintable())
    if cells(text)<=width:
        return text
    result=''
    for c in text:
        if cells(result+c)>max(0,width-(1 if ellipsis else 0)):
            break
        result+=c
    return result+('…' if ellipsis and width else '')


def wrap(text,width):
    # Retain a generous text area while handling wide glyphs without overflow.
    lines=[]
    for line in textwrap.wrap(clean(text),width=max(1,width)) or ['']:
        while cells(line)>width:
            prefix=fit(line,width)
            if not prefix:break
            lines.append(prefix);line=line[len(prefix):]
        lines.append(line)
    return lines


def box(title, content, width, minimum=0, style=1):
    width=max(8,width)
    label=fit(clean(title),width-6)
    lines=[('┌─ '+label+' '+'─'*(width-cells(label)-5)+'┐',style),('│'+' '*(width-2)+'│',0)]
    for text,color in content:
        value=fit(clean(text),width-4,True)
        lines.append(('│ '+value+' '*(width-4-cells(value))+' │',color))
    while len(lines)<minimum-2:
        lines.append(('│'+' '*(width-2)+'│',0))
    lines += [('│'+' '*(width-2)+'│',0),('└'+'─'*(width-2)+'┘',style)]
    return lines


def clock(value):
    try:
        value=float(value)
        value=int(max(0,value)) if math.isfinite(value) else 0
    except (ValueError,TypeError):value=0
    return f'{value//60:02d}:{value%60:02d}'


def music_lines(data,width,activity='standby'):
    state=data.get('state','unavailable')
    if state not in {'playing','paused'}:
        message={'stopped':'Nothing playing','checking':'Checking local player…','unavailable':'Player unavailable'}.get(state,'Player unavailable')
        return box('NOW PLAYING',[(message,0),('Say Hey Jarvis to choose a song.',3),('',0),('LOCAL LIBRARY',3)],width,minimum=10)
    lowered=data.get('lowered') and state=='playing'
    if state=='paused':label='PAUSED'
    elif lowered:label='MUSIC LOWERED · '+{'speaking':'Responding','listening':'Listening'}.get(activity,'Processing')
    else:label='PLAYING'
    try:
        elapsed=max(0,float(data.get('elapsed',0)));duration=max(0,float(data.get('duration',0)))
        if not math.isfinite(elapsed):elapsed=0
        if not math.isfinite(duration):duration=0
    except (ValueError,TypeError):elapsed,duration=0,0
    length=max(4,width-18)
    fill=min(length,int(length*min(elapsed/duration,1))) if duration else 0
    progress=clock(elapsed)+' '+'█'*fill+'─'*(length-fill)+' '+(clock(duration) if duration else '--:--')
    note='Restores after the response' if lowered else 'LOCAL LIBRARY'
    return box('NOW PLAYING',[(data.get('title','Unknown track'),0),(data.get('artist','Unknown artist'),3),('',0),
                              (label,4 if lowered else 1),(progress,1),(note,3)],width,minimum=10)


def elapsed_seconds(data,now):
    try:
        end=now if data.get('result')=='running' else float(data.get('updated',now))
        return max(0,int(end-float(data.get('started',end))))
    except (ValueError,TypeError):return 0


def processing_seconds(data,now):
    """Processing time is independent of the latest telemetry update."""
    try:
        start=float(data.get('processing_started',data.get('started',now)))
        end=float(data.get('processing_finished') or now)
        return max(0,end-start) if math.isfinite(start) and math.isfinite(end) else 0
    except (ValueError,TypeError):return 0


def processing_label(data,now):
    spinner='|/-\\'[int(now*4)%4]
    state='MODEL WORKING' if str(data.get('model_pending','0'))=='1' else 'PROCESSING REQUEST'
    return f'{spinner} {state}  ·  {clock(processing_seconds(data,now))}'


def welcome_glow(data,activity,now):
    """Eight-second violet greeting accent, superseded by errors/new requests."""
    if activity not in {'speaking','standby'} or data.get('attention'):
        return None
    try:
        start=float(data.get('welcome_glow_started',0))
        age=float(now)-start
        if not start or not math.isfinite(age) or not 0<=age<8:
            return None
        if float(data.get('started',0))>start:
            return None
    except (ValueError,TypeError):
        return None
    return 8 if age<6 and int(age*3)%3!=2 else 9


def response_glow(data,activity,now):
    if activity not in {'speaking','standby'} or data.get('attention') or not data.get('reply'):
        return None
    timestamps=[data.get('response_ready')]
    if data.get('stage')=='complete':timestamps.append(data.get('reactor_completed'))
    ages=[]
    for timestamp in timestamps:
        try:
            age=float(now)-float(timestamp)
            if math.isfinite(age) and 0<=age<1.8:ages.append(age)
        except (ValueError,TypeError):pass
    if not ages:return None
    age=min(ages)
    return 7 if .35<=age<1.1 else 1


def status_line(data,activity,now):
    if data.get("listening_paused"):return "LISTENING PAUSED  ·  Press P to resume",4
    elapsed=elapsed_seconds(data,now)
    if activity=='standby':
        try:recent=now-float(data.get('updated',0))<5
        except (ValueError,TypeError):recent=False
        if recent and data.get('stage')=='complete':
            return f'COMPLETED IN {elapsed}s  ·  Ready for Hey Jarvis',1
        return 'READY  ·  Say "Hey Jarvis"',5
    if activity=='attention':return 'ATTENTION  ·  Check the response below',4
    if activity=='processing':return processing_label(data,now),1
    return activity.upper()+f'  ·  {elapsed:02d}s elapsed',4 if activity=='listening' else 1


def speaker_line(value,diagnostics=False):
    value=clean(value)
    if diagnostics:return 'SPEAKER / '+value
    name=re.split(r'\s*\((?:similarity|score|confidence)',value,1,flags=re.I)[0].strip()
    if not name or name.lower() in {'pending','unknown'}:
        return 'SPEAKER / '+(name or 'Pending')
    return 'SPEAKER / '+name+' · estimated'


def timeline(data,activity):
    observed=data.get('activity_events',[])
    if observed:
        entries=[(clean(item[0]),clean(item[1])) for item in observed if isinstance(item,list) and len(item)>=2]
        if entries:
            return [(stamp+'  '+caption,(4 if activity=='attention' else 1) if i==len(entries[-4:])-1 else 3) for i,(stamp,caption) in enumerate(entries[-4:])]
    events=[(clean(stamp),clean(message)) for stamp,message in data.get('events',[]) if message]
    def stamp(words):
        found=[stamp for stamp,message in events if any(word in message.lower() for word in words)]
        return found[-1] if found else ''
    steps=[]
    if data.get('transcript'):steps.append((stamp(['transcrib','speaker','heard','matching']),'Heard command'))
    messages=' '.join(message.lower() for _,message in events)
    if 'local music' in messages:action='Selected local music'
    elif 'spotify' in messages:action='Selected Spotify'
    elif 'clock' in messages:action='Checked local clock'
    elif any(word in messages for word in ['selected','matching','controlling','sending']):action='Selected command'
    else:action=''
    if action:steps.append((stamp(['controlling','selected','sending','checking the local','matching']),action))
    reply=clean(data.get('reply',''))
    if reply and activity!='attention':
        action='Started playback' if reply.startswith(('Playing ','Resuming local')) else 'Paused music' if reply=='Music paused.' else 'Stopped music' if reply=='Music stopped.' else 'Speaking response' if activity=='speaking' else 'Delivered response'
        steps.append((stamp(['playing the response','speaking']),action))
    if activity=='attention':steps.append((events[-1][0] if events else '','Needs attention'))
    elif activity=='standby' and reply:steps.append((stamp(['command finished','command complete']),'Complete'))
    elif not steps and events:steps.append((events[-1][0],events[-1][1]))
    if not steps:return [('Waiting for a command.',3)]
    return [((stamp+'  ' if stamp else '')+message,4 if activity=='attention' and i==len(steps)-1 else 1 if i==len(steps)-1 else 3) for i,(stamp,message) in enumerate(steps[-4:])]


def left_lines(data,width,activity,elapsed,scroll=0,diagnostics=False,now=None):
    now=time.time() if now is None else now
    heard=data.get('transcript') or ('Listening for your command…' if activity=='listening' else 'Say "Hey Jarvis" to begin.')
    heard_content=[(s,0) for s in wrap(heard,width-4)[:2]]
    if activity=='listening':heard_content += [('',0)]+meter_lines(data,now,width-4)
    lines=box('YOU SAID',heard_content,width,minimum=5)
    lines += [(speaker_line(data.get('speaker','Pending'),diagnostics),3),('',0)]
    pending=clean(data.get('activity_caption') or data.get('detail',''))
    if pending:pending += '…'
    else:pending='Local model is working on your request…' if str(data.get('model_pending','0'))=='1' else 'Processing your request…'
    target=clean(data.get('activity_target',''))
    if target and activity=='processing':pending+=' '+target
    reply=data.get('attention') or data.get('reply') or (pending if activity=='processing' else 'Waiting for your command…')
    wrapped=wrap(reply,width-4)
    scroll=min(max(0,scroll),max(0,len(wrapped)-4))
    note=f'Lines {scroll+1}-{min(scroll+4,len(wrapped))} of {len(wrapped)} · Up/Down scroll' if len(wrapped)>4 else f'Completed in {elapsed}s' if activity=='standby' and data.get('reply') else data.get('detail','')
    content=[(s,4 if activity=='attention' else 0) for s in wrapped[scroll:scroll+4]]+[('',0),(note,3)]
    if activity=='processing':content.insert(-1,(processing_label(data,now),1))
    title='LAST RESPONSE' if activity=='standby' and data.get('reply') else 'READY' if activity=='standby' else activity.upper()
    lines += box('JARVIS / '+title,content,width,minimum=9,style=4 if activity=='attention' else response_glow(data,activity,now) or 1)
    lines += [('',0),('ACTIVITY',3),('',0)]+timeline(data,activity)
    return lines


def compose(data,music,w,h,activity,reactor,now=None,scroll=0,diagnostics=False):
    """Return positioned text cells; shared by curses and preview tests."""
    now=time.time() if now is None else now
    if birthday_active(data,now):
        return birthday_frame(w,h,now-float(data['show_started']),data.get('show_honoree','')),max(1,w-2)
    if ironman_active(data,now):
        return ironman_frame(w,h,ironman_elapsed(data,now)),max(1,w-2)
    if halloween_active(data,now):
        return halloween_frame(w,h,now-float(data['show_started'])),max(1,w-2)
    if briefing_active(data):
        return briefing_frame(data,w,h,reactor,now=now,scroll=scroll)
    width=max(1,min(w-2,MAX_WIDTH));origin=max(0,(w-width)//2)
    side=width>=98 and h>=40
    left=int((width-3)*.65) if side else width
    right=width-left-3 if side else 0
    result=[]
    scene={}
    response_top=None
    glow=welcome_glow(data,activity,now)
    def put(row,col,text,style=0,limit=None):
        if row<0 or row>=h-1 or col<0 or col>=w-1:return
        limit=min(w-col-1,limit if limit is not None else width)
        if limit<=0:return
        result.append((row,col,fit(text,limit),style,limit))
    put(0,origin,'J A R V I S  /  LIVE COMMAND CONSOLE',glow or 1,width)
    label,color=status_line(data,activity,now);put(2,origin,label,color,width)
    left_limit=h-2 if side else max(4,h-5)
    body=left_lines(data,max(8,left),activity,elapsed_seconds(data,now),scroll,diagnostics,now)
    if not side and h<30:
        pending=clean(data.get('activity_caption')) if data.get('activity_caption') else 'Model is working…'
        reply=data.get('attention') or data.get('reply') or (pending if activity=='processing' else 'Waiting for your command…')
        wrapped=wrap(reply,max(1,left))
        if h<18:
            body=[('JARVIS / RESPONSE',1)]+[(s,0) for s in wrapped[scroll:scroll+max(1,h-10)]]
        else:
            body=[('YOU SAID',1),(fit(clean(data.get('transcript') or 'Say Hey Jarvis to begin.'),left,True),0),('',0),('JARVIS / RESPONSE',1)]
            body += [(s,0) for s in wrapped[scroll:scroll+max(1,h-16)]]+[('',0),(speaker_line(data.get('speaker','Pending'),diagnostics),3)]
        if activity=='listening' and h>=18:
            body=body[:2]+meter_lines(data,now,left)+body[2:]
        elif activity=='listening':
            body=[('LISTENING / MICROPHONE',1)]+meter_lines(data,now,left)
    revealing=glow or response_glow(data,activity,now)
    in_response=False
    for row,(line,style) in enumerate(body):
        if row+4>=left_limit:break
        if line.startswith('┌─ JARVIS /'):in_response=True;response_top=row+4
        if glow and in_response and line.startswith(('┌','└')):style=glow
        if line.startswith('│') and line.endswith('│'):
            edge=revealing if in_response and revealing else 5
            put(row+4,origin,'│',edge,1);put(row+4,origin+1,line[1:-1],style,left-2);put(row+4,origin+left-1,'│',edge,1)
        else:put(row+4,origin,line,revealing if revealing and line=='JARVIS / RESPONSE' else style,left)
        if line.startswith('└'):
            if in_response and response_top is not None:scene['response']=(origin,response_top,left,row+5-response_top)
            in_response=False
    if side:
        col=origin+left+3
        art=reactor(data,now=now,large=right>=49 and h>=48)
        art_width=max(cells(line) for line,_ in art)
        offset=max(0,(right-art_width)//2)
        scene['reactor']=(col+offset,4,min(art_width,right-offset),len(art))
        for row,(line,style) in enumerate(art):
            if style==2:style=4 if activity=='listening' else 5 if activity=='standby' else 1
            if glow and line.strip():style=glow
            put(row+4,col+offset,line,style,right-offset)
        aside=current_remark(data,activity,now)
        if aside:
            text,style=aside
            text=fit(text,right,True)
            put(4+len(art),col+max(0,(right-cells(text))//2),text,style,right)
        music_rows=music_lines(music,right,activity)
        scene['music']=(col,4+len(art)+1,right,len(music_rows))
        scene['music_playing']=music.get('state')=='playing'
        for row,(line,style) in enumerate(music_rows):
            at=4+len(art)+1+row
            if line.startswith('│'):
                put(at,col,'│',5,1);put(at,col+1,line[1:-1],style,right-2);put(at,col+right-1,'│',5,1)
            else:put(at,col,line,style,right)
    elif h>=10:
        aside=current_remark(data,activity,now)
        if aside and left_limit<=h-5:
            put(h-5,origin,aside[0],aside[1],width)
        state=music.get('state')
        if state in {'playing','paused'}:
            put(h-4,origin,'MUSIC / '+clean(music.get('title'))+' · '+clean(music.get('artist')),1,width)
            label='PAUSED' if state=='paused' else 'MUSIC LOWERED' if music.get('lowered') else 'PLAYING'
            put(h-3,origin,label+' · '+clock(music.get('elapsed'))+' / '+(clock(music.get('duration')) if music.get('duration') else '--:--'),4 if state!='paused' and music.get('lowered') else 3,width)
        else:put(h-3,origin,'MUSIC / '+('Player unavailable' if state=='unavailable' else 'Nothing playing'),3,width)
    elif h>=6:
        put(h-2,origin,'MUSIC / '+clean(music.get('title') or 'Nothing playing'),3,width)
    result.extend(idle_drone_overlay(data,result,w,h,activity,now,scene=scene))
    return result,left


def draw_console(stdscr,status):
    import curses
    from jarvis.ui.jarvis_music_panel import MusicMonitor
    from jarvis.audio.jarvis_manual_listen import ManualListenController
    from jarvis.computer.jarvis_reset import ResetController
    curses.curs_set(0);stdscr.timeout(150)
    color=curses.has_colors();rich=False
    if color:
        curses.start_color();curses.use_default_colors()
        rich=curses.COLORS>=256
        for number,value in [(1,curses.COLOR_CYAN),(2,curses.COLOR_YELLOW),(3,244 if rich else curses.COLOR_WHITE),(4,214 if rich else curses.COLOR_YELLOW),(5,30 if rich else curses.COLOR_CYAN),(6,130 if rich else curses.COLOR_YELLOW),(7,255 if rich else curses.COLOR_WHITE),(8,141 if rich else curses.COLOR_MAGENTA),(9,60 if rich else curses.COLOR_MAGENTA),(10,208 if rich else curses.COLOR_YELLOW),(11,120 if rich else curses.COLOR_GREEN),(12,203 if rich else curses.COLOR_RED),(13,221 if rich else curses.COLOR_YELLOW),(14,88 if rich else curses.COLOR_RED),(15,238 if rich else curses.COLOR_BLUE)]:
            curses.init_pair(number,value,-1)
    monitor=MusicMonitor();scroll=0;previous=None;diagnostics=False
    manual=ManualListenController();reset=ResetController();notice='';notice_until=0
    viewer_idle_since=time.time()
    try:
        while True:
            frame_clock=time.monotonic()
            h,w=stdscr.getmaxyx();data=status.read_state(status.runtime()/'state.json');activity=status.visual_state(data)
            data["listening_paused"]=listening_paused()
            if data['listening_paused'] and activity=='listening':
                data=dict(data,stage='standby',result='idle',mic_active='0')
                activity='standby'
            if activity!='standby' or data.get('attention') or data.get('mic_active')=='1':viewer_idle_since=time.time()
            data['_viewer_idle_since']=viewer_idle_since
            if data.get('reply')!=previous:scroll=0;previous=data.get('reply')
            iron_showing=ironman_active(data)
            birthday_showing=birthday_active(data)
            showing=halloween_active(data) or iron_showing or birthday_showing
            stdscr.timeout(80 if showing or briefing_active(data) else 150)
            stdscr.erase()
            positioned,left=compose(data,monitor.data,w,h,activity,status.reactor_lines,scroll=scroll,diagnostics=diagnostics)
            for row,col,line,style,limit in positioned:
                attr=(curses.color_pair(style) if color else 0)|(curses.A_BOLD if style in {1,2,4,7,8,10,11} else curses.A_DIM if (style==9 or (style in {5,6} and not rich)) or (style==3 and not color) else 0)
                try:stdscr.addnstr(row,col,line,limit,attr)
                except curses.error:pass
            message=manual.poll_message()
            if message:notice=message;notice_until=time.monotonic()+5
            message=reset.poll_message()
            if message:notice=message;notice_until=time.monotonic()+5
            footer=notice if notice and time.monotonic()<notice_until else ('P resume' if data.get('listening_paused') else 'P pause')+'  ·  L listen  ·  Enter send  ·  R reset  ·  Q close  ·  ↑/↓ response  ·  D '+('hide diagnostics' if diagnostics else 'diagnostics')
            if iron_showing and not (notice and time.monotonic()<notice_until):footer='IRON MAN / SKYFALL  |  R cancel / reset  |  Q close this view'
            elif birthday_showing and not (notice and time.monotonic()<notice_until):footer='BIRTHDAY PROTOCOL  |  R cancel / reset  |  Q close this view'
            elif showing and not (notice and time.monotonic()<notice_until):footer='HALLOWEEN SHOW  |  R cancel / reset  |  Q close this view'
            elif briefing_active(data) and not (notice and time.monotonic()<notice_until):footer='MISSION BRIEFING  |  Up/Down scroll  |  L listen  |  R reset  |  Q close'
            footer_width=max(0,min(w-2,MAX_WIDTH));origin=max(0,(w-footer_width)//2)
            try:stdscr.addnstr(h-1,origin,fit(footer,footer_width),footer_width,curses.A_DIM)
            except curses.error:pass
            stdscr.refresh()
            if iron_showing:
                stdscr.timeout(max(1,int(1000/IRONMAN_FPS-(time.monotonic()-frame_clock)*1000)))
            key=stdscr.getch()
            if key!=-1:viewer_idle_since=time.time()
            if key in (ord('q'),ord('Q')):break
            if key in (ord('l'),ord('L')):
                notice=manual.trigger();notice_until=time.monotonic()+5
            elif key in (10,13,curses.KEY_ENTER):
                try:notice=request_finish()
                except OSError:notice='Could not finish recording. Try again.'
                notice_until=time.monotonic()+5
            elif key in (ord('r'),ord('R')):
                notice=reset.trigger();notice_until=time.monotonic()+5
            elif key in (ord('p'),ord('P')):
                try:notice=toggle_pause()
                except OSError:notice='Could not change listening state.'
                notice_until=time.monotonic()+5
            elif key in (ord('d'),ord('D')):diagnostics=not diagnostics
            elif key==curses.KEY_UP:scroll=max(0,scroll-1)
            elif key==curses.KEY_DOWN:
                if briefing_active(data):
                    scroll=min(briefing_scroll_limit(data,left,h),scroll+1)
                else:
                    count=len(wrap(data.get('attention') or data.get('reply') or '',max(4,left-4)))
                    scroll=min(max(0,count-4),scroll+1)
    finally:monitor.close()
