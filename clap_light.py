"""Double-clap control for MW-light; microphone audio stays in memory."""
import argparse, json, queue, time
from pathlib import Path
import numpy as np
import sounddevice as sd
from concurrent.futures import ThreadPoolExecutor

class Detector:
    def __init__(self, threshold=.12):
        self.threshold=threshold
        self.noise=.003
        self.last_peak=-100.
        self.first=None
        self.cooldown=-100.
    def feed(self, samples, now):
        x=np.asarray(samples).flatten()
        peak=float(np.max(np.abs(x)))
        rms=float(np.sqrt(np.mean(x*x)))
        limit=max(self.threshold,self.noise*8)
        impulse=peak>limit and peak>rms*2.5
        self.noise=.995*self.noise+.005*min(rms,limit/4)
        if self.first is not None and now-self.first>.65: self.first=None
        if not impulse or now-self.last_peak<.14: return False
        self.last_peak=now
        if now-self.cooldown<1.5: return False
        if self.first is not None and .18<=now-self.first<=.65:
            self.first=None
            self.cooldown=now
            return True
        self.first=now
        return False

def main():
    p=argparse.ArgumentParser(description='Double-clap control for MW-Light on Windows.')
    p.add_argument('--devices',action='store_true')
    p.add_argument('--device',type=int)
    p.add_argument('--threshold',type=float,default=.12)
    p.add_argument('--seconds',type=float,default=0)
    p.add_argument('--live',action='store_true',help='Enable real white-light switching')
    a=p.parse_args()
    if a.devices: print(sd.query_devices()); return
    q=queue.Queue(maxsize=100)
    def callback(data,frames,timing,status):
        if not q.full(): q.put((data.copy(),time.monotonic(),str(status)))
    detector=Detector(a.threshold)
    print(('LIVE: double clap switches the white light.' if a.live else 'DEMO: double claps are logged only.')+' Ctrl+C to stop. Audio is not saved.',flush=True)
    pool=ThreadPoolExecutor(max_workers=1)
    pending=None
    def toggle():
        from lamp_transport import Lamp
        try:
            with Lamp() as lamp: state=lamp.toggle()
            print('Lamp: '+('ON' if state else 'OFF'),flush=True)
        except Exception as e: print('Lamp error: '+str(e),flush=True)
    start=time.monotonic()
    log=Path(__file__).with_name('events.jsonl')
    try:
        with sd.InputStream(device=a.device,channels=1,samplerate=16000,blocksize=320,callback=callback):
            while not a.seconds or time.monotonic()-start<a.seconds:
                data,now,status=q.get(timeout=2)
                if status: print(status,flush=True)
                if detector.feed(data,now):
                    if pending is not None and not pending.done():continue
                    event={'time':time.strftime('%Y-%m-%d %H:%M:%S'),'event':'double_clap','action':'toggle_requested' if a.live else 'demo_only'}
                    with log.open('a',encoding='utf-8') as f: f.write(json.dumps(event)+'\n')
                    if a.live:
                        print('Double clap detected; switching...',flush=True)
                        pending=pool.submit(toggle)
                    else:print('Double clap detected (DEMO; lamp unchanged)',flush=True)
    except KeyboardInterrupt: pass
    finally:pool.shutdown(wait=True)
if __name__=='__main__': main()
