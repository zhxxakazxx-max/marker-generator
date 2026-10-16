from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

from PySide6.QtCore import Qt, QObject, QRunnable, QThreadPool, QTimer, Signal, QSize, QUrl
from PySide6.QtGui import QPixmap, QIcon, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton, QToolButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QStackedWidget, QScrollArea,
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QListWidget, QListWidgetItem,
    QAbstractItemView, QFileDialog, QMessageBox, QInputDialog, QSplitter, QTabWidget,
)

from .domain import COLORS, FIBERS, parse_composition, validate_composition, composition_text, import_column_c
from .storage import Store, default_data_dir
from .providers import generate_image, list_models, normalize_composition
from .theme import STYLE


def asset(name):
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent)) / 'assets' / name


def label(text, kind=None):
    w = QLabel(text)
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    if kind:
        w.setObjectName(kind)
    return w


def button(text, callback, primary=False):
    w = QPushButton(text)
    if primary:
        w.setObjectName('primary')
    w.clicked.connect(callback)
    return w


def card(title=None):
    w = QFrame()
    w.setObjectName('card')
    box = QVBoxLayout(w)
    box.setContentsMargins(20, 18, 20, 18)
    box.setSpacing(12)
    if title:
        box.addWidget(label(title, 'section'))
    return w, box


