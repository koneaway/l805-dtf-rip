"""
Epson L805 DTF RIP Engine
- One-click print (RIP + USB in single pipeline)
- Proper cancel with interrupt flag
- USB device scanner with printer name display
- Memory-only RIP data (no temp files)
"""
import sys, os, datetime
from pathlib import Path
from PIL import Image

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QSlider, QComboBox, QCheckBox,
    QGroupBox, QFileDialog, QProgressBar, QTextEdit, QFrame,
    QStatusBar, QMessageBox, QTabWidget, QSpinBox, QSizePolicy,
    QToolBar, QListWidget, QListWidgetItem, QAbstractItemView, QMenu,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QDialogButtonBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QPoint, QUrl
from PyQt6.QtGui import QPixmap, QImage, QAction, QKeySequence, QDragEnterEvent, QDropEvent

sys.path.insert(0, os.path.dirname(__file__))
from rip_engine import RIPCompiler, RIPConfig, PrintMode, DPIMode
from usb_comm import L805Printer, PrinterStatus, scan_usb_printers


# ── Pipeline worker ────────────────────────────────────────────────────────

class PrintPipeline(QThread):
    progress = pyqtSignal(int, str)
    log_msg  = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, image, config, printer):
        super().__init__()
        self.image    = image
        self.config   = config
        self.printer  = printer
        self._compiler = None

    def cancel(self):
        if self._compiler:
            self._compiler.cancel()
        self.printer.cancel()

    def run(self):
        try:
            # Phase 1: RIP (maps to 0-70%)
            self.log_msg.emit("── RIP 開始 ──")
            self._compiler = RIPCompiler(
                self.config,
                progress_cb=lambda p, m: self.progress.emit(int(p * 0.70), m),
                log_cb=lambda m: self.log_msg.emit(m)
            )
            rip_data = self._compiler.compile(self.image)
            # RIP data lives only in this local variable — no disk write

            self.log_msg.emit(f"RIP 完成 · {len(rip_data):,} bytes (僅存於記憶體，不寫入磁碟)")
            self.progress.emit(70, "RIP 完成，開始傳輸…")

            # Phase 2: USB transfer (maps to 70-100%)
            self.log_msg.emit("── USB 傳輸 ──")
            ok = self.printer.send_data(
                rip_data,
                progress_cb=lambda p, m: self.progress.emit(70 + int(p * 0.30), m)
            )
            if ok:
                self.progress.emit(100, "列印工作已送出")
                self.finished.emit(True, "列印工作已送出至印表機")
            else:
                if self.printer._cancel_flag:
                    self.finished.emit(False, "已取消")
                else:
                    self.finished.emit(False, "USB 傳輸失敗")

        except InterruptedError:
            self.log_msg.emit("⚠ RIP 取消")
            self.finished.emit(False, "已取消")
        except Exception as e:
            self.finished.emit(False, str(e))


# ── USB Printer Selector Dialog ────────────────────────────────────────────

class PrinterSelectorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("選擇印表機")
        self.setMinimumSize(640, 300)
        self.setStyleSheet(parent.styleSheet() if parent else "")
        self._selected = None

        lay = QVBoxLayout(self)

        hdr = QLabel("掃描到的 USB 印表機裝置")
        hdr.setStyleSheet("font-size:13px;font-weight:600;color:#CCCCCC;margin-bottom:4px")
        lay.addWidget(hdr)

        sub = QLabel("選取正確的印表機，然後點擊「使用此印表機」。如果沒有看到 L805，請確認已安裝 WinUSB 驅動。")
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#555560;font-size:11px;margin-bottom:8px")
        lay.addWidget(sub)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["裝置名稱", "製造商", "VID / PID", "Bus / Addr", "狀態"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setStyleSheet("""
            QTableWidget{background:#141416;color:#CCCCCC;border:1px solid #2A2A2E;gridline-color:#1E1E22}
            QTableWidget::item{padding:5px 8px}
            QTableWidget::item:selected{background:#0A1E38;color:#FFF}
            QHeaderView::section{background:#1A1A1E;color:#666670;border:none;padding:5px 8px;font-size:11px}
        """)
        self._table.doubleClicked.connect(self._accept_selection)
        lay.addWidget(self._table)

        btn_row = QHBoxLayout()
        self._scan_btn = QPushButton("🔄  重新掃描")
        self._scan_btn.clicked.connect(self._scan)
        self._use_sim  = QPushButton("模擬模式（無印表機）")
        self._use_sim.clicked.connect(self._accept_sim)
        self._ok_btn   = QPushButton("使用此印表機")
        self._ok_btn.setStyleSheet("""
            QPushButton{background:#0A84FF;color:#FFF;border:none;
                border-radius:5px;padding:6px 18px;font-weight:600}
            QPushButton:hover{background:#1A8EFF}
            QPushButton:disabled{background:#0A2A4A;color:#224466}
        """)
        self._ok_btn.setEnabled(False)
        self._ok_btn.clicked.connect(self._accept_selection)

        btn_row.addWidget(self._scan_btn)
        btn_row.addWidget(self._use_sim)
        btn_row.addStretch()
        btn_row.addWidget(self._ok_btn)
        lay.addLayout(btn_row)

        self._scan()

    def _scan(self):
        self._table.setRowCount(0)
        self._scan_btn.setEnabled(False)
        self._scan_btn.setText("掃描中…")
        QApplication.processEvents()

        devices = scan_usb_printers()
        self._devices = devices

        for i, d in enumerate(devices):
            self._table.insertRow(i)
            name = d['product'] or "Unknown"
            mfr  = d['manufacturer'] or ""
            vidpid = f"0x{d['vid']:04X} / 0x{d['pid']:04X}"
            busaddr = f"{d['bus']} / {d['address']}"
            status = "✓ Epson L805" if d['is_l805'] else ("Epson" if d['is_epson'] else "其他印表機")

            for col, text in enumerate([name, mfr, vidpid, busaddr, status]):
                item = QTableWidgetItem(text)
                if d['is_l805']:
                    item.setForeground(QColor("#4CAF50") if col == 4 else QColor("#CCCCCC"))
                    item.setBackground(QColor("#0A1A0A"))
                self._table.setItem(i, col, item)

        self._table.resizeColumnsToContents()
        self._scan_btn.setEnabled(True)
        self._scan_btn.setText("🔄  重新掃描")

        # Auto-select L805 if found
        for i, d in enumerate(devices):
            if d['is_l805']:
                self._table.selectRow(i)
                self._ok_btn.setEnabled(True)
                break

        self._table.selectionModel().selectionChanged.connect(
            lambda: self._ok_btn.setEnabled(
                len(self._table.selectedItems()) > 0))

    def _accept_selection(self):
        rows = self._table.selectedItems()
        if not rows:
            return
        row = self._table.currentRow()
        if 0 <= row < len(self._devices):
            self._selected = self._devices[row]
        self.accept()

    def _accept_sim(self):
        self._selected = None  # None = simulation mode
        self.accept()

    def get_selected(self):
        return self._selected  # None = sim mode, dict = real device


# Need to import QColor for the dialog
from PyQt6.QtGui import QColor


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
QMenu { background: #1E1E22; color: #CCCCCC; border: 1px solid #333338; padding: 4px 0; }
QMenu::item { padding: 6px 28px 6px 14px; }
QMenu::item:selected { background: #0A84FF; color: #FFF; }
QMenu::separator { height: 1px; background: #2A2A2E; margin: 3px 8px; }

QToolBar { background: #181820; border-bottom: 1px solid #2A2A2E; spacing: 3px; padding: 4px 8px; }
QToolBar::separator { background: #2A2A2E; width: 1px; margin: 3px 5px; }

QGroupBox {
    border: 1px solid #2E2E34; border-radius: 6px;
    margin-top: 14px; padding: 10px 8px 8px 8px; background: #1A1A1E;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 10px; top: -1px;
    padding: 0 5px; font-size: 10px; letter-spacing: 1px;
    color: #444450; background: #1E1E22;
}

QPushButton {
    background: #2A2A30; color: #CCCCCC;
    border: 1px solid #3A3A40; border-radius: 5px; padding: 5px 13px;
}
QPushButton:hover  { background: #34343C; border-color: #4A4A52; }
QPushButton:pressed { background: #1E1E24; }
QPushButton:disabled { color: #44444A; border-color: #2A2A2E; }

QSlider::groove:horizontal { height: 4px; background: #2A2A30; border-radius: 2px; }
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
QComboBox QAbstractItemView { background: #1E1E22; border: 1px solid #353538; selection-background-color: #0A84FF; color: #CCCCCC; }

QSpinBox { background: #252528; border: 1px solid #353538; border-radius: 5px; padding: 4px 6px; color: #CCCCCC; }
QCheckBox { color: #AAAAAA; spacing: 6px; }
QCheckBox::indicator { width: 15px; height: 15px; border-radius: 3px; border: 1px solid #3A3A40; background: #252528; }
QCheckBox::indicator:checked { background: #0A84FF; border-color: #0A84FF; }

QProgressBar { background: #252528; border: none; border-radius: 3px; height: 5px; color: transparent; }
QProgressBar::chunk { background: #0A84FF; border-radius: 3px; }

QTextEdit { background: #0C0C0E; border: 1px solid #222226; border-radius: 5px; color: #00CC66; font-family: 'Cascadia Code','Consolas',monospace; font-size: 11px; padding: 6px; }

QListWidget { background: #141416; border: none; color: #CCCCCC; outline: none; }
QListWidget::item { padding: 8px 10px; border-bottom: 1px solid #1E1E22; }
QListWidget::item:selected { background: #0A1E38; border-left: 2px solid #0A84FF; }
QListWidget::item:hover:!selected { background: #1E1E24; }

QTabWidget::pane { border: 1px solid #2A2A2E; background: #1A1A1E; }
QTabBar::tab { background: #141416; color: #666670; padding: 6px 14px; border: 1px solid #2A2A2E; border-bottom: none; border-radius: 5px 5px 0 0; margin-right: 2px; }
QTabBar::tab:selected { background: #1A1A1E; color: #EEEEEE; }
QTabBar::tab:hover:!selected { color: #AAAAAA; }

QStatusBar { background: #0E0E10; color: #44444A; font-size: 11px; border-top: 1px solid #1A1A1E; }
QLabel { color: #AAAAAA; }
"""


# ── Job item ───────────────────────────────────────────────────────────────

class JobItem:
    def __init__(self, path, image):
        self.path  = path
        self.image = image
        self.name  = Path(path).name
        self.w, self.h = image.size


# ── Preview widget ─────────────────────────────────────────────────────────

class PreviewWidget(QLabel):
    file_dropped = pyqtSignal(str)
    clicked      = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(360, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAcceptDrops(True)
        self._img  = None
        self._mode = "color"
        self._show_empty()

    def _show_empty(self):
        self.setStyleSheet("background:#0F0F12;border:2px dashed #2A2A30;border-radius:10px;color:#2E2E36")
        self.setText("拖曳影像至此處\n或點擊以開啟\n\nPNG · TIFF · JPG · BMP")
        self.setPixmap(QPixmap())

    def load(self, img):
        self._img = img
        self._draw()

    def set_mode(self, mode):
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
            tile = max(10, min(w, h) // 28)
            bg   = np.zeros((h, w, 4), dtype=np.float32)
            for y in range(0, h, tile):
                for x in range(0, w, tile):
                    c = 200.0 if (x // tile + y // tile) % 2 == 0 else 155.0
                    bg[y:y+tile, x:x+tile] = [c, c, c, 255]
            a   = arr[:, :, 3:4] / 255.0
            out = (arr * a + bg * (1 - a)).clip(0, 255).astype(np.uint8)
        elif self._mode == "white":
            alpha = arr[:, :, 3]
            out = np.zeros((h, w, 4), dtype=np.uint8)
            out[:, :, 0] = out[:, :, 1] = out[:, :, 2] = alpha.astype(np.uint8)
            out[:, :, 3] = 255
        else:
            bg  = np.zeros((h, w, 4), dtype=np.float32); bg[:, :, 3] = 255
            a   = arr[:, :, 3:4] / 255.0
            out = (arr * a + bg * (1 - a)).clip(0, 255).astype(np.uint8)

        canvas = Image.fromarray(out, "RGBA")
        aw = max(100, self.width() - 20)
        ah = max(80,  self.height() - 20)
        canvas.thumbnail((aw, ah), Image.LANCZOS)
        data = canvas.tobytes("raw", "RGBA")
        qi   = QImage(data, canvas.width, canvas.height, QImage.Format.Format_RGBA8888)
        self.setPixmap(QPixmap.fromImage(qi))
        self.setText("")
        self.setStyleSheet("background:#0F0F12;border:1px solid #252528;border-radius:8px")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._img:
            QTimer.singleShot(60, self._draw)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            exts = {'.png','.jpg','.jpeg','.tif','.tiff','.bmp'}
            if any(Path(u.toLocalFile()).suffix.lower() in exts for u in e.mimeData().urls()):
                e.acceptProposedAction()
                self.setStyleSheet("background:#0A1A2A;border:2px dashed #0A84FF;border-radius:10px;color:#0A84FF")
                self.setText("放開以載入")
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        if self._img: self._draw()
        else: self._show_empty()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if Path(p).suffix.lower() in {'.png','.jpg','.jpeg','.tif','.tiff','.bmp'}:
                self.file_dropped.emit(p)
                return


# ── Channel indicator ──────────────────────────────────────────────────────

class ChannelIndicator(QWidget):
    CH    = [('C','#00B4D8'),('M','#E040FB'),('Y','#FFD600'),
             ('K','#607D8B'),('W1','#B0C4CE'),('W2','#CFD8DC')]
    ACTIVE = {
        PrintMode.CMYK_WHITE: {0,1,2,3,4,5},
        PrintMode.WHITE_CMYK: {0,1,2,3,4,5},
        PrintMode.CMYK_ONLY:  {0,1,2,3},
        PrintMode.WHITE_ONLY: {4,5},
    }

    def __init__(self):
        super().__init__()
        self._mode = PrintMode.CMYK_WHITE
        self.setFixedHeight(34)
        lay = QHBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(4)
        self._items = []
        for sym, col in self.CH:
            w = QWidget(); w.setFixedSize(30, 28)
            wl = QVBoxLayout(w); wl.setContentsMargins(0,0,0,0); wl.setSpacing(1)
            dot = QLabel(); dot.setFixedSize(14,14); dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl = QLabel(sym); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size:9px;font-weight:700")
            wl.addWidget(dot, alignment=Qt.AlignmentFlag.AlignHCenter); wl.addWidget(lbl)
            lay.addWidget(w)
            self._items.append((dot, lbl, col))
        self._refresh()

    def set_mode(self, m):
        self._mode = m; self._refresh()

    def _refresh(self):
        active = self.ACTIVE.get(self._mode, set())
        for i,(dot,lbl,col) in enumerate(self._items):
            if i in active:
                dot.setStyleSheet(f"background:{col};border-radius:7px;border:1px solid rgba(255,255,255,0.15)")
                lbl.setStyleSheet("font-size:9px;font-weight:700;color:#CCCCCC")
            else:
                dot.setStyleSheet(f"background:#2A2A2E;border-radius:7px")
                lbl.setStyleSheet("font-size:9px;font-weight:700;color:#333338")


# ── Printer status panel (replaces simple badge) ───────────────────────────

class PrinterPanel(QFrame):
    scan_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setStyleSheet("QFrame{background:#111116;border-bottom:1px solid #1E1E22}")
        self.setFixedHeight(44)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        self._dot = QLabel("●")
        self._dot.setStyleSheet("color:#FF5252;font-size:14px")
        lay.addWidget(self._dot)

        self._name = QLabel("未連接印表機")
        self._name.setStyleSheet("color:#555560;font-size:12px")
        lay.addWidget(self._name)

        self._port = QLabel("")
        self._port.setStyleSheet("color:#333338;font-size:10px;font-family:monospace")
        lay.addWidget(self._port)

        lay.addStretch()

        self._sim_badge = QLabel("模擬模式")
        self._sim_badge.setStyleSheet("""
            background:#2A2A10;color:#888840;border:1px solid #404020;
            font-size:10px;padding:2px 8px;border-radius:10px
        """)
        self._sim_badge.setVisible(False)
        lay.addWidget(self._sim_badge)

        btn = QPushButton("🔌  選擇印表機")
        btn.setFixedHeight(28)
        btn.setStyleSheet("""
            QPushButton{background:#1A2A1A;color:#5CC85C;border:1px solid #2A4A2A;
                border-radius:5px;font-size:11px;padding:0 12px}
            QPushButton:hover{background:#1E341E}
        """)
        btn.clicked.connect(self.scan_requested)
        lay.addWidget(btn)

    def update_status(self, status: str, device_info: dict | None,
                      sim_mode: bool):
        colors = {
            PrinterStatus.READY:        "#4CAF50",
            PrinterStatus.PRINTING:     "#FF9800",
            PrinterStatus.ERROR:        "#FF5252",
            PrinterStatus.DISCONNECTED: "#FF5252",
        }
        col = colors.get(status, "#888880")
        self._dot.setStyleSheet(f"color:{col};font-size:14px")

        if device_info:
            name = device_info.get('product') or "Epson Printer"
            self._name.setText(name)
            self._name.setStyleSheet(f"color:{col};font-size:12px;font-weight:600")
            bus  = device_info.get('bus', 0)
            addr = device_info.get('address', 0)
            vid  = device_info.get('vid', 0)
            pid  = device_info.get('pid', 0)
            self._port.setText(f"  USB Bus {bus} · Addr {addr} · {vid:04X}:{pid:04X}")
        else:
            self._name.setText("未連接印表機" if not sim_mode else "Epson L805")
            self._name.setStyleSheet(f"color:{'#888840' if sim_mode else col};font-size:12px")
            self._port.setText("")

        self._sim_badge.setVisible(sim_mode)


# ── Main Window ────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("L805 DTF RIP Engine")
        self.setMinimumSize(1050, 660)
        self.resize(1200, 780)

        self._jobs: list[JobItem] = []
        self._cur_job = None
        self._pipeline = None
        self._current_mode = PrintMode.CMYK_WHITE
        self._device_info  = None

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
        QTimer.singleShot(600, self._open_printer_selector)

    # ── Menu bar ───────────────────────────────────────────────────────────

    def _build_menubar(self):
        mb = self.menuBar()

        fm = mb.addMenu("檔案(&F)")
        for text, slot, sc in [
            ("開啟影像(&O)…",    self._open_image,  "Ctrl+O"),
            ("移除目前工作(&W)", self._remove_job,   "Ctrl+W"),
        ]:
            a = QAction(text, self); a.setShortcut(QKeySequence(sc))
            a.triggered.connect(slot); fm.addAction(a)
        fm.addSeparator()
        a = QAction("結束(&X)", self); a.setShortcut(QKeySequence("Alt+F4"))
        a.triggered.connect(self.close); fm.addAction(a)

        em = mb.addMenu("編輯(&E)")
        a = QAction("清除工作佇列", self); a.triggered.connect(self._clear_queue)
        em.addAction(a)

        lm = mb.addMenu("語言(&L)")
        lm.addAction(QAction("繁體中文 ✓", self))
        lm.addAction(QAction("English", self))

        vm = mb.addMenu("檢視(&V)")
        for text, mode, sc in [
            ("彩色預覽", "color", "Ctrl+1"),
            ("白墨預覽", "white", "Ctrl+2"),
            ("黑底預覽", "black", "Ctrl+3"),
        ]:
            a = QAction(text, self); a.setShortcut(QKeySequence(sc))
            a.triggered.connect(lambda _, m=mode: self._set_view(m))
            vm.addAction(a)
        vm.addSeparator()
        a = QAction("日誌", self); a.triggered.connect(lambda: self._tabs.setCurrentIndex(3))
        vm.addAction(a)

        hm = mb.addMenu("說明(&H)")
        a = QAction("選擇印表機 / WinUSB 說明", self)
        a.triggered.connect(self._open_printer_selector); hm.addAction(a)
        hm.addSeparator()
        a = QAction("關於", self); a.triggered.connect(self._show_about)
        hm.addAction(a)

    # ── Toolbar ────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        tb = QToolBar("主工具列", self)
        tb.setMovable(False); tb.setIconSize(QSize(14,14))
        self.addToolBar(tb)

        def tbtn(label, slot, style=""):
            btn = QPushButton(label); btn.setFixedHeight(28)
            btn.clicked.connect(slot)
            if style: btn.setStyleSheet(style)
            tb.addWidget(btn); return btn

        tbtn("📂  開啟", self._open_image)
        tb.addSeparator()

        lbl = QLabel("  預覽  "); lbl.setStyleSheet("color:#3A3A42;font-size:11px")
        tb.addWidget(lbl)

        self._vbtns = {}
        for label, mode in [("彩色","color"),("白墨","white"),("黑底","black")]:
            btn = QPushButton(label); btn.setCheckable(True); btn.setFixedHeight(24)
            btn.setStyleSheet("""
                QPushButton{background:#222228;border:1px solid #2E2E34;color:#666670;
                    padding:2px 10px;font-size:11px;border-radius:0}
                QPushButton:checked{background:#0A2A4A;border-color:#0A84FF;color:#5ABAFF}
                QPushButton:hover{background:#2A2A32}
            """)
            btn.clicked.connect(lambda _, m=mode: self._set_view(m))
            tb.addWidget(btn); self._vbtns[mode] = btn
        self._vbtns["color"].setChecked(True)

    # ── Central layout ─────────────────────────────────────────────────────

    def _build_central(self):
        cw = QWidget(); self.setCentralWidget(cw)
        root = QVBoxLayout(cw); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Printer panel at top
        self._printer_panel = PrinterPanel()
        self._printer_panel.scan_requested.connect(self._open_printer_selector)
        root.addWidget(self._printer_panel)

        # Main split
        body = QWidget()
        body_lay = QHBoxLayout(body); body_lay.setContentsMargins(0,0,0,0); body_lay.setSpacing(0)
        root.addWidget(body, 1)

        # ── Left: job queue ──
        left = QWidget(); left.setFixedWidth(200)
        left.setStyleSheet("background:#111114;border-right:1px solid #1E1E22")
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)

        hdr = QLabel("  工作佇列")
        hdr.setFixedHeight(32)
        hdr.setStyleSheet("background:#0C0C0E;color:#3A3A42;font-size:9px;letter-spacing:1.5px;border-bottom:1px solid #1A1A1E;padding-left:10px")
        ll.addWidget(hdr)

        self._queue = QListWidget()
        self._queue.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._queue.itemClicked.connect(self._on_job_click)
        self._queue.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._queue.customContextMenuRequested.connect(self._queue_ctx)
        ll.addWidget(self._queue, 1)

        add = QPushButton("＋  加入影像"); add.setFixedHeight(34)
        add.setStyleSheet("""
            QPushButton{background:#141418;border:none;border-top:1px solid #1E1E22;
                color:#5CC85C;font-size:11px;border-radius:0}
            QPushButton:hover{background:#18221A}
        """)
        add.clicked.connect(self._open_image); ll.addWidget(add)
        body_lay.addWidget(left)

        # ── Center: preview ──
        mid = QWidget(); mid.setStyleSheet("background:#111116")
        ml = QVBoxLayout(mid); ml.setContentsMargins(10,8,10,8); ml.setSpacing(6)

        self.preview = PreviewWidget()
        self.preview.file_dropped.connect(self._load_path)
        self.preview.clicked.connect(self._open_image)
        ml.addWidget(self.preview, 1)

        self._info = QLabel("尚未載入影像")
        self._info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info.setStyleSheet("color:#333338;font-size:10px;font-family:monospace")
        ml.addWidget(self._info)

        self._prog = QProgressBar(); self._prog.setRange(0,100)
        self._prog.setFixedHeight(5); self._prog.setVisible(False)
        ml.addWidget(self._prog)

        self._prog_lbl = QLabel("")
        self._prog_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prog_lbl.setStyleSheet("color:#444450;font-size:10px;font-family:monospace")
        self._prog_lbl.setVisible(False)
        ml.addWidget(self._prog_lbl)

        # Action bar
        ab = QFrame(); ab.setFixedHeight(54)
        ab.setStyleSheet("background:#0E0E12;border-top:1px solid #1A1A1E")
        abl = QHBoxLayout(ab); abl.setContentsMargins(12,0,12,0); abl.setSpacing(8)

        self._mode_lbl = QLabel("模式 1 · 彩色＋白墨")
        self._mode_lbl.setStyleSheet("color:#444450;font-size:11px")
        abl.addWidget(self._mode_lbl)
        abl.addStretch()

        self._btn_cancel = QPushButton("✕ 取消")
        self._btn_cancel.setFixedHeight(36)
        self._btn_cancel.setStyleSheet("""
            QPushButton{background:#2A1A1A;color:#FF6060;border:1px solid #4A2A2A;border-radius:5px;padding:0 14px}
            QPushButton:hover{background:#341E1E}
        """)
        self._btn_cancel.setVisible(False)
        self._btn_cancel.clicked.connect(self._cancel)
        abl.addWidget(self._btn_cancel)

        self._btn_print = QPushButton("  🖨  列印")
        self._btn_print.setFixedHeight(40); self._btn_print.setFixedWidth(130)
        self._btn_print.setStyleSheet("""
            QPushButton{background:#0A84FF;color:#FFF;border:none;
                font-size:14px;font-weight:700;border-radius:7px;padding:0 18px}
            QPushButton:hover{background:#1A8EFF}
            QPushButton:pressed{background:#0070E0}
            QPushButton:disabled{background:#0A3050;color:#225588}
        """)
        self._btn_print.clicked.connect(self._print)
        abl.addWidget(self._btn_print)

        ml.addWidget(ab)
        body_lay.addWidget(mid, 1)

        # ── Right: settings ──
        right = QWidget(); right.setFixedWidth(248)
        right.setStyleSheet("background:#161618;border-left:1px solid #1E1E22")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        self._tabs = QTabWidget()
        self._tabs.addTab(self._tab_mode(),     "模式")
        self._tabs.addTab(self._tab_ink(),      "墨水")
        self._tabs.addTab(self._tab_halftone(), "加網")
        self._tabs.addTab(self._tab_log(),      "日誌")
        rl.addWidget(self._tabs)
        body_lay.addWidget(right)

    # ── Right tabs ─────────────────────────────────────────────────────────

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
            f = QFrame(); f.setFixedHeight(52)
            f.setCursor(Qt.CursorShape.PointingHandCursor)
            fl = QVBoxLayout(f); fl.setContentsMargins(10,5,10,5); fl.setSpacing(1)
            t = QLabel(f"{num} · {title}"); t.setStyleSheet("font-weight:600;font-size:11px;color:#CCCCCC")
            s = QLabel(sub); s.setStyleSheet("font-size:10px;color:#3A3A42")
            fl.addWidget(t); fl.addWidget(s)
            f.mousePressEvent = lambda e, m=mode: self._select_mode(m)
            lay.addWidget(f); self._mode_cards[mode] = f

        sep = QFrame(); sep.setFixedHeight(1); sep.setStyleSheet("background:#222228;margin:4px 0")
        lay.addWidget(sep)

        ch_lbl = QLabel("通道"); ch_lbl.setStyleSheet("color:#3A3A42;font-size:9px;letter-spacing:1px")
        lay.addWidget(ch_lbl)
        self._ch_ind = ChannelIndicator(); lay.addWidget(self._ch_ind)
        lay.addStretch()

        dg = QGroupBox("輸出設定"); dl = QVBoxLayout(dg)
        self._dpi_combo = QComboBox()
        self._dpi_combo.addItems(["1440×1440（標準）","5760×1440（最高）","720×720（草稿）"])
        dl.addWidget(self._dpi_combo)
        row = QHBoxLayout(); row.addWidget(QLabel("Multi-pass"))
        self._pass_spin = QSpinBox(); self._pass_spin.setRange(1,8); self._pass_spin.setValue(4); self._pass_spin.setSuffix(" x")
        row.addWidget(self._pass_spin); dl.addLayout(row)
        self._paper_combo = QComboBox()
        self._paper_combo.addItems(["A4 (210×297mm)","A5 (148×210mm)","A6 (105×148mm)"])
        dl.addWidget(self._paper_combo); lay.addWidget(dg)

        self._select_mode(PrintMode.CMYK_WHITE)
        return w

    def _tab_ink(self):
        w = QWidget(); lay = QVBoxLayout(w)

        def mk_slider(min_, max_, val, fmt):
            s = QSlider(Qt.Orientation.Horizontal); s.setRange(min_, max_); s.setValue(val)
            v = QLabel(fmt(val)); v.setFixedWidth(34); v.setStyleSheet("color:#EEEEEE;font-family:monospace;font-size:11px")
            s.valueChanged.connect(lambda n: v.setText(fmt(n)))
            return s, v

        wg = QGroupBox("白墨"); wl = QGridLayout(wg)
        wl.addWidget(QLabel("濃度"), 0, 0)
        self._white_s, self._white_v = mk_slider(0, 100, 90, lambda v: f"{v}%")
        wl.addWidget(self._white_s,0,1); wl.addWidget(self._white_v,0,2)
        wl.addWidget(QLabel("Alpha 閾值"), 1, 0)
        self._alpha_s, self._alpha_v = mk_slider(0, 30, 5, str)
        wl.addWidget(self._alpha_s,1,1); wl.addWidget(self._alpha_v,1,2)
        lay.addWidget(wg)

        cg = QGroupBox("Choke 收邊"); cl = QVBoxLayout(cg)
        self._choke_cb = QCheckBox("啟用  W ⊖ K"); self._choke_cb.setChecked(True)
        row = QHBoxLayout(); row.addWidget(QLabel("收縮"))
        self._choke_spin = QSpinBox(); self._choke_spin.setRange(1,5); self._choke_spin.setValue(2); self._choke_spin.setSuffix(" px"); self._choke_spin.setFixedWidth(64)
        row.addWidget(self._choke_spin); row.addStretch()
        cl.addWidget(self._choke_cb); cl.addLayout(row); lay.addWidget(cg)

        ig = QGroupBox("彩色墨量"); il = QGridLayout(ig)
        il.addWidget(QLabel("上限"), 0, 0)
        self._color_s, self._color_v = mk_slider(50, 100, 85, lambda v: f"{v}%")
        il.addWidget(self._color_s,0,1); il.addWidget(self._color_v,0,2)
        lay.addWidget(ig); lay.addStretch()
        return w

    def _tab_halftone(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Floyd-Steinberg\n8-bit → 2-bit: 0/1.5/3.0/4.5 pl").also(
            lambda l: None) if False else self._make_info_label())

        ag = QGroupBox("加網"); al = QGridLayout(ag)
        al.addWidget(QLabel("擴散強度"), 0, 0)
        self._diff_s = QSlider(Qt.Orientation.Horizontal); self._diff_s.setRange(50,100); self._diff_s.setValue(100)
        self._diff_v = QLabel("100%"); self._diff_v.setFixedWidth(34); self._diff_v.setStyleSheet("color:#EEEEEE;font-family:monospace;font-size:11px")
        self._diff_s.valueChanged.connect(lambda v: self._diff_v.setText(f"{v}%"))
        al.addWidget(self._diff_s,0,1); al.addWidget(self._diff_v,0,2)
        lay.addWidget(ag)

        dg = QGroupBox("VSDT 微滴"); dl = QVBoxLayout(dg)
        for code,name,size,bg in [("00","不噴墨","0 pl","#1A1A1E"),("01","小墨滴","1.5 pl","#1A2030"),("10","中墨滴","3.0 pl","#1A2535"),("11","大墨滴★","4.5 pl","#0A1E34")]:
            f = QFrame(); f.setStyleSheet(f"QFrame{{background:{bg};border-radius:4px}}")
            fl = QHBoxLayout(f); fl.setContentsMargins(8,5,8,5)
            c = QLabel(code); c.setStyleSheet("font-family:monospace;font-size:13px;font-weight:700;color:#0A84FF;min-width:26px")
            n = QLabel(f"{name}  {size}"); n.setStyleSheet("font-size:11px;color:#666670")
            fl.addWidget(c); fl.addWidget(n); fl.addStretch(); dl.addWidget(f)
        lay.addWidget(dg); lay.addStretch()
        return w

    def _make_info_label(self):
        l = QLabel("Floyd-Steinberg 誤差擴散\n8-bit → 2-bit: 0 / 1.5 / 3.0 / 4.5 pl")
        l.setStyleSheet("color:#3A3A42;font-size:11px;line-height:1.7;padding:4px 0")
        return l

    def _tab_log(self):
        w = QWidget(); lay = QVBoxLayout(w)
        self._log_box = QTextEdit(); self._log_box.setReadOnly(True)
        self._log_box.setPlaceholderText("列印日誌 (RIP 資料僅存於記憶體，不寫入磁碟)...")
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
        self._sb = QLabel("待機中"); sb.addWidget(self._sb)
        sb.addPermanentWidget(QLabel("L805 DTF RIP v1.0  ").also(
            lambda l: l.setStyleSheet("color:#222228;margin-right:4px")) if False
            else self._make_sb_right())

    def _make_sb_right(self):
        l = QLabel("L805 DTF RIP v1.0  ")
        l.setStyleSheet("color:#222228;margin-right:4px")
        return l

    # ── Actions ────────────────────────────────────────────────────────────

    def _select_mode(self, mode):
        self._current_mode = mode
        for m, f in self._mode_cards.items():
            if m == mode:
                f.setStyleSheet("QFrame{background:#0A1E38;border:1px solid #0A5090;border-radius:6px}")
            else:
                f.setStyleSheet("QFrame{background:#1C1C20;border:1px solid #252528;border-radius:6px}QFrame:hover{border-color:#3A3A3E}")
        self._ch_ind.set_mode(mode)
        labels = {
            PrintMode.CMYK_WHITE:"模式 1 · 彩色＋白墨",
            PrintMode.WHITE_CMYK:"模式 2 · 白墨＋彩色",
            PrintMode.CMYK_ONLY: "模式 3 · 僅彩色",
            PrintMode.WHITE_ONLY:"模式 4 · 僅白墨",
        }
        self._mode_lbl.setText(labels.get(mode,""))

    def _set_view(self, mode):
        self.preview.set_mode(mode)
        for m, btn in self._vbtns.items():
            btn.setChecked(m == mode)

    def _open_printer_selector(self):
        dlg = PrinterSelectorDialog(self)
        if dlg.exec():
            sel = dlg.get_selected()
            if sel is None:
                # Simulation mode
                self.printer._sim_mode = True
                self._device_info = None
                self.printer._set_status(PrinterStatus.READY)
                self._log("使用模擬模式（不連接實體印表機）")
            else:
                self._device_info = sel
                self.printer.select_device(sel['bus'], sel['address'])
                self.printer._sim_mode = False
                ok = self.printer.find_printer()
                if ok:
                    self._log(f"已連接: {sel['product']} (Bus {sel['bus']} Addr {sel['address']})")
            self._printer_panel.update_status(
                self.printer.status, self._device_info, self.printer._sim_mode)

    def _open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "開啟影像", "",
            "影像 (*.png *.tif *.tiff *.bmp *.jpg *.jpeg)")
        if path:
            self._load_path(path)

    def _load_path(self, path):
        try:
            img = Image.open(path).convert("RGBA")
            job = JobItem(path, img)
            self._jobs.append(job)
            item = QListWidgetItem()
            item.setText(f"  {job.name}\n  {job.w}×{job.h}")
            item.setData(Qt.ItemDataRole.UserRole, len(self._jobs)-1)
            self._queue.addItem(item)
            self._queue.setCurrentItem(item)
            self._activate_job(job)
            self._log(f"載入: {path}  ({job.w}×{job.h})")
        except Exception as e:
            QMessageBox.critical(self, "載入失敗", str(e))

    def _on_job_click(self, item):
        idx = item.data(Qt.ItemDataRole.UserRole)
        if 0 <= idx < len(self._jobs):
            self._activate_job(self._jobs[idx])

    def _activate_job(self, job):
        self._cur_job = job
        self.preview.load(job.image)
        self._info.setText(f"{job.name}   {job.w}×{job.h} px   RGBA")
        self.setWindowTitle(f"L805 DTF RIP Engine — [{job.name}]")
        self._refresh_ui()

    def _remove_job(self):
        row = self._queue.currentRow()
        if row < 0: return
        self._queue.takeItem(row)
        if 0 <= row < len(self._jobs): self._jobs.pop(row)
        for i in range(self._queue.count()):
            self._queue.item(i).setData(Qt.ItemDataRole.UserRole, i)
        self._cur_job = None
        self.preview._img = None; self.preview._show_empty()
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

    def _queue_ctx(self, pos):
        item = self._queue.itemAt(pos)
        if not item: return
        menu = QMenu(self)
        a1 = QAction("選取", self); a1.triggered.connect(lambda: self._queue.setCurrentItem(item)); menu.addAction(a1)
        a2 = QAction("移除", self); a2.triggered.connect(self._remove_job); menu.addAction(a2)
        menu.exec(self._queue.mapToGlobal(pos))

    def _current_config(self):
        dpi_map = {0:DPIMode.DPI_1440x1440, 1:DPIMode.DPI_5760x1440, 2:DPIMode.DPI_720x720}
        return RIPConfig(
            mode=self._current_mode,
            dpi=dpi_map.get(self._dpi_combo.currentIndex(), DPIMode.DPI_1440x1440),
            white_density=self._white_s.value()/100,
            alpha_threshold=self._alpha_s.value(),
            color_ink_limit=self._color_s.value()/100,
            choke_enabled=self._choke_cb.isChecked(),
            choke_pixels=self._choke_spin.value(),
            multipass=self._pass_spin.value(),
            error_diffusion_strength=self._diff_s.value()/100,
        )

    # ── One-click print ────────────────────────────────────────────────────

    def _print(self):
        if not self._cur_job: return
        self._btn_print.setEnabled(False)
        self._btn_cancel.setVisible(True)
        self._prog.setValue(0); self._prog.setVisible(True)
        self._prog_lbl.setVisible(True)
        self._log(f"═══ 列印: {self._cur_job.name} ═══")
        self._pipeline = PrintPipeline(self._cur_job.image, self._current_config(), self.printer)
        self._pipeline.progress.connect(self._on_progress)
        self._pipeline.log_msg.connect(self._log)
        self._pipeline.finished.connect(self._on_done)
        self._pipeline.start()

    def _cancel(self):
        if self._pipeline and self._pipeline.isRunning():
            self._pipeline.cancel()
            self._log("⚠ 取消中…")
            # Wait briefly for thread to stop
            QTimer.singleShot(500, self._reset_ui)
        else:
            self._reset_ui()

    def _on_progress(self, pct, msg):
        self._prog.setValue(pct)
        self._prog_lbl.setText(msg)
        self._sb.setText(msg)

    def _on_done(self, ok, msg):
        self._reset_ui()
        if ok:
            self._log(f"✓ {msg}")
            self._sb.setText(f"✓ {msg}")
            QMessageBox.information(self, "列印完成",
                f"{self._cur_job.name if self._cur_job else ''}\n已成功送出至印表機")
        else:
            self._log(f"{'⚠' if msg=='已取消' else '✗'} {msg}")
            if msg not in ("已取消",):
                QMessageBox.warning(self, "列印失敗", msg)

    def _reset_ui(self):
        self._btn_print.setEnabled(self._cur_job is not None)
        self._btn_cancel.setVisible(False)
        self._prog.setVisible(False)
        self._prog_lbl.setVisible(False)

    def _refresh_ui(self):
        self._btn_print.setEnabled(self._cur_job is not None)

    # ── Printer ────────────────────────────────────────────────────────────

    def _on_printer_status(self, s):
        self._printer_panel.update_status(s, self._device_info, self.printer._sim_mode)

    # ── Log ────────────────────────────────────────────────────────────────

    def _log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log_box.append(f"[{ts}] {msg}")
        self._log_box.verticalScrollBar().setValue(
            self._log_box.verticalScrollBar().maximum())

    def _save_log(self):
        p, _ = QFileDialog.getSaveFileName(self, "儲存日誌", "log.txt", "文字 (*.txt)")
        if p:
            with open(p, 'w', encoding='utf-8') as f:
                f.write(self._log_box.toPlainText())

    def _show_about(self):
        QMessageBox.about(self, "關於 L805 DTF RIP Engine",
            "Epson L805 DTF RIP Engine v1.0\n\n"
            "CMYKWW 六通道 · WinUSB 直通\n"
            "Floyd-Steinberg · VSDT · ESC/P-R\n\n"
            "RIP 資料完全在記憶體中處理，\n不寫入任何暫存檔案。\n\n"
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
