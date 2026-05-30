"""
Epson L805 DTF RIP Engine — Main GUI
Professional DTF RIP interface with drag-and-drop, preview toggle, Windows title bar
"""
import sys, os, threading
from pathlib import Path
from PIL import Image

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QSlider, QComboBox, QCheckBox,
    QGroupBox, QFileDialog, QProgressBar, QTextEdit, QSplitter,
    QFrame, QScrollArea, QStatusBar, QMessageBox, QTabWidget,
    QSpinBox, QSizePolicy, QToolBar, QMenuBar, QMenu, QListWidget,
    QListWidgetItem, QStackedWidget, QButtonGroup, QRadioButton,
    QAbstractItemView
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QMimeData, QUrl, QPoint
)
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QColor, QFont, QIcon, QAction,
    QDragEnterEvent, QDropEvent, QKeySequence, QPalette, QBrush,
    QLinearGradient, QFontDatabase
)

sys.path.insert(0, os.path.dirname(__file__))
from rip_engine import RIPCompiler, RIPConfig, PrintMode, DPIMode
from usb_comm import L805Printer, PrinterStatus


# ── Workers ────────────────────────────────────────────────────────────────

class RIPWorker(QThread):
    progress = pyqtSignal(int, str)
    log_msg  = pyqtSignal(str)
    finished = pyqtSignal(bytes)
    error    = pyqtSignal(str)

    def __init__(self, image, config):
        super().__init__()
        self.image  = image
        self.config = config

    def run(self):
        try:
            c = RIPCompiler(self.config,
                            progress_cb=lambda p,m: self.progress.emit(p,m),
                            log_cb=lambda m: self.log_msg.emit(m))
            self.finished.emit(c.compile(self.image))
        except Exception as e:
            self.error.emit(str(e))


class USBWorker(QThread):
    progress = pyqtSignal(int, str)
    log_msg  = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(self, printer, data):
        super().__init__()
        self.printer = printer
        self.data    = data

    def run(self):
        ok = self.printer.send_data(self.data,
                                    progress_cb=lambda p,m: self.progress.emit(p,m))
        self.finished.emit(ok)


# ── Style ──────────────────────────────────────────────────────────────────

STYLE = """
* { font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; }

QMainWindow { background: #2B2B2E; }

/* Menu Bar */
QMenuBar {
    background: #1E1E21;
    color: #CCCCCC;
    border-bottom: 1px solid #3A3A3E;
    padding: 2px 4px;
}
QMenuBar::item { padding: 4px 10px; border-radius: 4px; }
QMenuBar::item:selected { background: #3A3A40; color: #FFFFFF; }
QMenu {
    background: #252528; color: #CCCCCC;
    border: 1px solid #3A3A3E;
}
QMenu::item { padding: 6px 24px 6px 12px; }
QMenu::item:selected { background: #0A84FF; color: #FFFFFF; }
QMenu::separator { height: 1px; background: #3A3A3E; margin: 3px 0; }

/* Toolbar */
QToolBar {
    background: #252528;
    border-bottom: 1px solid #3A3A3E;
    spacing: 4px;
    padding: 4px 8px;
}
QToolBar QToolButton {
    background: transparent; border: none;
    color: #AAAAAA; padding: 5px 10px;
    border-radius: 5px; font-size: 11px;
}
QToolBar QToolButton:hover { background: #3A3A3E; color: #FFFFFF; }
QToolBar QToolButton:pressed { background: #0A84FF; color: #FFFFFF; }
QToolBar::separator { background: #3A3A3E; width: 1px; margin: 4px 6px; }

/* Panels */
QGroupBox {
    border: 1px solid #3A3A3E; border-radius: 6px;
    margin-top: 14px; padding: 10px 8px 8px 8px;
    background: #252528; color: #AAAAAA;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 10px; top: -1px;
    padding: 0 5px; font-size: 10px;
    letter-spacing: 1px; text-transform: uppercase;
    color: #666670; background: #2B2B2E;
}

/* Buttons */
QPushButton {
    background: #333338; color: #CCCCCC;
    border: 1px solid #454548; border-radius: 5px;
    padding: 6px 14px;
}
QPushButton:hover  { background: #3E3E44; border-color: #555560; }
QPushButton:pressed { background: #222226; }
QPushButton:disabled { color: #555558; border-color: #333336; }

QPushButton#btn_print {
    background: #0A84FF; color: #FFF; border: none;
    font-weight: 600; font-size: 13px;
    padding: 8px 22px; border-radius: 6px;
}
QPushButton#btn_print:hover   { background: #1A8EFF; }
QPushButton#btn_print:disabled { background: #0A3A6A; color: #336699; }

QPushButton#btn_rip {
    background: #1E4A1E; color: #5CC85C; border: 1px solid #2E6A2E;
    font-weight: 600; padding: 8px 22px; border-radius: 6px;
}
QPushButton#btn_rip:hover   { background: #245A24; }
QPushButton#btn_rip:disabled { color: #2E502E; border-color: #1E301E; }

/* Sliders */
QSlider::groove:horizontal {
    height: 4px; background: #3A3A3E; border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #0A84FF; border: none;
    width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
}
QSlider::sub-page:horizontal { background: #0A84FF; border-radius: 2px; }

/* Combos */
QComboBox {
    background: #333338; border: 1px solid #454548;
    border-radius: 5px; padding: 4px 8px; color: #CCCCCC;
}
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: #2A2A2E; border: 1px solid #454548;
    selection-background-color: #0A84FF; color: #CCCCCC;
}

/* SpinBox */
QSpinBox {
    background: #333338; border: 1px solid #454548;
    border-radius: 5px; padding: 4px 6px; color: #CCCCCC;
}

/* CheckBox */
QCheckBox { color: #AAAAAA; spacing: 6px; }
QCheckBox::indicator {
    width: 15px; height: 15px; border-radius: 3px;
    border: 1px solid #454548; background: #333338;
}
QCheckBox::indicator:checked { background: #0A84FF; border-color: #0A84FF; }

/* Progress */
QProgressBar {
    background: #333338; border: none; border-radius: 3px;
    height: 6px; text-align: center; color: transparent;
}
QProgressBar::chunk { background: #0A84FF; border-radius: 3px; }

/* Log */
QTextEdit {
    background: #0D0D0F; border: 1px solid #2A2A2E;
    border-radius: 5px; color: #00DD77;
    font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 11px;
    padding: 6px;
}

/* List */
QListWidget {
    background: #1E1E22; border: none;
    color: #CCCCCC; outline: none;
}
QListWidget::item {
    padding: 8px 10px; border-bottom: 1px solid #2A2A2E;
}
QListWidget::item:selected {
    background: #0A2A50; color: #FFFFFF; border-left: 3px solid #0A84FF;
}
QListWidget::item:hover { background: #2A2A30; }

/* Tabs */
QTabWidget::pane { border: 1px solid #3A3A3E; background: #252528; }
QTabBar::tab {
    background: #1E1E22; color: #777780;
    padding: 7px 14px; border: 1px solid #3A3A3E;
    border-bottom: none; border-radius: 5px 5px 0 0; margin-right: 2px;
}
QTabBar::tab:selected { background: #252528; color: #EEEEEE; }

/* Status Bar */
QStatusBar { background: #131315; color: #555560; font-size: 11px; border-top: 1px solid #2A2A2E; }

/* Splitter */
QSplitter::handle { background: #3A3A3E; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }

/* Radio */
QRadioButton { color: #AAAAAA; spacing: 6px; }
QRadioButton::indicator {
    width: 14px; height: 14px; border-radius: 7px;
    border: 1px solid #454548; background: #333338;
}
QRadioButton::indicator:checked { background: #0A84FF; border-color: #0A84FF; }

/* Label */
QLabel { color: #AAAAAA; }
QLabel#title_label { color: #EEEEEE; font-size: 13px; font-weight: 600; }
QLabel#sub_label   { color: #666670; font-size: 10px; }

/* Drop zone */
QLabel#drop_zone {
    color: #444450; border: 2px dashed #3A3A3E;
    border-radius: 10px; background: #1A1A1E;
}
QLabel#drop_zone[drag=true] {
    border-color: #0A84FF; background: #0A1A2A; color: #0A84FF;
}
"""


