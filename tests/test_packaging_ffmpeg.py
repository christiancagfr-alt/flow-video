import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from app.services import packaging_ffmpeg as native

APP=QApplication.instance() or QApplication([])


class NativePackagingTests(unittest.TestCase):
    def test_unopened_batch_video_uses_actual_duration(self):
        payload={'source':'long.mp4','mainDuration':0,'intro':{'enabled':True,'path':'intro.png','duration':2}}
        with patch.object(native,'probe_media',return_value={'duration':174.87}):native.resolve_duration(payload)
        self.assertAlmostEqual(payload['mainDuration'],174.87)
        self.assertAlmostEqual(payload['totalDuration'],176.87)

    def test_gaps_keep_subtitle_timing(self):
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder)
            payload={'fps':25,'mainDuration':4}
            layers=[{'path':str(work/'a.png'),'start':25,'duration':25},
                    {'path':str(work/'b.png'),'start':75,'duration':25}]
            with patch.object(native,'prepare_overlays',return_value={'captionOverlays':layers}):
                sequence=native.caption_sequence(payload,work).read_text('utf-8')
            durations=[float(line.split()[1]) for line in sequence.splitlines() if line.startswith('duration ')]
            self.assertEqual(durations,[1,1,1,1])
            files=[line for line in sequence.splitlines() if line.startswith('file ')]
            self.assertIn('blank.png',files[0]);self.assertIn('blank.png',files[2])
            self.assertEqual(files[-1],files[-2])

    def test_legacy_effects_require_compatibility(self):
        self.assertTrue(native.compatibility_reason({'captions':[{'text':'existing'}]}))
        self.assertFalse(native.compatibility_reason({'captions':[{'text':'reels'}],'reelsStyle':{'effect':'plain'}}))
        self.assertTrue(native.compatibility_reason({'reelsStyle':{'free_animation':'持续向上滚动'}}))
        self.assertTrue(native.compatibility_reason({'reelsStyle':{'free_animation':'中间固定滚动'}}))
        self.assertTrue(native.compatibility_reason({'reelsStyle':{'free_animation':'自定义区域滚动'}}))

    def test_middle_scroll_stays_inside_the_band(self):
        from app.services.packaging_overlay import paint_at, scroll_band
        style={'free_animation':'中间固定滚动','font':'Arial','font_size':72,'text':'#FFFFFF','outline':'#111111','outline_width':4,'line_length':10,'line_spacing':110}
        captions=[{'text':'SCROLL LINE ONE','start':0,'end':4},{'text':'SCROLL LINE TWO','start':0,'end':4},{'text':'SCROLL LINE THREE','start':0,'end':4}]
        band=scroll_band(style)
        self.assertLess(band['top'],960)
        self.assertGreater(band['top']+band['height'],960)
        self.assertLess(band['top']+band['height'],1900)
        image=paint_at(captions,style,2.0)
        def opaque(x,y):
            return image.pixelColor(x,y).alpha()>0
        self.assertFalse(any(opaque(540,y) for y in range(0,band['top'])))
        self.assertFalse(any(opaque(540,y) for y in range(band['top']+band['height'],1920)))
        self.assertTrue(any(opaque(x,y) for y in range(band['top']+80,band['top']+band['height']-80) for x in range(200,880,40)))

    def test_custom_scroll_respects_area_and_entry_exit_positions(self):
        from app.services.packaging_overlay import CUSTOM_SCROLL, paint_at, scroll_band, scroll_positions
        style={'free_animation':CUSTOM_SCROLL,'font':'Arial','font_size':72,'text':'#FFFFFF','outline':'#111111',
               'outline_width':4,'line_length':10,'line_spacing':110,'scroll_area_top':25,'scroll_area_bottom':65,
               'scroll_start_y':100,'scroll_end_auto':True}
        band=scroll_band(style)
        self.assertEqual(band['top'],480)
        self.assertEqual(band['height'],768)
        self.assertEqual(scroll_positions(style,1920,600),(1920,-600))
        style.update({'scroll_end_auto':False,'scroll_end_y':-150})
        self.assertEqual(scroll_positions(style,1920,600),(1920,-2880))
        style['scroll_end_auto']=True
        captions=[{'text':'CUSTOM SCROLL ONE','start':0,'end':4},{'text':'CUSTOM SCROLL TWO','start':0,'end':4},
                  {'text':'CUSTOM SCROLL THREE','start':0,'end':4}]
        from app.services.packaging_overlay import prepare_overlays
        with tempfile.TemporaryDirectory() as folder:
            prepared=prepare_overlays({'captions':captions,'reelsStyle':style,'fps':30,'mainDuration':4},Path(folder))
            layer=prepared['captionOverlays'][0]
            self.assertEqual(layer['scrollBand'],band)
            self.assertEqual(layer['scrollPath']['startY'],1920)
            self.assertEqual(layer['scrollPath']['endY'],-layer['imageHeight'])
        image=paint_at(captions,style,2.0)
        def opaque(x,y):return image.pixelColor(x,y).alpha()>0
        self.assertFalse(any(opaque(540,y) for y in range(0,band['top'])))
        self.assertFalse(any(opaque(540,y) for y in range(band['top']+band['height'],1920)))
        self.assertTrue(any(opaque(x,y) for y in range(band['top']+40,band['top']+band['height']-40) for x in range(200,880,40)))

    def test_custom_scroll_controls_apply_and_update_style(self):
        from app.ui.packaging_reels import PackagingReelsMixin
        class Settings:
            @staticmethod
            def value(key, default='', type=str):return default
            @staticmethod
            def setValue(key, value):pass
        class Host(QWidget, PackagingReelsMixin):
            def __init__(self):
                super().__init__();self._settings=Settings();self._loading_state=False;self._reels_style={};self.changed=False
            def _state_changed(self):self.changed=True
        host=Host();layout=QVBoxLayout(host)
        host._add_reels_styles(layout)
        self.assertTrue(host.scroll_options.isHidden())
        host.reels_preset.setCurrentText('滚动字幕 · 自定义区域');host._apply_reels_style()
        self.assertFalse(host.scroll_options.isHidden())
        host.scroll_area_top.setValue(30)
        self.assertEqual(host._reels_style['scroll_area_top'],30)
        host.scroll_end_auto.setChecked(False)
        self.assertTrue(host.scroll_end_y.isEnabled())
        self.assertFalse(host._reels_style['scroll_end_auto'])

    def test_graph_retains_intro_outro_audio_and_input_order(self):
        with tempfile.TemporaryDirectory() as folder:
            p={'source':'main.mp4','mainDuration':3,'fps':25,'width':720,'height':1280,
               'intro':{'enabled':True,'path':'intro.png','duration':1},
               'outro':{'enabled':True,'path':'outro.mp4','duration':2}}
            original=copy.deepcopy(p)
            with patch.object(native,'find_ffmpeg',return_value='ffmpeg'),patch.object(native,'probe_media',return_value={'audio':True}):
                command,duration=native.build_command(p,'result.mp4',Path(folder),['-c:v','libx264'])
            graph=(Path(folder)/'graph.txt').read_text('utf-8')
            self.assertIn('[intro][aintro][main][amain][outro][aoutro]concat=n=3',graph)
            self.assertIn('anullsrc=r=48000:cl=stereo',graph)
            self.assertEqual(duration,6);self.assertEqual(p,original)
            self.assertEqual(command[command.index('-filter_complex_threads')+1],'1')

    def test_preview_consumes_audio_output(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(native,'find_ffmpeg',return_value='ffmpeg'),patch.object(native,'probe_media',return_value={'audio':False}):
                command,_=native.build_command({'source':'main.mp4','mainDuration':3},'preview.png',Path(folder),[],preview_frame=30)
            self.assertIn('[finala]anullsink',(Path(folder)/'graph.txt').read_text('utf-8'))
            self.assertEqual(command[command.index('-frames:v')+1],'1')

    def test_unusable_gpu_falls_back_without_lowering_resolution(self):
        with patch.object(native.process,'run',side_effect=OSError):
            arguments,name=native.encoder_args('ffmpeg','h264')
        self.assertIn('libx264',arguments);self.assertIn('16',arguments);self.assertNotIn('-s',arguments)
