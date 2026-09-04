#!/usr/bin/env python3
"""Spuštění aplikace BMS Cam Control.

    python main.py            – normální start
    python main.py --demo     – simulovaná kamera bez hardwaru
    python main.py --list     – výpis kamer a stavu SDK
    python main.py --doctor   – diagnostika Qt, když aplikace nejde spustit
"""

import sys


def _doctor() -> int:
    """Vypíše diagnostiku Qt. Funguje i tehdy, když PyQt5 chybí."""
    from bmscam import qtenv
    print("Prostředí Qt:")
    for line in qtenv.report():
        print("  " + line)
    return 0


if __name__ == "__main__":
    # --doctor se řeší dřív než import zbytku aplikace: ta importuje PyQt5,
    # a právě když PyQt5 nejde načíst, je diagnostika nejvíc potřeba.
    if "--doctor" in sys.argv[1:]:
        sys.exit(_doctor())
    try:
        from bmscam.app import main
    except ImportError as exc:
        from bmscam import qtenv
        print(f"Nepodařilo se načíst aplikaci: {exc}", file=sys.stderr)
        print(qtenv.HELP_TEXT, file=sys.stderr)
        sys.exit(2)
    sys.exit(main())