# ── Job Queue Item ─────────────────────────────────────────────────────────

class JobItem:
    def __init__(self, path: str, image: Image.Image):
        self.path   = path
        self.image  = image
        self.name   = Path(path).name
        self.size   = f"{image.width}×{image.height}"
        self.mode_str = "CMYK+W"
        self.rip_data = None
        self.status   = "待處理"


# ── Preview Widget (drag-and-drop capable) ─────────────────────────────────

class PreviewWidget(QLabel):
    image_dropped = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop_zone")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(400, 340)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAcceptDrops(True)
        self._pil_image = None
        self._view_mode  = "color"   # "color" | "white"
        self._show_empty()

    def _show_empty(self):
        self.setProperty("drag", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self.setText("拖曳影像至此處\n或點擊「開啟影像」\n\n支援 PNG · TIFF · JPG · BMP")
        self.setPixmap(QPixmap())

    def load_image(self, img: Image.Image):
        self._pil_image = img
        self._refresh()

    def set_view_mode(self, mode: str):
        self._view_mode = mode
        if self._pil_image:
            self._refresh()

    def _refresh(self):
        if not self._pil_image:
            return
        img = self._pil_image.convert("RGBA")
        w, h = img.size

        # Choose background
        if self._view_mode == "white":
            bg_color = (30, 30, 34, 255)       # dark bg — shows white ink
        elif self._view_mode == "black":
            bg_color = (0, 0, 0, 255)
        else:
            bg_color = None                     # checkerboard for transparency

        canvas = Image.new("RGBA", (w, h), (255,255,255,255))
        if bg_color is None:
            # Draw checkerboard
            tile = max(8, min(w, h) // 32)
            for y in range(0, h, tile):
                for x in range(0, w, tile):
                    c = (200,200,200,255) if (x//tile + y//tile)%2==0 else (160,160,160,255)
                    for py in range(y, min(y+tile, h)):
                        for px in range(x, min(x+tile, w)):
                            canvas.putpixel((px,py), c)
        else:
            canvas = Image.new("RGBA", (w, h), bg_color)

        # Composite image onto background
        canvas.paste(img, mask=img.split()[3])

        # If white-ink view: show alpha channel as white layer
        if self._view_mode == "white":
            import numpy as np
            arr = np.array(self._pil_image.convert("RGBA"))
            alpha = arr[:,:,3]
            white_layer = Image.fromarray(alpha, mode='L').convert("RGBA")
            white_arr = np.array(white_layer)
            white_arr[:,:,0] = 255
            white_arr[:,:,1] = 255
            white_arr[:,:,2] = 255
            canvas = Image.fromarray(white_arr)

        # Scale to widget size
        aw, ah = self.width() - 20, self.height() - 20
        if aw > 0 and ah > 0:
            canvas.thumbnail((aw, ah), Image.LANCZOS)

        data = canvas.tobytes("raw", "RGBA")
        qimg = QImage(data, canvas.width, canvas.height, QImage.Format.Format_RGBA8888)
        self.setPixmap(QPixmap.fromImage(qimg))
        self.setText("")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._pil_image:
            QTimer.singleShot(50, self._refresh)

    # ── Drag & Drop ──
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            urls = e.mimeData().urls()
            exts = {'.png','.jpg','.jpeg','.tif','.tiff','.bmp'}
            if any(Path(u.toLocalFile()).suffix.lower() in exts for u in urls):
                e.acceptProposedAction()
                self.setProperty("drag", True)
                self.style().unpolish(self)
                self.style().polish(self)
                self.setText("放開以載入影像")
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        if not self._pil_image:
            self._show_empty()
        else:
            self._refresh()

    def dropEvent(self, e: QDropEvent):
        self.setProperty("drag", False)
        self.style().unpolish(self)
        self.style().polish(self)
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            exts = {'.png','.jpg','.jpeg','.tif','.tiff','.bmp'}
            if Path(path).suffix.lower() in exts:
                self.image_dropped.emit(path)
                break

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._pil_image:
            self.image_dropped.emit("")  # trigger open dialog


# ── Channel Bar ────────────────────────────────────────────────────────────

class ChannelBar(QWidget):
    CHANNELS = [
        ('C',  '#00B4D8', 'Cyan',   'CH0'),
        ('M',  '#E040FB', 'Magenta','CH1'),
        ('Y',  '#FFD600', 'Yellow', 'CH2'),
        ('K',  '#607D8B', 'Black',  'CH3'),
        ('W1', '#B0C4CE', 'White 1','CH4'),
        ('W2', '#CFD8DC', 'White 2','CH5'),
    ]
    ACTIVE = {
        PrintMode.CMYK_WHITE: {0,1,2,3,4,5},
        PrintMode.WHITE_CMYK: {0,1,2,3,4,5},
        PrintMode.CMYK_ONLY:  {0,1,2,3},
        PrintMode.WHITE_ONLY: {4,5},
    }

    def __init__(self):
        super().__init__()
        self.mode = PrintMode.CMYK_WHITE
        self.cards = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0,0,0,0)
        lay.setSpacing(5)
        for i,(sym,col,name,ch) in enumerate(self.CHANNELS):
            f = QFrame()
            f.setFixedSize(64, 72)
            fl = QVBoxLayout(f)
            fl.setContentsMargins(3,6,3,4)
            fl.setSpacing(1)
            dot = QLabel()
            dot.setFixedSize(22,22)
            dot.setStyleSheet(f"background:{col};border-radius:11px;border:1.5px solid rgba(255,255,255,0.15)")
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lsym  = QLabel(sym);  lsym.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lname = QLabel(name); lname.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lch   = QLabel(ch);   lch.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lsym.setStyleSheet("font-weight:600;font-size:12px;color:#EEEEEE")
            lname.setStyleSheet("font-size:8px;color:#666670")
            lch.setStyleSheet("font-size:8px;color:#444450;font-family:monospace")
            fl.addWidget(dot, alignment=Qt.AlignmentFlag.AlignHCenter)
            fl.addWidget(lsym); fl.addWidget(lname); fl.addWidget(lch)
            lay.addWidget(f)
            self.cards.append((f, dot, lsym, col))
        self._update()

    def set_mode(self, mode):
        self.mode = mode
        self._update()

    def _update(self):
        active = self.ACTIVE.get(self.mode, set())
        for i,(f,dot,lsym,col) in enumerate(self.cards):
            if i in active:
                f.setStyleSheet("QFrame{background:#1E2A1E;border:1px solid #2E5030;border-radius:7px}")
                dot.setStyleSheet(f"background:{col};border-radius:11px;border:1.5px solid rgba(255,255,255,0.2)")
                lsym.setStyleSheet("font-weight:600;font-size:12px;color:#EEEEEE")
            else:
                f.setStyleSheet("QFrame{background:#1A1A1C;border:1px solid #222226;border-radius:7px}")
                dot.setStyleSheet(f"background:{col};border-radius:11px;opacity:0.2;border:1px solid #333")
                lsym.setStyleSheet("font-weight:600;font-size:12px;color:#333336")


# ── Main Window ────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("L805 DTF RIP Engine")
        self.setMinimumSize(1100, 700)
        self.resize(1280, 820)

        self._jobs: list[JobItem] = []
        self._current_job: JobItem | None = None
        self._rip_worker  = None
        self._usb_worker  = None
        self._rip_data    = None
        self.printer = L805Printer(
            log_cb=self._log,
            status_cb=self._on_printer_status
        )
        self._current_mode = PrintMode.CMYK_WHITE

        self._build_menubar()
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()

        self.setStyleSheet(STYLE)
        self._update_actions()
        QTimer.singleShot(600, self._connect_printer)

    # ── Menu Bar ───────────────────────────────────────────────────────────

    def _build_menubar(self):
        mb = self.menuBar()

        # 檔案
        fm = mb.addMenu("檔案(&F)")
        self._act_open  = fm.addAction("開啟影像(&O)…", self._open_image, QKeySequence("Ctrl+O"))
        self._act_close = fm.addAction("移除目前工作(&W)", self._remove_job, QKeySequence("Ctrl+W"))
        fm.addSeparator()
        self._act_save_rip = fm.addAction("儲存 ESC/P-R 資料…", self._save_rip)
        fm.addSeparator()
        fm.addAction("結束(&X)", self.close, QKeySequence("Alt+F4"))

        # 編輯
        em = mb.addMenu("編輯(&E)")
        em.addAction("清除工作佇列", self._clear_queue)
        em.addSeparator()
        em.addAction("偏好設定…", lambda: QMessageBox.information(self,"設定","尚未開放"))

        # 語言
        lm = mb.addMenu("語言(&L)")
        lm.addAction("繁體中文 ✓")
        lm.addAction("English")

        # 檢視
        vm = mb.addMenu("檢視(&V)")
        vm.addAction("彩色預覽", lambda: self._set_view("color"), QKeySequence("Ctrl+1"))
        vm.addAction("白墨預覽", lambda: self._set_view("white"), QKeySequence("Ctrl+2"))
        vm.addAction("黑底預覽", lambda: self._set_view("black"), QKeySequence("Ctrl+3"))
        vm.addSeparator()
        vm.addAction("日誌視窗", lambda: self._tabs.setCurrentIndex(3))

        # 說明
        hm = mb.addMenu("說明(&H)")
        hm.addAction("WinUSB 驅動安裝指南", self._show_driver_help)
        hm.addSeparator()
        hm.addAction("關於 L805 DTF RIP", self._show_about)

    # ── Toolbar ────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        tb = QToolBar("主工具列", self)
        tb.setMovable(False)
        tb.setIconSize(QSize(16,16))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        tb.addAction("📂  開啟影像", self._open_image)
        tb.addSeparator()

        self._tb_rip   = tb.addAction("▶  編譯 RIP",   self._start_rip)
        self._tb_print = tb.addAction("🖨  傳送噴印",   self._start_print)
        self._tb_cancel = tb.addAction("✕  取消",        self._cancel)
        tb.addSeparator()

        # View toggle buttons
        lbl = QLabel("預覽:  ")
        lbl.setStyleSheet("color:#777780;font-size:11px;padding:0 4px")
        tb.addWidget(lbl)

        for label, mode in [("彩色","color"),("白墨","white"),("黑底","black")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.setStyleSheet("""
                QPushButton{background:#2A2A2E;border:1px solid #3A3A3E;
                    color:#888890;padding:2px 10px;border-radius:4px;}
                QPushButton:checked{background:#0A3A60;border-color:#0A84FF;color:#FFFFFF;}
                QPushButton:hover{background:#353540;}
            """)
            btn.clicked.connect(lambda checked, m=mode: self._set_view(m))
            if mode == "color":
                btn.setChecked(True)
                self._view_btn_color = btn
            elif mode == "white":
                self._view_btn_white = btn
            else:
                self._view_btn_black = btn
            tb.addWidget(btn)

        tb.addSeparator()
        self._printer_badge = QLabel("● 未連接")
        self._printer_badge.setStyleSheet("color:#FF453A;font-size:11px;padding:0 8px")
        tb.addWidget(self._printer_badge)

        scan_btn = QPushButton("掃描印表機")
        scan_btn.setFixedHeight(26)
        scan_btn.setStyleSheet("""
            QPushButton{background:#1E3A1E;border:1px solid #2E5A2E;
                color:#5CC85C;padding:2px 10px;border-radius:4px;}
            QPushButton:hover{background:#244422;}
        """)
        scan_btn.clicked.connect(self._connect_printer)
        tb.addWidget(scan_btn)

    # ── Central Layout ─────────────────────────────────────────────────────

    def _build_central(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)

        # ── Left: Job queue ──
        left = QWidget()
        left.setFixedWidth(210)
        left.setStyleSheet("background:#1E1E22;border-right:1px solid #2A2A2E")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0,0,0,0)
        ll.setSpacing(0)

        queue_hdr = QLabel("  工作佇列")
        queue_hdr.setFixedHeight(36)
        queue_hdr.setStyleSheet("""
            background:#161618;color:#666670;font-size:10px;
            letter-spacing:1.5px;text-transform:uppercase;
            border-bottom:1px solid #2A2A2E;padding-left:10px;
        """)
        ll.addWidget(queue_hdr)

        self._queue_list = QListWidget()
        self._queue_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._queue_list.itemClicked.connect(self._on_job_selected)
        self._queue_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._queue_list.customContextMenuRequested.connect(self._queue_context_menu)
        ll.addWidget(self._queue_list, 1)

        add_btn = QPushButton("＋  加入影像")
        add_btn.setFixedHeight(36)
        add_btn.setStyleSheet("""
            QPushButton{background:#1A2A1A;border:none;border-top:1px solid #2A3A2A;
                color:#5CC85C;font-size:12px;}
            QPushButton:hover{background:#1E341E;}
        """)
        add_btn.clicked.connect(self._open_image)
        ll.addWidget(add_btn)

        root.addWidget(left)

        # ── Center: Preview ──
        mid = QWidget()
        mid.setStyleSheet("background:#1A1A1D")
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(12,10,12,10)
        ml.setSpacing(8)

        # Channel bar
        ch_frame = QFrame()
        ch_frame.setStyleSheet("background:#212125;border-radius:8px;padding:6px")
        ch_lay = QVBoxLayout(ch_frame)
        ch_lay.setContentsMargins(8,6,8,6)
        ch_lay.setSpacing(4)
        ch_lbl = QLabel("CHANNEL MAPPING")
        ch_lbl.setStyleSheet("color:#444450;font-size:9px;letter-spacing:2px")
        self.channel_bar = ChannelBar()
        ch_lay.addWidget(ch_lbl)
        ch_lay.addWidget(self.channel_bar)
        ml.addWidget(ch_frame)

        # Preview
        self.preview = PreviewWidget()
        self.preview.image_dropped.connect(self._on_image_dropped)
        ml.addWidget(self.preview, 1)

        # Image info bar
        self._img_info = QLabel("尚未載入影像")
        self._img_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_info.setStyleSheet("color:#444450;font-size:10px;font-family:monospace;padding:2px")
        ml.addWidget(self._img_info)

        # Progress
        self._progress = QProgressBar()
        self._progress.setRange(0,100)
        self._progress.setFixedHeight(6)
        self._progress.setVisible(False)
        ml.addWidget(self._progress)

        self._progress_lbl = QLabel("")
        self._progress_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._progress_lbl.setStyleSheet("color:#555560;font-size:10px;font-family:monospace")
        self._progress_lbl.setVisible(False)
        ml.addWidget(self._progress_lbl)

        # Action row
        act_row = QHBoxLayout()
        act_row.setSpacing(8)

        self._mode_lbl = QLabel("模式 1 · 彩色＋白墨")
        self._mode_lbl.setStyleSheet("color:#555560;font-size:11px")

        self._btn_rip   = QPushButton("▶  編譯 RIP")
        self._btn_print = QPushButton("🖨  噴印")
        self._btn_rip.setObjectName("btn_rip")
        self._btn_print.setObjectName("btn_print")
        self._btn_rip.setFixedHeight(38)
        self._btn_print.setFixedHeight(38)
        self._btn_rip.clicked.connect(self._start_rip)
        self._btn_print.clicked.connect(self._start_print)

        act_row.addWidget(self._mode_lbl)
        act_row.addStretch()
        act_row.addWidget(self._btn_rip)
        act_row.addWidget(self._btn_print)
        ml.addLayout(act_row)

        root.addWidget(mid, 1)

        # ── Right: Settings ──
        right = QWidget()
        right.setFixedWidth(260)
        right.setStyleSheet("background:#222226;border-left:1px solid #2A2A2E")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(10,10,10,10)
        rl.setSpacing(10)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_mode_tab(),     "模式")
        self._tabs.addTab(self._build_ink_tab(),      "墨水")
        self._tabs.addTab(self._build_halftone_tab(), "加網")
        self._tabs.addTab(self._build_log_tab(),      "日誌")
        rl.addWidget(self._tabs, 1)

        root.addWidget(right)

    # ── Right panel tabs ───────────────────────────────────────────────────

    def _build_mode_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(5)

        MODES = [
            (PrintMode.CMYK_WHITE, "模式 1", "彩色 ＋ 白墨",  "標準 DTF"),
            (PrintMode.WHITE_CMYK, "模式 2", "白墨 ＋ 彩色",  "燈箱/打樣"),
            (PrintMode.CMYK_ONLY,  "模式 3", "僅彩色 CMYK",    "無白墨"),
            (PrintMode.WHITE_ONLY, "模式 4", "僅白墨",          "單色矽膠"),
        ]
        self._mode_frames = {}
        for mode, num, title, sub in MODES:
            f = QFrame()
            f.setFixedHeight(58)
            f.setStyleSheet("""
                QFrame{background:#2A2A2E;border:1px solid #383838;border-radius:7px}
                QFrame:hover{border-color:#4A4A52}
            """)
            f.setCursor(Qt.CursorShape.PointingHandCursor)
            fl = QVBoxLayout(f)
            fl.setContentsMargins(10,6,10,6)
            fl.setSpacing(1)
            t = QLabel(f"{num} · {title}")
            t.setStyleSheet("font-weight:600;font-size:12px;color:#CCCCCC")
            s = QLabel(sub)
            s.setStyleSheet("font-size:10px;color:#555560")
            fl.addWidget(t); fl.addWidget(s)
            f.mousePressEvent = lambda e, m=mode: self._select_mode(m)
            f._mode = mode
            lay.addWidget(f)
            self._mode_frames[mode] = f

        lay.addStretch()

        # DPI
        dpi_grp = QGroupBox("DPI")
        dl = QVBoxLayout(dpi_grp)
        self._dpi_combo = QComboBox()
        self._dpi_combo.addItems(["1440 × 1440（標準）","5760 × 1440（最高）","720 × 720（草稿）"])
        dl.addWidget(self._dpi_combo)

        row = QHBoxLayout()
        row.addWidget(QLabel("Multi-pass"))
        self._pass_spin = QSpinBox()
        self._pass_spin.setRange(1,8); self._pass_spin.setValue(4)
        self._pass_spin.setSuffix(" x")
        row.addWidget(self._pass_spin)
        dl.addLayout(row)
        lay.addWidget(dpi_grp)

        # Paper
        paper_grp = QGroupBox("紙張")
        pl = QVBoxLayout(paper_grp)
        self._paper_combo = QComboBox()
        self._paper_combo.addItems(["A4  (210×297 mm)","A5  (148×210 mm)","A6  (105×148 mm)"])
        pl.addWidget(self._paper_combo)
        lay.addWidget(paper_grp)

        self._select_mode(PrintMode.CMYK_WHITE)
        return w

    def _build_ink_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        wg = QGroupBox("白墨 White Ink")
        wl = QGridLayout(wg)

        wl.addWidget(QLabel("濃度"), 0, 0)
        self._white_slider = QSlider(Qt.Orientation.Horizontal)
        self._white_slider.setRange(0,100); self._white_slider.setValue(90)
        self._white_val = QLabel("90%"); self._white_val.setFixedWidth(36)
        self._white_val.setStyleSheet("color:#EEEEEE;font-family:monospace;font-size:11px")
        self._white_slider.valueChanged.connect(lambda v: self._white_val.setText(f"{v}%"))
        wl.addWidget(self._white_slider,0,1); wl.addWidget(self._white_val,0,2)

        wl.addWidget(QLabel("Alpha 閾值"), 1, 0)
        self._alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self._alpha_slider.setRange(0,30); self._alpha_slider.setValue(5)
        self._alpha_val = QLabel("5"); self._alpha_val.setFixedWidth(36)
        self._alpha_val.setStyleSheet("color:#EEEEEE;font-family:monospace;font-size:11px")
        self._alpha_slider.valueChanged.connect(lambda v: self._alpha_val.setText(str(v)))
        wl.addWidget(self._alpha_slider,1,1); wl.addWidget(self._alpha_val,1,2)
        lay.addWidget(wg)

        cg = QGroupBox("Choke 收邊腐蝕")
        cl = QVBoxLayout(cg)
        self._choke_cb = QCheckBox("啟用  W_choked = W ⊖ K")
        self._choke_cb.setChecked(True)
        row = QHBoxLayout()
        row.addWidget(QLabel("收縮"))
        self._choke_spin = QSpinBox()
        self._choke_spin.setRange(1,5); self._choke_spin.setValue(2)
        self._choke_spin.setSuffix(" px")
        row.addWidget(self._choke_spin); row.addStretch()
        cl.addWidget(self._choke_cb); cl.addLayout(row)
        lay.addWidget(cg)

        ig = QGroupBox("彩色墨量")
        il = QGridLayout(ig)
        il.addWidget(QLabel("上限"), 0, 0)
        self._color_slider = QSlider(Qt.Orientation.Horizontal)
        self._color_slider.setRange(50,100); self._color_slider.setValue(85)
        self._color_val = QLabel("85%"); self._color_val.setFixedWidth(36)
        self._color_val.setStyleSheet("color:#EEEEEE;font-family:monospace;font-size:11px")
        self._color_slider.valueChanged.connect(lambda v: self._color_val.setText(f"{v}%"))
        il.addWidget(self._color_slider,0,1); il.addWidget(self._color_val,0,2)
        lay.addWidget(ig)

        lay.addStretch()
        return w

    def _build_halftone_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        info = QLabel(
            "Floyd-Steinberg 誤差擴散\n"
            "8-bit → 2-bit: 0/1.5/3.0/4.5 pl"
        )
        info.setStyleSheet("color:#555560;font-size:11px;line-height:1.7;padding:4px")
        lay.addWidget(info)

        ag = QGroupBox("加網參數")
        al = QGridLayout(ag)
        al.addWidget(QLabel("擴散強度"), 0, 0)
        self._diff_slider = QSlider(Qt.Orientation.Horizontal)
        self._diff_slider.setRange(50,100); self._diff_slider.setValue(100)
        self._diff_val = QLabel("100%"); self._diff_val.setFixedWidth(36)
        self._diff_val.setStyleSheet("color:#EEEEEE;font-family:monospace;font-size:11px")
        self._diff_slider.valueChanged.connect(lambda v: self._diff_val.setText(f"{v}%"))
        al.addWidget(self._diff_slider,0,1); al.addWidget(self._diff_val,0,2)
        lay.addWidget(ag)

        dg = QGroupBox("VSDT 微滴")
        dl = QVBoxLayout(dg)
        for code, name, size in [("00","不噴墨","0 pl"),("01","小墨滴","1.5 pl"),
                                  ("10","中墨滴","3.0 pl"),("11","大墨滴★","4.5 pl")]:
            f = QFrame()
            f.setStyleSheet("QFrame{background:#2A2A2E;border-radius:5px}")
            fl = QHBoxLayout(f); fl.setContentsMargins(8,5,8,5)
            c = QLabel(code)
            c.setStyleSheet("font-family:monospace;font-size:13px;font-weight:700;color:#0A84FF;min-width:28px")
            n = QLabel(f"{name}  {size}")
            n.setStyleSheet("font-size:11px;color:#888890")
            fl.addWidget(c); fl.addWidget(n); fl.addStretch()
            dl.addWidget(f)
        lay.addWidget(dg)
        lay.addStretch()
        return w

    def _build_log_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self._log_box = QTextEdit()
        self._log_box.setReadOnly(True)
        self._log_box.setPlaceholderText("ESC/P-R 編譯日誌...")
        lay.addWidget(self._log_box)
        row = QHBoxLayout()
        cb = QPushButton("清除"); cb.clicked.connect(self._log_box.clear)
        sb = QPushButton("儲存…"); sb.clicked.connect(self._save_log)
        row.addWidget(cb); row.addWidget(sb); row.addStretch()
        lay.addLayout(row)
        return w

    # ── Status bar ─────────────────────────────────────────────────────────

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_lbl = QLabel("待機中")
        self._status_lbl.setStyleSheet("color:#555560")
        sb.addWidget(self._status_lbl)
        self._status_right = QLabel("L805 DTF RIP Engine v1.0")
        self._status_right.setStyleSheet("color:#333338;margin-right:8px")
        sb.addPermanentWidget(self._status_right)

    # ── Actions ────────────────────────────────────────────────────────────

    def _select_mode(self, mode: PrintMode):
        self._current_mode = mode
        for m, f in self._mode_frames.items():
            if m == mode:
                f.setStyleSheet("QFrame{background:#0A2A50;border:1px solid #0A84FF;border-radius:7px}")
            else:
                f.setStyleSheet("QFrame{background:#2A2A2E;border:1px solid #383838;border-radius:7px}QFrame:hover{border-color:#4A4A52}")
        self.channel_bar.set_mode(mode)
        labels = {
            PrintMode.CMYK_WHITE: "模式 1 · 彩色＋白墨",
            PrintMode.WHITE_CMYK: "模式 2 · 白墨＋彩色",
            PrintMode.CMYK_ONLY:  "模式 3 · 僅彩色",
            PrintMode.WHITE_ONLY: "模式 4 · 僅白墨",
        }
        self._mode_lbl.setText(labels.get(mode,""))

    def _set_view(self, mode: str):
        self.preview.set_view_mode(mode)
        for btn, m in [(self._view_btn_color,"color"),
                       (self._view_btn_white,"white"),
                       (self._view_btn_black,"black")]:
            btn.setChecked(m == mode)

    def _on_image_dropped(self, path: str):
        if not path:
            self._open_image()
            return
        self._load_image_path(path)

    def _open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "開啟影像", "",
            "影像檔案 (*.png *.tif *.tiff *.bmp *.jpg *.jpeg)")
        if path:
            self._load_image_path(path)

    def _load_image_path(self, path: str):
        try:
            img = Image.open(path).convert("RGBA")
            job = JobItem(path, img)
            self._jobs.append(job)
            item = QListWidgetItem(f"  {job.name}\n  {job.size}  {img.mode}")
            item.setData(Qt.ItemDataRole.UserRole, len(self._jobs)-1)
            self._queue_list.addItem(item)
            self._queue_list.setCurrentItem(item)
            self._select_job(job)
            self._log(f"載入: {path}")
        except Exception as e:
            QMessageBox.critical(self, "載入失敗", str(e))

    def _on_job_selected(self, item: QListWidgetItem):
        idx = item.data(Qt.ItemDataRole.UserRole)
        if 0 <= idx < len(self._jobs):
            self._select_job(self._jobs[idx])

    def _select_job(self, job: JobItem):
        self._current_job = job
        self.preview.load_image(job.image)
        w,h = job.image.size
        self._img_info.setText(f"{job.name}   {w}×{h} px   {job.image.mode}")
        self._rip_data = job.rip_data
        self._update_actions()

    def _remove_job(self):
        row = self._queue_list.currentRow()
        if row >= 0:
            self._queue_list.takeItem(row)
            if 0 <= row < len(self._jobs):
                self._jobs.pop(row)
            # Re-index
            for i in range(self._queue_list.count()):
                self._queue_list.item(i).setData(Qt.ItemDataRole.UserRole, i)
            self._current_job = None
            self._rip_data = None
            self.preview._pil_image = None
            self.preview._show_empty()
            self._img_info.setText("尚未載入影像")
            self._update_actions()

    def _clear_queue(self):
        self._queue_list.clear()
        self._jobs.clear()
        self._current_job = None
        self._rip_data = None
        self.preview._pil_image = None
        self.preview._show_empty()
        self._img_info.setText("尚未載入影像")
        self._update_actions()

    def _queue_context_menu(self, pos: QPoint):
        item = self._queue_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        menu.addAction("選取此工作", lambda: self._queue_list.setCurrentItem(item))
        menu.addAction("移除", self._remove_job)
        menu.exec(self._queue_list.mapToGlobal(pos))

    def _current_config(self) -> RIPConfig:
        dpi_map = {0: DPIMode.DPI_1440x1440, 1: DPIMode.DPI_5760x1440, 2: DPIMode.DPI_720x720}
        return RIPConfig(
            mode=self._current_mode,
            dpi=dpi_map.get(self._dpi_combo.currentIndex(), DPIMode.DPI_1440x1440),
            white_density=self._white_slider.value()/100,
            alpha_threshold=self._alpha_slider.value(),
            color_ink_limit=self._color_slider.value()/100,
            choke_enabled=self._choke_cb.isChecked(),
            choke_pixels=self._choke_spin.value(),
            multipass=self._pass_spin.value(),
            error_diffusion_strength=self._diff_slider.value()/100,
        )

    def _update_actions(self):
        has_img = self._current_job is not None
        has_rip = self._rip_data is not None
        self._btn_rip.setEnabled(has_img)
        self._btn_print.setEnabled(has_rip)
        self._tb_rip.setEnabled(has_img)
        self._tb_print.setEnabled(has_rip)

    def _connect_printer(self):
        self._log("掃描 USB 裝置...")
        self.printer.find_printer()

    def _on_printer_status(self, s: str):
        colors = {PrinterStatus.READY:"#4CAF50",PrinterStatus.PRINTING:"#FF9800",
                  PrinterStatus.ERROR:"#FF453A",PrinterStatus.DISCONNECTED:"#FF453A"}
        col = colors.get(s,"#777780")
        self._printer_badge.setText(f"● {s}")
        self._printer_badge.setStyleSheet(f"color:{col};font-size:11px;padding:0 8px")
        self._status_right.setText(f"印表機: {s}")

    def _start_rip(self):
        if not self._current_job:
            return
        self._btn_rip.setEnabled(False)
        self._btn_print.setEnabled(False)
        self._progress.setVisible(True)
        self._progress_lbl.setVisible(True)
        self._log("=== 開始 RIP 編譯 ===")
        cfg = self._current_config()
        self._rip_worker = RIPWorker(self._current_job.image, cfg)
        self._rip_worker.progress.connect(self._on_progress)
        self._rip_worker.log_msg.connect(self._log)
        self._rip_worker.finished.connect(self._on_rip_done)
        self._rip_worker.error.connect(self._on_rip_error)
        self._rip_worker.start()

    def _on_rip_done(self, data: bytes):
        self._rip_data = data
        if self._current_job:
            self._current_job.rip_data = data
        self._progress.setValue(100)
        self._btn_rip.setEnabled(True)
        self._btn_print.setEnabled(True)
        self._progress.setVisible(False)
        self._progress_lbl.setVisible(False)
        self._log(f"=== RIP 完成: {len(data):,} bytes ===")
        self._status_lbl.setText(f"RIP 完成 — {len(data)/1024:.1f} KB 就緒")

    def _on_rip_error(self, err: str):
        self._btn_rip.setEnabled(self._current_job is not None)
        self._progress.setVisible(False)
        self._progress_lbl.setVisible(False)
        self._log(f"❌ {err}")
        QMessageBox.critical(self, "RIP 失敗", err)

    def _on_progress(self, pct: int, msg: str):
        self._progress.setValue(pct)
        self._progress_lbl.setText(msg)
        self._status_lbl.setText(msg)

    def _start_print(self):
        if not self._rip_data:
            return
        self._btn_print.setEnabled(False)
        self._btn_rip.setEnabled(False)
        self._progress.setVisible(True)
        self._progress_lbl.setVisible(True)
        self._log("=== 開始傳輸至印表機 ===")
        self._usb_worker = USBWorker(self.printer, self._rip_data)
        self._usb_worker.progress.connect(self._on_progress)
        self._usb_worker.log_msg.connect(self._log)
        self._usb_worker.finished.connect(self._on_print_done)
        self._usb_worker.start()

    def _on_print_done(self, ok: bool):
        self._btn_print.setEnabled(self._rip_data is not None)
        self._btn_rip.setEnabled(self._current_job is not None)
        self._progress.setVisible(False)
        self._progress_lbl.setVisible(False)
        if ok:
            self._log("=== 噴印完成 ===")
            QMessageBox.information(self, "完成", "已成功傳送至 Epson L805")
        else:
            self._log("❌ 噴印失敗")

    def _cancel(self):
        if self._rip_worker and self._rip_worker.isRunning():
            self._rip_worker.terminate()
        if self._usb_worker and self._usb_worker.isRunning():
            self.printer.cancel()
        self._progress.setVisible(False)
        self._progress_lbl.setVisible(False)
        self._update_actions()
        self._log("⚠ 已取消")

    def _log(self, msg: str):
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log_box.append(f"[{ts}] {msg}")
        self._log_box.verticalScrollBar().setValue(
            self._log_box.verticalScrollBar().maximum())

    def _save_log(self):
        p,_ = QFileDialog.getSaveFileName(self,"儲存日誌","rip_log.txt","文字 (*.txt)")
        if p:
            with open(p,'w',encoding='utf-8') as f:
                f.write(self._log_box.toPlainText())

    def _save_rip(self):
        if not self._rip_data:
            QMessageBox.warning(self,"無資料","請先執行 RIP 編譯")
            return
        p,_ = QFileDialog.getSaveFileName(self,"儲存 ESC/P-R","output.prn","PRN (*.prn);;All (*)")
        if p:
            with open(p,'wb') as f: f.write(self._rip_data)
            self._log(f"已儲存: {p}")

    def _show_driver_help(self):
        QMessageBox.information(self,"WinUSB 驅動安裝",
            "1. 下載 Zadig: https://zadig.akeo.ie\n"
            "2. 連接 L805 USB 並開機\n"
            "3. Zadig → Options → List All Devices\n"
            "4. 選擇 EPSON L805\n"
            "5. Driver 選 WinUSB → Replace Driver\n"
            "6. 完成後重新掃描印表機")

    def _show_about(self):
        QMessageBox.about(self,"關於 L805 DTF RIP Engine",
            "Epson L805 DTF RIP Engine v1.0\n\n"
            "CMYKWW 六通道直通 WinUSB 噴印引擎\n"
            "Floyd-Steinberg 誤差擴散 · VSDT 多階微滴\n"
            "Morphological Choke · ESC/P-R 1440/5760 DPI\n\n"
            "© 2026 DTF Studio")


# ── Entry ──────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("L805 DTF RIP Engine")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
