from pathlib import Path
import os,sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['FLOWSTUDIO_DATA_DIR']=str(ROOT/'build/packaging-tests')
os.environ['FLOWSTUDIO_CAPTION_PRESET_DIR']=str(ROOT/'build/packaging-tests/presets')
from PySide6.QtWidgets import QApplication
from app.ui.packaging_page import PackagingPage
from app.services.packaging_overlay import load_caption_fonts
app=QApplication([]);load_caption_fonts()
from app.ui.styles import LIGHT
app.setStyleSheet(LIGHT);page=PackagingPage();page.resize(1600,1000)
path=str(ROOT/'build/packaging-tests/source.mp4')
state=page._default_state(path);state['duration']=3
state['captions']=[{'start':0,'end':3,'text':'Hello beautiful world','words':[{'start':0,'end':1,'text':'Hello'},{'start':1,'end':2,'text':'beautiful'},{'start':2,'end':3,'text':'world'}]}]
state['reelsStyle']=page._reels_presets['Descript 经典黄']
state['watermarks']=[{'path':str(ROOT/'build/packaging-tests/logo.png'),'enabled':True}]
page._project={'order':[path],'videos':{path:state}};page._current_path=path
page._load_state(state);page._rebuild_tree(False);page.show();app.processEvents()
for index in (0,1,2,6):
    page.tabs.setCurrentIndex(index);app.processEvents()
    page.grab().save(str(ROOT/f'build/packaging-tests/page-{index}.png'))
page.close();print('Packaging screenshots saved')
