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
    """Vrátí sdílenou instanci QApplication (drženou po dobu běhu testů).

    Zároveň zahodí uložený stav panelů. Aplikace si ho při zavření okna
    ukládá do QSettings, takže bez úklidu by jeden test nastavoval podmínky
    dalšímu – a testy by se chovaly jinak podle pořadí."""
    global _APP
    from PyQt5.QtCore import QSettings
    from PyQt5.QtWidgets import QApplication
    if _APP is None:
        _APP = QApplication.instance() or QApplication(sys.argv[:1])
    stored = QSettings("BMS", "CamControl")
    stored.remove("darkfield")
    stored.sync()            # bez sync() čte jiná instance pořád starou hodnotu
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
        assert data[0][0] == "#"
        # sloupce se hledají podle názvu, ne podle pořadí – to se mění
        assert any("Pokrytí" in cell for cell in data[0])
        assert any("Kanál" in cell for cell in data[0])
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
        assert not panel.bias                    # prázdná sada referencí
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
        # sloupec se najde podle klíče – pořadí se časem mění
        coverage = [k for k, _, _ in df.COLUMNS].index("coverage_pct")
        assert panel.window_.table.item(2, coverage).text() == "1.0000"

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
        assert wait_for(lambda: bool(win.df_panel.bias)), "reference nepřišla"
        assert win.df_panel.bias.get().frames == 3

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
        assert runner.submit(gray, bias,
                             df.Settings(sigma=4.0, min_area_px=2,
                                         stack_frames=1),
                             datetime.now())
        # druhý snímek počká ve frontě, nezahodí se
        assert runner.submit(gray, bias, df.Settings(stack_frames=1),
                             datetime.now())

        deadline = _time.time() + 10.0
        while _time.time() < deadline and len(results) < 2:
            app.processEvents()
            _time.sleep(0.01)
        assert len(results) == 2, results
        assert results[0]["particles"] in (-1, 1)
        assert not runner.busy
        # výsledek se ohlásí ve vlákně GUI, ale spočítal se jinde
        assert threads[0] == gui_thread
        assert runner.dropped == 0
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
        # Výchozí interval je 5 s a měření vzniká z průměru pěti snímků.
        assert panel.spin_interval.value() == 5.0
        assert panel.spin_stack.value() == 5
        assert panel.settings().stack_frames == 5
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


def test_darkfield_multichannel_cycle():
    """Cyklus R → G → B: barva, expozice, tři řádky a návrat do původního stavu."""
    import time as _time

    from bmscam import darkfield as df
    from bmscam.ui.main_window import MainWindow

    app = _app()
    win = MainWindow(prefer_demo=True)
    try:
        win.connectCamera()

        def pump(check, limit=15.0):
            deadline = _time.time() + limit
            while _time.time() < deadline and not check():
                app.processEvents()
                _time.sleep(0.01)
            return check()

        assert pump(lambda: win.view.hasImage()), "demo kamera nedodala obraz"

        # osvětlení "připojíme" jen naoko – zajímá nás, co se pošle
        sent = []
        win.led_panel.link.is_open = lambda: True
        win.led_panel._send = sent.append

        panel = win.df_panel
        panel.chk_multi.setChecked(True)
        panel.spin_settle.setValue(0.05)
        panel.channel_rows["red"][0].setValue(1.0)
        panel.channel_rows["green"][0].setValue(2.0)
        panel.channel_rows["blue"][0].setValue(3.0)

        # Režim vyžaduje ruční expozici – s automatikou by se čas měnil sám.
        win.camera.set("aexpo", 0)
        base_expo = win.camera.get("expotime")
        base_focus = win.camera.get("afposition")

        # --- reference se snímá po kanálech
        win.startBiasCapture(2)
        assert pump(lambda: not win._mc_mode and len(panel.bias) == 3), \
            f"reference nedokončena: {len(panel.bias)} kanálů"
        assert panel.bias.missing(df.CHANNEL_ORDER) == []
        for key in df.CHANNEL_ORDER:
            assert panel.bias.get(key).frames == 2

        # --- jedno měření = tři řádky, po jednom na kanál
        expo_seen = {}
        original_apply = win._applyChannel

        def spy(channel, settings):
            original_apply(channel, settings)
            expo_seen[channel] = win.camera.get("expotime")

        win._applyChannel = spy
        panel.clearSeries()
        win._requestSample()
        assert pump(lambda: not win._mc_mode and len(panel.series) == 3), \
            f"cyklus nedoběhl: {len(panel.series)} řádků"

        assert [s.channel for s in panel.series.samples] == list(df.CHANNEL_ORDER)
        assert panel.series.channels() == list(df.CHANNEL_ORDER)

        # násobek expozice se opravdu propsal do kamery
        assert expo_seen["green"] > expo_seen["red"], expo_seen
        assert expo_seen["blue"] > expo_seen["green"], expo_seen

        # každý kanál dostal svou barvu
        for key in df.CHANNEL_ORDER:
            want = LedProtocolAllColor(df.CHANNEL_COLORS[key])
            assert want in sent, (key, sent)

        # po cyklu je expozice, ostření i barva zpátky
        assert win.camera.get("expotime") == base_expo
        assert win.camera.get("afposition") == base_focus
        assert win._mc_channel == ""
    finally:
        win.close()


def LedProtocolAllColor(rgb):
    from bmscam.leds import LedProtocol
    return LedProtocol.all_color(rgb)


def test_darkfield_multichannel_needs_the_board():
    """Bez připojeného Arduina se režim nespustí a řekne proč."""
    from bmscam.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QMessageBox

    _app()
    win = MainWindow(prefer_demo=True)
    shown = []
    original = QMessageBox.information
    QMessageBox.information = lambda parent, title, text, *a, **k: shown.append(text)
    try:
        win.connectCamera()
        win.camera.set("aexpo", 0)
        win.df_panel.chk_multi.setChecked(True)
        assert win._startChannelCycle("measure") is False
        assert shown and "Arduino" in shown[0], shown
        assert win._mc_mode == ""
    finally:
        QMessageBox.information = original
        win.close()