class Photo(QLabel):
    def __init__(self):
        super().__init__()
        self.setObjectName('photo')
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(240, 240)
        self.original = QPixmap()

    def load(self, path=''):
        self.original = QPixmap(str(path)) if path else QPixmap()
        self.refresh()

    def refresh(self):
        if self.original.isNull():
            self.clear()
            self.setText('Select a generated image to review\n选择任务以预览')
        else:
            self.setPixmap(self.original.scaled(self.size() - QSize(16, 16), Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()


class WorkerSignals(QObject):
    done = Signal(object)
    error = Signal(str)
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
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self, data_dir=None):
        super().__init__()
        self.store = Store(Path(data_dir) if data_dir else default_data_dir())
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings = self.store.load_settings()
        self.jobs = self.store.load_jobs()
        for job in self.jobs:
            if job['status'] == 'running':
                job['status'] = 'interrupted'
                job['error'] = 'App closed during generation. Regenerate when ready.'
        self.running = False
        self.active_ids = set()
        self.workers = {}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(6)
        catalog_path = asset('catalog.json')
        self.catalog = json.loads(catalog_path.read_text('utf-8')) if catalog_path.exists() else {'compositions': [], 'errors': []}
        self.compositions = self.settings.get('compositions') or self.catalog.get('compositions', [])
        self.composition_errors = self.settings.get('composition_errors', self.catalog.get('errors', []))
        self.colors = self.catalog.get('colors') or COLORS
        self.custom_fabric = ''
        self.setWindowTitle('Fabric Label Studio · 成分唛工作台')
        self.resize(1450, 940)
        self.setMinimumSize(1120, 760)
        icon = asset('app.ico')
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        root = QWidget()
        self.setCentralWidget(root)
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(208)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(20, 28, 20, 24)
        sb.addWidget(label('F / L', 'brand'))
        sb.addWidget(label('FABRIC LABEL\nSTUDIO', 'brand'))
        sb.addWidget(label('成分唛工作台'))
        sb.addSpacing(32)
        self.nav = []
        for i, title in enumerate(['01   Create / 创建', '02   Review / 审核', '03   API & models']):
            b = button(title, lambda checked=False, idx=i: self.navigate(idx))
            b.setObjectName('nav')
            b.setCheckable(True)
            sb.addWidget(b)
            self.nav.append(b)
        sb.addStretch()
        sb.addWidget(label('ONE LABEL\nEVERY SIZE'))
        sb.addSpacing(12)
        sb.addWidget(label('Size-free composition labels\n成分 · 面料 · 缝线'))
        sb.addSpacing(24)
        sb.addWidget(label('Windows desktop  /  v1.0'))
        row.addWidget(sidebar)
        self.pages = QStackedWidget()
        row.addWidget(self.pages, 1)
        self.build_create()
        self.build_review()
        self.build_settings()
        self.navigate(0)
        self.populate_library()
        self.add_fiber('Cotton', 100)
        self.refresh_jobs()
        self.statusBar().showMessage('Ready. Select a composition and fabric colors. / 就绪')
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.dispatch)
        self.timer.start(350)

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        for i, b in enumerate(self.nav):
            b.setChecked(i == index)

    def page(self, title, subtitle):
        page = QWidget()
        page.setObjectName('page')
        box = QVBoxLayout(page)
        box.setContentsMargins(28, 24, 28, 22)
        box.setSpacing(16)
        box.addWidget(label('FABRIC LABEL STUDIO', 'eyebrow'))
        box.addWidget(label(title, 'title'))
        box.addWidget(label(subtitle, 'subtitle'))
        self.pages.addWidget(page)
        return box

    def build_create(self):
        box = self.page('Make your next label.', '选择成分与面料颜色。文字参考首图，统一去除尺码。')
        splitter = QSplitter()
        box.addWidget(splitter, 1)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left = QWidget()
        left.setObjectName('page')
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 5, 0)
        left_box.setSpacing(16)
        left_scroll.setWidget(left)
        splitter.addWidget(left_scroll)
        comp_card, c = card('01   Composition / 成分')
        left_box.addWidget(comp_card)
        self.tabs = QTabWidget()
        c.addWidget(self.tabs)
        library = QWidget()
        lib = QVBoxLayout(library)
        lib.setContentsMargins(0, 12, 0, 0)
        searchrow = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search Chinese or English / 搜索成分')
        self.search.textChanged.connect(self.filter_library)
        searchrow.addWidget(self.search, 1)
        searchrow.addWidget(button('Import Excel', self.import_excel))
        lib.addLayout(searchrow)
        self.library = QListWidget()
        self.library.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.library.setMinimumHeight(175)
        self.library.setMaximumHeight(220)
        self.library.itemSelectionChanged.connect(self.update_plan)
        lib.addWidget(self.library)
        selectrow = QHBoxLayout()
        selectrow.addWidget(button('Select visible', self.select_visible))
        selectrow.addWidget(button('Clear', self.library.clearSelection))
        selectrow.addWidget(button('Edit selected', self.edit_selected))
        lib.addLayout(selectrow)
        self.library_info = label('', 'muted')
        lib.addWidget(self.library_info)
        lib.addWidget(button('Rows needing correction / 待确认成分', self.show_composition_errors))
        self.tabs.addTab(library, 'Excel library / 成分库')
        manual = QWidget()
        man = QVBoxLayout(manual)
        man.setContentsMargins(0, 12, 0, 0)
        self.fiber_table = QTableWidget(0, 2)
        self.fiber_table.setHorizontalHeaderLabels(['FIBER / 成分', 'PERCENT / 占比'])
        self.fiber_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.fiber_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.fiber_table.verticalHeader().setVisible(False)
        self.fiber_table.setMinimumHeight(150)
        self.fiber_table.setMaximumHeight(200)
        man.addWidget(self.fiber_table)
        mrow = QHBoxLayout()
        mrow.addWidget(button('+ Add fiber', lambda: self.add_fiber('Polyester', 0)))
        mrow.addWidget(button('Remove row', self.remove_fiber))
        self.total = label('Total: 100%', 'muted')
        mrow.addWidget(self.total)
        man.addLayout(mrow)
        self.paste = QLineEdit()
        self.paste.setPlaceholderText('棉65%聚酯纤维35%  or  65% Cotton, 35% Polyester')
        man.addWidget(self.paste)
        prow = QHBoxLayout()
        prow.addWidget(button('Apply text', self.apply_text))
        prow.addWidget(button('AI interpret text', self.ai_parse))
        man.addLayout(prow)
        self.tabs.addTab(manual, 'Custom / 自定义')
        self.tabs.currentChanged.connect(self.update_plan)
        color_card, col = card('02   Fabric colors / 面料颜色')
        left_box.addWidget(color_card)
        col.addWidget(label('Choose several colors to create a batch. / 可多选颜色', 'muted'))
        grid = QGridLayout()
        grid.setSpacing(8)
        self.swatches = []
        for i, color in enumerate(self.colors):
            b = QToolButton()
            b.setObjectName('swatch')
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setText(color['name'])
            b.setMinimumSize(88, 94)
            b.setIconSize(QSize(68, 52))
            ref = asset(color.get('reference', ''))
            if ref.is_file():
                b.setIcon(QIcon(str(ref)))
            else:
                pm = QPixmap(68, 52)
                pm.fill(QColor(color['hex']))
                b.setIcon(QIcon(pm))
            b.setToolTip(color['name'] + ' ' + color['hex'])
            b.toggled.connect(self.update_plan)
            grid.addWidget(b, i // 4, i % 4)
            self.swatches.append(b)
        col.addLayout(grid)
        crow = QHBoxLayout()
        crow.addWidget(button('All 12 colors', lambda: self.set_colors(True)))
        crow.addWidget(button('Clear colors', lambda: self.set_colors(False)))
        col.addLayout(crow)
        self.fabric_info = label('Workbook fabric references are included.', 'muted')
        col.addWidget(self.fabric_info)
        frow = QHBoxLayout()
        frow.addWidget(button('Use custom fabric photo', self.choose_fabric))
        frow.addWidget(button('Reset', self.reset_fabric))
        col.addLayout(frow)
        left_box.addStretch()
        right, preview = card('Reference & label text / 版式参考')
        splitter.addWidget(right)
        self.example_photo = Photo()
        self.example_photo.setMinimumHeight(300)
        self.example_photo.load(asset('size-free-example.png'))
        preview.addWidget(self.example_photo, 1)
        preview.addWidget(label('SIZE-FREE EXAMPLE · 100% COTTON', 'eyebrow'))
        preview.addWidget(label('Example photo. Your selected composition appears in the generated result.', 'muted'))
        self.plan_text = label('100% Cotton\n\nMade in China', 'section')
        self.plan_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plan_text.setMinimumHeight(95)
        preview.addWidget(self.plan_text)
        self.plan_count = label('Choose a composition to begin.', 'muted')
        preview.addWidget(self.plan_count)
        preview.addWidget(button('Add to generation queue / 加入队列', self.enqueue_selection, True))
        preview.addWidget(label('The label stays cream with black text. Only the attached fabric changes color. No size is printed.', 'muted'))
        splitter.setSizes([620, 440])
        self.swatches[0].setChecked(True)

    def populate_library(self):
        self.library.clear()
        for entry in self.compositions:
            try:
                entry['parts'] = validate_composition(entry.get('parts') or parse_composition(entry['label']))
            except ValueError:
                continue
            item = QListWidgetItem(entry['label'])
            item.setToolTip(entry.get('source', '') + '\n' + composition_text(entry['parts']))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.library.addItem(item)
        self.library_info.setText(f'{self.library.count()} compositions from column C. {len(self.composition_errors)} rows need correction.')
        for i in range(self.library.count()):
            if self.library.item(i).data(Qt.ItemDataRole.UserRole)['parts'] == [{'name': 'Cotton', 'percent': 100}]:
                self.library.item(i).setSelected(True)
                self.library.scrollToItem(self.library.item(i))
                break
        self.filter_library()

    def filter_library(self):
        q = self.search.text().casefold().strip()
        for i in range(self.library.count()):
            item = self.library.item(i)
            entry = item.data(Qt.ItemDataRole.UserRole)
            item.setHidden(q not in (entry['label'] + ' ' + composition_text(entry['parts'])).casefold())

    def select_visible(self):
        for i in range(self.library.count()):
            item = self.library.item(i)
            if not item.isHidden():
                item.setSelected(True)

    def edit_selected(self):
        selected = self.library.selectedItems()
        if not selected:
            return self.notice('Select a composition first.')
        self.set_parts(selected[0].data(Qt.ItemDataRole.UserRole)['parts'])
        self.tabs.setCurrentIndex(1)

    def add_fiber(self, name='Cotton', percent=0):
        r = self.fiber_table.rowCount()
        self.fiber_table.insertRow(r)
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(FIBERS)
        combo.setCurrentText(name)
        combo.currentTextChanged.connect(self.update_plan)
        spin = QDoubleSpinBox()
        spin.setRange(0, 100)
        spin.setDecimals(2)
        spin.setSuffix('%')
        spin.setValue(float(percent))
        spin.valueChanged.connect(self.update_plan)
        self.fiber_table.setCellWidget(r, 0, combo)
        self.fiber_table.setCellWidget(r, 1, spin)
        self.fiber_table.setRowHeight(r, 44)
        self.update_plan()

    def remove_fiber(self):
        r = self.fiber_table.currentRow()
        if r < 0:
            r = self.fiber_table.rowCount() - 1
        if r >= 0:
            self.fiber_table.removeRow(r)
        self.update_plan()

    def set_parts(self, parts):
        self.fiber_table.setRowCount(0)
        for part in parts:
            self.add_fiber(part['name'], part['percent'])

    def manual_parts(self):
        return [{'name': self.fiber_table.cellWidget(r, 0).currentText(),
                 'percent': self.fiber_table.cellWidget(r, 1).value()} for r in range(self.fiber_table.rowCount())]

    def selected_compositions(self):
        if self.tabs.currentIndex() == 1:
            parts = validate_composition(self.manual_parts())
            return [{'parts': parts, 'label': composition_text(parts).replace('\n', ', '), 'source': 'Custom'}]
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.library.selectedItems()]

    def update_plan(self, *_):
        if not hasattr(self, 'plan_count'):
            return
        total = sum(p['percent'] for p in self.manual_parts())
        self.total.setText(f'Total: {total:g}%')
        try:
            entries = self.selected_compositions()
            ncolors = sum(b.isChecked() for b in self.swatches)
            self.plan_count.setText(f'{len(entries)} compositions × {ncolors} colors = {len(entries) * ncolors} images')
            self.plan_text.setText((composition_text(entries[0]['parts']) + '\n\nMade in China') if entries else 'Select a composition / 选择成分')
        except ValueError as exc:
            self.plan_count.setText(str(exc))
            self.plan_text.setText('Composition must total 100%')

    def apply_text(self):
        try:
            self.set_parts(parse_composition(self.paste.text()))
        except ValueError as exc:
            self.notice(str(exc))

    def ai_parse(self):
        if not self.settings.get('api_key'):
            self.navigate(2)
            return self.notice('Save your API key and text model first.')
        raw = self.paste.text().strip()
        if not raw:
            return self.notice('Paste composition text first.')
        self.statusBar().showMessage('Interpreting composition with the selected text model…')
        def done(result):
            try:
                parts = parse_composition(result)
                self.set_parts(parts)
                self.statusBar().showMessage('AI interpretation loaded. Review fibers and percentages before adding to queue.')
            except ValueError as exc:
                self.notice(f'AI response needs correction: {exc}\n\n{result}')
        self.launch(lambda: normalize_composition(copy.deepcopy(self.settings), raw), done, self.notice)

    def import_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import compositions from column C', '', 'Excel (*.xlsx *.xlsm)')
        if not path:
            return
        self.statusBar().showMessage('Reading Excel column C…')
        def done(result):
            if len(result['sheets']) > 1:
                sheet, ok = QInputDialog.getItem(self, 'Worksheet', 'Choose the sheet with composition column C:', result['sheets'], 0, False)
                if ok:
                    self.launch(lambda: import_column_c(path, sheet), self.accept_import, self.notice)
            else:
                self.accept_import(result)
        self.launch(lambda: import_column_c(path), done, self.notice)

    def accept_import(self, result):
        if not result['compositions']:
            return self.notice('No valid compositions found in column C.\n' + self.import_errors(result))
        self.compositions = result['compositions']
        self.composition_errors = result.get('errors', [])
        self.settings['compositions'] = self.compositions
        self.settings['composition_errors'] = self.composition_errors
        self.store.save_settings(self.settings)
        self.populate_library()
        self.tabs.setCurrentIndex(0)
        self.notice(f"Imported {len(self.compositions)} compositions.\n" + self.import_errors(result))

    def show_composition_errors(self):
        self.notice(self.import_errors({'errors': self.composition_errors}) + '\nUse Custom to enter the confirmed composition and percentages.')

    def import_errors(self, result):
        errors = result.get('errors', [])
        if not errors:
            return 'All composition rows validated.'
        report = self.data_dir / 'last-import-errors.json'
        report.write_text(json.dumps(errors, ensure_ascii=False, indent=2), 'utf-8')
        detail = '\n'.join(f"Row {e['row']}: {e['value']} — {e['error']}" for e in errors[:8])
        return f'{len(errors)} rows need correction and were skipped.\n{detail}\nFull report: {report}'

    def set_colors(self, selected):
        for b in self.swatches:
            b.setChecked(selected)

    def choose_fabric(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Custom fabric reference', '', 'Images (*.png *.jpg *.jpeg *.webp)')
        if path:
            try:
                self.custom_fabric = self.copy_reference(path)
                self.fabric_info.setText('Custom texture: ' + Path(path).name + '. Selected colors still apply.')
            except Exception as exc:
                self.notice(str(exc))

    def reset_fabric(self):
        self.custom_fabric = ''
        self.fabric_info.setText('Workbook fabric references are included.')

    def copy_reference(self, path):
        from PIL import Image
        if Path(path).stat().st_size > 20 * 1024 * 1024:
            raise ValueError('Reference image must be smaller than 20 MB.')
        with Image.open(path) as im:
            im.verify()
        folder = self.data_dir / 'references'
        folder.mkdir(exist_ok=True)
        target = folder / (uuid.uuid4().hex + Path(path).suffix.lower())
        shutil.copy2(path, target)
        return str(target)

    def enqueue_selection(self):
        try:
            entries = self.selected_compositions()
            colors = [c for c, b in zip(self.colors, self.swatches) if b.isChecked()]
            if not entries or not colors:
                return self.notice('Choose at least one composition and one fabric color.')
            for entry in entries:
                for color in colors:
                    self.jobs.append(self.new_job(entry['parts'], color, entry.get('source', 'Custom'), self.custom_fabric))
            self.persist_jobs()
            self.navigate(1)
            self.queue.setCurrentCell(len(self.jobs) - len(entries) * len(colors), 0)
            self.statusBar().showMessage(f'Added {len(entries) * len(colors)} jobs. Press Start queue to generate with your API.')
        except ValueError as exc:
            self.notice(str(exc))

    def new_job(self, parts, color, source='', custom_fabric='', feedback='', parent=''):
        return {'id': uuid.uuid4().hex, 'parts': copy.deepcopy(parts), 'color': copy.deepcopy(color),
                'source': source, 'custom_fabric': custom_fabric, 'feedback': feedback, 'parent': parent,
                'status': 'queued', 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'path': '', 'error': ''}

    def build_review(self):
        box = self.page('Review every detail.', '核对成分、文字、面料与缝线。满意后批准，不满意可重新生成。')
        actions = QHBoxLayout()
        self.queue_stats = label('0 queued', 'section')
        actions.addWidget(self.queue_stats, 1)
        self.start_btn = button('Start queue / 开始', self.start_queue, True)
        actions.addWidget(self.start_btn)
        actions.addWidget(button('Pause', self.pause_queue))
        actions.addWidget(button('Cancel queued', self.cancel_queued))
        actions.addWidget(button('Export approved', self.export_approved))
        box.addLayout(actions)
        split = QSplitter()
        box.addWidget(split, 1)
        queue_card, q = card('Generation queue / 任务列表')
        split.addWidget(queue_card)
        self.queue = QTableWidget(0, 3)
        self.queue.setHorizontalHeaderLabels(['COMPOSITION', 'FABRIC', 'STATUS'])
        self.queue.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.queue.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.queue.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.queue.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.queue.verticalHeader().setVisible(False)
        self.queue.itemSelectionChanged.connect(self.show_job)
        q.addWidget(self.queue, 1)
        q.addWidget(label('Each color is a separate job. You can keep creating while images generate. Running requests finish when paused.', 'muted'))
        preview_card, p = card('Image review / 图片审核')
        split.addWidget(preview_card)
        self.result_photo = Photo()
        p.addWidget(self.result_photo, 1)
        self.result_detail = label('No generated image selected.', 'muted')
        self.result_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        p.addWidget(self.result_detail)
        self.feedback = QLineEdit()
        self.feedback.setPlaceholderText('Regeneration notes / 修改意见，例如：缝线更清晰')
        p.addWidget(self.feedback)
        ar = QHBoxLayout()
        self.approve_btn = button('Approve / 批准', self.approve_job, True)
        self.regen_btn = button('Regenerate / 重生成', self.regenerate_job)
        ar.addWidget(self.approve_btn)
        ar.addWidget(self.regen_btn)
        p.addLayout(ar)
        self.full_btn = button('Open full-resolution image', self.open_full)
        p.addWidget(self.full_btn)
        p.addWidget(label('Compare the printed text with the expected text above before approval.', 'muted'))
        split.setSizes([610, 450])

    def refresh_jobs(self):
        selected = self.queue.currentRow()
        self.queue.blockSignals(True)
        self.queue.setRowCount(len(self.jobs))
        for row, job in enumerate(self.jobs):
            vals = [composition_text(job['parts']).replace('\n', ' / '), job['color']['name'], job['status'].capitalize()]
            for col, value in enumerate(vals):
                item = QTableWidgetItem(value)
                item.setToolTip(value + ('\n' + job.get('error', '') if col == 2 else ''))
                if col == 2:
                    item.setForeground(QColor({'approved': '#36703a', 'failed': '#aa422f', 'running': '#337aa0', 'review': '#967029'}.get(job['status'], '#718171')))
                self.queue.setItem(row, col, item)
            self.queue.setRowHeight(row, 44)
        if 0 <= selected < len(self.jobs):
            self.queue.selectRow(selected)
        self.queue.blockSignals(False)
        counts = {s: sum(j['status'] == s for j in self.jobs) for s in ['queued', 'running', 'review', 'approved']}
        self.queue_stats.setText('  ·  '.join(f'{v} {k}' for k, v in counts.items()))
        self.start_btn.setEnabled(not self.running)
        self.show_job()

    def persist_jobs(self):
        self.store.save_jobs(self.jobs)
        self.refresh_jobs()

    def current_job(self):
        row = self.queue.currentRow()
        return self.jobs[row] if 0 <= row < len(self.jobs) else None

    def show_job(self):
        job = self.current_job()
        if not job:
            self.result_photo.load()
            self.result_detail.setText('Select a job to see its image and expected text.')
        else:
            path = job.get('path', '')
            self.result_photo.load(path if path and Path(path).exists() else '')
            text = 'Expected text / 应有文字:\n' + composition_text(job['parts']) + '\nMade in China\n\n'
            text += f"{job['color']['name']}  ·  {job['status'].capitalize()}"
            if job.get('model'):
                text += '\nModel: ' + job['model']
            if job.get('error'):
                text += '\n' + job['error']
            if path and not Path(path).exists():
                text += '\nImage file is missing. Regenerate this job.'
            self.result_detail.setText(text)
        has_image = bool(job and job.get('path') and Path(job['path']).is_file())
        self.approve_btn.setEnabled(has_image and job['status'] == 'review')
        self.regen_btn.setEnabled(bool(job and job['status'] not in ['queued', 'running']))
        self.full_btn.setEnabled(has_image)

    def start_queue(self):
        if not self.settings.get('api_key'):
            self.navigate(2)
            return self.notice('Paste and save your API key before starting the queue.')
        if not any(j['status'] == 'queued' for j in self.jobs):
            return self.notice('Add compositions to the queue first.')
        self.running = True
        self.refresh_jobs()
        self.dispatch()

    def pause_queue(self):
        self.running = False
        self.refresh_jobs()
        self.statusBar().showMessage('Queue paused. Active API requests will finish.')

    def cancel_queued(self):
        self.running = False
        for job in self.jobs:
            if job['status'] == 'queued':
                job['status'] = 'cancelled'
        self.persist_jobs()

    def dispatch(self):
        if not self.running:
            return
        limit = max(1, min(4, int(self.settings.get('concurrency', 2))))
        while len(self.active_ids) < limit:
            job = next((j for j in self.jobs if j['status'] == 'queued'), None)
            if job is None:
                if not self.active_ids:
                    self.running = False
                    self.refresh_jobs()
                return
            self.start_job(job)

    def start_job(self, job):
        settings = copy.deepcopy(self.settings)
        settings.pop('compositions', None)
        reference = settings.get('reference_path') or str(asset('original-reference.png'))
        fabric = job.get('custom_fabric') or str(asset(job['color'].get('reference', '')))
        if not Path(fabric).is_file():
            fabric = ''
        output_dir = self.data_dir / 'images'
        output_dir.mkdir(exist_ok=True)
        output = str(output_dir / (job['id'] + '.png'))
        job['status'] = 'running'
        job['model'] = settings.get('image_model', '')
        job['provider'] = settings.get('provider', '')
        self.active_ids.add(job['id'])
        self.persist_jobs()
        def done(result):
            job.update(path=result['path'], prompt=result.get('prompt', ''), model=result.get('model', job['model']), status='review', error='')
            self.active_ids.discard(job['id'])
            self.persist_jobs()
            self.statusBar().showMessage('Image ready for review / 图片已生成，待审核')
        def failed(error):
            job.update(status='failed', error=error)
            self.active_ids.discard(job['id'])
            self.running = False
            self.persist_jobs()
            self.statusBar().showMessage('A job failed. Queue paused; review the error before restarting.')
        self.launch(lambda: generate_image(settings, job['parts'], job['color'], reference, output,
                                           job.get('feedback', ''), fabric), done, failed)

    def approve_job(self):
        job = self.current_job()
        if job and job['status'] == 'review' and Path(job.get('path', '')).is_file():
            job['status'] = 'approved'
            job['approved_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
            self.persist_jobs()
            self.statusBar().showMessage('Approved. This image is included in Export approved.')

    def regenerate_job(self):
        job = self.current_job()
        if not job or job['status'] in ['queued', 'running']:
            return
        new = self.new_job(job['parts'], job['color'], job.get('source', ''), job.get('custom_fabric', ''),
                           self.feedback.text().strip(), job['id'])
        self.jobs.append(new)
        self.feedback.clear()
        self.persist_jobs()
        self.queue.setCurrentCell(len(self.jobs) - 1, 0)
        self.statusBar().showMessage('New version queued. Previous result retained. Press Start queue if paused.')

    def open_full(self):
        job = self.current_job()
        if job and job.get('path'):
            QDesktopServices.openUrl(QUrl.fromLocalFile(job['path']))

    def export_to(self, folder):
        approved = [j for j in self.jobs if j['status'] == 'approved']
        missing = [j for j in approved if not Path(j.get('path', '')).is_file()]
        if missing:
            raise ValueError(f'{len(missing)} approved image files are missing. Regenerate them before exporting.')
        if not approved:
            raise ValueError('Approve at least one generated image first.')
        target = Path(folder) / ('FabricLabels-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:4])
        target.mkdir(parents=True)
        manifest = []
        for job in approved:
            text = composition_text(job['parts']).replace('\n', '_')
            slug = re.sub(r'[^a-zA-Z0-9_. -]', '', text).strip()[:100]
            name = f"{slug}_{job['color']['id']}_{job['id'][:8]}.png"
            shutil.copy2(job['path'], target / name)
            manifest.append({'file': name, 'composition': job['parts'], 'fabric': job['color']['name'],
                             'expected_text': composition_text(job['parts']) + '\nMade in China',
                             'size_free': True, 'model': job.get('model', ''), 'approved_at': job.get('approved_at', '')})
        (target / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), 'utf-8')
        return target

    def export_approved(self):
        if not any(j['status'] == 'approved' for j in self.jobs):
            return self.notice('Approve at least one generated image first.')
        folder = QFileDialog.getExistingDirectory(self, 'Choose export folder')
        if folder:
            try:
                target = self.export_to(folder)
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
                self.statusBar().showMessage('Approved PNGs exported to ' + str(target))
            except Exception as exc:
                self.notice(str(exc))

    def build_settings(self):
        box = self.page('Your models. Your workspace.', '粘贴 API Key，选择图像模型和文字模型。密钥保存在此 Windows 用户账户下。')
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName('page')
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(content)
        box.addWidget(scroll, 1)
        conn, c = card('Connection / API 连接')
        body.addWidget(conn)
        form = QFormLayout()
        form.setVerticalSpacing(14)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.provider = QComboBox()
        for name, value in [('OpenAI', 'openai'), ('OpenAI-compatible / 兼容接口', 'compatible'), ('Google Gemini', 'gemini')]:
            self.provider.addItem(name, value)
        self.provider.setCurrentIndex(max(0, self.provider.findData(self.settings.get('provider', 'openai'))))
        form.addRow('Provider / 服务商', self.provider)
        self.base_url = QLineEdit(self.settings.get('base_url', 'https://api.openai.com/v1'))
        form.addRow('API base URL', self.base_url)
        self.key = QLineEdit(self.settings.get('api_key', ''))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('Paste your API key here / 在此粘贴密钥')
        form.addRow('API key', self.key)
        show = QCheckBox('Show key / 显示密钥')
        show.toggled.connect(lambda v: self.key.setEchoMode(QLineEdit.EchoMode.Normal if v else QLineEdit.EchoMode.Password))
        form.addRow('', show)
        c.addLayout(form)
        c.addWidget(label('API calls send the selected composition and reference photos to this provider. API usage is billed by your provider. Keys are encrypted with Windows DPAPI.', 'muted'))
        mod, m = card('Model selection / 模型选择')
        body.addWidget(mod)
        model_form = QFormLayout()
        self.image_model = QComboBox()
        self.image_model.setEditable(True)
        self.image_model.addItems(['gpt-image-2', 'gpt-image-2.5-flare', 'gpt-image-2.5-sunburst'])
        self.image_model.setCurrentText(self.settings.get('image_model', 'gpt-image-2'))
        model_form.addRow('Image model / 图像模型', self.image_model)
        self.text_model = QComboBox()
        self.text_model.setEditable(True)
        self.text_model.addItems(['gpt-4.1-mini', 'gpt-5-mini', 'gpt-5.6-luna'])
        self.text_model.setCurrentText(self.settings.get('text_model', 'gpt-4.1-mini'))
        model_form.addRow('Text model / 文字模型', self.text_model)
        self.quality = QComboBox()
        self.quality.addItems(['high', 'medium', 'low', 'auto'])
        self.quality.setCurrentText(self.settings.get('quality', 'high'))
        model_form.addRow('Image quality / 质量', self.quality)
        self.size = QComboBox()
        self.size.setEditable(True)
        self.size.addItems(['1024x1024', '1024x1536', '1536x1024', 'auto'])
        self.size.setCurrentText(self.settings.get('size', '1024x1024'))
        model_form.addRow('Image pixels / 图片像素', self.size)
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 4)
        self.concurrency.setValue(int(self.settings.get('concurrency', 2)))
        model_form.addRow('Parallel jobs / 并发任务', self.concurrency)
        m.addLayout(model_form)
        m.addWidget(label('Choose a discovered model or type its exact API model ID. Image models must support reference-image editing. Text models are used only when you click AI interpret text. Provider model lists can include models without image support.', 'muted'))
        self.model_status = label('Fetch the models available to your API account.', 'muted')
        m.addWidget(self.model_status)
        m.addWidget(button('Test connection & fetch models / 测试并获取模型', self.fetch_models))
        ref, r = card('Label reference / 标签参考图')
        body.addWidget(ref)
        self.reference_label = label(self.settings.get('reference_path') or 'Included: your original label photograph. Size removal is required in every prompt.', 'muted')
        r.addWidget(self.reference_label)
        rr = QHBoxLayout()
        rr.addWidget(button('Choose another label photo', self.choose_label_reference))
        rr.addWidget(button('Use original reference', self.reset_label_reference))
        r.addLayout(rr)
        self.pending_reference = self.settings.get('reference_path', '')
        save_row = QHBoxLayout()
        save_row.addWidget(button('Save settings / 保存设置', self.save_settings, True))
        save_row.addWidget(button('Open local data folder', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_dir)))))
        save_row.addStretch()
        body.addLayout(save_row)
        body.addStretch()
        self.provider.currentIndexChanged.connect(self.provider_changed)
        self.quality.setEnabled(self.provider.currentData() != 'gemini')
        self.size.setEnabled(self.provider.currentData() != 'gemini')

    def provider_changed(self):
        provider = self.provider.currentData()
        # Never carry a provider key over to a different endpoint automatically.
        self.key.clear()
        if provider == 'gemini':
            self.base_url.setText('https://generativelanguage.googleapis.com/v1beta')
            self.image_model.clear()
            self.image_model.addItems(['gemini-2.5-flash-image', 'gemini-3-pro-image-preview'])
            self.text_model.clear()
            self.text_model.addItems(['gemini-2.5-flash', 'gemini-2.5-pro'])
        else:
            self.base_url.setText('https://api.openai.com/v1' if provider == 'openai' else '')
            self.image_model.clear()
            self.image_model.addItems(['gpt-image-2', 'gpt-image-2.5-flare', 'gpt-image-2.5-sunburst'])
            self.text_model.clear()
            self.text_model.addItems(['gpt-4.1-mini', 'gpt-5-mini'])
        self.quality.setEnabled(provider != 'gemini')
        self.size.setEnabled(provider != 'gemini')
        self.model_status.setText('Enter the key for this provider, then fetch models. Gemini uses its model output defaults.')

    def collect_settings(self):
        s = copy.deepcopy(self.settings)
        s.update(provider=self.provider.currentData(), base_url=self.base_url.text().strip().rstrip('/'),
                 api_key=self.key.text().strip(), image_model=self.image_model.currentText().strip(),
                 text_model=self.text_model.currentText().strip(), quality=self.quality.currentText(),
                 size=self.size.currentText().strip(), concurrency=self.concurrency.value(),
                 reference_path=self.pending_reference)
        from urllib.parse import urlparse
        u = urlparse(s['base_url'])
        if not u.netloc or (u.scheme != 'https' and not (u.scheme == 'http' and u.hostname in ['localhost', '127.0.0.1', '::1'])):
            raise ValueError('Use an HTTPS API base URL (or HTTP for localhost).')
        if not s['image_model'] or not s['text_model']:
            raise ValueError('Enter both image and text model IDs.')
        return s

    def save_settings(self):
        try:
            settings = self.collect_settings()
            self.store.save_settings(settings)
            self.settings = settings
            self.statusBar().showMessage('Settings saved. New API jobs use these models. / 设置已保存')
        except Exception as exc:
            self.notice(str(exc))

    def fetch_models(self):
        try:
            settings = self.collect_settings()
            if not settings['api_key']:
                return self.notice('Paste your API key first.')
        except ValueError as exc:
            return self.notice(str(exc))
        self.model_status.setText('Connecting…')
        def done(models):
            for combo in [self.image_model, self.text_model]:
                current = combo.currentText()
                combo.clear()
                combo.addItems(models)
                combo.setCurrentText(current)
            self.model_status.setText(f'Connected. {len(models)} models found. Select supported image and text models, then save.')
        self.launch(lambda: list_models(settings), done, lambda error: self.model_status.setText(error))

    def choose_label_reference(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Label layout reference', '', 'Images (*.png *.jpg *.jpeg *.webp)')
        if path:
            try:
                self.pending_reference = self.copy_reference(path)
                self.reference_label.setText(Path(path).name + ' — press Save settings to apply.')
            except Exception as exc:
                self.notice(str(exc))

    def reset_label_reference(self):
        self.pending_reference = ''
        self.reference_label.setText('Original label photograph — press Save settings to apply.')

    def launch(self, fn, done, error):
        worker = Worker(fn)
        token = uuid.uuid4().hex
        self.workers[token] = worker
        worker.signals.done.connect(done)
        worker.signals.error.connect(error)
        worker.signals.finished.connect(lambda: self.workers.pop(token, None))
        self.pool.start(worker)

    def notice(self, text):
        QMessageBox.information(self, 'Fabric Label Studio', str(text))

    def closeEvent(self, event):
        if self.workers:
            self.running = False
            self.refresh_jobs()
            self.notice('Queue paused. Wait for active API requests to finish, then close the app. Your jobs are saved.')
            event.ignore()
            return
        self.store.save_jobs(self.jobs)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Fabric Label Studio')
    app.setOrganizationName('FabricLabelStudio')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    app.setFont(QFont('Segoe UI', 10))
    try:
        window = MainWindow()
    except Exception as exc:
        QMessageBox.critical(None, 'Fabric Label Studio', 'Unable to start: ' + str(exc))
        return 1
    window.show()
    if '--smoke-test' in sys.argv:
        # Packaged startup probe; no network or generation.
        QTimer.singleShot(1500, app.quit)
    return app.exec()
