"""
Epson L805 DTF RIP Engine - Core Processing Module
ESC/P-R Raster command compiler with VSDT droplet control
"""
import numpy as np
from PIL import Image
import struct
import time
from dataclasses import dataclass
from typing import Optional, Callable
from enum import IntEnum


class PrintMode(IntEnum):
    CMYK_WHITE = 1   # Standard DTF: CMYK first, white on top
    WHITE_CMYK = 2   # Lightbox: white first, CMYK on top
    CMYK_ONLY  = 3   # No white channels
    WHITE_ONLY = 4   # Pure white output


class DPIMode(IntEnum):
    DPI_720x720   = 720
    DPI_1440x1440 = 1440
    DPI_5760x1440 = 5760


@dataclass
class RIPConfig:
    mode: PrintMode = PrintMode.CMYK_WHITE
    dpi: DPIMode = DPIMode.DPI_1440x1440
    white_density: float = 0.90       # 0.0 - 1.0
    alpha_threshold: int = 5          # 0 - 30
    color_ink_limit: float = 0.85     # 0.0 - 1.0
    choke_enabled: bool = True
    choke_pixels: int = 2             # 1 - 3
    multipass: int = 4                # 1 - 8
    error_diffusion_strength: float = 1.0


# ─── ESC/P-R Command Definitions ───────────────────────────────────────────

ESC = b'\x1B'
FF  = b'\x0C'

def escp_init():
    """ESC @ — Initialize printer"""
    return ESC + b'@'

def escp_remote1():
    """Enter remote mode"""
    return ESC + b'(R' + struct.pack('<H', 8) + b'\x00REMOTE1'

def escp_set_units(unit_720=1):
    """ESC ( U — Set unit"""
    return ESC + b'(U' + struct.pack('<HBB', 1, 0, unit_720)

def escp_set_page_length(length_units: int):
    """ESC ( C — Set page length"""
    return ESC + b'(C' + struct.pack('<HH', 2, length_units)

def escp_set_margins(top: int, bottom: int):
    """ESC ( c — Set top/bottom margins"""
    return ESC + b'(c' + struct.pack('<HHH', 4, top, bottom)

def escp_move_vertical(lines: int):
    """ESC ( V — Absolute vertical position"""
    return ESC + b'(V' + struct.pack('<HH', 2, lines)

def escp_select_graphics_mode():
    """ESC ( G — Select graphics mode"""
    return ESC + b'(G' + struct.pack('<HB', 1, 1)

