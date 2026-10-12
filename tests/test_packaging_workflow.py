import os,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QDialog
from PySide6.QtCore import QSettings,Qt
from PySide6.QtGui import QImage,QColor
from app.core import database,repository,work_dates
from app.services import performance_types,eye_states
APP=QApplication.instance() or QApplication([])

class PackagingWorkflowTests(unittest.TestCase):
    def test_merge_and_edit_keep_type_confirmation(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(database,'DB_PATH',Path(folder)/'test.db'):
            database.init_db()
            with database.connect() as con:
                con.execute("INSERT INTO recipients(id,name,work_date) VALUES(1,'test','2026-10-12')")
                con.execute("INSERT INTO hosts(id,recipient_id,name) VALUES(1,1,'host')")
                con.execute("INSERT INTO videos(id,host_id,seq) VALUES(1,1,1)")
                for i,text in enumerate(['First prayer.','Then speaking.','Keep this.'],1):con.execute('INSERT INTO flow_segments(id,video_id,seg_seq,foreign_text) VALUES(?,1,?,?)',(i,i,text))
            eye_states.save_modes(1,['First prayer.','Then speaking.','Keep this.'],['PRAYING','TALKING','PRAYING'])
            repository.merge_prompt_segment(1,'next','TALKING')
            repository.edit_prompt_segment_text(1,'Merged and edited.')
            with database.connect() as con:
                choices=performance_types.choices(con,1)
                self.assertEqual(performance_types.selected_mode(choices,{'segment_id':1,'foreign_text':'Merged and edited.'}),'TALKING')
                self.assertEqual(choices['1']['source'],'manual')
                self.assertEqual(choices['3']['source'],'sheet_color')
                self.assertEqual(performance_types.confirmed_videos(con,{1:'2026-10-12'}),{1})
                self.assertEqual(con.execute('SELECT manual_text_lock FROM flow_segments WHERE id=1').fetchone()[0],1)
            repository.set_prompt_segment_type(1,'PRAYING')
            with database.connect() as con:
                self.assertEqual(performance_types.choices(con,1)['1']['mode'],'PRAYING')
                con.execute("UPDATE flow_segments SET generation_command='active' WHERE id=1")
            with self.assertRaises(ValueError):repository.merge_prompt_segment(1,'next','TALKING')

    def test_clear_does_not_reimport_same_export_or_remove_video(self):
        from app.ui.packaging_page import PackagingPage
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'output.mp4';source.write_bytes(b'original')
            row={'id':123,'edit_output_path':str(source),'original_script':'Original task text','production_script':'','script':''}
            page=PackagingPage();page._settings=QSettings(str(Path(folder)/'ui.ini'),QSettings.IniFormat)
            with patch('app.services.packaging_tasks.edited_tasks',return_value=[row]):
                page.sync_edited_videos();page.sync_edited_videos()
                self.assertEqual(page._project['order'],[str(source.resolve())])
                self.assertEqual(page._project['videos'][str(source.resolve())]['source_script'],'Original task text')
                page._clear_tasks();page.sync_edited_videos()
                self.assertEqual(page._project['order'],[])
                self.assertEqual(source.read_bytes(),b'original')
            page.close();page.deleteLater()

    def test_prefilled_script_requires_confirmation(self):
        from app.ui.packaging_proofread import BatchScriptProofreadDialog
        srt='1\n00:00:00,000 --> 00:00:02,000\nhello word\n'
        dialog=BatchScriptProofreadDialog(None,[{'path':'clip.mp4','srt':srt,'words':srt,'script':'hello world'}])
        self.assertEqual(dialog.table.cellWidget(0,2).toPlainText(),'hello world')
        self.assertIn(0,dialog.results)
        self.assertEqual(dialog.table.item(0,0).checkState(),Qt.Unchecked)
        self.assertNotEqual(dialog.result(),QDialog.DialogCode.Accepted)
        dialog.close();dialog.deleteLater()

    def test_watermark_preview_updates_position_and_opacity(self):
        from app.ui.packaging_watermark_preview import WatermarkPreview
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'logo.png';im=QImage(20,20,QImage.Format_RGBA8888);im.fill(QColor('red'));im.save(str(path))
            view=WatermarkPreview(None);view.resize(100,100)
            item={'path':str(path),'scale':20,'opacity':100,'margin':0,'position':'右上'}
            view.set_layers([item],0,(100,100));view.show();APP.processEvents()
            self.assertGreater(view.grab().toImage().pixelColor(90,10).red(),240)
            item['position']='左下';view.set_layers([item],0,(100,100));APP.processEvents()
            self.assertGreater(view.grab().toImage().pixelColor(10,90).red(),240)
            view.clear();self.assertFalse(view.isVisible());view.close();view.deleteLater()

if __name__=='__main__':unittest.main()
