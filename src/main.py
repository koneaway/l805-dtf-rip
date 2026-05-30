"""
Epson L805 DTF RIP Engine
One-click print: RIP + USB transfer in single pipeline
"""
import sys, os, datetime
from pathlib import Path
from PIL import Image

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QSlider, QComboBox, QCheckBox,
    QGroupBox, QFileDialog, QProgressBar, QTextEdit, QSplitter,
    QFrame, QStatusBar, QMessageBox, QTabWidget, QSpinBox,
    QSizePolicy, QToolBar, QListWidget, QListWidgetItem,
    QAbstractItemView, QMenu
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QPoint, QUrl
from PyQt6.QtGui import (
    QPixmap, QImage, QAction, QKeySequence, QDragEnterEvent, QDropEvent
)

sys.path.insert(0, os.path.dirname(__file__))
from rip_engine import RIPCompiler, RIPConfig, PrintMode, DPIMode
from usb_comm import L805Printer, PrinterStatus


# ── Print Pipeline Worker ──────────────────────────────────────────────────
# RIP + USB transfer in a single thread, just like real RIP software.
# User clicks Print → everything happens automatically.

class PrintPipelineWorker(QThread):
    progress = pyqtSignal(int, str)   # pct, message
    log_msg  = pyqtSignal(str)
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, image: Image.Image, config: RIPConfig,
                 printer: L805Printer):
        super().__init__()
        self.image   = image
        self.config  = config
        self.printer = printer
        self._cancel = False

    def cancel(self):
        self._cancel = True
        self.printer.cancel()

    def run(self):
        try:
            # ── Phase 1: RIP (0–70%) ──────────────────────────────────────
            self.log_msg.emit("── 開始 RIP 編譯 ──")
            compiler = RIPCompiler(
                self.config,
                progress_cb=lambda p, m: self.progress.emit(int(p * 0.7), m),
                log_cb=lambda m: self.log_msg.emit(m)
            )
            rip_data = compiler.compile(self.image)

            if self._cancel:
                self.finished.emit(False, "已取消")
                return

            self.log_msg.emit(f"RIP 完成: {len(rip_data):,} bytes")
            self.progress.emit(70, "RIP 完成，準備傳輸...")

            # ── Phase 2: USB transfer (70–100%) ──────────────────────────
            self.log_msg.emit("── 傳輸至印表機 ──")

            def usb_progress(pct, msg):
                mapped = 70 + int(pct * 0.30)
                self.progress.emit(mapped, msg)

            ok = self.printer.send_data(rip_data, progress_cb=usb_progress)

            if ok:
                self.progress.emit(100, "列印完成")
                self.finished.emit(True, "列印工作已送出")
            else:
                self.finished.emit(False, "USB 傳輸失敗")

        except Exception as e:
            self.finished.emit(False, str(e))


# ── Style ──────────────────────────────────────────────────────────────────

STYLE = """
* { font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; }
QMainWindow, QWidget { background: #1E1E22; color: #CCCCCC; }

QMenuBar {
    background: #141416; color: #BBBBBB;
    border-bottom: 1px solid #2A2A2E; padding: 1px 4px;
}
QMenuBar::item { padding: 4px 10px; border-radius: 3px; }
QMenuBar::item:selected { background: #2A2A30; color: #FFF; }
QMenu {
    background: #1E1E22; color: #CCCCCC;
    border: 1px solid #333338; padding: 4px 0;
}
QMenu::item { padding: 6px 28px 6px 14px; }
QMenu::item:selected { background: #0A84FF; color: #FFF; }
QMenu::separator { height: 1px; background: #2A2A2E; margin: 3px 8px; }

QToolBar {
    background: #181820; border-bottom: 1px solid #2A2A2E;
    spacing: 3px; padding: 4px 8px;
}
QToolBar::separator { background: #2A2A2E; width: 1px; margin: 3px 5px; }

QGroupBox {
    border: 1px solid #2E2E34; border-radius: 6px;
    margin-top: 14px; padding: 10px 8px 8px 8px;
    background: #1A1A1E;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 10px; top: -1px;
    padding: 0 5px; font-size: 10px; letter-spacing: 1px;
    color: #444450; background: #1E1E22;
}

QPushButton {
    background: #2A2A30; color: #CCCCCC;
    border: 1px solid #3A3A40; border-radius: 5px;
    padding: 5px 13px;
}
QPushButton:hover  { background: #34343C; border-color: #4A4A52; }
QPushButton:pressed { background: #1E1E24; }
QPushButton:disabled { color: #44444A; border-color: #2A2A2E; }

QSlider::groove:horizontal {
    height: 4px; background: #2A2A30; border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #0A84FF; border: none;
    width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
}
QSlider::sub-page:horizontal { background: #0A84FF; border-radius: 2px; }

QComboBox {
    background: #252528; border: 1px solid #353538;
    border-radius: 5px; padding: 4px 8px; color: #CCCCCC;
}
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: #1E1E22; border: 1px solid #353538;
    selection-background-color: #0A84FF; color: #CCCCCC;
}

QSpinBox {
    background: #252528; border: 1px solid #353538;
    border-radius: 5px; padding: 4px 6px; color: #CCCCCC;
}
QCheckBox { color: #AAAAAA; spacing: 6px; }
QCheckBox::indicator {
    width: 15px; height: 15px; border-radius: 3px;
    border: 1px solid #3A3A40; background: #252528;
}
QCheckBox::indicator:checked { background: #0A84FF; border-color: #0A84FF; }

QProgressBar {
    background: #252528; border: none; border-radius: 3px;
    height: 5px; text-align: center; color: transparent;
}
QProgressBar::chunk { background: #0A84FF; border-radius: 3px; }

QTextEdit {
    background: #0C0C0E; border: 1px solid #222226;
    border-radius: 5px; color: #00CC66;
    font-family: 'Cascadia Code','Consolas',monospace; font-size: 11px;
    padding: 6px;
}

QListWidget {
    background: #141416; border: none;
    color: #CCCCCC; outline: none;
}
QListWidget::item { padding: 8px 10px; border-bottom: 1px solid #1E1E22; }
QListWidget::item:selected { background: #0A1E38; border-left: 2px solid #0A84FF; }
QListWidget::item:hover:!selected { background: #1E1E24; }

QTabWidget::pane { border: 1px solid #2A2A2E; background: #1A1A1E; }
QTabBar::tab {
    background: #141416; color: #666670;
    padding: 6px 14px; border: 1px solid #2A2A2E;
    border-bottom: none; border-radius: 5px 5px 0 0; margin-right: 2px;
}
QTabBar::tab:selected { background: #1A1A1E; color: #EEEEEE; }

QStatusBar {
    background: #0E0E10; color: #44444A;
    font-size: 11px; border-top: 1px solid #1A1A1E;
}
QLabel { color: #AAAAAA; }
"""


