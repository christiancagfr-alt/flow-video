"""Standalone Flow Master V8 matcher.

This is a separate prompt source from 人物设置. When it is selected, generation
does not read host persona, base templates, or the editable core prompt.
GPT looks at the reference image once and picks from the catalogs below.
Studio then writes the same continuity locks onto every segment.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from app.core import repository as repo

SETTING_KEY = "prompt_instruction_source"
SOURCE_PERSONA = "persona"
SOURCE = "flow_master_v8"

VOICE_BANDS = ("toddler", "child", "teen", "adult", "senior", "uncertain")
POSTURES = ("standing", "seated", "walking", "crouching", "lying", "uncertain")
HAND_STATES = ("free", "left_occupied", "right_occupied", "both_occupied", "uncertain")

ACTION_CATALOG = (
    {
        "id": "v8_keep",
        "name": "保持原接触",
        "prompt": "身体留在参考图的位置和姿态。已经握住或扶着的东西保持原有接触，不放下、不换手、不新加手臂。",
    },
    {
        "id": "v8_free_hand",
        "name": "空闲手轻动作",
        "prompt": "只有空着的那只手做一个小幅度动作。已经占用的手保持原来的接触，不参与这个动作。",
    },
    {
        "id": "v8_walk",
        "name": "沿原方向继续",
        "prompt": "人物沿参考图里已经开始的方向和步态继续走，不重新迈第一步。手部接触随身体一起移动。",
    },
)

CAMERA_CATALOG = (
    {
        "id": "v8_hold",
        "name": "固定机位",
        "prompt": "摄影机保持当前机位和景别，不推近、不横移、不绕到另一侧。人物位置不因镜头改变。",
    },
    {
        "id": "v8_push",
        "name": "同侧缓推",
        "prompt": "摄影机从当前观察侧缓慢推近，不经过人物正脸的另一侧。人物仍留在原位置。",
    },
    {
        "id": "v8_pull",
        "name": "同侧缓拉",
        "prompt": "摄影机从当前观察侧缓慢拉远。人物仍留在原位置，场地结构不改。",
    },
    {
        "id": "v8_truck",
        "name": "同侧横移",
        "prompt": "摄影机沿人物同一侧横移，本段内不反向。人物的世界位置不跟着镜头转到另一边。",
    },
    {
        "id": "v8_arc",
        "name": "同侧小弧",
        "prompt": "摄影机沿人物同一侧做小弧线，不穿过正脸，不绕到背后再绕回。人物不转身追镜头。",
    },
)

_ACTION_BY_ID = {item["id"]: item for item in ACTION_CATALOG}
_CAMERA_BY_ID = {item["id"]: item for item in CAMERA_CATALOG}

DEVELOPER_INSTRUCTIONS = (
    "【防穿帮指令】\n"
    "这次只使用防穿帮指令，不使用人物设置。不要读取或复述表演预设、动作按钮、镜头策略、人物自定义要求、基础模板或核心提示词。\n"
    "先看这一张参考图一次，判断姿态、手部接触、是否持麦、是否有手机入画，以及声音年龄段。"
    "再为每个片段只写该段的情绪和说话状态。\n"
    "不要描写衣服颜色、五官、发型、建筑或背景清单，不要抄文案，不要发明第三只手、换装或未出现的手机。\n"
    "外观、手部接触、眼睛、声纹和上下条接缝由软件本地写入。镜头只返回 camera_id，不要把镜头句子写进 prompt。\n"
    "每条 prompt 必须以“文案： ”结束，占位符后不要再写任何内容。"
)

MATCH_INSTRUCTIONS = (
    "先完成一次参考图判断，写入 motion_selection。selected_action_ids 只能来自动作候选。"
    "坐着、躺着或蹲着不要选继续走；两只手都占着或看不清手时不要选空闲手动作；不能确定就选 v8_keep。\n"
    "然后为每个片段写一条 prompt：只写本段情绪和说话状态，不要写衣服、五官、场地清单、镜头过程和文案正文。"
    "睁眼或闭眼、手部接触和人物位置不要另写，软件会按片段类型接上。"
    "camera_id 只能来自镜头候选。每条 prompt 以“文案： ”结束。"
)

_VOICE = {
    "toddler": "声音始终是同一个人：2到4岁，轻软奶音，同一口音，不换声。",
    "child": "声音始终是同一个人：儿童音色，同一口音，不换声。",
    "teen": "声音始终是同一个人：少年音色，同一口音，不换声。",
    "adult": "声音始终是同一个人：成年音色，同一口音，不换声。",
    "senior": "声音始终是同一个人：年长音色，同一口音，不换声。",
    "uncertain": "声音始终是同一个人，同一口音和同一音色，不换声。",
}

_REFERENCE = "用这张图保持人物外观、整套衣服、发型和原有场地，不换人、不换装、不重建场景。"
_EXEC = (
    "只逐词说出文案中的原文，不增词、不漏词、不重复。第一个词从第一帧开始说，口型同步。"
    "说完最后一个词就停止说话。不要字幕、标题或水印。人声清楚，不要背景音乐和后期配音。"
)
_POSTURE = {
    "standing": "人物保持参考图中的站姿，仍在原来的支撑面上",
    "seated": "人物保持参考图中的坐姿，不离开座位",
    "walking": "人物沿原来的方向和步态继续，不重新起步",
    "crouching": "人物保持参考图中的蹲姿和位置",
    "lying": "人物保持参考图中的躺姿和位置",
    "uncertain": "人物保持参考图中的姿态和位置",
}
_HANDS = {
    "mic": "拿麦的手一直握着麦，麦头留在嘴前，不换手、不放下",
    "both": "两只手保持原来的接触和物品，不放下、不换手、不做新手势，也不出现第三只手",
    "one": "被占用的那只手保持原来的接触，只有空着的手可以有小动作",
    "free": "双手按参考图的位置自然放置，不凭空多出手臂或道具",
}
_EYES = {
    "说话": "眼睛自然睁开，看向当前该看的对象",
    "祷告": "眼睛闭合。镜头从脸的前侧看，大约偏离正脸四十度，不从正面拍摄",
    "睁开": "从第一帧起一边自然睁眼一边说出第一个词，之后保持睁眼",
}
_SEAMS = {
    "开场": "第一帧已经是：{body}。{eyes}。",
    "换向": "镜头从已经停稳的同一人物状态开始，人物不回到参考图的初始位置。",
    "同向": "镜头沿同一方向继续，人物不回到参考图的初始位置。",
    "停稳": "说到最后几个词时镜头先停稳，人物仍是：{body}。",
    "延续": "说到最后几个词时人物仍是：{body}。",
}
_FILE_CACHE = {"path": "", "mtime": None, "sections": None}


def instruction_path() -> Path:
    from app.services.app_paths import data_dir
    return Path(data_dir()) / "flow_master_v8.md"


def _parse_sections(text: str) -> dict:
    sections = {}
    key = None
    buf = []

    def flush():
        if key is not None:
            sections[key] = "\n".join(buf).strip()

    for line in str(text or "").splitlines():
        if line.startswith("## "):
            flush()
            key = line[3:].strip()
            buf = []
        elif key is not None:
            buf.append(line)
    flush()
    return sections


def load_sections() -> dict:
    path = instruction_path()
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _FILE_CACHE.update(path=key, mtime=None, sections={})
        return {}
    cached = _FILE_CACHE
    if cached["path"] == key and cached["mtime"] == mtime and isinstance(cached["sections"], dict):
        return cached["sections"]
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        sections = {}
    else:
        sections = _parse_sections(text)
    _FILE_CACHE.update(path=key, mtime=mtime, sections=sections)
    return sections


def section(key: str, default: str) -> str:
    value = str(load_sections().get(key) or "").strip()
    return value or default


def _fill(template: str, **fields) -> str:
    try:
        return str(template).format(**fields)
    except (IndexError, KeyError, ValueError):
        return str(template)


def _catalog_from_file(prefix: str, defaults):
    found = {}
    for key, body in load_sections().items():
        if not str(key).startswith(prefix):
            continue
        rest = str(key)[len(prefix):].strip()
        item_id, _, name = rest.partition(" ")
        item_id = item_id.strip()
        if item_id:
            found[item_id] = (name.strip(), str(body or "").strip())
    items = []
    for item in defaults:
        name, prompt = found.get(item["id"], ("", ""))
        items.append({
            "id": item["id"],
            "name": name or item["name"],
            "prompt": prompt or item["prompt"],
        })
    return tuple(items)


def action_catalog():
    return _catalog_from_file("动作-", ACTION_CATALOG)


def camera_catalog():
    return _catalog_from_file("镜头-", CAMERA_CATALOG)


def action_by_id():
    return {item["id"]: item for item in action_catalog()}


def camera_by_id():
    return {item["id"]: item for item in camera_catalog()}


def developer_instructions() -> str:
    return section("给GPT的说明", DEVELOPER_INSTRUCTIONS)


def default_instruction_text() -> str:
    blocks = [
        ("给GPT的说明", DEVELOPER_INSTRUCTIONS.strip()),
        ("匹配要求", MATCH_INSTRUCTIONS.strip()),
        ("外观锁", _REFERENCE),
        ("执行要求", _EXEC.strip()),
        ("眼睛-说话", _EYES["说话"]),
        ("眼睛-祷告", _EYES["祷告"]),
        ("眼睛-睁开", _EYES["睁开"]),
    ]
    blocks.extend((f"声纹-{band}", sentence) for band, sentence in _VOICE.items())
    blocks.extend((f"姿态-{name}", sentence) for name, sentence in _POSTURE.items())
    blocks.extend((f"手-{name}", sentence) for name, sentence in _HANDS.items())
    blocks.extend((f"动作-{item['id']} {item['name']}", item["prompt"]) for item in ACTION_CATALOG)
    blocks.extend((f"镜头-{item['id']} {item['name']}", item["prompt"]) for item in CAMERA_CATALOG)
    blocks.extend((f"接缝-{name}", sentence) for name, sentence in _SEAMS.items())
    lines = [
        "# 防穿帮指令",
        "",
        "改下面各段的文字后保存。下一次 GPT 生成会使用新内容。",
        "不要删除以 ## 开头的标题，也不要改标题里的英文编号。",
        "",
    ]
    for key, body in blocks:
        lines.append(f"## {key}")
        lines.append(str(body).strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def ensure_instruction_file() -> Path:
    """Create the editable copy once. A later edit is left as the user saved it."""
    path = instruction_path()
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(default_instruction_text(), encoding="utf-8", newline="\n")
        _FILE_CACHE.update(path="", mtime=None, sections=None)
    return path


def open_instruction_file() -> Path:
    path = ensure_instruction_file()
    target = str(path)
    if os.name == "nt":
        os.startfile(target)
    elif sys.platform == "darwin":
        import subprocess
        subprocess.Popen(["open", target])
    else:
        import subprocess
        subprocess.Popen(["xdg-open", target])
    return path


class BatchError(RuntimeError):
    pass


def is_active(group) -> bool:
    return str((group or {}).get("instruction_source") or "") == SOURCE


def voice_key(host_id) -> str:
    return f"flow_master_v8_voice_{int(host_id or 0)}"


def voice_sentence(band: str) -> str:
    band = str(band or "")
    if band not in _VOICE:
        band = "uncertain"
    return section(f"声纹-{band}", _VOICE[band])


def load_voice(host_id) -> str:
    host_id = int(host_id or 0)
    if not host_id:
        return ""
    return str(repo.get_setting(voice_key(host_id), "") or "").strip()


def clear_voice(host_id) -> None:
    host_id = int(host_id or 0)
    if host_id:
        repo.set_setting(voice_key(host_id), "")


def configure_group(group) -> str:
    """Point one image group at the V8 catalogs and drop persona fields."""
    group["instruction_source"] = SOURCE
    group["auto_action_match"] = True
    group["action_presets"] = [dict(item) for item in action_catalog()]
    group["camera_presets"] = [dict(item) for item in camera_catalog()]
    group["host_rule"] = ""
    group["template_snapshot"] = ""
    group["locked_voice"] = load_voice(group.get("host_id"))
    return developer_instructions()


def dynamic_text(group, segments) -> str:
    image_rule = str(group.get("image_rule") or "").strip()
    rows = []
    for seg in segments:
        row = {
            "id": str(seg["segment_id"]),
            "text": str(seg.get("foreign_text") or "").strip(),
            "performance_mode": seg.get("performance_mode") or "TALKING",
        }
        rule = str(seg.get("segment_rule") or "").strip()
        if rule:
            row["rule"] = rule
        rows.append(row)
    parts = []
    if image_rule:
        parts.append("本图补充，只能在不换人、不换装、不改建场地时执行：" + image_rule)
    locked = str(group.get("locked_voice") or "").strip()
    if locked:
        parts.append("该主播声纹已锁定，本次不要改年龄或音色：" + locked)
    parts.append(
        "动作候选(JSON)：" + json.dumps(list(action_catalog()), ensure_ascii=False, separators=(",", ":"))
    )
    parts.append(
        "镜头候选(JSON)：" + json.dumps(list(camera_catalog()), ensure_ascii=False, separators=(",", ":"))
    )
    parts.append(
        "片段数据(JSON)：\n" + json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    )
    parts.append(section("匹配要求", MATCH_INSTRUCTIONS))
    return "\n\n".join(parts)


def _clamp_confidence(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _observation(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    posture = str(raw.get("posture") or "uncertain")
    if posture not in POSTURES:
        posture = "uncertain"
    hand_state = str(raw.get("hand_state") or "uncertain")
    if hand_state not in HAND_STATES:
        hand_state = "uncertain"
    band = str(raw.get("voice_age_band") or "uncertain")
    if band not in VOICE_BANDS:
        band = "uncertain"
    confidence = _clamp_confidence(raw.get("confidence", 0.0))
    return {
        "posture": posture,
        "hand_state": hand_state,
        "object_interaction": bool(raw.get("object_interaction")),
        "praying_pose": bool(raw.get("praying_pose")),
        "mic_visible": bool(raw.get("mic_visible")),
        "device_visible": bool(raw.get("device_visible")),
        "voice_age_band": band,
        "confidence": confidence,
        "selected_action_ids": [str(item) for item in list(raw.get("selected_action_ids") or [])],
    }


def _action_allowed(action_id: str, observation: dict) -> bool:
    posture = observation["posture"]
    hand_state = observation["hand_state"]
    if action_id == "v8_walk":
        return posture == "walking"
    if action_id == "v8_free_hand":
        return hand_state in {"free", "left_occupied", "right_occupied"} and not observation["object_interaction"]
    if action_id == "v8_keep":
        return True
    return False


def chosen_action(observation: dict) -> dict:
    requested = []
    for action_id in observation.get("selected_action_ids") or []:
        if action_id == "__SAFE_STATIC__":
            action_id = "v8_keep"
        if action_id not in requested:
            requested.append(action_id)
    allowed = [action_id for action_id in requested if _action_allowed(action_id, observation)]
    if observation["confidence"] < 0.55 and observation["hand_state"] != "free":
        allowed = [action_id for action_id in allowed if action_id == "v8_keep"]
    specific = [action_id for action_id in allowed if action_id != "v8_keep"]
    pick = specific[0] if specific else (allowed[0] if allowed else "v8_keep")
    catalog = action_by_id()
    return catalog.get(pick) or catalog["v8_keep"]


def body_sentence(observation: dict) -> str:
    posture = observation["posture"] if observation["posture"] in _POSTURE else "uncertain"
    place = section(f"姿态-{posture}", _POSTURE[posture])
    if observation.get("mic_visible"):
        hand_key = "mic"
    elif observation["hand_state"] in {"both_occupied", "uncertain"} or observation.get("object_interaction"):
        hand_key = "both"
    elif observation["hand_state"] in {"left_occupied", "right_occupied"}:
        hand_key = "one"
    else:
        hand_key = "free"
    return place + "，" + section(f"手-{hand_key}", _HANDS[hand_key])


def eye_sentence(praying: bool, observation: dict) -> str:
    if praying:
        return section("眼睛-祷告", _EYES["祷告"])
    if observation.get("praying_pose"):
        return section("眼睛-睁开", _EYES["睁开"])
    return section("眼睛-说话", _EYES["说话"])


def seam_block(index: int, total: int, body: str, eyes: str, camera_id: str, camera_ids) -> str:
    lines = [_fill(section("接缝-开场", _SEAMS["开场"]), body=body, eyes=eyes)]
    if index > 0:
        previous = camera_ids[index - 1]
        if previous != camera_id:
            lines.append(section("接缝-换向", _SEAMS["换向"]))
        else:
            lines.append(section("接缝-同向", _SEAMS["同向"]))
    if index + 1 < total:
        nxt = camera_ids[index + 1]
        if nxt != camera_id:
            lines.append(_fill(section("接缝-停稳", _SEAMS["停稳"]), body=body, eyes=eyes))
        else:
            lines.append(_fill(section("接缝-延续", _SEAMS["延续"]), body=body, eyes=eyes))
    return "".join(lines)


def strip_conflicts(text: str, observation: dict, praying: bool) -> str:
    """Drop dynamic clauses that contradict the image lock for this segment."""
    markers = []
    if observation.get("hand_state") != "free" or observation.get("object_interaction") or observation.get("mic_visible"):
        markers.extend(("挥手", "摆手", "指向", "抬手", "换手", "第三只手", "放下麦", "放下麦克风"))
    if observation.get("posture") in {"seated", "lying", "crouching"}:
        markers.extend(("走动", "行走", "起身", "向前走"))
    if not observation.get("device_visible"):
        markers.extend(("手机", "智能手机", "自拍杆"))
    if praying:
        markers.extend(("睁眼看向镜头", "睁眼看镜头", "直视镜头", "正面拍摄", "正面特写"))
    else:
        markers.extend(("全程闭眼", "一直闭眼", "保持闭眼"))
    kept = []
    for clause in re.split(r"[，,。；;！!？?\n]+", str(text or "")):
        clause = clause.strip()
        if not clause:
            continue
        if any(marker in clause for marker in markers):
            if "空闲" in clause and observation.get("hand_state") in {"left_occupied", "right_occupied"}:
                kept.append(clause)
                continue
            continue
        kept.append(clause)
    return "，".join(kept)


def _normalize_dynamic(raw: str, dialogue: str) -> str:
    text = str(raw or "").strip()
    match = re.search(r"文案\s*[:：]", text)
    if match:
        text = text[:match.start()].rstrip(" \n\t；;，,。:.：")
    dialogue = str(dialogue or "").strip()
    if dialogue and dialogue in text:
        text = text.replace(dialogue, "")
    return text.strip()


def _remember_voice(group, band: str) -> str:
    locked = str(group.get("locked_voice") or "").strip()
    if locked:
        return locked
    sentence = voice_sentence(band)
    host_id = int(group.get("host_id") or 0)
    if host_id:
        repo.set_setting(voice_key(host_id), sentence)
    return sentence


def assemble_prompt(*, dynamic: str, dialogue: str, observation: dict, index: int, total: int,
                    praying: bool, voice: str, camera_id: str, camera_ids, image_rule: str = "",
                    segment_rule: str = "") -> str:
    action = chosen_action(observation)
    cameras = camera_by_id()
    camera = cameras.get(camera_id) or cameras["v8_hold"]
    body = body_sentence(observation)
    eyes = eye_sentence(praying, observation)
    parts = [
        section("外观锁", _REFERENCE),
        seam_block(index, total, body, eyes, camera["id"], camera_ids),
        action["prompt"],
        camera["prompt"],
    ]
    emotion = strip_conflicts(dynamic, observation, praying)
    if emotion:
        parts.append(emotion)
    parts.append("文案： " + str(dialogue or "").strip())
    if voice:
        parts.append(voice)
    image_rule = str(image_rule or "").strip()
    segment_rule = str(segment_rule or "").strip()
    if image_rule:
        parts.append("本图补充：" + image_rule)
    if segment_rule:
        parts.append("本段补充：" + segment_rule)
    parts.append(section("执行要求", _EXEC))
    return "\n".join(parts)


def complete_batch(parsed, group, segments) -> dict:
    observation = _observation((parsed or {}).get("motion_selection") or {})
    action = chosen_action(observation)
    observation["selected_action_ids"] = [action["id"]]
    observation["selected_action_names"] = [action["name"]]
    by_id = {}
    for row in list((parsed or {}).get("results") or []):
        sid = str((row or {}).get("id") or "")
        prompt = str((row or {}).get("prompt") or "")
        if sid and prompt.strip():
            by_id[sid] = {
                "prompt": prompt,
                "camera_id": str((row or {}).get("camera_id") or ""),
            }
    missing = [str(seg["segment_id"]) for seg in segments if str(seg["segment_id"]) not in by_id]
    if missing:
        raise BatchError("批量结果缺少片段：" + ", ".join(missing[:20]))
    camera_ids = []
    for seg in segments:
        camera_id = by_id[str(seg["segment_id"])]["camera_id"]
        if camera_id not in _CAMERA_BY_ID:
            camera_id = "v8_hold"
        camera_ids.append(camera_id)
    voice = _remember_voice(group, observation["voice_age_band"])
    prompts = {}
    ai_prompts = {}
    image_rule = str(group.get("image_rule") or "")
    for index, seg in enumerate(segments):
        sid = str(seg["segment_id"])
        dialogue = str(seg.get("foreign_text") or "").strip()
        dynamic = _normalize_dynamic(by_id[sid]["prompt"], dialogue)
        praying = str(seg.get("performance_mode") or "").upper() == "PRAYING"
        ai_prompts[sid] = dynamic
        prompts[sid] = assemble_prompt(
            dynamic=dynamic,
            dialogue=dialogue,
            observation=observation,
            index=index,
            total=len(segments),
            praying=praying,
            voice=voice,
            camera_id=camera_ids[index],
            camera_ids=camera_ids,
            image_rule=image_rule,
            segment_rule=str(seg.get("segment_rule") or ""),
        )
    return {
        "prompts": prompts,
        "ai_prompts": ai_prompts,
        "motion_selection": {
            "enabled": True,
            "posture": observation["posture"],
            "hand_state": observation["hand_state"],
            "object_interaction": observation["object_interaction"],
            "praying_pose": observation["praying_pose"],
            "selected_action_ids": observation["selected_action_ids"],
            "selected_action_names": observation["selected_action_names"],
            "reason_code": "UNCERTAIN",
            "confidence": observation["confidence"],
            "preset_rule": action["prompt"],
            "safety_rule": "",
        },
    }
