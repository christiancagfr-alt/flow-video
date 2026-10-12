"""Structured physical camera plans; independent of legacy video execution."""
import math
import re

TYPES = ('STATIC DOLLY_IN DOLLY_OUT TRUCK_LEFT TRUCK_RIGHT ARC_LEFT ARC_RIGHT '
         'ORBIT_LEFT ORBIT_RIGHT DIAGONAL_DOLLY_LEFT DIAGONAL_DOLLY_RIGHT '
         'FRONT_TRACK SIDE_TRACK REAR_FOLLOW CRANE_UP CRANE_DOWN PEDESTAL_UP PEDESTAL_DOWN').split()
SCHEMA = {'type':'object','properties': {
    'enabled':{'type':'boolean'}, 'level':{'type':'integer','minimum':0,'maximum':4},
    'type':{'type':'string','enum':TYPES}, 'start_angle':{'type':'string'}, 'end_angle':{'type':'string'},
    'movement_amount_deg':{'type':['number','null']}, 'movement_distance_m':{'type':['number','null']},
    'duration_sec':{'type':'number'}, 'parallax_required':{'type':'boolean'}, 'perspective_change':{'type':'boolean'}},
    'additionalProperties':False}
SCHEMA['required']=list(SCHEMA['properties'])
INSTRUCTIONS = '''Every segment must return camera_motion (formal CAMERA_PLAN). Levels: 0 static, 1 subtle, 2 normal, 3 clear spatial motion, 4 strong spatial motion. Ordinary sermon segments use 2; openings 3-4, transitions/climax 3, prayer 1-2, ending interaction 2-3. Do not make most shots level 0/1. Vary movement types, not only DOLLY_IN. Specify physical start/end positions, degrees for arcs/orbits (20-30 subtle, 30-45 clear, 45-60 strong), meters for translations and seconds within the clip duration. Front-facing means the face remains mainly visible, and permits front-left 20 to front-right 20. Stable composition means stable framing DURING movement, never a locked camera. No digital zoom or simulated background pan. Set perspective_change for front-to-side, large lateral displacement, or a changed background structure. Choose level <=2 with <=30 degrees and no large perspective change. Camera plan overrides conflicting camera stability presets.'''

PRAYING_INSTRUCTIONS = (
    "PRAYING (closed-eye prayer) segments OVERRIDE the front-facing allowance above: the camera must NEVER be face-on. "
    "Every start_angle and end_angle must be a side or three-quarter view at least 30 degrees away from the subject's front "
    "(side, front-side of 30 degrees or more, rear-side or rear views are allowed); the 'front-left 20 to front-right 20' allowance does NOT apply to PRAYING. "
    "Arc/orbit moves must stay on ONE side of the subject and must never pass through, or stop near, the front. "
    "Prefer dolly in/out, truck, or same-side arcs. Never write 'front', 'face-on' or a front angle under 30 degrees for PRAYING segments. "
    "Non-PRAYING segments keep the original rules."
)
PRAYING_CAMERA_TAIL = ("keep a non-frontal side or three-quarter view of the subject throughout; "
                       "never move to, through or near the face-on front view. ")
PRAYING_CATALOG_SUFFIX = ("闭眼祷告(PRAYING)片段使用本镜头时：不允许正面拍摄人物，环绕或移动只能在人物同一侧进行，"
                          "不得经过或停在正面。")

_FRONT_WORDS = re.compile(r'(?<![非不无避免开要许得止])正面(?!偏)|正前|face[- ]?on|front[- ]?on|head[- ]?on|straight[- ]?on|directly in front|\bfront\b(?![- ]?(?:left|right|side))', re.I)
_FRONT_OFFSET = re.compile(r'正面偏[左右]约?\s*(\d+(?:\.\d+)?)\s*度')
_NEAR_FRONT = re.compile(r'前[侧方]?\s*约?\s*(\d+(?:\.\d+)?)\s*度')


def _near_front(text):
    t = str(text or '')
    for m in _FRONT_OFFSET.finditer(t):
        if float(m.group(1)) < 30: return True
    t = _FRONT_OFFSET.sub('', t)
    if _FRONT_WORDS.search(t): return True
    return any(float(m.group(1)) < 30 for m in _NEAR_FRONT.finditer(t))


def _side(text):
    t = str(text or '').lower(); left = '左' in t or 'left' in t; right = '右' in t or 'right' in t
    return 'L' if left and not right else ('R' if right and not left else '')


