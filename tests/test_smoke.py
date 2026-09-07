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
        assert win.tabs.count() == 6          # 5 skupin vlastností + Dark Field
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
        panel.setRotation(0)             # moduly zapojené podle popisků
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


def test_led_panel_maps_sides_to_wiring():
    """Popisek strany musí sedět na modul, který na té straně opravdu leží."""
    from bmscam.leds import DEFAULT_ROTATION, LedProtocol
    from bmscam.ui.led_panel import LedPanel

    app = _app()
    panel = LedPanel()
    try:
        sent = []
        panel._send = sent.append

        # Výchozí zapojení: první modul leží vpravo, „Horní“ je tedy modul 4.
        assert DEFAULT_ROTATION == 1
        panel.setRotation(DEFAULT_ROTATION)
        sent.clear()
        panel._onSolo(1)                        # strana „Horní“
        assert sent == [LedProtocol.only(4)], sent
        sent.clear()
        panel._onSolo(2)                        # strana „Pravý“
        assert sent == [LedProtocol.only(1)], sent

        # Šikmé osvětlení jde stejnou cestou.
        sent.clear()
        panel._onDirection(0)                   # tlačítko „H“
        assert sent == [LedProtocol.only(4)], sent

        # Stav z desky se rozřadí zpátky na správné strany.
        panel._setConnected(True)
        panel._onLine("STATE 4 1 255 9 9 9")    # modul 4 = horní strana
        app.processEvents()
        assert panel.panels[0].color() == (9, 9, 9)

        # Bez natočení adresuje aplikace moduly přímo.
        panel.setRotation(0)
        sent.clear()
        panel._onSolo(1)
        assert sent == [LedProtocol.only(1)], sent
    finally:
        panel.setRotation(DEFAULT_ROTATION)
        panel.shutdown()


def test_workspace_roundtrip_and_old_profile():
    """Kompletní nastavení se uloží a načte; starý profil kamery se povýší."""
    import json
    import shutil
    import tempfile

    from bmscam import workspace

    folder = tempfile.mkdtemp()
    try:
        data = workspace.new(
            camera={"backend": "uvcham", "values": {"expotime": 1234, "again": 100},
                    "resolution": 0, "resolution_size": [3840, 2160], "codec": 1},
            leds={"rotation": 1, "master_on": True, "master_brightness": 200,
                  "panels": [{"on": True, "brightness": 255, "color": [255, 0, 0]}]},
            darkfield={"interval_s": 10.0, "threshold_mode": "sigma", "sigma": 5.0},
            capture={"save_dir": folder, "timelapse_interval": 15, "um_per_px": 0.5})
        path = os.path.join(folder, "nastaveni.json")
        workspace.save(path, data)

        back = workspace.load(path)
        assert back["format"] == workspace.FORMAT
        assert workspace.section(back, "camera")["values"]["expotime"] == 1234
        assert workspace.section(back, "leds")["rotation"] == 1
        assert workspace.section(back, "capture")["timelapse_interval"] == 15
        summary = " ".join(workspace.describe(back))
        assert "3840×2160" in summary and "Dark Field" in summary

        # starý profil (jen vlastnosti kamery v kořeni) se přečte taky
        old_path = os.path.join(folder, "stary.json")
        with open(old_path, "w", encoding="utf-8") as fh:
            json.dump({"backend": "demo", "values": {"again": 42}}, fh)
        old = workspace.load(old_path)
        assert workspace.section(old, "camera")["values"]["again"] == 42

        # poškozený soubor je hlášená chyba, ne pád
        bad = os.path.join(folder, "spatny.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{tohle není JSON")
        try:
            workspace.load(bad)
        except workspace.WorkspaceError:
            pass
        else:
            raise AssertionError("poškozený soubor se měl ohlásit")

        # výchozí složka končí na „BMS fotky“ ve Stažených souborech
        default = workspace.default_save_dir()
        assert default.endswith(workspace.FOLDER_NAME)
        assert "ownload" in default or "tažen" in default or "tahov" in default
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_main_window_saves_and_loads_everything():
    """Uložit a načíst musí projít celou aplikací, ne jen kamerou."""
    import shutil
    import tempfile

    from bmscam import workspace
    from bmscam.ui.main_window import MainWindow

    _app()
    win = MainWindow(prefer_demo=True)
    folder = tempfile.mkdtemp()
    try:
        win.connectCamera()
        win.save_dir = folder
        win.spin_interval.setValue(23)
        win.view.um_per_px = 0.25
        win.df_panel.spin_sigma.setValue(7.5)
        win.led_panel.setRotation(2)
        win.led_panel.panels[0].setState(True, 111, (10, 20, 30))

        path = os.path.join(folder, "vse.json")
        workspace.save(path, workspace.new(
            camera=win._cameraSettings(),
            leds=win.led_panel.workspaceSettings(),
            darkfield=win.df_panel.settings(None).to_dict(),
            capture=win._captureSettings()))

        # všechno přenastavit jinak a pak načíst zpátky
        win.spin_interval.setValue(5)
        win.df_panel.spin_sigma.setValue(2.0)
        win.led_panel.setRotation(0)
        win.led_panel.panels[0].setState(False, 1, (0, 0, 0))
        win.applyProfile(path)

        assert win.spin_interval.value() == 23
        assert win.df_panel.spin_sigma.value() == 7.5
        assert win.led_panel.rotation == 2
        assert win.led_panel.panels[0].color() == (10, 20, 30)
        assert win.led_panel.panels[0].brightness() == 111
        assert win.view.um_per_px == 0.25
        assert win.save_dir == folder
    finally:
        win.led_panel.setRotation(1)
        win.close()
        shutil.rmtree(folder, ignore_errors=True)


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
    assert seen == [2]                   # i programové přepnutí se ohlásí
    seg.setCurrentIndex(2)
    assert seen == [2]                   # ale jen když se něco změní
    seg.buttons[1].click()
    assert seen == [2, 1] and seg.currentIndex() == 1
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


