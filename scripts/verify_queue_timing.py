"""Verify real ten-second retry waits and Qt responsiveness without any API calls."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from studio.app import MainWindow
from studio.providers import _http_error

app = QApplication([])
calls, ticks = [], []
heartbeat = QTimer()
heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
heartbeat.start(50)

def unavailable(*args):
    calls.append(time.monotonic())
    raise _http_error(502)

with tempfile.TemporaryDirectory(prefix='fabric-retry-timing-') as temp:
    window = MainWindow(temp)
    window.settings['api_key'] = 'TEST-LOCAL-NO-API'
    window.jobs = [window.new_job([{'name': 'Cotton', 'percent': 100}], window.colors[0])]
    with patch('studio.app.generate_image', side_effect=unavailable):
        window.start_queue()
        deadline = time.monotonic() + 40
        while (window.running or window.workers) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
    assert not window.running and not window.workers, 'Queue did not finish'
    assert len(calls) == 3, calls
    gaps = [right - left for left, right in zip(calls, calls[1:])]
    assert all(gap >= 10 for gap in gaps), gaps
    assert window.jobs[0]['status'] == 'failed'
    assert window.jobs[0]['attempts'] == 3
    assert len(ticks) > 100, 'Qt was blocked during retry waits'
    window.close()
    print(f'PASS: exactly 3 attempts; retry gaps {gaps[0]:.2f}s, {gaps[1]:.2f}s; Qt heartbeat {len(ticks)} ticks.')
