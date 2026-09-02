"""Minimalistický ctypes binding pro nativní SDK ToupTek (libtoupcam.so / toupcam.dll).

Záměrně obsahuje jen tu část API, která je dlouhodobě stabilní a
dokumentovaná (pojmenované get_/put_ funkce). Nepoužívá Toupcam_put_Option,
protože číselné hodnoty voleb se mezi verzemi SDK liší.

Knihovna se hledá v ``bmscam/lib`` a pak ve standardních cestách systému;
lze ji vynutit proměnnou prostředí ``BMSCAM_TOUPCAM_LIB``.
"""

import ctypes
import os
import platform
import sys
from ctypes import (POINTER, c_char, c_char_p, c_int, c_uint, c_ushort,
                    c_void_p, c_wchar, c_wchar_p, byref)

TOUPCAM_MAX = 128

# ------------------------------------------------------------------ události -
TOUPCAM_EVENT_EXPOSURE = 0x0001
TOUPCAM_EVENT_TEMPTINT = 0x0002
TOUPCAM_EVENT_IMAGE = 0x0004
TOUPCAM_EVENT_STILLIMAGE = 0x0005
TOUPCAM_EVENT_WBGAIN = 0x0006
TOUPCAM_EVENT_ERROR = 0x0080
TOUPCAM_EVENT_DISCONNECTED = 0x0081
TOUPCAM_EVENT_NOFRAMETIMEOUT = 0x0082
TOUPCAM_EVENT_FOCUSPOS = 0x0084

# ----------------------------------------------- dokumentované rozsahy SDK ---
RANGES = {                      # klíč: (min, max, default)
    "brightness": (-64, 64, 0),
    "contrast": (-100, 100, 0),
    "hue": (-180, 180, 0),
    "saturation": (0, 255, 128),
    "gamma": (20, 180, 100),
    "temp": (2000, 15000, 6503),
    "tint": (200, 2500, 1000),
    "wbgain": (-127, 127, 0),
    "aexpotarget": (16, 235, 120),
}

_IS_WIN = platform.system() == "Windows"
_TCHAR = c_wchar if _IS_WIN else c_char
_TCHAR_P = c_wchar_p if _IS_WIN else c_char_p


class ToupcamDeviceV2(ctypes.Structure):
    """Prvních 128 znaků struktury; model se čte až po otevření kamery."""
    _fields_ = [("displayname", _TCHAR * 64),
                ("id", _TCHAR * 64),
                ("model", c_void_p)]


CALLBACK = (ctypes.WINFUNCTYPE if _IS_WIN else ctypes.CFUNCTYPE)(None, c_uint, c_void_p)


class ToupcamError(OSError):
    def __init__(self, hr, fn=""):
        super().__init__(f"{fn} selhalo (hr=0x{hr & 0xffffffff:08x})")
        self.hr = hr


def _lib_candidates():
    forced = os.environ.get("BMSCAM_TOUPCAM_LIB")
    if forced:
        yield forced
    here = os.path.dirname(os.path.abspath(__file__))
    arch = "x64" if sys.maxsize > 2 ** 32 else "x86"
    if _IS_WIN:
        names = ("toupcam.dll",)
    elif platform.system() == "Darwin":
        names = ("libtoupcam.dylib",)
    else:
        names = ("libtoupcam.so",)
    other = "x86" if arch == "x64" else "x64"
    for name in names:
        yield os.path.join(here, "lib", arch, name)
        yield os.path.join(here, "lib", name)
        yield name
        # poslední pokus – knihovna pro jinou architekturu (dá srozumitelnou chybu)
        yield os.path.join(here, "lib", other, name)