# ── Job item ───────────────────────────────────────────────────────────────

class JobItem:
    def __init__(self, path: str, image: Image.Image):
        self.path  = path
        self.image = image
        self.name  = Path(path).name
        self.w, self.h = image.size
        self.status = "待處理"


# ── Drop-capable preview ───────────────────────────────────────────────────

class PreviewWidget(QLabel):
    file_dropped = pyqtSignal(str)
    clicked      = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(360, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAcceptDrops(True)
        self._img: Image.Image | None = None
        self._mode = "color"
        self._show_empty()

    def _show_empty(self):
        self.setStyleSheet("""
            background:#0F0F12;
            border:2px dashed #2A2A30;
            border-radius:10px;
            color:#2E2E36;
        """)
        self.setText("拖曳影像至此處\n或點擊以開啟\n\nPNG · TIFF · JPG · BMP")
        self.setPixmap(QPixmap())

    def load(self, img: Image.Image):
        self._img = img
        self._draw()

    def set_mode(self, mode: str):
        self._mode = mode
        if self._img:
            self._draw()

    def _draw(self):
        if not self._img:
            return
        import numpy as np
        rgba = self._img.convert("RGBA")
        w, h = rgba.size
        arr  = np.array(rgba).astype(np.float32)

        if self._mode == "color":
            # Checkerboard background to show transparency
            tile = max(10, min(w, h) // 28)
            bg = np.zeros((h, w, 4), dtype=np.float32)
            for y in range(0, h, tile):
                for x in range(0, w, tile):
                    c = 200 if (x // tile + y // tile) % 2 == 0 else 155
                    bg[y:y+tile, x:x+tile] = [c, c, c, 255]
            a = arr[:, :, 3:4] / 255.0
            composite = arr * a + bg * (1 - a)
            out = composite.clip(0, 255).astype(np.uint8)

        elif self._mode == "white":
            # Show alpha channel as white layer on dark bg
            alpha = arr[:, :, 3]
            out = np.zeros((h, w, 4), dtype=np.uint8)
            out[:, :, 0] = alpha
            out[:, :, 1] = alpha
            out[:, :, 2] = alpha
            out[:, :, 3] = 255

        else:  # black
            bg = np.zeros((h, w, 4), dtype=np.float32)
            bg[:, :, 3] = 255
            a = arr[:, :, 3:4] / 255.0
            composite = arr * a + bg * (1 - a)
            out = composite.clip(0, 255).astype(np.uint8)

        # Scale to widget
        canvas = Image.fromarray(out, "RGBA")
        aw = max(100, self.width() - 20)
        ah = max(80,  self.height() - 20)
        canvas.thumbnail((aw, ah), Image.LANCZOS)

        data = canvas.tobytes("raw", "RGBA")
        qi = QImage(data, canvas.width, canvas.height,
                    QImage.Format.Format_RGBA8888)
        self.setPixmap(QPixmap.fromImage(qi))
        self.setText("")
        self.setStyleSheet("""
            background:#0F0F12;
            border:1px solid #252528;
            border-radius:8px;
        """)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._img:
            QTimer.singleShot(60, self._draw)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            exts = {'.png','.jpg','.jpeg','.tif','.tiff','.bmp'}
            if any(Path(u.toLocalFile()).suffix.lower() in exts
                   for u in e.mimeData().urls()):
                e.acceptProposedAction()
                self.setStyleSheet("""
                    background:#0A1A2A;
                    border:2px dashed #0A84FF;
                    border-radius:10px; color:#0A84FF;
                """)
                self.setText("放開以載入")
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        if self._img: self._draw()
        else: self._show_empty()

    def dropEvent(self, e: QDropEvent):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if Path(p).suffix.lower() in {'.png','.jpg','.jpeg','.tif','.tiff','.bmp'}:
                self.file_dropped.emit(p)
                return


# ── Channel indicator (compact, right-panel only) ─────────────────────────

class ChannelIndicator(QWidget):
    CHANNELS = [
        ('C',  '#00B4D8'), ('M',  '#E040FB'),
        ('Y',  '#FFD600'), ('K',  '#607D8B'),
        ('W1', '#B0C4CE'), ('W2', '#CFD8DC'),
    ]
    ACTIVE = {
        PrintMode.CMYK_WHITE: {0,1,2,3,4,5},
        PrintMode.WHITE_CMYK: {0,1,2,3,4,5},
        PrintMode.CMYK_ONLY:  {0,1,2,3},
        PrintMode.WHITE_ONLY: {4,5},
    }

    def __init__(self):
        super().__init__()
        self._mode = PrintMode.CMYK_WHITE
        self.setFixedHeight(36)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._dots = []
        for sym, col in self.CHANNELS:
            w = QWidget()
            w.setFixedSize(30, 30)
            wl = QVBoxLayout(w)
            wl.setContentsMargins(0,0,0,0)
            wl.setSpacing(1)
            dot = QLabel()
            dot.setFixedSize(14, 14)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl = QLabel(sym)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size:9px;font-weight:700")
            wl.addWidget(dot, alignment=Qt.AlignmentFlag.AlignHCenter)
            wl.addWidget(lbl)
            lay.addWidget(w)
            self._dots.append((dot, lbl, col))
        self._refresh()

    def set_mode(self, m):
        self._mode = m
        self._refresh()

    def _refresh(self):
        active = self.ACTIVE.get(self._mode, set())
        for i, (dot, lbl, col) in enumerate(self._dots):
            if i in active:
                dot.setStyleSheet(f"background:{col};border-radius:7px;border:1px solid rgba(255,255,255,0.15)")
                lbl.setStyleSheet("font-size:9px;font-weight:700;color:#CCCCCC")
            else:
                dot.setStyleSheet(f"background:{col};border-radius:7px;opacity:0.15")
                lbl.setStyleSheet("font-size:9px;font-weight:700;color:#333338")


# ── Main Window ────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("L805 DTF RIP Engine")
        self.setMinimumSize(1050, 660)
        self.resize(1200, 780)

        self._jobs:    list[JobItem] = []
        self._cur_job: JobItem | None = None
        self._pipeline: PrintPipelineWorker | None = None
        self._current_mode = PrintMode.CMYK_WHITE

        self.printer = L805Printer(
            log_cb=self._log,
            status_cb=self._on_printer_status
        )

        self._build_menubar()
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self.setStyleSheet(STYLE)
        self._refresh_ui()
        QTimer.singleShot(500, self._connect_printer)

    # ── Menu bar ───────────────────────────────────────────────────────────

    def _build_menubar(self):
        mb = self.menuBar()

        # 檔案
        fm = mb.addMenu("檔案(&F)")
        a = QAction("開啟影像(&O)…", self)
        a.setShortcut(QKeySequence("Ctrl+O"))
        a.triggered.connect(self._open_image)
        fm.addAction(a)

        a2 = QAction("移除目前工作(&W)", self)
        a2.setShortcut(QKeySequence("Ctrl+W"))
        a2.triggered.connect(self._remove_job)
        fm.addAction(a2)

        fm.addSeparator()

        a3 = QAction("儲存 ESC/P-R 資料…", self)
        a3.triggered.connect(self._save_rip)
        fm.addAction(a3)

        fm.addSeparator()

        a4 = QAction("結束(&X)", self)
        a4.setShortcut(QKeySequence("Alt+F4"))
        a4.triggered.connect(self.close)
        fm.addAction(a4)

        # 編輯
        em = mb.addMenu("編輯(&E)")
        a5 = QAction("清除工作佇列", self)
        a5.triggered.connect(self._clear_queue)
        em.addAction(a5)

        # 語言
        lm = mb.addMenu("語言(&L)")
        lm.addAction(QAction("繁體中文 ✓", self))
        lm.addAction(QAction("English", self))

        # 檢視
        vm = mb.addMenu("檢視(&V)")
        for label, mode, sc in [
            ("彩色預覽", "color", "Ctrl+1"),
            ("白墨預覽", "white", "Ctrl+2"),
            ("黑底預覽", "black", "Ctrl+3"),
        ]:
            a = QAction(label, self)
            a.setShortcut(QKeySequence(sc))
            a.triggered.connect(lambda checked, m=mode: self._set_view(m))
            vm.addAction(a)

        vm.addSeparator()
        a6 = QAction("日誌", self)
        a6.triggered.connect(lambda: self._tabs.setCurrentIndex(3))
        vm.addAction(a6)

        # 說明
        hm = mb.addMenu("說明(&H)")
        a7 = QAction("WinUSB 驅動安裝指南", self)
        a7.triggered.connect(self._show_driver_help)
        hm.addAction(a7)
        hm.addSeparator()
        a8 = QAction("關於", self)
        a8.triggered.connect(self._show_about)
        hm.addAction(a8)

    # ── Toolbar ────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        tb = QToolBar("主工具列", self)
        tb.setMovable(False)
        tb.setIconSize(QSize(14, 14))
        self.addToolBar(tb)

        def tbtn(label, slot, style=""):
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.clicked.connect(slot)
            if style:
                btn.setStyleSheet(style)
            tb.addWidget(btn)
            return btn

        tbtn("📂  開啟", self._open_image)
        tb.addSeparator()

        # View toggle group
        lbl = QLabel("  預覽  ")
        lbl.setStyleSheet("color:#3A3A42;font-size:11px")
        tb.addWidget(lbl)

        self._vbtns = {}
        for label, mode in [("彩色","color"),("白墨","white"),("黑底","black")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(24)
            btn.setStyleSheet("""
                QPushButton{background:#222228;border:1px solid #2E2E34;
                    color:#666670;padding:2px 10px;font-size:11px;
                    border-radius:0}
                QPushButton:first-child{border-radius:4px 0 0 4px}
                QPushButton:checked{background:#0A2A4A;border-color:#0A84FF;color:#5ABAFF}
                QPushButton:hover{background:#2A2A32}
            """)
            btn.clicked.connect(lambda _, m=mode: self._set_view(m))
            tb.addWidget(btn)
            self._vbtns[mode] = btn
        self._vbtns["color"].setChecked(True)

        tb.addSeparator()

        # Printer status
        self._tb_printer = QLabel("● 掃描中")
        self._tb_printer.setStyleSheet("color:#888880;font-size:11px;padding:0 6px")
        tb.addWidget(self._tb_printer)

        tbtn("掃描印表機", self._connect_printer,
             "QPushButton{background:#1A2A1A;color:#5CC85C;border:1px solid #2A4A2A;border-radius:4px;font-size:11px}")

    # ── Central layout ─────────────────────────────────────────────────────

    def _build_central(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        root = QHBoxLayout(cw)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left: job queue ──────────────────────────────────────────────
        left = QWidget()
        left.setFixedWidth(200)
        left.setStyleSheet("background:#111114;border-right:1px solid #1E1E22")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        hdr = QLabel("  工作佇列")
        hdr.setFixedHeight(32)
        hdr.setStyleSheet("""
            background:#0C0C0E;color:#3A3A42;font-size:9px;
            letter-spacing:1.5px;border-bottom:1px solid #1A1A1E;
            padding-left:10px;
        """)
        ll.addWidget(hdr)

        self._queue = QListWidget()
        self._queue.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._queue.itemClicked.connect(self._on_job_click)
        self._queue.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._queue.customContextMenuRequested.connect(self._queue_ctx)
        ll.addWidget(self._queue, 1)

        add = QPushButton("＋  加入影像")
        add.setFixedHeight(34)
        add.setStyleSheet("""
            QPushButton{background:#141418;border:none;border-top:1px solid #1E1E22;
                color:#5CC85C;font-size:11px;border-radius:0}
            QPushButton:hover{background:#18221A}
        """)
        add.clicked.connect(self._open_image)
        ll.addWidget(add)

        root.addWidget(left)

        # ── Center: preview ───────────────────────────────────────────────
        mid = QWidget()
        mid.setStyleSheet("background:#111116")
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(10, 8, 10, 8)
        ml.setSpacing(6)

        # Preview toolbar (view mode strip inside center panel)
        ptb = QFrame()
        ptb.setFixedHeight(32)
        ptb.setStyleSheet("background:#161618;border-radius:6px")
        ptbl = QHBoxLayout(ptb)
        ptbl.setContentsMargins(8, 0, 8, 0)
        ptbl.setSpacing(6)
        ptbl.addWidget(QLabel("預覽:").also(
            lambda l: l.setStyleSheet("color:#3A3A42;font-size:10px")) if False
            else self._make_view_strip())
        ml.addWidget(ptb)

        self.preview = PreviewWidget()
        self.preview.file_dropped.connect(self._load_path)
        self.preview.clicked.connect(self._open_image)
        ml.addWidget(self.preview, 1)

        # Info bar
        self._info = QLabel("尚未載入影像")
        self._info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info.setStyleSheet("color:#333338;font-size:10px;font-family:monospace")
        ml.addWidget(self._info)

        # Progress
        self._prog = QProgressBar()
        self._prog.setRange(0, 100)
        self._prog.setFixedHeight(5)
        self._prog.setVisible(False)
        ml.addWidget(self._prog)

        self._prog_lbl = QLabel("")
        self._prog_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prog_lbl.setStyleSheet("color:#444450;font-size:10px;font-family:monospace")
        self._prog_lbl.setVisible(False)
        ml.addWidget(self._prog_lbl)

        # ── Action bar (bottom of center) ────────────────────────────────
        ab = QFrame()
        ab.setFixedHeight(54)
        ab.setStyleSheet("background:#0E0E12;border-top:1px solid #1A1A1E;border-radius:0")
        abl = QHBoxLayout(ab)
        abl.setContentsMargins(12, 0, 12, 0)
        abl.setSpacing(8)

        self._mode_lbl = QLabel("模式 1 · 彩色＋白墨")
        self._mode_lbl.setStyleSheet("color:#444450;font-size:11px")
        abl.addWidget(self._mode_lbl)
        abl.addStretch()

        # Cancel (hidden by default)
        self._btn_cancel = QPushButton("✕ 取消")
        self._btn_cancel.setFixedHeight(36)
        self._btn_cancel.setStyleSheet("""
            QPushButton{background:#2A1A1A;color:#FF6060;
                border:1px solid #4A2A2A;border-radius:5px;padding:0 14px}
            QPushButton:hover{background:#341E1E}
        """)
        self._btn_cancel.setVisible(False)
        self._btn_cancel.clicked.connect(self._cancel)
        abl.addWidget(self._btn_cancel)

        # THE PRINT BUTTON — one click does everything
        self._btn_print = QPushButton("  🖨  列印")
        self._btn_print.setFixedHeight(40)
        self._btn_print.setFixedWidth(130)
        self._btn_print.setStyleSheet("""
            QPushButton{
                background:#0A84FF;color:#FFF;border:none;
                font-size:14px;font-weight:700;border-radius:7px;
                padding:0 18px;
            }
            QPushButton:hover{background:#1A8EFF}
            QPushButton:pressed{background:#0070E0}
            QPushButton:disabled{background:#0A3050;color:#225588}
        """)
        self._btn_print.clicked.connect(self._print)
        abl.addWidget(self._btn_print)

        ml.addWidget(ab)
        root.addWidget(mid, 1)

        # ── Right: settings ───────────────────────────────────────────────
        right = QWidget()
        right.setFixedWidth(248)
        right.setStyleSheet("background:#161618;border-left:1px solid #1E1E22")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._tab_mode(),     "模式")
        self._tabs.addTab(self._tab_ink(),      "墨水")
        self._tabs.addTab(self._tab_halftone(), "加網")
        self._tabs.addTab(self._tab_log(),      "日誌")
        rl.addWidget(self._tabs)

        root.addWidget(right)

    def _make_view_strip(self):
        """Returns a widget with the 3 view toggle buttons inline."""
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lbl = QLabel("預覽模式  ")
        lbl.setStyleSheet("color:#3A3A42;font-size:10px")
        lay.addWidget(lbl)
        for label, mode in [("彩色","color"),("白墨層","white"),("黑底","black")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(22)
            btn.setStyleSheet("""
                QPushButton{background:#1A1A1E;border:1px solid #2A2A2E;
                    color:#555560;padding:1px 10px;font-size:11px;border-radius:0}
                QPushButton:checked{background:#0A2040;border-color:#0A84FF;color:#4AABFF}
                QPushButton:hover{background:#222228}
            """)
            btn.clicked.connect(lambda _, m=mode: self._set_view(m))
            lay.addWidget(btn)
            self._vbtns[mode] = btn
        self._vbtns["color"].setChecked(True)
        lay.addStretch()
        return w

    # ── Right-panel tabs ───────────────────────────────────────────────────

    def _tab_mode(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(5)

        MODES = [
            (PrintMode.CMYK_WHITE, "模式 1", "彩色 ＋ 白墨",  "標準 DTF"),
            (PrintMode.WHITE_CMYK, "模式 2", "白墨 ＋ 彩色",  "燈箱/打樣"),
            (PrintMode.CMYK_ONLY,  "模式 3", "僅彩色 CMYK",    "淺色膠片"),
            (PrintMode.WHITE_ONLY, "模式 4", "僅白墨",          "矽膠單色"),
        ]
        self._mode_cards = {}
        for mode, num, title, sub in MODES:
            f = QFrame()
            f.setFixedHeight(52)
            f.setCursor(Qt.CursorShape.PointingHandCursor)
            fl = QVBoxLayout(f); fl.setContentsMargins(10,5,10,5); fl.setSpacing(1)
            t = QLabel(f"{num} · {title}")
            t.setStyleSheet("font-weight:600;font-size:11px;color:#CCCCCC")
            s = QLabel(sub)
            s.setStyleSheet("font-size:10px;color:#3A3A42")
            fl.addWidget(t); fl.addWidget(s)
            f.mousePressEvent = lambda e, m=mode: self._select_mode(m)
            f._mode = mode
            lay.addWidget(f)
            self._mode_cards[mode] = f

        # Channel indicator (compact, in settings panel)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#222228;margin:4px 0")
        lay.addWidget(sep)

        ch_lbl = QLabel("通道")
        ch_lbl.setStyleSheet("color:#3A3A42;font-size:9px;letter-spacing:1px;margin-top:4px")
        lay.addWidget(ch_lbl)

        self._ch_indicator = ChannelIndicator()
        lay.addWidget(self._ch_indicator)

        lay.addStretch()

        # DPI / paper
        dg = QGroupBox("輸出設定")
        dl = QVBoxLayout(dg)
        self._dpi_combo = QComboBox()
        self._dpi_combo.addItems(["1440×1440（標準）","5760×1440（最高）","720×720（草稿）"])
        dl.addWidget(self._dpi_combo)

        row = QHBoxLayout()
        row.addWidget(QLabel("Multi-pass"))
        self._pass_spin = QSpinBox()
        self._pass_spin.setRange(1,8); self._pass_spin.setValue(4)
        self._pass_spin.setSuffix(" x")
        row.addWidget(self._pass_spin)
        dl.addLayout(row)

        self._paper_combo = QComboBox()
        self._paper_combo.addItems(["A4 (210×297mm)","A5 (148×210mm)","A6 (105×148mm)"])
        dl.addWidget(self._paper_combo)
        lay.addWidget(dg)

        self._select_mode(PrintMode.CMYK_WHITE)
        return w

    def _tab_ink(self):
        w = QWidget(); lay = QVBoxLayout(w)

        wg = QGroupBox("白墨  White Ink")
        wl = QGridLayout(wg)

        def slider_row(label, min_, max_, val, cb):
            wl_row = QHBoxLayout()
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(min_, max_); s.setValue(val)
            v = QLabel(cb(val))
            v.setFixedWidth(34)
            v.setStyleSheet("color:#EEEEEE;font-family:monospace;font-size:11px")
            s.valueChanged.connect(lambda n: v.setText(cb(n)))
            return s, v

        wl.addWidget(QLabel("濃度"), 0, 0)
        self._white_s, self._white_v = slider_row("", 0, 100, 90, lambda v: f"{v}%")
        wl.addWidget(self._white_s, 0, 1); wl.addWidget(self._white_v, 0, 2)

        wl.addWidget(QLabel("Alpha 閾值"), 1, 0)
        self._alpha_s, self._alpha_v = slider_row("", 0, 30, 5, str)
        wl.addWidget(self._alpha_s, 1, 1); wl.addWidget(self._alpha_v, 1, 2)
        lay.addWidget(wg)

        cg = QGroupBox("Choke 收邊")
        cl = QVBoxLayout(cg)
        self._choke_cb = QCheckBox("啟用  W ⊖ K")
        self._choke_cb.setChecked(True)
        row = QHBoxLayout()
        row.addWidget(QLabel("收縮"))
        self._choke_spin = QSpinBox()
        self._choke_spin.setRange(1,5); self._choke_spin.setValue(2)
        self._choke_spin.setSuffix(" px"); self._choke_spin.setFixedWidth(64)
        row.addWidget(self._choke_spin); row.addStretch()
        cl.addWidget(self._choke_cb); cl.addLayout(row)
        lay.addWidget(cg)

        ig = QGroupBox("彩色墨量上限")
        il = QGridLayout(ig)
        il.addWidget(QLabel("上限"), 0, 0)
        self._color_s, self._color_v = slider_row("", 50, 100, 85, lambda v: f"{v}%")
        il.addWidget(self._color_s, 0, 1); il.addWidget(self._color_v, 0, 2)
        lay.addWidget(ig)

        lay.addStretch()
        return w

    def _tab_halftone(self):
        w = QWidget(); lay = QVBoxLayout(w)
        info = QLabel("Floyd-Steinberg 誤差擴散\n8-bit → 2-bit: 0 / 1.5 / 3.0 / 4.5 pl")
        info.setStyleSheet("color:#3A3A42;font-size:11px;line-height:1.7;padding:4px 0")
        lay.addWidget(info)

        ag = QGroupBox("加網")
        al = QGridLayout(ag)
        al.addWidget(QLabel("擴散強度"), 0, 0)
        self._diff_s = QSlider(Qt.Orientation.Horizontal)
        self._diff_s.setRange(50,100); self._diff_s.setValue(100)
        self._diff_v = QLabel("100%")
        self._diff_v.setFixedWidth(34)
        self._diff_v.setStyleSheet("color:#EEEEEE;font-family:monospace;font-size:11px")
        self._diff_s.valueChanged.connect(lambda v: self._diff_v.setText(f"{v}%"))
        al.addWidget(self._diff_s,0,1); al.addWidget(self._diff_v,0,2)
        lay.addWidget(ag)

        dg = QGroupBox("VSDT 微滴對照")
        dl = QVBoxLayout(dg)
        for code, name, size, bg in [
            ("00","不噴墨","0 pl","#1A1A1E"),
            ("01","小墨滴","1.5 pl","#1A2030"),
            ("10","中墨滴","3.0 pl","#1A2535"),
            ("11","大墨滴★","4.5 pl","#0A1E34"),
        ]:
            f = QFrame()
            f.setStyleSheet(f"QFrame{{background:{bg};border-radius:4px}}")
            fl = QHBoxLayout(f); fl.setContentsMargins(8,5,8,5)
            c = QLabel(code); c.setStyleSheet("font-family:monospace;font-size:13px;font-weight:700;color:#0A84FF;min-width:26px")
            n = QLabel(f"{name}  {size}"); n.setStyleSheet("font-size:11px;color:#666670")
            fl.addWidget(c); fl.addWidget(n); fl.addStretch()
            dl.addWidget(f)
        lay.addWidget(dg)
        lay.addStretch()
        return w

    def _tab_log(self):
        w = QWidget(); lay = QVBoxLayout(w)
        self._log_box = QTextEdit()
        self._log_box.setReadOnly(True)
        self._log_box.setPlaceholderText("列印日誌...")
        lay.addWidget(self._log_box)
        row = QHBoxLayout()
        cb = QPushButton("清除"); cb.clicked.connect(self._log_box.clear)
        sb = QPushButton("儲存…"); sb.clicked.connect(self._save_log)
        row.addWidget(cb); row.addWidget(sb); row.addStretch()
        lay.addLayout(row)
        return w

    # ── Status bar ─────────────────────────────────────────────────────────

    def _build_statusbar(self):
        sb = QStatusBar(); self.setStatusBar(sb)
        self._sb_left  = QLabel("待機中")
        self._sb_right = QLabel("L805 DTF RIP v1.0")
        self._sb_right.setStyleSheet("color:#222228;margin-right:8px")
        sb.addWidget(self._sb_left)
        sb.addPermanentWidget(self._sb_right)

    # ── Core actions ───────────────────────────────────────────────────────

    def _select_mode(self, mode: PrintMode):
        self._current_mode = mode
        for m, f in self._mode_cards.items():
            if m == mode:
                f.setStyleSheet("QFrame{background:#0A1E38;border:1px solid #0A5090;border-radius:6px}")
            else:
                f.setStyleSheet("QFrame{background:#1C1C20;border:1px solid #252528;border-radius:6px}QFrame:hover{border-color:#3A3A3E}")
        self._ch_indicator.set_mode(mode)
        labels = {
            PrintMode.CMYK_WHITE: "模式 1 · 彩色＋白墨",
            PrintMode.WHITE_CMYK: "模式 2 · 白墨＋彩色",
            PrintMode.CMYK_ONLY:  "模式 3 · 僅彩色",
            PrintMode.WHITE_ONLY: "模式 4 · 僅白墨",
        }
        self._mode_lbl.setText(labels.get(mode, ""))

    def _set_view(self, mode: str):
        self.preview.set_mode(mode)
        for m, btn in self._vbtns.items():
            btn.setChecked(m == mode)

    def _open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "開啟影像", "",
            "影像 (*.png *.tif *.tiff *.bmp *.jpg *.jpeg)")
        if path:
            self._load_path(path)

    def _load_path(self, path: str):
        try:
            img = Image.open(path).convert("RGBA")
            job = JobItem(path, img)
            self._jobs.append(job)

            item = QListWidgetItem()
            item.setText(f"  {job.name}\n  {job.w}×{job.h}")
            item.setData(Qt.ItemDataRole.UserRole, len(self._jobs) - 1)
            self._queue.addItem(item)
            self._queue.setCurrentItem(item)
            self._activate_job(job)
            self._log(f"載入: {path}  ({job.w}×{job.h})")
        except Exception as e:
            QMessageBox.critical(self, "載入失敗", str(e))

    def _on_job_click(self, item: QListWidgetItem):
        idx = item.data(Qt.ItemDataRole.UserRole)
        if 0 <= idx < len(self._jobs):
            self._activate_job(self._jobs[idx])

    def _activate_job(self, job: JobItem):
        self._cur_job = job
        self.preview.load(job.image)
        self._info.setText(f"{job.name}   {job.w}×{job.h} px   RGBA")
        self.setWindowTitle(f"L805 DTF RIP Engine — [{job.name}]")
        self._refresh_ui()

    def _remove_job(self):
        row = self._queue.currentRow()
        if row < 0: return
        self._queue.takeItem(row)
        if 0 <= row < len(self._jobs):
            self._jobs.pop(row)
        for i in range(self._queue.count()):
            self._queue.item(i).setData(Qt.ItemDataRole.UserRole, i)
        self._cur_job = None
        self.preview._img = None
        self.preview._show_empty()
        self._info.setText("尚未載入影像")
        self.setWindowTitle("L805 DTF RIP Engine")
        self._refresh_ui()

    def _clear_queue(self):
        self._queue.clear(); self._jobs.clear()
        self._cur_job = None
        self.preview._img = None; self.preview._show_empty()
        self._info.setText("尚未載入影像")
        self.setWindowTitle("L805 DTF RIP Engine")
        self._refresh_ui()

    def _queue_ctx(self, pos: QPoint):
        item = self._queue.itemAt(pos)
        if not item: return
        menu = QMenu(self)
        a1 = QAction("選取", self); a1.triggered.connect(lambda: self._queue.setCurrentItem(item)); menu.addAction(a1)
        a2 = QAction("移除", self); a2.triggered.connect(self._remove_job); menu.addAction(a2)
        menu.exec(self._queue.mapToGlobal(pos))

    def _current_config(self) -> RIPConfig:
        dpi_map = {0: DPIMode.DPI_1440x1440, 1: DPIMode.DPI_5760x1440, 2: DPIMode.DPI_720x720}
        return RIPConfig(
            mode=self._current_mode,
            dpi=dpi_map.get(self._dpi_combo.currentIndex(), DPIMode.DPI_1440x1440),
            white_density=self._white_s.value() / 100,
            alpha_threshold=self._alpha_s.value(),
            color_ink_limit=self._color_s.value() / 100,
            choke_enabled=self._choke_cb.isChecked(),
            choke_pixels=self._choke_spin.value(),
            multipass=self._pass_spin.value(),
            error_diffusion_strength=self._diff_s.value() / 100,
        )

    # ── THE main action: one-click print ──────────────────────────────────
    def _print(self):
        if not self._cur_job:
            return

        self._btn_print.setEnabled(False)
        self._btn_cancel.setVisible(True)
        self._prog.setValue(0)
        self._prog.setVisible(True)
        self._prog_lbl.setVisible(True)
        self._log(f"═══ 列印: {self._cur_job.name} ═══")

        self._pipeline = PrintPipelineWorker(
            self._cur_job.image,
            self._current_config(),
            self.printer
        )
        self._pipeline.progress.connect(self._on_progress)
        self._pipeline.log_msg.connect(self._log)
        self._pipeline.finished.connect(self._on_done)
        self._pipeline.start()

    def _cancel(self):
        if self._pipeline and self._pipeline.isRunning():
            self._pipeline.cancel()
        self._log("⚠ 已取消")
        self._reset_ui()

    def _on_progress(self, pct: int, msg: str):
        self._prog.setValue(pct)
        self._prog_lbl.setText(msg)
        self._sb_left.setText(msg)

    def _on_done(self, ok: bool, msg: str):
        self._reset_ui()
        if ok:
            self._log(f"✓ {msg}")
            self._sb_left.setText(f"✓ {msg}")
            QMessageBox.information(self, "列印完成", f"{self._cur_job.name if self._cur_job else ''}\n已成功送出至 Epson L805")
        else:
            self._log(f"✗ {msg}")
            if msg != "已取消":
                QMessageBox.warning(self, "列印失敗", msg)

    def _reset_ui(self):
        self._btn_print.setEnabled(self._cur_job is not None)
        self._btn_cancel.setVisible(False)
        self._prog.setVisible(False)
        self._prog_lbl.setVisible(False)

    def _refresh_ui(self):
        has = self._cur_job is not None
        self._btn_print.setEnabled(has)

    # ── Printer ────────────────────────────────────────────────────────────

    def _connect_printer(self):
        self._log("掃描 USB 裝置...")
        self.printer.find_printer()

    def _on_printer_status(self, s: str):
        colors = {
            PrinterStatus.READY:        "#4CAF50",
            PrinterStatus.PRINTING:     "#FF9800",
            PrinterStatus.ERROR:        "#FF5252",
            PrinterStatus.DISCONNECTED: "#FF5252",
        }
        col = colors.get(s, "#888880")
        self._tb_printer.setText(f"● {s}")
        self._tb_printer.setStyleSheet(f"color:{col};font-size:11px;padding:0 6px")
        self._sb_right.setText(f"印表機: {s}")

    # ── Log / Save ─────────────────────────────────────────────────────────

    def _log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log_box.append(f"[{ts}] {msg}")
        self._log_box.verticalScrollBar().setValue(
            self._log_box.verticalScrollBar().maximum())

    def _save_log(self):
        p, _ = QFileDialog.getSaveFileName(self, "儲存日誌", "log.txt", "文字 (*.txt)")
        if p:
            with open(p, 'w', encoding='utf-8') as f:
                f.write(self._log_box.toPlainText())

    def _save_rip(self):
        QMessageBox.information(self, "提示", "請先列印一次，日誌中會顯示 ESC/P-R 資料大小。\n如需儲存原始資料，請在日誌 tab 中儲存。")

    def _show_driver_help(self):
        QMessageBox.information(self, "WinUSB 驅動安裝",
            "1. 下載 Zadig: https://zadig.akeo.ie\n"
            "2. L805 USB 連接電腦並開機\n"
            "3. Zadig → Options → List All Devices\n"
            "4. 選擇 EPSON L805\n"
            "5. Driver 選 WinUSB → Replace Driver\n"
            "6. 完成後重新掃描印表機")

    def _show_about(self):
        QMessageBox.about(self, "關於",
            "Epson L805 DTF RIP Engine v1.0\n\n"
            "CMYKWW 六通道 · WinUSB 直通\n"
            "Floyd-Steinberg · VSDT · ESC/P-R\n"
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
