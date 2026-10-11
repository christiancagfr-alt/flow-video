"""Owned whisper.cpp subprocess and WAV validation; no Resolve API access."""
import argparse
import os
import signal
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from app.services import quiet_process as subprocess
import time
import wave
from pathlib import Path


def atomic_text(path,text):
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(str(text),encoding='utf-8');temp.replace(path)


def run(args):
    output=Path(args.output)
    crop = None
    start = getattr(args, "start", None)
    start_value = float(start or 0)
    try:
        if args.language!='sw':raise ValueError('WHISPER_LANGUAGE_ERROR: 必须使用 sw')
        with wave.open(args.wav,'rb') as audio:
            if audio.getsampwidth()!=2 or audio.getcomptype()!='NONE' or audio.getframerate()<16000 or audio.getnframes()==0:
                raise ValueError('WAV_FORMAT_ERROR: FlowStudio_WAV16 必须输出16-bit PCM音频，采样率至少16kHz')
            duration=audio.getnframes()/audio.getframerate()
        if start_value < 0 or args.duration <= 0 or start_value + args.duration > duration + max(0.15,2/args.fps):
            raise ValueError('WAV_RANGE_ERROR')
        if start is None and abs(duration-args.duration)>max(0.15,2/args.fps):
            raise ValueError('WAV_DURATION_MISMATCH: WAV时长与当前视频范围不一致')
        wav_path = args.wav
        if start is not None:
            crop = output.with_suffix('.crop.wav')
            with wave.open(args.wav,'rb') as source, wave.open(str(crop),'wb') as target:
                target.setparams(source.getparams())
                source.setpos(round(start_value*source.getframerate()))
                target.writeframes(source.readframes(round(args.duration*source.getframerate())))
            wav_path = str(crop)
        with output.with_suffix('.log').open('wb') as log:
            log.write(b'Whisper language: sw\n');log.flush()
            proc=subprocess.Popen([args.cli,'-m',args.model,'-f',wav_path,'-l','sw','-osrt','-of',str(output)],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                code=proc.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                proc.terminate() if os.name == 'nt' else os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill() if os.name == 'nt' else os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                raise RuntimeError('WHISPER_TIMEOUT: 识别超时，已停止本次Whisper进程')
        if code!=0:raise RuntimeError('WHISPER_FAILED: 退出码 '+str(code)+'，请查看本视频Whisper日志')
        srt=output.with_suffix('.srt')
        if not srt.is_file() or srt.stat().st_size==0:raise RuntimeError('WHISPER_FAILED: 未生成SRT时间结果')
        atomic_text(output.with_suffix('.exit'),'0')
        return 0
    except Exception as exc:
        atomic_text(output.with_suffix('.error'),str(exc))
        atomic_text(output.with_suffix('.exit'),'1')
        return 1
    finally:
        if crop is not None: crop.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('cli','model','wav','output','language'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--duration',type=float,required=True);parser.add_argument('--fps',type=float,required=True)
    parser.add_argument('--timeout',type=int,default=600)
    parser.add_argument('--start',type=float,default=None)
    raise SystemExit(run(parser.parse_args()))