def praying_front_violation(plan):
    """Why a camera plan would shoot a praying subject from the front ('' when it is safe)."""
    p = dict(plan or {})
    if not p.get('enabled') or p.get('type') == 'STATIC': return ''
    start, end = p.get('start_angle', ''), p.get('end_angle', '')
    if _near_front(start) or _near_front(end): return 'front_or_near_front_angle'
    rear = lambda x: '后' in str(x) or 'rear' in str(x).lower() or 'behind' in str(x).lower()
    if str(p.get('type', '')).startswith(('ARC', 'ORBIT')) and not (rear(start) or rear(end)):
        a, b = _side(start), _side(end)
        if a and b and a != b: return 'arc_crosses_front'
    return ''


def enforce_praying(plan):
    """Replace a front-shooting plan for a PRAYING segment with a safe same-side push-in.

    Returns (plan, reason). Reason is '' when the plan was already safe.
    """
    reason = praying_front_violation(plan)
    if not reason: return plan, ''
    try: dur = min(6.0, float((plan or {}).get('duration_sec') or 5)) or 5.0
    except (TypeError, ValueError): dur = 5.0
    safe = {'enabled': True, 'level': 2, 'type': 'DOLLY_IN',
            'start_angle': "side three-quarter view, about 45 degrees off the subject's front, never face-on",
            'end_angle': 'closer side three-quarter view at the same angle, never face-on',
            'movement_amount_deg': None, 'movement_distance_m': 1.0, 'duration_sec': dur,
            'parallax_required': True, 'perspective_change': False}
    return normalize(safe), reason


def normalize(value):
    p=dict(value or {})
    if p.get('type') not in TYPES: raise ValueError('运镜方案：不支持的运镜类型')
    level=p.get('level')
    if type(level) is not int or not 0<=level<=4: raise ValueError('运镜方案：运镜等级必须是 0 到 4 的整数')
    if not p.get('enabled') or level==0 or p['type']=='STATIC':
        p.update(enabled=False,level=0,type='STATIC',parallax_required=False,requires_aux_image=False)
        return p
    for key in ('start_angle','end_angle'):
        if not str(p.get(key) or '').strip(): raise ValueError('运镜方案：缺少参数 '+key)
    for key in ('duration_sec','movement_amount_deg','movement_distance_m'):
        v=p.get(key)
        if v is not None and (isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0):
            raise ValueError('运镜方案：参数无效 '+key)
    if not p.get('duration_sec') or p['duration_sec']>8: raise ValueError('运镜方案：运镜时长必须大于 0 秒且不超过 8 秒，请调整提示词后重试')
    angular=p['type'].startswith(('ARC','ORBIT'))
    amount=p.get('movement_amount_deg') or 0
    distance=p.get('movement_distance_m') or 0
    if not (amount if angular else distance): raise ValueError('运镜方案：请提供有效的移动距离或旋转角度')
    angle_text=str(p['end_angle']).upper()
    side=('SIDE' in angle_text or 'REAR' in angle_text) and 'FRONT' in str(p['start_angle']).upper()
    p['parallax_required']=level>=2
    p['requires_aux_image']=bool(level>=4 or amount>45 or (level>=3 and amount>30) or side or p.get('perspective_change'))
    return p

def block(p, praying=False):
    p=normalize(p)
    if not p['enabled']: return 'CAMERA: STATIC. Fixed camera for this explicitly static segment.'
    angular=p['type'].startswith(('ARC','ORBIT'))
    amount=f"{p['movement_amount_deg']:g} degrees" if angular else f"{p['movement_distance_m']:g} meters"
    movement=p['type'].lower().replace('_',' ')
    direction={'ARC_RIGHT':'clockwise toward the subject’s right-front side','ORBIT_RIGHT':'clockwise around the subject','ARC_LEFT':'counterclockwise toward the subject’s left-front side','ORBIT_LEFT':'counterclockwise around the subject','DOLLY_IN':'forward','DOLLY_OUT':'backward','FRONT_TRACK':'backward in front of the moving subject','SIDE_TRACK':'alongside the moving subject','REAR_FOLLOW':'forward behind the moving subject'}.get(p['type'],movement)
    return (f"CAMERA:\nSTART POSITION: {p['start_angle'].replace('_',' ').lower()}.\n"
            f"MOVEMENT: The camera physically performs a {movement} over {p['duration_sec']:g} seconds.\n"
            f"DIRECTION / AMOUNT: Travel {direction}, approximately {amount}.\n"
            f"END POSITION: {p['end_angle'].replace('_',' ').lower()}.\n"
            "PARALLAX: Foreground elements shift faster than the distant background, visibly changing their spatial relationship to the subject.\n"
            "Maintain stable cinematic framing during the camera movement and "
            + (PRAYING_CAMERA_TAIL if praying else "keep the face mainly visible where the planned view allows. ")
            + "This is real physical camera displacement, not digital zoom, crop, artificial background pan or simulated reframing.")

