import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from app.core import database, repository as repo
from app.services import local_prompt_fill as fill
from app.ui.local_prompt_dialog import LocalPromptDialog
APP=QApplication.instance() or QApplication([])

class LocalFillTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.dbpatch=patch.object(database,'DB_PATH',Path(self.folder.name)/'studio.db');self.dbpatch.start()
        database.init_db()
        rid=repo.find_or_create_recipient('r','ZB','t','20261009');self.hid=repo.find_or_create_host(rid,'h')
        vid=repo.add_video_to_host(self.hid,original_script='Hello. Amen.');repo.sync_flow_segments(vid,['Hello.','Amen.'])
        self.tasks=[dict(r) for r in repo.list_prompt_tasks(host_id=self.hid,work_date='2026-10-09')]
        self.expected={t['segment_id']:t for t in self.tasks}
    def tearDown(self):self.dbpatch.stop();self.folder.cleanup()
    def test_spreadsheet_multiline_and_delimiters(self):
        self.assertEqual(fill.parse_manual('"first\nsecond"\nthird'),['first\nsecond','third'])
        self.assertEqual(fill.parse_manual('first\nsecond\n---\nthird',True),['first\nsecond','third'])
        with self.assertRaises(ValueError):fill.parse_manual('one\n\nthree')
        with self.assertRaises(ValueError):fill.parse_manual('one\ttwo')
    def test_template_modes_and_literal_dialogue(self):
        t={**self.tasks[0],'foreign_text':'Literal {主播}','performance_mode':'PRAYING'}
        p=fill.render('{眼睛要求} {文案}',t)
        self.assertIn('eyes closed',p);self.assertIn('{主播}',p)
        t['performance_mode']='TALKING';self.assertIn('eyes naturally open',fill.render('{眼睛要求} {文案}',t))
        with self.assertRaises(ValueError):fill.render('no dialogue',t)
    def test_save_without_api_usage_and_preserve_copy(self):
        mapping={sid:'Prompt '+str(sid) for sid in self.expected}
        self.assertEqual(fill.save(mapping,self.expected,'2026-10-09','手动批量'),2)
        with database.connect() as con:
            self.assertEqual(con.execute('select count(*) from api_usage_log').fetchone()[0],0)
            self.assertEqual([r[0] for r in con.execute('select foreign_text from flow_segments order by id')],['Hello.','Amen.'])
            self.assertEqual(con.execute("select count(*) from flow_segments where prompt_review_status='待检查'").fetchone()[0],2)
    def test_atomic_rejection_of_started_task(self):
        ids=list(self.expected)
        with database.connect() as con:con.execute("update flow_segments set generation_command='running' where id=?",(ids[1],))
        with self.assertRaises(ValueError):fill.save({i:'new' for i in ids},self.expected,'2026-10-09','模板套用')
        with database.connect() as con:self.assertEqual(con.execute("select count(*) from flow_segments where coalesce(prompt,'')<>''").fetchone()[0],0)
    def test_stale_preview_and_date_rejected(self):
        sid=next(iter(self.expected))
        with self.assertRaises(ValueError):fill.save({sid:'new'},self.expected,'2026-10-10','手动批量')
        with database.connect() as con:con.execute("update flow_segments set prompt='changed' where id=?",(sid,))
        with self.assertRaises(ValueError):fill.save({sid:'new'},self.expected,'2026-10-09','手动批量')
    def test_custom_template_survives_reload(self):
        fill.save_template('Mine','Hello {文案}');self.assertEqual(fill.templates()[-1]['body'],'Hello {文案}')
        fill.save_template('Mine','New {文案}');self.assertEqual(sum(t['name']=='Mine' for t in fill.templates()),1)
    def test_dialog_previews_skip_existing_and_match_counts(self):
        tasks=[dict(t) for t in self.tasks];tasks[0]['prompt']='keep'
        dlg=LocalPromptDialog(tasks,'2026-10-09')
        dlg.editor.setPlainText('only new');dlg.refresh_preview()
        self.assertEqual(list(dlg.mapping),[tasks[1]['segment_id']])
        dlg.overwrite.setChecked(True);dlg.refresh_preview();self.assertFalse(dlg.mapping)
        dlg.close()
        template=LocalPromptDialog(tasks,'2026-10-09',True);self.assertEqual(len(template.mapping),1);template.close()

if __name__=='__main__':unittest.main()
