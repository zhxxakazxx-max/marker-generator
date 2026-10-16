"""Capture the actual app widgets for visual QA; no network calls."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from studio.app import MainWindow
from studio.theme import STYLE

app = QApplication([])
for filename in ['segoeui.ttf', 'segoeuib.ttf', 'msyh.ttc']:
    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / filename
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
app.setStyle('Fusion')
app.setStyleSheet(STYLE)
with tempfile.TemporaryDirectory() as temp:
    window = MainWindow(temp)
    window.show()
    app.processEvents()
    output = Path(__file__).resolve().parents[1] / 'qa'
    output.mkdir(exist_ok=True)
    for i, name in enumerate(['create', 'review', 'settings']):
        window.navigate(i)
        app.processEvents()
        window.grab().save(str(output / (name + '.png')))
    window.close()
