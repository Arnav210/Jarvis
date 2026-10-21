"""Level telemetry from existing 16-kHz mono PCM; never opens a microphone."""
import argparse
from array import array
from collections import deque
import json
import math
import signal
import sys
import time
import wave

class MicMeter:
    def __init__(self,threshold=450,emit=None):
        if emit is None:
            from jarvis_status import emit
        self.emit=emit
        self.threshold=threshold
        self.history=deque(maxlen=20)
        self.last=-math.inf
        self.pending=b''

    def start(self):
        self.history.clear();self.pending=b'';self.last=-math.inf
        self.emit(mic_active='1',mic_updated=str(time.time()),mic_history='[]',mic_label='Waiting for audio')

    def feed(self,pcm,force=False):
        pcm=self.pending+pcm
        self.pending=pcm[-1:] if len(pcm)%2 else b''
        pcm=pcm[:len(pcm)//2*2]
        if not pcm:return
        samples=array('h');samples.frombytes(pcm)
        if sys.byteorder!='little':samples.byteswap()
        rms=math.sqrt(sum(value*value for value in samples)/len(samples))
        peak=max(abs(value) for value in samples)
        rms_db=max(-96,20*math.log10(max(rms,1e-6)/32768))
        peak_db=max(-96,20*math.log10(max(peak,1e-6)/32768))
        now=time.monotonic()
        if not force and now-self.last<.12:return
        self.last=now
        level=max(0,min(1,(rms_db+60)/60))
        self.history.append(round(level,3))
        label='CLIPPING' if peak>=32112 else 'Sound detected' if rms>=self.threshold else 'Quiet'
        self.emit(mic_active='1',mic_updated=str(time.time()),mic_history=json.dumps(list(self.history)),mic_rms_db=f'{rms_db:.1f}',mic_peak_db=f'{peak_db:.1f}',mic_label=label)

    def stop(self):
        self.emit(mic_active='0',mic_updated=str(time.time()),mic_label='Capture finished')

def watch_wav(path,seconds):
    """Observe the WAV already being written by arecord; no second capture."""
    meter=MicMeter();meter.start()
    deadline=time.monotonic()+max(0,seconds)+2
    source=None
    running=True
    def stop(*_):
        nonlocal running
        running=False
    previous={sig:signal.signal(sig,stop) for sig in (signal.SIGTERM,signal.SIGINT)}
    try:
        while running and time.monotonic()<deadline:
            if source is None:
                try:
                    source=wave.open(path,'rb')
                    if (source.getnchannels(),source.getsampwidth(),source.getframerate())!=(1,2,16000):
                        raise ValueError('Meter requires 16-kHz S16_LE mono WAV')
                except (OSError,EOFError,wave.Error):
                    time.sleep(.04);continue
            pcm=source.readframes(2560)
            if pcm:meter.feed(pcm,force=True)
            else:time.sleep(.04)
    finally:
        if source is not None:source.close()
        meter.stop()
        for sig,handler in previous.items():signal.signal(sig,handler)

def meter_lines(data,now,width=60):
    if str(data.get('mic_active','0'))!='1':return [('MIC / Capture finished',3)] if data.get('mic_updated') else [('MIC / Waiting for capture',3)]
    try:age=now-float(data.get('mic_updated',0))
    except (ValueError,TypeError):age=math.inf
    if not math.isfinite(age) or age<0 or age>.7:return [('MIC / Waiting for audio data',3)]
    try:
        history=json.loads(data.get('mic_history','[]'))
        history=[max(0,min(1,float(value))) for value in history[-20:] if isinstance(value,(int,float)) and math.isfinite(value)]
    except (ValueError,TypeError):history=[]
    if not history:return [('MIC / Waiting for audio',3)]
    bars=''.join('·' if value==0 else '▁▂▃▄▅▆▇█'[min(7,int(value*8))] for value in history[-max(1,min(20,width-7)):])
    label=str(data.get('mic_label','Sound level'))
    if label not in {'Quiet','Sound detected','CLIPPING'}:label='Sound level'
    style=4 if label=='CLIPPING' else 1
    return [('MIC / '+bars,style),(label+' · '+str(data.get('mic_rms_db','--'))+' dBFS',3)]

def main():
    parser=argparse.ArgumentParser(description='Observe audio levels in an existing recording; does not open the microphone.')
    parser.add_argument('--watch-wav',required=True)
    parser.add_argument('--seconds',type=float,default=5)
    args=parser.parse_args();watch_wav(args.watch_wav,args.seconds)

if __name__=='__main__':main()
