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

from PySide6.QtWidgets import QApplication, QLineEdit

from studio.app import MainWindow, asset
from studio.domain import composition_text
from studio.storage import Store


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
        self.temp.cleanup()

    def until(self, predicate, description="workflow condition", timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
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
