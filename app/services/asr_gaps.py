"""Find audible, uncaptioned intervals. Audio energy is not a speech detector."""
import wave


def uncovered_intervals(words, duration, minimum=2.0):
    spans=sorted((max(0,float(w['start'])),min(duration,float(w['end']))) for w in words if float(w['end'])>float(w['start']))
    gaps=[];cursor=0.
    for start,end in spans:
        if start-cursor>=minimum:gaps.append((cursor,start))
        cursor=max(cursor,end)
    if duration-cursor>=minimum:gaps.append((cursor,duration))
    return gaps


def audible_gaps(wav_path, words, minimum=2.0):
    import numpy as np
    with wave.open(str(wav_path),'rb') as f:
        rate=f.getframerate()
        if f.getnchannels()!=1 or f.getsampwidth()!=2:raise ValueError('Gap check requires mono PCM16')
        samples=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').astype(np.float32)/32768
    step=max(1,int(rate*.1));count=len(samples)//step
    if not count:return []
    rms=np.sqrt(np.mean(samples[:count*step].reshape(count,step)**2,axis=1))
    threshold=max(.006,float(np.percentile(rms,80))*.12)
    active=rms>threshold
    result=[]
    for start,end in uncovered_intervals(words,len(samples)/rate,minimum):
        a=int(start/.1);b=min(count,int(end/.1))
        if float(active[a:b].sum())*.1>=.6:result.append((start,end))
    return result


def insert_gap_words(segments, additions, gaps):
    original=[dict(w) for s in segments for w in s.get('words',[])]
    added=[]
    for s in additions:
        for w in s.get('words',[]):
            start,end=float(w['start']),float(w['end'])
            for a,b in gaps:
                if a<=(start+end)/2<b:
                    item={**w,'start':max(a,start),'end':min(b,end)}
                    if item['end']>item['start']:added.append(item)
                    break
    words=sorted(original+added,key=lambda w:(w['start'],w['end']))
    if not words:return segments
    return [{'start':words[0]['start'],'end':max(w['end'] for w in words),
             'text':' '.join(w['text'] for w in words),'words':words}]
