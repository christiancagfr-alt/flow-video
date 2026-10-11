import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest,tempfile
from pathlib import Path
from unittest.mock import patch,MagicMock
from app.core import database,repository as repo
from app.services import task_recovery,channel_pool
from app.services.production_worker import ProductionWorker
from app.ui.runtime_tasks import RuntimeTasksDialog

class RuntimeFixTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.dbpatch=patch.object(database,'DB_PATH',Path(self.folder.name)/'studio.db');self.dbpatch.start();database.init_db()
        rid=repo.find_or_create_recipient('r','ZB','t','20261009');hid=repo.find_or_create_host(rid,'h')
        vid=repo.add_video_to_host(hid,original_script='Hello. Amen.')
        repo.sync_flow_segments(vid,['Hello.','Amen.'])
        with database.connect() as con:
            con.execute("UPDATE flow_segments SET prompt='test prompt',prompt_review_status='已提交'")
        self.tasks=[dict(r) for r in repo.list_flow_tasks(work_date='2026-10-09')]
        self.ids=[t['segment_id'] for t in self.tasks]
        self.bridge=MagicMock()
    def tearDown(self):self.dbpatch.stop();self.folder.cleanup()
    def command(self,status='已准备',dispatch='queued'):
        with database.connect() as con:
            con.execute("UPDATE flow_segments SET flow_status=?,generation_command='cmd',flow_channel_key='CH1'",(status,))
            con.execute("UPDATE flow_channel_pool SET task_command_id='cmd' WHERE channel_key='CH1'")
        for sid in self.ids:repo.create_dispatch(sid,'CH1','cmd',sid,1,'test','test.mp4',status=dispatch)
    def test_abandon_only_one_sibling_and_preserve_content(self):
        self.command()
        task_recovery.abandon_task(self.ids[0],self.bridge,'2026-10-09')
        self.bridge.remove_task_from_command.assert_called_once_with('cmd',self.ids[0])
        with database.connect() as con:
            one=con.execute('SELECT * FROM flow_segments WHERE id=?',(self.ids[0],)).fetchone()
            other=con.execute('SELECT * FROM flow_segments WHERE id=?',(self.ids[1],)).fetchone()
            self.assertEqual(one['flow_status'],'已放弃');self.assertEqual(one['generation_command'],'')
            self.assertEqual(one['prompt'],'test prompt');self.assertEqual(other['generation_command'],'cmd')
            self.assertEqual(con.execute("SELECT task_command_id FROM flow_channel_pool WHERE channel_key='CH1'").fetchone()[0],'cmd')
        task_recovery.abandon_task(self.ids[1],self.bridge,'2026-10-09')
        with database.connect() as con:self.assertEqual(con.execute("SELECT task_command_id FROM flow_channel_pool WHERE channel_key='CH1'").fetchone()[0],'')
        self.assertFalse(repo.list_flow_tasks(work_date='2026-10-09'))
    def test_abandon_date_guard(self):
        with self.assertRaises(ValueError):task_recovery.abandon_task(self.ids[0],self.bridge,'2026-10-10')
        self.bridge.remove_task_from_command.assert_not_called()
    def test_queued_sibling_holds_slot_but_terminal_failure_releases(self):
        self.command()
        with database.connect() as con:con.execute("UPDATE flow_segments SET flow_status='失败' WHERE id=?",(self.ids[0],))
        self.assertNotIn('CH1',repo.release_submitted_channel_commands())
        with database.connect() as con:con.execute("UPDATE flow_segments SET flow_status='失败'")
        self.assertIn('CH1',repo.release_submitted_channel_commands())
    def test_durable_submitted_dispatch_releases_legacy_status(self):
        self.command(status='已提交',dispatch='submitted')
        self.assertIn('CH1',repo.release_submitted_channel_commands())
        with database.connect() as con:self.assertEqual(con.execute("SELECT count(*) FROM flow_segments WHERE generation_command='cmd'").fetchone()[0],2)
    def test_missing_error_failure_stays_visible_and_image_error_is_recorded(self):
        with database.connect() as con:con.execute("UPDATE flow_segments SET flow_status='失败' WHERE id=?",(self.ids[0],))
        rows,states,channels,records,count=RuntimeTasksDialog._read_rows('2026-10-09')
        self.assertEqual(len(rows),1);self.assertIn('未返回',records[0]['detail'])
        ProductionWorker._record_image_block(self.tasks[1],FileNotFoundError('missing.png'))
        rows,*_=RuntimeTasksDialog._read_rows('2026-10-09')
        self.assertEqual(len(rows),2);self.assertTrue(any('missing.png' in r['flow_error'] for r in rows))
    def test_edit_prompt_retries_only_selected_task(self):
        self.command(status='失败')
        task_recovery.reset_task(self.ids[0],self.bridge,prompt='corrected prompt')
        with database.connect() as con:
            one=con.execute('SELECT * FROM flow_segments WHERE id=?',(self.ids[0],)).fetchone()
            other=con.execute('SELECT * FROM flow_segments WHERE id=?',(self.ids[1],)).fetchone()
            self.assertEqual(one['prompt'],'corrected prompt');self.assertEqual(one['flow_status'],'待生成')
            self.assertEqual(one['generation_command'],'');self.assertEqual(other['prompt'],'test prompt')
    def test_edit_running_task_rejected_before_bridge_mutation(self):
        self.command(status='生成中',dispatch='submitted')
        with self.assertRaises(ValueError):task_recovery.reset_task(self.ids[0],self.bridge,prompt='changed')
        self.bridge.remove_task_from_command.assert_not_called();self.bridge.cancel_host_commands.assert_not_called()
    def test_waves_cap_and_remainder(self):
        tasks=[dict(self.tasks[0],segment_id=i,seg_seq=i,image_path='same.png') for i in range(13)]
        channels=[dict(id=i,channel_key='CH'+str(i),sort_order=i) for i in (1,2)]
        with patch('app.services.pause_control.filter_tasks',side_effect=lambda ts:ts),patch('app.services.local_bridge.get_bridge',return_value=self.bridge),patch.object(channel_pool,'_image_sibling_state',return_value={}),patch.object(channel_pool.runtime_log,'log'):
            first=channel_pool.plan(tasks,channels)
            assigned=[t['segment_id'] for ts in first.values() for t in ts]
            self.assertEqual(len(assigned),10);self.assertEqual(len(set(assigned)),10)
            self.assertTrue(all(len(ts)<=5 for ts in first.values()))
            rest=channel_pool.plan([t for t in tasks if t['segment_id'] not in assigned],channels)
            self.assertEqual(sum(map(len,rest.values())),3)
if __name__=='__main__':unittest.main()
