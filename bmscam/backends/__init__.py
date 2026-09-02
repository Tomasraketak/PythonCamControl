"""Registr dostupných backendů."""

from typing import Dict, List, Optional, Type

from ..spec import DeviceInfo
from .base import (EVENT_DISCONNECT, EVENT_ERROR, EVENT_IMAGE, CameraBackend,
                   CameraError, Frame)
from .demo import DemoBackend
from .toupcam_backend import ToupcamBackend
from .uvcham_backend import UvchamBackend

#: pořadí = priorita při automatické volbě
BACKENDS: List[Type[CameraBackend]] = [UvchamBackend, ToupcamBackend, DemoBackend]

BY_NAME: Dict[str, Type[CameraBackend]] = {b.name: b for b in BACKENDS}


def available_backends(include_demo: bool = True) -> List[Type[CameraBackend]]:
    out = []
    for b in BACKENDS:
        if b is DemoBackend and not include_demo:
            continue
        try:
            if b.available():
                out.append(b)
        except Exception:
            pass
    return out


def enumerate_devices(include_demo: bool = True) -> List[DeviceInfo]:
    """Projde všechny dostupné backendy a vrátí seznam kamer."""
    devices: List[DeviceInfo] = []
    for b in available_backends(include_demo):
        try:
            devices.extend(b.enumerate())
        except Exception:
            continue
    return devices


def open_device(device: DeviceInfo) -> CameraBackend:
    backend = BY_NAME.get(device.backend)
    if backend is None:
        raise CameraError(f"Neznámý backend „{device.backend}“.")
    return backend.open(device.id)


def diagnostics() -> List[str]:
    """Řádky pro dialog „Diagnostika SDK“."""
    lines = []
    for b in BACKENDS:
        try:
            ok = b.available()
        except Exception as exc:
            lines.append(f"{b.name}: chyba – {exc}")
            continue
        if ok:
            ver = b.sdk_version() or "?"
            lines.append(f"{b.name}: k dispozici (verze {ver}) – {b.description}")
        else:
            lines.append(f"{b.name}: nedostupné – {b.unavailable_reason() or 'není nainstalováno'}")
    return lines


__all__ = ["BACKENDS", "BY_NAME", "CameraBackend", "CameraError", "Frame",
           "EVENT_IMAGE", "EVENT_DISCONNECT", "EVENT_ERROR", "DemoBackend",
           "available_backends", "enumerate_devices", "open_device", "diagnostics"]
