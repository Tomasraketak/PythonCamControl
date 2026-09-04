"""Rozbor nahraného videa – proč ho přehrávač nechce otevřít.

Windows hlásí u vadného videa kód `0xC00D36C4`
(`MF_E_UNSUPPORTED_BYTESTREAM_TYPE`), což znamená jediné: *tomuhle souboru
nerozumím*. Důvody jsou ale dva úplně různé a je potřeba je rozlišit:

1. **Soubor není dokončený.** Kontejner MP4 má na konci rejstřík (`moov`),
   který se zapíše až při ukončení nahrávání. Když se stream mezitím
   zastaví (třeba změnou rozlišení) nebo aplikace skončí bez zavolání
   `Uvcham_record(NULL)`, zůstane jen holá `mdat` s daty a žádný přehrávač
   soubor neotevře. Data jsou tam, ale bez rejstříku jsou nepoužitelná.

2. **Soubor je v pořádku, jen ho neumí *tenhle* přehrávač.** Aplikace
   „Filmy a TV" jede přes Media Foundation a zvládne prakticky jen H.264
   a HEVC. Když SDK zapíše MJPEG nebo MPEG-4 Part 2, Windows couvne se
   stejným kódem – a VLC přitom video přehraje bez problémů.

Modul přečte hlavičku souboru a řekne, o který z těch dvou případů jde.
"""

import os
import struct
from typing import List, Optional, Tuple

#: kodeky, které přehraje Media Foundation (tedy „Filmy a TV" ve Windows)
_MF_CODECS = {"avc1", "avc3", "h264", "hev1", "hvc1", "hevc", "mp4a", "ac-3"}

#: lidské názvy kodeků, se kterými se u mikroskopových kamer dá potkat
_CODEC_NAMES = {
    "avc1": "H.264", "avc3": "H.264", "h264": "H.264",
    "hev1": "HEVC (H.265)", "hvc1": "HEVC (H.265)",
    "mp4v": "MPEG-4 Part 2", "mjpa": "Motion JPEG", "jpeg": "Motion JPEG",
    "mp4a": "AAC (zvuk)", "raw ": "nekomprimovaný obraz",
}

_ASF_GUID = bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")
_MKV_MAGIC = b"\x1a\x45\xdf\xa3"

#: kontejnery, které umí zapsat Uvcham_record
KNOWN_SUFFIXES = (".mp4", ".mkv", ".asf")


class VideoReport:
    """Výsledek rozboru souboru."""

    def __init__(self, path: str):
        self.path = path
        self.size = 0
        self.container = ""          # mp4 / mkv / asf / neznámý
        self.complete: Optional[bool] = None   # None = nelze určit
        self.codec = ""              # fourcc
        self.duration = 0.0          # sekundy, 0 = neznámo
        self.playable_in_windows: Optional[bool] = None
        self.problem = ""            # prázdné = nic nenalezeno

    # ---------------------------------------------------------------- výstup
    def codec_name(self) -> str:
        if not self.codec:
            return ""
        return _CODEC_NAMES.get(self.codec, self.codec)

    def lines(self) -> List[str]:
        out = [f"soubor:     {self.path}",
               f"velikost:   {self.size / 1e6:.1f} MB ({self.size} B)"]
        if self.container:
            out.append(f"kontejner:  {self.container}")
        if self.codec:
            out.append(f"kodek:      {self.codec_name()} ({self.codec})")
        if self.duration:
            out.append(f"délka:      {self.duration:.1f} s")
        if self.complete is not None:
            out.append("dokončeno:  " + ("ano" if self.complete else "NE"))
        return out

    def verdict(self) -> str:
        """Věta, kterou má smysl ukázat uživateli."""
        if self.problem:
            return self.problem
        if self.complete is False:
            return ("Soubor není dokončený – chybí v něm rejstřík, který se "
                    "zapisuje až při ukončení nahrávání. Nahrávání skončilo "
                    "nestandardně: došlo místo na disku, zavřela se aplikace, "
                    "odpojila se kamera nebo se během záznamu změnilo "
                    "rozlišení.")
        if self.playable_in_windows is False:
            return (f"Soubor je v pořádku, ale je v kodeku {self.codec_name()}, "
                    "který přehrávač „Filmy a TV“ neumí. Otevřete ho ve VLC, "
                    "nebo ho převeďte do H.264.")
        if self.complete:
            return "Soubor vypadá v pořádku."
        return "Soubor se nepodařilo rozebrat – formát není známý."


