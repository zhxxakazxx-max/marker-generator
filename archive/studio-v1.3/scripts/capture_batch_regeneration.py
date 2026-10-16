"""Capture synthetic batch selection; does not access customer data or the network."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
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
                   for color in window.colors]
    for job in window.jobs:
        job.update(status='failed', attempts=3, error='The provider is temporarily unavailable for this attempt. (HTTP 502)')
    window.queue_message = 'Select rows, then Regenerate selected / 选择多个任务后点击批量重生成。'
    window.refresh_jobs()
    window.navigate(1)
    table = window.queue
    table.setCurrentCell(2, 0)
    for row in [1, 2, 3]:
        table.selectionModel().select(table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    window.feedback.setText('Sharper stitching / 缝线更清晰')
    window.show()
    for width, height in [(1450, 940), (1120, 760)]:
        window.resize(width, height)
        app.processEvents()
        window.grab().save(str(out / f'batch-{width}.png'))
    window.close()
