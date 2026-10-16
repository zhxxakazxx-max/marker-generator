"""Standalone document-wide batch generator with resumable Chinese folders."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from time import monotonic

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from .domain import composition_text, import_column_c, validate_composition
from .providers import generate_image
from .storage import Store, default_data_dir
from .theme import STYLE


VERSION = "1.0.0"
MAX_ATTEMPTS = 3
REQUEST_INTERVAL_SECONDS = 10
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def asset(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "assets" / name


def safe_component(value: str, fallback: str) -> str:
    value = _INVALID_FILENAME.sub("_", " ".join(str(value).split())).strip(" .")
    if not value or value.upper() in _RESERVED:
        value = fallback
    return value[:120].rstrip(" .") or fallback


def chinese_color_name(color: dict) -> str:
    name = str(color.get("name") or "").split("/", 1)[0].strip()
    return safe_component(name, safe_component(str(color.get("id") or "颜色"), "颜色"))


def build_batch_jobs(compositions: list[dict], colors: list[dict], output_dir: str | Path) -> list[dict]:
    root = Path(output_dir).resolve()
    jobs: list[dict] = []
    seen: set[str] = set()
    for entry in compositions:
        parts = validate_composition(entry.get("parts") or [])
        label = safe_component(
            entry.get("raw") or entry.get("label") or composition_text(parts).replace("\n", "_"),
            "成分",
        )
        for color in colors:
            color_name = chinese_color_name(color)
            identity = json.dumps({"parts": parts, "color": color.get("id")}, ensure_ascii=False, sort_keys=True)
            job_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
            if job_id in seen:
                continue
            seen.add(job_id)
            jobs.append({
                "id": job_id,
                "source": entry.get("source", ""),
                "composition": label,
                "parts": copy.deepcopy(parts),
                "color_name": color_name,
                "color": copy.deepcopy(color),
                "path": str(root / label / f"{color_name}.png"),
                "status": "queued",
                "attempts": 0,
                "attempt_history": [],
                "error": "",
            })
    return jobs


def valid_png(path: str | Path) -> bool:
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return image.width > 0 and image.height > 0 and image.format == "PNG"
    except Exception:
        return False


class BatchState:
    def __init__(self, root: Path, jobs: list[dict]):
        self.root = root
        self.path = root / "batch-progress.json"
        self.jobs = jobs

    @classmethod
    def open(cls, output_dir: str | Path, compositions: list[dict], colors: list[dict]) -> "BatchState":
        root = Path(output_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        planned = build_batch_jobs(compositions, colors, root)
        progress = root / "batch-progress.json"
        previous: dict[str, dict] = {}
        if progress.is_file():
            payload = json.loads(progress.read_text("utf-8"))
            previous = {job.get("id"): job for job in payload.get("jobs", []) if job.get("id")}
        for job in planned:
            old = previous.get(job["id"], {})
            job["attempts"] = max(0, int(old.get("attempts", 0)))
            job["attempt_history"] = list(old.get("attempt_history", []))
            job["error"] = str(old.get("error", ""))
            if valid_png(job["path"]):
                job.update(status="completed", error="")
            elif old.get("status") == "failed" and job["attempts"] >= MAX_ATTEMPTS:
                job["status"] = "failed"
            else:
                job["status"] = "queued"
        state = cls(root, planned)
        state.save()
        return state

    def save(self) -> None:
        payload = {
            "version": 1,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "jobs": self.jobs,
        }
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        os.replace(temporary, self.path)

    def write_failure_report(self) -> None:
        failures = [
            {key: job.get(key) for key in ["source", "composition", "color_name", "attempts", "error"]}
            for job in self.jobs if job["status"] == "failed"
        ]
        (self.root / "failed-tasks.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), "utf-8")

    def retry_failed(self) -> int:
        count = 0
        for job in self.jobs:
            if job["status"] != "failed":
                continue
            job.update(status="queued", attempts=0, attempt_history=[], error="")
            count += 1
        if count:
            self.save()
        return count


class WorkerSignals(QObject):
    done = Signal(object)
    error = Signal(object)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.signals.done.emit(self.fn())
        except Exception as exc:
            self.signals.error.emit(exc)
        finally:
            self.signals.finished.emit()


class BatchGeneratorWindow(QMainWindow):
    def __init__(self, workbook: str = "", output: str = ""):
        super().__init__()
        self.store = Store(default_data_dir())
        self.settings = self.store.load_settings()
        catalog = json.loads(asset("catalog.json").read_text("utf-8"))
        self.colors = catalog["colors"]
        self.state: BatchState | None = None
        self.running = False
        self.active_ids: set[str] = set()
        self.workers: dict[str, Worker] = {}
        self.retry_due: dict[str, float] = {}
        self.next_dispatch_at = 0.0
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self.setWindowTitle(f"Fabric Label Batch Generator v{VERSION} · 成分颜色批量生成")
        self.resize(920, 680)

        page = QWidget()
        self.setCentralWidget(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        title = QLabel("全部成分 × 全部颜色")
        title.setObjectName("title")
        layout.addWidget(title)
        layout.addWidget(QLabel("每种成分建立一个中文文件夹，文件夹内保存 12 张中文颜色图片。支持断点续跑。"))

        form = QFormLayout()
        workbook_row = QHBoxLayout()
        self.workbook_path = QLineEdit(workbook)
        workbook_row.addWidget(self.workbook_path, 1)
        choose_workbook = QPushButton("选择 Excel")
        choose_workbook.clicked.connect(self.choose_workbook)
        workbook_row.addWidget(choose_workbook)
        form.addRow("成分文档", workbook_row)
        output_row = QHBoxLayout()
        self.output_path = QLineEdit(output)
        output_row.addWidget(self.output_path, 1)
        choose_output = QPushButton("选择输出目录")
        choose_output.clicked.connect(self.choose_output)
        output_row.addWidget(choose_output)
        form.addRow("图片目录", output_row)
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 4)
        self.concurrency.setValue(max(1, min(4, int(self.settings.get("concurrency", 2)))))
        form.addRow("并发任务", self.concurrency)
        layout.addLayout(form)

        actions = QHBoxLayout()
        self.start_button = QPushButton("开始 / 继续生成")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start_batch)
        actions.addWidget(self.start_button)
        pause = QPushButton("暂停")
        pause.clicked.connect(self.pause_batch)
        actions.addWidget(pause)
        retry_failed = QPushButton("重试全部失败")
        retry_failed.clicked.connect(self.retry_failed_jobs)
        actions.addWidget(retry_failed)
        open_output = QPushButton("打开图片目录")
        open_output.clicked.connect(self.open_output)
        actions.addWidget(open_output)
        actions.addStretch()
        layout.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1428)
        layout.addWidget(self.progress)
        self.stats = QLabel("等待开始")
        self.stats.setObjectName("section")
        layout.addWidget(self.stats)
        self.detail = QLabel("请求启动至少间隔 10 秒；临时错误最多尝试 3 次。关闭后重新打开可继续。")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.dispatch)
        self.timer.start(350)

    def choose_workbook(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择成分文档", "", "Excel (*.xlsx *.xlsm)")
        if path:
            self.workbook_path.setText(path)

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择图片输出目录")
        if path:
            self.output_path.setText(path)

    def append_log(self, message: str):
        self.log.appendPlainText(time.strftime("%H:%M:%S") + "  " + message)

    def prepare(self):
        workbook = Path(self.workbook_path.text().strip())
        output_text = self.output_path.text().strip()
        if not workbook.is_file():
            raise ValueError("请选择有效的 Excel 成分文档。")
        if not output_text:
            raise ValueError("请选择图片输出目录。")
        output = Path(output_text)
        if not self.settings.get("api_key") or not self.settings.get("image_model"):
            raise ValueError("请先在 Fabric Label Studio 的 API & models 页面保存 API 密钥和图像模型。")
        imported = import_column_c(workbook)
        if not imported["compositions"]:
            raise ValueError("文档 C 列没有可生成的有效成分。")
        self.state = BatchState.open(output, imported["compositions"], self.colors)
        (output / "import-errors.json").write_text(
            json.dumps(imported.get("errors", []), ensure_ascii=False, indent=2), "utf-8"
        )
        self.progress.setRange(0, len(self.state.jobs))
        self.append_log(
            f"已读取 {len(imported['compositions'])} 条有效成分 × {len(self.colors)} 种颜色 = {len(self.state.jobs)} 张。"
        )
        self.update_stats()

    def start_batch(self):
        try:
            if self.state is None:
                self.prepare()
            if not any(job["status"] in {"queued", "retrying"} for job in self.state.jobs):
                self.update_stats()
                return
            self.running = True
            self.start_button.setEnabled(False)
            self.append_log("批量生成已开始。")
            self.dispatch()
        except Exception as exc:
            QMessageBox.critical(self, "无法开始", str(exc))

    def pause_batch(self):
        self.running = False
        self.start_button.setEnabled(True)
        self.append_log("已暂停；正在执行的请求会完成。")
        self.update_stats()

    def retry_failed_jobs(self):
        if self.state is None:
            try:
                self.prepare()
            except Exception as exc:
                QMessageBox.critical(self, "无法读取任务", str(exc))
                return
        count = self.state.retry_failed()
        if not count:
            self.append_log("当前没有失败任务。")
            return
        self.append_log(f"已将 {count} 个失败任务重新排队，每个任务重新获得 3 次尝试机会。")
        self.update_stats()

    def open_output(self):
        path = Path(self.output_path.text().strip())
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def dispatch(self):
        if not self.running or self.state is None:
            return
        pending = [job for job in self.state.jobs if job["status"] in {"queued", "retrying"}]
        if not pending and not self.active_ids:
            self.running = False
            self.start_button.setEnabled(True)
            self.state.write_failure_report()
            self.append_log("本轮处理结束。请查看完成数量和失败报告。")
            self.update_stats()
            return
        now = monotonic()
        limit = self.concurrency.value()
        if len(self.active_ids) >= limit or now < self.next_dispatch_at:
            return
        job = next((item for item in pending if item["status"] == "retrying" and now >= self.retry_due.get(item["id"], 0)), None)
        if job is None:
            job = next((item for item in pending if item["status"] == "queued"), None)
        if job is not None:
            self.next_dispatch_at = now + REQUEST_INTERVAL_SECONDS
            self.start_job(job)

    def start_job(self, job: dict):
        if self.state is None:
            return
        if job["attempts"] >= MAX_ATTEMPTS:
            job["status"] = "failed"
            self.state.save()
            self.update_stats()
            return
        output = Path(job["path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        settings = copy.deepcopy(self.settings)
        reference = settings.get("reference_path") or str(asset("original-reference.png"))
        fabric = asset(job["color"].get("reference", ""))
        fabric_path = str(fabric) if fabric.is_file() else ""
        job["status"] = "running"
        job["attempts"] += 1
        attempt = {
            "attempt": job["attempts"],
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "running",
            "error": "",
        }
        job["attempt_history"].append(attempt)
        self.active_ids.add(job["id"])
        self.retry_due.pop(job["id"], None)
        self.state.save()
        self.update_stats()
        self.append_log(f"{job['composition']} / {job['color_name']}：第 {job['attempts']}/3 次。")

        def done(result):
            attempt.update(status="succeeded", finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
            job.update(status="completed", error="", path=result["path"])
            self.active_ids.discard(job["id"])
            self.state.save()
            self.update_stats()

        def failed(error):
            message = str(error)
            attempt.update(status="failed", error=message, finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
            job.update(status="failed", error=message)
            self.active_ids.discard(job["id"])
            retryable = getattr(error, "retryable", False)
            if retryable and job["attempts"] < MAX_ATTEMPTS:
                job["status"] = "retrying"
                self.retry_due[job["id"]] = monotonic() + REQUEST_INTERVAL_SECONDS
                self.append_log(f"{job['composition']} / {job['color_name']}：临时失败，10 秒后重试。")
            elif not retryable:
                self.running = False
                self.start_button.setEnabled(True)
                self.append_log("队列因配置或非临时错误暂停：" + message)
            else:
                self.append_log(f"{job['composition']} / {job['color_name']}：3 次均失败。")
            self.state.save()
            self.update_stats()

        worker = Worker(lambda: generate_image(settings, job["parts"], job["color"], reference, str(output), "", fabric_path))
        token = job["id"] + ":" + str(job["attempts"])
        self.workers[token] = worker
        worker.signals.done.connect(done)
        worker.signals.error.connect(failed)
        worker.signals.finished.connect(lambda: self.workers.pop(token, None))
        self.pool.start(worker)

    def update_stats(self):
        if self.state is None:
            return
        counts = {status: sum(job["status"] == status for job in self.state.jobs)
                  for status in ["queued", "running", "retrying", "completed", "failed"]}
        self.progress.setValue(counts["completed"])
        self.stats.setText(
            f"完成 {counts['completed']} / {len(self.state.jobs)}　运行 {counts['running']}　"
            f"排队 {counts['queued']}　等待重试 {counts['retrying']}　失败 {counts['failed']}"
        )

    def closeEvent(self, event):
        if self.workers:
            self.pause_batch()
            QMessageBox.information(self, "请稍候", "已暂停新任务。请等待正在执行的请求完成后再关闭。")
            event.ignore()
            return
        if self.state:
            self.state.save()
        event.accept()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--workbook", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--autostart", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])
    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("Fabric Label Batch Generator")
    app.setOrganizationName("FabricLabelStudio")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Segoe UI", 10))
    window = BatchGeneratorWindow(args.workbook, args.output)
    window.show()
    if args.autostart:
        QTimer.singleShot(300, window.start_batch)
    if args.smoke_test:
        QTimer.singleShot(1200, app.quit)
    return app.exec()
