from PySide6.QtWidgets import QMessageBox
from app.services import duration_choices


def resolve(parent,tasks):
    pending=duration_choices.unresolved(tasks)
    if not pending:return tasks
    analyses=[duration_choices.timing(t) for t in pending]
    integrity=sum(1 for x in analyses if x.get('timing_status')=='INTEGRITY_FAILED')
    manual=sum(1 for x in analyses if x.get('timing_status')=='UNSPLITTABLE' or x.get('manual_text_lock'))
    box=QMessageBox(parent);box.setWindowTitle('口播时长安全检查')
    if integrity:
        box.setText(f'⚠️ {integrity} 个片段完整性校验失败，已禁止提交 Flow。')
        box.setInformativeText('请返回文案编辑，确认没有少字、多字或顺序变化后重新处理。\n完整性失败不能通过“锁定 8 秒”绕过。')
        box.addButton('返回人工调整',QMessageBox.RejectRole);box.exec()
        return None
    if manual:
        box.setText(f'⚠️ 时长超限 · {manual} 个片段需要人工调整。')
        box.setInformativeText('系统不会加快语速、删除台词或强制硬切。\n“自动平衡”只会使用自然语义断点；无法安全拆分时会保持原文。\n如你明确确认原文可在 8 秒内自然完成，可使用人工时长锁定。')
    else:
        box.setText(f'{len(pending)} 个片段超过 8 秒的安全口播余量。')
        box.setInformativeText('自动平衡会优先使用自然语义断点，并重新选择 4 / 6 / 8 秒；不会提高人物语速。')
    split=box.addButton('自动平衡',QMessageBox.AcceptRole)
    force=box.addButton('人工锁定 8 秒',QMessageBox.ActionRole)
    box.addButton(QMessageBox.Cancel);box.exec()
    clicked=box.clickedButton()
    if clicked not in (split,force):return None
    try:
        changed=duration_choices.apply(pending,'split' if clicked==split else 'force')
    except Exception as exc:
        QMessageBox.warning(parent,'口播时长',str(exc));return None
    changed_ids={t['segment_id'] for t in pending}
    result=[t for t in tasks if t['segment_id'] not in changed_ids]+changed
    return sorted(result,key=lambda t:(t['video_id'],t['seg_seq']))