def escp_set_resolution(hdpi: int, vdpi: int):
    """ESC ( D — Set resolution"""
    base = 3600
    h_unit = base // hdpi
    v_unit = base // vdpi
    return ESC + b'(D' + struct.pack('<HBBB', 3, base // 360, v_unit, h_unit)

def escp_raster_data(channel: int, color_id: int, width_px: int,
                     data_2bit: np.ndarray) -> bytes:
    """
    ESC . — Compressed raster data for one channel/color
    2-bit per pixel: 00=no drop, 01=small(1.5pl), 10=med(3pl), 11=large(4.5pl)
    Packed into bytes MSB first.
    """
    # Pack 2-bit values into bytes (4 pixels per byte)
    n_bytes = (width_px + 3) // 4
    packed = np.zeros(n_bytes, dtype=np.uint8)
    for i in range(min(len(data_2bit), width_px)):
        byte_idx = i // 4
        bit_pos  = 6 - (i % 4) * 2
        packed[byte_idx] |= (int(data_2bit[i]) & 0x03) << bit_pos

    # ESC . compression=0 (raw), v-res, h-res, nozzles, width(little-endian)
    header = ESC + b'.' + bytes([0, 180, 180, 1]) + struct.pack('<H', width_px)
    return header + packed.tobytes()

def escp_form_feed():
    return FF

def escp_end():
    return ESC + b'@'


# ─── Floyd-Steinberg Error Diffusion ───────────────────────────────────────

def floyd_steinberg_2bit(channel_8bit: np.ndarray,
                         strength: float = 1.0,
                         ink_limit: float = 1.0) -> np.ndarray:
    """
    Convert 8-bit density map → 2-bit droplet decision map.
    Returns array of same shape with values in {0,1,2,3}.
    """
    h, w = channel_8bit.shape
    buf = channel_8bit.astype(np.float32) * ink_limit
    out = np.zeros((h, w), dtype=np.uint8)

    # Thresholds for 2-bit: 0→0, 1→85, 2→170, 3→255
    thresholds = np.array([0, 64, 128, 192, 256], dtype=np.float32)
    levels     = np.array([0, 85, 170, 255],       dtype=np.float32)

    for y in range(h):
        left_to_right = (y % 2 == 0)
        xs = range(w) if left_to_right else range(w-1, -1, -1)
        for x in xs:
            old_val = np.clip(buf[y, x], 0, 255)
            # Quantize to nearest 2-bit level
            idx = np.searchsorted(thresholds[1:], old_val)
            idx = int(np.clip(idx, 0, 3))
            out[y, x] = idx
            quant_err = (old_val - levels[idx]) * strength

            # Serpentine diffusion
            if left_to_right:
                if x + 1 < w:
                    buf[y,     x+1] += quant_err * 7/16
                if y + 1 < h:
                    if x - 1 >= 0:
                        buf[y+1, x-1] += quant_err * 3/16
                    buf[y+1, x]     += quant_err * 5/16
                    if x + 1 < w:
                        buf[y+1, x+1] += quant_err * 1/16
            else:
                if x - 1 >= 0:
                    buf[y,     x-1] += quant_err * 7/16
                if y + 1 < h:
                    if x + 1 < w:
                        buf[y+1, x+1] += quant_err * 3/16
                    buf[y+1, x]     += quant_err * 5/16
                    if x - 1 >= 0:
                        buf[y+1, x-1] += quant_err * 1/16
    return out


# ─── Morphological Erosion (Choke) ─────────────────────────────────────────

def morphological_erosion(mask: np.ndarray, radius: int) -> np.ndarray:
    """
    Binary erosion: W_choked = W ⊖ K_choke
    Shrinks white ink boundary inward by `radius` pixels.
    """
    from PIL import ImageFilter, ImageOps
    img = Image.fromarray((mask * 255).astype(np.uint8), mode='L')
    for _ in range(radius):
        img = img.filter(ImageFilter.MinFilter(3))
    return np.array(img).astype(np.float32) / 255.0


# ─── Channel Splitter ──────────────────────────────────────────────────────

def split_rgba_to_channels(rgba_image: Image.Image,
                            config: RIPConfig) -> dict:
    """
    Decompose RGBA image into 6 DTF channels:
    Returns dict with keys: C, M, Y, K, W1, W2
    Each value is a numpy float32 array [0,1] of shape (H, W)
    """
    img = rgba_image.convert('RGBA')
    arr = np.array(img).astype(np.float32) / 255.0
    R, G, B, A = arr[:,:,0], arr[:,:,1], arr[:,:,2], arr[:,:,3]

    # Simple RGB → CMY (subtractive)
    C_raw = 1.0 - R
    M_raw = 1.0 - G
    Y_raw = 1.0 - B

    # Under-color removal → K extraction
    K_raw = np.minimum(np.minimum(C_raw, M_raw), Y_raw) * 0.85
    C = np.clip(C_raw - K_raw, 0, 1)
    M = np.clip(M_raw - K_raw, 0, 1)
    Y = np.clip(Y_raw - K_raw, 0, 1)
    K = K_raw

    # White channel from alpha
    alpha_thresh = config.alpha_threshold / 255.0
    white_mask = (A > alpha_thresh).astype(np.float32) * A * config.white_density

    # Choke erosion
    if config.choke_enabled and config.choke_pixels > 0:
        binary_mask = (A > alpha_thresh).astype(np.float32)
        choked = morphological_erosion(binary_mask, config.choke_pixels)
        white_mask = choked * A * config.white_density

    # Split white equally between W1 and W2
    W1 = white_mask * 0.5 + white_mask * 0.5  # = white_mask (equal split)
    W2 = white_mask.copy()

    return {'C': C, 'M': M, 'Y': Y, 'K': K, 'W1': W1, 'W2': W2}


# ─── Main RIP Compiler ─────────────────────────────────────────────────────

class RIPCompiler:
    """
    Compiles RGBA image → ESC/P-R binary stream for Epson L805 DTF
    """

    # L805 channel order: C=0, M=1, Y=2, K=3, W1=4(LtC), W2=5(LtM)
    CHANNEL_COLOR_IDS = {
        'C':  0x02,  # Cyan
        'M':  0x01,  # Magenta
        'Y':  0x04,  # Yellow
        'K':  0x00,  # Black
        'W1': 0x10,  # Light Cyan → W1
        'W2': 0x11,  # Light Magenta → W2
    }

    def __init__(self, config: RIPConfig,
                 progress_cb: Optional[Callable] = None,
                 log_cb: Optional[Callable] = None):
        self.config = config
        self.progress_cb = progress_cb or (lambda p, msg: None)
        self.log_cb = log_cb or (lambda msg: None)

    def _log(self, msg):
        self.log_cb(msg)

    def _progress(self, pct, msg):
        self.progress_cb(pct, msg)

    def compile(self, rgba_image: Image.Image) -> bytes:
        cfg = self.config
        w, h = rgba_image.size
        self._log(f"影像尺寸: {w}x{h} px")
        self._progress(3, "讀取 RGBA 點陣圖...")

        # ── Step 1: Channel splitting
        self._progress(10, "ICC Profile 轉換 → CMYK + Alpha 提取...")
        channels = split_rgba_to_channels(rgba_image, cfg)
        self._log("通道解構完成: C/M/Y/K/W1/W2")

        # ── Step 2: Ink limit
        ink_limit = cfg.color_ink_limit
        for ch in ['C','M','Y','K']:
            channels[ch] = np.clip(channels[ch] * ink_limit, 0, 1)

        # ── Step 3: Error diffusion → 2-bit per channel
        self._progress(30, "Floyd-Steinberg 誤差擴散加網...")
        dithered = {}
        channel_order = self._get_channel_order()
        for i, ch in enumerate(channels.keys()):
            pct = 30 + int(i * 25 / 6)
            self._progress(pct, f"加網處理 {ch} 通道...")
            density_8bit = (channels[ch] * 255).astype(np.float32)
            # For white channels use large droplets (11) where active
            if ch in ('W1', 'W2'):
                # White uses large droplets for coverage
                mask = (channels[ch] > 0.1).astype(np.uint8)
                dithered[ch] = mask * 3  # Force 11 (large drop) for white
            else:
                dithered[ch] = floyd_steinberg_2bit(
                    density_8bit, cfg.error_diffusion_strength, 1.0)

        self._progress(58, "編譯 ESC/P-R 指令流...")

        # ── Step 4: Build ESC/P-R stream
        buf = bytearray()

        # Header
        buf += escp_init()
        buf += escp_remote1()
        buf += escp_select_graphics_mode()
        buf += escp_set_units(1)

        hdpi, vdpi = self._get_dpi_values()
        buf += escp_set_resolution(hdpi, vdpi)

        # Page setup
        v_units_per_line = 720 // vdpi if vdpi <= 720 else 1
        buf += escp_set_page_length(h + 100)
        buf += escp_set_margins(0, h + 50)

        self._progress(65, f"掃描線輸出 ({h} 行)...")

        # ── Step 5: Rasterize line by line
        channels_to_print = channel_order

        for y in range(h):
            if y % 50 == 0:
                pct = 65 + int(y / h * 25)
                self._progress(pct, f"輸出掃描線 {y}/{h}...")

            buf += escp_move_vertical(y)

            for ch_name in channels_to_print:
                if ch_name not in dithered:
                    continue
                row_2bit = dithered[ch_name][y, :]
                # Check if row has any ink
                if np.any(row_2bit > 0):
                    color_id = self.CHANNEL_COLOR_IDS[ch_name]
                    buf += escp_raster_data(
                        channel=list(channels.keys()).index(ch_name),
                        color_id=color_id,
                        width_px=w,
                        data_2bit=row_2bit
                    )

        self._progress(92, "寫入頁尾指令...")
        buf += escp_form_feed()
        buf += escp_end()

        self._progress(100, f"編譯完成 — {len(buf):,} bytes")
        self._log(f"ESC/P-R 串流大小: {len(buf):,} bytes ({len(buf)/1024:.1f} KB)")
        return bytes(buf)

    def _get_channel_order(self) -> list:
        """Returns channel print order based on mode"""
        mode = self.config.mode
        if mode == PrintMode.CMYK_WHITE:
            return ['C', 'M', 'Y', 'K', 'W1', 'W2']
        elif mode == PrintMode.WHITE_CMYK:
            return ['W1', 'W2', 'C', 'M', 'Y', 'K']
        elif mode == PrintMode.CMYK_ONLY:
            return ['C', 'M', 'Y', 'K']
        elif mode == PrintMode.WHITE_ONLY:
            return ['W1', 'W2']
        return ['C', 'M', 'Y', 'K', 'W1', 'W2']

    def _get_dpi_values(self) -> tuple:
        dpi = self.config.dpi
        if dpi == DPIMode.DPI_5760x1440:
            return (5760, 1440)
        elif dpi == DPIMode.DPI_720x720:
            return (720, 720)
        else:
            return (1440, 1440)
