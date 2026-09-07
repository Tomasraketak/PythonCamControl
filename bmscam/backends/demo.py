"""Simulovaná kamera – umožní vyzkoušet celé GUI bez připojeného hardwaru.

Generuje syntetický „mikroskopický“ obraz, který reaguje na expozici, zisk,
jas, barvu i překlopení, takže se dá ověřit chování ovládacích prvků.
"""

import math
import random
import threading
import time
from typing import Dict, List, Optional, Tuple

from ..spec import DeviceInfo, PropSpec, make_spec
from .base import EVENT_IMAGE, CameraBackend, CameraError, Frame

try:
    import numpy as _np
except ImportError:      # pragma: no cover - numpy je volitelný
    _np = None

_RESOLUTIONS = [(3840, 2160), (1920, 1080), (1280, 720), (640, 480)]


def _dibstride(width: int) -> int:
    return (width * 24 + 31) // 32 * 4


class DemoBackend(CameraBackend):
    name = "demo"
    description = "Simulovaná kamera (bez hardwaru)"
    supports_record = False

    def __init__(self):
        self._values: Dict[str, int] = {}
        self._props: Dict[str, PropSpec] = {}
        self._res_index = 2
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._callback = None
        self._buf = None
        self._front = None                 # hotový snímek pro pull()
        self._lock = threading.Lock()
        self._w = self._h = self._stride = 0
        self._t0 = time.time()
        self._cells = [(random.random(), random.random(), random.uniform(0.02, 0.06),
                        random.uniform(-0.03, 0.03), random.uniform(-0.03, 0.03))
                       for _ in range(28)]
        self._build_props()

    # ------------------------------------------------------------ discovery -
    @classmethod
    def available(cls) -> bool:
        return True

    @classmethod
    def sdk_version(cls) -> str:
        return "demo 1.0"

    @classmethod
    def enumerate(cls) -> List[DeviceInfo]:
        return [DeviceInfo(id="demo", name="Simulovaná kamera 8MP (demo)", backend=cls.name)]

    @classmethod
    def open(cls, device_id: Optional[str] = None) -> "DemoBackend":
        return cls()

    # ------------------------------------------------------------ vlastnosti -
    def _build_props(self) -> None:
        defs = [
            ("aexpo", 0, 1, 1), ("expotime", 100, 200000, 20000, dict(unit="ms", scale=0.001, decimals=2)),
            ("again", 100, 800, 100, dict(unit="%")), ("aexpotarget", 16, 235, 120),
            ("hz", 0, 2, 1),
            ("wbmode", 0, 2, 1), ("wb_once", 0, 1, 0),
            ("temp", 2000, 15000, 6503), ("tint", 200, 2500, 1000),
            ("wbred", -127, 127, 0), ("wbgreen", -127, 127, 0), ("wbblue", -127, 127, 0),
            ("brightness", -64, 64, 0), ("contrast", -100, 100, 0),
            ("saturation", 0, 255, 128), ("hue", -180, 180, 0),
            ("gamma", 20, 180, 100), ("sharpness", 0, 100, 20), ("denoise", 0, 100, 0),
            ("chrome", 0, 1, 0), ("negative", 0, 1, 0),
            ("fliphorz", 0, 1, 0), ("flipvert", 0, 1, 0),
            ("afmode", 0, 3, 1), ("af_once", 0, 1, 0),
            ("afposition", 0, 854, 400), ("afposition_abs", -5400, 10600, 0),
            ("afzone", 0, 63, 27), ("affeedback", 0, 5, 1),
            ("light", 0, 100, 60), ("zoom", 100, 400, 100),
            ("bps", 1, 200, 60), ("realtime", 0, 1, 1), ("pause", 0, 1, 0),
            ("framerate", 0, 120, 0),
        ]
        for item in defs:
            key, lo, hi, dv = item[:4]
            over = item[4] if len(item) > 4 else {}
            self._props[key] = make_spec(key, lo, hi, dv, **over)
            self._values[key] = dv

    def props(self) -> Dict[str, PropSpec]:
        return self._props

    def get(self, key: str) -> int:
        if key not in self._values:
            raise CameraError(f"Vlastnost „{key}“ není podporována.")
        if key == "framerate":
            return 30
        if key == "affeedback" and self._values.get("afmode") == 1:
            return 2 if (time.time() - self._t0) % 6 < 2 else 1
        if key in ("expotime", "again") and self._values.get("aexpo"):
            # v automatice hodnoty „dýchají“, aby bylo vidět živé obnovování
            spec = self._props[key]
            span = (spec.maximum - spec.minimum) * 0.2
            mid = (spec.maximum + spec.minimum) / 2
            return int(mid + span * math.sin((time.time() - self._t0) / 3.0))
        return self._values[key]

    def set(self, key: str, value: int) -> None:
        if key not in self._values:
            raise CameraError(f"Vlastnost „{key}“ není podporována.")
        self._values[key] = int(value)

    def action(self, key: str) -> None:
        if key == "wb_once":
            for k in ("wbred", "wbgreen", "wbblue"):
                self._values[k] = random.randint(-12, 12)
        elif key == "af_once":
            self._values["afposition"] = random.randint(200, 700)
        else:
            raise CameraError(f"Neznámá akce „{key}“.")

    # -------------------------------------------------------------- rozlišení
    def resolutions(self) -> List[Tuple[int, int]]:
        return list(_RESOLUTIONS)

    def get_resolution(self) -> int:
        return self._res_index

    def set_resolution(self, index: int) -> None:
        self._res_index = max(0, min(index, len(_RESOLUTIONS) - 1))

    def codecs(self) -> List[str]:
        return ["MJPG", "H264"]

    def get_codec(self) -> int:
        return 0

    def set_codec(self, index: int) -> None:
        pass

    # ------------------------------------------------------------------ tok --
    def start(self, callback) -> None:
        self._callback = callback
        self._w, self._h = _RESOLUTIONS[self._res_index]
        self._stride = _dibstride(self._w)
        # Dvě vyrovnávací paměti: do jedné se kreslí, druhou si mezitím
        # čte aplikace. Skutečná kamera se chová stejně.
        self._buf = bytearray(self._stride * self._h)
        self._front = bytearray(self._stride * self._h)
        self._stop_evt.clear()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop_evt.wait(1 / 15.0):
            if self._values.get("pause"):
                continue
            # Kreslí se tady, ve vlákně kamery. Dokud to bylo v pull(),
            # platila aplikace za každý snímek ~100 ms ve vlákně GUI
            # a okno kvůli tomu sekalo.
            self._render()
            with self._lock:
                self._buf, self._front = self._front, self._buf
            if self._callback:
                self._callback(EVENT_IMAGE)

    def stop(self) -> None:
        self._running = False
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def is_running(self) -> bool:
        return self._running

    def pull(self) -> Optional[Frame]:
        if not self._running or self._front is None:
            return None
        with self._lock:
            return Frame(self._front, self._w, self._h, self._stride)

    # -------------------------------------------------------------- kreslení -
    def _gain_factor(self) -> float:
        """Jak světlý obraz vyjde – v automatice drží kamera jas sama."""
        light = 0.6 + self._values["light"] / 150.0
        if self._values.get("aexpo"):
            target = self._values["aexpotarget"] / 120.0
            return light * target
        spec = self._props["expotime"]
        rel = (self._values["expotime"] - spec.minimum) / max(spec.maximum - spec.minimum, 1)
        return (0.25 + 1.5 * rel) * (self._values["again"] / 100.0) * light

    def _render(self) -> None:
        if _np is None:
            self._render_fallback()
            return
        w, h, t = self._w, self._h, time.time() - self._t0
        # pracujeme ve zmenšeném rozlišení a pak zvětšíme (rychlost)
        sw, sh = min(w, 480), max(1, int(min(w, 480) * h / w))
        cache = getattr(self, "_grid_cache", None)
        if cache is None or cache[0] != (w, h, sw, sh):
            yy, xx = _np.mgrid[0:sh, 0:sw]
            cache = ((w, h, sw, sh), xx / sw, yy / sh,
                     _np.arange(h) * sh // h, _np.arange(w) * sw // w)
            self._grid_cache = cache
        _, xn, yn, rows, cols = cache
        img = _np.full((sh, sw), 0.82, dtype=_np.float32)
        img += 0.03 * _np.sin(xn * 40 + t * 0.6) * _np.sin(yn * 32)
        blobs = _np.zeros((sh, sw), dtype=_np.float32)
        for cx, cy, r, vx, vy in self._cells:
            px = (cx + vx * t * 0.05) % 1.0
            py = (cy + vy * t * 0.05) % 1.0
            d = ((xn - px) ** 2 + (yn - py) ** 2) / (r * r)
            blobs += _np.exp(-d * 2.5)
        img -= 0.45 * _np.clip(blobs, 0, 1.4)

        # rozostření podle vzdálenosti od "zaostřené" polohy
        focus = abs(self._values["afposition"] - 400) / 400.0
        if self._values.get("afmode") == 1:
            focus = 0.05
        if focus > 0.02:
            k = max(1, int(focus * 6))
            kernel = _np.ones(2 * k + 1, dtype=_np.float32) / (2 * k + 1)
            img = _np.apply_along_axis(lambda m: _np.convolve(m, kernel, mode="same"), 1, img)

        img = _np.clip(img * self._gain_factor(), 0, 1)
        img = img ** (100.0 / max(self._values["gamma"], 1))
        img = _np.clip((img - 0.5) * (1 + self._values["contrast"] / 150.0) + 0.5
                       + self._values["brightness"] / 128.0, 0, 1)

        rgb = _np.repeat(img[:, :, None], 3, axis=2)
        if not self._values["chrome"]:
            sat = self._values["saturation"] / 128.0
            tint = _np.array([1.02 + self._values["wbred"] / 400.0,
                              0.99 + self._values["wbgreen"] / 400.0,
                              0.93 + self._values["wbblue"] / 400.0], dtype=_np.float32)
            temp = (self._values["temp"] - 6503) / 8000.0
            tint = tint * _np.array([1 + temp * 0.35, 1.0, 1 - temp * 0.35], dtype=_np.float32)
            colored = _np.clip(rgb * tint, 0, 1)
            rgb = _np.clip(rgb + (colored - rgb) * sat, 0, 1)
        if self._values["negative"]:
            rgb = 1.0 - rgb
        noise = self._values["again"] / 100.0 * 0.012 * (1 - self._values["denoise"] / 120.0)
        if noise > 0:
            rgb = _np.clip(rgb + _np.random.normal(0, noise, rgb.shape).astype(_np.float32), 0, 1)

        small = (rgb * 255).astype(_np.uint8)
        big = small[rows][:, cols]
        if self._values["fliphorz"]:
            big = big[:, ::-1]
        if self._values["flipvert"]:
            big = big[::-1]
        # Zapisujeme rovnou do vyrovnávací paměti. Přes mezikopii a
        # tobytes() to znamenalo tři kopie celého snímku na každý pull –
        # na 4K skoro sto milisekund, což sekalo celé GUI v demo režimu.
        out = _np.asarray(memoryview(self._buf)).reshape(h, self._stride)
        out[:, : w * 3] = big.reshape(h, w * 3)

    def _render_fallback(self) -> None:
        """Bez numpy jen jednoduchý gradient, ať aplikace přesto běží."""
        g = int(200 * min(self._gain_factor(), 1.0))
        row = bytes((g, g, min(255, g + 20))) * self._w
        row += b"\0" * (self._stride - len(row))
        self._buf[:] = row * self._h

    def info(self) -> Dict[str, str]:
        return {"Kamera": "Simulovaná kamera 8MP (demo)", "SDK": self.sdk_version(),
                "Sériové číslo": "DEMO-0001", "Firmware": "2025-07-22"}

    def close(self) -> None:
        self.stop()
        self._buf = None
