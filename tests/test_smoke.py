"""Základní testy bez připojené kamery (běží i bez displeje).

Spuštění:  python -m pytest tests   nebo   python tests/test_smoke.py
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from bmscam.backends import DemoBackend, diagnostics, enumerate_devices  # noqa: E402
from bmscam.spec import CATALOG, make_spec  # noqa: E402


_APP = None


def _app():
    """Vrátí sdílenou instanci QApplication (drženou po dobu běhu testů)."""
    global _APP
    from PyQt5.QtWidgets import QApplication
    if _APP is None:
        _APP = QApplication.instance() or QApplication(sys.argv[:1])
    return _APP


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
    from bmscam.ui.main_window import MainWindow

    app = _app()
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
    from bmscam.ui.led_panel import LedPanel

    app = _app()
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
    from bmscam.serialio import SerialLink, available

    if not available():
        return
    _app()
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

    from bmscam.leds import LedProtocol, LedState
    from bmscam.serialio import SerialLink, available

    if not available() or not hasattr(_os, "openpty"):
        return

    app = _app()
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




# ------------------------------------------------------------------ vzhled --

def test_theme_provides_tokens_and_icons():
    from bmscam.ui import theme

    _app()
    qss = theme.stylesheet()
    assert theme.ACCENT in qss and theme.SURFACE in qss
    assert "border-radius: 0" in qss          # systém je bez zaoblení
    assert not theme.icon("camera").isNull()
    assert theme.icon("neexistujici-ikona").isNull()


def test_segmented_control_selects_and_clears():
    from bmscam.ui.widgets import SegmentedControl

    _app()
    seg = SegmentedControl(["A", "B", "C"])
    seen = []
    seg.currentChanged.connect(seen.append)
    assert seg.currentIndex() == 0
    seg.setCurrentIndex(2)
    assert seg.currentIndex() == 2
    seg.buttons[1].click()
    assert seen == [1] and seg.currentIndex() == 1
    seg.clearSelection()
    assert seg.currentIndex() == -1

    empty = SegmentedControl(["A", "B"], preselect=False)
    assert empty.currentIndex() == -1


def test_side_panel_collapses():
    from bmscam.ui import theme
    from bmscam.ui.widgets import SidePanel

    _app()
    panel = SidePanel("Test", "left")
    assert panel.width() == theme.PANEL_WIDTH
    panel.toggle()
    assert panel.is_collapsed() and panel.width() == theme.PANEL_COLLAPSED
    assert not panel.body.isVisible()
    panel.toggle()
    assert not panel.is_collapsed() and panel.width() == theme.PANEL_WIDTH


def test_main_window_view_controls():
    from bmscam.ui import theme
    from bmscam.ui.main_window import MainWindow

    app = _app()
    app.setStyleSheet(theme.stylesheet())
    win = MainWindow(prefer_demo=True)
    win.show()
    win.connectCamera()
    try:
        for _ in range(20):
            app.processEvents()
        # přepínání panelu osvětlení
        win.act_leds.setChecked(False)
        assert win.right_panel.is_collapsed()
        win.act_leds.setChecked(True)
        assert not win.right_panel.is_collapsed()
        # světlé pozadí náhledu
        win.btn_stage.setChecked(True)
        assert win.view._light_stage
        win.btn_stage.setChecked(False)
        # překryvy
        win.act_grid.setChecked(True)
        assert win.view.show_grid
        # záložky vlastností
        win.seg_tabs.buttons[2].click()
        assert win.tabs.currentIndex() == 2
        # údaje v proužku přes obraz
        assert "EXP" in win.view._stats
        win.view.set_recording(65)
        assert win.view._recording == 65
    finally:
        win.close()


# ------------------------------------------------------------- prostředí Qt --

def test_qtenv_points_at_pyqt_plugins():
    """qtenv nasměruje Qt na zásuvné moduly, které patří k PyQt5."""
    import os
    from bmscam import qtenv

    directory = qtenv.plugins_dir()
    assert directory and os.path.isdir(os.path.join(directory, "platforms"))
    assert qtenv.prepare() == directory
    assert os.environ["QT_PLUGIN_PATH"] == directory
    assert os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] == \
        os.path.join(directory, "platforms")

    qtenv.apply_library_path()
    from PyQt5.QtCore import QCoreApplication
    assert directory in QCoreApplication.libraryPaths()

    text = "\n".join(qtenv.report())
    assert "PyQt5" in text and "QT_QPA_PLATFORM_PLUGIN_PATH" in text


def test_opencv_import_is_deferred():
    """Modul cv2 se nesmí načíst při pouhém importu aplikace.

    Import cv2 ve Windows přepíše cesty k zásuvným modulům Qt, což aplikaci
    znemožní otevřít okno."""
    import subprocess

    code = ("import sys, bmscam.app;"
            " import bmscam.backends.uvc_opencv as u;"
            " print('cv2' in sys.modules or u._import_done)")
    out = subprocess.run([sys.executable, "-c", code], cwd=_ROOT,
                         capture_output=True, text=True)
    assert out.stdout.strip() == "False", out.stdout + out.stderr


# ------------------------------------------------------- zadávání hodnot --

def test_prop_row_accepts_typed_value():
    """Hodnotu jde zadat číslem; posuvník i pole se drží spolu."""
    from bmscam.spec import make_spec
    from bmscam.ui.controls import PropRow

    _app()
    row = PropRow(make_spec("expotime", 100, 2000000, 20000,
                            unit="", scale=1.0, decimals=0))
    seen = []
    row.valueChanged.connect(lambda key, val: seen.append((key, val)))
    try:
        assert row.spin.isEnabled() and not row.spin.isReadOnly()
        assert (row.spin.minimum(), row.spin.maximum()) == (100, 2000000)
        assert row.spin.singleStep() > 1        # krok po jedné by byl k ničemu

        row.spin.setValue(123456)               # jako by uživatel číslo napsal
        assert row.slider.value() == 123456
        assert seen[-1] == ("expotime", 123456)

        row.slider.setValue(777)                # a zpět: posuvník mění pole
        assert row.spin.value() == 777
    finally:
        row.deleteLater()


def test_prop_row_spin_respects_scale():
    """Pole s desetinnými místy přepočítává na syrové jednotky SDK."""
    from bmscam.spec import make_spec
    from bmscam.ui.controls import PropRow

    _app()
    row = PropRow(make_spec("expotime", 100, 200000, 20000))   # µs -> ms
    seen = []
    row.valueChanged.connect(lambda key, val: seen.append(val))
    try:
        row.spin.setValue(50.0)                 # 50 ms
        assert seen[-1] == 50000                # = 50 000 µs
        assert row.slider.value() == 50000
    finally:
        row.deleteLater()


# --------------------------------------------------------- kontrola videa --

def _mp4(*boxes: bytes) -> bytes:
    return b"".join(boxes)


def _box(kind: bytes, payload: bytes = b"") -> bytes:
    import struct
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def test_videocheck_detects_unfinished_file(tmpdir=None):
    """Soubor bez rejstříku moov = nedokončené nahrávání."""
    import tempfile
    from bmscam import videocheck

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
        fh.write(_mp4(_box(b"ftyp", b"isom" + b"\x00" * 8),
                      _box(b"mdat", b"\x00" * 8000)))
        path = fh.name
    try:
        report = videocheck.inspect(path)
        assert report.container == "MP4"
        assert report.complete is False
        assert "není dokončený" in report.verdict()
    finally:
        os.unlink(path)


def test_videocheck_reports_codec():
    """Dokončený soubor: pozná kodek a řekne, jestli ho Windows přehrají."""
    import struct
    import tempfile
    from bmscam import videocheck

    mvhd = _box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, 1000, 5000))
    stsd = _box(b"stsd", b"\x00\x00\x00\x00" + struct.pack(">I", 1)
                + _box(b"mp4v", b"\x00" * 70))
    moov = _box(b"moov", mvhd + _box(b"trak", _box(b"mdia", _box(
        b"minf", _box(b"stbl", stsd)))))
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
        fh.write(_mp4(_box(b"ftyp", b"isom" + b"\x00" * 8),
                      _box(b"mdat", b"\x00" * 8000), moov))
        path = fh.name
    try:
        report = videocheck.inspect(path)
        assert report.complete is True
        assert report.codec == "mp4v"
        assert report.duration == 5.0
        assert report.playable_in_windows is False
        assert "VLC" in report.verdict()
    finally:
        os.unlink(path)


def test_videocheck_handles_empty_and_missing():
    import tempfile
    from bmscam import videocheck

    assert "neexistuje" in videocheck.inspect("/nic/takoveho.mp4").verdict()
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
        path = fh.name
    try:
        assert "prázdný" in videocheck.inspect(path).verdict()
    finally:
        os.unlink(path)


def test_video_suffix_is_enforced():
    """Bez známé přípony by SDK nevědělo, jaký kontejner zapsat."""
    from bmscam import videocheck
    from bmscam.ui.main_window import MainWindow

    assert videocheck.suffix_is_supported("a/b/zaznam.mp4")
    assert videocheck.suffix_is_supported("ZAZNAM.MKV")
    assert not videocheck.suffix_is_supported("zaznam.avi")
    assert MainWindow._fixVideoSuffix("zaznam") == "zaznam.mp4"
    assert MainWindow._fixVideoSuffix("zaznam.avi") == "zaznam.mp4"
    assert MainWindow._fixVideoSuffix("zaznam.mkv") == "zaznam.mkv"


def test_recording_blocks_stream_restart():
    """Změna rozlišení během nahrávání by soubor nechala nedokončený."""
    from bmscam.ui.main_window import MainWindow

    from PyQt5.QtWidgets import QMessageBox

    app = _app()
    win = MainWindow(prefer_demo=True)
    win.connectCamera()
    shown = []
    original_dialog = QMessageBox.information
    QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a[-1]))
    try:
        for _ in range(10):
            app.processEvents()
        assert win._allowStreamRestart("Rozlišení") is True
        assert not shown
        win._recording_since = 1.0             # jako by běželo nahrávání
        assert win.isRecording()
        blocked = []
        win._fillResolutions = lambda: blocked.append(True)
        original = win.camera.get_resolution()
        assert win._allowStreamRestart("Rozlišení") is False
        assert blocked                          # nabídka se vrátila zpět
        assert win.camera.get_resolution() == original
        assert shown and "nahrávání" in shown[0]
        win._recording_since = None
    finally:
        QMessageBox.information = original_dialog
        win.close()


# ------------------------------------------------------------- časosběr ---

def test_timelapse_uses_its_own_folder():
    """Každý časosběr má vlastní podsložku a číslované snímky."""
    import tempfile
    from bmscam.ui.main_window import MainWindow

    app = _app()
    win = MainWindow(prefer_demo=True)
    win.connectCamera()
    workdir = tempfile.mkdtemp()
    win.save_dir = workdir
    try:
        import time as _time
        deadline = _time.time() + 5.0
        while _time.time() < deadline and not win.view.hasImage():
            app.processEvents()
            _time.sleep(0.02)
        assert win.view.hasImage(), "demo kamera nedodala obraz"

        win.toggleTimelapse(True)
        folder = win._timelapse_dir
        assert folder and os.path.isdir(folder)
        assert os.path.dirname(folder) == workdir
        assert os.path.basename(folder).startswith("casosber_")

        win._onTimelapse()
        win._onTimelapse()
        assert win._timelapse_count == 2
        shots = sorted(os.listdir(folder))
        assert len(shots) == 2
        assert shots[0].startswith("snimek_0001_")
        assert shots[1].startswith("snimek_0002_")

        win.toggleTimelapse(False)
        assert win._timelapse_dir is None
        # běžný snímek jde dál do pracovní složky, ne do složky časosběru
        path = win.snapshot(silent=True)
        assert path and os.path.dirname(path) == workdir

        # druhý časosběr dostane jinou složku a prázdný po sobě uklidí
        win.toggleTimelapse(True)
        second = win._timelapse_dir
        assert second != folder
        win.toggleTimelapse(False)
        assert not os.path.exists(second)
    finally:
        win.close()
        import shutil as _shutil
        _shutil.rmtree(workdir, ignore_errors=True)


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
