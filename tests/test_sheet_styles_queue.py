import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from app.services import sheet_style
from app.core import database
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextDocument, QTextCursor
from app.ui.sheet_rich_text import apply
from app.ui.prompt_center import GenerateWorker

APP = QApplication.instance() or QApplication([])

class StyleTests(unittest.TestCase):
    def test_sparse_rows_utf16_and_original_text(self):
        text = '  黑字😀\n红字  '
        offset = len('  黑字😀\n'.encode('utf-16-le')) // 2
        cell = {'userEnteredValue': {'stringValue': text}, 'textFormatRuns': [
            {'startIndex': offset, 'format': {'foregroundColorStyle': {'rgbColor': {'red': 1}}, 'bold': True}}]}
        api = MagicMock()
        api.spreadsheets().get().execute.return_value = {'sheets': [{'data': [
            {'startRow': 4, 'startColumn': 2, 'rowData': [{'values':[{'formattedValue':'中'}]}, {}, {'values':[{'formattedValue':'末'}]}]},
            {'startRow': 4, 'startColumn': 3, 'rowData': [{'values':[cell]}, {}, {'values':[{'formattedValue':'last'}]}]}
        ]}]}
        parsed = {'header_map':{'中文内容':2,'外文内容':3}, 'tasks':[
            {'表格行号':5,'中文内容':'中','外文内容':text}, {'表格行号':7,'中文内容':'末','外文内容':'last'}]}
        sheet_style.enrich(api,'id',"O'Brien",parsed)
        snapshot = parsed['tasks'][0]['_source_styles']['外文内容']
        self.assertEqual(parsed['tasks'][0]['外文内容'], text)
        self.assertEqual(parsed['tasks'][1]['_source_styles']['外文内容']['text'], 'last')
        self.assertNotIn('[TALKING]', text)
        doc=QTextDocument();doc.setPlainText(text);apply(doc,snapshot)
        self.assertEqual(doc.toPlainText(), text)
        cursor=QTextCursor(doc);cursor.setPosition(offset+1)
        self.assertEqual(cursor.charFormat().foreground().color().name(), '#ff0000')
        cursor.setPosition(1)
        self.assertEqual(cursor.charFormat().foreground().color().name(), '#000000')
        self.assertIn("'O''Brien'",api.spreadsheets().get.call_args.kwargs['ranges'][0])

    def test_no_api_does_not_silently_strip_styles(self):
        with self.assertRaises(RuntimeError):
            sheet_style.enrich(None,'id','tab',{'tasks':[{}]})

    def test_style_updates_preserve_local_edits(self):
        old=database.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            database.DB_PATH=Path(folder)/'test.db'
            try:
                sheet_style.save_video(3, {'外文内容': {'text':'unchanged','cell':{}}})
                sheet_style.mark_edited(3,'外文内容')
                sheet_style.save_video(3, {'外文内容': {'text':'unchanged','cell':{'textFormatRuns':[]}}})
                self.assertTrue(sheet_style.load_video(3)['外文内容']['local_override'])
            finally: database.DB_PATH=old

class SyncIntegrationTests(unittest.TestCase):
    def test_repeat_sync_preserves_ids_text_and_production(self):
        from app.services import pre_gpt_pipeline as pipeline
        old=database.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);database.DB_PATH=root/'studio.db'
            try:
                database.init_db()
                text='  Original black.\nOriginal red.  '
                task={'表格行号':5,'需求人员':'R','主播名称':'H','中文内容':'  中文\n红色  ','外文内容':text,'需求说明':'','模式':'TALKING','主播图片链接':'',
                      '_source_styles':{'外文内容':{'text':text,'cell':{'textFormatRuns':[{'startIndex':18,'format':{'foregroundColor':{'red':1}}}]}},'中文内容':{'text':'  中文\n红色  ','cell':{}}}}
                parsed={'tasks':[task]}
                with patch.object(pipeline,'DB_FILE',root/'intake.db'),patch.object(pipeline,'load_settings',return_value={'local_root':str(root/'assets')}):
                    self.assertEqual(pipeline.import_tasks(parsed,'sheet','0')[:3],(1,0,0))
                    con=pipeline.init_db();row=con.execute('SELECT id,foreign_text,chinese_text FROM tasks').fetchone()
                    self.assertEqual(row[1],text);self.assertEqual(row[2],task['中文内容']);con.close()
                    with database.connect() as main:
                        main.execute("INSERT INTO recipients(id,name,work_date) VALUES(1,'R','2026-10-08')")
                        main.execute("INSERT INTO hosts(id,recipient_id,name) VALUES(1,1,'H')")
                        main.execute("INSERT INTO videos(id,host_id,seq,original_script,script) VALUES(1,1,1,?,'already prepared')",(text,))
                    con=pipeline.init_db()
                    con.execute('INSERT INTO production_links VALUES(?,1)',(row[0],));con.commit();con.close()
                    task['_source_styles']['外文内容']['cell']['textFormatRuns'][0]['format']['bold']=True
                    self.assertEqual(pipeline.import_tasks(parsed,'sheet','0')[:3],(0,0,1))
                    con=pipeline.init_db();self.assertEqual(con.execute('SELECT id FROM tasks').fetchall(),[(row[0],)]);con.close()
                    with database.connect() as main:self.assertEqual(main.execute('SELECT script FROM videos WHERE id=1').fetchone()[0],'already prepared')
                    self.assertTrue(sheet_style.load_video(1)['外文内容']['cell']['textFormatRuns'][0]['format']['bold'])
            finally:database.DB_PATH=old


