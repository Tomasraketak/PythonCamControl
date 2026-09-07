"""Kompletní nastavení aplikace v jednom souboru.

Profil kamery ukládal jen vlastnosti senzoru. Tenhle formát drží celé
pracoviště: kameru, osvětlení, rozbor temného pole i nastavení snímání –
tedy všechno, co je potřeba, aby se měření dalo za týden zopakovat za
stejných podmínek.

Soubor je obyčejný JSON, aby šel přečíst i bez aplikace a aby se dal
připojit k naměřeným datům. Modul je bez Qt, takže se dá testovat zvlášť.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

#: verze formátu – roste, jen když se změní význam už zapsaných polí
FORMAT = 2

#: klíče oddílů; pořadí určuje i pořadí v souboru
SECTIONS = ("camera", "leds", "darkfield", "capture")


class WorkspaceError(Exception):
    """Soubor nejde přečíst nebo to není nastavení této aplikace."""


def new(**sections) -> Dict[str, Any]:
    """Sestaví soubor s hlavičkou a zadanými oddíly."""
    data: Dict[str, Any] = {
        "app": "BMS Cam Control",
        "format": FORMAT,
        "saved": datetime.now().isoformat(" ", "seconds"),
    }
    for key in SECTIONS:
        if key in sections and sections[key] is not None:
            data[key] = sections[key]
    return data


def save(path: str, data: Dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def load(path: str) -> Dict[str, Any]:
    """Načte soubor a převede i starý formát profilu kamery."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise WorkspaceError(str(exc)) from exc
    except ValueError as exc:
        raise WorkspaceError(f"Soubor není platný JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError("Soubor neobsahuje nastavení aplikace.")
    return upgrade(data)


def upgrade(data: Dict[str, Any]) -> Dict[str, Any]:
    """Starší profil (jen vlastnosti kamery) povýší na dnešní podobu.

    Profily uložené dřívějšími verzemi měly „values“ přímo v kořeni. Číst
    je dál je levné a uživateli to ušetří ruční přepisování."""
    if "values" in data and "camera" not in data:
        data = dict(data)
        data["camera"] = {"backend": data.pop("backend", ""),
                          "values": data.pop("values") or {}}
        data.setdefault("format", 1)
    return data


def section(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Oddíl souboru; chybějící oddíl je prázdný slovník, ne chyba."""
    value = data.get(name)
    return value if isinstance(value, dict) else {}


def describe(data: Dict[str, Any]) -> List[str]:
    """Řádky pro potvrzovací okno – co soubor obsahuje."""
    lines = []
    saved = data.get("saved")
    if saved:
        lines.append(f"Uloženo {saved}")
    camera = section(data, "camera")
    if camera.get("values"):
        backend = camera.get("backend") or "?"
        lines.append("Kamera: {} vlastností (backend {})"
                     .format(len(camera["values"]), backend))
        size = camera.get("resolution_size")
        if size:
            lines.append("Rozlišení: {}×{}".format(*size))
    leds = section(data, "leds")
    if leds:
        panels = leds.get("panels") or []
        lines.append(f"Osvětlení: {len(panels)} stran"
                     + (f", natočení {leds.get('rotation', 0)}" if leds.get("rotation") else ""))
    dark = section(data, "darkfield")
    if dark:
        lines.append("Dark Field: interval {} s, práh {}"
                     .format(dark.get("interval_s", "?"),
                             dark.get("threshold_mode", "?")))
    capture = section(data, "capture")
    if capture.get("save_dir"):
        lines.append("Pracovní složka: " + str(capture["save_dir"]))
    return lines or ["Soubor neobsahuje žádné známé nastavení."]


#: podsložka, do které se ukládají soubory s nastavením
SETTINGS_FOLDER = "nastavení"


def settings_dir(base: str) -> str:
    """Složka „nastavení“ uvnitř pracovní složky; když není, založí se.

    Nastavení tak leží pohromadě vedle fotek, ne rozházené mezi nimi."""
    path = os.path.join(base, SETTINGS_FOLDER)
    os.makedirs(path, exist_ok=True)
    return path


def default_name(folder: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(folder, f"nastaveni_{stamp}.json")


# ------------------------------------------------------------ pracovní složka

#: název podsložky, do které aplikace ukládá, když si uživatel nevybere jinak
FOLDER_NAME = "BMS fotky"


def default_save_dir() -> str:
    """Výchozí pracovní složka: Stažené soubory přihlášeného uživatele.

    Na Windows to vyjde na C:/Users/<uživatel>/Downloads/BMS fotky – tedy
    přesně tam, kam si uživatel přál. Cesta se skládá z domovské složky,
    ne z pevně zapsaného jména, aby fungovala i na druhém počítači a po
    přejmenování účtu."""
    home = os.path.expanduser("~")
    downloads = os.path.join(home, "Downloads")
    if not os.path.isdir(downloads):
        for name in ("Stažené soubory", "Stahování"):   # lokalizovaný Windows
            candidate = os.path.join(home, name)
            if os.path.isdir(candidate):
                downloads = candidate
                break
    return os.path.join(downloads, FOLDER_NAME)
