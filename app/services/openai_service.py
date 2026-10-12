from __future__ import annotations
from app.services import camera_motion
import base64
import hashlib
import json
import mimetypes
import os
import sys
import re
import socket
from pathlib import Path
from app.services import quiet_process as subprocess
import urllib.request
import urllib.error

API_URL = "https://api.openai.com/v1/responses"
KEYCHAIN_SERVICE = "com.flowstudio.openai"
KEYCHAIN_ACCOUNT = "FlowStudio"

# Verified against current OpenAI model documentation on 2026-09-10.
# USD per 1M text tokens: input / cached input / output.
PRICING = {
    "gpt-5.6-luna":  {"input": 0.20, "cached": 0.02, "output": 1.20},
    "gpt-5.6-terra": {"input": 2.00, "cached": 0.20, "output": 12.00},
    "gpt-5.6-sol":   {"input": 4.00, "cached": 0.40, "output": 20.00},
}

def save_api_key_to_keychain(api_key: str):
    from app.services.credential_pool import save
    save(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, api_key)


def _api_keys():
    env = os.environ.get("OPENAI_API_KEY", "").strip()
    if env: return [env]
    from app.services.credential_pool import read
    try: return read(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    except Exception: return []


def get_api_key():
    keys = _api_keys()
    return keys[0] if keys else ''


def next_api_key():
    from app.services.credential_pool import next_key
    return next_key(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, _api_keys())


def delete_api_key():
    from app.services.credential_pool import clear
    clear(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)


def _image_data_url(path: str, task_id=''):
    from app.services.image_assets import resolve_image_asset
    return resolve_image_asset(path, task_id).data_url()

def _extract_output_text(data: dict):
    if data.get("output_text"):
        return str(data["output_text"]).strip()
    chunks = []
    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                chunks.append(content.get("text", ""))
    return "\n".join(x for x in chunks if x).strip()

def calculate_cost(model, input_tokens, cached_tokens, output_tokens):
    rates = PRICING.get(model, PRICING["gpt-5.6-luna"])
    uncached = max(0, int(input_tokens or 0) - int(cached_tokens or 0))
    return (
        uncached / 1_000_000 * rates["input"] +
        int(cached_tokens or 0) / 1_000_000 * rates["cached"] +
        int(output_tokens or 0) / 1_000_000 * rates["output"]
    )


def _prompt_completeness_guard():
    """Mandatory output coverage appended after the user's/core templates.

    The core template may ask for concise wording, but concise must never mean
    dropping execution constraints.  This guard is intentionally output-facing:
    it does not change the user's underlying persona/template data.
    """
    return (
        "【最终提示词完整性规则｜强制覆盖】\n"
        "‘简洁’只允许删除解释、重复和同义废话，绝不允许省略会影响 Flow 执行的约束。"
        "每个片段的最终提示词必须是可独立执行的完整提示词，不能依赖‘遵守上述规则’‘同前’等省略表达。\n"
        "每条最终提示词必须明确覆盖："
        "①参考图身份/服装/场景/光线连续性及防变形防穿帮；"
        "②当前人物表演风格、情绪和本片段实际采用的人物动作，并保留人物自定义要求；"
        "③当前镜头调度策略及其内部规则，并明确写出本片段实际采用的允许镜头，禁止使用镜头池外镜头；"
        "④人物逐词完整说出当前文案、自然真人语速、准确口型同步、文案外绝不说任何字词；"
        "⑤面部持续清晰对焦，禁止失焦、拉风箱、明显运动模糊、人物比例跳变、身体/手指/背景扭曲；"
        "⑥禁止新增字幕、标题、贴纸文字、姓名条和水印式文案；"
        "⑦真实现场自然收音，人声清楚靠前，禁止背景音乐、旁白、后期配音、异常混响/回声；"
        "⑧当前基础模板、图片特殊要求、片段补充要求中仍然有效的硬限制。\n"
        "人物设置中的表演要求、人物动作预设和人物自定义要求不得只缩写成预设名称或泛化标签；"
        "最终提示词必须保留这些设置里真正影响执行的动作幅度、频率、姿态、情绪和禁止项。"
        "‘允许镜头池’属于可选池时，不要求把整个镜头池逐项抄进最终提示词，"
        "但必须明确写出本片段实际选中的镜头，并完整保留镜头预设细节和策略内部限制。"
        "人物动作存在多个候选时，可按文案自然选择实际动作，但必须明确写出本片段采用的动作及其关键执行细节，且不得使用未允许动作。\n"
        "禁止为了缩短输出而省略上述类别；允许合并成自然、紧凑的一段或数句，但执行信息必须完整。"
    )



DIALOGUE_MARKER = "文案： "

SAFE_STATIC_ACTION_ID = "__SAFE_STATIC__"
SAFE_STATIC_ACTION_PROMPT = (
    "保持参考图原有身体姿态、手部位置和道具关系；不额外增加手势或大幅肢体动作。"
    "如果手中正在拿、扶、操作物品，双手/手指/握持关系与物品位置保持连续稳定，只允许眨眼、自然表情、"
    "轻微头部和上半身呼吸式动作；不得放下、换手、抛接、旋转或重新抓取物品。"
)

_MOTION_REASON_CODES = (
    "FREE_HANDS", "LEFT_HAND_OCCUPIED", "RIGHT_HAND_OCCUPIED", "BOTH_HANDS_OCCUPIED",
    "OBJECT_INTERACTION", "SEATED", "WALKING", "PRAYING", "STATIC_POSE", "UNCERTAIN", "MANUAL",
)


def _motion_catalog(group):
    """Normalize the host-selected action preset pool supplied by the persona layer."""
    out = []
    seen = set()
    for raw in list(group.get("action_presets") or []):
        if not isinstance(raw, dict):
            continue
        pid = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        prompt = str(raw.get("prompt") or "").strip()
        if not pid or not prompt or pid in seen:
            continue
        seen.add(pid)
        out.append({"id": pid, "name": name or pid, "prompt": prompt})
    return out


def _unsafe_motion_for_observation(item, observation):
    """Reject obviously conflicting user presets; do not rewrite the user's preset text."""
    text = (str(item.get("name") or "") + " " + str(item.get("prompt") or "")).lower()
    hand_state = str(observation.get("hand_state") or "uncertain")
    posture = str(observation.get("posture") or "uncertain")
    object_interaction = bool(observation.get("object_interaction"))
    praying_pose = bool(observation.get("praying_pose"))

    hand_gesture_markers = (
        "手势", "挥手", "摆手", "抬手", "指向", "比划", "gesture", "wave", "point", "raise hand",
        "arm gesture", "hands move", "hand movement",
    )
    walking_markers = ("走动", "走路", "行走", "向前走", "walk", "walking", "2—3步", "2-3步")
    large_markers = ("大幅手势", "幅度较大", "夸张手势", "vigorous gesture", "large gesture", "big gesture")

    if hand_state in {"left_occupied", "right_occupied", "both_occupied"} or object_interaction:
        if any(marker in text for marker in hand_gesture_markers):
            return True
    if posture == "seated" and any(marker in text for marker in walking_markers):
        return True
    if praying_pose and (any(marker in text for marker in walking_markers) or any(marker in text for marker in large_markers)):
        return True
    return False


def _motion_safety_rule(observation):
    posture = str(observation.get("posture") or "uncertain")
    hand_state = str(observation.get("hand_state") or "uncertain")
    object_interaction = bool(observation.get("object_interaction"))
    praying_pose = bool(observation.get("praying_pose"))
    rules = []
    if posture == "seated":
        rules.append("人物保持参考图坐姿，不起身、不行走，不改变座位关系")
    elif posture == "walking":
        rules.append("人物保持自然行走逻辑，步伐与身体重心连续，禁止突然停走切换或姿态跳变")
    elif posture in {"standing", "crouching", "lying"}:
        rules.append("保持参考图当前身体姿态，不无故切换为其他姿态")

    if hand_state == "both_occupied":
        rules.append("双手均被占用：两只手、手指、握持点和所持物体保持稳定连续，禁止任何额外说话手势、放下、换手或重新抓取")
    elif hand_state == "left_occupied":
        rules.append("左手被占用：左手及其物体保持固定连续，禁止左手说话手势；仅空闲右手可在预设允许时做轻微动作")
    elif hand_state == "right_occupied":
        rules.append("右手被占用：右手及其物体保持固定连续，禁止右手说话手势；仅空闲左手可在预设允许时做轻微动作")
    elif hand_state == "uncertain":
        rules.append("手部状态无法可靠确认时采用保守动作，禁止新增明显手势或改变手与道具关系")

    if object_interaction:
        rules.append("人物正在与物品交互：只延续参考图已有的合理操作动作，不插入与任务无关的讲话手势")
    if praying_pose:
        rules.append("保持参考图祷告姿态和手部关系，动作轻微克制")
    return "；".join(rules)


def _sanitize_motion_selection(raw, catalog, auto_enabled=True):
    """Validate GPT's one-shot visual selection and produce deterministic preset text."""
    by_id = {str(x["id"]): x for x in catalog}
    if not auto_enabled:
        return {
            "enabled": False, "posture": "uncertain", "hand_state": "uncertain",
            "object_interaction": False, "praying_pose": False,
            "selected_action_ids": [], "selected_action_names": [],
            "reason_code": "MANUAL", "confidence": 1.0,
            "preset_rule": "", "safety_rule": "",
        }

    raw = raw if isinstance(raw, dict) else {}
    posture = str(raw.get("posture") or "uncertain")
    if posture not in {"standing", "seated", "walking", "crouching", "lying", "uncertain"}:
        posture = "uncertain"
    hand_state = str(raw.get("hand_state") or "uncertain")
    if hand_state not in {"free", "left_occupied", "right_occupied", "both_occupied", "uncertain"}:
        hand_state = "uncertain"
    observation = {
        "posture": posture,
        "hand_state": hand_state,
        "object_interaction": bool(raw.get("object_interaction")),
        "praying_pose": bool(raw.get("praying_pose")),
    }
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
    except Exception:
        confidence = 0.0
    reason_code = str(raw.get("reason_code") or "UNCERTAIN")
    if reason_code not in _MOTION_REASON_CODES:
        reason_code = "UNCERTAIN"

    requested = []
    for pid in list(raw.get("selected_action_ids") or []):
        pid = str(pid)
        if pid not in requested:
            requested.append(pid)

    selected = []
    for pid in requested:
        item = by_id.get(pid)
        if not item:
            continue
        if _unsafe_motion_for_observation(item, observation):
            continue
        selected.append(item)

    # Low-confidence or visually risky states become conservative automatically.
    visually_risky = hand_state != "free" or observation["object_interaction"] or posture == "uncertain"
    if confidence < 0.55 and visually_risky:
        selected = []
    if not selected:
        selected_ids = [SAFE_STATIC_ACTION_ID]
        selected_names = ["安全保守动作"]
        preset_rule = SAFE_STATIC_ACTION_PROMPT
    else:
        selected_ids = [str(x["id"]) for x in selected]
        selected_names = [str(x["name"]) for x in selected]
        preset_rule = "；".join(str(x["prompt"]) for x in selected if str(x.get("prompt") or "").strip())

    return {
        "enabled": True,
        **observation,
        "selected_action_ids": selected_ids,
        "selected_action_names": selected_names,
        "reason_code": reason_code,
        "confidence": confidence,
        "preset_rule": preset_rule,
        "safety_rule": _motion_safety_rule(observation),
    }

def _dynamic_prompt_generation_guard():
    return (
        "【Flow Studio 动态生成协议｜最高优先级】\n"
        "Studio 会在 GPT 返回后，本地自动拼接完整文案、基础模板、图片/片段规则和固定底层限制。"
        "因此你只负责生成真正需要视觉理解、语义判断和镜头分配的动态部分；禁止重复输出共享固定规则，禁止复制片段文案正文。\n"
        "每条动态提示词必须明确写出：当前情绪/表演状态；本片段实际采用的人物动作及关键动作细节；"
        "从允许镜头池中实际选中的镜头方式及本片段执行细节；必要的环境动态；人物与镜头如何同时运动；说话状态与语言感觉。"
        "不能只写预设名称，必须写清本片段实际怎么动、镜头实际怎么拍。\n"
        "【运动执行强化】如果本片段采用了走动、跟拍、环绕、推进、拉远或其他真实位移镜头，必须把运动写成硬动作，而不是建议："
        "人物走动时明确起始站位、方向、约2-3个自然步伐或等价连续位移，并写明人物必须真正离开原始站位、空间位置发生变化；"
        "镜头运动时明确起始角度、移动方向、持续运动，并写明摄影机真实改变空间位置、产生连续空间视差，不能退化成固定机位、轻微晃动或数码变焦。"
        "如果采用‘人物走动+镜头跟随/环绕’，必须明确两者同时持续发生，不能只执行其中一个。"
        "若当前片段并未选择走动或移动镜头，则不要强行添加。\n"
        "当请求提供‘动作候选预设’时，必须先基于参考图只做一次动作状态判断，再从候选预设中选择安全且匹配的子集；禁止把全部候选预设同时套用。"
        "人物设置里的禁止项、道具连续性、手部连续性和自定义硬限制必须在动态动作设计中遵守；若人物手里已有物品，保持原手持状态，不得丢失、换手或出现额外手臂。\n"
        "每条 prompt 必须以完全一致的占位符“文案： ”结束。占位符后不得输出台词、引号、解释或任何其他内容。"
        "片段 JSON 中的 text 仅用于理解语义和选择动作/镜头，绝对不要复制到输出。\n"
        "不要复述参考图连续性、防穿帮、无字幕、现场收音、口型、防失焦等固定规则；Studio 会在本地确定性追加，避免重复 token。"
    )


def _local_flow_execution_guard():
    return (
        "【Studio 固定执行约束】"
        "严格保持参考图人物身份、人数、五官肤色、发型发色、体型、服装配饰、场景、关键背景、布局、光线、色温和整体视觉连续；"
        "不得擅自增删重要人物或物体，禁止人物比例跳变、身体/手指/道具/背景变形扭曲、镜头穿模、明显运动模糊。"
        "人物必须像真实人物在当前情境中自然讲话，禁止 AI 念稿、朗诵腔、客服腔、机械表演和舞台式夸张；"
        "逐词完整说出“文案”后的当前片段原文，保持原顺序，不增删改、不重复、不漏读、不额外说任何字词，正常真人语速，口型逐词准确同步；"
        "最后一个字结束后立即停止语言发声，只保持自然表情、姿态、视线和无声呼吸。如果本文案发音时长短于视频画面时长，必须保持正常乃至紧凑的连贯真人口语语速，绝不可为了强行填满视频画面而拖长单字读音、降速或强加异常停顿。"
        "面部始终清晰对焦，禁止失焦、拉风箱和突兀景深变化。"
        "禁止新增字幕、翻译字幕、标题、姓名条、贴纸文字、角标或水印式文案；参考图原有环境文字保持原状。"
        "采用真实现场自然收音，人声清楚靠前，只保留极轻微真实环境底声；禁止背景音乐、AI 旁白、画外音、后期配音、异常混响、回声、广播处理和影院空间感。"
    )




def _compact_host_fixed_rule(host_rule: str) -> str:
    """Keep only deterministic hard persona constraints for local assembly.

    GPT already receives the full persona rule and is responsible for choosing the
    actual per-segment emotion/action/camera. Re-appending the full action presets,
    strategy and entire camera pool after GPT causes duplication and can weaken the
    selected motion. Locally keep only hard continuity/prohibition clauses and user
    custom requirements.
    """
    text = str(host_rule or "").strip()
    if not text:
        return ""

    # Camera strategy/pool are candidate instructions for GPT, not final Flow text.
    # Split known persona sections conservatively; unknown text is treated as custom.
    labels = (
        "表演要求：", "人物动作：", "人物动作选择模式：", "人物动作候选预设：",
        "镜头调度策略：", "允许镜头池：", "人物自定义要求："
    )
    positions = []
    for label in labels:
        pos = text.find(label)
        if pos >= 0:
            positions.append((pos, label))
    positions.sort()
    sections = {}
    if positions:
        for i, (pos, label) in enumerate(positions):
            start = pos + len(label)
            end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
            sections[label[:-1]] = text[start:end].strip("；; \n")
    else:
        sections["人物自定义要求"] = text

    hard_words = (
        "必须", "禁止", "不得", "不能", "不允许", "保持", "避免", "绕过",
        "紧紧握住", "始终", "如果", "若", "手里", "手中", "道具", "第三只手",
        "穿过", "穿帮", "障碍", "连续",
    )
    keep = []
    for section_name in ("表演要求", "人物动作", "人物自定义要求"):
        body = sections.get(section_name, "")
        if not body:
            continue
        # Custom requirements are user-authored and must be preserved in full.
        clauses = re.split(r"[；;。\n，,]+", body)
        for clause in clauses:
            clause = clause.strip(" ，,。；;\n\t")
            if not clause:
                continue
            if section_name == "人物自定义要求" or any(w in clause for w in hard_words):
                keep.append(clause)

    # Remove the stock camera-pool tail that may have been captured in a preceding
    # section by older serialized persona strings.
    cleaned = []
    seen = set()
    for clause in keep:
        if clause.startswith("本批次仅从上述允许镜头池") or "允许镜头池仅作为硬限制" in clause:
            continue
        key = re.sub(r"[\s，,。；;：:]", "", clause)
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(clause)
    return "；".join(cleaned)

def _normalize_dynamic_prompt(raw_prompt: str, dialogue: str = "") -> str:
    """Return GPT's dynamic-only text with one exact dialogue placeholder at the end.

    Any accidental text after 文案： is discarded.  If the model copied the exact
    dialogue elsewhere, remove that duplicate locally before saving the skeleton.
    """
    text = str(raw_prompt or "").strip()
    match = re.search(r"文案\s*[:：]", text)
    if match:
        text = text[:match.start()].rstrip(" \n\t；;，,。:.：")
    dialogue = str(dialogue or "").strip()
    if dialogue and dialogue in text:
        text = text.replace(dialogue, "").strip()
    return (text + ("\n" if text else "") + DIALOGUE_MARKER)


def _is_praying(seg) -> bool:
    try:
        return str((seg.get("performance_mode") if hasattr(seg, "get") else seg["performance_mode"]) or "").upper() == "PRAYING"
    except Exception:
        return False


_PRAYING_FINAL_CAMERA_LIMIT = (
    "【闭眼祷告镜头限制】全程不得从正面拍摄人物；镜头只能位于人物侧面、侧前（与正面至少30度）或侧后；"
    "环绕或移动只能在人物同一侧进行，不得经过或停在正面。"
)


def assemble_final_flow_prompt(*, dynamic_prompt: str, dialogue: str, base_template: str = "",
                               host_rule: str = "", image_rule: str = "", segment_rule: str = "",
                               motion_rule: str = "", motion_safety_rule: str = "", camera_rule: str = "",
                               praying: bool = False) -> str:
    """Deterministically assemble the Flow prompt without spending GPT output tokens."""
    skeleton = _normalize_dynamic_prompt(dynamic_prompt, dialogue)
    # Fill only the exact terminal marker produced/normalized above.
    prefix = skeleton[:-len(DIALOGUE_MARKER)] if skeleton.endswith(DIALOGUE_MARKER) else skeleton
    parts = [prefix.rstrip(), f"{DIALOGUE_MARKER}{str(dialogue or '').strip()}"]
    template = str(base_template or "").strip()
    host = str(host_rule or "").strip()
    image = str(image_rule or "").strip()
    segment = str(segment_rule or "").strip()
    motion = str(motion_rule or "").strip()
    motion_safety = str(motion_safety_rule or "").strip()
    if template:
        parts.append("【基础模板固定要求】" + template)
    if host:
        compact_host = _compact_host_fixed_rule(host)
        if compact_host:
            parts.append("【人物固定硬约束】" + compact_host)
    if motion:
        parts.append("【自动匹配人物动作预设】" + motion)
    if camera_rule:
        parts.append("【镜头调度执行要求】" + str(camera_rule).strip())
    if motion_safety:
        parts.append("【参考图动作安全约束】" + motion_safety)
    if image:
        parts.append("【图片特殊要求】" + image)
    if segment:
        parts.append("【片段补充要求】" + segment)
    parts.append(_local_flow_execution_guard())
    if praying:
        parts.append(_PRAYING_FINAL_CAMERA_LIMIT)   # last line: closed-eye prayer is never shot from the front
    return "\n".join(x for x in parts if x).strip()


def generate_prompt(*, model, core_prompt, task, timeout=120):
    api_key = next_api_key()
    if not api_key:
        raise RuntimeError("尚未设置 OpenAI API Key。请先进入“AI 设置”。")

    stable_prefix = (
        "【Flow Studio 固定核心规则】\n"
        + core_prompt.strip()
        + "\n\n" + _prompt_completeness_guard()
        + "\n\n【固定输出要求】\n"
          "只输出一条最终 Flow 提示词，不添加标题、编号、解释或总结。\n"
    )

    dynamic_text = (
        "\n【当前主播】\n" + (task.get("host_name") or "") +
        "\n\n【当前主播人物设置｜强制执行】\n" + (task.get("host_rule") or "无额外规则") +
        "\n人物动作、镜头调度策略和允许镜头池为硬约束；最终提示词必须明确体现实际人物动作和实际采用镜头，且不得使用未允许镜头。" +
        "\n\n【当前图片特殊要求】\n" + (task.get("image_rule") or "无额外规则") +
        "\n\n【当前片段补充要求】\n" + (task.get("segment_rule") or "无额外规则") +
        "\n\n【当前完整文案】\n" + (task.get("foreign_text") or "") +
        "\n\n请结合参考图和以上规则生成最终 Flow 提示词。"
    )

    content = [
        {"type": "input_text", "text": stable_prefix},
        {"type": "input_text", "text": dynamic_text},
    ]

    request_task_ids = str(task.get("segment_id",task.get("video_id","")))
    image_url = _image_data_url(task.get("image_path") or "", task.get("segment_id", task.get("video_id", "")))
    if image_url:
        content.append({"type": "input_image", "image_url": image_url})

    cache_hash = hashlib.sha256(
        (model + "\n" + stable_prefix).encode("utf-8")
    ).hexdigest()[:32]

    payload = {
        "model": model,
        "input": [{
            "role": "user",
            "content": content
        }],
        "prompt_cache_key": "flowstudio-" + cache_hash,
        "reasoning": {"effort": "none"},
        "text": {"verbosity": "medium"},
        "max_output_tokens": 1800,
        "store": False
    }

    from app.services.image_assets import log as image_log
    image_count = sum(part.get('type') == 'input_image' for message in payload['input'] for part in message.get('content', []) if isinstance(part, dict))
    if not image_count:
        raise ValueError('图片未加入请求，已阻止提交')
    image_log.info('[GPT_IMAGE_REQUEST] task=%s request_contains_image=true image_count=%d encoding=ok', request_task_ids,image_count)
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {body[:1200]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 OpenAI API：{exc}") from exc

    text = _extract_output_text(data)
    if not text:
        raise RuntimeError("API 返回成功，但没有读取到提示词文本。")

    usage = data.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    details = usage.get("input_tokens_details") or {}
    cached_tokens = int(details.get("cached_tokens") or 0)
    cost = calculate_cost(model, input_tokens, cached_tokens, output_tokens)

    return {
        "text": text,
        "response_id": data.get("id", ""),
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
    }


def generate_prompts_for_image(*, model, core_prompt, group, image_detail="low", timeout=180, on_request=None):
    """
    One request = one reference image + all selected Flow segments under it.

    Input-cost optimizations:
    - reference image appears exactly once;
    - core rules appear exactly once;
    - empty batch/image/segment rules are omitted;
    - segment payload uses compact keys;
    - image detail is configurable (default: low).
    """
    api_key = next_api_key()
    if not api_key:
        raise RuntimeError("尚未设置 OpenAI API Key。请先进入“AI 设置”。")

    segments = list(group.get("segments") or [])
    if not segments:
        raise ValueError("当前图片没有可生成的 Flow 片段。")

    detail = image_detail if image_detail in ("low", "auto", "high") else "low"
    auto_action_match = bool(group.get("auto_action_match", True))
    action_catalog = _motion_catalog(group)
    camera_catalog = group.get("camera_presets", [])
    from app.services import camera_motion
    any_praying = any(_is_praying(seg) for seg in segments)
    if any_praying:
        # Presets (e.g. a plain orbit) may not forbid frontal shots; closed-eye prayer must never be shot face-on.
        camera_catalog = [
            dict(c, prompt=str(c.get("prompt", "")).rstrip(" 。.") + "。" + camera_motion.PRAYING_CATALOG_SUFFIX)
            if "正面" not in str(c.get("prompt", "")) else c
            for c in camera_catalog
        ]

    # Stable prefix kept identical across requests to maximize prompt-cache reuse.
    # Append a mandatory coverage guard after the editable core/base template so
    # "keep it concise" can never be interpreted as "drop execution rules".
    from app.services import camera_motion
    stable_text = camera_motion.clean(core_prompt.strip()) + "\n\n" + _dynamic_prompt_generation_guard() + "\n" + camera_motion.INSTRUCTIONS

    # Only include non-empty shared rules.
    shared_parts = []
    host_rule = (group.get("host_rule") or "").strip()
    image_rule = (group.get("image_rule") or "").strip()
    if host_rule:
        if auto_action_match:
            shared_parts.append(
                "【当前主播人物设置｜强制执行】\n" + host_rule +
                "\n执行要求：表演风格、镜头调度策略、策略内部规则、允许镜头池和人物自定义硬限制必须执行。"
                "人物动作按钮仅作为候选池，不得把全部候选动作同时执行；必须结合参考图只选择安全且匹配的候选预设。"
                "实际镜头只能从允许镜头池中选择，不得自行加入未选镜头。"
                "当前人物设置与镜头限制覆盖核心默认摄影/动作组合中的冲突项，不得被默认规则替换。"
            )
        else:
            shared_parts.append(
                "【当前主播人物设置｜强制执行】\n" + host_rule +
                "\n执行要求：以上人物动作、镜头调度策略、策略内部规则和允许镜头池均为本批硬约束。"
                "每个片段的最终提示词必须明确体现当前已选人物动作，并明确写出本片段实际采用的镜头方式；"
                "实际镜头只能从允许镜头池中选择，不得自行加入未选镜头。"
                "当前人物设置与镜头限制覆盖核心默认摄影/动作组合中的冲突项，不得被默认规则替换。"
            )
    if image_rule:
        shared_parts.append("当前图片特殊要求：" + image_rule)
    if camera_catalog:
        shared_parts.append(
            "镜头候选预设 camera_catalog (JSON)：" + json.dumps(camera_catalog, ensure_ascii=False, separators=(",", ":")) +
            "\n你必须根据文案情感和策略，从上述目录中为每个片段挑选最合适的镜头，不可全部使用相同的镜头。只能使用这里提供的预设ID。"
        )
    if auto_action_match:
        shared_parts.append(
            "动作候选预设(JSON)：" + json.dumps(action_catalog, ensure_ascii=False, separators=(",", ":")) +
            "\n自动匹配规则：先对本请求唯一参考图做一次整体判断，识别身体姿态、左右手是否被物品占用、是否双手占用、是否正在操作物品、是否为祷告姿态。"
            "然后只从上述候选预设中选择一个或多个互不冲突、最安全的预设；不得因为文案需要表达而无视参考图的手部/道具状态。"
            "双手占用或正在操作物品时禁止选择要求自由手势/挥手/指向/大幅手部动作的预设；单手占用时禁止让被占用手参与说话手势；"
            "坐姿不得选择走动/起身类预设；无法可靠判断或候选均冲突时选择 __SAFE_STATIC__。"
        )

    # Compact segment structure. No duplicated task_id / verbose field names.
    compact_segments = []
    for seg in segments:
        row = {
            "id": str(seg["segment_id"]),
            "text": (seg.get("foreign_text") or "").strip(),
            "performance_mode": seg.get("performance_mode") or "TALKING",
        }
        rule = (seg.get("segment_rule") or "").strip()
        if rule:
            row["rule"] = rule
        compact_segments.append(row)

    dynamic_parts = []
    if shared_parts:
        dynamic_parts.append("\n".join(shared_parts))
    dynamic_parts.append(
        "片段数据(JSON)：\n" + json.dumps(
            compact_segments,
            ensure_ascii=False,
            separators=(",", ":")
        )
    )
    if auto_action_match:
        dynamic_parts.append(
            "先完成一次且仅一次参考图动作状态判断，并在 motion_selection 中返回结果；该选择对当前图片下全部片段共享。"
            "selected_action_ids 只能来自动作候选预设 id 或 __SAFE_STATIC__，可选择多个但必须互不冲突。"
            "然后为每个 id 生成一条动态提示词，严格一一对应。只写本片段需要 GPT 判断的动态信息："
            "情绪/表演、在已选动作预设约束下的实际动作细节、实际镜头执行细节、必要环境动态和说话状态。"
            "若选中走动/跟拍/环绕/推进等运动，必须写成明确强制执行的真实位移：人物注明方向和连续步伐，"
            "摄影机注明起始角度、移动方向、持续位移和空间视差；人物与镜头需要同时运动时必须明确同时持续发生。"
            "【注意】你必须从 camera_catalog 中选择合适的镜头，只在 camera_id 返回其 ID，绝对不要在 prompt 中把镜头预设英文抄写出来。"
            "不要复述候选预设全文、共享固定规则或文案正文。每条 prompt 必须以“文案： ”结束，且其后不得再有任何内容。"
        )
    else:
        dynamic_parts.append(
            "动作自动匹配已关闭：motion_selection 只返回 MANUAL/空选择，不重新选择人物动作。"
            "为每个 id 生成一条动态提示词，严格一一对应。只写本片段需要 GPT 判断的动态信息："
            "情绪/表演、实际动作及细节、实际镜头执行细节、必要环境动态和说话状态。"
            "若选中走动/跟拍/环绕/推进等运动，必须写成明确强制执行的真实位移。"
            "【注意】你必须从 camera_catalog 中选择合适的镜头，只在 camera_id 返回其 ID，绝对不要在 prompt 中把镜头预设英文抄写出来。"
            "不要复述共享固定规则，不要输出文案正文。每条 prompt 必须以“文案： ”结束，且其后不得再有任何内容。对于不同 performance_mode 的片段，请严格遵守其对应模式的基础模板和设定（例如TALKING遵守睁眼正常交流，PRAYING遵守闭眼祈祷），绝不混淆！"
        )
    dynamic_parts.append(camera_motion.INSTRUCTIONS + " Auxiliary images are DISABLED for this group.")
    if any_praying:
        dynamic_parts.append(camera_motion.PRAYING_INSTRUCTIONS)
    dynamic_text = "\n\n".join(dynamic_parts)

    # Put the stable instruction in a developer message, dynamic task + image in user.
    # The image is sent once for the whole group.
    user_content = [{"type": "input_text", "text": dynamic_text}]
    request_task_ids = ",".join(str(s.get("segment_id","")) for s in segments)
    image_url = _image_data_url(group.get("image_path") or "", ",".join(str(s.get("segment_id", "")) for s in segments))
    if image_url:
        user_content.append({
            "type": "input_image",
            "image_url": image_url,
            "detail": detail,
        })

    cache_hash = hashlib.sha256(
        (model + "\n" + stable_text).encode("utf-8")
    ).hexdigest()[:32]

    allowed_action_ids = [str(x["id"]) for x in action_catalog]
    if SAFE_STATIC_ACTION_ID not in allowed_action_ids:
        allowed_action_ids.append(SAFE_STATIC_ACTION_ID)
    schema = {
        "type": "object",
        "properties": {
            "motion_selection": {
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean"},
                    "posture": {"type": "string", "enum": ["standing", "seated", "walking", "crouching", "lying", "uncertain"]},
                    "hand_state": {"type": "string", "enum": ["free", "left_occupied", "right_occupied", "both_occupied", "uncertain"]},
                    "object_interaction": {"type": "boolean"},
                    "praying_pose": {"type": "boolean"},
                    "selected_action_ids": {
                        "type": "array",
                        "items": {"type": "string", "enum": allowed_action_ids},
                    },
                    "reason_code": {"type": "string", "enum": list(_MOTION_REASON_CODES)},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["enabled", "posture", "hand_state", "object_interaction", "praying_pose", "selected_action_ids", "reason_code", "confidence"],
                "additionalProperties": False,
            },
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "prompt": {"type": "string"},
                        "camera_id": {"type": "string"},
                        "camera_motion": camera_motion.SCHEMA,
                    },
                    "required": ["id", "prompt", "camera_id", "camera_motion"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["motion_selection", "results"],
        "additionalProperties": False,
    }

    # Complete per-segment prompts now explicitly restate all execution-critical
    # constraints. Allow enough room so the model never has to compress them away.
    # Billing remains based on actual output tokens.
    # The configured GPT-5.6 models support very large outputs. Prefer one complete
    # response for an entire image group instead of forcing tiny request chunks.
    # This is a budget ceiling only; usage/cost is based on tokens actually returned.
    max_output = min(30000, max(3000, 850 * len(segments)))

    payload = {
        "model": model,
        "input": [
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": stable_text}],
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
        "prompt_cache_key": "flowstudio-core-" + cache_hash,
        "reasoning": {"effort": "none"},
        "text": {
            "verbosity": "low",
            "format": {
                "type": "json_schema",
                "name": "flow_prompt_batch",
                "strict": True,
                "schema": schema,
            },
        },
        "max_output_tokens": max_output,
        "store": False,
    }

    from app.services.image_assets import log as image_log
    image_count = sum(part.get('type') == 'input_image' for message in payload['input'] for part in message.get('content', []) if isinstance(part, dict))
    if not image_count:
        raise ValueError('图片未加入请求，已阻止提交')
    image_log.info('[GPT_IMAGE_REQUEST] task=%s request_contains_image=true image_count=%d encoding=ok', request_task_ids,image_count)
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    if on_request:
        try:
            on_request({
                "segment_count": len(segments),
                "max_output_tokens": max_output,
                "timeout": timeout,
            })
        except Exception:
            pass

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {body[:1600]}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError(f"OpenAI API 请求超时（等待 {int(timeout)} 秒仍未返回）") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
            raise RuntimeError(f"OpenAI API 请求超时（等待 {int(timeout)} 秒仍未返回）") from exc
        raise RuntimeError(f"无法连接 OpenAI API：{exc}") from exc

    output_text = _extract_output_text(data)
    if not output_text:
        raise RuntimeError("API 返回成功，但没有读取到批量提示词结果。")

    try:
        parsed = json.loads(output_text)
        result_rows = parsed.get("results") or []
    except Exception as exc:
        raise RuntimeError("API 返回内容不是可解析的结构化批量结果。") from exc

    motion_selection = _sanitize_motion_selection(
        parsed.get("motion_selection") or {}, action_catalog, auto_enabled=auto_action_match
    )

    dynamic_map = {}
    camera_plans = {}
    cam_map = {}
    cam_dict = {str(c['id']): str(c.get('prompt', '')) for c in camera_catalog}
    for row in result_rows:
        sid = str(row.get("id") or "")
        prompt = str(row.get("prompt") or "")
        cam_id = str(row.get("camera_id") or "")
        cp = camera_motion.normalize(row.get("camera_motion"))
        camera_plans[sid] = cp
        
        if sid and prompt.strip():
            dynamic_map[sid] = prompt
            if cam_id and cam_id in cam_dict:
                cam_map[sid] = cam_dict[cam_id]

    missing = [
        str(seg["segment_id"]) for seg in segments
        if str(seg["segment_id"]) not in dynamic_map
    ]
    if missing:
        raise RuntimeError("批量结果缺少片段：" + ", ".join(missing[:20]))

    # GPT returns only dynamic decisions.  Studio inserts the exact dialogue and
    # appends all deterministic rules locally, so output tokens are not wasted
    # repeating the same constraints dozens of times.
    base_template = str(group.get("template_snapshot") or "").strip()
    result_map = {}
    normalized_dynamic_map = {}
    segment_by_id = {str(seg["segment_id"]): seg for seg in segments}
    for sid, raw_prompt in dynamic_map.items():
        seg = segment_by_id[sid]
        dialogue = str(seg.get("foreign_text") or "").strip()
        normalized_dynamic = _normalize_dynamic_prompt(raw_prompt, dialogue)
        normalized_dynamic_map[sid] = normalized_dynamic
        seg_praying = _is_praying(seg)
        if seg_praying:
            camera_plans[sid], front_reason = camera_motion.enforce_praying(camera_plans[sid])
            if front_reason:
                try:
                    from app.services.runtime_log import log as _rlog
                    _rlog("praying_front_camera_corrected", level="WARNING", segment_id=sid, reason=front_reason)
                except Exception:
                    pass
        result_map[sid] = assemble_final_flow_prompt(
            dynamic_prompt=normalized_dynamic,
            dialogue=dialogue,
            base_template=base_template,
            host_rule=host_rule,
            image_rule=image_rule,
            segment_rule=str(seg.get("segment_rule") or "").strip(),
            motion_rule=motion_selection.get("preset_rule", "") if auto_action_match else "",
            motion_safety_rule=motion_selection.get("safety_rule", "") if auto_action_match else "",
            camera_rule=camera_motion.block(camera_plans[sid], praying=seg_praying),
            praying=seg_praying,
        )

    for sid in result_map:
        if camera_plans[sid]["enabled"]: result_map[sid] = camera_motion.clean_preserving_dialogue(result_map[sid], str(segment_by_id[sid].get("foreign_text") or "").strip())

    try:
        from app.services.runtime_log import log as runtime_log
        runtime_log(
            "GPT_AUTO_MOTION_PRESET",
            video_id=group.get("video_id"), host_id=group.get("host_id"),
            image_path=str(group.get("image_path") or ""),
            auto_enabled=bool(auto_action_match),
            selected_action_ids=motion_selection.get("selected_action_ids", []),
            selected_action_names=motion_selection.get("selected_action_names", []),
            posture=motion_selection.get("posture"), hand_state=motion_selection.get("hand_state"),
            object_interaction=motion_selection.get("object_interaction"), praying_pose=motion_selection.get("praying_pose"),
            reason_code=motion_selection.get("reason_code"), confidence=motion_selection.get("confidence"),
        )
    except Exception:
        pass

    usage = data.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    details = usage.get("input_tokens_details") or {}
    cached_tokens = int(details.get("cached_tokens") or 0)
    cost = calculate_cost(model, input_tokens, cached_tokens, output_tokens)

    return {
        "prompts": result_map,
        "ai_prompts": normalized_dynamic_map,
        "response_id": data.get("id", ""),
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
        "request_count": 1,
        "image_detail": detail,
        "motion_selection": motion_selection,
        "camera_plans": camera_plans,
    }




def generate_enhanced_prompts(*, model, core_prompt, group, config, preset_snapshot, timeout=180, image_detail="low", on_request=None):
    """Plan camera endpoints in one text request; image generation stays in Flow."""
    def obj(properties):
        return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    string={'type':'string'}
    strings={'type':'array','items':string}
    video=obj({'SEGMENT_ID':string,'VIDEO_PROMPT':string,'camera_motion':camera_motion.SCHEMA,
               'IMAGE_BINDING':obj({'START_IMAGE':string,'END_IMAGE':string})})
    shot=obj({'SHOT_ID':string,'IMAGE_PROMPT':string,'PURPOSE':string,'USED_BY':strings})
    schema=obj({'VIDEO_PLAN':{'type':'array','items':video},'IMAGE_PLAN':{'type':'array','items':shot}})
    segments=list(group.get('segments') or [])
    image=_image_data_url(group.get('image_path') or '', ','.join(str(x['segment_id']) for x in segments))
    if not image:raise ValueError('图片未加入请求，已阻止提交')
    instruction=(core_prompt+'\n'+camera_motion.INSTRUCTIONS+'\n'+camera_motion.PRAYING_INSTRUCTIONS+
      '\nReturn VIDEO_PLAN for every segment. For strong camera moves requiring a new viewpoint, return a SHOT_001-style '
      'IMAGE_PLAN endpoint prompt and bind START_IMAGE=MASTER, END_IMAGE=its SHOT_ID. Otherwise END_IMAGE is empty. '
      'Do not change dialogue. Image prompts must retain the same person, clothing and scene. Maximum auxiliary images: '+str(int(config.get('camera_limit') or 0)))
    payload={'model':model,'store':False,'input':[{'role':'developer','content':instruction},
      {'role':'user','content':[{'type':'input_text','text':json.dumps(segments,ensure_ascii=False)},
       {'type':'input_image','image_url':image,'detail':image_detail}]}],
      'text':{'format':{'type':'json_schema','name':'camera_endpoint_plan','strict':True,'schema':schema}},
      'max_output_tokens':min(30000,max(3000,1000*len(segments)))}
    req=urllib.request.Request(API_URL,data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+next_api_key(),'Content-Type':'application/json'},method='POST')
    if on_request:on_request({'segment_count':len(segments)})
    with urllib.request.urlopen(req,timeout=timeout) as response:data=json.loads(response.read().decode())
    if data.get('status')=='incomplete':raise RuntimeError('辅助图规划返回不完整，请检查后重试')
    plan=json.loads(_extract_output_text(data))
    camera_motion.prepare_review_draft(plan,segments)
    if len(plan.get('IMAGE_PLAN') or [])>int(config.get('camera_limit') or 0):raise ValueError('运镜方案：辅助图片数量超过设置上限')
    prompts={};original={};by_id={str(x['segment_id']):x for x in segments}
    for item in plan['VIDEO_PLAN']:
        sid=str(item['SEGMENT_ID']);seg=by_id[sid];cp=item.get('camera_motion') or {}
        if _is_praying(seg):cp,_=camera_motion.enforce_praying(cp);item['camera_motion']=cp
        text=str(item.get('VIDEO_PROMPT') or '')
        original[sid]=text
        prompts[sid]=assemble_final_flow_prompt(dynamic_prompt=camera_motion.clean(text),dialogue=str(seg.get('foreign_text') or ''),
            base_template=str(group.get('template_snapshot') or core_prompt),host_rule=str(group.get('host_rule') or ''),
            image_rule=str(group.get('image_rule') or ''),segment_rule=str(seg.get('segment_rule') or ''),
            camera_rule=camera_motion.review_camera_block(cp),praying=_is_praying(seg))
    usage=data.get('usage') or {};inp=int(usage.get('input_tokens') or 0);out=int(usage.get('output_tokens') or 0)
    cached=int((usage.get('input_tokens_details') or {}).get('cached_tokens') or 0)
    return {'prompts':prompts,'ai_prompts':original,'data':plan,'input_tokens':inp,'output_tokens':out,'cached_tokens':cached,
       'cost_usd':calculate_cost(model,inp,cached,out),'request_count':1}
