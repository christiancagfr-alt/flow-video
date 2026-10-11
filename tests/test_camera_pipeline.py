import sys, unittest, tempfile, types
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services import camera_motion as cm
from app.core import database
from app.services import camera_aux, broll_presets

class MotionTests(unittest.TestCase):
    def plan(self,**kw):
        return dict(enabled=True,level=3,type='ARC_RIGHT',start_angle='FRONT_LEFT_20',end_angle='FRONT_RIGHT_20',movement_amount_deg=40,movement_distance_m=None,duration_sec=6,parallax_required=True,requires_aux_image=False,perspective_change=False,**kw)
    def test_thresholds(self):
        p=self.plan()
        for level,angle,expected in [(0,40,False),(1,20,False),(2,30,False),(3,30,False),(3,31,True),(4,20,True),(2,46,True)]:
            self.assertEqual(cm.normalize(dict(p,level=level,movement_amount_deg=angle))['requires_aux_image'],expected)
    def test_all_movement_blocks(self):
        for typ in cm.TYPES:
            p=dict(self.plan(),type=typ,movement_distance_m=1.5)
            text=cm.block(p)
            if typ!='STATIC':
                for label in ['START POSITION','MOVEMENT','DIRECTION / AMOUNT','END POSITION','PARALLAX']: self.assertIn(label,text)
                self.assertIn('6 seconds',text)
    def test_invalid_and_missing_binding(self):
        for patch in [{'type':'ZOOM'},{'duration_sec':0},{'movement_amount_deg':None},{'level':9}]:
            with self.assertRaises(ValueError): cm.normalize(dict(self.plan(),**patch))
        with self.assertRaises(ValueError): cm.validate_plans({'VIDEO_PLAN':[{'SEGMENT_ID':'1','camera_motion':self.plan()}]},[{'segment_id':1}],1)
    def test_unique_used_by_repairs_omitted_end_binding(self):
        data={'VIDEO_PLAN':[{'SEGMENT_ID':'1','camera_motion':self.plan(),'GENERATION_MODE':'MASTER_ONLY','IMAGE_BINDING':None}], 'IMAGE_PLAN':[{'SHOT_ID':'SHOT_1','IMAGE_PROMPT':'left 35 degrees','USED_BY':['1']}]}
        cm.validate_plans(data,[{'segment_id':1}],1)
        self.assertEqual(data['VIDEO_PLAN'][0]['GENERATION_MODE'],'START_END')
        self.assertEqual(data['VIDEO_PLAN'][0]['IMAGE_BINDING']['END_IMAGE'],'SHOT_1')

    def test_nonstandard_shot_id_does_not_discard_prompt(self):
        data={'VIDEO_PLAN':[{'SEGMENT_ID':'1','VIDEO_PROMPT':'Move camera to left 35 degrees','camera_motion':self.plan(),'IMAGE_BINDING':{'START_IMAGE':'MASTER','END_IMAGE':'左侧机位'}}], 'IMAGE_PLAN':[{'SHOT_ID':'左侧机位','IMAGE_PROMPT':'Camera at subject left 35 degrees.','USED_BY':['1']}]}
        cm.prepare_review_draft(data,[{'segment_id':1}])
        self.assertEqual(data['IMAGE_PLAN'][0]['SHOT_ID'],'SHOT_001')
        self.assertEqual(data['VIDEO_PLAN'][0]['IMAGE_BINDING']['END_IMAGE'],'SHOT_001')
        self.assertEqual(data['IMAGE_PLAN'][0]['IMAGE_PROMPT'],'Camera at subject left 35 degrees.')
    def test_empty_aux_prompt_is_retained_for_review(self):
        data={'VIDEO_PLAN':[{'SEGMENT_ID':'1','VIDEO_PROMPT':'Move camera','camera_motion':self.plan()}],'IMAGE_PLAN':[{'SHOT_ID':'1','IMAGE_PROMPT':'','USED_BY':['1']}]}
        cm.prepare_review_draft(data,[{'segment_id':1}])
        self.assertEqual(len(data['IMAGE_PLAN']),1)
        self.assertTrue(data['review_notes'])

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=database.DB_PATH;database.DB_PATH=Path(self.tmp.name)/'test.db'
        database.init_db();database.init_db()
        from app.core import repository as repo
        repo.set_setting('flow_download_root', self.tmp.name)
        with database.connect() as c:
            c.execute("INSERT INTO recipients(id,name,work_date) VALUES(1,'R','2026-09-29')")
            c.execute("INSERT INTO hosts(id,recipient_id,name) VALUES(1,1,'H')")
            c.execute("INSERT INTO videos(id,host_id,seq) VALUES(1,1,1)")
            c.execute("INSERT INTO flow_segments(id,video_id,seg_seq,foreign_text,generation_command) VALUES(1,1,1,'talk','video-cmd'),(2,1,1000,'[辅助图] SHOT_001: endpoint','aux-cmd')")
        broll_presets.save_video_plan('1',[{'SEGMENT_ID':'1','IMAGE_BINDING':{'START_IMAGE':'MASTER','END_IMAGE':'SHOT_001'},'camera_motion':{'requires_aux_image':True}}],[],[],{})
        self.task={'video_id':1,'segment_id':1,'TASK_TYPE':'VIDEO'}
    def tearDown(self): database.DB_PATH=self.old;self.tmp.cleanup()
    def event(self,**kw):return dict(type='image_download_completed',task_type='CAMERA_AUX_IMAGE',segment_id=2,video_id=1,shot_id='SHOT_001',command_id='aux-cmd',host_id=1,download_method='flow_native_button',resolution='2K',**kw)
    def test_migration_and_gate(self):
        with self.assertRaises(RuntimeError):camera_aux.resolve(self.task)
        self.assertEqual(camera_aux.resolve(dict(self.task,segment_id=9))[1],{})
    def test_stale_and_missing_receipt(self):
        self.assertTrue(camera_aux.accept(dict(self.event(),command_id='old')))
        with self.assertRaises(ValueError):camera_aux.accept(self.event(output_path='/missing.png'))
        with self.assertRaises(RuntimeError):camera_aux.resolve(self.task)
    def test_ready_receipt_idempotency_and_unlock(self):
        # The test runtime lacks Qt. Use a real Pillow decoder behind the Qt adapter.
        from PIL import Image
        class Reader:
            def __init__(self,path):self.path=path
            def read(self):
                try:
                    with Image.open(self.path) as im:
                        size=im.size;im.verify()
                    null=False
                except Exception:null=True;size=(0,0)
                return types.SimpleNamespace(isNull=lambda:null,width=lambda:size[0],height=lambda:size[1])
        from unittest.mock import patch
        decoder_patch=patch.dict(sys.modules,{'PySide6.QtGui':types.SimpleNamespace(QImageReader=Reader)})
        decoder_patch.start();self.addCleanup(decoder_patch.stop)
        path=Path(self.tmp.name)/'FlowStudio/.incoming/VIDEO_1/CAMERA_AUX/end.png';path.parent.mkdir(parents=True);Image.new('RGB',(1152,2048)).save(path)
        event=self.event(output_path=str(path))
        for _ in range(2):self.assertTrue(camera_aux.accept(event))
        archived=Path(camera_aux.resolve(self.task)[1]['SHOT_001'])
        self.assertIn('assets/camera_aux/video_1',archived.as_posix())
        self.assertTrue(archived.is_file())
        self.assertFalse(path.exists())
        camera_aux.accept(dict(event,type='image_download_started'))
        with database.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM asset_jobs').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT status FROM asset_jobs').fetchone()[0],'READY')
            self.assertEqual(c.execute('SELECT flow_status FROM flow_segments WHERE id=2').fetchone()[0],'已完成')
        archived.unlink()
        with self.assertRaises(RuntimeError):camera_aux.resolve(self.task)
    def test_creation_is_executable_and_stable_identity(self):
        from app.core import repository as repo
        for purpose in ('first','renamed'):
            repo.create_image_plan_segments(1,[{'SHOT_ID':'SHOT_002','PURPOSE':purpose,'IMAGE_PROMPT':'same pastor at right 35 degrees'}],'test')
        with database.connect() as c:
            rows=c.execute("SELECT * FROM flow_segments WHERE foreign_text LIKE '[辅助图] SHOT_002:%'").fetchall()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['prompt_review_status'],'待检查')
            self.assertEqual(c.execute("SELECT status FROM asset_jobs WHERE job_id='SHOT_002'").fetchone()[0],'PLANNED')
    def test_actual_payload_has_two_uploaded_images(self):
        from app.services.production_worker import ProductionWorker
        from app.services import channel_pool
        from unittest.mock import patch
        master=Path(self.tmp.name)/'master.png';master.write_bytes(b'master')
        end=Path(self.tmp.name)/'end.png';end.write_bytes(b'endpoint')
        with database.connect() as c:
            c.execute("INSERT INTO asset_jobs(video_id,source_url,job_type,job_id,status,local_path) VALUES(1,'camera_aux:SHOT_001','CAMERA_AUX_IMAGE','SHOT_001','READY',?)",(str(end),))
        with database.connect() as c:
            c.execute("UPDATE asset_jobs SET image_width=1152,image_height=2048,download_method='flow_native_button'")
        task=dict(self.task,image_path=str(master),video_seq=1,seg_seq=1,foreign_text='Hello',prompt='CAMERA',generation_mode='FRAME',flow_retry_count=0,host_id=1,host_name='H',recipient_id=1,recipient_name='R')
        ch=dict(id=1,channel_key='CH1',role='normal',collection_url='https://labs.google/fx/tools/flow/project/test',download_subdir='CH1',upload_state='idle',upload_fingerprint='',images_uploaded=0,upload_verified_at='',upload_command_id='')
        worker=ProductionWorker(None);worker.day='2026-09-29'
        with patch.object(channel_pool,'resolve_task_image_path',side_effect=lambda t:Path(t['image_path'])):
            job=worker._make_pool_job(ch,[task],'test-command',dispatch_tasks=True)
            payload=job['tasks'][0]
            self.assertEqual(job['image_count'],2)
            paths=[f['path'] for f in job['image_files']]
            self.assertIn(payload['image_path'],paths)
            self.assertIn(payload['end_image_path'],paths)
            self.assertNotEqual(payload['image_path'],payload['end_image_path'])
            ordinary=worker._make_pool_job(ch,[dict(task,segment_id=99)],'ordinary-command',dispatch_tasks=True)
            self.assertEqual(ordinary['image_count'],1)
            self.assertEqual(ordinary['tasks'][0]['end_image_path'],'')
    def test_enhanced_prompt_response_contract(self):
        import json
        from unittest.mock import patch
        from app.services import openai_service as ai
        motion=MotionTests().plan()
        data={'VIDEO_PLAN':[{'SEGMENT_ID':'1','VIDEO_PROMPT':'stable camera','CAMERA_ID':'a','camera_motion':motion,'GENERATION_MODE':'START_END','IMAGE_BINDING':{'START_IMAGE':'MASTER','END_IMAGE':'SHOT_001','MATERIAL_IMAGES':None}}], 'IMAGE_PLAN':[{'SHOT_ID':'SHOT_001','TYPE':'CAMERA_AUX_IMAGE','PURPOSE':'endpoint','IMAGE_PROMPT':'front right 20 degrees','USED_BY':['1']}]}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(data)}]}]}).encode()
        group={'segments':[{'segment_id':1,'video_id':1,'foreign_text':'stable camera'}], 'auto_action_match':False}
        with patch.object(ai,'get_api_key',return_value='test'),patch.object(ai,'_image_data_url',return_value='data:image/png;base64,dGVzdA=='),patch('urllib.request.urlopen',return_value=Response()):
            result=ai.generate_enhanced_prompts(model='test',core_prompt='stable camera',group=group,config={'camera_enabled':True,'camera_limit':1},preset_snapshot={})
        self.assertIn('DIRECTION / AMOUNT:',result['prompts']['1'])
        self.assertIn('文案： stable camera',result['prompts']['1'])
        self.assertTrue(result['data']['VIDEO_PLAN'][0]['camera_motion']['requires_aux_image'])
    def test_missing_aux_plan_saves_text_without_retry(self):
        import json
        from unittest.mock import patch
        from app.services import openai_service as ai
        motion=MotionTests().plan()
        data={'VIDEO_PLAN':[{'SEGMENT_ID':'1','VIDEO_PROMPT':'stable camera','CAMERA_ID':'a','camera_motion':motion,'GENERATION_MODE':'START_END','IMAGE_BINDING':{'START_IMAGE':'MASTER','END_IMAGE':'SHOT_001','MATERIAL_IMAGES':None}}], 'IMAGE_PLAN':[{'SHOT_ID':'SHOT_001','TYPE':'CAMERA_AUX_IMAGE','PURPOSE':'endpoint','IMAGE_PROMPT':'front right 20 degrees','USED_BY':['1']}]}
        responses=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):
                import copy
                current=copy.deepcopy(data)
                if not responses: current['IMAGE_PLAN']=[]
                responses.append(current)
                return json.dumps({'usage':{'input_tokens':10,'output_tokens':5},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(current)}]}]}).encode()
        group={'segments':[{'segment_id':1,'video_id':1,'foreign_text':'stable camera'}], 'auto_action_match':False}
        with patch.object(ai,'get_api_key',return_value='test'),patch.object(ai,'_image_data_url',return_value='data:image/png;base64,dGVzdA=='),patch('urllib.request.urlopen',return_value=Response()):
            result=ai.generate_enhanced_prompts(model='test',core_prompt='stable camera',group=group,config={'camera_enabled':True,'camera_limit':1},preset_snapshot={})
        self.assertIn('DIRECTION / AMOUNT:',result['prompts']['1'])
        self.assertIn('文案： stable camera',result['prompts']['1'])
        self.assertTrue(result['data']['VIDEO_PLAN'][0]['camera_motion']['requires_aux_image'])
        self.assertEqual(len(responses),1)
        self.assertEqual(result['input_tokens'],10)
        self.assertEqual(result['output_tokens'],5)
        self.assertTrue(result['data']['review_notes'])
    def test_quality_floor_and_native_proof(self):
        self.assertTrue(camera_aux.meets_2k(1152,2048))
        self.assertFalse(camera_aux.meets_2k(1024,1024))
        self.assertFalse(camera_aux.meets_2k(512,4096))
        with self.assertRaisesRegex(ValueError,'AUX_NATIVE_2K_RECEIPT_REQUIRED'):
            camera_aux.accept(dict(self.event(),download_method='cdn'))
    def test_old_ready_without_quality_does_not_unlock(self):
        path=Path(self.tmp.name)/'old.png';path.write_bytes(b'old')
        with database.connect() as c:
            c.execute("INSERT INTO asset_jobs(video_id,source_url,job_type,job_id,status,local_path) VALUES(1,'old','CAMERA_AUX_IMAGE','SHOT_001','READY',?)",(str(path),))
        with self.assertRaisesRegex(RuntimeError,'REQUIRES_NATIVE_2K'):camera_aux.resolve(self.task)
    def test_regular_receipt_untouched(self):self.assertFalse(camera_aux.accept({'type':'video_download_completed','task_type':'VIDEO'}))

if __name__=='__main__':unittest.main()
