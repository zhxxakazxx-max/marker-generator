STYLE = """
* { font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 13px; color: #253932; }
QMainWindow, QWidget#page { background: #f5f6f2; }
QFrame#sidebar { background: #173d32; border: none; }
QFrame#sidebar QLabel { color: #e9f0df; background: transparent; }
QLabel#brand { font-size: 22px; font-weight: 700; }
QLabel#eyebrow { color: #688574; font-size: 11px; font-weight: 700; }
QLabel#title { font-size: 29px; font-weight: 700; }
QLabel#subtitle, QLabel#muted { color: #6f7d73; }
QLabel#section { font-size: 16px; font-weight: 600; }
QFrame#card { background: white; border: 1px solid #dfe5dd; border-radius: 12px; }
QFrame#card QLabel { background: transparent; border: none; }
QLabel#stat { font-size: 22px; font-weight: 700; color: #235741; }
QPushButton { background: white; border: 1px solid #d7dfd5; border-radius: 7px; padding: 9px 15px; font-weight: 600; }
QPushButton:hover { background: #edf3e7; border-color: #9cb393; }
QPushButton:pressed { background: #d6e7c6; }
QPushButton:disabled { color: #a0aaa1; background: #eef1ec; border-color: #e1e6de; }
QPushButton#primary { background: #234f3d; color: white; border: 1px solid #234f3d; }
QPushButton#primary:hover { background: #35674e; }
QPushButton#primary:disabled { background: #a7b5aa; border-color: #a7b5aa; }
QPushButton#nav { text-align: left; background: transparent; color: #dce7da; border: none; padding: 13px 16px; }
QPushButton#nav:checked { background: #355b48; color: #e3f4bd; }
QPushButton#nav:hover { background: #294f3d; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #fff; border: 1px solid #d8e0d5; border-radius: 6px; padding: 7px; selection-background-color: #d0e6b5; selection-color: #173d32; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border: 1px solid #749463; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #d0e6b5; selection-color: #173d32; }
QTableWidget, QListWidget { background: white; border: 1px solid #dfe5db; border-radius: 6px; gridline-color: #eef1ea; outline: none; }
QTableWidget::item { padding: 7px; }
QListWidget::item { padding: 9px; border-bottom: 1px solid #f1f3ee; }
QTableWidget::item:selected, QListWidget::item:selected { background: #e4efda; color: #173d32; }
QHeaderView::section { background: #f0f3eb; color: #6b7b6d; padding: 9px; border: none; font-size: 11px; font-weight: 600; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 9px; }
QScrollBar::handle:vertical { background: #cbd5c7; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QToolButton#swatch { background: #f7f8f3; border: 2px solid #e8ede3; border-radius: 8px; padding: 5px; }
QToolButton#swatch:hover { border-color: #9ebc86; }
QToolButton#swatch:checked { background: #eaf3dd; border-color: #47764b; }
QCheckBox { spacing: 8px; }
QStatusBar { background: #edf1e8; color: #4f6855; }
QSplitter::handle { background: transparent; width: 14px; }
QLabel#photo { background: #e8ebe3; border-radius: 10px; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #e9eee2; padding: 10px 18px; border-radius: 4px; margin-right: 5px; }
QTabBar::tab:selected { background: #315b43; color: white; }
"""
