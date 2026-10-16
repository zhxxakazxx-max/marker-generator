"""Render synthetic queue states at two window sizes; no customer data or API calls."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from studio.app import MainWindow
from studio.theme import STYLE

app = QApplication([])
for name in ['segoeui.ttf', 'segoeuib.ttf', 'msyh.ttc']:
    QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name))
app.setStyle('Fusion')
app.setStyleSheet(STYLE)
app.setFont(QFont('Segoe UI', 10))
out = Path(__file__).resolve().parents[1] / 'qa'
out.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as temp:
    window = MainWindow(temp)
    window.timer.stop()
    window.jobs = [window.new_job([{'name': 'Cotton', 'percent': 100}], color)
                   for _ in range(10) for color in window.colors]
    window.jobs[2].update(status='retrying', attempts=2, error='The provider is temporarily unavailable. (HTTP 502)')
    window.jobs[7].update(status='failed', attempts=3, error='The provider is temporarily unavailable. (HTTP 502)')
    window.queue_message = '米白 / Ivory：第 2/3 次失败，等待 10 秒后重试。'
    window.refresh_jobs()
    window.navigate(1)
    window.queue.setCurrentCell(2, 0)
    window.show()
    for width, height in [(1450, 940), (1120, 760)]:
        window.resize(width, height)
        app.processEvents()
        window.grab().save(str(out / f'queue-{width}.png'))
    window.close()