# ------------------------------------------------------------ dark field --

def _speckled(rng, shape=(240, 320), level=8.0, noise=1.5, spots=0,
              radius=3, amplitude=60.0):
    """Snímek tmavého pole: tmavé pozadí a na něm svítící částice."""
    import numpy as np
    img = level + rng.normal(0, noise, shape)
    yy, xx = np.ogrid[:shape[0], :shape[1]]
    for y, x in zip(rng.integers(15, shape[0] - 15, spots),
                    rng.integers(15, shape[1] - 15, spots)):
        img[(yy - y) ** 2 + (xx - x) ** 2 <= radius * radius] += amplitude
    return img.astype("float32")


def test_darkfield_counts_contamination():
    """Víc částic = větší pokrytí; čisté sklíčko vyjde jako nula."""
    import numpy as np
    from bmscam import darkfield as df

    rng = np.random.default_rng(42)
    collector = df.BiasCollector(5)
    while not collector.add(_speckled(rng)):
        pass
    bias = collector.result()
    assert bias.frames == 5
    assert 6.0 < bias.level < 10.0

    settings = df.Settings(sigma=5.0, min_area_px=4, um_per_px=0.5)
    clean = df.analyze(_speckled(rng), bias, settings)
    assert clean["coverage_pct"] < 0.01

    few = df.analyze(_speckled(rng, spots=5), bias, settings)
    many = df.analyze(_speckled(rng, spots=20), bias, settings)
    assert few["coverage_pct"] > clean["coverage_pct"]
    assert many["coverage_pct"] > 3 * few["coverage_pct"]
    assert many["particle_area_px"] > few["particle_area_px"]
    assert many["area_um2"] == many["particle_area_px"] * 0.25
    assert 50 < few["mean_signal"] < 70          # jas přidaných částic

    try:
        import cv2                               # noqa: F401
    except ImportError:
        assert few["particles"] == -1            # bez OpenCV se nepočítají
    else:
        assert few["particles"] == 5 and many["particles"] == 20


def test_darkfield_threshold_modes_and_bias_mismatch():
    import numpy as np
    from bmscam import darkfield as df

    rng = np.random.default_rng(7)
    collector = df.BiasCollector(3)
    while not collector.add(_speckled(rng)):
        pass
    bias = collector.result()

    frame = _speckled(rng, spots=10)
    strict = df.analyze(frame, bias, df.Settings(sigma=20.0, min_area_px=1))
    loose = df.analyze(frame, bias, df.Settings(sigma=2.0, min_area_px=1))
    assert loose["coverage_pct"] >= strict["coverage_pct"]
    assert loose["threshold"] < strict["threshold"]

    absolute = df.analyze(frame, bias, df.Settings(
        threshold_mode=df.THRESHOLD_ABSOLUTE, absolute=30.0, min_area_px=1))
    assert abs(absolute["threshold"] - 30.0) < 1e-6

    # bez reference se použije medián snímku, nespadne to
    assert df.analyze(frame, None, df.Settings())["coverage_pct"] > 0

    # jiné rozlišení než reference musí být srozumitelná chyba
    try:
        df.analyze(_speckled(rng, shape=(100, 100)), bias, df.Settings())
    except ValueError as exc:
        assert "rozlišení" in str(exc)
    else:
        raise AssertionError("nesouhlasné rozlišení mělo skončit chybou")


