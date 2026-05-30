"""
Epson L805 DTF RIP Engine — Main GUI Application
PyQt6 Desktop Application
"""
import sys
import os
import threading
from pathlib import Path
from PIL import Image

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QSlider, QComboBox, QCheckBox,
    QGroupBox, QFileDialog, QProgressBar, QTextEdit, QSplitter,
    QFrame, QScrollArea, QSizePolicy, QStatusBar, QMessageBox,
    QTabWidget, QSpinBox, QDoubleSpinBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QColor, QFont, QPalette,
    QLinearGradient, QIcon, QBrush
)

# Import our engine modules
sys.path.insert(0, os.path.dirname(__file__))
from rip_engine import RIPCompiler, RIPConfig, PrintMode, DPIMode
from usb_comm import L805Printer, PrinterStatus


# ─── Worker Threads ────────────────────────────────────────────────────────

class RIPWorker(QThread):
    progress  = pyqtSignal(int, str)
    log_msg   = pyqtSignal(str)
    finished  = pyqtSignal(bytes)
    error     = pyqtSignal(str)

    def __init__(self, image: Image.Image, config: RIPConfig):
        super().__init__()
        self.image  = image
        self.config = config

    def run(self):
        try:
            compiler = RIPCompiler(
                self.config,
                progress_cb=lambda p, m: self.progress.emit(p, m),
                log_cb=lambda m: self.log_msg.emit(m)
            )
            data = compiler.compile(self.image)
            self.finished.emit(data)
        except Exception as e:
            self.error.emit(str(e))


class USBWorker(QThread):
    progress  = pyqtSignal(int, str)
    log_msg   = pyqtSignal(str)
    finished  = pyqtSignal(bool)

    def __init__(self, printer: L805Printer, data: bytes):
        super().__init__()
        self.printer = printer
        self.data    = data

    def run(self):
        ok = self.printer.send_data(
            self.data,
            progress_cb=lambda p, m: self.progress.emit(p, m)
        )
        self.finished.emit(ok)


# ─── Styles ────────────────────────────────────────────────────────────────

DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #1A1A1C;
    color: #E8E8EA;
    font-family: 'Segoe UI', 'Arial', sans-serif;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #2E2E32;
    border-radius: 8px;
    margin-top: 16px;
    padding: 12px 10px 10px 10px;
    background-color: #1E1E22;
}
QGroupBox::title {
    color: #888890;
    font-size: 11px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    subcontrol-origin: margin;
    left: 12px;
    top: -1px;
    padding: 0 6px;
    background-color: #1A1A1C;
}
QPushButton {
    background-color: #2A2A2E;
    color: #E8E8EA;
    border: 1px solid #3A3A3E;
    border-radius: 6px;
    padding: 7px 16px;
    font-size: 13px;
}
QPushButton:hover  { background-color: #35353A; border-color: #4A4A50; }
QPushButton:pressed { background-color: #202025; }
QPushButton:disabled { color: #444448; border-color: #2A2A2E; }

QPushButton#printBtn {
    background-color: #0A84FF;
    color: #FFFFFF;
    border: none;
    font-weight: 600;
    padding: 9px 24px;
    font-size: 14px;
    border-radius: 8px;
}
QPushButton#printBtn:hover   { background-color: #1A90FF; }
QPushButton#printBtn:disabled { background-color: #1A3A5C; color: #4A7AB0; }

QPushButton#connectBtn {
    background-color: #1E3A1E;
    color: #4CAF50;
    border: 1px solid #2E6030;
    border-radius: 6px;
}
QPushButton#connectBtn:hover { background-color: #244422; }

QSlider::groove:horizontal {
    height: 4px;
    background: #2E2E36;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #0A84FF;
    border: none;
    width: 16px; height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}
QSlider::sub-page:horizontal { background: #0A84FF; border-radius: 2px; }

QComboBox {
    background-color: #2A2A2E;
    border: 1px solid #3A3A3E;
    border-radius: 6px;
    padding: 5px 10px;
    color: #E8E8EA;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #252528;
    border: 1px solid #3A3A3E;
    selection-background-color: #0A84FF;
}

QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid #3A3A3E;
    background-color: #2A2A2E;
}
QCheckBox::indicator:checked {
    background-color: #0A84FF;
    border-color: #0A84FF;
    image: none;
}

QProgressBar {
    background-color: #2A2A2E;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    font-size: 11px;
    color: #888890;
}
QProgressBar::chunk {
    background-color: #0A84FF;
    border-radius: 4px;
}

QTextEdit {
    background-color: #131315;
    border: 1px solid #2A2A2E;
    border-radius: 6px;
    color: #00CC66;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 11px;
    padding: 6px;
}

QLabel#sectionTitle {
    font-size: 11px;
    color: #555560;
    letter-spacing: 1.5px;
    text-transform: uppercase;
}

