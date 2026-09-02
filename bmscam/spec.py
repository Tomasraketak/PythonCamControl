"""Kanonický popis vlastností kamery, nezávislý na konkrétním SDK.

Jednotlivé backendy (uvcham / toupcam / demo) hlásí, které z těchto klíčů
skutečně podporují; GUI se pak sestaví jen z dostupných prvků.
"""

from dataclasses import dataclass, field
from typing import Optional, Sequence

# ---------------------------------------------------------------- skupiny ---
GROUP_EXPO = "expo"
GROUP_WB = "wb"
GROUP_IMAGE = "image"
GROUP_FOCUS = "focus"
GROUP_VIDEO = "video"

GROUP_TITLES = {
    GROUP_EXPO: "Expozice",
    GROUP_WB: "Bílá",
    GROUP_IMAGE: "Obraz",
    GROUP_FOCUS: "Ostření",
    GROUP_VIDEO: "Video",
}
GROUP_TOOLTIPS = {
    GROUP_EXPO: "Expozice, zisk a potlačení blikání",
    GROUP_WB: "Vyvážení bílé a barevné zisky",
    GROUP_IMAGE: "Jas, kontrast, barvy a orientace obrazu",
    GROUP_FOCUS: "Zaostření, digitální zoom a osvětlení",
    GROUP_VIDEO: "Datový tok a režim přenosu",
}
GROUP_ORDER = (GROUP_EXPO, GROUP_WB, GROUP_IMAGE, GROUP_FOCUS, GROUP_VIDEO)

# ------------------------------------------------------------------- typy ---
KIND_SLIDER = "slider"   # celočíselný rozsah -> slider + spinbox
KIND_CHECK = "check"     # 0/1 -> checkbox
KIND_COMBO = "combo"     # výčet -> combobox
KIND_READONLY = "ro"     # jen zobrazení hodnoty
KIND_ACTION = "action"   # tlačítko (jednorázová akce)


@dataclass
class DeviceInfo:
    """Jedna nalezená kamera."""
    id: str
    name: str
    backend: str = ""

    def __str__(self) -> str:
        return f"{self.name}  [{self.backend}]" if self.backend else self.name


@dataclass
class PropSpec:
    """Popis jedné ovladatelné vlastnosti tak, jak ji hlásí backend."""
    key: str
    label: str
    group: str
    kind: str = KIND_SLIDER
    minimum: int = 0
    maximum: int = 100
    default: int = 0
    items: Sequence[str] = ()
    unit: str = ""
    tip: str = ""
    scale: float = 1.0          # zobrazená hodnota = raw * scale
    decimals: int = 0           # počet desetinných míst při zobrazení
    live: bool = False          # hodnotu je třeba periodicky obnovovat (auto režimy)
    write_only: bool = False    # nelze číst (např. UVCHAM_ZOOM)
    hidden: bool = False        # ovládá se jinak než posuvníkem (např. WB ROI)
    needs_restart: bool = False # změna vyžaduje zastavení streamu

    def format(self, raw: int) -> str:
        val = raw * self.scale
        txt = f"{val:.{self.decimals}f}" if self.decimals else f"{int(round(val))}"
        return f"{txt} {self.unit}".strip()


