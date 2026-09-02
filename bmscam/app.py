"""Spouštěč aplikace."""

import argparse
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from .ui.main_window import APP_NAME, MainWindow


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        prog="bmscam",
        description="Ovládání mikroskopové kamery BMS Microscopes 8MP 4K UHD.")
    ap.add_argument("--demo", action="store_true",
                    help="přednostně otevřít simulovanou kameru (bez hardwaru)")
    ap.add_argument("--no-demo", action="store_true",
                    help="nenabízet simulovanou kameru v seznamu zařízení")
    ap.add_argument("--connect", action="store_true",
                    help="připojit první nalezenou kameru hned po startu")
    ap.add_argument("--list", action="store_true",
                    help="jen vypsat nalezené kamery a stav SDK a skončit")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.list:
        from .backends import diagnostics, enumerate_devices
        print("Stav SDK:")
        for line in diagnostics():
            print("  " + line)
        print("\nNalezené kamery:")
        devices = enumerate_devices(include_demo=not args.no_demo)
        for i, dev in enumerate(devices):
            print(f"  [{i}] {dev.name}  (backend {dev.backend}, id {dev.id})")
        if not devices:
            print("  žádné")
        return 0

    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("BMS")

    win = MainWindow(prefer_demo=args.demo, include_demo=not args.no_demo)
    win.show()
    if args.connect or args.demo:
        win.connectCamera()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
