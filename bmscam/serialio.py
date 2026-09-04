"""Sériová komunikace s Arduinem (pyserial + Qt signály).

Čtení běží ve vlastním vlákně, přijaté řádky se do GUI dostávají signálem,
takže se s Qt prvky pracuje vždy jen v hlavním vlákně.
"""

import threading
import time
from typing import List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

try:
    import serial
    from serial.tools import list_ports
    SERIAL_ERROR = ""
except ImportError as exc:            # pyserial je volitelná závislost
    serial = None
    list_ports = None
    SERIAL_ERROR = (f"Knihovna pyserial není nainstalovaná ({exc}). "
                    "Nainstalujte ji příkazem:  pip install pyserial")


def available() -> bool:
    return serial is not None


def unavailable_reason() -> str:
    return SERIAL_ERROR


def list_serial_ports() -> List[tuple]:
    """Vrátí seznam (zařízení, popis) dostupných sériových portů."""
    if list_ports is None:
        return []
    out = []
    for port in list_ports.comports():
        label = port.description or port.device
        if port.manufacturer and port.manufacturer not in label:
            label = f"{label} – {port.manufacturer}"
        out.append((port.device, label))
    return out


def guess_arduino_port() -> Optional[str]:
    """Zkusí najít port, který vypadá jako Arduino."""
    if list_ports is None:
        return None
    keywords = ("arduino", "mega", "ch340", "ch910", "usb serial", "wch",
                "ftdi", "usb-serial")
    for port in list_ports.comports():
        haystack = " ".join(filter(None, (port.description, port.manufacturer,
                                          port.product))).lower()
        if any(k in haystack for k in keywords):
            return port.device
    ports = list_ports.comports()
    return ports[0].device if len(ports) == 1 else None


class SerialLink(QObject):
    """Spojení s deskou: otevření portu, čtení řádků, odesílání příkazů."""

    lineReceived = pyqtSignal(str)
    lineSent = pyqtSignal(str)
    opened = pyqtSignal(str)          # název portu
    closed = pyqtSignal()
    failed = pyqtSignal(str)          # text chyby

    #: Arduino se po otevření portu restartuje, chvíli trvá než naběhne
    BOOT_DELAY = 1.8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._port: Optional["serial.Serial"] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._name = ""

    # ---------------------------------------------------------------- stav --
    def is_open(self) -> bool:
        return self._port is not None and self._port.is_open

    def port_name(self) -> str:
        return self._name

    # -------------------------------------------------------------- otevření
    def open(self, port: str, baud: int) -> bool:
        if not available():
            self.failed.emit(SERIAL_ERROR)
            return False
        self.close()
        try:
            self._port = serial.Serial(port, int(baud), timeout=0.2,
                                       write_timeout=2.0)
        except Exception as exc:      # serial.SerialException i OSError
            self._port = None
            self.failed.emit(f"Port {port} se nepodařilo otevřít: {exc}")
            return False
        self._name = port
        self._stop.clear()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        self.opened.emit(port)
        return True

    def close(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        port, self._port = self._port, None
        if port is not None:
            try:
                port.close()
            except Exception:
                pass
            self._name = ""
            self.closed.emit()

    # ------------------------------------------------------------- odesílání
    def send(self, line: str) -> bool:
        if not self.is_open():
            self.failed.emit("Není otevřený žádný sériový port.")
            return False
        text = line.strip()
        if not text:
            return False
        try:
            with self._lock:
                self._port.write((text + "\n").encode("ascii", "replace"))
        except Exception as exc:
            self.failed.emit(f"Zápis na port selhal: {exc}")
            self.close()
            return False
        self.lineSent.emit(text)
        return True

    # ----------------------------------------------------------------- čtení
    def _read_loop(self) -> None:
        buffer = b""
        while not self._stop.is_set():
            port = self._port
            if port is None:
                break
            try:
                chunk = port.read(256)
            except Exception as exc:
                if not self._stop.is_set():
                    self.failed.emit(f"Čtení z portu selhalo: {exc}")
                break
            if not chunk:
                continue
            buffer += chunk
            while b"\n" in buffer:
                raw, _, buffer = buffer.partition(b"\n")
                text = raw.decode("utf-8", "replace").strip()
                if text:
                    self.lineReceived.emit(text)
            if len(buffer) > 4096:            # ochrana proti zahlcení
                buffer = b""
