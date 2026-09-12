"""Protokol pro řízení osvětlení WS2812 (moduly FC101) přes Arduino.

Modul je záměrně bez závislosti na Qt i na pyserial – dá se testovat samostatně.
Odpovídá sketchi ``arduino/bms_led_controller``.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

PANELS = 4
LEDS_PER_PANEL = 8
BAUD = 115200

#: Moduly tvoří strany čtverce kolem objektivu; pořadí odpovídá zřetězení
#: datového vodiče po směru hodinových ručiček (viz docs/zapojeni_led.md).
PANEL_NAMES = ("Horní", "Pravý", "Dolní", "Levý")
PANEL_SHORT = ("shora", "zprava", "zdola", "zleva")

RGB = Tuple[int, int, int]

#: O kolik stran je zřetězení modulů natočené proti popiskům v aplikaci.
#: Modul, který sketch adresuje jako první, nemusí ležet nahoře – záleží,
#: kde se datový vodič připojil. Při natočení 1 leží první modul vpravo,
#: takže „Horní“ v aplikaci se musí poslat na modul 4.
DEFAULT_ROTATION = 1


def wire_index(gui_index: int, rotation: int = DEFAULT_ROTATION) -> int:
    """Číslo modulu (1..4) pro stranu, kterou aplikace zobrazuje jako `gui_index`.

    >>> wire_index(0, 1)      # „Horní“ při natočení o jednu stranu
    4
    >>> wire_index(1, 1)      # „Pravý“
    1
    >>> wire_index(0, 0)      # bez natočení adresuje aplikace přímo
    1
    """
    return (gui_index - int(rotation)) % PANELS + 1


def gui_index(wire: int, rotation: int = DEFAULT_ROTATION) -> int:
    """Opak :func:`wire_index` – ze zprávy Arduina zpět na stranu v aplikaci."""
    return (int(wire) - 1 + int(rotation)) % PANELS

#: Jednotlivé kanály WS2812 a jejich vlnová délka.
#: Čip má tři samostatné čipy LED, každý s vlastním úzkým pásmem – když
#: se rozsvítí jen jeden, chová se osvětlení jako (široké) pásmové
#: filtrování. To se hodí u vzorků, které v některé části spektra
#: kontrastují líp, a u temného pole, kde na vlnové délce závisí rozptyl.
#: Údaje jsou z katalogových listů běžných WS2812B; kus od kusu se liší.
CHANNELS: List[Tuple[str, str, RGB, int, str]] = [
    # klíč,   popis,      barva,           typicky, rozsah
    ("red",   "Červená",  (255, 0, 0),     625,     "620–630 nm"),
    ("green", "Zelená",   (0, 255, 0),     520,     "515–530 nm"),
    ("blue",  "Modrá",    (0, 0, 255),     470,     "465–475 nm"),
]


def channel(key: str) -> Tuple[str, str, RGB, int, str]:
    """Kanál podle klíče („red“ / „green“ / „blue“)."""
    for item in CHANNELS:
        if item[0] == key:
            return item
    raise KeyError(key)


#: přednastavené barvy nabízené v aplikaci
PRESETS: List[Tuple[str, RGB]] = [
    ("Bílá", (255, 255, 255)),
    ("Teplá bílá", (255, 180, 107)),
    ("Studená bílá", (201, 226, 255)),
    ("Červená", (255, 0, 0)),
    ("Zelená", (0, 255, 0)),
    ("Modrá", (0, 0, 255)),
    ("Žlutá", (255, 220, 0)),
    ("Azurová", (0, 255, 255)),
    ("Purpurová", (255, 0, 255)),
]


def clamp(value: int, low: int = 0, high: int = 255) -> int:
    return max(low, min(int(value), high))


@dataclass
class PanelState:
    on: bool = True
    brightness: int = 255
    color: RGB = (255, 255, 255)


@dataclass
class LedState:
    """Stav celého osvětlení tak, jak jej hlásí Arduino."""
    master_on: bool = True
    master_brightness: int = 128
    panels: List[PanelState] = field(
        default_factory=lambda: [PanelState() for _ in range(PANELS)])

    def panel(self, index: int) -> PanelState:
        """Panel podle čísla 1..4."""
        return self.panels[index - 1]


class LedProtocol:
    """Sestavuje textové příkazy a rozebírá odpovědi Arduina."""

    # ------------------------------------------------------------- příkazy --
    @staticmethod
    def ping() -> str:
        return "PING"

    @staticmethod
    def state() -> str:
        return "STATE"

    @staticmethod
    def save() -> str:
        return "SAVE"

    @staticmethod
    def load() -> str:
        return "LOAD"

    @staticmethod
    def panel_power(index: int, on: bool) -> str:
        return f"P {int(index)} {'ON' if on else 'OFF'}"

    @staticmethod
    def panel_brightness(index: int, value: int) -> str:
        return f"P {int(index)} B {clamp(value)}"

    @staticmethod
    def panel_color(index: int, color: RGB) -> str:
        r, g, b = (clamp(c) for c in color)
        return f"P {int(index)} C {r} {g} {b}"

    @staticmethod
    def all_power(on: bool) -> str:
        return f"ALL {'ON' if on else 'OFF'}"

    @staticmethod
    def all_brightness(value: int) -> str:
        return f"ALL B {clamp(value)}"

    @staticmethod
    def all_color(color: RGB) -> str:
        r, g, b = (clamp(c) for c in color)
        return f"ALL C {r} {g} {b}"

    @staticmethod
    def only(index: int) -> str:
        return f"ONLY {int(index)}"

    # ------------------------------------------------------------- odpovědi -
    @staticmethod
    def is_banner(line: str) -> bool:
        return line.startswith("READY BMSLED")

    @staticmethod
    def parse_banner(line: str) -> Dict[str, str]:
        """``READY BMSLED 1.0 PANELS=4 LEDS=8`` -> slovník s údaji."""
        parts = line.split()
        out: Dict[str, str] = {}
        if len(parts) >= 3:
            out["version"] = parts[2]
        for part in parts[3:]:
            if "=" in part:
                key, _, value = part.partition("=")
                out[key.lower()] = value
        return out

    @staticmethod
    def parse_state(line: str, state: LedState) -> bool:
        """Zpracuje řádek ``STATE …``. Vrací True, pokud se stav změnil."""
        if not line.startswith("STATE "):
            return False
        parts = line.split()
        try:
            if parts[1].upper() == "MASTER":
                state.master_on = parts[2] == "1"
                state.master_brightness = clamp(int(parts[3]))
                return True
            index = int(parts[1])
            if not 1 <= index <= len(state.panels):
                return False
            panel = state.panel(index)
            panel.on = parts[2] == "1"
            panel.brightness = clamp(int(parts[3]))
            panel.color = (clamp(int(parts[4])), clamp(int(parts[5])),
                           clamp(int(parts[6])))
            return True
        except (IndexError, ValueError):
            return False

    @staticmethod
    def is_error(line: str) -> bool:
        return line.startswith("ERR")


def color_to_hex(color: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(clamp(c) for c in color))
