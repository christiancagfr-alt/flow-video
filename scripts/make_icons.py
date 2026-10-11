from pathlib import Path
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt
from PIL import Image
root=Path(__file__).resolve().parents[1]
app=QApplication([])
image=QImage(1024,1024,QImage.Format.Format_ARGB32);image.fill(Qt.GlobalColor.transparent)
painter=QPainter(image);QSvgRenderer(str(root/'assets/flowstudio.svg')).render(painter);painter.end()
image.save(str(root/'assets/flowstudio.png'))
picture=Image.open(root/'assets/flowstudio.png')
picture.save(root/'assets/flowstudio.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
picture.save(root/'assets/flowstudio.icns')
