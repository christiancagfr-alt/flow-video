"""Comprehensive Chinese diagnostic & solution guide for Flow Generation Center, Browser Plugin, LLM, and Network errors.

Internal database/protocol codes remain untouched; all user-facing strings are
translated into plain Chinese with root-cause explanations and step-by-step solutions.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.services.resolve_error_guide import EditingErrorInfo


_FILE_SUFFIX_RE = re.compile(r":\s*([^\s:;/\\]+\.(?:jpg|jpeg|png|webp|mp4|wav|mov))", re.I)
_ENG_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")


def _extract_filename(raw: str) -> str:
    m = _FILE_SUFFIX_RE.search(raw or "")
    if m:
        return m.group(1)
    if ":" in (raw or ""):
        tail = raw.split(":", 1)[1].strip()
        if tail and len(tail) <= 90 and not tail.startswith("{"):
            return Path(tail).name
    return ""


def diagnose_flow_error(
    raw_error: str,
    *,
    status: str = "",
    channel_key: str = "",
    host_name: str = "",
    seg_code: str = "",
    retry_count: int = 0,
) -> EditingErrorInfo:
    """Translate any Flow / Browser / API / Python error into structured Chinese ``EditingErrorInfo``."""
    raw = str(raw_error or "").strip()
    st = str(status or "").strip()

    # Strip abandon wrapper prefix if present while preserving context
    abandon_prefix = ""
    core_raw = raw
    if "；原错误：" in core_raw:
        parts = core_raw.split("；原错误：")
        abandon_prefix = parts[0].strip()
        core_raw = parts[-1].strip()
        if core_raw in ("未提供", ""):
            core_raw = ""

    upper = core_raw.upper()
    fname = _extract_filename(core_raw)

    loc_items: list[tuple[str, str]] = []
    if host_name or seg_code:
        loc_items.append(("所属任务", " · ".join(x for x in (host_name, f"片段 {seg_code}" if seg_code else "") if x)))
    if channel_key:
        loc_items.append(("执行通道", channel_key))
    if fname:
        loc_items.append(("涉及文件", fname))
    if retry_count > 0:
        loc_items.append(("已重试次数", f"{retry_count} 次"))

    # ── 1. Google Labs / Flow Cloud API Public Errors ──────────────────────
    if "PUBLIC_ERROR_UNUSUAL_ACTIVITY_TOO_MUCH_TRAFFIC" in upper or "TOO_MUCH_TRAFFIC" in upper:
        return EditingErrorInfo(
            code="PUBLIC_ERROR_UNUSUAL_ACTIVITY_TOO_MUCH_TRAFFIC",
            stage_label="Google 云端限流",
            title="当前 Google 账号或网络节点并发流量过高，触发临时限流",
            inline_text="Google 账号/网络流量过高被临时限流 · 建议换通道或稍等再试",
            cause=(
                "Google Flow 云端检测到当前通道绑定的 Google 账号或代理网络节点在短时间内发送了过多生成请求，"
                "触发了流量保护限制（TOO_MUCH_TRAFFIC）。本次任务未扣减有效成片。"
            ),
            solutions=[
                "在该任务行的通道下拉框中选择其他空闲通道（或顶部选择「自动分配空闲通道」），点击「↻」重试；",
                "如果多个通道同时报此错误，说明当前代理/VPN 节点 IP 被 Google 临时限流，请切换代理节点；",
                "暂停该通道 5～10 分钟后再恢复派发，避免连续高频触发风控。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if "PUBLIC_ERROR_UNUSUAL_ACTIVITY" in upper or "UNUSUAL_ACTIVITY" in upper:
        return EditingErrorInfo(
            code="PUBLIC_ERROR_UNUSUAL_ACTIVITY",
            stage_label="Google 账号/网络风控",
            title="Google 检测到当前账号或网络异常活动，请求被风控拦截",
            inline_text="Google 检测到操作频繁触发风控拦截 · 建议切换其他通道或更换网络节点重试",
            cause=(
                "Google Flow 安全系统判定当前浏览器通道的 Google 账号或网络 IP 存在高频自动化特征或异常活动"
                "（PUBLIC_ERROR_UNUSUAL_ACTIVITY），因此临时拒绝了本次视频生成请求。"
            ),
            solutions=[
                "优先在该行将通道切换为其他空闲通道（更换另一个 Google 账号窗口），然后点击右侧「↻」重试；",
                "打开报错通道对应的 Chrome 浏览器窗口，刷新一次 Google Flow 页面，确认账号未弹出验证码或异常提示；",
                "若所有通道均报此错，请切换你的 VPN / 代理网络节点 IP，或休息 5～15 分钟后再批量重试。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if "PUBLIC_ERROR_PROMINENT_PEOPLE" in upper or "PROMINENT_PEOPLE" in upper:
        return EditingErrorInfo(
            code="PUBLIC_ERROR_PROMINENT_PEOPLE_FILTER_FAILED",
            stage_label="人物肖像与合规过滤",
            title="触发 Google 公众人物/敏感人脸安全过滤",
            inline_text="触发 Google 公众人物/敏感肖像过滤 · 建议点击「✎」微调提示词或更换参考图",
            cause=(
                "Google Flow 的人物合规过滤器认为当前参考图或提示词涉及真实公众人物、名人肖像或受保护人脸特征"
                "（PUBLIC_ERROR_PROMINENT_PEOPLE_FILTER_FAILED），从而拦截了本次生成。"
            ),
            solutions=[
                "点击该行右侧的「✎」按钮检查提示词，删改可能暗示真实名人、政治人物或特定现实身份的词汇后重试；",
                "如果仅偶发出现，可直接点击「↻」原词重试一次（Google 肖像检测偶有误判）；",
                "若同一位主播的所有片段全部报此错，说明该主播的参考图片本身被 Google 标记为敏感人脸，请前往「角色库」替换或微调该主播的参考图。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if "PUBLIC_ERROR_VIDEO_GENERATION_TIMED_OUT" in upper or "GENERATION_TIMED_OUT" in upper:
        return EditingErrorInfo(
            code="PUBLIC_ERROR_VIDEO_GENERATION_TIMED_OUT",
            stage_label="Google 云端算力超时",
            title="Google 云端视频渲染超时",
            inline_text="Google 云端服务器渲染超时 · 无需改词，直接点击「↻」重试即可",
            cause=(
                "任务已成功提交到 Google Flow 云端，但因 Google 服务器算力排队拥堵，未能在云端规定时间内完成渲染"
                "（PUBLIC_ERROR_VIDEO_GENERATION_TIMED_OUT）。你的提示词和参考图本身没有问题。"
            ),
            solutions=[
                "无需修改提示词，直接点击该行右侧「↻」按钮（或勾选后批量重置重试）即可恢复；",
                "建议保持顶部「自动分配空闲通道」开启，系统会自动交给当前响应最快的通道执行。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if any(
        k in upper
        for k in (
            "PUBLIC_ERROR_UNSAFE",
            "PUBLIC_ERROR_SAFETY",
            "SAFETY_FILTER",
            "CONTENT_POLICY",
            "PROMPT_REJECTED",
            "PROMPT_INVALID",
            "PROMPT_FORMAT",
            "PROMPT_POLICY",
        )
    ) or any(k in core_raw for k in ("违反", "内容政策", "提示词格式", "提示词被拒")):
        return EditingErrorInfo(
            code="PROMPT_SAFETY_FILTER",
            stage_label="提示词安全审核",
            title="提示词或画面触发了 Google 内容安全审核限制",
            inline_text="提示词触发 Google 内容安全限制 · 请点击「✎」修改敏感描述后重试",
            cause=(
                "Google Flow 安全策略拦截了当前提示词或画面描述（可能包含激烈肢体冲突、流血受伤、敏感宗教/政治字眼、"
                "未成年人特征或不符合要求的参数格式）。"
            ),
            solutions=[
                "点击该行右侧的「✎」（修改提示词并重试）按钮；",
                "将提示词中容易触发审核的激烈词汇改为温和、平实的画面动作描述；",
                "保存后系统会自动重新排入通道生成。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if any(k in upper for k in ("QUOTA_EXCEEDED", "RESOURCE_EXHAUSTED", "RATE_LIMIT", "DAILY_QUOTA", "INSUFFICIENT_QUOTA", "HTTP 429", "STATUS 429")):
        return EditingErrorInfo(
            code="QUOTA_EXCEEDED",
            stage_label="账号配额与点数限制",
            title="当前通道 Google 账号配额或今日点数已达上限",
            inline_text="当前通道账号点数/配额不足 · 请切换其他通道或更换有额度的账号",
            cause=(
                "该通道登录的 Google Flow 账号今日生成次数、点数余额或每分钟请求上限已满，无法继续生成新视频。"
            ),
            solutions=[
                "将该任务改派到其他有剩余点数的通道，点击「↻」重试；",
                "若该通道账号点数已彻底用完，可在「生产进度 -> 运行通道」暂停该通道，或在对应浏览器更换新的 Google 账号。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if any(k in upper for k in ("SERVER_UNAUTHORIZED", "UNAUTHENTICATED", "UNAUTHORIZED", "PERMISSION_DENIED", "HTTP 401", "HTTP 403")):
        return EditingErrorInfo(
            code="SERVER_UNAUTHORIZED",
            stage_label="账号登录与权限失效",
            title="通道浏览器的 Google Flow 登录状态已过期或无权限",
            inline_text="Google 账号登录过期或权限失效 · 请在对应通道浏览器重新登录并刷新页面",
            cause=(
                "浏览器向 Google Flow 发送请求时返回了未授权状态（SERVER_UNAUTHORIZED / 401 / 403），"
                "通常是因为该通道的 Google 账号退出了登录、Cookie 过期或当前项目链接无访问权限。"
            ),
            solutions=[
                "切到该通道对应的 Chrome 浏览器窗口，检查是否退出了 Google 账号；",
                "重新登录 Google Flow 并按 Cmd+R 刷新页面，确保能正常看到项目编辑界面；",
                "回到本窗口点击「↻」重新派发任务。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if upper in ("INTERNAL", "UNAVAILABLE", "BAD_GATEWAY", "GATEWAY_TIMEOUT") or any(
        k in upper for k in ("INTERNAL_ERROR", "SERVICE_UNAVAILABLE", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504")
    ):
        return EditingErrorInfo(
            code="GOOGLE_SERVER_ERROR",
            stage_label="Google 云端服务波动",
            title="Google Flow 云端服务器临时内部错误或繁忙",
            inline_text="Google 云端服务器临时故障 (INTERNAL/UNAVAILABLE) · 直接点击「↻」重试即可",
            cause=(
                "Google Flow 官方后端服务器出现了瞬时内部错误（INTERNAL / UNAVAILABLE）。"
                "这不是你本地软件或提示词的问题。"
            ),
            solutions=[
                "无需修改提示词，直接点击右侧「↻」按钮重新提交即可；",
                "若连续多次报相同错误，说明 Google 服务器正在波动，建议稍等 1～3 分钟后再批量重试。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    # ── 2. Browser Plugin Upload / Reference Image / DOM Readiness Errors ──
    if "图片上传失败" in core_raw and "跳过" in core_raw:
        return EditingErrorInfo(
            code="UPLOAD_SKIPPED_3X",
            stage_label="参考图上传跳过",
            title=f"参考图{f'（{fname}）' if fname else ''}连续上传失败已自动跳过",
            inline_text=f"参考图{f' {fname} ' if fname else ''}上传失败已跳过 · 请检查网络后点击「↻」单独重试",
            cause=(
                "网页插件尝试将该主播的参考图上传到 Google Flow 时连续失败（常见于网络波动、代理上传慢或网页卡死），"
                "为避免阻塞后续其他主播的任务，插件已自动跳过该任务。"
            ),
            solutions=[
                "点击右侧「🖼」确认本地参考图片存在且能正常打开；",
                "检查对应通道浏览器网络是否通畅，刷新一次 Flow 网页；",
                "点击右侧「↻」按钮（或勾选后点底部「↻ 重置重试」）重新上传参考图并生成。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if "IMAGE_NOT_UPLOADED" in upper or "IMAGE_UPLOAD_FAILED" in upper:
        return EditingErrorInfo(
            code="IMAGE_NOT_UPLOADED",
            stage_label="参考图上传未完成",
            title=f"参考图{f'（{fname}）' if fname else ''}未能成功上传至 Flow 网页",
            inline_text=f"参考图{f' {fname} ' if fname else ''}上传网页未成功 · 建议刷新通道网页或换通道重试",
            cause=(
                "浏览器插件在向 Google Flow 页面上传主播参考图时超时或中断（IMAGE_NOT_UPLOADED），"
                "可能因为当前通道网页未停留在项目生成界面、网络上传不稳定，或浏览器窗口被系统休眠。"
            ),
            solutions=[
                "打开对应通道的 Chrome 窗口，确认页面停留在正常的 Flow 项目编辑页并刷新一次；",
                "直接点击该行右侧「↻」重试（或选择「自动分配空闲通道」交给其他健康通道执行）；",
                "可点击「🖼」按钮确认本地参考图片文件未被移动或删除。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if "REFERENCE_STATE_NOT_DETECTED" in upper:
        return EditingErrorInfo(
            code="REFERENCE_STATE_NOT_DETECTED",
            stage_label="网页参考图状态核对",
            title=f"网页未确认参考图{f'（{fname}）' if fname else ''}挂载就绪",
            inline_text=f"网页未检测到参考图{f' {fname} ' if fname else ''}挂载状态 · 建议刷新通道网页后点击「↻」重试",
            cause=(
                "参考图已尝试选入网页，但 Google Flow 页面未能在规定时间内渲染出已挂载的参考图缩略图状态"
                "（REFERENCE_STATE_NOT_DETECTED），通常由于网页前端卡顿或标签页处于后台休眠。"
            ),
            solutions=[
                "将对应通道的 Chrome 窗口切到前台并刷新一次页面；",
                "点击该任务右侧的「↻」按钮重新派发即可。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if "FIRST_FRAME_NOT_CONFIRMED" in upper:
        return EditingErrorInfo(
            code="FIRST_FRAME_NOT_CONFIRMED",
            stage_label="首帧图片挂载",
            title="网页输入框未能确认首帧参考图挂载成功",
            inline_text="首帧参考图在网页端未确认就绪 · 直接点击「↻」重试或刷新通道网页",
            cause=(
                "插件在将图片设为视频首帧（First Frame）时，网页界面未及时响应确认状态（FIRST_FRAME_NOT_CONFIRMED）。"
            ),
            solutions=[
                "直接点击右侧「↻」重试；",
                "若同一通道连续出现，请手动刷新该通道的 Chrome 网页。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if "EYE_IMAGE_MODEL_NOT_CONFIRMED" in upper or "睁眼参考图" in core_raw:
        return EditingErrorInfo(
            code="EYE_IMAGE_MODEL_NOT_CONFIRMED",
            stage_label="睁眼参考图准备",
            title="睁眼参考图模型未确认就绪，暂未提交视频",
            inline_text="睁眼参考图尚未就绪（未扣视频点数） · 直接点击「↻」继续即可",
            cause=(
                "系统在准备睁眼参考图时，网页端的图片生成模型未能及时切换或返回结果（EYE_IMAGE_MODEL_NOT_CONFIRMED）。"
                "为保证人物睁眼效果，本次暂未提交视频生成。"
            ),
            solutions=[
                "直接点击右侧「↻」重试，系统会继续查找或复用原图片任务，不会重复浪费额度；",
                "确认对应通道浏览器页面处于正常在线状态。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if "FLOW_GENERATE_BUTTON_NOT_READY" in upper or "BUTTON" in upper:
        return EditingErrorInfo(
            code="FLOW_GENERATE_BUTTON_NOT_READY",
            stage_label="网页生成按钮状态",
            title="Flow 网页上的「生成」按钮处于不可点击状态",
            inline_text="网页「生成」按钮暂不可用 · 请检查通道网页是否加载完成或刷新页面后重试",
            cause=(
                "插件已填入提示词，但网页上的「Generate（生成）」按钮仍处于禁用灰色状态（FLOW_GENERATE_BUTTON_NOT_READY），"
                "常见于参考图还在转圈加载、网页脚本卡住或账号点数不足。"
            ),
            solutions=[
                "查看对应通道的浏览器页面，确认图片已加载完成且账号仍有可用点数；",
                "刷新一次该通道网页后，回到此处点击「↻」重试。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if "FLOW_SUBMISSION_NOT_STARTED" in upper:
        return EditingErrorInfo(
            code="FLOW_SUBMISSION_NOT_STARTED",
            stage_label="网页提交请求未发出",
            title="已点击生成按钮但网页未发出生成请求",
            inline_text="网页点击后未发出生成请求（未扣点数） · 可直接安全点击「↻」重试",
            cause=(
                "浏览器插件已点击生成按钮，但 Google Flow 页面因前端瞬时卡顿并未实际发出网络请求"
                "（FLOW_SUBMISSION_NOT_STARTED）。本次未消耗任何点数。"
            ),
            solutions=[
                "直接点击右侧「↻」按钮重新派发即可；",
                "若该通道多次出现，请刷新该通道浏览器页面。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if any(k in upper for k in ("SUBMISSION_NOT_CONFIRMED", "SUBMISSION_UNCONFIRMED", "SUBMITTED_NOT_CONFIRMED")):
        return EditingErrorInfo(
            code="SUBMISSION_NOT_CONFIRMED",
            stage_label="提交回执超时",
            title="任务已发往网页，但超时未收到开始生成回执",
            inline_text="网页超时未返回开始生成回执 · 建议点击「↻」换空闲通道重试",
            cause=(
                "任务已下发给浏览器插件，但超过等待时间仍未收到网页开始生成的确认回执。"
                "可能是该通道网页被切到后台休眠、网络断连或页面刷新中断。"
            ),
            solutions=[
                "直接点击右侧「↻」（或勾选后点底部「↻ 重置重试」），系统会自动释放原卡住通道并改派空闲通道；",
                "检查原通道 Chrome 窗口是否正常停留在 Flow 项目页面。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if "MAIN_ENGINE_TIMEOUT" in upper:
        return EditingErrorInfo(
            code="MAIN_ENGINE_TIMEOUT",
            stage_label="网页执行引擎超时",
            title="等待浏览器通道主引擎响应超时",
            inline_text="通道网页响应超时 · 建议刷新对应浏览器页面或换通道重试",
            cause=(
                "浏览器插件主执行引擎在规定时间内未能完成页面操作（MAIN_ENGINE_TIMEOUT），"
                "通常因为 Chrome 标签页被系统挂起休眠或网页前端卡死。"
            ),
            solutions=[
                "将对应通道的 Chrome 窗口恢复到前台显示并按 Cmd+R 刷新页面；",
                "点击右侧「↻」将任务改派给空闲健康通道重试。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if "ENGINE_BUSY" in upper:
        return EditingErrorInfo(
            code="ENGINE_BUSY",
            stage_label="通道忙碌冲突",
            title="目标通道正在执行其他任务，暂时繁忙",
            inline_text="目标通道暂忙 · 点击「↻」自动分配空闲通道重试即可",
            cause="该通道浏览器正在处理上一条上传或生成指令（ENGINE_BUSY），未能同时接管当前任务。",
            solutions=[
                "将该行通道设为「自动分配」，点击右侧「↻」即可交由空闲通道立即执行。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if "BRIDGE_TIMEOUT" in upper:
        return EditingErrorInfo(
            code="BRIDGE_TIMEOUT",
            stage_label="插件与本地通信超时",
            title="浏览器插件与本地软件登记下载时通信超时",
            inline_text="插件回传下载通信超时 · 点击「↻」重试或前往「下载完成」重新拉取",
            cause=(
                "视频在网页端已准备下载，但浏览器插件向本地 Bridge 登记下载锁时响应超时"
                "（BRIDGE_TIMEOUT:FS_DOWNLOAD_RESERVE）。"
            ),
            solutions=[
                "点击右侧「↻」重试该片段；",
                "如果网页端其实已经生成出视频，也可在「下载完成」窗口中一键重新拉取云端视频。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if any(k in upper for k in ("AUX_IMAGE_FILE_MISSING", "AUX_IMAGE_MISSING", "AUX_IMAGE_PENDING")):
        return EditingErrorInfo(
            code="AUX_IMAGE_MISSING",
            stage_label="多机位参考图未就绪",
            title="辅助机位/多镜头参考图片缺失或尚未生成完成",
            inline_text="辅助镜头参考图未就绪或本地文件缺失 · 请确认参考图正常后再重试",
            cause="当前片段绑定了辅助机位参考图，但该图片文件在本地不存在或仍在生成中。",
            solutions=[
                "点击右侧「🖼」检查参考图路径是否有效；",
                "在「任务录入 / 角色库」中确认该主播的图片素材完整后再点击「↻」重试。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if "FileNotFoundError" in core_raw or "No such file" in core_raw or ("missing" in core_raw.lower() and (".png" in core_raw.lower() or ".jpg" in core_raw.lower())):
        return EditingErrorInfo(
            code="IMAGE_FILE_NOT_FOUND",
            stage_label="本地参考图缺失",
            title=f"找不到本地参考图片文件{f'（{fname}）' if fname else ''}",
            inline_text=f"本地参考图文件缺失{f' ({fname})' if fname else ''} · 请在角色库重新绑定图片后重试",
            cause=f"系统准备派发任务时，发现绑定的本地参考图文件不存在或已被移动删除（{core_raw}）。",
            solutions=[
                "前往「角色库」或「任务录入」页面，重新为该主播上传或绑定有效的参考图片；",
                "绑定完成后回到本窗口点击「↻」重试。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    # ── 3. Download & Timeout & Generic Flow Failures ──────────────────────
    if "生成超时" in core_raw or "超过15分钟" in core_raw or "超过20分钟" in core_raw or "超过6小时" in core_raw:
        return EditingErrorInfo(
            code="FLOW_GENERATION_TIMEOUT",
            stage_label="生成等待超时",
            title="网页端生成等待超时，未收到成片视频",
            inline_text="网页端生成超时未收到视频 · 建议点击「↻」换空闲通道重试",
            cause=f"任务在网页端等待时间超过上限仍未收到完成视频（{core_raw}），可能网页生成卡死或网络中断。",
            solutions=[
                "直接点击右侧「↻」（或勾选后批量重置重试），系统会解绑原卡住通道并重新派发；",
                "建议检查原通道浏览器页面是否停留在正常状态。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if st == "下载失败" or "DOWNLOAD" in upper or "下载失败" in core_raw:
        return EditingErrorInfo(
            code="VIDEO_DOWNLOAD_FAILED",
            stage_label="视频下载阶段",
            title="云端视频下载到本地时失败",
            inline_text="云端视频拉取保存失败 · 点击「↻」重试下载（建议检查网络或磁盘空间）",
            cause=(
                "视频已在 Google Flow 生成，但在从云端直链下载保存到本地通道目录时发生中断或超时"
                + (f"（{core_raw}）。" if core_raw else "。")
            ),
            solutions=[
                "确保网络连接与代理稳定，且本地磁盘空间充足；",
                "点击右侧「↻」重新执行，或前往「下载完成」管理窗口直接拉取原云端视频。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if upper == "FAILED" or core_raw == "Flow 视频生成失败":
        return EditingErrorInfo(
            code="FLOW_GENERIC_FAILED",
            stage_label="Flow 云端生成异常",
            title="Google Flow 网页返回生成失败状态",
            inline_text="Google Flow 网页返回生成失败 · 建议点击「↻」换通道重试，连续失败可点「✎」微调提示词",
            cause=(
                "Google Flow 网页端将该条视频标记为了生成失败（FAILED），但未返回更具体的子错误码。"
                "常见原因包括：云端算力瞬时拥堵、当前通道账号触发轻度频控，或提示词中存在隐性敏感描述。"
            ),
            solutions=[
                "先直接点击右侧「↻」按钮（自动分配空闲通道）重试一次；",
                "如果同一片段连续重试 2 次仍报此错，请点击「✎」微调提示词 wording（避免敏感词或复杂长句）后再试；",
                "若整个通道所有任务都失败，请去对应 Chrome 窗口刷新页面或切换网络节点。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    if not core_raw:
        if st in ("失败", "下载失败"):
            return EditingErrorInfo(
                code="FLOW_EMPTY_ERROR",
                stage_label="Flow 异常诊断",
                title=f"任务状态为「{st}」（网页未返回具体错误码）",
                inline_text="网页未返回具体失败原因 · 可直接点击「↻」重置重试",
                cause="任务在执行或下载过程中中断，但网页插件未收到 Google 返回的具体错误代码。",
                solutions=[
                    "直接点击右侧「↻」按钮（或勾选后批量重置重试）重新派发；",
                    "可点击「查看详情」查看该片段的最近通道派发时间与状态记录。",
                ],
                location_items=loc_items,
                raw_error=raw or "Flow 未返回具体失败原因；请查看下方最近派发记录。",
            )
        return EditingErrorInfo(
            code="FLOW_RUNNING_NORMAL",
            stage_label="运行状态诊断",
            title=f"当前任务状态：{st or '运行中'}",
            inline_text="正在网页通道执行中" if st in ("已准备", "已提交", "生成中", "下载中") else "等待网页回执",
            cause="当前任务正在队列或浏览器通道中执行，尚未报告错误。",
            solutions=[
                "若等待时间过长疑似卡住，可直接勾选后点击「↻」强制重置并换空闲通道重试。",
            ],
            location_items=loc_items,
            raw_error=raw,
        )

    # ── 4. Fallback for any remaining English tokens or Python exceptions ──
    cleaned_cn = translate_common_exception_cn(core_raw)
    if abandon_prefix:
        cleaned_cn = f"{abandon_prefix}（原因：{cleaned_cn}）"

    return EditingErrorInfo(
        code="FLOW_OTHER_ERROR",
        stage_label="Flow 任务异常诊断",
        title=cleaned_cn[:72],
        inline_text=f"{cleaned_cn} · 可点击「↻」重试或点「查看详情」排查",
        cause=f"任务执行过程中收到异常回执：{cleaned_cn}。",
        solutions=[
            "优先点击该行右侧「↻」按钮（自动分配空闲通道）重新尝试；",
            "若提示与提示词或内容相关，请点击「✎」微调提示词后再试；",
            "若同一通道反复报错，请检查对应 Chrome 窗口是否正常在线并刷新页面。",
        ],
        location_items=loc_items,
        raw_error=raw,
    )


def translate_common_exception_cn(raw: str) -> str:
    """Translate any raw Python / HTTP / SQLite / OS / Flow error string into natural Chinese."""
    s = str(raw or "").strip()
    if not s:
        return "操作未完成，请稍后重试"

    up = s.upper()
    # Direct Flow code replacements inside compound strings
    token_map = {
        "PUBLIC_ERROR_UNUSUAL_ACTIVITY_TOO_MUCH_TRAFFIC": "Google 账号/网络流量过高触发临时限流",
        "PUBLIC_ERROR_UNUSUAL_ACTIVITY": "Google 检测到账号/网络操作频繁触发风控限制",
        "PUBLIC_ERROR_PROMINENT_PEOPLE_FILTER_FAILED": "触发 Google 公众人物/敏感人脸安全过滤",
        "PUBLIC_ERROR_VIDEO_GENERATION_TIMED_OUT": "Google 云端视频渲染超时",
        "PUBLIC_ERROR_UNSAFE": "触发 Google 内容安全审核限制",
        "PUBLIC_ERROR_SAFETY": "触发 Google 内容安全审核限制",
        "SAFETY_FILTER": "触发内容安全过滤限制",
        "CONTENT_POLICY": "违反内容安全政策",
        "PROMPT_REJECTED": "提示词被安全策略拒绝",
        "PROMPT_INVALID": "提示词格式无效",
        "SERVER_UNAUTHORIZED": "Google 账号登录过期或权限失效",
        "IMAGE_NOT_UPLOADED": "参考图片未成功上传至网页",
        "REFERENCE_STATE_NOT_DETECTED": "网页未检测到参考图就绪状态",
        "FIRST_FRAME_NOT_CONFIRMED": "网页首帧参考图未确认就绪",
        "EYE_IMAGE_MODEL_NOT_CONFIRMED": "睁眼参考图模型未确认就绪",
        "FLOW_GENERATE_BUTTON_NOT_READY": "网页生成按钮暂不可点击",
        "FLOW_SUBMISSION_NOT_STARTED": "已点击生成按钮但网页未发出请求",
        "SUBMISSION_NOT_CONFIRMED": "提交后超时未收到网页确认回执",
        "SUBMISSION_UNCONFIRMED": "提交后超时未收到网页确认回执",
        "MAIN_ENGINE_TIMEOUT": "网页通道执行引擎响应超时",
        "ENGINE_BUSY": "当前通道繁忙",
        "BRIDGE_TIMEOUT:FS_DOWNLOAD_RESERVE": "插件登记下载通信超时",
        "BRIDGE_TIMEOUT": "本地通信桥接超时",
        "AUX_IMAGE_FILE_MISSING": "辅助镜头参考图文件缺失",
        "AUX_IMAGE_MISSING": "辅助镜头参考图未绑定",
        "AUX_IMAGE_PENDING": "辅助镜头参考图尚在生成中",
        "GPT_BATCH_REQUEST_FAILED": "AI 批量生成提示词请求失败",
        "SHEET_LINK_ERROR": "Google 表格链接无法访问",
        "INTERNAL": "Google 云端服务器内部错误",
        "UNAVAILABLE": "Google 云端服务暂时不可用",
        "FAILED": "网页端返回生成失败",
    }
    out = s
    for k, v in token_map.items():
        if k in up:
            out = re.sub(re.escape(k), v, out, flags=re.I)

    # Common Python / network / SQLite exceptions
    if "database is locked" in s.lower():
        return "本地数据库正忙（database is locked），请稍等 1～2 秒后重试"
    if "disk i/o error" in s.lower():
        return "磁盘读写异常，请检查磁盘连接与可用空间"
    if "no space left on device" in s.lower():
        return "本地磁盘空间已满，请清理磁盘后再试"
    if "connection refused" in s.lower():
        return "本地服务或网络连接被拒绝，请检查网络或代理设置"
    if "timed out" in s.lower() or "timeout" in s.lower():
        if out == s:
            return f"网络或服务响应超时（{s}）"
    if "ssl" in s.lower() and ("eof" in s.lower() or "cert" in s.lower() or "error" in s.lower()):
        return "网络连接 SSL 握手中断，请检查代理/VPN 节点是否稳定"
    if "401" in s and ("unauthorized" in s.lower() or "invalid_api_key" in s.lower()):
        return "API 密钥无效或未授权（401），请检查密钥配置"
    if "429" in s or "rate limit" in s.lower() or "insufficient_quota" in s.lower():
        return "API 请求频率超限或账户余额不足（429），请切换密钥或稍后重试"
    if "permission denied" in s.lower() or "operation not permitted" in s.lower():
        return "系统文件或目录访问权限不足，请检查文件夹权限"
    if "no such file or directory" in s.lower() or "filenotfounderror" in s.lower():
        fn = _extract_filename(s)
        return f"找不到指定的本地文件{f'（{fn}）' if fn else ''}，请确认文件未被移动或删除"

    # Strip leftover screaming snake case tokens if any remain
    out = _ENG_TOKEN_RE.sub(lambda m: token_map.get(m.group(0).upper(), "异常代码"), out)
    return out
