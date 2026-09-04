"""Základní testy bez připojené kamery (běží i bez displeje).

Spuštění:  python -m pytest tests   nebo   python tests/test_smoke.py
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bmscam.backends import DemoBackend, diagnostics, enumerate_devices  # noqa: E402
from bmscam.spec import CATALOG, make_spec  # noqa: E402


def test_diagnostics_lists_all_backends():
    from bmscam.backends import BACKENDS
    lines = diagnostics()
    assert len(lines) == len(BACKENDS)
    assert any(line.startswith("demo:") for line in lines)
    assert any(line.startswith("uvcham:") for line in lines)


def test_demo_device_is_found():
    devices = enumerate_devices()
    assert any(d.backend == "demo" for d in devices)


def test_demo_stream_and_props():
    cam = DemoBackend.open()
    try:
        assert cam.resolutions()
        cam.set_resolution(3)
        received = []
        cam.start(received.append)
        frame = cam.pull()
        assert frame is not None
        assert frame.width * 3 <= frame.stride
        assert len(frame.data) == frame.stride * frame.height

        cam.set("brightness", 20)
        assert cam.get("brightness") == 20
        cam.action("wb_once")
        assert cam.info()["Sériové číslo"] == "DEMO-0001"
    finally:
        cam.close()


def test_prop_spec_formatting():
    spec = make_spec("expotime", 100, 200000, 20000)
    assert spec.format(20000) == "20.00 ms"
    assert make_spec("brightness", -64, 64, 0).format(-10) == "-10"


def test_catalog_groups_are_known():
    from bmscam.spec import GROUP_ORDER
    for key, meta in CATALOG.items():
        assert meta["group"] in GROUP_ORDER, key


def test_main_window_builds_and_connects():
    from PyQt5.QtWidgets import QApplication
    from bmscam.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = MainWindow(prefer_demo=True)
    win.show()
    win.connectCamera()
    try:
        assert win.camera is not None
        assert win.tabs.count() == 5
        for _ in range(20):
            app.processEvents()
        win._onPropChanged("contrast", 25)
        assert win.camera.get("contrast") == 25
    finally:
        win.close()




# ---------------------------------------------------------------- osvětlení --

def test_led_protocol_builds_commands():
    from bmscam.leds import LedProtocol as P
    assert P.panel_color(2, (10, 20, 300)) == "P 2 C 10 20 255"
    assert P.panel_brightness(1, -5) == "P 1 B 0"
    assert P.all_power(False) == "ALL OFF"
    assert P.only(3) == "ONLY 3"


def test_led_protocol_parses_replies():
    from bmscam.leds import LedProtocol as P, LedState
    assert P.is_banner("READY BMSLED 1.0 PANELS=4 LEDS=8")
    info = P.parse_banner("READY BMSLED 1.0 PANELS=4 LEDS=8")
    assert info == {"version": "1.0", "panels": "4", "leds": "8"}

    state = LedState()
    assert P.parse_state("STATE MASTER 0 90", state)
    assert state.master_on is False and state.master_brightness == 90
    assert P.parse_state("STATE 2 1 200 255 128 0", state)
    assert state.panel(2).color == (255, 128, 0)
    assert not P.parse_state("STATE zmetek", state)
    assert not P.parse_state("OK", state)
    assert P.is_error("ERR cislo panelu")


def test_led_panel_reflects_board_state():
    from PyQt5.QtWidgets import QApplication
    from bmscam.ui.led_panel import LedPanel

    app = QApplication.instance() or QApplication(sys.argv[:1])
    panel = LedPanel()
    try:
        panel._setConnected(True)
        for line in ("READY BMSLED 1.0 PANELS=4 LEDS=8",
                     "STATE MASTER 1 200",
                     "STATE 1 1 255 255 0 0",
                     "STATE 2 0 128 0 255 0"):
            panel._onLine(line)
        app.processEvents()
        assert panel.slider_master.value() == 200
        assert panel.panels[0].color() == (255, 0, 0)
        assert panel.panels[1].chk_on.isChecked() is False
        assert panel.panels[1].slider.value() == 128
        # bez otevřeného portu se nic neodešle a aplikace nespadne
        panel._onSolo(3)
        panel._setAllColor((1, 2, 3))
        assert panel.panels[3].color() == (1, 2, 3)
    finally:
        panel.shutdown()


def test_serial_link_reports_bad_port():
    from PyQt5.QtWidgets import QApplication
    from bmscam.serialio import SerialLink, available

    if not available():
        return
    QApplication.instance() or QApplication(sys.argv[:1])
    link = SerialLink()
    errors = []
    link.failed.connect(errors.append)
    assert link.open("/dev/rozhodne-neexistuje", 115200) is False
    assert errors and "nepodařilo" in errors[0]
    assert link.send("PING") is False




def test_serial_roundtrip_against_fake_board():
    """Ověří odesílání i příjem proti simulované desce na pseudoterminálu."""
    import os as _os
    import threading
    import time

    from PyQt5.QtWidgets import QApplication
    from bmscam.leds import LedProtocol, LedState
    from bmscam.serialio import SerialLink, available

    if not available() or not hasattr(_os, "openpty"):
        return

    app = QApplication.instance() or QApplication(sys.argv[:1])
    master_fd, slave_fd = _os.openpty()
    board_stop = threading.Event()

    def fake_board():
        """Napodobí sketch: odpoví na PING a STATE."""
        buf = b""
        while not board_stop.is_set():
            try:
                chunk = _os.read(master_fd, 128)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                raw, _, buf = buf.partition(b"\n")
                cmd = raw.decode().strip().upper()
                if cmd == "PING":
                    _os.write(master_fd, b"READY BMSLED 1.0 PANELS=4 LEDS=8\n")
                elif cmd == "STATE":
                    _os.write(master_fd, b"STATE MASTER 1 77\n"
                                         b"STATE 1 1 250 0 128 255\nOK\n")
                else:
                    _os.write(master_fd, b"OK\n")

    thread = threading.Thread(target=fake_board, daemon=True)
    thread.start()

    link = SerialLink()
    received = []
    link.lineReceived.connect(received.append)
    try:
        assert link.open(_os.ttyname(slave_fd), 115200)
        assert link.send(LedProtocol.ping())
        assert link.send(LedProtocol.state())
        deadline = time.time() + 3.0
        while time.time() < deadline and len(received) < 4:
            app.processEvents()
            time.sleep(0.02)
        assert any(LedProtocol.is_banner(line) for line in received), received
        state = LedState()
        for line in received:
            LedProtocol.parse_state(line, state)
        assert state.master_brightness == 77
        assert state.panel(1).color == (0, 128, 255)
    finally:
        board_stop.set()
        link.close()
        _os.close(slave_fd)
        _os.close(master_fd)


# ------------------------------------------------------- záložní UVC backend --

class _FakeCapture:
    """Napodobenina cv2.VideoCapture pro test bez kamery."""

    def __init__(self, index, api=None):
        self.index = index
        self.released = False
        self.values = {3: 1280.0, 4: 720.0,      # šířka, výška
                       10: 128.0, 11: 32.0, 12: 64.0, 13: 0.0,
                       14: 0.0, 15: -6.0, 21: 1.0,
                       99: -1.0}                 # nepodporovaná vlastnost

    def isOpened(self):
        return self.index < 2

    def get(self, prop):
        return self.values.get(prop, -1.0)

    def set(self, prop, value):
        if prop == 99:
            return False
        self.values[prop] = float(value)
        return True

    def read(self):
        width, height = int(self.values[3]), int(self.values[4])
        return True, _FakeFrame(width, height)

    def release(self):
        self.released = True


class _FakeFrame:
    def __init__(self, width, height):
        self.shape = (height, width, 3)
        self._data = b"\x40" * (width * height * 3)

    def tobytes(self):
        return self._data


def _fake_cv2():
    import types
    mod = types.ModuleType("cv2")
    mod.__version__ = "4.0.0-fake"
    mod.VideoCapture = _FakeCapture
    mod.CAP_DSHOW = mod.CAP_V4L2 = mod.CAP_AVFOUNDATION = 0
    mod.CAP_PROP_FRAME_WIDTH, mod.CAP_PROP_FRAME_HEIGHT = 3, 4
    mod.CAP_PROP_BRIGHTNESS, mod.CAP_PROP_CONTRAST = 10, 11
    mod.CAP_PROP_SATURATION, mod.CAP_PROP_HUE = 12, 13
    mod.CAP_PROP_GAIN, mod.CAP_PROP_EXPOSURE = 14, 15
    mod.CAP_PROP_AUTO_EXPOSURE = 21
    mod.CAP_PROP_GAMMA = mod.CAP_PROP_SHARPNESS = 99
    mod.CAP_PROP_WB_TEMPERATURE = mod.CAP_PROP_AUTO_WB = 99
    mod.CAP_PROP_AUTOFOCUS = mod.CAP_PROP_FOCUS = 99
    return mod


def test_opencv_backend_with_fake_camera():
    import importlib

    original = sys.modules.get("cv2")
    sys.modules["cv2"] = _fake_cv2()
    try:
        module = importlib.reload(
            importlib.import_module("bmscam.backends.uvc_opencv"))
        backend = module.OpenCvBackend

        assert backend.available()
        devices = backend.enumerate()
        assert [d.id for d in devices] == ["0", "1"]     # #2 a #3 se neotevřou

        cam = backend.open("0")
        try:
            keys = set(cam.props())
            assert {"brightness", "contrast", "saturation", "again",
                    "expotime", "aexpo"} <= keys
            assert "gamma" not in keys                   # ovladač ji nehlásí

            cam.set("brightness", 200)
            assert cam.get("brightness") == 200

            assert (1280, 720) in cam.resolutions()
            cam.set_resolution(cam.resolutions().index((1920, 1080)))
            assert cam.get_resolution() == cam.resolutions().index((1920, 1080))

            events = []
            cam.start(events.append)
            deadline = __import__("time").time() + 2.0
            while __import__("time").time() < deadline and not events:
                __import__("time").sleep(0.02)
            cam.stop()
            assert events and events[0] == module.EVENT_IMAGE
            frame = cam.pull()
            assert frame.width == 1920 and frame.stride == 1920 * 3
            assert cam.pixel_order == "bgr"
        finally:
            cam.close()
    finally:
        if original is not None:
            sys.modules["cv2"] = original
        else:
            sys.modules.pop("cv2", None)
        importlib.reload(importlib.import_module("bmscam.backends.uvc_opencv"))



if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK   {name}")
            except Exception as exc:            # noqa: BLE001
                failed += 1
                print(f"CHYBA {name}: {exc}")
    sys.exit(1 if failed else 0)
