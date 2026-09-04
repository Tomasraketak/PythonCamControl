"""Spouštěč aplikace."""

import argparse
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from . import qtenv
from .ui import theme
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
    ap.add_argument("--doctor", action="store_true",
                    help="vypsat, kde Qt hledá své knihovny (při potížích se spuštěním)")
    ap.add_argument("--check-video", metavar="SOUBOR",
                    help="rozebrat nahrané video a říct, proč nejde přehrát")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.doctor:
        print("Prostředí Qt:")
        for line in qtenv.report():
            print("  " + line)
        return 0

    if args.check_video:
        from .videocheck import inspect
        report = inspect(args.check_video)
        for line in report.lines():
            print("  " + line)
        print("\n" + report.verdict())
        return 0

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

    qtenv.apply_library_path()
    try:
        app = QApplication(sys.argv[:1])
    except Exception as exc:                      # pragma: no cover – jen Qt
        print(f"Chyba při startu Qt: {exc}", file=sys.stderr)
        print(qtenv.HELP_TEXT, file=sys.stderr)
        return 2
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("BMS")
    app.setStyle("Fusion")
    app.setStyleSheet(theme.stylesheet())

    win = MainWindow(prefer_demo=args.demo, include_demo=not args.no_demo)
    win.show()
    if args.connect or args.demo:
        win.connectCamera()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
