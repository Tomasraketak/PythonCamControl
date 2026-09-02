"""Společné rozhraní všech backendů."""

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..spec import DeviceInfo, PropSpec

# událost -> předává se do GUI
EVENT_IMAGE = 1
EVENT_DISCONNECT = 2
EVENT_ERROR = 4

EventCallback = Callable[[int], None]


class CameraError(Exception):
    """Chyba při komunikaci s kamerou."""


class Frame:
    """Jeden snímek: syrová RGB888 data + geometrie."""

    __slots__ = ("data", "width", "height", "stride")

    def __init__(self, data, width: int, height: int, stride: int):
        self.data = data
        self.width = width
        self.height = height
        self.stride = stride


class CameraBackend:
    """Abstraktní kamera. Backend implementuje jen to, co jeho SDK umí."""

    #: krátký identifikátor ("uvcham", "toupcam", "demo")
    name = "base"
    #: popis pro uživatele
    description = ""
    #: podporuje nahrávání videa přes SDK
    supports_record = False

    # ------------------------------------------------------------ discovery -
    @classmethod
    def available(cls) -> bool:
        """Je knihovna SDK v tomto systému k dispozici?"""
        return False

    @classmethod
    def unavailable_reason(cls) -> str:
        return ""

    @classmethod
    def sdk_version(cls) -> str:
        return ""

    @classmethod
    def enumerate(cls) -> List[DeviceInfo]:
        return []

    @classmethod
    def open(cls, device_id: Optional[str]) -> "CameraBackend":
        raise NotImplementedError

    # ------------------------------------------------------------- vlastnosti
    def props(self) -> Dict[str, PropSpec]:
        """Klíč -> PropSpec pro vše, co kamera reálně podporuje."""
        return {}

    def get(self, key: str) -> int:
        raise NotImplementedError

    def set(self, key: str, value: int) -> None:
        raise NotImplementedError

    def action(self, key: str) -> None:
        """Jednorázová akce (wb_once, af_once…)."""
        raise NotImplementedError

    # -------------------------------------------------------------- rozlišení
    def resolutions(self) -> List[Tuple[int, int]]:
        return []

    def get_resolution(self) -> int:
        return 0

    def set_resolution(self, index: int) -> None:
        raise NotImplementedError

    def codecs(self) -> List[str]:
        return []

    def get_codec(self) -> int:
        return 0

    def set_codec(self, index: int) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------------ tok --
    def start(self, callback: EventCallback) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        pass

    def pull(self) -> Optional[Frame]:
        """Vyzvedne poslední snímek (pull mode)."""
        return None

    def is_running(self) -> bool:
        return False

    # ---------------------------------------------------------------- záznam --
    def record_start(self, path: str) -> None:
        raise CameraError("Tento backend neumí nahrávat video.")

    def record_stop(self) -> None:
        pass

    # ----------------------------------------------------------------- ostatní
    def info(self) -> Dict[str, str]:
        """Informace o kameře pro stavový panel (SN, firmware…)."""
        return {}

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
