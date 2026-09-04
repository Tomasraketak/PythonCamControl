"""BMS Cam Control – ovládání mikroskopové kamery BMS Microscopes 8MP 4K UHD."""

from . import qtenv

# Musí proběhnout dřív, než cokoli importuje PyQt5 nebo cv2 – viz qtenv.py.
qtenv.prepare()

__version__ = "1.0.0"
__all__ = ["__version__", "qtenv"]
