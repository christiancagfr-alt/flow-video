"""Presentation only: never changes persistent task/recovery state."""
from __future__ import annotations

import re

from app.services.flow_error_guide import diagnose_flow_error

TEMPORARY = re.compile(
    r"REFERENCE_STATE_NOT_DETECTED|FLOW_GENERATE_BUTTON_NOT_READY|MAIN_ENGINE_TIMEOUT"
    r"|SUBMIT(?:TED|SION)?_(?:NOT_CONFIRMED|UNCONFIRMED)|FIRST_FRAME_NOT_CONFIRMED",
    re.I,
)
PROMPT = re.compile(
    r"PROMPT_(?:REJECTED|INVALID|FORMAT|POLICY)|CONTENT_POLICY|SAFETY_FILTER"
    r"|PUBLIC_ERROR_UNSAFE|PROMINENT_PEOPLE|违反.{0,8}(?:内容|政策)"
    r"|提示词格式|提示词.{0,8}(?:拒绝|违规)|内容政策",
    re.I,
)


def upload_skipped(task) -> bool:
    """Image upload failed 3x in the plugin and the task was skipped: manual retry only."""
    raw = str(task.get("flow_error") or "")
    return task.get("flow_status") == "失败" and "图片上传失败" in raw and "跳过" in raw


def needs_prompt(task) -> bool:
    return task.get("flow_status") in ("失败", "下载失败") and bool(
        PROMPT.search(str(task.get("flow_error") or ""))
    )


def error_view(task, recovery):
    raw = str(task.get("flow_error") or "")
    status = str(task.get("flow_status") or "")
    history = int((recovery or {}).get("failures") or 0)
    if status in ("已提交", "生成中", "下载中", "已完成"):
        if not raw and not history:
            return status, 0, "", ""
        info = diagnose_flow_error(raw, status=status) if raw else None
        cn_line = f"{info.title}（{raw}）" if info else ""
        detail = f"历史失败记录：{history}\n{cn_line}".strip()
        return status, 0, info.title if info else "", detail

    label = (
        "需修改提示词"
        if needs_prompt(task)
        else ("图片上传失败·已跳过" if upload_skipped(task) else status)
    )
    info = diagnose_flow_error(
        raw,
        status=status,
        channel_key=str(task.get("flow_channel_key") or ""),
        host_name=str(task.get("host_name") or ""),
        seg_code=(
            f"{int(task['video_seq']):02d}-{int(task['seg_seq']):02d}"
            if task.get("video_seq") is not None and task.get("seg_seq") is not None
            else ""
        ),
        retry_count=int(task.get("flow_retry_count") or history or 0),
    )
    reason = info.inline_text
    if not raw:
        detail = (
            "Flow 未返回具体失败原因；请查看任务详情中的最近派发记录。"
            if status in ("失败", "下载失败")
            else "暂无错误回执。"
        )
    else:
        sol_lines = "\n".join(f"  {idx}. {s}" for idx, s in enumerate(info.solutions, 1))
        detail = (
            f"【中文诊断】{info.title}\n"
            f"【原因说明】{info.cause}\n"
            f"【建议解决】\n{sol_lines}\n"
            f"【原始错误码】{raw}"
        )
    return label, history, reason, detail