# ------------------------------------------------------------------- MP4 ---

def _read_box(fh, end: int) -> Optional[Tuple[str, int, int]]:
    """Přečte hlavičku boxu; vrátí (typ, začátek dat, konec boxu)."""
    start = fh.tell()
    if start + 8 > end:
        return None
    header = fh.read(8)
    if len(header) < 8:
        return None
    size = struct.unpack(">I", header[:4])[0]
    kind = header[4:8].decode("latin-1")
    data = start + 8
    if size == 1:                      # 64bitová velikost
        extra = fh.read(8)
        if len(extra) < 8:
            return None
        size = struct.unpack(">Q", extra)[0]
        data = start + 16
    elif size == 0:                    # box sahá do konce souboru
        size = end - start
    if size < 8 or start + size > end:
        return None
    return kind, data, start + size


#: boxy, do kterých je potřeba zanořit se při hledání stsd
_CONTAINERS = {"moov", "trak", "mdia", "minf", "stbl", "udta"}


def _walk_mp4(fh, start: int, end: int, report: VideoReport) -> None:
    fh.seek(start)
    while fh.tell() < end:
        box = _read_box(fh, end)
        if box is None:
            return
        kind, data, stop = box
        if kind == "moov":
            report.complete = True
        if kind == "mvhd":
            fh.seek(data)
            _read_mvhd(fh, report)
        elif kind == "stsd":
            fh.seek(data + 8)          # verze/příznaky + počet položek
            entry = _read_box(fh, stop)
            if entry is not None and not report.codec:
                report.codec = entry[0]
        elif kind in _CONTAINERS:
            _walk_mp4(fh, data, stop, report)
        fh.seek(stop)


def _read_mvhd(fh, report: VideoReport) -> None:
    head = fh.read(4)
    if len(head) < 4:
        return
    version = head[0]
    try:
        if version == 1:
            _, _, scale, duration = struct.unpack(">QQIQ", fh.read(28))
        else:
            _, _, scale, duration = struct.unpack(">IIII", fh.read(16))
    except struct.error:
        return
    if scale:
        report.duration = duration / scale


def _check_mp4(fh, report: VideoReport) -> None:
    report.container = "MP4"
    report.complete = False
    _walk_mp4(fh, 0, report.size, report)
    if report.codec:
        report.playable_in_windows = report.codec.lower() in _MF_CODECS


# ------------------------------------------------------------------ rozbor --

def inspect(path: str) -> VideoReport:
    """Rozebere soubor s videem a vrátí zprávu o jeho stavu."""
    report = VideoReport(path)
    if not os.path.exists(path):
        report.problem = "Soubor neexistuje."
        return report
    report.size = os.path.getsize(path)
    if report.size == 0:
        report.problem = ("Soubor je prázdný – nahrávání nezapsalo ani bajt. "
                          "Kamera nejspíš záznam vůbec nespustila.")
        return report

    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
            if head[:4] == _MKV_MAGIC:
                report.container = "Matroska (MKV)"
            elif head[:16] == _ASF_GUID:
                report.container = "ASF / WMV"
            elif len(head) >= 8 and head[4:8] in (b"ftyp", b"moov", b"mdat",
                                                  b"free", b"skip", b"wide"):
                _check_mp4(fh, report)
            else:
                report.problem = (
                    "Soubor nezačíná hlavičkou žádného známého kontejneru "
                    "(MP4, MKV ani ASF) – data jsou nejspíš poškozená.")
    except OSError as exc:
        report.problem = f"Soubor nelze přečíst: {exc}"
    if report.size < 4096 and not report.problem:
        report.problem = ("Soubor je příliš malý na to, aby obsahoval video – "
                          "nahrávání se nejspíš hned po startu zastavilo.")
    return report


def suffix_is_supported(path: str) -> bool:
    """Umí SDK do takové přípony zapisovat?"""
    return os.path.splitext(path)[1].lower() in KNOWN_SUFFIXES
