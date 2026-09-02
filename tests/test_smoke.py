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
    lines = diagnostics()
    assert len(lines) == 3
    assert any(line.startswith("demo:") for line in lines)


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