QTabWidget::pane {
    border: 1px solid #2E2E32;
    border-radius: 8px;
    background-color: #1E1E22;
}
QTabBar::tab {
    background: #1A1A1C;
    color: #666670;
    padding: 8px 16px;
    border-radius: 6px 6px 0 0;
    border: 1px solid #2E2E32;
    border-bottom: none;
    margin-right: 2px;
}
QTabBar::tab:selected { background: #1E1E22; color: #E8E8EA; }
QTabBar::tab:hover    { color: #AAAABC; }

QScrollBar:vertical {
    background: #1A1A1C;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #3A3A3E;
    border-radius: 4px;
    min-height: 30px;
}
QStatusBar { background-color: #131315; color: #555560; font-size: 11px; }
QSplitter::handle { background: #2E2E32; width: 1px; }
"""


# ─── Channel Indicator Widget ─────────────────────────────────────────────

class ChannelBar(QWidget):
    CHANNELS = [
        ('C',  '#00B4D8', 'Cyan',       'CH0'),
        ('M',  '#E040FB', 'Magenta',    'CH1'),
        ('Y',  '#FFD600', 'Yellow',     'CH2'),
        ('K',  '#607D8B', 'Black',      'CH3'),
        ('W1', '#B0C4CE', '白墨 1',     'CH4'),
        ('W2', '#CFD8DC', '白墨 2',     'CH5'),
    ]
    MODE_ACTIVE = {
        PrintMode.CMYK_WHITE: {0,1,2,3,4,5},
        PrintMode.WHITE_CMYK: {0,1,2,3,4,5},
        PrintMode.CMYK_ONLY:  {0,1,2,3},
        PrintMode.WHITE_ONLY: {4,5},
    }

    def __init__(self):
        super().__init__()
        self.mode = PrintMode.CMYK_WHITE
        self.labels = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for i, (sym, color, name, ch) in enumerate(self.CHANNELS):
            card = QFrame()
            card.setFixedSize(72, 80)
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: #22222A;
                    border: 1px solid #333338;
                    border-radius: 8px;
                }}
            """)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(4, 8, 4, 8)
            cl.setSpacing(2)

            dot = QLabel()
            dot.setFixedSize(24, 24)
            dot.setStyleSheet(f"""
                background-color: {color};
                border-radius: 12px;
                border: 1px solid rgba(255,255,255,0.15);
            """)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)

            lbl_sym  = QLabel(sym)
            lbl_name = QLabel(name)
            lbl_ch   = QLabel(ch)
            lbl_sym.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_ch.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_sym.setStyleSheet("font-weight: 600; font-size: 13px;")
            lbl_name.setStyleSheet("font-size: 9px; color: #666670;")
            lbl_ch.setStyleSheet("font-size: 9px; color: #444450; font-family: monospace;")

            cl.addWidget(dot, alignment=Qt.AlignmentFlag.AlignHCenter)
            cl.addWidget(lbl_sym)
            cl.addWidget(lbl_name)
            cl.addWidget(lbl_ch)

            layout.addWidget(card)
            self.labels.append((card, dot, lbl_sym))

        self._update_active()

    def set_mode(self, mode: PrintMode):
        self.mode = mode
        self._update_active()

    def _update_active(self):
        active = self.MODE_ACTIVE.get(self.mode, set())
        colors = [c[1] for c in self.CHANNELS]
        for i, (card, dot, sym) in enumerate(self.labels):
            if i in active:
                card.setStyleSheet("""
                    QFrame {
                        background-color: #1E2A1E;
                        border: 1px solid #2E5030;
                        border-radius: 8px;
                    }
                """)
                dot.setStyleSheet(f"""
                    background-color: {colors[i]};
                    border-radius: 12px;
                    border: 1px solid rgba(255,255,255,0.2);
                """)
                sym.setStyleSheet("font-weight: 600; font-size: 13px; color: #E8E8EA;")
            else:
                card.setStyleSheet("""
                    QFrame {
                        background-color: #1A1A1C;
                        border: 1px solid #222226;
                        border-radius: 8px;
                        opacity: 0.3;
                    }
                """)
                dot.setStyleSheet(f"""
                    background-color: {colors[i]};
                    border-radius: 12px;
                    opacity: 0.2;
                """)
                sym.setStyleSheet("font-weight: 600; font-size: 13px; color: #444448;")


# ─── Preview Widget ────────────────────────────────────────────────────────

class PreviewWidget(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(320, 240)
        self.setStyleSheet("""
            background-color: #131315;
            border: 1px solid #2E2E32;
            border-radius: 8px;
        """)
        self.setText("尚未載入影像\n請點擊「開啟影像」")
        self.setStyleSheet(self.styleSheet() + "color: #444450;")
        self._original: Image.Image = None

    def load_image(self, img: Image.Image):
        self._original = img
        self._refresh()

    def _refresh(self):
        if self._original is None:
            return
        img = self._original.convert('RGBA')
        # Checkerboard for transparency
        w, h = img.size
        checker = Image.new('RGBA', (w, h), (40, 40, 44, 255))
        tile = 12
        for y in range(0, h, tile):
            for x in range(0, w, tile):
                if (x // tile + y // tile) % 2 == 0:
                    for py in range(y, min(y+tile, h)):
                        for px in range(x, min(x+tile, w)):
                            checker.putpixel((px, py), (50, 50, 55, 255))
        from PIL import ImageChops
        checker.paste(img, mask=img.split()[3])
        # Scale to fit
        max_w, max_h = 480, 360
        img.thumbnail((max_w, max_h), Image.LANCZOS)
        checker.thumbnail((max_w, max_h), Image.LANCZOS)
        qimg = self._pil_to_qimage(checker)
        self.setPixmap(QPixmap.fromImage(qimg))

    @staticmethod
    def _pil_to_qimage(pil_img: Image.Image) -> QImage:
        pil_img = pil_img.convert('RGBA')
        data = pil_img.tobytes('raw', 'RGBA')
        return QImage(data, pil_img.width, pil_img.height,
                      QImage.Format.Format_RGBA8888)


# ─── Main Window ───────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Epson L805 DTF RIP Engine")
        self.setMinimumSize(1100, 780)
        self.resize(1200, 860)

        self._image: Image.Image = None
        self._rip_data: bytes = None
        self._rip_worker: RIPWorker = None
        self._usb_worker: USBWorker = None
        self.printer = L805Printer(
            log_cb=self._append_log,
            status_cb=self._on_printer_status
        )

        self._build_ui()
        self.setStyleSheet(DARK_STYLE)
        self._update_ui_state()

        # Auto-scan USB on start
        QTimer.singleShot(500, self._connect_printer)

    # ── UI Construction ───────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        root.addWidget(self._build_topbar())

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setContentsMargins(12, 8, 12, 8)

        # Left panel
        left = QWidget()
        left.setFixedWidth(280)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(10)
        left_layout.addWidget(self._build_mode_panel())
        left_layout.addWidget(self._build_resolution_panel())
        left_layout.addWidget(self._build_paper_panel())
        left_layout.addStretch()
        left_layout.addWidget(self._build_connect_panel())

        # Right panel
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        # Channel bar
        ch_group = QGroupBox("通道映射矩陣  CHANNEL MAPPING")
        ch_layout = QHBoxLayout(ch_group)
        self.channel_bar = ChannelBar()
        ch_layout.addWidget(self.channel_bar)
        right_layout.addWidget(ch_group)

        # Tabs
        tabs = QTabWidget()
        tabs.addTab(self._build_image_tab(),    "影像 / 預覽")
        tabs.addTab(self._build_ink_tab(),       "墨水 / 白墨設定")
        tabs.addTab(self._build_halftone_tab(),  "半色調加網")
        tabs.addTab(self._build_log_tab(),       "ESC/P-R 日誌")
        right_layout.addWidget(tabs, 1)

        # Bottom action bar
        right_layout.addWidget(self._build_action_bar())

        splitter.addWidget(left)
        splitter.addWidget(right)
        root.addWidget(splitter, 1)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("待機中 · 請連接 Epson L805 USB")

    def _build_topbar(self):
        bar = QFrame()
        bar.setFixedHeight(46)
        bar.setStyleSheet("""
            QFrame {
                background-color: #131315;
                border-bottom: 1px solid #2A2A2E;
            }
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)

        badge = QLabel("RIP ENGINE")
        badge.setStyleSheet("""
            background-color: #0A84FF;
            color: white;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 2px;
            padding: 2px 8px;
            border-radius: 4px;
        """)
        title = QLabel("Epson L805  DTF CMYKWW")
        title.setStyleSheet("font-size: 14px; font-weight: 600; color: #E8E8EA; margin-left: 10px;")

        self.printer_status_lbl = QLabel("● 未連接")
        self.printer_status_lbl.setStyleSheet("color: #FF453A; font-size: 12px; margin-left: auto;")

        layout.addWidget(badge)
        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(self.printer_status_lbl)
        return bar

    def _build_mode_panel(self):
        group = QGroupBox("噴印模式  PRINT MODE")
        layout = QVBoxLayout(group)
        layout.setSpacing(4)

        modes = [
            (PrintMode.CMYK_WHITE, "模式 1 · 彩色 ＋ 白墨",  "標準 DTF — 彩先噴，白覆蓋"),
            (PrintMode.WHITE_CMYK, "模式 2 · 白墨 ＋ 彩色",  "燈箱/打樣 — 白先噴"),
            (PrintMode.CMYK_ONLY,  "模式 3 · 僅彩色 CMYK",   "無白墨底層"),
            (PrintMode.WHITE_ONLY, "模式 4 · 僅白墨",         "純白圖案/矽膠熱轉"),
        ]
        self._mode_btns = []
        for mode, label, sublabel in modes:
            btn = QPushButton()
            btn.setCheckable(True)
            btn_layout = QVBoxLayout()
            btn_layout.setContentsMargins(10, 6, 10, 6)
            btn_layout.setSpacing(2)
            top = QLabel(label)
            top.setStyleSheet("font-weight: 600; font-size: 12px;")
            sub = QLabel(sublabel)
            sub.setStyleSheet("font-size: 10px; color: #666670;")
            btn_layout.addWidget(top)
            btn_layout.addWidget(sub)
            w = QWidget()
            w.setLayout(btn_layout)

            frame = QFrame()
            frame.setFixedHeight(56)
            frame.setStyleSheet("""
                QFrame {
                    background-color: #22222A;
                    border: 1px solid #333338;
                    border-radius: 8px;
                }
                QFrame:hover { border-color: #4A4A50; background-color: #25252D; }
            """)
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(10, 6, 10, 6)
            fl.setSpacing(2)
            t = QLabel(label)
            t.setStyleSheet("font-weight: 600; font-size: 12px; color: #E8E8EA;")
            s = QLabel(sublabel)
            s.setStyleSheet("font-size: 10px; color: #666670;")
            fl.addWidget(t)
            fl.addWidget(s)
            frame.mousePressEvent = lambda e, m=mode, f=frame: self._select_mode(m)
            frame._mode = mode
            layout.addWidget(frame)
            self._mode_btns.append(frame)

        return group

    def _select_mode(self, mode: PrintMode):
        for frame in self._mode_btns:
            if frame._mode == mode:
                frame.setStyleSheet("""
                    QFrame {
                        background-color: #0A2A50;
                        border: 1px solid #0A84FF;
                        border-radius: 8px;
                    }
                """)
            else:
                frame.setStyleSheet("""
                    QFrame {
                        background-color: #22222A;
                        border: 1px solid #333338;
                        border-radius: 8px;
                    }
                    QFrame:hover { border-color: #4A4A50; }
                """)
        self._current_mode = mode
        self.channel_bar.set_mode(mode)
        self._update_mode_label()

    def _build_resolution_panel(self):
        group = QGroupBox("解析度  DPI")
        layout = QVBoxLayout(group)
        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems([
            "1440 × 1440 DPI（標準）",
            "5760 × 1440 DPI（最高品質）",
            "720 × 720 DPI（草稿）",
        ])
        layout.addWidget(self.dpi_combo)

        row = QHBoxLayout()
        row.addWidget(QLabel("Multi-pass:"))
        self.pass_spin = QSpinBox()
        self.pass_spin.setRange(1, 8)
        self.pass_spin.setValue(4)
        self.pass_spin.setSuffix(" pass")
        self.pass_spin.setStyleSheet("""
            QSpinBox {
                background-color: #2A2A2E;
                border: 1px solid #3A3A3E;
                border-radius: 6px;
                padding: 4px 8px;
                color: #E8E8EA;
            }
        """)
        row.addWidget(self.pass_spin)
        layout.addLayout(row)
        return group

    def _build_paper_panel(self):
        group = QGroupBox("紙張尺寸  PAPER SIZE")
        layout = QVBoxLayout(group)
        self.paper_combo = QComboBox()
        self.paper_combo.addItems([
            "A4  (210 × 297 mm)",
            "A5  (148 × 210 mm)",
            "A6  (105 × 148 mm)",
        ])
        layout.addWidget(self.paper_combo)
        return group

    def _build_connect_panel(self):
        group = QGroupBox("印表機連線")
        layout = QVBoxLayout(group)
        self.connect_btn = QPushButton("🔌  掃描 USB 印表機")
        self.connect_btn.setObjectName("connectBtn")
        self.connect_btn.clicked.connect(self._connect_printer)
        layout.addWidget(self.connect_btn)

        self.printer_info = QLabel("未連接")
        self.printer_info.setStyleSheet("font-size: 10px; color: #555560; line-height: 1.6;")
        self.printer_info.setWordWrap(True)
        layout.addWidget(self.printer_info)
        return group

    def _build_image_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        # Open button
        btn_row = QHBoxLayout()
        open_btn = QPushButton("📂  開啟影像 (PNG / TIFF + Alpha)")
        open_btn.clicked.connect(self._open_image)
        btn_row.addWidget(open_btn)
        self.img_info_lbl = QLabel("—")
        self.img_info_lbl.setStyleSheet("font-size: 11px; color: #666670; font-family: monospace;")
        btn_row.addWidget(self.img_info_lbl)
        layout.addLayout(btn_row)

        # Preview
        self.preview = PreviewWidget()
        layout.addWidget(self.preview, 1)
        return w

    def _build_ink_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(14)

        # White ink
        wg = QGroupBox("白墨通道設定  WHITE INK")
        wl = QGridLayout(wg)

        wl.addWidget(QLabel("白墨濃度"), 0, 0)
        self.white_slider = QSlider(Qt.Orientation.Horizontal)
        self.white_slider.setRange(0, 100)
        self.white_slider.setValue(90)
        self.white_val = QLabel("90%")
        self.white_val.setFixedWidth(40)
        self.white_slider.valueChanged.connect(
            lambda v: self.white_val.setText(f"{v}%"))
        wl.addWidget(self.white_slider, 0, 1)
        wl.addWidget(self.white_val, 0, 2)

        wl.addWidget(QLabel("Alpha 閾值"), 1, 0)
        self.alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self.alpha_slider.setRange(0, 30)
        self.alpha_slider.setValue(5)
        self.alpha_val = QLabel("5")
        self.alpha_val.setFixedWidth(40)
        self.alpha_slider.valueChanged.connect(
            lambda v: self.alpha_val.setText(str(v)))
        wl.addWidget(self.alpha_slider, 1, 1)
        wl.addWidget(self.alpha_val, 1, 2)

        # Choke
        choke_row = QHBoxLayout()
        self.choke_cb = QCheckBox("啟用白墨收邊腐蝕  W_choked = W ⊖ K")
        self.choke_cb.setChecked(True)
        choke_row.addWidget(self.choke_cb)
        choke_row.addWidget(QLabel("收縮"))
        self.choke_spin = QSpinBox()
        self.choke_spin.setRange(1, 5)
        self.choke_spin.setValue(2)
        self.choke_spin.setSuffix(" px")
        self.choke_spin.setFixedWidth(70)
        self.choke_spin.setStyleSheet("""
            QSpinBox {
                background-color: #2A2A2E; border: 1px solid #3A3A3E;
                border-radius: 6px; padding: 4px 8px; color: #E8E8EA;
            }
        """)
        choke_row.addWidget(self.choke_spin)
        wl.addLayout(choke_row, 2, 0, 1, 3)
        layout.addWidget(wg)

        # Color ink
        cg = QGroupBox("彩色墨量設定  COLOR INK")
        cl = QGridLayout(cg)
        cl.addWidget(QLabel("彩色最大墨量"), 0, 0)
        self.color_ink_slider = QSlider(Qt.Orientation.Horizontal)
        self.color_ink_slider.setRange(50, 100)
        self.color_ink_slider.setValue(85)
        self.color_ink_val = QLabel("85%")
        self.color_ink_val.setFixedWidth(40)
        self.color_ink_slider.valueChanged.connect(
            lambda v: self.color_ink_val.setText(f"{v}%"))
        cl.addWidget(self.color_ink_slider, 0, 1)
        cl.addWidget(self.color_ink_val, 0, 2)
        layout.addWidget(cg)

        layout.addStretch()
        return w

    def _build_halftone_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        info = QLabel(
            "採用修正型 Floyd-Steinberg 誤差擴散演算法\n"
            "將 8-bit 密度值 (0–255) 轉化為 2-bit 墨滴決策 {00,01,10,11}\n"
            "對應 L805 VSDT：0 pl / 1.5 pl / 3.0 pl / 4.5 pl"
        )
        info.setStyleSheet("color: #666670; font-size: 12px; line-height: 1.8;")
        layout.addWidget(info)

        algo_group = QGroupBox("加網參數")
        al = QGridLayout(algo_group)

        al.addWidget(QLabel("誤差擴散強度"), 0, 0)
        self.diff_slider = QSlider(Qt.Orientation.Horizontal)
        self.diff_slider.setRange(50, 100)
        self.diff_slider.setValue(100)
        self.diff_val = QLabel("100%")
        self.diff_val.setFixedWidth(40)
        self.diff_slider.valueChanged.connect(
            lambda v: self.diff_val.setText(f"{v}%"))
        al.addWidget(self.diff_slider, 0, 1)
        al.addWidget(self.diff_val, 0, 2)

        # Diffusion matrix display
        matrix_lbl = QLabel(
            "誤差傳播矩陣:\n"
            "            [ X  ] [ 7/16 ]\n"
            "  [ 3/16 ] [ 5/16 ] [ 1/16 ]"
        )
        matrix_lbl.setStyleSheet(
            "font-family: 'Cascadia Code', 'Consolas', monospace;"
            "font-size: 12px; color: #00CC66;"
            "background: #131315; padding: 12px; border-radius: 6px;"
        )
        al.addWidget(matrix_lbl, 1, 0, 1, 3)
        layout.addWidget(algo_group)

        droplet_group = QGroupBox("多階微滴 (VSDT)  Droplet Size")
        dl = QGridLayout(droplet_group)
        droplets = [
            ("00", "不噴墨",   "0 pl",    "#333338"),
            ("01", "小墨滴",   "~1.5 pl", "#0A3A5A"),
            ("10", "中墨滴",   "~3.0 pl", "#0A4A6A"),
            ("11", "大墨滴 ★", "~4.5 pl (白墨核心)", "#0A2A4A"),
        ]
        for i, (code, name, size, bg) in enumerate(droplets):
            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {bg};
                    border: 1px solid #3A3A3E;
                    border-radius: 6px;
                }}
            """)
            cl2 = QHBoxLayout(card)
            cl2.setContentsMargins(10, 8, 10, 8)
            code_lbl = QLabel(code)
            code_lbl.setStyleSheet("font-family: monospace; font-size: 16px; font-weight: 700; color: #0A84FF; min-width: 30px;")
            name_lbl = QLabel(f"{name}\n{size}")
            name_lbl.setStyleSheet("font-size: 11px; color: #AAAABC; line-height: 1.5;")
            cl2.addWidget(code_lbl)
            cl2.addWidget(name_lbl)
            cl2.addStretch()
            row, col = i // 2, i % 2
            dl.addWidget(card, row, col)

        layout.addWidget(droplet_group)
        layout.addStretch()
        return w

    def _build_log_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("ESC/P-R 編譯日誌將顯示於此...")
        layout.addWidget(self.log_box)
        btn_row = QHBoxLayout()
        clear_btn = QPushButton("清除日誌")
        clear_btn.clicked.connect(self.log_box.clear)
        save_btn = QPushButton("儲存日誌...")
        save_btn.clicked.connect(self._save_log)
        save_rip_btn = QPushButton("儲存 ESC/P-R 二進位...")
        save_rip_btn.clicked.connect(self._save_rip_data)
        btn_row.addWidget(clear_btn)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(save_rip_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return w

    def _build_action_bar(self):
        bar = QFrame()
        bar.setStyleSheet("""
            QFrame {
                background-color: #131315;
                border-top: 1px solid #2A2A2E;
                border-radius: 0px;
            }
        """)
        bar.setFixedHeight(64)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)

        self.mode_label = QLabel("模式 1 · 彩色 ＋ 白墨")
        self.mode_label.setStyleSheet("font-size: 12px; color: #666670;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(240)
        self.progress_bar.setVisible(False)

        self.progress_lbl = QLabel("")
        self.progress_lbl.setStyleSheet("font-size: 11px; color: #666670; font-family: monospace;")
        self.progress_lbl.setVisible(False)

        self.rip_btn = QPushButton("▶  編譯 ESC/P-R")
        self.rip_btn.setFixedHeight(42)
        self.rip_btn.clicked.connect(self._start_rip)
        self.rip_btn.setStyleSheet("""
            QPushButton {
                background-color: #1E3A1E;
                color: #4CAF50;
                border: 1px solid #2E6030;
                border-radius: 8px;
                font-size: 13px;
                font-weight: 600;
                padding: 0 20px;
            }
            QPushButton:hover { background-color: #244422; }
            QPushButton:disabled { color: #2E5030; border-color: #1E3020; }
        """)

        self.print_btn = QPushButton("🖨  噴印")
        self.print_btn.setObjectName("printBtn")
        self.print_btn.setFixedHeight(42)
        self.print_btn.clicked.connect(self._start_print)
        self.print_btn.setEnabled(False)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedHeight(42)
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setEnabled(False)

        layout.addWidget(self.mode_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_lbl)
        layout.addStretch()
        layout.addWidget(self.rip_btn)
        layout.addWidget(self.print_btn)
        layout.addWidget(self.cancel_btn)
        return bar

    # ── Helpers / State ──────────────────────────────────────────────────

    def _current_config(self) -> RIPConfig:
        dpi_map = {0: DPIMode.DPI_1440x1440, 1: DPIMode.DPI_5760x1440, 2: DPIMode.DPI_720x720}
        return RIPConfig(
            mode=getattr(self, '_current_mode', PrintMode.CMYK_WHITE),
            dpi=dpi_map.get(self.dpi_combo.currentIndex(), DPIMode.DPI_1440x1440),
            white_density=self.white_slider.value() / 100.0,
            alpha_threshold=self.alpha_slider.value(),
            color_ink_limit=self.color_ink_slider.value() / 100.0,
            choke_enabled=self.choke_cb.isChecked(),
            choke_pixels=self.choke_spin.value(),
            multipass=self.pass_spin.value(),
            error_diffusion_strength=self.diff_slider.value() / 100.0,
        )

    def _update_mode_label(self):
        labels = {
            PrintMode.CMYK_WHITE: "模式 1 · 彩色 ＋ 白墨",
            PrintMode.WHITE_CMYK: "模式 2 · 白墨 ＋ 彩色",
            PrintMode.CMYK_ONLY:  "模式 3 · 僅彩色",
            PrintMode.WHITE_ONLY: "模式 4 · 僅白墨",
        }
        mode = getattr(self, '_current_mode', PrintMode.CMYK_WHITE)
        self.mode_label.setText(labels.get(mode, ""))

    def _update_ui_state(self):
        has_img = self._image is not None
        has_rip = self._rip_data is not None
        self.rip_btn.setEnabled(has_img)
        self.print_btn.setEnabled(has_rip)
        # Select default mode
        if not hasattr(self, '_current_mode'):
            self._current_mode = PrintMode.CMYK_WHITE
            self._select_mode(PrintMode.CMYK_WHITE)

    def _append_log(self, msg: str):
        self.log_box.append(f"[{self._timestamp()}] {msg}")
        self.log_box.verticalScrollBar().setValue(
            self.log_box.verticalScrollBar().maximum())

    def _timestamp(self):
        import datetime
        return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _on_printer_status(self, status: str):
        color = {
            PrinterStatus.READY:      "#4CAF50",
            PrinterStatus.PRINTING:   "#FF9800",
            PrinterStatus.ERROR:      "#FF453A",
            PrinterStatus.DISCONNECTED: "#FF453A",
            PrinterStatus.BUSY:       "#FF9800",
        }.get(status, "#666670")
        self.printer_status_lbl.setText(f"● {status}")
        self.printer_status_lbl.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.status_bar.showMessage(f"印表機狀態: {status}")

    def _on_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.progress_lbl.setText(msg)
        self.status_bar.showMessage(msg)

    # ── Actions ──────────────────────────────────────────────────────────

    def _connect_printer(self):
        self._append_log("掃描 USB 裝置...")
        ok = self.printer.find_printer()
        if ok:
            self.printer_info.setText(
                f"✓ 連接成功\n"
                f"Epson L805 DTF\n"
                f"{'模擬模式' if self.printer._sim_mode else 'USB 直連'}"
            )
            self._append_log("印表機就緒")
        else:
            self.printer_info.setText(
                "❌ 未找到印表機\n"
                "請確認:\n"
                "1. USB 線連接\n"
                "2. 已安裝 WinUSB 驅動\n"
                "3. 印表機已開機"
            )

    def _open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "開啟影像",
            "", "影像檔案 (*.png *.tif *.tiff *.bmp *.jpg *.jpeg)"
        )
        if not path:
            return
        try:
            img = Image.open(path)
            if img.mode not in ('RGBA', 'RGB'):
                img = img.convert('RGBA')
            self._image = img
            self._rip_data = None
            self.print_btn.setEnabled(False)
            w, h = img.size
            mode = img.mode
            self.img_info_lbl.setText(f"{Path(path).name}  |  {w}×{h} px  |  {mode}")
            self.preview.load_image(img)
            self._update_ui_state()
            self._append_log(f"載入影像: {path} ({w}×{h}, {mode})")
        except Exception as e:
            QMessageBox.critical(self, "影像載入失敗", str(e))

    def _start_rip(self):
        if self._image is None:
            return
        self.rip_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_lbl.setVisible(True)
        self._rip_data = None
        self.print_btn.setEnabled(False)
        self._append_log("=== 開始 RIP 編譯 ===")

        cfg = self._current_config()
        self._rip_worker = RIPWorker(self._image, cfg)
        self._rip_worker.progress.connect(self._on_progress)
        self._rip_worker.log_msg.connect(self._append_log)
        self._rip_worker.finished.connect(self._on_rip_done)
        self._rip_worker.error.connect(self._on_rip_error)
        self._rip_worker.start()

    def _on_rip_done(self, data: bytes):
        self._rip_data = data
        self.progress_bar.setValue(100)
        self.rip_btn.setEnabled(True)
        self.print_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._append_log(f"=== RIP 完成: {len(data):,} bytes ===")
        self.status_bar.showMessage(f"ESC/P-R 編譯完成 — {len(data)/1024:.1f} KB — 可以噴印")

    def _on_rip_error(self, err: str):
        self.rip_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self._append_log(f"❌ RIP 錯誤: {err}")
        QMessageBox.critical(self, "RIP 編譯失敗", err)

    def _start_print(self):
        if not self._rip_data:
            return
        self.print_btn.setEnabled(False)
        self.rip_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._append_log("=== 開始傳輸至印表機 ===")

        self._usb_worker = USBWorker(self.printer, self._rip_data)
        self._usb_worker.progress.connect(self._on_progress)
        self._usb_worker.log_msg.connect(self._append_log)
        self._usb_worker.finished.connect(self._on_print_done)
        self._usb_worker.start()

    def _on_print_done(self, ok: bool):
        self.print_btn.setEnabled(True)
        self.rip_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_lbl.setVisible(False)
        if ok:
            self._append_log("=== 噴印完成 ===")
            QMessageBox.information(self, "噴印完成", "影像已成功傳送至 Epson L805")
        else:
            self._append_log("❌ 噴印失敗")

    def _cancel(self):
        if self._rip_worker and self._rip_worker.isRunning():
            self._rip_worker.terminate()
        if self._usb_worker and self._usb_worker.isRunning():
            self.printer.cancel()
        self.cancel_btn.setEnabled(False)
        self.rip_btn.setEnabled(self._image is not None)
        self.print_btn.setEnabled(self._rip_data is not None)
        self.progress_bar.setVisible(False)
        self.progress_lbl.setVisible(False)
        self._append_log("⚠ 操作已取消")

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "儲存日誌", "rip_log.txt", "文字檔 (*.txt)")
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.log_box.toPlainText())

    def _save_rip_data(self):
        if not self._rip_data:
            QMessageBox.warning(self, "尚無資料", "請先執行 RIP 編譯")
            return
        path, _ = QFileDialog.getSaveFileName(self, "儲存 ESC/P-R 資料", "output.prn", "PRN 檔 (*.prn);;所有檔案 (*)")
        if path:
            with open(path, 'wb') as f:
                f.write(self._rip_data)
            self._append_log(f"已儲存: {path}")


# ─── Entry Point ───────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("L805 DTF RIP Engine")
    app.setOrganizationName("DTF Studio")

    # High DPI (AA_UseHighDpiPixmaps removed in PyQt6, handled automatically)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
