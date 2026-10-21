"""Regression checks for readable, bounded terminal presentation."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import jarvis_console_layout as layout
import jarvis_status as status

data={'stage':'complete','result':'0','started':'100','updated':113,
      'speaker':'Xavier (similarity 0.039, margin 0.033)',
      'transcript':'Hey Jarvis, play some song from Bruno Mars.',
      'reply':'Playing When I Was Your Man by Bruno Mars.',
      'events':[['20:33:36','Checking speaker identity.'],['20:33:37','Matching the transcript to an available command.'],
                ['20:33:37','Matching the request to an available action.'],['20:33:37','Controlling the local music library.'],
                ['20:33:37','Playing the response through the room speaker.'],['20:33:37','Playing the response.'],
                ['20:33:47','Command finished. Waiting for Hey Jarvis.']]}
music={'state':'playing','title':'When I Was Your Man','artist':'Bruno Mars','elapsed':129,'duration':234,'lowered':False}
assert layout.status_line(data,'standby',114)[0].startswith('COMPLETED IN 13s')
assert layout.status_line(data,'standby',120)[0]=='READY  ·  Say "Hey Jarvis"'
assert 'similarity' not in layout.speaker_line(data['speaker'])
assert layout.speaker_line(data['speaker'])=='SPEAKER / Xavier · estimated'
assert 'similarity 0.039' in layout.speaker_line(data['speaker'],True)
steps=layout.timeline(data,'standby')
assert len(steps)==4 and steps[-1][0].endswith('Complete')
assert sum('Started playback' in line for line,_ in steps)==1
assert steps[-1][1]==1 and all(style==3 for _,style in steps[:-1])
print('PASS readable completion timing, speaker diagnostics and condensed activity')

for w,h in [(220,58),(200,48),(150,48),(144,48),(144,46),(126,40),(100,40),(100,38),(80,24),(40,12),(12,6)]:
    for state in ['standby','listening','processing','speaking','attention']:
        sample=dict(data,stage='complete' if state=='standby' else state,result='0' if state=='standby' else 'running',attention='Check the player' if state=='attention' else '')
        positions,left=layout.compose(sample,music,w,h,state,status.reactor_lines,now=120)
        seen=set()
        for row,col,text,style,limit in positions:
            assert 0<=row<h-1 and 0<=col<w-1
            assert layout.cells(text)<=limit and col+layout.cells(text)<w
            for x in range(col,col+layout.cells(text)):
                assert (row,x) not in seen,('overlap',w,h,state,row,x)
                seen.add((row,x))
        text='\n'.join(item[2] for item in positions)
        assert 'similarity' not in text
        if w>=100 and h>=40:
            assert 'NOW PLAYING' in text and 'ARC REACTOR' in text
            art_end=max(row for row,col,line,style,limit in positions if 'WAITING FOR HEY JARVIS' in line or 'DELIVERING RESPONSE' in line or 'LISTENING FOR COMMAND' in line or 'WORKING ON RESPONSE' in line or 'CHECK MESSAGE ON LEFT' in line)
            music_start=min(row for row,col,line,style,limit in positions if 'NOW PLAYING' in line)
            assert music_start-art_end==2,('detached music panel',art_end,music_start)
        if w>150:
            assert min(col for row,col,*_ in positions)==(w-layout.MAX_WIDTH)//2
            assert max(col+layout.cells(line) for row,col,line,*_ in positions)<=(w-layout.MAX_WIDTH)//2+layout.MAX_WIDTH
print('PASS centered width, attached music, bounds and no overlap across 55 layouts')

for title in ['A'*300,'繁體中文測試'*20,'ROSÉ & Bruno Mars']:
    rows=layout.box('EXAMPLE',[(title,0)],49)
    assert all(layout.cells(line)==49 for line,_ in rows)
print('PASS long titles and wide Unicode remain within their panel')
assert any(style==4 and 'MUSIC LOWERED' in line for line,style in layout.music_lines(dict(music,lowered=True),49,'listening'))
assert any(style==1 and 'PLAYING' in line for line,style in layout.music_lines(music,49))
print('ALL_CONSOLE_DESIGN_TESTS_PASSED')
