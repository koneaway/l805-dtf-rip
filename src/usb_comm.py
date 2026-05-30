"""
Epson L805 USB Direct Communication
Scans all USB devices, shows device names, allows selection
"""
import time
from typing import Optional, Callable

try:
    import usb.core
    import usb.util
    USB_AVAILABLE = True
except ImportError:
    USB_AVAILABLE = False

EPSON_VENDOR_ID   = 0x04B8
KNOWN_L805_PIDS   = [0x08A1, 0x0841, 0x08A0, 0x0870]
CHUNK_SIZE        = 65536

class PrinterStatus:
    DISCONNECTED = "未連接"
    READY        = "就緒"
    PRINTING     = "列印中"
    ERROR        = "錯誤"
    BUSY         = "忙碌"


def scan_usb_printers() -> list[dict]:
    """
    Scan all USB devices and return list of potential printers.
    Returns: [{ 'vid', 'pid', 'manufacturer', 'product', 'serial',
                'bus', 'address', 'is_epson', 'is_l805' }]
    """
    results = []
    if not USB_AVAILABLE:
        return [{'vid': 0, 'pid': 0, 'manufacturer': 'PyUSB 未安裝',
                 'product': '模擬印表機 (Epson L805)', 'serial': 'SIM',
                 'bus': 0, 'address': 0, 'is_epson': True, 'is_l805': True}]
    try:
        devices = list(usb.core.find(find_all=True))
        for dev in devices:
            try:
                mfr     = usb.util.get_string(dev, dev.iManufacturer) if dev.iManufacturer else ""
                product = usb.util.get_string(dev, dev.iProduct)      if dev.iProduct      else ""
                serial  = usb.util.get_string(dev, dev.iSerialNumber) if dev.iSerialNumber else ""
            except Exception:
                mfr = product = serial = ""

            is_epson = dev.idVendor == EPSON_VENDOR_ID or "epson" in (mfr + product).lower()
            is_l805  = is_epson and dev.idProduct in KNOWN_L805_PIDS

            # Only show printers (class 7) or known Epson devices
            is_printer = False
            try:
                for cfg in dev:
                    for intf in cfg:
                        if intf.bInterfaceClass == 7:  # USB Printer class
                            is_printer = True
            except Exception:
                pass

            if is_epson or is_printer or is_l805:
                results.append({
                    'vid': dev.idVendor, 'pid': dev.idProduct,
                    'manufacturer': mfr or f"VID 0x{dev.idVendor:04X}",
                    'product': product or f"Unknown Device PID 0x{dev.idProduct:04X}",
                    'serial': serial,
                    'bus': dev.bus, 'address': dev.address,
                    'is_epson': is_epson, 'is_l805': is_l805,
                })
    except Exception as e:
        results.append({'vid': 0, 'pid': 0, 'manufacturer': f'掃描錯誤: {e}',
                        'product': '請確認 WinUSB 驅動已安裝', 'serial': '',
                        'bus': 0, 'address': 0, 'is_epson': False, 'is_l805': False})
    return results


class L805Printer:
    def __init__(self, log_cb: Optional[Callable] = None,
                 status_cb: Optional[Callable] = None):
        self.log       = log_cb    or (lambda m: None)
        self.status_cb = status_cb or (lambda s: None)
        self.device       = None
        self.out_endpoint = None
        self.status       = PrinterStatus.DISCONNECTED
        self._cancel_flag = False
        self._sim_mode    = False
        self._selected_bus     = None
        self._selected_address = None

    def _set_status(self, s):
        self.status = s
        self.status_cb(s)

    def select_device(self, bus: int, address: int):
        """Select a specific USB device by bus/address."""
        self._selected_bus     = bus
        self._selected_address = address

    def find_printer(self) -> bool:
        if not USB_AVAILABLE:
            self.log("⚠ PyUSB 未安裝 — 模擬模式")
            self._sim_mode = True
            self._set_status(PrinterStatus.READY)
            return True

        self.log("掃描 USB 裝置...")
        try:
            # If user selected a specific device, try that first
            if self._selected_bus is not None and self._selected_address is not None:
                dev = usb.core.find(bus=self._selected_bus,
                                    address=self._selected_address)
                if dev:
                    self.device = dev
                    self.log(f"使用已選取裝置: Bus {self._selected_bus} Addr {self._selected_address}")
                    return self._configure_device()

            # Otherwise scan for known L805 PIDs
            for pid in KNOWN_L805_PIDS:
                dev = usb.core.find(idVendor=EPSON_VENDOR_ID, idProduct=pid)
                if dev:
                    self.device = dev
                    self.log(f"找到印表機: VID=0x{EPSON_VENDOR_ID:04X} PID=0x{pid:04X}")
                    return self._configure_device()

        except Exception as e:
            self.log(f"⚠ 掃描錯誤: {e}")

        self.log("⚠ 未找到 L805 — 使用模擬模式")
        self._sim_mode = True
        self._set_status(PrinterStatus.READY)
        return True

    def _configure_device(self) -> bool:
        try:
            dev = self.device
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
            dev.set_configuration()
            cfg  = dev.get_active_configuration()
            intf = cfg[(0, 0)]
            self.out_endpoint = usb.util.find_descriptor(
                intf,
                custom_match=lambda e:
                    usb.util.endpoint_direction(e.bEndpointAddress)
                    == usb.util.ENDPOINT_OUT and
                    usb.util.endpoint_type(e.bmAttributes)
                    == usb.util.ENDPOINT_TYPE_BULK
            )
            if self.out_endpoint is None:
                self.log("❌ 找不到 Bulk OUT 端點")
                return False
            self.log(f"Bulk OUT: 0x{self.out_endpoint.bEndpointAddress:02X} — 就緒")
            self._set_status(PrinterStatus.READY)
            return True
        except Exception as e:
            self.log(f"❌ 設定失敗: {e}")
            self._set_status(PrinterStatus.ERROR)
            return False

    def send_data(self, data: bytes,
                  progress_cb: Optional[Callable] = None) -> bool:
        self._cancel_flag = False
        if self._sim_mode:
            return self._simulate(data, progress_cb)
        if not self.out_endpoint:
            self.log("❌ 無端點 — 請先掃描印表機")
            return False
        self._set_status(PrinterStatus.PRINTING)
        total = len(data); sent = 0
        self.log(f"傳輸 {total:,} bytes...")
        try:
            while sent < total:
                if self._cancel_flag:
                    self._set_status(PrinterStatus.READY)
                    return False
                chunk = data[sent:sent + CHUNK_SIZE]
                written = self.out_endpoint.write(chunk, timeout=30000)
                sent += written
                if progress_cb:
                    progress_cb(int(sent/total*100), f"傳輸 {sent:,}/{total:,} bytes")
            self._set_status(PrinterStatus.READY)
            return True
        except Exception as e:
            self.log(f"❌ 傳輸失敗: {e}")
            self._set_status(PrinterStatus.ERROR)
            return False

    def _simulate(self, data: bytes,
                  progress_cb: Optional[Callable] = None) -> bool:
        self._set_status(PrinterStatus.PRINTING)
        total = len(data)
        self.log(f"[模擬] {total:,} bytes")
        for i in range(21):
            if self._cancel_flag:
                self._set_status(PrinterStatus.READY)
                return False
            time.sleep(0.12)
            pct = int(i / 20 * 100)
            if progress_cb:
                progress_cb(pct, f"[模擬] {int(total*i/20):,}/{total:,} bytes")
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
