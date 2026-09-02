#!/usr/bin/env python3
"""Spuštění aplikace BMS Cam Control.

    python main.py            – normální start
    python main.py --demo     – simulovaná kamera bez hardwaru
    python main.py --list     – výpis kamer a stavu SDK
"""

import sys

from bmscam.app import main

if __name__ == "__main__":
    sys.exit(main())