class QueueTests(unittest.TestCase):
    def task(self, sid, host=1, video=1):
        return dict(segment_id=sid,host_id=host,video_id=video,video_seq=video,image_path='shared.png',performance_mode='TALKING',foreign_text='hello')

    def test_same_image_different_hosts_and_videos_are_separate(self):
        tasks={1:self.task(1),2:self.task(2,2,2),3:self.task(3,1,3),4:self.task(4)}
        with patch('app.ui.prompt_center.repo.get_prompt_task',side_effect=tasks.get):
            groups=GenerateWorker([1,4,2,3],'test','test')._build_groups()
        self.assertEqual([[s['segment_id'] for s in g['segments']] for g in groups],[[1,4],[2],[3]])

    def test_header_queues_only_checked_pending_current_day(self):
        from types import SimpleNamespace
        from app.ui.prompt_center import PromptCenterPage
        rows=[]
        for sid,prompt,review in [(1,'','待检查'),(2,'existing','待检查'),(3,'','待检查'),(4,'','已提交')]:
            rows.append(dict(self.task(sid),prompt=prompt,prompt_review_status=review))
        fake=SimpleNamespace(worker=None,checked_ids={1,2,4},progress=MagicMock(),header_generate=MagicMock(),current_job=MagicMock(),
            generate_empty=MagicMock(),generate_selected=MagicMock(),retry_failed=MagicMock(),on_progress=MagicMock(),on_item_done=MagicMock(),on_finished=MagicMock(),_release_generate_worker=MagicMock())
        with patch('app.ui.prompt_center.openai_service.get_api_key',return_value='fake'),patch('app.ui.prompt_center.work_dates.active',return_value='2026-10-08'),patch('app.ui.prompt_center.repo.list_prompt_tasks',return_value=rows) as listing,patch('app.ui.prompt_center.repo.get_prompt_task',side_effect=lambda sid:next(t for t in rows if t['segment_id']==sid)),patch('app.ui.prompt_center.repo.get_setting',return_value='configured'),patch('app.ui.prompt_center.GenerateWorker') as worker:
            PromptCenterPage.start_generation(fake,'checked_pending')
            listing.assert_called_once_with(work_date='2026-10-08')
            self.assertEqual(worker.call_args.args[0],[1]);worker.return_value.start.assert_called_once()

    def test_failure_continues_without_duplicate_requests(self):
        tasks={1:self.task(1),2:self.task(2,2,2)}
        calls=[]
        def request(**kwargs):
            sid=kwargs['group']['segments'][0]['segment_id'];calls.append(sid)
            kwargs['on_request']()
            if sid==1: raise RuntimeError('test failure')
            return dict(prompts={2:'ok'},input_tokens=1,cached_tokens=0,output_tokens=1,cost_usd=0)
        worker=GenerateWorker([1,2],'test','core');summaries=[]
        worker.finished_summary.connect(lambda *x:summaries.append(x))
        with patch('app.ui.prompt_center.repo.get_prompt_task',side_effect=tasks.get), patch('app.ui.prompt_center.repo.get_setting',side_effect=lambda key,default='': 'template' if key=='talking_base_prompt' else default), patch('app.ui.prompt_center.openai_service.generate_prompts_for_image',side_effect=request), patch('app.ui.prompt_center.repo.save_prompt_batch_results'), patch('app.ui.prompt_center.repo.mark_prompt_failed'):
            worker.run()
        self.assertEqual(calls,[1,2]);self.assertEqual(summaries[0][:2],(1,1))

if __name__=='__main__': unittest.main()
