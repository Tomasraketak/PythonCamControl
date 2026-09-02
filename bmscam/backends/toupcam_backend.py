"""Backend nad nativním SDK ToupTek (libtoupcam.so / toupcam.dll).

Používá se tam, kde není k dispozici uvcham.dll – tedy hlavně na Linuxu.
Knihovnu je třeba umístit do ``bmscam/lib/<x64|x86>/`` nebo na ni ukázat
proměnnou ``BMSCAM_TOUPCAM_LIB``.
"""

import ctypes
import threading
from typing import Dict, List, Optional, Tuple

from ..spec import DeviceInfo, KIND_CHECK, PropSpec, make_spec
from ..toupcam_ctypes import (RANGES, TOUPCAM_EVENT_DISCONNECTED,
                              TOUPCAM_EVENT_ERROR, TOUPCAM_EVENT_IMAGE,
                              TOUPCAM_EVENT_NOFRAMETIMEOUT, CALLBACK, Toupcam)
from .base import (EVENT_DISCONNECT, EVENT_ERROR, EVENT_IMAGE, CameraBackend,
                   CameraError, Frame)


def _dibstride(width: int) -> int:
    return (width * 24 + 31) // 32 * 4


class ToupcamBackend(CameraBackend):
    name = "toupcam"
    description = "ToupTek native SDK (libtoupcam)"
    supports_record = False          # nativní SDK nemá zabudovaný zápis videa

    def __init__(self, handle, device: DeviceInfo):
        self._h = handle
        self._device = device
        self._props: Dict[str, PropSpec] = {}
        self._running = False
        self._paused = False
        self._buf = None
        self._w = self._h_px = self._stride = 0
        self._lock = threading.Lock()
        self._callback = None
        self._cb_ref = None
        self._mono = False
        #: pořadí bajtů, které SDK vrací (Linux: RGB, Windows: BGR)
        self.pixel_order = "bgr" if Toupcam.path().endswith(".dll") else "rgb"
        self._probe()

    # ------------------------------------------------------------ discovery -
    @classmethod
    def available(cls) -> bool:
        return Toupcam.load()

    @classmethod
    def unavailable_reason(cls) -> str:
        Toupcam.load()
        return Toupcam.error()

    @classmethod
    def sdk_version(cls) -> str:
        return Toupcam.version()

    @classmethod
    def enumerate(cls) -> List[DeviceInfo]:
        if not Toupcam.load():
            return []
        return [DeviceInfo(id=ident, name=name, backend=cls.name)
                for name, ident in Toupcam.enum()]

    @classmethod
    def open(cls, device_id: Optional[str]) -> "ToupcamBackend":
        if not Toupcam.load():
            raise CameraError(Toupcam.error())
        devices = Toupcam.enum()
        if not devices:
            raise CameraError("Nebyla nalezena žádná kamera.")
        name, ident = next(((n, i) for n, i in devices if i == device_id), devices[0])
        handle = Toupcam.open(ident)
        if not handle:
            raise CameraError(f"Kameru „{name}“ se nepodařilo otevřít.")
        return cls(handle, DeviceInfo(id=ident, name=name, backend=cls.name))

    # ------------------------------------------------------------ vlastnosti -
    def _try(self, fn, *a):
        try:
            return fn(*a)
        except Exception:
            return None

    def _probe(self) -> None:
        h = self._h
        self._mono = self._try(lambda: Toupcam._call("get_MonoMode", h) == 0) is True

        if self._try(Toupcam.get_int, h, "AutoExpoEnable") is not None:
            self._props["aexpo"] = make_spec("aexpo", 0, 1, 1)

        rng = self._expo_range()
        if rng:
            self._props["expotime"] = make_spec("expotime", *rng, unit="ms",
                                                scale=0.001, decimals=2)
        rng = self._gain_range()
        if rng:
            self._props["again"] = make_spec("again", *rng, unit="%")
        if self._try(Toupcam.get_ushort, h, "AutoExpoTarget") is not None:
            self._props["aexpotarget"] = make_spec("aexpotarget", *RANGES["aexpotarget"])
        if self._try(Toupcam.get_int, h, "HZ") is not None:
            self._props["hz"] = make_spec("hz", 0, 2, 1)

        if not self._mono:
            if self._try(self._get_temptint) is not None:
                self._props["temp"] = make_spec("temp", *RANGES["temp"])
                self._props["tint"] = make_spec("tint", *RANGES["tint"])
            if self._try(self._get_wbgain) is not None:
                for key in ("wbred", "wbgreen", "wbblue"):
                    self._props[key] = make_spec(key, *RANGES["wbgain"])
            if Toupcam.has("AwbOnce"):
                self._props["wb_once"] = make_spec("wb_once")
            for key, api in (("saturation", "Saturation"), ("hue", "Hue")):
                if self._try(Toupcam.get_int, h, api) is not None:
                    self._props[key] = make_spec(key, *RANGES[key])
            if self._try(Toupcam.get_int, h, "Chrome") is not None:
                self._props["chrome"] = make_spec("chrome", 0, 1, 0)

        for key, api in (("brightness", "Brightness"), ("contrast", "Contrast"),
                         ("gamma", "Gamma")):
            if self._try(Toupcam.get_int, h, api) is not None:
                self._props[key] = make_spec(key, *RANGES[key])
        for key, api in (("negative", "Negative"), ("fliphorz", "HFlip"),
                         ("flipvert", "VFlip"), ("realtime", "RealTime")):
            if self._try(Toupcam.get_int, h, api) is not None:
                self._props[key] = make_spec(key, 0, 1, 0)

        if Toupcam.has("Pause"):
            self._props["pause"] = make_spec("pause", 0, 1, 0)
        if Toupcam.has("get_FrameRate"):
            self._props["framerate"] = make_spec("framerate", 0, 1000, 0)
        if Toupcam.has("put_AFMode"):
            self._props["af_once"] = make_spec("af_once", tip="Jednorázové zaostření (experimentální).")

    def _expo_range(self):
        try:
            lo, hi, df = (ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint())
            Toupcam._call("get_ExpTimeRange", self._h, ctypes.byref(lo),
                          ctypes.byref(hi), ctypes.byref(df))
            return (lo.value, min(hi.value, 5_000_000), df.value)
        except Exception:
            return None

    def _gain_range(self):
        try:
            lo, hi, df = (ctypes.c_ushort(), ctypes.c_ushort(), ctypes.c_ushort())
            Toupcam._call("get_ExpoAGainRange", self._h, ctypes.byref(lo),
                          ctypes.byref(hi), ctypes.byref(df))
            return (lo.value, hi.value, df.value)
        except Exception:
            return None

    def _get_temptint(self) -> Tuple[int, int]:
        t, ti = ctypes.c_int(), ctypes.c_int()
        Toupcam._call("get_TempTint", self._h, ctypes.byref(t), ctypes.byref(ti))
        return t.value, ti.value

    def _get_wbgain(self) -> List[int]:
        arr = (ctypes.c_int * 3)()
        Toupcam._call("get_WhiteBalanceGain", self._h, arr)
        return list(arr)

    def _put_wbgain(self, values) -> None:
        arr = (ctypes.c_int * 3)(*[int(v) for v in values])
        Toupcam._call("put_WhiteBalanceGain", self._h, arr)

    def props(self) -> Dict[str, PropSpec]:
        return self._props

    _SIMPLE = {"brightness": "Brightness", "contrast": "Contrast", "hue": "Hue",
               "saturation": "Saturation", "gamma": "Gamma", "chrome": "Chrome",
               "negative": "Negative", "fliphorz": "HFlip", "flipvert": "VFlip",
               "realtime": "RealTime", "hz": "HZ"}

    def get(self, key: str) -> int:
        h = self._h
        try:
            if key in self._SIMPLE:
                return Toupcam.get_int(h, self._SIMPLE[key])
            if key == "aexpo":
                return Toupcam.get_int(h, "AutoExpoEnable")
            if key == "expotime":
                return Toupcam.get_uint(h, "ExpoTime")
            if key == "again":
                return Toupcam.get_ushort(h, "ExpoAGain")
            if key == "aexpotarget":
                return Toupcam.get_ushort(h, "AutoExpoTarget")
            if key in ("temp", "tint"):
                t, ti = self._get_temptint()
                return t if key == "temp" else ti
            if key in ("wbred", "wbgreen", "wbblue"):
                return self._get_wbgain()[("wbred", "wbgreen", "wbblue").index(key)]
            if key == "pause":
                return 1 if self._paused else 0
            if key == "framerate":
                return self._framerate()
        except Exception as exc:
            raise CameraError(str(exc)) from exc
        raise CameraError(f"Vlastnost „{key}“ není podporována.")

    def set(self, key: str, value: int) -> None:
        h, value = self._h, int(value)
        try:
            if key in self._SIMPLE:
                Toupcam.put_int(h, self._SIMPLE[key], value)
                return
            if key == "aexpo":
                Toupcam._call("put_AutoExpoEnable", h, ctypes.c_int(value))
                return
            if key == "expotime":
                Toupcam._call("put_ExpoTime", h, ctypes.c_uint(value))
                return
            if key == "again":
                Toupcam._call("put_ExpoAGain", h, ctypes.c_ushort(value))
                return
            if key == "aexpotarget":
                Toupcam._call("put_AutoExpoTarget", h, ctypes.c_ushort(value))
                return
            if key in ("temp", "tint"):
                t, ti = self._get_temptint()
                if key == "temp":
                    t = value
                else:
                    ti = value
                Toupcam._call("put_TempTint", h, ctypes.c_int(t), ctypes.c_int(ti))
                return
            if key in ("wbred", "wbgreen", "wbblue"):
                gains = self._get_wbgain()
                gains[("wbred", "wbgreen", "wbblue").index(key)] = value
                self._put_wbgain(gains)
                return
            if key == "pause":
                Toupcam._call("Pause", h, ctypes.c_int(value))
                self._paused = bool(value)
                return
        except Exception as exc:
            raise CameraError(str(exc)) from exc
        raise CameraError(f"Vlastnost „{key}“ nelze nastavit.")

    def action(self, key: str) -> None:
        try:
            if key == "wb_once":
                Toupcam._call("AwbOnce", self._h, None, None)
            elif key == "af_once":
                Toupcam._call("put_AFMode", self._h, ctypes.c_int(1))
            else:
                raise CameraError(f"Neznámá akce „{key}“.")
        except CameraError:
            raise
        except Exception as exc:
            raise CameraError(str(exc)) from exc

    def _framerate(self) -> int:
        nframe, ntime, ntotal = (ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint())
        Toupcam._call("get_FrameRate", self._h, ctypes.byref(nframe),
                      ctypes.byref(ntime), ctypes.byref(ntotal))
        return int(nframe.value * 1000 / ntime.value) if ntime.value else 0

    # -------------------------------------------------------------- rozlišení
    def resolutions(self) -> List[Tuple[int, int]]:
        out = []
        try:
            n = Toupcam._call("get_ResolutionNumber", self._h)
        except Exception:
            return out
        for i in range(max(int(n), 0)):
            w, h = ctypes.c_int(), ctypes.c_int()
            try:
                Toupcam._call("get_Resolution", self._h, ctypes.c_uint(i),
                              ctypes.byref(w), ctypes.byref(h))
            except Exception:
                break
            out.append((w.value, h.value))
        return out

    def get_resolution(self) -> int:
        v = ctypes.c_uint()
        Toupcam._call("get_eSize", self._h, ctypes.byref(v))
        return v.value

    def set_resolution(self, index: int) -> None:
        Toupcam._call("put_eSize", self._h, ctypes.c_uint(int(index)))

    # ------------------------------------------------------------------ tok --
    def _alloc(self) -> None:
        w, h = ctypes.c_int(), ctypes.c_int()
        Toupcam._call("get_Size", self._h, ctypes.byref(w), ctypes.byref(h))
        self._w, self._h_px = w.value, h.value
        self._stride = _dibstride(self._w)
        self._buf = bytearray(self._stride * self._h_px)

    def start(self, callback) -> None:
        self._callback = callback
        self._alloc()
        self._cb_ref = CALLBACK(self._on_event)     # držet referenci!
        try:
            Toupcam._call("StartPullModeWithCallback", self._h, self._cb_ref, None)
        except Exception as exc:
            raise CameraError(f"Stream se nepodařilo spustit: {exc}") from exc
        self._running = True

    def _on_event(self, nevent, _ctx):
        out = 0
        if nevent == TOUPCAM_EVENT_IMAGE:
            out = EVENT_IMAGE
        elif nevent == TOUPCAM_EVENT_DISCONNECTED:
            out = EVENT_DISCONNECT
        elif nevent in (TOUPCAM_EVENT_ERROR, TOUPCAM_EVENT_NOFRAMETIMEOUT):
            out = EVENT_ERROR
        if out and self._callback:
            self._callback(out)

    def stop(self) -> None:
        if self._running:
            try:
                Toupcam._call("Stop", self._h)
            except Exception:
                pass
            self._running = False

    def is_running(self) -> bool:
        return self._running

    def pull(self) -> Optional[Frame]:
        if not self._running or self._buf is None:
            return None
        with self._lock:
            view = (ctypes.c_char * len(self._buf)).from_buffer(self._buf)
            try:
                Toupcam._call("PullImageV3", self._h, view, 0, 24, 0, None)
            except Exception:
                return None
            finally:
                del view
            return Frame(self._buf, self._w, self._h_px, self._stride)

    # ---------------------------------------------------------------- ostatní
    def info(self) -> Dict[str, str]:
        out = {"Kamera": self._device.name, "SDK": self.sdk_version()}
        for label, api, size in (("Sériové číslo", "SerialNumber", 32),
                                 ("Firmware", "FwVersion", 16),
                                 ("Hardware", "HwVersion", 16),
                                 ("Vyrobeno", "ProductionDate", 10)):
            val = self._try(Toupcam.get_str, self._h, api, size)
            if val:
                out[label] = val
        if self._mono:
            out["Senzor"] = "monochromatický"
        return out

    def close(self) -> None:
        self.stop()
        self._buf = None
        if self._h:
            try:
                Toupcam._call("Close", self._h)
            finally:
                self._h = None