def test_darkfield_multichannel_reanalysis_keeps_channels():
    """Zpětný rozbor si vezme ke každému snímku referenci jeho kanálu."""
    import shutil
    import tempfile

    import numpy as np

    from bmscam import darkfield as df

    folder = tempfile.mkdtemp()
    try:
        biases = df.BiasSet()
        store = df.FrameStore(folder)
        for index, channel in enumerate(df.CHANNEL_ORDER):
            level = 10.0 + 20 * index          # každý kanál svítí jinak
            biases.put(channel, df.Bias(np.full((60, 80), level, np.float32), 4))
            frame = np.full((60, 80), int(level), np.uint8)
            frame[20:26, 30:36] = 200          # stejná částice ve všech
            store.save(frame, channel=channel)

        paths = df.FrameStore.list_frames(folder)
        assert [df.FrameStore.frame_channel(p) for p in paths] == \
            list(df.CHANNEL_ORDER)

        series = df.reanalyze(paths, biases, df.Settings(sigma=4.0, min_area_px=2))
        assert [s.channel for s in series.samples] == list(df.CHANNEL_ORDER)
        # správná reference = ve všech kanálech se najde táž jedna částice
        assert [int(s.particles) for s in series.samples] == [1, 1, 1]

        # Se špatnou referencí (jednou pro všechny) se rozbití pozná až
        # u pevného prahu – práh podle sigma je vůči posunu pozadí odolný,
        # protože si úroveň pozadí dopočítá z mediánu snímku.
        wrong = df.BiasSet({"": biases.get("red")})
        absolute = df.Settings(threshold_mode=df.THRESHOLD_ABSOLUTE,
                               absolute=15.0, min_area_px=2)
        good = df.reanalyze(paths, biases, absolute)
        bad = df.reanalyze(paths, wrong, absolute)
        assert [int(s.particles) for s in good.samples] == [1, 1, 1]
        assert all(s.coverage_pct < 1.0 for s in good.samples), \
            [s.coverage_pct for s in good.samples]
        # zelený a modrý snímek jsou proti červené referenci celé "nad prahem",
        # takže pokrytí vyskočí na sto procent – přesně to, čemu se má
        # vlastní referencí pro každý kanál předejít
        assert bad.samples[0].coverage_pct < 1.0
        assert bad.samples[1].coverage_pct > 99.0, bad.samples[1].coverage_pct
        assert bad.samples[2].coverage_pct > 99.0, bad.samples[2].coverage_pct
    finally:
        shutil.rmtree(folder, ignore_errors=True)




def test_measurement_autosaves_and_starts_a_fresh_series():
    """Zastavení uloží tabulku, spuštění začne s prázdnou řadou."""
    import glob as _glob
    import shutil
    import tempfile

    from bmscam.ui.main_window import MainWindow

    _app()
    folder = tempfile.mkdtemp()
    win = MainWindow(prefer_demo=True)
    try:
        win.save_dir = folder
        # čerstvá reference, ať se měření nezastaví kvůli automatickému snímání
        import numpy as np

        from bmscam import darkfield as df
        win.df_panel.setBias(df.Bias(np.zeros((16, 16), np.float32), 16))
        win.df_panel.addSample({"coverage_pct": 1.0, "particles": 2,
                                "area_px": 10, "threshold": 5.0})
        assert len(win.df_panel.series) == 1

        win._onDarkFieldToggled(False, 1.0)          # zastavení měření
        csvs = _glob.glob(os.path.join(folder, "*.csv"))
        assert len(csvs) == 1, csvs

        # Nové spuštění vyžaduje kameru; řada se maže hned po jejím ověření.
        win.connectCamera()
        win._onDarkFieldToggled(True, 1.0)
        assert len(win.df_panel.series) == 0
        win._onDarkFieldToggled(False, 1.0)
    finally:
        win.close()
        shutil.rmtree(folder, ignore_errors=True)


def test_settings_go_to_their_own_folder():
    """Nastavení se ukládá do podsložky „nastavení“, která se sama založí."""
    import shutil
    import tempfile

    from bmscam import workspace
    from bmscam.ui.main_window import MainWindow

    _app()
    folder = tempfile.mkdtemp()
    win = MainWindow(prefer_demo=True)
    try:
        win.save_dir = os.path.join(folder, "BMS fotky")
        target = win._settingsDir()
        assert os.path.isdir(target)
        assert os.path.basename(target) == workspace.SETTINGS_FOLDER
        assert workspace.default_name(target).startswith(target)
    finally:
        win.close()
        shutil.rmtree(folder, ignore_errors=True)


