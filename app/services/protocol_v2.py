import json
import time
from app.services import runtime_log
from app.core import database

# Protocol V2 Adapter

def intercept_v2_event(event):
    """
    Intercepts Protocol V2 structured events from the plugin via Bridge.
    Converts them to legacy events for workflow.py, or handles new task types natively.
    """
    typ = event.get('type')
    
    if typ == 'TASK_ACK':
        # Studio收到ACK以后任务状态：DISPATCHED -> ACCEPTED
        task_id = event.get('TASK_ID')
        accepted = event.get('ACCEPTED')
        task_type = event.get('TASK_TYPE', 'VIDEO')
        runtime_log.log('protocol_v2_ack', task_id=task_id, accepted=accepted, task_type=task_type)
        if not accepted:
            # handle already accepted
            pass
        return True # Handled natively, don't pass to legacy workflow.accept

    if typ == 'TASK_STATUS':
        task_id = event.get('TASK_ID')
        task_type = event.get('TASK_TYPE', 'VIDEO')
        status = event.get('STATUS')
        runtime_log.log('protocol_v2_status', task_id=task_id, status=status, task_type=task_type)
        
        # Translate to legacy for VIDEO
        if task_type == 'VIDEO' or task_type == 'REWORK':
            if status == 'GENERATING':
                return {'type': 'generation_task_status', 'state': 'running', 'command_id': task_id.split('_')[0] if '_' in task_id else task_id, 'segment_id': event.get('SEGMENT_ID')}
        
        return True

    if typ == 'TASK_RESULT':
        task_id = event.get('TASK_ID')
        task_type = event.get('TASK_TYPE', 'VIDEO')
        status = event.get('STATUS')
        local_file = event.get('LOCAL_FILE_PATH')
        
        if task_type == 'VIDEO' or task_type == 'REWORK':
            # Map back to legacy download completed
            cmd_id = task_id.split('_')[0] if '_' in task_id else task_id
            return {
                'type': 'video_download_completed',
                'command_id': cmd_id,
                'segment_id': event.get('SEGMENT_ID'),
                'download_path': local_file,
                'channel_key': event.get('CHANNEL_ID')
            }
        
        # For new types: bind asset
        if status == 'READY':
            with database.connect() as con:
                # Store the bound asset location
                video_id = event.get('VIDEO_ID')
                target_id = event.get('SHOT_ID') or event.get('BROLL_ID') or event.get('SEGMENT_ID')
                if target_id and local_file:
                    con.execute("INSERT OR REPLACE INTO asset_jobs (video_id, job_type, job_id, local_path, status) VALUES (?, ?, ?, ?, 'READY')",
                                (video_id, task_type, target_id, local_file))
                    runtime_log.log('protocol_v2_asset_bound', task_type=task_type, target_id=target_id, path=local_file)
        return True

    if typ == 'TASK_FAILED':
        task_id = event.get('TASK_ID')
        error_code = event.get('ERROR_CODE')
        error_msg = event.get('ERROR_MESSAGE')
        task_type = event.get('TASK_TYPE', 'VIDEO')
        
        if task_type == 'VIDEO' or task_type == 'REWORK':
            cmd_id = task_id.split('_')[0] if '_' in task_id else task_id
            return {
                'type': 'generation_task_status',
                'state': 'failed',
                'command_id': cmd_id,
                'segment_id': event.get('SEGMENT_ID'),
                'error': error_msg
            }
            
        runtime_log.log('protocol_v2_failed', task_id=task_id, task_type=task_type, error=error_msg)
        return True
        
    return event


def enrich_job_with_v2_protocol(job):
    """
    Enriches the legacy job dict with Protocol V2 Envelope fields before dispatching.
    """
    job['PROTOCOL_VERSION'] = 2
    tasks = job.get('tasks', [])
    for t in tasks:
        # Backward compat + Envelope
        cmd_id = job.get('command_id', 'cmd')
        seg_id = t.get('segment_id', '0')
        t['TASK_ID'] = f"{cmd_id}_{seg_id}"
        t['TASK_TYPE'] = t.get('TASK_TYPE', 'VIDEO')
        t['SEGMENT_ID'] = seg_id
        
        # If standard video task
        if t['TASK_TYPE'] == 'VIDEO':
            t['IMAGE_PATH'] = t.get('image')
            t['VIDEO_PROMPT'] = t.get('prompt')
            # Determine VIDEO_ID from DB if needed
            # For performance, maybe it's already there or we ignore since plugin mostly uses TASK_ID
    return job

