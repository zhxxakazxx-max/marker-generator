"""Batch generator tests. Provider calls always use local fixtures."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from studio.batch_generator import BatchState, build_batch_jobs, valid_png


class BatchPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fabric-batch-TEST-")
        self.output = Path(self.temp.name)
        self.compositions = [
            {
                "source": "Sheet1!C4",
                "label": "腈纶40%棉60%",
                "raw": "腈纶40%棉60%",
                "parts": [{"name": "Acrylic", "percent": 40}, {"name": "Cotton", "percent": 60}],
            },
            {
                "source": "Sheet1!C5",
                "label": "棉100%",
                "parts": [{"name": "Cotton", "percent": 100}],
            },
        ]
        self.colors = [
            {"id": "light_blue", "name": "浅蓝 / Light blue", "hex": "#AABED0"},
            {"id": "ivory", "name": "米白 / Ivory", "hex": "#D9D9C9"},
        ]

    def tearDown(self):
        self.temp.cleanup()

    def test_jobs_use_one_chinese_composition_folder_and_chinese_color_files(self):
        jobs = build_batch_jobs(self.compositions, self.colors, self.output)
        self.assertEqual(len(jobs), 4)
        self.assertEqual(
            [Path(job["path"]).relative_to(self.output.resolve()).as_posix() for job in jobs],
            [
                "腈纶40%棉60%/浅蓝.png",
                "腈纶40%棉60%/米白.png",
                "棉100%/浅蓝.png",
                "棉100%/米白.png",
            ],
        )
        self.assertEqual(len({job["id"] for job in jobs}), 4)
        self.assertTrue(all(job["status"] == "queued" and job["attempts"] == 0 for job in jobs))

    def test_original_chinese_text_names_folder_when_normalized_label_is_english(self):
        composition = {
            "source": "Sheet1!C4",
            "raw": "腈纶40%棉60%",
            "label": "40% Acrylic · 60% Cotton",
            "parts": [{"name": "Acrylic", "percent": 40}, {"name": "Cotton", "percent": 60}],
        }
        jobs = build_batch_jobs([composition], self.colors[:1], self.output)
        relative = Path(jobs[0]["path"]).relative_to(self.output.resolve()).as_posix()
        self.assertEqual(relative, "腈纶40%棉60%/浅蓝.png")

    def test_resume_keeps_completed_png_and_requeues_interrupted_attempt_with_budget(self):
        jobs = build_batch_jobs(self.compositions, self.colors, self.output)
        first = Path(jobs[0]["path"])
        first.parent.mkdir(parents=True)
        fixture = Path(__file__).resolve().parents[1] / "assets" / "size-free-example.png"
        shutil.copyfile(fixture, first)
        jobs[0].update(status="running", attempts=1, error="old")
        jobs[1].update(status="running", attempts=2, error="connection lost")
        jobs[2].update(status="failed", attempts=3, error="three failures")
        (self.output / "batch-progress.json").write_text(json.dumps({"jobs": jobs}, ensure_ascii=False), "utf-8")

        state = BatchState.open(self.output, self.compositions, self.colors)

        self.assertTrue(valid_png(first))
        self.assertEqual(state.jobs[0]["status"], "completed")
        self.assertEqual((state.jobs[0]["attempts"], state.jobs[0]["error"]), (1, ""))
        self.assertEqual((state.jobs[1]["status"], state.jobs[1]["attempts"]), ("queued", 2))
        self.assertEqual((state.jobs[2]["status"], state.jobs[2]["attempts"]), ("failed", 3))
        self.assertEqual(state.jobs[3]["status"], "queued")

    def test_progress_save_is_utf8_and_does_not_store_api_key(self):
        state = BatchState.open(self.output, self.compositions, self.colors)
        state.save()
        raw = (self.output / "batch-progress.json").read_text("utf-8")
        self.assertIn("腈纶40%棉60%", raw)
        self.assertNotIn("api_key", raw)
        self.assertNotIn("secret", raw.casefold())

    def test_retry_failed_resets_only_failed_jobs_with_a_new_three_attempt_budget(self):
        state = BatchState.open(self.output, self.compositions, self.colors)
        state.jobs[0].update(status="failed", attempts=3, error="HTTP 502")
        state.jobs[0]["attempt_history"] = [{"attempt": value} for value in (1, 2, 3)]
        state.jobs[1].update(status="completed", attempts=1, error="")

        count = state.retry_failed()

        self.assertEqual(count, 1)
        self.assertEqual(
            (state.jobs[0]["status"], state.jobs[0]["attempts"], state.jobs[0]["error"], state.jobs[0]["attempt_history"]),
            ("queued", 0, "", []),
        )
        self.assertEqual((state.jobs[1]["status"], state.jobs[1]["attempts"]), ("completed", 1))


if __name__ == "__main__":
    unittest.main()
