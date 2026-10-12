import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
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