def test_darkfield_bias_survives_save_and_load():
    import tempfile
    import numpy as np
    from bmscam import darkfield as df

    rng = np.random.default_rng(3)
    bias = df.Bias(_speckled(rng), frames=9)
    with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as fh:
        path = fh.name
    try:
        bias.save(path)
        loaded = df.Bias.load(path)
        assert loaded.frames == 9
        assert loaded.shape == bias.shape
        assert np.allclose(loaded.mean, bias.mean)
    finally:
        os.unlink(path)


def test_darkfield_series_and_csv():
    import csv as _csv
    import tempfile
    from datetime import datetime, timedelta
    from bmscam import darkfield as df

    series = df.Series()
    start = datetime(2026, 9, 7, 8, 0, 0)
    for i in range(5):
        series.add({"coverage_pct": 0.1 * i, "particles": i,
                    "particle_area_px": 10 * i, "area_um2": 2.5 * i,
                    "mean_signal": 50.0, "max_signal": 60.0,
                    "bg_sigma": 1.5, "threshold": 9.0},
                   start + timedelta(seconds=60 * i))
    assert len(series) == 5
    assert series.values("time_s") == [0.0, 60.0, 120.0, 180.0, 240.0]
    assert abs(series.rate_per_minute() - 0.1) < 1e-6     # 0,1 % za minutu

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as fh:
        path = fh.name
    try:
        series.to_csv(path, df.Settings(sigma=4.0), None)
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = list(_csv.reader(fh, delimiter=";"))
        # zakomentované řádky s nastavením poznáme podle "# " na začátku;
        # samotné "#" je název prvního sloupce tabulky
        notes = [r for r in rows if r and r[0].startswith("# ")]
        data = [r for r in rows if r and not r[0].startswith("# ")]
        assert any("sigma" in r[0] for r in notes)        # nastavení je v hlavičce
        assert len(data) == 6                             # záhlaví + 5 řádků
        assert data[0][0] == "#" and "Pokrytí" in data[0][3]
        assert data[-1][1] == "240.00"
    finally:
        os.unlink(path)

    series.clear()
    assert len(series) == 0 and series.rate_per_minute() == 0.0


def test_darkfield_gray_conversion():
    """Z RGB888 snímku se vytáhne šedotónové pole i při zarovnaném řádku."""
    import numpy as np
    from bmscam import darkfield as df

    width, height = 5, 3
    stride = width * 3 + 4                      # zarovnání jako v SDK
    raw = bytearray(stride * height)
    for y in range(height):
        for x in range(width):
            value = 10 * y + x
            for channel in range(3):
                raw[y * stride + x * 3 + channel] = value

    class _Frame:
        pass
    frame = _Frame()
    frame.data, frame.width, frame.height, frame.stride = raw, width, height, stride

    gray = df.to_gray(frame)
    assert gray.shape == (height, width)
    assert gray[2, 4] == 24 and gray[0, 0] == 0
    assert df.crop(gray, (1, 1, 3, 2)).shape == (2, 3)
    assert df.crop(gray, None).shape == (height, width)


