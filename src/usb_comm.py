"""
Epson L805 USB Direct Communication
Bypasses Windows Spooler — sends raw ESC/P-R stream directly to printer endpoint
"""
import time
import threading
from typing import Optional, Callable

# Try to import usb — graceful fallback for simulation mode
try:
    import usb.core
    import usb.util
    USB_AVAILABLE = True
except ImportError:
    USB_AVAILABLE = False


# Epson L805 USB identifiers
EPSON_VENDOR_ID  = 0x04B8
L805_PRODUCT_ID  = 0x08A1   # Epson L805
L800_PRODUCT_ID  = 0x0841   # L800 (same hardware base, some firmwares)

# Alternate product IDs seen in DTF conversions
KNOWN_PRODUCT_IDS = [L805_PRODUCT_ID, L800_PRODUCT_ID, 0x08A0, 0x0870]

# USB transfer chunk size (64KB optimal for bulk transfer)
CHUNK_SIZE = 65536


class PrinterStatus:
    DISCONNECTED = "未連接"
    READY        = "就緒"
    PRINTING     = "列印中"
    ERROR        = "錯誤"
    BUSY         = "忙碌"


class L805Printer:
    """
    Direct USB communication with Epson L805 (DTF modified)
    Uses bulk OUT endpoint for raw ESC/P-R data
    """

    def __init__(self,
                 log_cb: Optional[Callable] = None,
                 status_cb: Optional[Callable] = None):
        self.log = log_cb or (lambda msg: None)
        self.status_cb = status_cb or (lambda s: None)
        self.device = None
        self.out_endpoint = None
        self.status = PrinterStatus.DISCONNECTED
        self._cancel_flag = False
        self._sim_mode = False

    def _set_status(self, s: str):
        self.status = s
        self.status_cb(s)

    def find_printer(self) -> bool:
        """Scan USB bus for Epson L805"""
        if not USB_AVAILABLE:
            self.log("⚠ PyUSB 未安裝 — 切換至模擬模式")
            self._sim_mode = True
            self._set_status(PrinterStatus.READY)
            return True

        self.log("掃描 USB 裝置...")
        try:
            for pid in KNOWN_PRODUCT_IDS:
                dev = usb.core.find(idVendor=EPSON_VENDOR_ID, idProduct=pid)
                if dev is not None:
                    self.device = dev
                    self.log(f"找到印表機: VID=0x{EPSON_VENDOR_ID:04X} PID=0x{pid:04X}")
                    return self._configure_device()
        except Exception as e:
            self.log(f"⚠ USB 掃描錯誤: {e} — 切換至模擬模式")
            self._sim_mode = True
            self._set_status(PrinterStatus.READY)
            return True

        # No printer found — offer simulation mode
        self.log("⚠ 未找到 Epson L805 — 切換至模擬模式（連接印表機後請重新掃描）")
        self._sim_mode = True
        self._set_status(PrinterStatus.READY)
        return True

    def _configure_device(self) -> bool:
        """Claim USB interface and locate bulk OUT endpoint"""
        try:
            dev = self.device

            # Detach kernel driver if needed (Linux)
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
                self.log("已分離核心驅動")

            dev.set_configuration()
            cfg = dev.get_active_configuration()
            intf = cfg[(0, 0)]

            # Find bulk OUT endpoint
            self.out_endpoint = usb.util.find_descriptor(
                intf,
                custom_match=lambda e:
                    usb.util.endpoint_direction(e.bEndpointAddress) ==
                    usb.util.ENDPOINT_OUT and
                    usb.util.endpoint_type(e.bmAttributes) ==
                    usb.util.ENDPOINT_TYPE_BULK
            )

            if self.out_endpoint is None:
                self.log("❌ 找不到 Bulk OUT 端點")
                return False

            ep_addr = self.out_endpoint.bEndpointAddress
            self.log(f"Bulk OUT 端點: 0x{ep_addr:02X} — 就緒")
            self._set_status(PrinterStatus.READY)
            return True

        except Exception as e:
            self.log(f"❌ USB 設定失敗: {e}")
            self._set_status(PrinterStatus.ERROR)
            return False

    def send_data(self, data: bytes,
                  progress_cb: Optional[Callable] = None) -> bool:
        """
        Send raw ESC/P-R stream to printer via bulk transfer
        Chunks into 64KB blocks for reliable transfer
        """
        self._cancel_flag = False

        if self._sim_mode:
            return self._simulate_send(data, progress_cb)

        if self.out_endpoint is None:
            self.log("❌ 無可用端點 — 請先連接印表機")
            return False

        self._set_status(PrinterStatus.PRINTING)
        total = len(data)
        sent  = 0
        self.log(f"開始傳輸 {total:,} bytes → 印表機")

        try:
            while sent < total:
                if self._cancel_flag:
                    self.log("⚠ 使用者取消列印")
                    self._set_status(PrinterStatus.READY)
                    return False

                chunk = data[sent: sent + CHUNK_SIZE]
                written = self.out_endpoint.write(chunk, timeout=30000)
                sent += written

                pct = int(sent / total * 100)
                if progress_cb:
                    progress_cb(pct, f"傳輸中 {sent:,}/{total:,} bytes")

            self.log(f"✓ 傳輸完成: {sent:,} bytes")
            self._set_status(PrinterStatus.READY)
            return True

        except Exception as e:
            self.log(f"❌ USB 傳輸失敗: {e}")
            self._set_status(PrinterStatus.ERROR)
            return False

    def _simulate_send(self, data: bytes,
                       progress_cb: Optional[Callable] = None) -> bool:
        """Simulation mode — fake USB transfer with timing"""
        total = len(data)
        self._set_status(PrinterStatus.PRINTING)
        self.log(f"[模擬] 傳輸 {total:,} bytes...")

        steps = 20
        for i in range(steps + 1):
            if self._cancel_flag:
                self._set_status(PrinterStatus.READY)
                return False
            time.sleep(0.15)
            pct = int(i / steps * 100)
            if progress_cb:
                progress_cb(pct, f"[模擬] 傳輸中 {int(total*i/steps):,}/{total:,} bytes")

        self.log("✓ [模擬] 列印完成")
        self._set_status(PrinterStatus.READY)
        return True

    def cancel(self):
        self._cancel_flag = True

    def disconnect(self):
        if self.device and not self._sim_mode:
            try:
                usb.util.dispose_resources(self.device)
            except Exception:
                pass
        self.device = None
        self.out_endpoint = None
        self._set_status(PrinterStatus.DISCONNECTED)
        self.log("USB 連線已中斷")
