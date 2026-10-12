import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.services import eye_states
from app.services.material_assignment import assign, image_mode, material_folder, reference_tasks
from app.services.speech_preparation import prepare_swahili_speech
from app.core import database


def snapshot(text, offset):
    return {'text':text,'base_mode':'PRAYING','cell':{'textFormatRuns':[{'startIndex':offset,'format':{'foregroundColor':{'red':1}}}]}}


class EyeMaterialsTests(unittest.TestCase):
    def test_manual_image_choice_persists_without_renaming(self):
        from app.services import pre_gpt_pipeline as intake
        from app.services.material_assignment import manual_modes
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder, patch.object(intake,'DB_FILE',Path(folder)/'intake.db'):
            root=Path(folder);photo=root/'photo.png';Image.new('RGB',(8,8),'red').save(photo)
            con=intake.init_db()
            con.execute("INSERT INTO groups_tbl(group_key,local_dir,talking_count) VALUES('g',?,1)",(str(root),))
            con.execute("INSERT INTO tasks(spreadsheet_id,gid,sheet_row,group_key,mode) VALUES('s','0',1,'g','TALKING')")
            con.execute("INSERT INTO assets(group_key,local_path,original_name) VALUES('g',?,'photo.png')",(str(photo),));con.commit();con.close()
            result=intake.confirm_named_materials('g',[])
            self.assertEqual(result['status'],'READY_FOR_GPT')
            con=intake.init_db()
            try:self.assertEqual(image_mode(photo,'PRAYING',manual=manual_modes(con)),'TALKING')
            finally:con.close()
            self.assertTrue(photo.is_file())

    def test_open_scripts_do_not_use_ink_as_eye_state(self):
        source=snapshot('Black text. Red text.',12)
        source['base_mode']='TALKING'
        self.assertEqual(eye_states.blocks(source),[('Black text. Red text.','TALKING')])
        self.assertEqual(eye_states.reference_mode({'外文内容':source},'TALKING'),'TALKING')
        path=Path('闭眼.png').resolve()
        self.assertEqual(image_mode(path,'PRAYING',manual={str(path):'TALKING'}),'TALKING')

    def test_utf16_color_boundary_and_unchanged_source(self):
        text='Mungu asante.\nAmina. Fungua macho.'
        source=snapshot(text,len('Mungu asante.\n'.encode('utf-16-le'))//2)
        lines,modes,timings,spoken=eye_states.prepare(source,lambda s:prepare_swahili_speech(s,max_chars=150))
        self.assertEqual(modes,['PRAYING','TALKING'])
        self.assertEqual(''.join(''.join(lines).split()),''.join(text.split()))
        self.assertEqual(source['text'],text)
        self.assertEqual(len(lines),len(timings))
        emoji=snapshot('黑😀红',3)
        self.assertEqual(eye_states.blocks(emoji),[('黑😀','PRAYING'),('红','TALKING')])

    def test_theme_red_and_default_black(self):
        source={'text':'red','base_mode':'PRAYING','theme':{'themeColors':[{'colorType':'ACCENT1','color':{'rgbColor':{'red':.8}}}]},
                'cell':{'effectiveFormat':{'textFormat':{'foregroundColorStyle':{'themeColor':'ACCENT1'}}}}}
        self.assertEqual(eye_states.blocks(source),[('red','TALKING')])
        self.assertEqual(eye_states.blocks({'text':'black','cell':{}}),[('black','TALKING')])
        self.assertEqual(eye_states.blocks({'text':'edited','local_override':True}),[])

    def test_shortage_reuse_is_stable_and_same_type(self):
        files=[Path(str(i)) for i in range(12)]
        modes={p:'PRAYING' for p in files}
        tasks=[{'id':i,'mode':'PRAYING'} for i in range(13)]
        first=assign(tasks,files,modes,{})
        self.assertEqual(len(first),12)
        with patch('app.services.material_assignment.random.choice',return_value=files[3]) as choose:
            filled=assign(tasks,files,modes,first,True)
            self.assertEqual(filled[12],files[3]);choose.assert_called_once()
        self.assertEqual(assign(tasks,files,modes,filled,True),filled)
        self.assertEqual(assign([{'id':99,'mode':'TALKING'}],files,modes,{},True),{})

    def test_explicit_pools_are_never_cross_filled(self):
        closed,opened=Path('闭眼.png'),Path('睁眼.png')
        files=[closed,opened];modes={closed:'PRAYING',opened:'TALKING'}
        tasks=[{'id':1,'mode':'TALKING'},{'id':2,'mode':'PRAYING'},{'id':3,'mode':'TALKING'}]
        actual=assign(reference_tasks(tasks,modes),files,modes,{},True)
        self.assertEqual(actual,{1:opened,2:closed,3:opened})
        refs=reference_tasks(tasks,{closed:'PRAYING'})
        self.assertTrue(all(t['mode']=='PRAYING' for t in refs))
        self.assertEqual(tasks[0]['mode'],'TALKING')

    def test_picture_folder_and_filename_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pictures=root/'素材';pictures.mkdir()
            self.assertEqual(material_folder(root),pictures)
            self.assertEqual(material_folder(pictures),pictures)
        self.assertEqual(image_mode('闭眼.png','TALKING'),'PRAYING')
        self.assertEqual(image_mode('photo.png',None,'PRAYING'),'PRAYING')

    def test_saved_modes_require_matching_text(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(database,'DB_PATH',Path(folder)/'test.db'), patch('app.core.work_dates.video_work_date',return_value='2026-10-09'):
            with database.connect() as con:
                con.execute('CREATE TABLE flow_segments(id INTEGER,video_id INTEGER,seg_seq INTEGER,foreign_text TEXT)')
                con.execute('CREATE TABLE app_settings(key TEXT PRIMARY KEY,value TEXT)')
                con.execute("INSERT INTO flow_segments VALUES(1,2,1,'hello')")
            self.assertFalse(eye_states.save_modes(2,['different'],['TALKING']))
            self.assertTrue(eye_states.save_modes(2,['hello'],['TALKING']))
            from app.services.performance_types import choices,selected_mode
            with database.connect() as con:
                self.assertEqual(selected_mode(choices(con,2),{'segment_id':1,'foreign_text':'hello'}),'TALKING')

class ProductionIntegrationTests(unittest.TestCase):
    def test_reflow_and_dispatch_keep_color_modes(self):
        from app.core import repository as repo, work_dates
        from app.services import sheet_style, reflow_rules
        with tempfile.TemporaryDirectory() as folder, patch.object(database,'DB_PATH',Path(folder)/'test.db'), patch('app.core.work_dates.active',return_value='2026-10-09'):
            database.init_db()
            rid=repo.find_or_create_recipient('recipient','ZB','test','20261009')
            hid=repo.find_or_create_host(rid,'host')
            text='Mungu asante. Amina rafiki.'
            vid=repo.add_video_to_host(hid,original_script=text)
            sheet_style.save_video(vid,{'外文内容':snapshot(text,len('Mungu asante. '))})
            repo.sync_flow_segments(vid,[text])
            changed=reflow_rules.apply({**reflow_rules.DEFAULTS,'max_chars':150},'2026-10-09')
            self.assertEqual(changed['changed'],1)
            rows=repo.list_prompt_tasks(host_id=hid,work_date='2026-10-09')
            self.assertEqual([r['performance_mode'] for r in rows],['PRAYING','TALKING'])
            job=eye_states.enrich_job({'tasks':[{'segment_id':r['segment_id']} for r in rows]})
            self.assertFalse(job['tasks'][0]['open_eye_prompt'])
            self.assertEqual(job['tasks'][1]['open_eye_prompt'],eye_states.OPEN_EYE_PROMPT)
            self.assertEqual(sheet_style.load_video(vid)['外文内容']['text'],text)

class LegacyColorTests(unittest.TestCase):
    def test_backfill_preserves_old_punctuation_and_ids(self):
        from app.core import repository as repo
        from app.services import sheet_style
        with tempfile.TemporaryDirectory() as folder, patch.object(database,'DB_PATH',Path(folder)/'test.db'):
            database.init_db()
            rid=repo.find_or_create_recipient('r','ZB','test','20261009')
            hid=repo.find_or_create_host(rid,'h')
            text='Mungu asante Amina rafiki'
            vid=repo.add_video_to_host(hid,original_script=text)
            sheet_style.save_video(vid,{'外文内容':snapshot(text,len('Mungu asante '))})
            repo.sync_flow_segments(vid,['Mungu.','asante.','Amina rafiki.'])
            with database.connect() as con:
                before=[tuple(r) for r in con.execute('select id,foreign_text from flow_segments')]
            self.assertEqual(eye_states.reconcile_saved_colors('2026-10-09')['updated'],1)
            rows=repo.list_prompt_tasks(host_id=hid,work_date='2026-10-09')
            self.assertEqual([r['performance_mode'] for r in rows],['PRAYING','PRAYING','TALKING'])
            self.assertTrue(all(r['segment_type_source']=='sheet_color' for r in rows))
            with database.connect() as con:
                self.assertEqual(before,[tuple(r) for r in con.execute('select id,foreign_text from flow_segments')])
            self.assertEqual(eye_states.reconcile_saved_colors('2026-10-09')['updated'],0)

if __name__=='__main__':unittest.main()