# --------------------------------------------------- katalog známých klíčů ---
# Backend si odsud bere popisky, aby byly ve všech režimech stejné.
CATALOG = {
    # expozice
    "aexpo":        dict(label="Automatická expozice", group=GROUP_EXPO, kind=KIND_CHECK,
                         tip="Kamera si sama řídí expoziční čas a zisk."),
    "expotime":     dict(label="Expoziční čas", group=GROUP_EXPO, unit="ms", scale=0.001, decimals=2, live=True,
                         tip="Delší čas = světlejší obraz, ale rozmazání pohybu."),
    "again":        dict(label="Zisk (gain)", group=GROUP_EXPO, unit="%", live=True,
                         tip="Zesílení signálu. Vyšší hodnota přidává šum."),
    "aexpotarget":  dict(label="Cílový jas AE", group=GROUP_EXPO,
                         tip="Jak světlý obraz má automatika držet."),
    "hz":           dict(label="Frekvence sítě", group=GROUP_EXPO, kind=KIND_COMBO,
                         items=("60 Hz (AC)", "50 Hz (AC)", "Stejnosměrné (DC)"),
                         tip="Potlačení blikání osvětlení. V ČR obvykle 50 Hz."),
    # vyvážení bílé
    "wbmode":       dict(label="Režim WB", group=GROUP_WB, kind=KIND_COMBO,
                         items=("Ruční", "Automatický", "Podle výřezu (ROI)")),
    "wbroileft":    dict(label="WB ROI – vlevo", group=GROUP_WB, hidden=True),
    "wbroitop":     dict(label="WB ROI – nahoře", group=GROUP_WB, hidden=True),
    "wbroiwidth":   dict(label="WB ROI – šířka", group=GROUP_WB, hidden=True),
    "wbroiheight":  dict(label="WB ROI – výška", group=GROUP_WB, hidden=True),
    "wb_once":      dict(label="Vyvážit bílou nyní", group=GROUP_WB, kind=KIND_ACTION,
                         tip="Jednorázové vyvážení podle aktuálního obrazu."),
    "temp":         dict(label="Teplota barev", group=GROUP_WB, unit="K", live=True),
    "tint":         dict(label="Odstín (tint)", group=GROUP_WB, live=True),
    "wbred":        dict(label="Zisk – červená", group=GROUP_WB, live=True),
    "wbgreen":      dict(label="Zisk – zelená", group=GROUP_WB, live=True),
    "wbblue":       dict(label="Zisk – modrá", group=GROUP_WB, live=True),
    # obraz
    "brightness":   dict(label="Jas", group=GROUP_IMAGE),
    "contrast":     dict(label="Kontrast", group=GROUP_IMAGE),
    "saturation":   dict(label="Sytost", group=GROUP_IMAGE),
    "hue":          dict(label="Odstín", group=GROUP_IMAGE),
    "gamma":        dict(label="Gama", group=GROUP_IMAGE),
    "sharpness":    dict(label="Ostrost", group=GROUP_IMAGE),
    "denoise":      dict(label="Potlačení šumu", group=GROUP_IMAGE),
    "chrome":       dict(label="Černobíle", group=GROUP_IMAGE, kind=KIND_CHECK),
    "negative":     dict(label="Negativ", group=GROUP_IMAGE, kind=KIND_CHECK),
    "fliphorz":     dict(label="Převrátit vodorovně", group=GROUP_IMAGE, kind=KIND_CHECK),
    "flipvert":     dict(label="Převrátit svisle", group=GROUP_IMAGE, kind=KIND_CHECK),
    # zaostření
    "afmode":       dict(label="Režim ostření", group=GROUP_FOCUS, kind=KIND_COMBO,
                         items=("Ruční", "Automatické", "Jednorázové", "Konjugovaná kalibrace")),
    "af_once":      dict(label="Zaostřit nyní", group=GROUP_FOCUS, kind=KIND_ACTION),
    "afposition":   dict(label="Poloha ostření", group=GROUP_FOCUS, live=True),
    "afposition_abs": dict(label="Absolutní poloha", group=GROUP_FOCUS, unit="mm", scale=0.001, decimals=2, live=True),
    "afzone":       dict(label="Zóna ostření", group=GROUP_FOCUS,
                         tip="Index zóny, ve které se vyhodnocuje ostrost."),
    "affeedback":   dict(label="Stav ostření", group=GROUP_FOCUS, kind=KIND_READONLY, live=True),
    "light":        dict(label="Jas osvětlení", group=GROUP_FOCUS,
                         tip="Řízení jasu zdroje světla mikroskopu."),
    "zoom":         dict(label="Digitální zoom", group=GROUP_FOCUS, write_only=True),
    # video
    "bps":          dict(label="Datový tok", group=GROUP_VIDEO, unit="Mb/s"),
    "realtime":     dict(label="Režim reálného času", group=GROUP_VIDEO, kind=KIND_CHECK,
                         tip="Zahazuje zpožděné snímky – nižší latence."),
    "pause":        dict(label="Pozastavit snímání", group=GROUP_VIDEO, kind=KIND_CHECK),
    "framerate":    dict(label="Snímková frekvence", group=GROUP_VIDEO, kind=KIND_READONLY, unit="fps", live=True),
}

AF_FEEDBACK_TEXT = {
    0: "neznámý",
    1: "zaostřeno",
    2: "ostří se…",
    3: "rozostřeno",
    4: "posunout stolek nahoru",
    5: "posunout stolek dolů",
}


def make_spec(key: str, minimum: int = 0, maximum: int = 1, default: int = 0, **over) -> PropSpec:
    """Vytvoří PropSpec podle katalogu, s možností přepsat jednotlivá pole."""
    base = dict(CATALOG.get(key, {}))
    base.update(over)
    base.setdefault("label", key)
    base.setdefault("group", GROUP_IMAGE)
    return PropSpec(key=key, minimum=minimum, maximum=maximum, default=default, **base)