def test_reference_is_saved_automatically_with_its_conditions():
    """Reference se uloží sama a vedle ní i popis nastavení."""
    import glob as _glob
    import json
    import shutil
    import tempfile
    import time as _time

    from bmscam import darkfield as df
    from bmscam.ui.main_window import MainWindow

    app = _app()
    folder = tempfile.mkdtemp()
    win = MainWindow(prefer_demo=True)
    win.connectCamera()
    try:
        win.save_dir = folder
        deadline = _time.time() + 5.0
        while _time.time() < deadline and not win.view.hasImage():
            app.processEvents()
            _time.sleep(0.02)

        win.startBiasCapture(2)
        deadline = _time.time() + 10.0
        while _time.time() < deadline and not win.df_panel.bias:
            app.processEvents()
            _time.sleep(0.01)
        assert win.df_panel.bias, "reference nepřišla"

        ref_dir = os.path.join(folder, "reference")
        npz = _glob.glob(os.path.join(ref_dir, "*.npz"))
        meta = _glob.glob(os.path.join(ref_dir, "*.json"))
        assert len(npz) == 1 and len(meta) == 1, (npz, meta)

        # popis podmínek jde přečíst zpátky ze souboru s referencí
        loaded = df.BiasSet.load(npz[0])
        assert loaded.note(), "u reference chybí popis nastavení"
        with open(meta[0], encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["reference"]["file"] == os.path.basename(npz[0])
        assert "darkfield" in data and "leds" in data
    finally:
        win.close()
        shutil.rmtree(folder, ignore_errors=True)


def test_runner_queues_frames_instead_of_dropping_them():
    """Když rozbor nestíhá, snímky čekají ve frontě a dopočítají se."""
    import time as _time

    import numpy as np

    from bmscam import darkfield as df
    from bmscam.ui.darkfield_worker import DarkFieldRunner

    app = _app()
    runner = DarkFieldRunner()
    try:
        got = []
        runner.sampleReady.connect(lambda m, w: got.append(m))
        gray = np.zeros((64, 64), "uint8")
        gray[10:14, 10:14] = 200
        settings = df.Settings(stack_frames=1)
        for _ in range(5):
            assert runner.submit(gray.copy(), None, settings, None)
        assert runner.pending > 1, "fronta se vůbec nenaplnila"

        deadline = _time.time() + 10.0
        while _time.time() < deadline and len(got) < 5:
            app.processEvents()
            _time.sleep(0.01)
        assert len(got) == 5, got
        assert runner.dropped == 0
        assert runner.pending == 0

        # Fronta je omezená objemem dat, ne počtem snímků.
        runner.max_queued_bytes = gray.nbytes * 2
        runner.busy = True                      # nikdo teď frontu nevybírá
        accepted = [runner.submit(gray.copy(), None, settings, None)
                    for _ in range(5)]
        assert accepted[0] and not accepted[-1], accepted
        assert runner.dropped > 0
        assert runner.clearQueue() > 0
    finally:
        runner.shutdown()


def test_stopping_measurement_finishes_the_backlog():
    """Zastavení měření dopočítá, co ještě viselo ve frontě."""
    import shutil
    import tempfile
    import time as _time

    import numpy as np

    from bmscam import darkfield as df
    from bmscam.ui.main_window import MainWindow

    app = _app()
    folder = tempfile.mkdtemp()
    win = MainWindow(prefer_demo=True)
    try:
        win.save_dir = folder
        gray = np.zeros((64, 64), "uint8")
        settings = df.Settings(stack_frames=1)
        for _ in range(4):
            win.df_runner.submit(gray.copy(), None, settings, None)
        assert win.df_runner.pending > 1

        win._onDarkFieldToggled(False, 1.0)     # zastavení měření
        assert win.df_runner.pending == 0, "fronta se nedopočítala"
        assert len(win.df_panel.series) == 4
        assert win.df_runner.dropped == 0
        for _ in range(5):
            app.processEvents()
    finally:
        win.close()
        shutil.rmtree(folder, ignore_errors=True)


def test_led_cross_buttons_follow_the_real_layout():
    """Zapínání stran je v kříži a drží stejný stav jako karty."""
    from bmscam.leds import PANEL_NAMES
    from bmscam.ui.led_panel import LedPanel

    app = _app()
    panel = LedPanel()
    try:
        assert len(panel.cross_buttons) == 4
        grid = panel.cross_buttons[0].parentWidget().layout()

        def cell(widget):
            index = grid.indexOf(widget)
            row_, col, _, _ = grid.getItemPosition(index)
            return row_, col

        # horní nahoře uprostřed, levá vlevo, pravá vpravo, dolní dole
        assert cell(panel.cross_buttons[0]) == (0, 1)
        assert cell(panel.cross_buttons[3]) == (1, 0)
        assert cell(panel.cross_buttons[1]) == (1, 2)
        assert cell(panel.cross_buttons[2]) == (2, 1)
        assert panel.cross_buttons[0].text() == PANEL_NAMES[0]

        # tlačítko přepne kartu a karta přepne tlačítko
        panel.cross_buttons[1].setChecked(True)
        panel.cross_buttons[1].clicked.emit(True)
        app.processEvents()
        assert panel.panels[1].isOn()
        panel.panels[1].chk_on.setChecked(False)
        app.processEvents()
        assert not panel.cross_buttons[1].isChecked()
    finally:
        panel.shutdown()


def test_queue_limit_is_settable_from_the_gui():
    """Strop fronty jde přenastavit v okně a projeví se hned."""
    from bmscam.ui.main_window import MainWindow

    app = _app()
    win = MainWindow(prefer_demo=True)
    try:
        assert win.df_runner.max_queued_bytes == \
            win.df_panel.spin_queue.value() * 1024 * 1024
        win.df_panel.spin_queue.setValue(512)
        app.processEvents()
        assert win.df_runner.max_queued_bytes == 512 * 1024 * 1024
        # hodnota se uloží i do souboru s kompletním nastavením
        assert win.df_panel.settings().queue_mb == 512
        win.df_panel.applySettings({"queue_mb": 1024})
        app.processEvents()
        assert win.df_runner.max_queued_bytes == 1024 * 1024 * 1024
    finally:
        win.settings.remove("df_queue_mb")
        win.close()


def test_camera_switches_between_color_and_mono():
    """Přepínač v liště přepne kameru mezi barevným a černobílým obrazem."""
    import numpy as np

    from bmscam import darkfield as df
    from bmscam.ui.main_window import MainWindow

    app = _app()
    win = MainWindow(prefer_demo=True)
    win.connectCamera()
    try:
        assert win.seg_color.isEnabled(), "kamera hlásí, že režim umí"
        assert not win.isMonochrome()

        def frame_gray():
            frame = win.camera.pull()
            raw = np.frombuffer(frame.data, dtype=np.uint8)
            raw = raw[: frame.stride * frame.height].reshape(frame.height,
                                                             frame.stride)
            return raw[:, : frame.width * 3].reshape(frame.height, frame.width, 3)

        win.seg_color.setCurrentIndex(1)          # jako kliknutí na „Černobíle“
        app.processEvents()
        assert win.isMonochrome()
        assert win.camera.get("chrome") == 1
        # kamera může mít rozpracovaný ještě barevný snímek – počkáme na další
        import time as _time
        deadline = _time.time() + 5.0
        while _time.time() < deadline:
            pixels = frame_gray()
            if np.array_equal(pixels[:, :, 0], pixels[:, :, 2]):
                break
            app.processEvents()
            _time.sleep(0.05)
        assert np.array_equal(pixels[:, :, 0], pixels[:, :, 2]), "obraz není šedý"
        # dark field pozná černobílý obraz a nemusí složky průměrovat
        assert df.to_gray_u8(win.camera.pull()).ndim == 2

        # barevné doladění nemá v černobílém režimu co dělat
        for panel in win.panels.values():
            row_ = panel.rows.get("saturation")
            if row_ is not None and getattr(row_, "slider", None) is not None:
                assert not row_.slider.isEnabled()

        win.seg_color.setCurrentIndex(0)
        app.processEvents()
        assert not win.isMonochrome()
        assert win.camera.get("chrome") == 0
    finally:
        win.close()


def test_frame_stacker_averages_and_cuts_noise():
    """Průměr snímků potlačí šum a respektuje kanál i rozlišení."""
    import numpy as np

    from bmscam import darkfield as df

    rng = np.random.default_rng(11)
    base = np.full((60, 80), 100.0)
    stacker = df.FrameStacker(5)
    single = None
    for index in range(5):
        noisy = np.clip(base + rng.normal(0, 12, base.shape), 0, 255).astype("uint8")
        if single is None:
            single = noisy
        done = stacker.add(noisy, None, "")
        assert done == (index == 4)
    average = stacker.result()
    assert average.dtype == np.uint8
    assert abs(float(average.mean()) - 100.0) < 1.5
    # šum klesne zhruba na 1/sqrt(5); s rezervou stačí ověřit, že klesl
    assert average.std() < single.std() * 0.7

    # jiný kanál nebo rozlišení rozdělanou dávku zahodí
    stacker = df.FrameStacker(3)
    stacker.add(np.zeros((10, 10), "uint8"), None, "red")
    stacker.add(np.zeros((10, 10), "uint8"), None, "green")
    assert stacker.taken == 1 and stacker.channel == "green"
    stacker.add(np.zeros((12, 12), "uint8"), None, "green")
    assert stacker.taken == 1


def test_measurement_stacks_frames_into_one_png():
    """Z pěti dílčích snímků vznikne jedno měření a jeden uložený PNG."""
    import shutil
    import tempfile
    import time as _time

    import numpy as np

    from bmscam import darkfield as df
    from bmscam.ui.darkfield_worker import DarkFieldRunner

    app = _app()
    folder = tempfile.mkdtemp()
    runner = DarkFieldRunner()
    try:
        samples, progress = [], []
        runner.sampleReady.connect(lambda m, w: samples.append(m))
        runner.stackProgress.connect(lambda t, c: progress.append((t, c)))

        store = df.FrameStore(folder)
        settings = df.Settings(stack_frames=5)
        gray = np.full((40, 50), 100, "uint8")
        for _ in range(5):
            assert runner.submit(gray.copy(), None, settings, None, store)

        deadline = _time.time() + 10.0
        while _time.time() < deadline and not samples:
            app.processEvents()
            _time.sleep(0.01)
        assert len(samples) == 1, samples
        assert progress[0] == (1, 5) and progress[-1] == (5, 5)

        # na disku je jediný snímek – ten zprůměrovaný
        paths = df.FrameStore.list_frames(folder)
        assert len(paths) == 1, paths
        assert paths[0].endswith(".png") or paths[0].endswith(".npz")
        stored = df.FrameStore.load_frame(paths[0])
        assert stored.shape == gray.shape
        assert abs(float(stored.mean()) - 100.0) < 1.0
    finally:
        runner.shutdown()
        shutil.rmtree(folder, ignore_errors=True)


def test_old_settings_load_without_stacking():
    """Soubor ze starší verze se načte se stejným chováním jako tehdy."""
    from bmscam.ui.darkfield_panel import DarkFieldPanel

    _app()
    panel = DarkFieldPanel()
    # starší verze průměrování neznala – interval znamenal jeden snímek
    panel.applySettings({"interval_s": 1.0, "threshold_mode": "sigma",
                         "sigma": 5.0, "min_area_px": 2})
    assert panel.spin_interval.value() == 1.0
    assert panel.spin_stack.value() == 1
    assert panel.settings().stack_frames == 1

    # dnešní soubor si počet snímků nese s sebou
    panel.applySettings({"interval_s": 5.0, "stack_frames": 4})
    assert panel.spin_stack.value() == 4


def test_dark_mode_repaints_the_whole_window():
    """Tmavý režim přebarví i prvky s vlastním stylopisem."""
    from PyQt5.QtWidgets import QApplication

    from bmscam.ui import theme
    from bmscam.ui.main_window import MainWindow

    app = _app()
    app.setStyleSheet(theme.stylesheet())
    win = MainWindow(prefer_demo=True)
    win.resize(1200, 800)
    win.show()
    try:
        for _ in range(20):
            app.processEvents()
        assert theme.mode() == "light"
        light_bg = theme.BG

        win.setDarkMode(True)
        for _ in range(20):
            app.processEvents()
        assert theme.mode() == "dark"
        assert theme.BG != light_bg
        assert "dark" in theme.stylesheet() or theme.BG in theme.stylesheet()

        # plochy se opravdu překreslily – vzorek pixelu z levého panelu
        image = win.grab().toImage()
        corner = win.left_panel.mapTo(win, win.left_panel.rect().topLeft())
        assert image.pixelColor(corner.x() + 6, corner.y() + 6).name() == theme.BG

        # prvky s vlastním stylopisem dostaly nové barvy
        assert theme.DIVIDER in win.seg_tabs.styleSheet()
        assert theme.ACCENT in win.led_panel.cross_buttons[0].styleSheet()
        assert theme.ON_ACCENT in win.led_panel.cross_buttons[0].styleSheet()

        win.setDarkMode(False)
        for _ in range(10):
            app.processEvents()
        assert theme.mode() == "light" and theme.BG == light_bg
        assert theme.DIVIDER in win.seg_tabs.styleSheet()
    finally:
        win.settings.remove("dark_mode")
        win.close()
        theme.set_mode("light")
        app.setStyleSheet(theme.stylesheet())


def test_theme_hooks_do_not_keep_widgets_alive():
    """Registrace překreslení nesmí držet zavřené okno v paměti."""
    import gc

    from bmscam.ui import theme
    from bmscam.ui.widgets import SegmentedControl

    _app()
    theme.refresh()               # zahodí odkazy na widgety z jiných testů
    before = len(theme._hooks)
    control = SegmentedControl(["A", "B"])
    assert len(theme._hooks) > before
    del control
    gc.collect()
    theme.refresh()               # mrtvé odkazy se přitom zahodí
    assert len(theme._hooks) == before


def test_dfa_analysis_separates_haze_particles_and_fibers():
    """Rozbor převzatý z DarkFieldAnalyzeru rozliší opar, částice a vlákna."""
    import numpy as np

    from bmscam import darkfield as df, dfa

    if not dfa.available():                     # bez OpenCV se test nedá udělat
        return

    rng = np.random.default_rng(4)
    clean = rng.normal(20.0, 1.5, (600, 800)).astype(np.float32)
    bias = df.Bias(clean.copy(), 8)

    frame = clean.copy()
    frame[200:206, 300:306] += 60.0             # kompaktní částice
    frame[400:404, 100:200] += 45.0             # vlákno / škrábanec
    frame[:, :] += 0.0
    image = np.clip(frame, 0, 255).astype(np.uint8)

    settings = df.Settings(sigma=5.0, min_area_px=3)
    metrics = df.analyze(image, bias, settings)
    assert metrics["method"] == df.METHOD_DFA
    assert metrics["fibers"] >= 1, metrics
    assert metrics["points"] >= 1, metrics
    assert metrics["threshold"] >= settings.min_threshold_adu
    assert 0.0 <= metrics["cleanliness"] <= 100.0

    # difuzní zamlžení: plošný nárůst přes celý snímek se pozná jako opar,
    # ne jako obrovská částice
    hazy = np.clip(clean + 9.0, 0, 255).astype(np.uint8)
    haze_metrics = df.analyze(hazy, bias, settings)
    assert haze_metrics["haze_pct"] > 50.0, haze_metrics
    assert haze_metrics["haze_mean"] > 4.0
    assert haze_metrics["coverage_pct"] > 50.0
    assert haze_metrics["cleanliness"] < metrics["cleanliness"]

    # velký snímek se před rozborem zmenší (binning), jinak by segmentace
    # šumu na 4K trvala vteřiny
    from bmscam import dfa as _dfa
    assert _dfa.resolve_binning(2160) == 2 and _dfa.resolve_binning(720) == 1
    assert metrics.get("binning") == 1        # 600 px vysoký snímek se nezmenšuje

    # čisté sklíčko: skoro nulové pokrytí, vysoká čistota
    quiet = np.clip(clean + rng.normal(0, 1.5, clean.shape), 0, 255).astype(np.uint8)
    empty = df.analyze(quiet, bias, settings)
    assert empty["coverage_pct"] < 1.0, empty
    assert empty["cleanliness"] > 90.0


def test_analysis_falls_back_without_opencv():
    """Bez OpenCV se použije jednoduchá metoda, měření se nezastaví."""
    import numpy as np

    from bmscam import darkfield as df

    image = np.full((80, 100), 20, np.uint8)
    image[30:36, 40:46] = 200
    bias = df.Bias(np.full((80, 100), 20.0, np.float32), 4)
    metrics = df.analyze(image, bias, df.Settings(method=df.METHOD_SIMPLE))
    assert metrics["method"] == df.METHOD_SIMPLE
    assert metrics["coverage_pct"] > 0.0


def test_sample_material_and_temperature_reach_names_and_graphs():
    """Materiál a teplota se dostanou do názvů souborů, CSV i grafu."""
    import shutil
    import tempfile

    from bmscam import darkfield as df
    from bmscam.ui.main_window import MainWindow

    _app()
    folder = tempfile.mkdtemp()
    win = MainWindow(prefer_demo=True)
    try:
        win.save_dir = folder
        panel = win.df_panel
        index = panel.cmb_material.findData("pla")
        assert index > 0, "materiál PLA v nabídce chybí"
        panel.cmb_material.setCurrentIndex(index)
        panel.spin_temp.setValue(120.0)
        assert panel.sampleTag() == "pla_120C"
        assert panel.sampleLabel() == "PLA · 120 °C"
        assert panel.settings().material == "pla"
        assert panel.settings().temperature_c == 120.0

        # složka měření i CSV nesou značku vzorku
        directory = win._makeDarkFieldDir()
        assert os.path.basename(directory).endswith("_pla_120C"), directory
        panel.addSample({"coverage_pct": 1.0, "particles": 2,
                         "particle_area_px": 10, "threshold": 5.0})
        csv_path = panel.autoSaveSeries(folder)
        assert "pla_120C" in os.path.basename(csv_path), csv_path
        with open(csv_path, encoding="utf-8-sig") as fh:
            head = fh.read(2000)
        assert "PLA · 120 °C" in head

        # graf i titulek okna vzorek pojmenují
        panel.showTable()
        window = panel.window_
        assert "PLA" in window.windowTitle() or "PLA" in window._chartTitle("Pokrytí")

        # a uložené nastavení si materiál i teplotu pamatuje
        panel.applySettings({"material": "kapton", "temperature_c": 80.0})
        assert panel.sampleTag() == "kapton_80C"
        assert df.material_title("kapton") == "Kaptonová páska"
    finally:
        win.close()
        shutil.rmtree(folder, ignore_errors=True)


def _make_series(folder, frames=8, size=(360, 480), rng_seed=3):
    """Vyrobí umělou sérii snímků s přibývajícími částicemi."""
    import numpy as np
    import cv2

    rng = np.random.default_rng(rng_seed)
    base = rng.normal(18.0, 2.0, size).astype(np.float32)
    paths = []
    for index in range(frames):
        frame = base + rng.normal(0, 1.0, size)
        for _ in range(2 + index):
            y = int(rng.integers(5, size[0] - 6))
            x = int(rng.integers(5, size[1] - 6))
            frame[y:y + 4, x:x + 4] += 70.0
        name = "df_{:05d}_20260910_1200{:02d}_000.png".format(index + 1, index)
        path = os.path.join(folder, name)
        cv2.imwrite(path, np.clip(frame, 0, 255).astype("uint8"))
        paths.append(path)
    return paths


def test_vendored_core_matches_upstream_analyzer():
    """Převzaté jádro musí dát stejná čísla jako DarkFieldAnalyzer.

    Porovnává se proti *upstream* kopii, pokud je na stroji k dispozici;
    jinak se aspoň ověří, že dávkový rozbor a živý rozbor jednoho snímku
    počítají totéž. Právě kvůli téhle shodě se jádro vendorovalo, místo
    aby se metoda psala znovu."""
    import shutil
    import tempfile

    import numpy as np

    from bmscam import darkfield as df
    from bmscam.dfa import analyzer as core, frameio

    folder = tempfile.mkdtemp()
    try:
        paths = _make_series(folder)
        params = core.AnalysisParams(bias_frames=3, binning=1, align_frames=False)
        result = core.analyze_series(frameio.list_image_files(folder), params)
        assert result.metrics, result.warnings
        assert result.bias is not None

        # Živý rozbor jednoho snímku (jak běží u kamery) musí dát stejná
        # čísla jako dávkový rozbor téhož snímku se stejným pozadím.
        last = result.metrics[-1]
        frame = frameio.load_frame(last.filepath, full_scale=result.bias.full_scale,
                                   mono_mode=params.mono_mode)
        settings = df.Settings(sigma=params.sigma, min_area_px=params.min_area_px,
                               absolute=params.absolute_threshold,
                               haze_threshold=params.haze_threshold,
                               cluster_min_area_px=params.cluster_min_area_px,
                               fiber_aspect_ratio=params.fiber_aspect_ratio,
                               fiber_min_length_px=params.fiber_min_length_px,
                               saturation_adu=params.saturation_adu,
                               min_threshold_adu=params.min_threshold_adu,
                               binning=1, um_per_px=params.um_per_px)
        live = df.analyze(frame.data, df.Bias(result.bias.data, 3), settings)
        assert abs(live["coverage_pct"] - last.total_coverage_pct) < 1e-9
        assert live["particles"] == last.total_particle_count
        assert live["points"] == last.point_count
        assert abs(live["threshold"] - last.applied_threshold) < 1e-9
        assert abs(live["cleanliness"] - last.cleanliness_score) < 1e-9
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_analyzer_screen_runs_a_batch_and_reloads_it():
    """Obrazovka rozboru projde celý postup: složka → rozbor → tabulka → CSV."""
    import shutil
    import tempfile
    import time as _time

    from bmscam.ui.analyzer_screen import AnalyzerScreen
    from bmscam.ui.main_window import MainWindow

    app = _app()
    base = tempfile.mkdtemp()
    folder = os.path.join(base, "darkfield_20260910_120000_pla_120C")
    os.makedirs(folder)
    try:
        _make_series(folder, frames=6)
        win = MainWindow(prefer_demo=True)
        try:
            win.showScreen(1)                     # obrazovka se staví až teď
            app.processEvents()
            screen = win.analyzer
            assert isinstance(screen, AnalyzerScreen)
            screen.base_dir = base
            screen.refreshFolders()
            assert screen.tbl_folders.rowCount() >= 1
            screen.tbl_folders.selectRow(0)
            assert screen.selected_folder == folder

            screen.spin_bias.setValue(2)
            screen.chk_align.setChecked(False)
            screen.cmb_binning.setCurrentIndex(1)      # plné rozlišení
            screen.startAnalysis()
            deadline = _time.time() + 60.0
            while _time.time() < deadline and screen.result is None:
                app.processEvents()
                _time.sleep(0.02)
            assert screen.result is not None, "rozbor nedoběhl"
            assert screen.tbl_results.rowCount() == len(screen.result.metrics)
            assert "Souhrn" in screen.txt_summary.toHtml()

            # prohlížeč dostal sérii a umí vykreslit snímek
            assert screen.viewer.image_paths
            screen.viewer.render_current_frame()
            app.processEvents()
            assert "Pokrytí" in screen.viewer.status_lbl.text()

            # export a zpětné načtení tabulky
            from bmscam.dfa import exporter
            csv_path = os.path.join(folder, "analyza.csv")
            exporter.export_to_csv(screen.result.metrics, csv_path,
                                   screen.result.params, folder_name="test")
            header, rows = AnalyzerScreen._readCsv(csv_path)
            assert header[0] == "Index"
            assert len(rows) == len(screen.result.metrics)

            # průvodce metodou je součástí obrazovky
            titles = [screen.tabs.tabText(i) for i in range(screen.tabs.count())]
            assert titles == ["Snímky", "Tabulka", "Souhrn", "Grafy", "Průvodce"]
        finally:
            win.close()
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_guide_document_follows_the_palette():
    """Nápověda převzatá z DarkFieldAnalyzeru se v tmavém režimu přebarví."""
    from bmscam.dfa import help_text
    from bmscam.ui import theme

    light = theme.document_html(help_text.HELP_HTML)
    assert light == help_text.HELP_HTML, "světlý režim nechává dokument beze změny"
    try:
        theme.set_mode("dark")
        dark = theme.document_html(help_text.HELP_HTML)
        assert "#F8F9FA" not in dark, "papírové pozadí zůstalo v tmavém režimu"
        assert theme.SURFACE in dark and theme.TEXT in dark
    finally:
        theme.set_mode("light")


def test_screen_switch_survives_a_broken_analyzer():
    """Když obrazovku analýzy nejde postavit, program to řekne a běží dál."""
    from PyQt5.QtWidgets import QMessageBox

    from bmscam.ui import analyzer_screen
    from bmscam.ui.main_window import MainWindow

    app = _app()
    win = MainWindow(prefer_demo=True)
    original = analyzer_screen.AnalyzerScreen
    warnings = []
    original_warning = QMessageBox.warning
    QMessageBox.warning = staticmethod(
        lambda *args, **kwargs: warnings.append(args[2]) or QMessageBox.Ok)
    try:
        class Broken:
            def __init__(self, *args, **kwargs):
                raise ImportError("libGL.so.1: cannot open shared object file")

        analyzer_screen.AnalyzerScreen = Broken
        win.showScreen(1)
        app.processEvents()
        assert win.analyzer is None
        assert win.screens.currentIndex() == 0, "zůstalo se u kamery"
        assert win.seg_screen.currentIndex() == 0
        assert warnings and "OpenCV" in warnings[0]

        # po opravě prostředí se obrazovka postaví normálně
        analyzer_screen.AnalyzerScreen = original
        win.showScreen(1)
        app.processEvents()
        assert win.analyzer is not None
        assert win.screens.currentIndex() == 1
    finally:
        QMessageBox.warning = original_warning
        analyzer_screen.AnalyzerScreen = original
        win.close()


def test_opencv_preload_runs_before_qt():
    """Spouštěč načte OpenCV dřív, než vznikne QApplication."""
    import subprocess

    from bmscam import qtenv

    assert qtenv.preload_opencv() is None or True     # jen nesmí spadnout

    code = ("import sys;"
            " from bmscam import qtenv;"
            " err = qtenv.preload_opencv();"
            " from PyQt5.QtWidgets import QApplication;"
            " print('cv2' in sys.modules, QApplication.instance() is None)")
    out = subprocess.run([sys.executable, "-c", code], cwd=_ROOT,
                         capture_output=True, text=True)
    assert out.stdout.strip() == "True True", out.stdout + out.stderr


def test_reference_written_here_is_readable_by_the_analyzer():
    """Reference z měření musí obrazovka analýzy přečíst a popsat.

    Přesně tady spadl program uživateli: popis reference sahal na pole,
    které záznam ReferenceRecord nemá."""
    import shutil
    import tempfile

    import numpy as np

    from bmscam import darkfield as df, workspace
    from bmscam.dfa import reference as refmod
    from bmscam.ui.analyzer_screen import AnalyzerScreen
    from bmscam.ui.main_window import MainWindow

    app = _app()
    base = tempfile.mkdtemp()
    measurement = os.path.join(base, "darkfield_20260910_120000")
    ref_dir = os.path.join(base, "reference")
    os.makedirs(measurement)
    os.makedirs(ref_dir)
    try:
        # reference se uloží přesně tak, jak ji ukládá měření
        bias = df.BiasSet()
        bias.put("", df.Bias(np.full((60, 80), 12.0, np.float32), 16))
        npz = os.path.join(ref_dir, "reference_20260910_115000.npz")
        bias.save(npz, "expozice 20 ms · zisk 100")
        data = workspace.new(capture={"save_dir": base})
        data["reference"] = {"file": os.path.basename(npz),
                             "describe": bias.describe(), "note": "test"}
        workspace.save(os.path.join(ref_dir, "reference_20260910_115000.json"), data)

        records = refmod.list_references(ref_dir)
        assert len(records) == 1
        assert records[0].name.endswith(".npz")
        assert records[0].label

        win = MainWindow(prefer_demo=True)
        try:
            win.showScreen(1)
            app.processEvents()
            screen = win.analyzer
            assert isinstance(screen, AnalyzerScreen)
            screen.base_dir = base
            screen.selected_folder = measurement
            screen.reference_dir = ref_dir
            screen.updateReferenceInfo()
            text = screen.lbl_reference.text()
            assert "1 referencí" in text, text
            assert "reference_20260910_115000.npz" in text
            assert "nejde" not in text.lower(), text

            # a načtení dat reference projde celým řetězcem až k biasu
            planes = refmod.load_reference(records[0])
            assert planes.mono.shape == (60, 80)
        finally:
            win.close()
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_unhandled_exception_shows_a_dialog_instead_of_killing_the_app():
    """Chyba ve slotu nesmí ukončit proces – PyQt5 by jinak zavolal abort."""
    import sys as _sys

    from bmscam.ui import errors

    _app()
    errors._installed = False
    original = _sys.excepthook
    try:
        errors.install("Test")
        assert _sys.excepthook is not original
        shown = []
        from PyQt5.QtWidgets import QMessageBox
        original_exec = QMessageBox.exec_
        QMessageBox.exec_ = lambda self: shown.append(self.text()) or 0
        try:
            _sys.excepthook(ValueError, ValueError("rozbité"), None)
        finally:
            QMessageBox.exec_ = original_exec
        assert shown and "rozbité" in shown[0]
    finally:
        _sys.excepthook = original
        errors._installed = False


def test_ui_only_touches_fields_the_vendored_core_really_has():
    """Smlouva mezi rozhraním a převzatým jádrem.

    Pád u uživatele vznikl tím, že obrazovka sáhla na pole, které záznam
    reference nemá. Tenhle test projde všechna pole, na která rozhraní
    sahá, aby se to při příští aktualizaci jádra poznalo hned."""
    from dataclasses import fields

    from bmscam.dfa import analyzer as core, exporter, frameio, reference
    from bmscam.dfa.alignment import AlignmentModel
    from bmscam.dfa.live import _METRIC_MAP

    def has(cls, name):
        return (name in {f.name for f in fields(cls)}
                if hasattr(cls, "__dataclass_fields__") else hasattr(cls, name)) \
            or hasattr(cls, name)

    for name in ("name", "label", "npz_path", "created"):
        assert has(reference.ReferenceRecord, name), name
    for name in ("data", "frames_used", "binning", "full_scale", "is_external",
                 "reference_path", "reference_label", "level_offset_adu"):
        assert has(core.BiasModel, name), name
    for name in ("measured_drift_px", "crop", "crop_fraction", "usable",
                 "measure", "hot_mask"):
        assert has(AlignmentModel, name), name
    for name in ("metrics", "bias", "params", "alignment", "elapsed_s",
                 "cancelled", "warnings", "notes"):
        assert has(core.SeriesResult, name), name
    for name in ("is_bias_frame", "timestamp", "filepath", "align_ok"):
        assert has(core.FrameMetrics, name), name

    # metriky, které živý rozbor překládá na sloupce tabulky
    metric_names = {f.name for f in fields(core.FrameMetrics)}
    for _ours, theirs in _METRIC_MAP:
        assert theirs in metric_names, theirs
    for _name, attr, _spec in exporter.CSV_COLUMNS:
        assert attr is None or attr in metric_names, attr

    for module, names in ((exporter, ("summarize", "export_all", "export_to_csv",
                                      "export_summary_plots", "_fmt")),
                          (frameio, ("list_image_files", "list_measurement_folders",
                                     "load_frame", "build_time_axis")),
                          (reference, ("find_reference_dir", "list_references",
                                       "load_reference"))):
        for name in names:
            assert hasattr(module, name), f"{module.__name__}.{name}"


def test_live_table_matches_the_batch_analysis_row_by_row():
    """Živé měření musí dát stejné řádky jako dávková analýza.

    Tohle je smysl celého vendorovaného jádra: „Tabulka a graf“ u kamery
    ukazuje totéž, co by vyšlo, kdyby se stejné snímky pustily obrazovkou
    Analýza – včetně rychlostí změn a klasifikace fáze děje."""
    import shutil
    import tempfile

    from bmscam import darkfield as df
    from bmscam.dfa import analyzer as core, frameio

    folder = tempfile.mkdtemp()
    try:
        _make_series(folder, frames=10, size=(300, 400), rng_seed=9)
        params = core.AnalysisParams(bias_frames=3, binning=1, align_frames=False)
        result = core.analyze_series(frameio.list_image_files(folder), params)
        assert len(result.metrics) >= 5, result.warnings

        settings = df.Settings(
            sigma=params.sigma, min_area_px=params.min_area_px,
            haze_threshold=params.haze_threshold,
            cluster_min_area_px=params.cluster_min_area_px,
            fiber_aspect_ratio=params.fiber_aspect_ratio,
            fiber_min_length_px=params.fiber_min_length_px,
            saturation_adu=params.saturation_adu, binning=1,
            um_per_px=params.um_per_px)
        bias = df.Bias(result.bias.data, result.bias.frames_used)

        series = df.Series()
        for metrics in result.metrics:
            frame = frameio.load_frame(metrics.filepath,
                                       full_scale=result.bias.full_scale,
                                       mono_mode=params.mono_mode)
            series.add(df.analyze(frame.data, bias, settings), metrics.timestamp)

        pairs = (("coverage_pct", "total_coverage_pct"),
                 ("particles", "total_particle_count"),
                 ("points", "point_count"), ("clusters", "cluster_count"),
                 ("fibers", "fiber_count"), ("haze_pct", "haze_coverage_pct"),
                 ("haze_only_pct", "haze_only_coverage_pct"),
                 ("threshold", "applied_threshold"),
                 ("cleanliness", "cleanliness_score"), ("snr", "snr"),
                 ("density_mpx", "particle_density_per_mpx"),
                 ("rate_coverage", "rate_coverage_pct_per_s"),
                 ("rate_haze", "rate_haze_pct_per_s"),
                 ("phase", "phase"))
        assert len(series.samples) == len(result.metrics)
        for sample, metrics in zip(series.samples, result.metrics):
            for ours, theirs in pairs:
                mine, theirs_value = getattr(sample, ours), getattr(metrics, theirs)
                if isinstance(theirs_value, str):
                    assert mine == theirs_value, (ours, mine, theirs_value)
                else:
                    assert abs(float(mine) - float(theirs_value)) < 1e-9, \
                        (ours, mine, theirs_value)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_stale_reference_is_retaken_before_measuring():
    """Starší reference než dvě minuty se před měřením pořídí znovu."""
    import shutil
    import tempfile
    import time as _time
    from datetime import datetime, timedelta

    import numpy as np

    from bmscam import darkfield as df
    from bmscam.ui.main_window import MainWindow

    app = _app()
    folder = tempfile.mkdtemp()
    win = MainWindow(prefer_demo=True)
    win.connectCamera()
    try:
        win.save_dir = folder
        deadline = _time.time() + 5.0
        while _time.time() < deadline and not win.view.hasImage():
            app.processEvents()
            _time.sleep(0.02)

        # reference stará pět minut
        old = df.Bias(np.zeros((16, 16), np.float32), 16,
                      created=datetime.now() - timedelta(minutes=5))
        win.df_panel.setBias(old)
        assert win._biasIsStale()

        win.df_panel.chk_store.setChecked(False)
        win.df_panel.spin_stack.setValue(1)
        win.df_panel.setMeasuring(True)           # jako kliknutí na Spustit měření
        app.processEvents()
        # měření zatím neběží – nejdřív se snímá reference
        assert win.df_runner.collecting_bias or win._start_after_bias

        deadline = _time.time() + 20.0
        while _time.time() < deadline and win._start_after_bias:
            app.processEvents()
            _time.sleep(0.02)
        assert win._start_after_bias is None, "reference se nedokončila"
        assert not win._biasIsStale(), "nová reference není čerstvá"
        assert win.df_panel.isMeasuring(), "měření se po referenci nespustilo"
        assert win.df_timer.isActive()

        win.df_panel.setMeasuring(False)
        app.processEvents()

        # čerstvá reference se znovu nesnímá
        win.df_panel.setMeasuring(True)
        app.processEvents()
        assert win._start_after_bias is None
        assert not win.df_runner.collecting_bias
        win.df_panel.setMeasuring(False)
        app.processEvents()
    finally:
        win.close()
        shutil.rmtree(folder, ignore_errors=True)


def test_live_alignment_cancels_a_shifted_slide():
    """Živé zarovnání podle prachu smaže falešnou kontaminaci z driftu."""
    import cv2
    import numpy as np

    from bmscam import darkfield as df, dfa

    rng = np.random.default_rng(4)
    size = (400, 560)
    stars = [(int(rng.integers(25, size[0] - 25)), int(rng.integers(25, size[1] - 25)))
             for _ in range(80)]

    def render(dy, dx, extra=0, seed=0):
        local = np.random.default_rng(seed)
        canvas = np.zeros(size, np.float32)
        for y, x in stars:
            yy, xx = y + dy, x + dx
            if 5 < yy < size[0] - 6 and 5 < xx < size[1] - 6:
                canvas[yy, xx] += 900.0
        for _ in range(extra):
            canvas[int(local.integers(20, size[0] - 20)),
                   int(local.integers(20, size[1] - 20))] += 700.0
        # částice rozostřená optikou – ostrý bod jádro bere jako vadný pixel
        canvas = cv2.GaussianBlur(canvas, (0, 0), 1.6)
        return np.clip(16.0 + canvas + local.normal(0, 1.0, size), 0, 255).astype("uint8")

    settings = df.Settings(binning=1)
    reference = render(0, 0, seed=1)
    bias = df.Bias(reference.astype(np.float32), 16)
    bias.anchor = dfa.build_anchor(bias.mean, settings)
    assert bias.anchor is not None and bias.anchor.usable
    assert bias.anchor.anchor.count > 40
    assert bias.anchor.crop is not None            # ořez je pevný, ne podle driftu

    shifted = render(7, -5, seed=2)
    aligned = df.analyze(shifted, bias, settings)
    plain = df.analyze(shifted, df.Bias(reference.astype(np.float32), 16),
                       df.Settings(binning=1, align_frames=False))
    assert aligned["align_stars"] > 40
    assert abs(aligned["align_dx"] + 5.0) < 1.0
    assert abs(aligned["align_dy"] - 7.0) < 1.0
    assert aligned["particles"] == 0, aligned["particles"]
    assert plain["particles"] > 40, "bez zarovnání musí drift udělat falešné částice"

    # skutečné nové částice zarovnání nesmaže
    dirty = render(7, -5, extra=6, seed=3)
    found = df.analyze(dirty, bias, settings)
    assert found["particles"] == 6, found["particles"]


def test_panel_settings_survive_a_restart():
    """Nastavení panelu měření se uloží při zavření a načte při startu."""
    from PyQt5.QtCore import QSettings

    from bmscam.ui.main_window import MainWindow

    app = _app()
    win = MainWindow(prefer_demo=True)
    try:
        win.df_panel.spin_interval.setValue(9.0)
        win.df_panel.spin_stack.setValue(2)
        win.df_panel.spin_sigma.setValue(6.5)
        win.df_panel.chk_store.setChecked(False)
        win.df_panel.cmb_material.setCurrentIndex(
            win.df_panel.cmb_material.findData("pla"))
        win.df_panel.spin_temp.setValue(120.0)
    finally:
        win.close()                      # tady se stav ukládá
    app.processEvents()

    stored = QSettings("BMS", "CamControl").value("darkfield")
    assert isinstance(stored, dict) and stored["interval_s"] == 9.0

    again = MainWindow(prefer_demo=True)
    try:
        assert again.df_panel.spin_interval.value() == 9.0
        assert again.df_panel.spin_stack.value() == 2
        assert again.df_panel.spin_sigma.value() == 6.5
        assert again.df_panel.wantsStoredFrames() is False, "vypnutá volba se zapnula"
        assert again.df_panel.material() == "pla"
        assert again.df_panel.temperature() == 120.0
    finally:
        again.close()
    _app()                               # uklidí uložený stav pro další testy


def test_bool_from_settings_text():
    """QSettings umí vrátit „false“ jako text – nesmí se z toho stát pravda."""
    from bmscam.ui.darkfield_panel import DarkFieldPanel

    assert DarkFieldPanel._asBool("false") is False
    assert DarkFieldPanel._asBool("0") is False
    assert DarkFieldPanel._asBool("true") is True
    assert DarkFieldPanel._asBool(True) is True
    assert DarkFieldPanel._asBool(0) is False


def test_collapsible_section_hides_its_body():
    """Panel měření ukazuje jen to, co je právě potřeba."""
    from bmscam.ui.darkfield_panel import DarkFieldPanel

    _app()
    panel = DarkFieldPanel()

    # kanálové řádky se ukazují jen se zapnutým režimem
    # (isVisibleTo, protože samotný panel v testu není zobrazený)
    assert not panel.channel_box.isVisibleTo(panel)
    panel.chk_multi.setChecked(True)
    assert panel.channel_box.isVisibleTo(panel)
    panel.chk_multi.setChecked(False)
    assert not panel.channel_box.isVisibleTo(panel)

    # rozšířené prahy jsou sbalené, dokud se nerozkliknou
    assert not panel.spin_haze.isVisibleTo(panel)
    advanced = panel.spin_haze.parentWidget()
    while advanced is not None and not hasattr(advanced, "setExpanded"):
        advanced = advanced.parentWidget()
    assert advanced is not None, "rozšířené volby nejsou ve sbalitelném bloku"
    advanced.setExpanded(True)
    assert panel.spin_haze.isVisibleTo(panel)


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
