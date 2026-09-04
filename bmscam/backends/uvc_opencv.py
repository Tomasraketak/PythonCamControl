"""Záložní backend pro živý obraz přes OpenCV (UVC / DirectShow).

Kamera se hlásí jako běžné UVC zařízení, takže ji operační systém vidí i bez
SDK výrobce. Tenhle backend proto slouží jako pojistka: když `uvcham.dll`
kameru z jakéhokoli důvodu nenajde, obraz je pořád vidět a základní veličiny
jde nastavit.

Omezení oproti nativnímu SDK: ovladač nehlásí rozsahy jednotlivých veličin,
proto se používají obvyklé hodnoty z tabulky níže a skutečné chování se
u různých ovladačů může lišit. Pro přesné ovládání používejte backend
`uvcham`.
"""

import platform
import threading
from typing import Dict, List, Optional, Tuple

from ..spec import DeviceInfo, KIND_CHECK, PropSpec, make_spec
from .base import EVENT_ERROR, EVENT_IMAGE, CameraBackend, CameraError, Frame

#: modul `cv2` se načítá až při prvním použití – schválně.
#: Import `cv2` totiž ve Windows přidá do PATH vlastní knihovny Qt a přepíše
#: proměnnou QT_QPA_PLATFORM_PLUGIN_PATH, takže by se aplikaci rozbilo
#: hledání zásuvných modulů Qt. Takhle k tomu dojde až po startu okna.
cv2 = None
IMPORT_ERROR = ""
_import_done = False


def _load_cv2():
    """Načte OpenCV při prvním použití; vrátí modul, nebo None."""
    global cv2, IMPORT_ERROR, _import_done
    if _import_done:
        return cv2
    _import_done = True
    try:
        import cv2 as _module
    except ImportError as exc:
        IMPORT_ERROR = (f"OpenCV není nainstalované ({exc}). "
                        "Nainstalujte jej příkazem:  pip install opencv-python")
    else:
        cv2 = _module
    return cv2

#: kolik indexů zařízení se při hledání vyzkouší
MAX_PROBE = 4

#: obvyklá rozlišení nabízená uživateli (skutečné se ověří při přepnutí)
COMMON_RESOLUTIONS = [(3840, 2160), (2592, 1944), (1920, 1080),
                      (1280, 720), (640, 480)]

#: klíč -> (vlastnost OpenCV, min, max, výchozí)
_PROPS = [
    ("aexpo",      "CAP_PROP_AUTO_EXPOSURE", 0, 1, 1),
    ("expotime",   "CAP_PROP_EXPOSURE", -13, 0, -6),
    ("again",      "CAP_PROP_GAIN", 0, 255, 0),
    ("brightness", "CAP_PROP_BRIGHTNESS", 0, 255, 128),
    ("contrast",   "CAP_PROP_CONTRAST", 0, 255, 32),
    ("saturation", "CAP_PROP_SATURATION", 0, 255, 64),
    ("hue",        "CAP_PROP_HUE", -180, 180, 0),
    ("gamma",      "CAP_PROP_GAMMA", 1, 500, 100),
    ("sharpness",  "CAP_PROP_SHARPNESS", 0, 255, 0),
    ("temp",       "CAP_PROP_WB_TEMPERATURE", 2000, 10000, 6500),
    ("wbmode",     "CAP_PROP_AUTO_WB", 0, 1, 1),
    ("afmode",     "CAP_PROP_AUTOFOCUS", 0, 1, 1),
    ("afposition", "CAP_PROP_FOCUS", 0, 255, 0),
]

#: popisky, které se u tohoto backendu liší od katalogu
_OVERRIDES = {
    "expotime": dict(unit="", scale=1.0, decimals=0,
                     tip="Expozice v krocích ovladače (log2 sekundy, "
                         "nižší hodnota = kratší čas)."),
    "again": dict(unit=""),
    "wbmode": dict(kind=KIND_CHECK, label="Automatické vyvážení bílé", items=()),
    "afmode": dict(kind=KIND_CHECK, label="Automatické ostření", items=()),
}


def _api_preference() -> int:
    system = platform.system()
    if system == "Windows":
        return cv2.CAP_DSHOW
    if system == "Darwin":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_V4L2


def _is_valid(value) -> bool:
    """OpenCV vrací -1 (nebo NaN) u vlastností, které ovladač nezná."""
    try:
        return value == value and value != -1.0
    except TypeError:
        return False


