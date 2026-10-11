from __future__ import annotations

import base64
import json
import mimetypes
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.core import repository as repo
from app.services.openai_service import API_URL, get_api_key, calculate_cost
from app.services.media_qc import extract_four_qc_frames
from app.services import runtime_log


def _data_url(path: str) -> str:
    p = Path(path); mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode('ascii')}"


def _output_text(data: dict) -> str:
    if data.get("output_text"):
        return str(data["output_text"])
    chunks=[]
    for item in data.get("output",[]):
        for content in item.get("content",[]):
            if content.get("type") == "output_text": chunks.append(content.get("text", ""))
    return "\n".join(chunks)


def run_ai_qc(segment_id: int, video_path: str, reference_image: str, target_text: str, prompt_text: str, speech: dict[str, Any]) -> dict[str, Any]:
    """AI first-pass QC. Exactly four frames are sent, all within Whisper speech range."""
    key = get_api_key()
    if not key:
        raise RuntimeError("尚未设置 OpenAI API Key")
    st, en = speech.get("speech_start"), speech.get("speech_end")
    qc_dir = Path(video_path).parent/".flowstudio_qc"/f"S{int(segment_id):06d}"
    frames = extract_four_qc_frames(video_path, st, en, qc_dir)

    model = str(repo.get_setting("ai_qc_model", "gpt-5.6-luna") or "gpt-5.6-luna")
    rules = str(repo.get_setting("ai_qc_global_rules", "") or "").strip()
    schema = {
        "type":"object","properties":{
            "light":{"type":"string","enum":["green","yellow","red"]},
            "summary":{"type":"string"},
            "issues":{"type":"array","items":{"type":"object","properties":{
                "category":{"type":"string"},"severity":{"type":"string","enum":["low","medium","high"]},
                "confidence":{"type":"number"},"time":{"type":"number"},"message":{"type":"string"}
            },"required":["category","severity","confidence","time","message"],"additionalProperties":False}}
        },"required":["light","summary","issues"],"additionalProperties":False
    }
    text = (
        "你是 Flow Studio 的AI视觉初检员。只根据四张来自有效说话区间的画面、参考图、指定文案、Flow提示词和Whisper时间信息判断视觉问题。"
        "重点检查：人物身份/脸部稳定、手和身体异常、手持物/麦克风/雕像变化、嘴部明显异常、场景连续性、提示词明确禁止/必须出现的内容。"
        "不要因为正常硬切/运镜而报错。四张图无法证明的动态问题不要臆测；不要判断背景音乐、噪声或混响，因为这里没有向模型发送音频。"
        "green=未发现明显问题；yellow=存在可疑但不确定；red=高置信度明显不可用。AI只做第一遍，不决定返工。"
        f"\n全局QC规则：{rules or '无'}"
        f"\n指定文案：{target_text}"
        f"\nFlow提示词：{prompt_text}"
        f"\nWhisper匹配率：{speech.get('match_score',0):.3f}；有效区间：{st:.3f}-{en:.3f}s"
        f"\n四帧时间点：{', '.join(str(x['time']) for x in frames)}"
    )
    content=[{"type":"input_text","text":text}]
    if reference_image and Path(reference_image).is_file():
        content.append({"type":"input_image","image_url":_data_url(reference_image),"detail":"low"})
    for f in frames:
        content.append({"type":"input_image","image_url":_data_url(f["path"]),"detail":"low"})
    payload={
        "model":model,
        "input":[{"role":"user","content":content}],
        "reasoning":{"effort":"none"},
        "text":{"verbosity":"low","format":{"type":"json_schema","name":"flowstudio_ai_qc","strict":True,"schema":schema}},
        "max_output_tokens":900,"store":False
    }
    req=urllib.request.Request(API_URL,data=json.dumps(payload).encode(),headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=120) as resp:
            data=json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body=exc.read().decode(errors="replace")
        raise RuntimeError(f"AI质检 HTTP {exc.code}: {body[:1200]}") from exc
    result=json.loads(_output_text(data) or "{}")
    usage=data.get("usage") or {}; details=usage.get("input_tokens_details") or {}
    cost=calculate_cost(model,int(usage.get("input_tokens") or 0),int(details.get("cached_tokens") or 0),int(usage.get("output_tokens") or 0))
    result.update({"frames":frames,"model":model,"cost_usd":cost,"response_id":data.get("id","") ,"checked_at":time.time()})
    repo.save_ai_qc_result(segment_id,result)
    repo.log_api_usage(segment_id,model,int(usage.get("input_tokens") or 0),int(details.get("cached_tokens") or 0),int(usage.get("output_tokens") or 0),cost)
    runtime_log.log("ai_qc_finished",segment_id=segment_id,light=result.get("light"),issues=len(result.get("issues") or []),cost=cost)
    return result