class Toupcam:
    """Tenká obálka nad knihovnou. ``Toupcam.load()`` vrací True/False."""

    _lib = None
    _error = ""
    _path = ""

    # ----------------------------------------------------------- načtení ----
    @classmethod
    def load(cls) -> bool:
        if cls._lib is not None:
            return True
        if cls._error:
            return False
        loader = ctypes.WinDLL if _IS_WIN else ctypes.CDLL
        errors = []
        for cand in _lib_candidates():
            try:
                lib = loader(cand)
            except OSError as exc:
                errors.append(f"{cand}: {exc}")
                continue
            cls._lib = lib
            cls._path = cand
            cls._bind()
            return True
        cls._error = "knihovnu toupcam se nepodařilo načíst — " + "; ".join(errors[-2:])
        return False

    @classmethod
    def error(cls) -> str:
        return cls._error

    @classmethod
    def path(cls) -> str:
        return cls._path

    @classmethod
    def has(cls, fn: str) -> bool:
        return cls._lib is not None and hasattr(cls._lib, "Toupcam_" + fn)

    @staticmethod
    def _sig(lib, name, restype, argtypes):
        try:
            fn = getattr(lib, name)
        except AttributeError:
            return
        fn.restype = restype
        fn.argtypes = argtypes

    @classmethod
    def _bind(cls):
        lib, sig = cls._lib, cls._sig
        H = c_void_p
        sig(lib, "Toupcam_Version", _TCHAR_P, None)
        sig(lib, "Toupcam_EnumV2", c_uint, [POINTER(ToupcamDeviceV2)])
        sig(lib, "Toupcam_Open", H, [_TCHAR_P])
        sig(lib, "Toupcam_Close", None, [H])
        sig(lib, "Toupcam_StartPullModeWithCallback", c_int, [H, CALLBACK, c_void_p])
        sig(lib, "Toupcam_PullImageV3", c_int, [H, c_void_p, c_int, c_int, c_int, c_void_p])
        sig(lib, "Toupcam_Stop", c_int, [H])
        sig(lib, "Toupcam_Pause", c_int, [H, c_int])
        sig(lib, "Toupcam_Snap", c_int, [H, c_uint])
        sig(lib, "Toupcam_get_Size", c_int, [H, POINTER(c_int), POINTER(c_int)])
        sig(lib, "Toupcam_get_eSize", c_int, [H, POINTER(c_uint)])
        sig(lib, "Toupcam_put_eSize", c_int, [H, c_uint])
        sig(lib, "Toupcam_get_ResolutionNumber", c_int, [H])
        sig(lib, "Toupcam_get_Resolution", c_int, [H, c_uint, POINTER(c_int), POINTER(c_int)])
        sig(lib, "Toupcam_get_ExpTimeRange", c_int, [H, POINTER(c_uint), POINTER(c_uint), POINTER(c_uint)])
        sig(lib, "Toupcam_get_ExpoTime", c_int, [H, POINTER(c_uint)])
        sig(lib, "Toupcam_put_ExpoTime", c_int, [H, c_uint])
        sig(lib, "Toupcam_get_ExpoAGainRange", c_int, [H, POINTER(c_ushort), POINTER(c_ushort), POINTER(c_ushort)])
        sig(lib, "Toupcam_get_ExpoAGain", c_int, [H, POINTER(c_ushort)])
        sig(lib, "Toupcam_put_ExpoAGain", c_int, [H, c_ushort])
        sig(lib, "Toupcam_get_AutoExpoEnable", c_int, [H, POINTER(c_int)])
        sig(lib, "Toupcam_put_AutoExpoEnable", c_int, [H, c_int])
        sig(lib, "Toupcam_get_AutoExpoTarget", c_int, [H, POINTER(c_ushort)])
        sig(lib, "Toupcam_put_AutoExpoTarget", c_int, [H, c_ushort])
        for name in ("Brightness", "Contrast", "Hue", "Saturation", "Gamma",
                     "Chrome", "Negative", "HFlip", "VFlip", "HZ"):
            sig(lib, "Toupcam_get_" + name, c_int, [H, POINTER(c_int)])
            sig(lib, "Toupcam_put_" + name, c_int, [H, c_int])
        sig(lib, "Toupcam_get_RealTime", c_int, [H, POINTER(c_int)])
        sig(lib, "Toupcam_put_RealTime", c_int, [H, c_int])
        sig(lib, "Toupcam_get_TempTint", c_int, [H, POINTER(c_int), POINTER(c_int)])
        sig(lib, "Toupcam_put_TempTint", c_int, [H, c_int, c_int])
        sig(lib, "Toupcam_get_WhiteBalanceGain", c_int, [H, c_int * 3])
        sig(lib, "Toupcam_put_WhiteBalanceGain", c_int, [H, c_int * 3])
        sig(lib, "Toupcam_AwbOnce", c_int, [H, c_void_p, c_void_p])
        sig(lib, "Toupcam_AwbInit", c_int, [H, c_void_p, c_void_p])
        sig(lib, "Toupcam_get_MonoMode", c_int, [H])
        sig(lib, "Toupcam_get_FrameRate", c_int, [H, POINTER(c_uint), POINTER(c_uint), POINTER(c_uint)])
        sig(lib, "Toupcam_get_SerialNumber", c_int, [H, c_char * 32])
        sig(lib, "Toupcam_get_FwVersion", c_int, [H, c_char * 16])
        sig(lib, "Toupcam_get_HwVersion", c_int, [H, c_char * 16])
        sig(lib, "Toupcam_get_ProductionDate", c_int, [H, c_char * 10])
        sig(lib, "Toupcam_get_Temperature", c_int, [H, POINTER(c_ushort)])
        sig(lib, "Toupcam_put_LEDState", c_int, [H, c_ushort, c_ushort, c_ushort])
        sig(lib, "Toupcam_put_AFMode", c_int, [H, c_int])
        sig(lib, "Toupcam_get_AFState", c_int, [H, POINTER(c_uint)])

    # ------------------------------------------------------------ pomocné ---
    @classmethod
    def _call(cls, fn, *args):
        f = getattr(cls._lib, "Toupcam_" + fn, None)
        if f is None:
            raise AttributeError(f"Toupcam_{fn} není v knihovně k dispozici")
        hr = f(*args)
        if isinstance(hr, int) and hr < 0:
            raise ToupcamError(hr, "Toupcam_" + fn)
        return hr

    @classmethod
    def version(cls) -> str:
        if not cls.load():
            return ""
        v = cls._lib.Toupcam_Version()
        return v if isinstance(v, str) else (v or b"").decode("ascii", "replace")

    @classmethod
    def enum(cls):
        if not cls.load():
            return []
        arr = (ToupcamDeviceV2 * TOUPCAM_MAX)()
        n = cls._lib.Toupcam_EnumV2(arr)
        out = []
        for i in range(n):
            name = arr[i].displayname
            ident = arr[i].id
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
                ident = ident.decode("utf-8", "replace")
            out.append((name, ident))
        return out

    @classmethod
    def open(cls, ident):
        if not cls.load():
            raise ToupcamError(-1, "load")
        arg = None
        if ident is not None:
            arg = ident if _IS_WIN else ident.encode("utf-8")
        h = cls._lib.Toupcam_Open(arg)
        return h

    # ------------------------------------------------- typové zkratky get/put
    @classmethod
    def get_int(cls, h, name) -> int:
        v = c_int(0)
        cls._call("get_" + name, h, byref(v))
        return v.value

    @classmethod
    def put_int(cls, h, name, value) -> None:
        cls._call("put_" + name, h, c_int(int(value)))

    @classmethod
    def get_uint(cls, h, name) -> int:
        v = c_uint(0)
        cls._call("get_" + name, h, byref(v))
        return v.value

    @classmethod
    def get_ushort(cls, h, name) -> int:
        v = c_ushort(0)
        cls._call("get_" + name, h, byref(v))
        return v.value

    @classmethod
    def get_str(cls, h, name, size) -> str:
        buf = ctypes.create_string_buffer(size + 1)
        cls._call("get_" + name, h, ctypes.cast(buf, c_char_p))
        return buf.value.decode("ascii", "replace").strip()