class OpenCvBackend(CameraBackend):
    name = "uvc"
    description = "Záložní živý obraz přes OpenCV (UVC / DirectShow)"
    supports_record = False

    def __init__(self, cap, index: int):
        self._cap = cap
        self._index = index
        self._props: Dict[str, PropSpec] = {}
        self._cvprops: Dict[str, int] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._callback = None
        self._lock = threading.Lock()
        self._frame: Optional[Frame] = None
        self.pixel_order = "bgr"          # OpenCV vrací BGR
        self._probe()

    # ------------------------------------------------------------ discovery -
    @classmethod
    def available(cls) -> bool:
        return _load_cv2() is not None

    @classmethod
    def unavailable_reason(cls) -> str:
        _load_cv2()
        return IMPORT_ERROR

    @classmethod
    def sdk_version(cls) -> str:
        return f"OpenCV {cv2.__version__}" if _load_cv2() else ""

    @classmethod
    def enumerate(cls) -> List[DeviceInfo]:
        if _load_cv2() is None:
            return []
        found = []
        for index in range(MAX_PROBE):
            cap = None
            try:
                cap = cv2.VideoCapture(index, _api_preference())
                if cap.isOpened():
                    found.append(DeviceInfo(id=str(index),
                                            name=f"UVC kamera #{index}",
                                            backend=cls.name))
            except Exception:
                pass
            finally:
                if cap is not None:
                    cap.release()
        return found

    @classmethod
    def open(cls, device_id: Optional[str]) -> "OpenCvBackend":
        if _load_cv2() is None:
            raise CameraError(IMPORT_ERROR)
        try:
            index = int(device_id) if device_id is not None else 0
        except ValueError:
            index = 0
        cap = cv2.VideoCapture(index, _api_preference())
        if not cap.isOpened():
            cap.release()
            raise CameraError(f"UVC kameru #{index} se nepodařilo otevřít.")
        return cls(cap, index)

    # ------------------------------------------------------------ vlastnosti -
    def _probe(self) -> None:
        for key, attr, lo, hi, default in _PROPS:
            prop = getattr(cv2, attr, None)
            if prop is None:
                continue
            try:
                value = self._cap.get(prop)
            except Exception:
                continue
            if not _is_valid(value):
                continue
            self._cvprops[key] = prop
            self._props[key] = make_spec(key, lo, hi, default,
                                         **_OVERRIDES.get(key, {}))

    def props(self) -> Dict[str, PropSpec]:
        return self._props

    def get(self, key: str) -> int:
        prop = self._cvprops.get(key)
        if prop is None:
            raise CameraError(f"Vlastnost „{key}“ není podporována.")
        value = self._cap.get(prop)
        if not _is_valid(value):
            raise CameraError(f"Vlastnost „{key}“ nelze přečíst.")
        return int(round(value))

    def set(self, key: str, value: int) -> None:
        prop = self._cvprops.get(key)
        if prop is None:
            raise CameraError(f"Vlastnost „{key}“ není podporována.")
        if not self._cap.set(prop, float(value)):
            raise CameraError(f"Ovladač odmítl nastavit „{key}“.")

    def action(self, key: str) -> None:
        raise CameraError("Tento backend nepodporuje jednorázové akce.")

    # -------------------------------------------------------------- rozlišení
    def resolutions(self) -> List[Tuple[int, int]]:
        current = (int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                   int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        out = list(COMMON_RESOLUTIONS)
        if current[0] > 0 and current not in out:
            out.insert(0, current)
        return out

    def get_resolution(self) -> int:
        current = (int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                   int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        resolutions = self.resolutions()
        return resolutions.index(current) if current in resolutions else 0

    def set_resolution(self, index: int) -> None:
        resolutions = self.resolutions()
        if not 0 <= index < len(resolutions):
            raise CameraError("Neplatné rozlišení.")
        width, height = resolutions[index]
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    # ------------------------------------------------------------------ tok --
    def start(self, callback) -> None:
        self._callback = callback
        self._stop.clear()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                ok, frame = self._cap.read()
            except Exception:
                ok, frame = False, None
            if not ok or frame is None:
                failures += 1
                if failures > 30 and self._callback:
                    self._callback(EVENT_ERROR)
                    return
                continue
            failures = 0
            height, width = frame.shape[:2]
            data = frame.tobytes()
            with self._lock:
                self._frame = Frame(data, width, height, width * 3)
            if self._callback:
                self._callback(EVENT_IMAGE)

    def stop(self) -> None:
        self._running = False
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.5)

    def is_running(self) -> bool:
        return self._running

    def pull(self) -> Optional[Frame]:
        with self._lock:
            return self._frame

    # ---------------------------------------------------------------- ostatní
    def info(self) -> Dict[str, str]:
        return {"Kamera": f"UVC kamera #{self._index}",
                "SDK": self.sdk_version(),
                "Pozn.": "záložní režim, rozsahy hodnot jsou orientační"}

    def close(self) -> None:
        self.stop()
        self._frame = None
        if self._cap is not None:
            try:
                self._cap.release()
            finally:
                self._cap = None
