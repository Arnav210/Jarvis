"""Read-only telemetry and responsive console checks; never uses speaker output."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

with tempfile.TemporaryDirectory(prefix='jarvis-panel-test-') as directory:
    os.environ['XDG_RUNTIME_DIR']=directory
    os.environ['JARVIS_MUSIC_SOCKET']=directory+'/player.sock'
    import jarvis_music as music
    from music_fixture import prepare_music
    prepare_music(directory, music)
    import jarvis_music_duck as duck
    import jarvis_music_panel as panel
    panel.INDEX = music.MUSIC / 'library.json'
    import jarvis_status as status
    assert panel.snapshot()['state']=='stopped'
    player=subprocess.Popen(['mpv','--no-config','--ao=null','--no-video','--idle=yes','--pause=yes','--terminal=no','--input-ipc-server='+str(music.SOCKET)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if music.property_value('pid')==player.pid:break
            time.sleep(.05)
        assert panel.snapshot()['state']=='stopped'
        music.perform('play',"That's What I Like")
        for _ in range(100):
            data=panel.snapshot()
            if data.get('duration',0)>0:break
            time.sleep(.05)
        assert data['title']=="That's What I Like" and data['artist']=='Bruno Mars',data
        assert data['state']=='playing' and data['duration']>60,data
        time.sleep(.2)
        assert panel.snapshot()['elapsed']>data['elapsed']
        print('PASS actual song, artist, progress and duration from silent MPV')
        before=music.property_value('volume')
        with duck.ducked():
            data=panel.snapshot()
            assert data['lowered']
            assert any('MUSIC LOWERED' in line for line,_ in panel.music_lines(data,49,'speaking'))
        assert not panel.snapshot()['lowered']
        assert music.property_value('volume')==before
        music.perform('pause')
        assert panel.snapshot()['state']=='paused'
        assert not any('MUSIC LOWERED' in line for line,_ in panel.music_lines(panel.snapshot(),49))
        music.perform('stop')
        assert panel.snapshot()['state']=='stopped'
        print('PASS ducked, restored, paused and stopped states; telemetry changes no volume')

        sample={'state':'playing','title':"That's What I Like",'artist':'Bruno Mars','elapsed':84,'duration':206,'lowered':True}
        for width in (31,49,80):
            lines=panel.music_lines(sample,width,'speaking')
            assert len(lines)==10 and all(len(line)==width for line,_ in lines)
        for state in ('stopped','checking','unavailable'):
            assert len(panel.music_lines({'state':state},49))==10
        assert panel.clock(float('nan'))=='00:00'
        assert panel.clock(-20)=='00:00'
        print('PASS bounded panel text and unknown-time formatting')

        class Monitor:
            data=sample
            def close(self):pass
        class Screen:
            def __init__(self,h,w):self.h,self.w=h,w;self.keys=iter([258,259,ord('q')]);self.frames=[];self.cells={}
            def getmaxyx(self):return self.h,self.w
            def timeout(self,value):pass
            def erase(self):self.cells={}
            def addnstr(self,row,col,text,limit,attr):
                assert 0<=row<self.h and 0<=col<self.w,(row,col,self.h,self.w)
                text=text[:limit]
                assert col+len(text)<=self.w
                for offset,char in enumerate(text):
                    position=(row,col+offset)
                    assert position not in self.cells,('overlapping cell',position)
                    self.cells[position]=char
            def refresh(self):
                self.frames.append('\n'.join(''.join(self.cells.get((y,x),' ') for x in range(self.w)) for y in range(self.h)))
            def getch(self):return next(self.keys)
        state={'stage':'speaking','result':'running','reply':' '.join(['long response']*150),'transcript':"What's playing?",'speaker':'Unknown','events':[['14:32:12','Checking player.']]}
        with patch.object(panel,'MusicMonitor',Monitor),patch.object(status,'read_state',return_value=state),patch('curses.curs_set'),patch('curses.has_colors',return_value=False):
            for height,width in ((46,144),(40,144),(38,100),(36,100),(24,80),(12,40)):
                screen=Screen(height,width)
                status.draw(screen)
                assert len(screen.frames)==3
                if height>=40 and width>=100:
                    assert 'NOW PLAYING' in screen.frames[-1] and 'ARC REACTOR' in screen.frames[-1]
                    assert "That's What I Like" in screen.frames[-1]
                else:assert 'MUSIC /' in screen.frames[-1]
        print('PASS actual console renderer at six terminal sizes, scrolling, no overlap')
    finally:
        player.terminate();player.wait(timeout=5)
    assert panel.snapshot()['state'] in {'stopped','unavailable'}
    print('ALL_MUSIC_PANEL_TESTS_PASSED')