def test_darkfield_panel_flow():
    """Panel: reference, měření, tabulka, souhrn."""
    import numpy as np
    from bmscam import darkfield as df
    from bmscam.ui.darkfield_panel import DarkFieldPanel

    app = _app()
    panel = DarkFieldPanel()
    try:
        assert panel.bias is None
        assert "Není pořízen" in panel.lbl_bias.text()

        rng = np.random.default_rng(11)
        panel.setBias(df.Bias(_speckled(rng), frames=4))
        assert "4 snímků" in panel.lbl_bias.text()
        assert panel.btn_bias_save.isEnabled()

        settings = panel.settings()
        assert settings.threshold_mode == df.THRESHOLD_SIGMA
        panel.seg_mode.setCurrentIndex(1)
        assert panel.settings().threshold_mode == df.THRESHOLD_ABSOLUTE
        assert panel.spin_sigma.isEnabled() is False

        for i in range(3):
            panel.addSample({"coverage_pct": 0.5 * i, "particles": i,
                             "particle_area_px": i, "area_um2": 0.0,
                             "mean_signal": 1.0, "max_signal": 2.0,
                             "bg_sigma": 1.0, "threshold": 5.0})
        assert len(panel.series) == 3
        assert "3 měření" in panel.summaryText()
        assert "(3)" in panel.btn_table.text()

        panel.showTable()
        assert panel.window_.table.rowCount() == 3
        assert panel.window_.table.item(2, 3).text() == "1.0000"

        panel.clearSeries()
        assert len(panel.series) == 0
        assert panel.window_.table.rowCount() == 0
    finally:
        if panel.window_ is not None:
            panel.window_.close()
        panel.deleteLater()


def test_main_window_darkfield_measures_from_camera():
    """Celý řetěz: snímek z kamery → reference → měření → řádek tabulky."""
    import time as _time
    from bmscam.ui.main_window import MainWindow

    app = _app()
    win = MainWindow(prefer_demo=True)
    win.connectCamera()
    try:
        deadline = _time.time() + 5.0
        while _time.time() < deadline and not win.view.hasImage():
            app.processEvents()
            _time.sleep(0.02)
        assert win.view.hasImage()

        # Rozbor běží ve vlastním vlákně, výsledek proto přijde až později.
        def wait_for(check, limit=10.0):
            deadline = _time.time() + limit
            while _time.time() < deadline and not check():
                app.processEvents()
                _time.sleep(0.01)
            return check()

        win.startBiasCapture(3)
        assert wait_for(lambda: win.df_panel.bias is not None), "reference nepřišla"
        assert win.df_panel.bias.frames == 3

        win._requestSample()
        assert wait_for(lambda: len(win.df_panel.series) == 1), "měření nepřišlo"
        sample = win.df_panel.series.samples[0]
        assert sample.threshold > 0
        assert sample.coverage_pct >= 0.0
    finally:
        win.close()


def test_darkfield_background_stats_match_full_median():
    """Vzorkovaný odhad pozadí musí dát prakticky totéž co plný medián."""
    import numpy as np
    from bmscam import darkfield as df

    rng = np.random.default_rng(7)
    diff = rng.normal(3.0, 2.0, (1200, 1600)).astype(np.float32)
    diff[400:410, 500:510] = 200.0            # pár částic navíc
    median, sigma = df.background_stats(diff)
    full_median = float(np.median(diff))
    full_sigma = float(np.median(np.abs(diff - full_median))) * 1.4826
    assert abs(median - full_median) < 0.05, (median, full_median)
    assert abs(sigma - full_sigma) < 0.05, (sigma, full_sigma)


