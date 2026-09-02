"""Backend nad originálním SDK BMS / uvcham.dll (Windows).

Toto je primární cesta pro kameru „BMS Microscopes RJ45 8MP 4K UHD
Multioutput HDMI“ – používá se přiložená knihovna uvcham.dll a modul
uvcham.py z SDK (uvcham.20250722).
"""

import os
import platform
import sys
import threading
from typing import Dict, List, Optional, Tuple

from ..spec import AF_FEEDBACK_TEXT, DeviceInfo, KIND_CHECK, KIND_READONLY, PropSpec, make_spec
from .base import (EVENT_DISCONNECT, EVENT_ERROR, EVENT_IMAGE, CameraBackend,
                   CameraError, Frame)

_uvcham = None
_import_error = ""


def _lib_dir() -> Optional[str]:
    """Adresář s přibalenou uvcham.dll podle architektury interpretu."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    arch = "x64" if sys.maxsize > 2 ** 32 else "x86"
    path = os.path.join(here, "lib", arch)
    return path if os.path.isfile(os.path.join(path, "uvcham.dll")) else None


def _load():
    """Načte modul uvcham (jen na Windows). Vrací modul nebo None."""
    global _uvcham, _import_error
    if _uvcham is not None or _import_error:
        return _uvcham
    if platform.system() != "Windows":
        _import_error = "uvcham.dll je knihovna pro Windows – v tomto systému ji nelze načíst."
        return None
    try:
        d = _lib_dir()
        if d and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(d)          # aby se našla přibalená DLL
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        from .. import uvcham as mod         # vendorovaný modul z SDK
        mod.Uvcham.Version()                 # vynutí načtení DLL
        _uvcham = mod
    except Exception as exc:                 # pragma: no cover - jen na Windows
        _import_error = f"uvcham.dll se nepodařilo načíst: {exc}"
    return _uvcham


# klíč -> (konstanta SDK, přepis PropSpec)
_MAP = [
    ("aexpo",          "UVCHAM_AEXPO", {}),
    ("expotime",       "UVCHAM_EXPOTIME", dict(unit="", scale=1.0, decimals=0,
                                               tip="Expoziční čas v jednotkách SDK – vyšší hodnota = světlejší obraz.")),
    ("again",          "UVCHAM_AGAIN", dict(unit="")),
    ("aexpotarget",    "UVCHAM_AEXPOTARGET", {}),
    ("hz",             "UVCHAM_HZ", {}),

    ("wbmode",         "UVCHAM_WBMODE", {}),
    ("wbroileft",      "UVCHAM_WBROILEFT", {}),
    ("wbroitop",       "UVCHAM_WBROITOP", {}),
    ("wbroiwidth",     "UVCHAM_WBROIWIDTH", {}),
    ("wbroiheight",    "UVCHAM_WBROIHEIGHT", {}),
    ("temp",           "UVCHAM_TEMP", {}),
    ("tint",           "UVCHAM_TINT", {}),
    ("wbred",          "UVCHAM_WBRED", {}),
    ("wbgreen",        "UVCHAM_WBGREEN", {}),
    ("wbblue",         "UVCHAM_WBBLUE", {}),

    ("brightness",     "UVCHAM_BRIGHTNESS", {}),
    ("contrast",       "UVCHAM_CONTRAST", {}),
    ("saturation",     "UVCHAM_SATURATION", {}),
    ("hue",            "UVCHAM_HUE", {}),
    ("gamma",          "UVCHAM_GAMMA", {}),
    ("sharpness",      "UVCHAM_SHARPNESS", {}),
    ("denoise",        "UVCHAM_DENOISE", {}),
    ("chrome",         "UVCHAM_CHROME", {}),
    ("negative",       "UVCHAM_NEGATIVE", {}),
    ("fliphorz",       "UVCHAM_FLIPHORZ", {}),
    ("flipvert",       "UVCHAM_FLIPVERT", {}),

    ("afmode",         "UVCHAM_AFMODE", {}),
    ("afposition",     "UVCHAM_AFPOSITION", {}),
    ("afposition_abs", "UVCHAM_AFPOSITION_ABSOLUTE", {}),
    ("afzone",         "UVCHAM_AFZONE", {}),
    ("affeedback",     "UVCHAM_AFFEEDBACK", {}),
    ("light",          "UVCHAM_LIGHT_ADJUSTMENT", {}),
    ("zoom",           "UVCHAM_ZOOM", {}),

    ("bps",            "UVCHAM_BPS", {}),
    ("realtime",       "UVCHAM_REALTIME", {}),
    ("pause",          "UVCHAM_PAUSE", {}),
]


class UvchamBackend(CameraBackend):
    name = "uvcham"
    description = "BMS / uvcham.dll (Windows)"
    supports_record = True

    def __init__(self, cam, device: DeviceInfo):
        self._cam = cam
        self._device = device
        self._props: Dict[str, PropSpec] = {}
        self._ids: Dict[str, int] = {}
        self._running = False
        self._recording = False
        self._buf = None          # bytearray sdílený s SDK
        self._cbuf = None         # ctypes pohled na týž paměťový blok
        self._w = self._h = self._stride = 0
        self._lock = threading.Lock()
        self._callback = None
        self._probe()

    # ------------------------------------------------------------ discovery -
    @classmethod
    def available(cls) -> bool:
        return _load() is not None

    @classmethod
    def unavailable_reason(cls) -> str:
        _load()
        return _import_error

    @classmethod
    def sdk_version(cls) -> str:
        mod = _load()
        return mod.Uvcham.Version() if mod else ""

    @classmethod
    def enumerate(cls) -> List[DeviceInfo]:
        mod = _load()
        if not mod:
            return []
        return [DeviceInfo(id=d.id, name=d.displayname, backend=cls.name)
                for d in mod.Uvcham.enum()]

    @classmethod
    def open(cls, device_id: Optional[str]) -> "UvchamBackend":
        mod = _load()
        if not mod:
            raise CameraError(_import_error)
        devices = mod.Uvcham.enum()
        if not devices:
            raise CameraError("Nebyla nalezena žádná kamera.")
        dev = next((d for d in devices if d.id == device_id), devices[0])
        cam = mod.Uvcham.open(dev.id)
        if cam is None:
            raise CameraError(f"Kameru „{dev.displayname}“ se nepodařilo otevřít.")
        try:
            cam.put(mod.UVCHAM_FORMAT, 2)     # RGB888 kvůli QImage
        except Exception:
            pass
        return cls(cam, DeviceInfo(id=dev.id, name=dev.displayname, backend=cls.name))

    # ------------------------------------------------------------ vlastnosti -
    def _probe(self) -> None:
        """Zjistí, které vlastnosti kamera skutečně podporuje."""
        mod = _load()
        for key, const, over in _MAP:
            pid = getattr(mod, const, None)
            if pid is None:
                continue
            try:
                nmin, nmax, ndef = self._cam.range(pid)
            except Exception:
                continue                       # vlastnost není podporována
            if nmax <= nmin and key not in ("aexpo",):
                nmin, nmax = 0, max(nmax, 1)
            spec = make_spec(key, nmin, nmax, ndef, **over)
            if spec.kind == KIND_CHECK:
                spec.minimum, spec.maximum = 0, 1
            self._props[key] = spec
            self._ids[key] = pid

        if "wbmode" in self._props:
            self._props["wb_once"] = make_spec("wb_once")
        if "afmode" in self._props:
            self._props["af_once"] = make_spec("af_once")

    def props(self) -> Dict[str, PropSpec]:
        return self._props

    def get(self, key: str) -> int:
        pid = self._ids.get(key)
        if pid is None:
            raise CameraError(f"Vlastnost „{key}“ není podporována.")
        try:
            return self._cam.get(pid)
        except Exception as exc:
            raise CameraError(str(exc)) from exc

    def set(self, key: str, value: int) -> None:
        pid = self._ids.get(key)
        if pid is None:
            raise CameraError(f"Vlastnost „{key}“ není podporována.")
        try:
            self._cam.put(pid, int(value))
        except Exception as exc:
            raise CameraError(str(exc)) from exc

    def action(self, key: str) -> None:
        mod = _load()
        if key == "wb_once":
            self._cam.put(mod.UVCHAM_WBMODE, 3)      # jednorázové vyvážení
        elif key == "af_once":
            self._cam.put(mod.UVCHAM_AFMODE, 2)      # one-shot AF
        else:
            raise CameraError(f"Neznámá akce „{key}“.")

    def format_readonly(self, key: str, raw: int) -> str:
        if key == "affeedback":
            return AF_FEEDBACK_TEXT.get(raw, str(raw))
        return str(raw)

    # -------------------------------------------------------------- rozlišení
    def resolutions(self) -> List[Tuple[int, int]]:
        mod = _load()
        out: List[Tuple[int, int]] = []
        try:
            _, nmax, _ = self._cam.range(mod.UVCHAM_RES)
        except Exception:
            nmax = 0
        limit = max(nmax + 1, 1)
        for i in range(min(limit, 32)):
            try:
                w = self._cam.get(mod.UVCHAM_WIDTH | i)
                h = self._cam.get(mod.UVCHAM_HEIGHT | i)
            except Exception:
                break
            if w <= 0 or h <= 0:
                break
            out.append((w, h))
        return out

    def get_resolution(self) -> int:
        return self._cam.get(_load().UVCHAM_RES)

    def set_resolution(self, index: int) -> None:
        self._cam.put(_load().UVCHAM_RES, int(index))

    def codecs(self) -> List[str]:
        mod = _load()
        out: List[str] = []
        try:
            _, nmax, _ = self._cam.range(mod.UVCHAM_CODEC)
        except Exception:
            return out
        for i in range(min(max(nmax + 1, 1), 16)):
            try:
                fourcc = self._cam.get(mod.UVCHAM_CODEC_FOURCC | i)
            except Exception:
                break
            out.append(_fourcc_str(fourcc))
        return out

    def get_codec(self) -> int:
        try:
            return self._cam.get(_load().UVCHAM_CODEC)
        except Exception:
            return 0

    def set_codec(self, index: int) -> None:
        self._cam.put(_load().UVCHAM_CODEC, int(index))

    # ------------------------------------------------------------------ tok --
    def _alloc(self) -> None:
        mod = _load()
        import ctypes
        res = self.get_resolution()
        self._w = self._cam.get(mod.UVCHAM_WIDTH | res)
        self._h = self._cam.get(mod.UVCHAM_HEIGHT | res)
        self._stride = mod.TDIBWIDTHBYTES(self._w * 24)
        self._buf = bytearray(self._stride * self._h)
        self._cbuf = (ctypes.c_char * len(self._buf)).from_buffer(self._buf)

    def start(self, callback) -> None:
        self._callback = callback
        self._alloc()
        try:
            self._cam.start(None, _event_trampoline, self)   # pull mode
        except Exception as exc:
            raise CameraError(f"Stream se nepodařilo spustit: {exc}") from exc
        self._running = True

    def stop(self) -> None:
        if self._running:
            try:
                self._cam.stop()
            except Exception:
                pass
            self._running = False

    def is_running(self) -> bool:
        return self._running

    def pull(self) -> Optional[Frame]:
        if not self._running or self._cbuf is None:
            return None
        with self._lock:
            try:
                self._cam.pull(self._cbuf)
            except Exception:
                return None
            return Frame(self._buf, self._w, self._h, self._stride)

    # ---------------------------------------------------------------- záznam --
    def record_start(self, path: str) -> None:
        self._cam.record(_encode_path(path))
        self._recording = True

    def record_stop(self) -> None:
        if self._recording:
            try:
                self._cam.record(None)
            finally:
                self._recording = False

    # ---------------------------------------------------------------- ostatní
    def info(self) -> Dict[str, str]:
        mod = _load()
        out = {"Kamera": self._device.name, "SDK": self.sdk_version()}
        try:
            out["Sériové číslo"] = str(self._cam.get(mod.UVCHAM_SN))
        except Exception:
            pass
        try:
            y = self._cam.get(mod.UVCHAM_YEAR)
            m = self._cam.get(mod.UVCHAM_MONTH)
            d = self._cam.get(mod.UVCHAM_DAY)
            out["Firmware"] = f"{y:04d}-{m:02d}-{d:02d}"
        except Exception:
            pass
        return out

    def close(self) -> None:
        self.record_stop()
        self.stop()
        self._cbuf = None
        self._buf = None
        if self._cam is not None:
            try:
                self._cam.close()
            finally:
                self._cam = None


def _event_trampoline(nevent: int, ctx: "UvchamBackend") -> None:
    """Volá se z interního vlákna DLL – jen přeloží kód události."""
    mod = _load()
    out = 0
    if nevent & mod.UVCHAM_EVENT_IMAGE:
        out |= EVENT_IMAGE
    if nevent & mod.UVCHAM_EVENT_DISCONNECT:
        out |= EVENT_DISCONNECT
    if nevent & mod.UVCHAM_EVENT_ERROR:
        out |= EVENT_ERROR
    if out and ctx._callback:
        ctx._callback(out)


def _fourcc_str(value: int) -> str:
    chars = [chr((value >> (8 * i)) & 0xFF) for i in range(4)]
    text = "".join(c for c in chars if c.isprintable())
    return text or str(value)


def _encode_path(path: str) -> bytes:
    """Uvcham_record přebírá char* – na Windows kóduj v ANSI."""
    try:
        return path.encode("mbcs")
    except (LookupError, UnicodeEncodeError):
        return path.encode("utf-8", "replace")
