"""Desktop workflow tests. Provider output is a copied TEST FIXTURE, never a live generation."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtTest import QTest

from studio.app import MainWindow, asset
from studio.domain import composition_text
from studio.storage import Store
from studio.providers import _http_error


TEST_SECRET = "test-only-local-api-key-DO-NOT-EXPORT"
FIXTURE_MARKER = "TEST FIXTURE: bundled example copied by a mocked provider; no API image generation occurred."


def mock_image(settings, parts, color, reference, output, feedback="", fabric=""):
    """Create a temporary copied fixture, explicitly marked in job prompt and sidecar."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(asset("size-free-example.png"), output)
    output.with_suffix(".test-only.txt").write_text(FIXTURE_MARKER, encoding="utf-8")
    return {"path": str(output), "prompt": FIXTURE_MARKER, "model": "TEST-MOCK-image-model"}


class DesktopWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.now = 1000.0
        self.clock_patch = patch('studio.app.queue_clock', lambda: self.now, create=True)
        self.clock_patch.start()
        self.temp = tempfile.TemporaryDirectory(prefix="fabric-studio-TEST-")
        self.folder = Path(self.temp.name)
        self.notices = []
        self.notice_patch = patch.object(MainWindow, "notice", lambda instance, text: self.notices.append(str(text)))
        self.notice_patch.start()
        self.window = MainWindow(self.folder)
        self.window.timer.stop()
        self.window.settings["api_key"] = TEST_SECRET
        self.release_events = []

    def tearDown(self):
        for event in self.release_events:
            event.set()
        self.window.running = False
        self.window.timer.stop()
        deadline = time.monotonic() + 5
        while self.window.workers and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.window.pool.waitForDone(5000)
        self.application.processEvents()
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        self.notice_patch.stop()
        self.clock_patch.stop()
        self.temp.cleanup()

    def until(self, predicate, description="workflow condition", timeout=8, advance_clock=True):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if advance_clock:
                self.now += 10
            self.application.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        self.fail(f"Timed out waiting for {description}; statuses={[j['status'] for j in self.window.jobs]}, active={self.window.active_ids}")

    def enqueue(self, compositions=1, colors=1):
        self.window.tabs.setCurrentIndex(0)
        self.window.library.clearSelection()
        for index in range(compositions):
            self.window.library.item(index).setSelected(True)
        self.window.set_colors(False)
        for index in range(colors):
            self.window.swatches[index].setChecked(True)
        self.window.enqueue_selection()

    def complete_queue(self):
        self.window.timer.start(10)
        self.window.start_queue()
        self.until(lambda: not self.window.running and not self.window.workers, "all queued jobs completed")

    def test_queue_all_document_combinations_requires_confirmation_and_adds_every_pair(self):
        self.assertEqual((self.window.library.count(), len(self.window.colors)), (119, 12))
        with patch("studio.app.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            self.window.all_combinations_btn.click()
        self.assertEqual(self.window.jobs, [])

        with patch("studio.app.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            self.window.all_combinations_btn.click()

        self.assertEqual(len(self.window.jobs), 1428)
        pairs = {(composition_text(job["parts"]), job["color"]["id"]) for job in self.window.jobs}
        self.assertEqual(len(pairs), 1428)
        self.assertTrue(all(job["status"] == "queued" and job["attempts"] == 0 for job in self.window.jobs))
        self.assertIn("1,428", self.window.statusBar().currentMessage())
        self.assertIn("4,284", self.window.queue_state.text())

    def test_generated_and_exported_png_names_include_composition_color_and_unique_job_suffix(self):
        self.enqueue()
        job = self.window.jobs[0]
        expected_name = f"40% Acrylic_60% Cotton__light_blue__{job['id'][:8]}.png"
        with patch("studio.app.generate_image", side_effect=mock_image):
            self.complete_queue()

        self.assertEqual(Path(job["path"]).name, expected_name)
        self.window.queue.setCurrentCell(0, 0)
        self.window.approve_job()
        target = self.window.export_to(self.folder / "named-exports")
        self.assertTrue((target / expected_name).is_file())

    def test_queue_ctrl_shift_selection_and_select_all_clear_controls(self):
        self.enqueue(compositions=1, colors=5)
        for job in self.window.jobs:
            job['status'] = 'failed'
        self.window.persist_jobs()
        self.window.navigate(1)
        self.window.show()
        self.application.processEvents()
        table = self.window.queue

        def click(row, modifier=Qt.KeyboardModifier.NoModifier):
            QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, modifier,
                             table.visualRect(table.model().index(row, 0)).center())

        click(0)
        click(2, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(sorted(i.row() for i in table.selectionModel().selectedRows()), [0, 2])
        self.window.refresh_jobs()
        click(4, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(sorted(i.row() for i in table.selectionModel().selectedRows()), [0, 2, 3, 4])
        click(0)
        click(3, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(sorted(i.row() for i in table.selectionModel().selectedRows()), [0, 1, 2, 3])
        self.window.select_all_jobs_btn.click()
        self.assertEqual(len(table.selectionModel().selectedRows()), 5)
        self.assertTrue(self.window.batch_regen_btn.isEnabled())
        self.window.clear_job_selection_btn.click()
        self.assertEqual(table.selectionModel().selectedRows(), [])
        self.assertFalse(self.window.batch_regen_btn.isEnabled())

    def test_queue_refresh_keeps_selected_job_ids_and_preview_current_job(self):
        self.enqueue(compositions=1, colors=5)
        table = self.window.queue
        selection = table.selectionModel()
        selection.clearSelection()
        for row in [0, 2]:
            selection.select(table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        table.setCurrentCell(2, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
        expected = {self.window.jobs[0]['id'], self.window.jobs[2]['id']}
        current_id = self.window.jobs[2]['id']
        self.window.jobs.reverse()
        self.window.persist_jobs()
        actual = {self.window.jobs[i.row()]['id'] for i in selection.selectedRows()}
        self.assertEqual(actual, expected)
        self.assertEqual(self.window.current_job()['id'], current_id)

    def test_batch_regenerate_preserves_results_skips_active_and_pending_children(self):
        self.enqueue(compositions=1, colors=8)
        for job, status in zip(self.window.jobs, ['failed', 'review', 'approved', 'cancelled', 'interrupted', 'queued', 'running', 'retrying']):
            job.update(status=status, attempts=3, feedback='old notes', error='historical error')
        image_job = self.window.jobs[2]
        old_image = self.folder / 'approved.png'
        shutil.copyfile(asset('size-free-example.png'), old_image)
        image_job['path'] = str(old_image)
        image_bytes = old_image.read_bytes()
        original = copy.deepcopy(self.window.jobs)
        pending = self.window.new_job(original[0]['parts'], original[0]['color'], parent=original[0]['id'])
        self.window.jobs.append(pending)
        self.window.persist_jobs()
        self.window.queue.selectAll()
        self.window.feedback.setText('Make the seam clearer')
        self.window.regenerate_selected_jobs()
        self.assertEqual(self.window.jobs[:8], original)
        self.assertEqual(self.window.jobs[8], pending)
        self.assertEqual(len(self.window.jobs), 13)
        new_jobs = self.window.jobs[9:]
        self.assertEqual([job['parent'] for job in new_jobs], [job['id'] for job in original[1:5]])
        for job, parent in zip(new_jobs, original[1:5]):
            self.assertEqual(job['parts'], parent['parts'])
            self.assertEqual(job['color'], parent['color'])
            self.assertEqual((job['status'], job['attempts'], job['path'], job['feedback']),
                             ('queued', 0, '', 'Make the seam clearer'))
        self.assertEqual(old_image.read_bytes(), image_bytes)
        self.assertFalse(self.window.running)
        self.assertEqual(len(self.window.queue.selectionModel().selectedRows()), 9)
        self.assertIn('4', self.window.queue_state.text())
        self.assertIn('5', self.window.queue_state.text())
        self.window.regenerate_selected_jobs()
        self.assertEqual(len(self.window.jobs), 13)
        self.assertFalse(self.window.batch_regen_btn.isEnabled())

    def test_batch_regenerate_uses_existing_notes_when_shared_notes_empty(self):
        self.enqueue(compositions=1, colors=2)
        for i, job in enumerate(self.window.jobs):
            job.update(status='failed', feedback=f'original feedback {i}', custom_fabric='saved-reference.png', source='Custom')
        self.window.persist_jobs()
        self.window.queue.selectAll()
        self.window.feedback.setText('   ')
        self.window.regenerate_selected_jobs()
        new = self.window.jobs[2:]
        self.assertEqual(len(new), 2)
        self.assertEqual([job['feedback'] for job in new], ['original feedback 0', 'original feedback 1'])
        self.assertTrue(all(job['custom_fabric'] == 'saved-reference.png' and job['source'] == 'Custom' for job in new))

    def test_selected_batch_gets_three_attempts_each_and_completes_in_running_queue(self):
        self.enqueue(compositions=1, colors=2)
        for job in self.window.jobs:
            job.update(status='failed', attempts=3)
        self.window.persist_jobs()
        self.window.queue.selectAll()
        self.window.running = True
        calls = {}

        def generate(*args):
            job_id = Path(args[4]).stem
            calls[job_id] = calls.get(job_id, 0) + 1
            if calls[job_id] < 3:
                raise _http_error(502)
            return mock_image(*args)

        with patch('studio.app.generate_image', side_effect=generate):
            self.window.regenerate_selected_jobs()
            self.assertTrue(self.window.running)
            self.window.timer.start(10)
            self.until(lambda: not self.window.running and not self.window.workers)
        self.assertEqual([job['status'] for job in self.window.jobs], ['failed', 'failed', 'review', 'review'])
        self.assertEqual([job['attempts'] for job in self.window.jobs], [3, 3, 3, 3])
        self.assertEqual(sorted(calls.values()), [3, 3])

    def test_bundled_library_custom_validation_and_cartesian_batch(self):
        self.assertEqual(self.window.library.count(), 119)
        self.assertEqual(len(self.window.colors), 12)
        self.assertEqual(len(self.window.catalog["errors"]), 2)
        self.window.tabs.setCurrentIndex(1)
        self.window.set_parts([{"name": "Cotton", "percent": 60}, {"name": "Polyester", "percent": 35}])
        self.window.enqueue_selection()
        self.assertEqual(self.window.jobs, [])
        self.assertIn("100%", self.notices[-1])
        self.enqueue(compositions=2, colors=3)
        self.assertEqual(len(self.window.jobs), 6)
        pairs = {(composition_text(j["parts"]), j["color"]["id"]) for j in self.window.jobs}
        self.assertEqual(len(pairs), 6)
        self.assertEqual(len({j["id"] for j in self.window.jobs}), 6)
        self.assertTrue(all(j["status"] == "queued" for j in self.window.jobs))
        self.assertNotIn(TEST_SECRET, (self.folder / "jobs.json").read_text("utf-8"))

    def test_async_concurrency_pause_and_resume(self):
        self.enqueue(compositions=2, colors=3)
        self.window.settings["concurrency"] = 2
        release = threading.Event()
        self.release_events.append(release)
        lock = threading.Lock()
        metrics = {"active": 0, "peak": 0, "calls": 0}

        def generate(*args):
            self.assertEqual(args[0]["api_key"], TEST_SECRET)
            with lock:
                metrics["active"] += 1
                metrics["calls"] += 1
                metrics["peak"] = max(metrics["peak"], metrics["active"])
            try:
                if not release.wait(5):
                    raise TimeoutError("TEST fixture release was not signaled")
                time.sleep(0.025)
                return mock_image(*args)
            finally:
                with lock:
                    metrics["active"] -= 1

        with patch("studio.app.generate_image", side_effect=generate):
            self.window.timer.start(10)
            self.window.start_queue()
            self.until(lambda: metrics["active"] == 2, "two parallel mock calls")
            self.assertEqual(len(self.window.active_ids), 2)
            self.window.pause_queue()
            release.set()
            self.until(lambda: not self.window.workers, "active calls finish after pause")
            self.assertFalse(self.window.running)
            self.assertEqual(sum(j["status"] == "review" for j in self.window.jobs), 2)
            self.assertEqual(sum(j["status"] == "queued" for j in self.window.jobs), 4)
            self.complete_queue()
        self.assertEqual(metrics["calls"], 6)
        self.assertEqual(metrics["peak"], 2)
        self.assertTrue(all(j["status"] == "review" for j in self.window.jobs))
        self.assertTrue(all(j["prompt"] == FIXTURE_MARKER for j in self.window.jobs))
        self.assertNotIn(TEST_SECRET, (self.folder / "jobs.json").read_text("utf-8"))

    def test_provider_failure_pauses_remaining_jobs_and_resume_is_explicit(self):
        self.enqueue(compositions=1, colors=3)
        self.window.settings["concurrency"] = 1
        with patch("studio.app.generate_image", side_effect=RuntimeError("TEST provider failure")) as generate:
            self.window.timer.start(10)
            self.window.start_queue()
            self.until(lambda: not self.window.workers and not self.window.running, "failure pauses queue")
            self.assertEqual(generate.call_count, 1)
        self.assertEqual([j["status"] for j in self.window.jobs], ["failed", "queued", "queued"])
        self.assertIn("TEST provider failure", self.window.jobs[0]["error"])
        with patch("studio.app.generate_image", side_effect=mock_image):
            self.complete_queue()
        self.assertEqual([j["status"] for j in self.window.jobs], ["failed", "review", "review"])

    def test_single_502_does_not_stop_other_colors(self):
        self.enqueue(compositions=1, colors=4)
        self.window.settings["concurrency"] = 1
        failed_color = self.window.jobs[1]["color"]["id"]

        def generate(*args):
            if args[2]["id"] == failed_color:
                raise _http_error(502)
            return mock_image(*args)

        with patch("studio.app.generate_image", side_effect=generate):
            self.complete_queue()
        self.assertEqual([j["status"] for j in self.window.jobs], ["review", "failed", "review", "review"])
        self.assertIn("1 failed", self.window.queue_stats.text())
        self.assertIn("完成", self.window.queue_state.text())
        self.assertIn("502", self.window.jobs[1]["error"])

    def test_three_attempts_ten_seconds_apart_before_failed_and_regenerate(self):
        self.enqueue()
        job = self.window.jobs[0]
        self.window.queue.setCurrentCell(0, 0)
        with patch("studio.app.generate_image", side_effect=_http_error(502)) as generate:
            self.window.start_queue()
            self.until(lambda: not self.window.workers, advance_clock=False)
            self.assertEqual(job['status'], 'retrying')
            self.assertEqual(job['attempts'], 1)
            self.assertTrue(self.window.running)
            self.assertFalse(self.window.regen_btn.isEnabled())
            self.assertIn('1/3', self.window.queue.item(0, 2).text())
            for attempt in [2, 3]:
                self.now += 9.9
                self.window.dispatch()
                self.assertEqual(generate.call_count, attempt - 1)
                self.now += .1
                self.window.dispatch()
                self.until(lambda: not self.window.workers, advance_clock=False)
                self.assertEqual(job['attempts'], attempt)
            self.assertEqual(job['status'], 'failed')
            self.assertTrue(self.window.regen_btn.isEnabled())
            self.now += 100
            self.window.dispatch()
            self.window.start_queue()
            self.window.dispatch()
            self.assertEqual(generate.call_count, 3)
        self.assertEqual(len(self.window.jobs), 1)
        saved = self.window.store.load_jobs()[0]
        self.assertEqual(saved['attempts'], 3)
        self.assertEqual(len(saved['attempt_history']), 3)
        self.window.regenerate_job()
        self.assertEqual(self.window.jobs[1]['attempts'], 0)
        self.assertEqual(self.window.jobs[1]['parent'], job['id'])

    def test_401_pauses_immediately(self):
        self.enqueue(compositions=1, colors=3)
        self.window.settings["concurrency"] = 1
        with patch("studio.app.generate_image", side_effect=_http_error(401)):
            self.complete_queue()
        self.assertEqual([j["status"] for j in self.window.jobs], ["failed", "queued", "queued"])
        self.assertIn("401", self.window.queue_state.text())

    def test_retry_failed_preserves_results_and_cannot_duplicate_pending_retry(self):
        self.enqueue(compositions=1, colors=3)
        self.window.jobs[0].update(status="failed", error="HTTP 502")
        self.window.jobs[1]["status"] = "approved"
        original = copy.deepcopy(self.window.jobs)
        self.window.persist_jobs()
        self.window.retry_failed_jobs()
        self.window.retry_failed_jobs()
        self.assertEqual(len(self.window.jobs), 4)
        self.assertEqual(self.window.jobs[:3], original)
        retry = self.window.jobs[3]
        self.assertEqual(retry["parent"], original[0]["id"])
        self.assertEqual(retry["status"], "queued")
        self.assertFalse(self.window.running)
        self.assertFalse(self.window.retry_failed_btn.isEnabled())
        with patch("studio.app.generate_image", side_effect=mock_image):
            self.complete_queue()
        self.window.retry_failed_jobs()
        self.assertEqual(len(self.window.jobs), 4)

    def test_late_502_does_not_override_manual_pause(self):
        self.enqueue(compositions=1, colors=3)
        release = threading.Event()
        self.release_events.append(release)
        self.window.settings["concurrency"] = 1

        def generate(*args):
            release.wait(5)
            raise _http_error(502)

        with patch("studio.app.generate_image", side_effect=generate):
            self.window.start_queue()
            self.window.pause_queue()
            release.set()
            self.until(lambda: not self.window.workers)
        self.assertFalse(self.window.running)
        self.assertEqual([j["status"] for j in self.window.jobs], ["retrying", "queued", "queued"])
        self.assertIn("手动", self.window.queue_state.text())

    def test_120_jobs_with_parallel_502_retry_only_failed_color_three_times(self):
        self.enqueue(compositions=10, colors=12)
        self.window.settings["concurrency"] = 4
        failed_id = self.window.jobs[2]["id"][:8]
        calls = []

        def generate(*args):
            job_id = Path(args[4]).stem.rsplit("__", 1)[-1]
            calls.append(job_id)
            if job_id == failed_id:
                raise _http_error(502)
            return mock_image(*args)

        with patch("studio.app.generate_image", side_effect=generate):
            self.complete_queue()
        self.assertEqual(len(calls), 122)
        self.assertEqual(len(set(calls)), 120)
        self.assertEqual(calls.count(failed_id), 3)
        self.assertEqual(sum(j['status'] == 'review' for j in self.window.jobs), 119)
        saved = self.window.store.load_jobs()
        self.assertEqual(sum(j['status'] == 'failed' for j in saved), 1)
        self.assertEqual(self.window.active_ids, set())

    def test_each_failed_task_gets_its_own_three_attempt_budget(self):
        self.enqueue(compositions=1, colors=6)
        self.window.settings["concurrency"] = 1
        failures = {self.window.jobs[i]['id'][:8] for i in [0, 1, 3, 4]}

        def generate(*args):
            if Path(args[4]).stem.rsplit('__', 1)[-1] in failures:
                raise _http_error(503)
            return mock_image(*args)

        with patch("studio.app.generate_image", side_effect=generate):
            self.complete_queue()
        self.assertEqual([j['status'] for j in self.window.jobs],
                         ['failed', 'failed', 'review', 'failed', 'failed', 'review'])
        self.assertEqual([j['attempts'] for j in self.window.jobs], [3, 3, 1, 3, 3, 1])

    def test_success_on_second_attempt_clears_error_and_stops_retrying(self):
        self.enqueue()
        calls = []

        def generate(*args):
            calls.append(1)
            if len(calls) == 1:
                raise _http_error(502)
            return mock_image(*args)

        with patch('studio.app.generate_image', side_effect=generate):
            self.complete_queue()
        job = self.window.jobs[0]
        self.assertEqual((job['status'], job['attempts'], job['error']), ('review', 2, ''))
        self.assertEqual(len(calls), 2)
        self.assertTrue(Path(job['path']).is_file())

    def test_new_requests_are_spaced_even_when_concurrency_allows_more(self):
        self.enqueue(compositions=1, colors=2)
        self.window.settings['concurrency'] = 4
        release = threading.Event()
        self.release_events.append(release)
        calls = []

        def generate(*args):
            calls.append(self.now)
            release.wait(5)
            return mock_image(*args)

        with patch('studio.app.generate_image', side_effect=generate):
            self.window.start_queue()
            self.until(lambda: bool(calls), advance_clock=False)
            self.assertEqual(len(self.window.active_ids), 1)
            self.now += 9.9
            self.window.dispatch()
            self.assertEqual(len(self.window.active_ids), 1)
            self.now += .1
            self.window.dispatch()
            self.until(lambda: len(calls) == 2, advance_clock=False)
            self.assertEqual(calls, [1000.0, 1010.0])
            release.set()
            self.until(lambda: not self.window.workers)

    def test_pause_resume_keeps_attempt_budget_and_cancel_stops_retry(self):
        self.enqueue()
        with patch('studio.app.generate_image', side_effect=_http_error(502)) as generate:
            self.window.start_queue()
            self.until(lambda: not self.window.workers, advance_clock=False)
            self.window.pause_queue()
            self.now += 20
            self.window.dispatch()
            self.assertEqual(generate.call_count, 1)
            self.window.start_queue()
            self.until(lambda: not self.window.workers, advance_clock=False)
            self.assertEqual(self.window.jobs[0]['attempts'], 2)
            self.assertEqual(self.window.jobs[0]['status'], 'retrying')
            self.window.cancel_queued()
            self.now += 100
            self.window.start_queue()
            self.window.dispatch()
            self.assertEqual(generate.call_count, 2)
            self.assertEqual(self.window.jobs[0]['status'], 'cancelled')

    def test_reopen_waiting_retry_retains_two_attempts_and_never_autostarts(self):
        self.enqueue()
        self.window.jobs[0].update(status='retrying', attempts=2, error='HTTP 502')
        self.window.persist_jobs()
        reopened = MainWindow(self.folder)
        try:
            reopened.timer.stop()
            reopened.settings['api_key'] = TEST_SECRET
            self.assertFalse(reopened.running)
            self.assertEqual(reopened.jobs[0]['attempts'], 2)
            with patch('studio.app.generate_image', side_effect=_http_error(502)) as generate:
                reopened.start_queue()
                self.assertEqual(generate.call_count, 0)
                self.now += 10
                reopened.dispatch()
                self.until(lambda: not reopened.workers, advance_clock=False)
                self.assertEqual(reopened.jobs[0]['status'], 'failed')
                self.assertEqual(reopened.jobs[0]['attempts'], 3)
                self.assertEqual(generate.call_count, 1)
        finally:
            reopened.close()
            reopened.deleteLater()

    def test_cancel_during_request_prevents_its_late_failure_from_retrying(self):
        self.enqueue()
        release = threading.Event()
        self.release_events.append(release)

        def generate(*args):
            release.wait(5)
            raise _http_error(502)

        with patch('studio.app.generate_image', side_effect=generate) as provider:
            self.window.start_queue()
            self.window.cancel_queued()
            release.set()
            self.until(lambda: not self.window.workers)
            self.assertEqual(self.window.jobs[0]['status'], 'cancelled')
            self.now += 100
            self.window.start_queue()
            self.window.dispatch()
            self.assertEqual(provider.call_count, 1)

    def test_retry_wait_starts_after_failure_not_request_start(self):
        self.enqueue()
        release = threading.Event()
        self.release_events.append(release)

        def generate(*args):
            release.wait(5)
            raise _http_error(502)

        with patch('studio.app.generate_image', side_effect=generate) as provider:
            self.window.start_queue()
            self.now += 60
            release.set()
            self.until(lambda: not self.window.workers, advance_clock=False)
            self.window.dispatch()
            self.now += 9.9
            self.window.dispatch()
            self.assertEqual(provider.call_count, 1)
            self.now += .1
            self.window.dispatch()
            self.until(lambda: not self.window.workers, advance_clock=False)
            self.assertEqual(provider.call_count, 2)

    def test_approve_regenerate_preserves_old_image_and_exports_only_approved(self):
        self.enqueue()
        with patch("studio.app.generate_image", side_effect=mock_image):
            self.complete_queue()
        self.window.queue.setCurrentCell(0, 0)
        self.window.show_job()
        self.assertTrue(self.window.approve_btn.isEnabled())
        self.assertFalse(self.window.result_photo.original.isNull())
        self.window.approve_job()
        original = copy.deepcopy(self.window.jobs[0])
        original_bytes = Path(original["path"]).read_bytes()
        self.window.feedback.setText("TEST: make stitching sharper")
        self.window.regenerate_job()
        self.assertEqual(self.window.jobs[0], original)
        self.assertEqual(self.window.jobs[1]["parent"], original["id"])
        self.assertEqual(self.window.jobs[1]["feedback"], "TEST: make stitching sharper")
        self.assertEqual(self.window.jobs[1]["path"], "")
        with patch("studio.app.generate_image", side_effect=mock_image):
            self.complete_queue()
        self.assertEqual(self.window.jobs[1]["status"], "review")
        self.assertNotEqual(self.window.jobs[1]["path"], original["path"])
        self.assertEqual(Path(original["path"]).read_bytes(), original_bytes)
        target = self.window.export_to(self.folder / "test-exports")
        manifest_text = (target / "manifest.json").read_text("utf-8")
        manifest = json.loads(manifest_text)
        self.assertEqual(len(manifest), 1)
        self.assertEqual(len(list(target.glob("*.png"))), 1)
        self.assertTrue(manifest[0]["size_free"])
        self.assertEqual(manifest[0]["expected_text"], composition_text(original["parts"]) + "\nMade in China")
        self.assertEqual((target / manifest[0]["file"]).read_bytes(), original_bytes)
        self.assertNotIn(TEST_SECRET, manifest_text)
        self.assertNotIn("api_key", manifest_text)
        self.assertNotIn("prompt", manifest_text)

    def test_reopen_marks_running_jobs_interrupted_and_keeps_completed_jobs(self):
        self.enqueue(compositions=1, colors=2)
        self.window.jobs[0]["status"] = "running"
        self.window.jobs[1]["status"] = "cancelled"
        self.window.store.save_jobs(self.window.jobs)
        reopened = MainWindow(self.folder)
        try:
            reopened.timer.stop()
            self.assertEqual([j["status"] for j in reopened.jobs], ["interrupted", "cancelled"])
            self.assertIn("App closed", reopened.jobs[0]["error"])
            self.assertFalse(reopened.running)
            self.assertEqual(reopened.active_ids, set())
        finally:
            reopened.close()
            reopened.deleteLater()
            self.application.processEvents()

    @unittest.skipUnless(os.name == "nt", "Windows user-scoped settings encryption")
    def test_settings_ui_encryption_and_provider_key_reset(self):
        self.assertEqual(self.window.key.echoMode(), QLineEdit.EchoMode.Password)
        self.window.key.setText(TEST_SECRET)
        self.window.image_model.setCurrentText("TEST-custom-image-model")
        self.window.text_model.setCurrentText("TEST-custom-text-model")
        self.window.concurrency.setValue(3)
        self.window.save_settings()
        raw = (self.folder / "settings.json").read_text("utf-8")
        self.assertNotIn(TEST_SECRET, raw)
        self.assertIn("dpapi:v1:", raw)
        settings = Store(self.folder).load_settings()
        self.assertEqual(settings["api_key"], TEST_SECRET)
        self.assertEqual(settings["image_model"], "TEST-custom-image-model")
        self.assertEqual(settings["text_model"], "TEST-custom-text-model")
        self.assertEqual(settings["concurrency"], 3)
        self.window.provider.setCurrentIndex(self.window.provider.findData("gemini"))
        self.assertEqual(self.window.key.text(), "")
        self.assertEqual(self.window.base_url.text(), "https://generativelanguage.googleapis.com/v1beta")


if __name__ == "__main__":
    unittest.main()
