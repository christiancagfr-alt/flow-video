import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest,tempfile
from pathlib import Path
from unittest.mock import patch,MagicMock
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QColor
from app.core import database,repository as repo
from app.services import clip_transform as tr
from app.ui.clip_transform import TransformVideoWidget,ClipTransformDialog
from app.services.production_worker import ProductionWorker
APP=QApplication.instance() or QApplication([])
class ClipTransformTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(database,'DB_PATH',Path(self.tmp.name)/'test.db');self.p.start();database.init_db()
        rid=repo.find_or_create_recipient('r','ZB','t','20261009');hid=repo.find_or_create_host(rid,'h');self.vid=repo.add_video_to_host(hid,original_script='Hi')
        repo.sync_flow_segments(self.vid,['Hi']);self.sid=repo.list_prompt_tasks(host_id=hid,work_date='2026-10-09')[0]['segment_id']
        with database.connect() as con:
            self.oid=con.execute("INSERT INTO flow_outputs(segment_id,command_id,media_id,output_path) VALUES(?,'c','m','old.mp4')",(self.sid,)).lastrowid
    def tearDown(self):self.p.stop();self.tmp.cleanup()
    def test_output_version_and_move(self):
        v=tr.save(self.oid,dict(ZoomX=1.25,Pan=23,Tilt=-40));self.assertEqual(tr.get(self.oid),v)
        repo.rebind_flow_output_path(self.sid,'old.mp4','new.mp4')
        self.assertEqual(tr.for_source(self.sid,'new.mp4'),v);self.assertEqual(tr.for_source(self.sid,'other-generation.mp4'),{})
    def test_reject_imported_batch_and_invalid_numbers(self):
        from app.services.resolve_batches import ensure_schema
        ensure_schema()
        with database.connect() as con:
            con.execute("INSERT INTO davinci_batches(batch_id,work_date,project_name,timeline_name,status,video_count,manifest_path) VALUES('b','2026-10-09','p','t','IMPORTING',1,'m')")
            con.execute("INSERT INTO davinci_video_state(batch_id,video_id) VALUES('b',?)",(self.vid,))
        with self.assertRaises(ValueError):tr.save(self.oid,{'ZoomX':1.3})
        for value in (float('nan'),float('inf'),0):
            with self.assertRaises(ValueError):tr.validate({'ZoomX':value})
    def test_resolve_same_values_readback_and_size_guard(self):
        values=dict(ZoomX=1.2,Pan=20,Tilt=-30);props={};clip=MagicMock()
        clip.SetProperty.side_effect=lambda k,v:props.update({k:v}) or True;clip.GetProperty.side_effect=lambda k:props[k]
        tr.apply_resolve(clip,values,720,1280);self.assertEqual(props,dict(ZoomX=1.2,ZoomY=1.2,Pan=20.,Tilt=-30.))
        with self.assertRaises(RuntimeError):tr.apply_resolve(clip,values,1080,1920)
        clip.GetProperty.return_value=0;clip.GetProperty.side_effect=None
        with self.assertRaises(RuntimeError):tr.apply_resolve(clip,values,720,1280)
    def test_preview_and_cancel_without_changing_source(self):
        widget=TransformVideoWidget();widget.resize(180,320)
        image=QImage(180,320,QImage.Format_RGB32);image.fill(QColor('white'))
        for y in range(300,320):
            for x in range(180):image.setPixelColor(x,y,QColor('red'))
        widget.image=image;widget.show();APP.processEvents()
        self.assertEqual(widget.grab().toImage().pixelColor(90,310),QColor('red'))
        dlg=ClipTransformDialog(self.oid,widget);dlg.fields['ZoomX'].setValue(1.3);APP.processEvents()
        self.assertEqual(widget.grab().toImage().pixelColor(90,310),QColor('white'))
        self.assertEqual(image.pixelColor(90,310),QColor('red'));dlg.reject();self.assertEqual(widget.values['ZoomX'],1)
        widget.close()
    def test_failed_or_submitted_tasks_are_never_reclaimed(self):
        with database.connect() as con:con.execute("UPDATE flow_segments SET generation_command='cmd',flow_status='失败' WHERE id=?",(self.sid,))
        repo.create_dispatch(self.sid,'CH1','cmd',1,1,'n','f',status='queued',release_at=1)
        with database.connect() as con:
            con.execute("UPDATE flow_dispatches SET stage='QUEUED',last_update_at=1");did=con.execute('SELECT id FROM flow_dispatches').fetchone()[0]
        self.assertEqual(repo.requeue_unsubmitted_dispatches([did]),0)
        with database.connect() as con:con.execute("UPDATE flow_segments SET flow_status='已准备'");con.execute("UPDATE flow_dispatches SET submitted_at='2026-10-09'")
        self.assertEqual(repo.requeue_unsubmitted_dispatches([did]),0)
        with database.connect() as con:con.execute("UPDATE flow_dispatches SET submitted_at='' ")
        self.assertEqual(repo.requeue_unsubmitted_dispatches([did]),1)
        bridge=MagicMock();ProductionWorker(bridge)._auto_retry_timed_out_active_commands('2026-10-09');bridge.cancel_host_commands.assert_not_called();bridge.request_progress_scan.assert_called_once()
    def test_auto_pool_excludes_failure_until_manual_reset(self):
        rows=[dict(segment_id=i,flow_status=status,generation_command='') for i,status in enumerate(('失败','下载失败','待生成','已准备'))]
        worker=ProductionWorker(MagicMock());worker.day='2026-10-09'
        with patch('app.services.production_worker.repo.list_flow_tasks',return_value=rows),patch('app.services.production_worker.workflow.redo_ids',return_value=set()):
            self.assertEqual([r['segment_id'] for r in worker._pool_scope_tasks()],[2,3])
        with patch('app.services.production_worker.repo.list_flow_tasks',return_value=rows),patch('app.services.production_worker.workflow.redo_ids',return_value={0,1,2,3}):
            self.assertEqual([r['segment_id'] for r in worker._pool_scope_tasks(True)],[2,3])
    def test_audit_preserves_failed_and_uncertain_running(self):
        with database.connect() as con:
            con.execute("UPDATE flow_segments SET prompt='p',prompt_review_status='已提交',flow_status='生成中',generation_command='' WHERE id=?",(self.sid,))
        audit=repo.reconcile_selected_date_unfinished_tasks(work_date='2026-10-09');self.assertEqual(audit['requeued'],[])
        with database.connect() as con:con.execute("UPDATE flow_segments SET flow_status='失败' WHERE id=?",(self.sid,))
        audit=repo.reconcile_selected_date_unfinished_tasks(work_date='2026-10-09');self.assertEqual(audit['requeued'],[])
    def test_lua_import_script_compiles(self):
        from lupa import LuaRuntime
        LuaRuntime().compile(Path('davinci_autoedit_v0_5_0/FlowStudio_Import_Batch.lua').read_text(encoding='utf-8'))
if __name__=='__main__':unittest.main()
