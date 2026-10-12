"""Keep each overlap word in exactly one chunk's ownership window."""
def owned_segments(segments, lower, upper):
    result=[]
    for segment in segments:
        words=[dict(w) for w in segment.get('words',[])
               if lower <= (float(w['start'])+float(w['end']))/2 < upper
               and float(w['end'])>float(w['start'])]
        if words:
            result.append({**segment,'start':words[0]['start'],'end':words[-1]['end'],
                           'text':' '.join(w.get('text','').strip() for w in words),'words':words})
        elif not segment.get('words') and lower <= (float(segment['start'])+float(segment['end']))/2 < upper:
            result.append(dict(segment))
    return result


def stitch_segments(previous, current, boundary):
    """Join using a shared spoken word, allowing timestamp jitter at a seam."""
    if not previous:return current
    if not current:return previous
    import re
    left=[w for s in previous for w in s.get('words',[])]
    right=[w for s in current for w in s.get('words',[])]
    normal=lambda w:re.sub(r'\W+','',w.get('text','')).casefold()
    anchors=[]
    for i,a in enumerate(left):
        if abs((a['start']+a['end'])/2-boundary)>2:continue
        for j,b in enumerate(right):
            if abs((b['start']+b['end'])/2-boundary)>2:continue
            if normal(a) and normal(a)==normal(b) and abs(a['start']-b['start'])<1:
                anchors.append((abs((a['start']+a['end']+b['start']+b['end'])/4-boundary),i,j))
    if not anchors:return owned_segments(previous,0,boundary)+owned_segments(current,boundary,float('inf'))
    _,i,j=min(anchors)
    words=[dict(w) for w in left[:i+1]+right[j+1:]]
    return [{'start':words[0]['start'],'end':words[-1]['end'],'text':' '.join(w['text'] for w in words),'words':words}]