def clean(text):
    for phrase in ('stable camera','static framing','minimal camera movement','subject remains perfectly centered','keep exactly the original composition','maintain original framing','minimal movement','subject centered'):
        text=re.sub(re.escape(phrase),'stable cinematic framing during the camera movement',text,flags=re.I)
    return text

def validate_plans(data, segments, aux_limit):
    plans=data.get('VIDEO_PLAN',[])
    ids=[str(x.get('SEGMENT_ID')) for x in plans]
    expected=[str(x['segment_id']) for x in segments]
    if len(ids)!=len(set(ids)) or set(ids)!=set(expected): raise ValueError('运镜方案：片段缺失或重复')
    for item in plans:
        p=normalize(item.get('camera_motion')); item['camera_motion']=p
        if p.get('requires_aux_image'):
            binding=item.get('IMAGE_BINDING') or {}
            matches=[x for x in data.get('IMAGE_PLAN',[]) if str(item['SEGMENT_ID']) in {str(v) for v in x.get('USED_BY',[])}]
            if not binding.get('END_IMAGE') and len(matches)==1:
                binding={'START_IMAGE':'MASTER','END_IMAGE':matches[0]['SHOT_ID']}
                item['IMAGE_BINDING']=binding;item['GENERATION_MODE']='START_END'
            valid={str(x.get('SHOT_ID')) for x in data.get('IMAGE_PLAN',[]) if str(x.get('IMAGE_PROMPT') or '').strip()}
            if binding.get('END_IMAGE') not in valid:raise ValueError('运镜方案：缺少有效的辅助尾帧图片')
    if len(data.get('IMAGE_PLAN') or [])>aux_limit:raise ValueError('运镜方案：辅助图片数量超过设置上限')
def clean_preserving_dialogue(text, dialogue):
    literal='文案： '+dialogue
    if literal not in text: return clean(text)
    before,after=text.split(literal,1)
    return clean(before)+literal+clean(after)


def prepare_review_draft(data, segments):
    notes=[]
    aliases={}
    for index,image in enumerate(data.get('IMAGE_PLAN') or [],1):
        old=str(image.get('SHOT_ID') or '')
        new=old if re.fullmatch(r'SHOT_[0-9]+',old) else f'SHOT_{index:03d}'
        aliases[old]=new;image['SHOT_ID']=new
        if not str(image.get('IMAGE_PROMPT') or '').strip():notes.append(f'{new}：辅助图片提示词为空，请补充。')
    for item in data.get('VIDEO_PLAN') or []:
        binding=item.get('IMAGE_BINDING') or {}
        if binding.get('END_IMAGE') in aliases:binding['END_IMAGE']=aliases[binding['END_IMAGE']]
    expected={str(seg['segment_id']) for seg in segments}
    seen=set()
    for item in data.get('VIDEO_PLAN') or []:
        sid=str(item.get('SEGMENT_ID'))
        if sid not in expected or sid in seen:raise ValueError('返回的片段编号重复或不匹配，请重新生成该组。')
        seen.add(sid)
        try:item['camera_motion']=normalize(item.get('camera_motion'))
        except (ValueError,TypeError):
            item['camera_motion']=dict(item.get('camera_motion') or {})
            notes.append(f'片段 {sid}：运镜参数不完整，已保留提示词供检查。')
    if seen!=expected:raise ValueError('GPT 返回内容缺少文案片段，请重新生成缺失片段。')
    available={str(x.get('SHOT_ID')) for x in data.get('IMAGE_PLAN') or [] if str(x.get('IMAGE_PROMPT') or '').strip()}
    for item in data.get('VIDEO_PLAN') or []:
        if (item.get('camera_motion') or {}).get('requires_aux_image') and (item.get('IMAGE_BINDING') or {}).get('END_IMAGE') not in available:
            notes.append('片段 '+str(item['SEGMENT_ID'])+'：缺少辅助结束帧图片规划，请补充后提交。')
    data['review_notes']=notes
    return data
def review_camera_block(plan):
    try:return block(plan)
    except (ValueError,TypeError,KeyError):return ''