def test_darkfield_frame_store_roundtrip_and_reanalysis():
    """Uložené snímky jde přečíst zpátky a vyhodnotit znovu jiným prahem."""
    import shutil
    import tempfile

    import numpy as np
    from bmscam import darkfield as df

    folder = tempfile.mkdtemp()
    try:
        bias = df.Bias(np.full((90, 120), 10.0, np.float32), 4)
        store = df.FrameStore(folder)
        for step in range(3):
            frame = np.full((90, 120), 10, np.uint8)
            # každý snímek má o jednu částici víc – kontaminace přibývá
            for i in range(step + 1):
                frame[10 + 6 * i:14 + 6 * i, 20:24] = 200
            store.save(frame)
        assert store.count == 3
        assert store.bytes_used() > 0

        paths = df.FrameStore.list_frames(folder)
        assert len(paths) == 3
        back = df.FrameStore.load_frame(paths[0])
        assert back.shape == (90, 120) and back.max() == 200

        settings = df.Settings(sigma=5.0, min_area_px=2)
        series = df.reanalyze(paths, bias, settings)
        assert len(series) == 3
        counts = [int(s.particles) for s in series.samples]
        assert counts == [1, 2, 3], counts
        # zpětný rozbor s přísnějším prahem na velikost částice je vyhodí
        strict = df.Settings(sigma=5.0, min_area_px=1000)
        assert [int(s.particles) for s in df.reanalyze(paths, bias, strict).samples] \
            == [0, 0, 0]

        seen = []
        df.reanalyze(paths, bias, settings,
                     lambda done, total: seen.append((done, total)) or done < 2)
        assert seen == [(1, 3), (2, 3)], seen      # zrušeno po druhém snímku
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_darkfield_worker_runs_off_the_gui_thread():
    """Runner spočítá měření ve vlastním vlákně a vrátí je signálem."""
    import threading
    import time as _time
    from datetime import datetime

    import numpy as np

    from bmscam import darkfield as df
    from bmscam.ui.darkfield_worker import DarkFieldRunner

    app = _app()
    runner = DarkFieldRunner()
    try:
        gui_thread = threading.current_thread().ident
        threads, results = [], []
        runner.sampleReady.connect(
            lambda m, w: (threads.append(threading.current_thread().ident),
                          results.append(m)))

        bias = df.Bias(np.zeros((60, 80), np.float32), 1)
        gray = np.zeros((60, 80), np.uint8)
        gray[20:26, 30:36] = 180
        assert runner.submit(gray, bias, df.Settings(sigma=4.0, min_area_px=2),
                             datetime.now())
        # druhý snímek se má zahodit, dokud se počítá ten první
        runner.submit(gray, bias, df.Settings(), datetime.now())

        deadline = _time.time() + 10.0
        while _time.time() < deadline and not results:
            app.processEvents()
            _time.sleep(0.01)
        assert results, "výsledek nepřišel"
        assert results[0]["particles"] in (-1, 1)
        assert not runner.busy
        # výsledek se ohlásí ve vlákně GUI, ale spočítal se jinde
        assert threads[0] == gui_thread
        assert runner.dropped == 1
    finally:
        runner.shutdown()


def test_darkfield_panel_offers_reanalysis_and_frame_storage():
    """Panel má volby, na kterých stojí zpětný rozbor."""
    import shutil
    import tempfile

    from bmscam import darkfield as df
    from bmscam.ui.darkfield_panel import DarkFieldPanel

    _app()
    panel = DarkFieldPanel()
    try:
        # Výchozí interval je 10 s – živý rozbor každou sekundu je zbytečná zátěž.
        assert panel.spin_interval.value() == 10.0
        assert panel.wantsStoredFrames()
        assert panel.settings().store_frames

        folder = tempfile.mkdtemp()
        try:
            store = df.FrameStore(folder)
            store.save(__import__("numpy").zeros((20, 20), "uint8"))
            panel.setStoreInfo(store)
            assert "1 snímků" in panel.lbl_store.text()
            panel.setStoreInfo(None)
            assert panel.lbl_store.text() == ""
        finally:
            shutil.rmtree(folder, ignore_errors=True)

        asked = []
        panel.reanalyzeRequested.connect(lambda: asked.append(True))
        panel.reanalyzeRequested.emit()
        assert asked == [True]

        replacement = df.Series()
        replacement.add({"coverage_pct": 1.0, "particles": 2, "threshold": 5.0})
        panel.setSeries(replacement)
        assert len(panel.series) == 1
    finally:
        panel.deleteLater()


def test_demo_camera_renders_outside_pull():
    """pull() musí být levný – kreslení patří do vlákna kamery, ne do GUI."""
    import time as _time

    from bmscam.backends import DemoBackend

    cam = DemoBackend()
    cam.start(lambda event: None)
    try:
        deadline = _time.time() + 5.0
        while _time.time() < deadline and cam.pull() is None:
            _time.sleep(0.02)
        _time.sleep(0.3)                      # ať proběhne aspoň jedno kreslení

        worst = 0.0
        for _ in range(5):
            began = _time.perf_counter()
            frame = cam.pull()
            worst = max(worst, _time.perf_counter() - began)
            assert frame is not None
        # Dokud se kreslilo uvnitř pull(), stálo tohle přes 100 ms na snímek.
        assert worst < 0.02, f"pull() trvá {worst * 1000:.0f} ms"

        # obraz se opravdu mění, kreslení tedy běží
        first = bytes(cam.pull().data)
        changed = False
        deadline = _time.time() + 3.0
        while _time.time() < deadline and not changed:
            _time.sleep(0.05)
            changed = bytes(cam.pull().data) != first
        assert changed, "simulovaná kamera nedodává nové snímky"
    finally:
        cam.stop()


