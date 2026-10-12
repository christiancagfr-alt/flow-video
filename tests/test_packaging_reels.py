import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import tempfile
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from app.services.packaging_media import (output_size,output_basename,available_output,
    captions_from_srt,captions_to_srt,recognition_result,validate_captions)
from app.services.reels.captions import proofread_srt_keep_timestamps,batch_script_paste_assignments
from app.services.packaging_overlay import paint_at,prepare_overlays

APP=QApplication.instance() or QApplication([])

class PackagingReelsTests(unittest.TestCase):
    def test_asr_overlap_keeps_crossing_sentence_words_once(self):
        from app.services.asr_timing import owned_segments
        segment={'start':72,'end':76,'text':'one two three four',
            'words':[{'start':72+i,'end':73+i,'text':w} for i,w in enumerate('one two three four'.split())]}
        left=owned_segments([segment],0,74)
        right=owned_segments([segment],74,148)
        words=[w for s in left+right for w in s['words']]
        self.assertEqual([w['text'] for w in words],['one','two','three','four'])
        self.assertEqual(right[0]['start'],74)
        self.assertEqual(right[0]['text'],'three four')

    def test_asr_overlap_matches_words_despite_timestamp_jitter(self):
        from app.services.asr_timing import stitch_segments
        def segment(words):return {'start':words[0]['start'],'end':words[-1]['end'],'text':'','words':words}
        left=segment([{'start':72,'end':73,'text':'you'},{'start':73.8,'end':74.4,'text':'ask'}])
        right=segment([{'start':73.5,'end':74.1,'text':'ask'},{'start':74.4,'end':74.8,'text':'what'}])
        joined=stitch_segments([left],[right],74)
        self.assertEqual([w['text'] for s in joined for w in s['words']],['you','ask','what'])

    def test_timeline_seeks_and_selects_caption_after_intro(self):
        from app.ui.packaging_timeline import PackagingTimeline
        from PySide6.QtCore import Qt,QPoint
        from PySide6.QtTest import QTest
        timeline=PackagingTimeline();timeline.resize(1000,220)
        timeline.set_state({'source':'a.mp4','duration':10,'intro':{'enabled':True,'path':'intro.png','duration':2},
            'captions':[{'start':1,'end':3,'text':'hello'}]})
        timeline.show();APP.processEvents()
        selections=[];seeks=[]
        timeline.captionSelected.connect(selections.append);timeline.seekRequested.connect(seeks.append)
        rect=next(rect for rect,index,text in timeline.hits if index==0)
        QTest.mouseClick(timeline,Qt.LeftButton,pos=rect.center().toPoint())
        self.assertEqual(selections,[0]);self.assertAlmostEqual(seeks[0]/1000,2,delta=.05)
        self.assertEqual(timeline.duration,12)
        timeline.close()

    def test_resolution(self):
        self.assertEqual(output_size('16:9','720p'),(1280,720))
        self.assertEqual(output_size('9:16','4K'),(2160,3840))
        self.assertEqual(output_size('原始比例','默认最高',(1920,1080)),(1920,1080))

    def test_names_and_collisions(self):
        params={'rename_enabled':True,'rename_start':2,'rename_padding':3,
            'rename_prefix':'a/b','rename_titles':'Hello\nWorld','rename_date_enabled':True,'rename_date':'20261011'}
        self.assertEqual(output_basename('source.mp4',params,1),'003-a_b-World-20261011')
        with tempfile.TemporaryDirectory() as d:
            first=available_output(d,'name','mp4');Path(first).touch()
            self.assertEqual(Path(available_output(d,'name','mp4')).name,'name_2.mp4')

    def test_proofreading_keeps_timing(self):
        source='1\n00:00:01,200 --> 00:00:02,700\nHello word\n'
        result,changes=proofread_srt_keep_timestamps(source,'Hello world')
        self.assertIn('00:00:01,200 --> 00:00:02,700',result)
        self.assertIn('Hello world',result);self.assertEqual(len(changes),1)

    def test_multiline_spreadsheet(self):
        rows=[{'path':'a.mp4'},{'path':'b.mp4'}]
        self.assertEqual(batch_script_paste_assignments('a.mp4\t"line one\nline two"',rows,'name'),[(0,'line one\nline two')])
        with self.assertRaises(ValueError):batch_script_paste_assignments('missing.mp4\ttext',rows,'name')

    def test_recognition_words(self):
        caps,estimated=recognition_result('1\n00:00:00,200 --> 00:00:02,000\nHello world\n',
            {'words':[{'start':.2,'end':.5,'word':'Hello'},{'start':1.1,'end':2,'word':'world'}]})
        self.assertFalse(estimated);self.assertAlmostEqual([w for c in caps for w in c['words']][1]['start'],1.1)
        self.assertEqual(' '.join(c['text'] for c in captions_from_srt(captions_to_srt(caps))),'Hello world')

    def test_all_reels_styles_paint(self):
        presets=json.loads(Path('app/services/reels/presets.json').read_text(encoding='utf-8'))
        captions=[{'start':1.,'end':3.,'text':'Jesus loves you today',
            'words':[{'start':1+i*.5,'end':1.5+i*.5,'text':w} for i,w in enumerate('Jesus loves you today'.split())]}]
        for name,style in presets.items():
            with self.subTest(name=name):
                image=paint_at(captions,style,1.6)
                self.assertFalse(image.isNull())
                self.assertTrue(any(bytes(image.bits())[3::4]),name)
        with tempfile.TemporaryDirectory() as d:
            p=prepare_overlays({'mainDuration':4,'fps':30,'captions':captions,'reelsStyle':presets['Descript 经典黄']},d)
            self.assertTrue(p['captionOverlays']);self.assertGreaterEqual(p['captionOverlays'][0]['start'],30)
            self.assertTrue(all(x['start']+x['duration']<=90 for x in p['captionOverlays']))

    def test_page_roundtrip_preserves_original_features(self):
        from app.ui.packaging_page import PackagingPage
        page=PackagingPage()
        state=page._default_state('demo.mp4');state['title']['text']='Keep title'
        state['intro']['path']='intro.png';state['broll']=[{'path':'b.png','start':1,'end':2,'fit':'cover'}]
        state['watermarks']=[{'path':'logo.png','enabled':True}]
        state['params'].update(output_resolution='720p',output_fps='60',output_format='WebM / VP9',rename_prefix='Prefix')
        page._project={'videos':{'demo.mp4':state},'order':['demo.mp4']};page._current_path='demo.mp4'
        page._load_state(state);result=page._capture_controls()
        self.assertEqual(result['title']['text'],'Keep title');self.assertEqual(result['intro']['path'],'intro.png')
        self.assertEqual(result['broll'][0]['path'],'b.png');self.assertEqual(result['params']['output_fps'],'60')
        self.assertEqual(result['watermarks'][0]['path'],'logo.png')
        page.close();page.deleteLater()

    def test_bulk_style_keeps_each_video_script_and_retimes_words(self):
        from app.ui.packaging_page import PackagingPage
        page=PackagingPage()
        first=page._default_state('a.mp4');second=page._default_state('b.mp4')
        first['captions']=[{'start':1.,'end':3.,'text':'Hello world',
            'words':[{'start':1.,'end':2.,'text':'Hello'},{'start':2.,'end':3.,'text':'world'}]}]
        second['captions']=[{'start':0.,'end':2.,'text':'Different script'}]
        page._project={'videos':{'a.mp4':first,'b.mp4':second},'order':['a.mp4','b.mp4']}
        page._current_path='a.mp4';page._load_state(first)
        page.caption_table.item(0,0).setText('2.000')
        page.caption_table.item(0,1).setText('6.000')
        result=page._capture_controls()['captions'][0]
        self.assertEqual(result['words'][1]['start'],4.)
        self.assertEqual(result['words'][1]['end'],6.)
        page._apply_to_all()
        self.assertEqual(second['captions'][0]['text'],'Different script')
        page.close();page.deleteLater()

    def test_watermark_alpha_and_gif_timing(self):
        from PIL import Image
        from app.services.packaging_watermark import prepare_knockout,gif_frames
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'logo.png'
            im=Image.new('RGBA',(2,1),'white');im.putpixel((0,0),(255,0,0,128));im.save(source)
            with Image.open(prepare_knockout(source)) as result:
                self.assertEqual(result.getpixel((1,0)),(255,255,255,255))
                self.assertEqual(result.getpixel((0,0))[3],128)
            animated=Path(folder)/'animated.gif'
            Image.new('RGB',(2,2),'red').save(animated,save_all=True,
                append_images=[Image.new('RGB',(2,2),'blue')],duration=[100,300],loop=0)
            frames,duration=gif_frames(animated)
            self.assertEqual(len(frames),2);self.assertAlmostEqual(duration,.4)
            self.assertAlmostEqual(frames[1]['start'],.1)

    def test_render_output_appends_after_cursor_moved_and_updates_progress(self):
        from unittest.mock import Mock
        from PySide6.QtGui import QTextCursor
        from app.ui.packaging_page import PackagingPage
        page=PackagingPage()
        page.remotion_log.setPlainText('existing\n')
        page.remotion_log.moveCursor(QTextCursor.MoveOperation.Start)
        proc=Mock()
        proc.readAllStandardOutput.return_value=b'render 42%\n'
        page._read_render_output(proc)
        self.assertEqual(page.remotion_log.toPlainText(),'existing\nrender 42%\n')
        self.assertEqual(page.render_progress.value(),42)
        proc.readAllStandardOutput.return_value=b'next 75%\n'
        page._read_render_output(proc)
        self.assertTrue(page.remotion_log.toPlainText().endswith('next 75%\n'))
        self.assertEqual(page.render_progress.value(),75)
        page.close();page.deleteLater()

    def test_failed_render_start_advances_once(self):
        from unittest.mock import patch
        from PySide6.QtCore import QProcess
        from app.ui.packaging_page import PackagingPage
        page=PackagingPage();state=page._default_state('a.mp4')
        page._project={'videos':{'a.mp4':state},'order':['a.mp4']}
        page._rendering_path='a.mp4';page._render_total=1;page._render_output='out.mp4'
        proc=QProcess(page);page._render_process=proc
        with patch('app.ui.packaging_page.QTimer.singleShot') as advance:
            page._render_error(proc,QProcess.FailedToStart)
            page._render_finished(proc,1)
            self.assertEqual(page._render_done,1)
            self.assertEqual(state['status'],'失败')
            advance.assert_called_once()
        page.close();page.deleteLater()

if __name__=='__main__':unittest.main()
