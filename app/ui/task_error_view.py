"""Presentation only: never changes persistent task/recovery state."""
import re

TEMPORARY = re.compile(r'REFERENCE_STATE_NOT_DETECTED|FLOW_GENERATE_BUTTON_NOT_READY|MAIN_ENGINE_TIMEOUT|SUBMIT(?:TED|SION)?_(?:NOT_CONFIRMED|UNCONFIRMED)|FIRST_FRAME_NOT_CONFIRMED', re.I)
PROMPT = re.compile(r'PROMPT_(?:REJECTED|INVALID|FORMAT|POLICY)|CONTENT_POLICY|SAFETY_FILTER|PUBLIC_ERROR_UNSAFE|违反.{0,8}(?:内容|政策)|提示词格式|提示词.{0,8}(?:拒绝|违规)|内容政策', re.I)

def upload_skipped(task):
    """Image upload failed 3x in the plugin and the task was skipped: manual retry only."""
    raw = str(task.get('flow_error') or '')
    return task.get('flow_status') == '失败' and '图片上传失败' in raw and '跳过' in raw

def needs_prompt(task):
    return task.get('flow_status') in ('失败', '下载失败') and bool(PROMPT.search(str(task.get('flow_error') or '')))

def error_view(task, recovery):
    raw = str(task.get('flow_error') or '')
    status = str(task.get('flow_status') or '')
    history = int(recovery.get('failures') or 0)
    if status in ('已提交', '生成中', '下载中', '已完成'):
        return status, 0, '', (f'历史失败记录：{history}\n{raw}' if history or raw else '')
    label = '需修改提示词' if needs_prompt(task) else ('图片上传失败·已跳过' if upload_skipped(task) else status)
    if not raw: reason = 'Flow 未返回具体失败原因' if status in ('失败','下载失败') else '等待网页回执'
    elif upload_skipped(task): reason = '图片上传3次失败，需手动单独重试'
    elif TEMPORARY.search(raw): reason = '网页暂未就绪' if status in ('失败','下载失败') else '正在核对网页状态'
    elif needs_prompt(task): reason = '提示词被拒绝或格式有误'
    elif 'IMAGE' in raw.upper() or '图片' in raw: reason = '图片未准备好'
    elif 'DOWNLOAD' in raw.upper() or '下载' in raw: reason = '视频下载失败'
    elif 'ENGINE_BUSY' in raw: reason = '执行器暂忙'
    elif 'BUTTON' in raw.upper(): reason = '生成按钮暂不可用'
    else: reason = '任务执行异常（查看详情）'
    return label, history, reason, raw or ('Flow 未返回具体失败原因；请查看任务详情中的最近派发记录。' if status in ('失败','下载失败') else '暂无错误回执。')