def test_darkfield_frame_store_handles_accented_path():
    """Cesta s diakritikou musí projít – cv2.imwrite na ní na Windows selže."""
    import shutil
    import tempfile

    import numpy as np

    from bmscam import darkfield as df

    root = tempfile.mkdtemp()
    folder = os.path.join(root, "Tomáš Michal", "BMS fotky", "měření")
    try:
        store = df.FrameStore(folder)
        original = np.zeros((40, 60), np.uint8)
        original[10:20, 15:25] = 200
        path = store.save(original)
        assert os.path.isfile(path), path
        assert os.path.getsize(path) > 0

        back = df.FrameStore.load_frame(path)
        assert np.array_equal(back, original), "snímek se nevrátil beze změny"
        assert df.FrameStore.list_frames(folder) == [path]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_led_panel_has_single_channel_buttons():
    """Rychlá volba jednoho kanálu pošle čistou barvu a hlásí vlnovou délku."""
    from bmscam.leds import CHANNELS, LedProtocol, channel
    from bmscam.ui.led_panel import LedPanel

    _app()
    panel = LedPanel()
    try:
        sent = []
        panel._send = sent.append          # bez připojeného Arduina

        assert set(panel.channel_buttons) == {"red", "green", "blue"}
        for key, name, rgb, typical, span in CHANNELS:
            btn = panel.channel_buttons[key]
            assert btn.text() == f"{typical} nm", btn.text()
            tip = btn.toolTip()
            assert span in tip and name in tip, tip

            sent.clear()
            btn.click()
            assert sent == [LedProtocol.all_color(rgb)], sent
            # barva se propíše i do jednotlivých stran
            assert all(w.color() == rgb for w in panel.panels)

        # čísla odpovídají katalogu WS2812B
        assert channel("red")[3] == 625
        assert channel("green")[3] == 520
        assert channel("blue")[3] == 470
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_exposure_report_names_the_culprit():
    """Závěr kontroly expozice musí rozlišit čtyři situace."""
    from bmscam.ui.main_window import MainWindow

    watched = [("aexpo", "automatika expozice"), ("expotime", "expoziční čas"),
               ("again", "zisk")]
    steady = [100.0, 100.4, 100.2]

    head, verdict, detail = MainWindow._exposureReport(
        watched, {"aexpo": 0, "expotime": 500, "again": 100}, {}, steady)
    assert "stabilní" in head.lower(), head
    assert "stálá na 500" in detail

    head, verdict, detail = MainWindow._exposureReport(
        watched, {"aexpo": 1, "expotime": 500, "again": 100}, {}, steady)
    assert "utomatika" in head and "vypněte" in verdict

    head, verdict, detail = MainWindow._exposureReport(
        watched, {"aexpo": 0, "expotime": 500, "again": 100},
        {"expotime": {600, 700}}, steady)
    assert "pozadí" in head, head
    assert "expoziční čas" in verdict
    assert "MĚNILA SE" in detail

    head, verdict, detail = MainWindow._exposureReport(
        watched, {"aexpo": 0, "expotime": 500, "again": 100}, {},
        [100.0, 130.0])
    assert "jas obrazu kolísá" in head, head
    assert "30.00" in verdict

    # bez jediného vzorku to nesmí spadnout
    head, verdict, detail = MainWindow._exposureReport(watched, {}, {}, [])
    assert "nehlásí" in detail


def test_exposure_check_runs_against_demo_camera():
    """Kontrola projde celou cestou přes skutečné okno a simulovanou kameru."""
    import time as _time

    from bmscam.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QMessageBox

    app = _app()
    win = MainWindow(prefer_demo=True)
    shown = QMessageBox.exec_
    QMessageBox.exec_ = lambda self: 0          # bez modálního okna
    try:
        win.connectCamera()
        deadline = _time.time() + 5.0
        while _time.time() < deadline and not win.view.hasImage():
            app.processEvents()
            _time.sleep(0.02)
        # simulovaná kamera startuje se zapnutou automatikou – to musí poznat
        win.camera.set("aexpo", 1)
        verdict = win.checkExposure(seconds=2.0)
        assert "vypněte" in verdict, verdict

        # s ruční expozicí už si nemá na co stěžovat
        win.camera.set("aexpo", 0)
        verdict = win.checkExposure(seconds=2.0)
        assert verdict, "kontrola nevrátila závěr"
        assert "vypněte" not in verdict, verdict
    finally:
        QMessageBox.exec_ = shown
        win.close()


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
