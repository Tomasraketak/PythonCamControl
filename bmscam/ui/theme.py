"""Vzhled aplikace – návrhový systém „Modernist".

Barvy, rozestupy, písmo a stylopis pro Qt na jednom místě, aby se vzhled
dal upravit bez zásahů do jednotlivých oken. Odpovídá předloze
`CamControl - Redesign.dc.html`.
"""

import weakref

from PyQt5.QtCore import QByteArray, QSize, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer

# ------------------------------------------------------------------- barvy --
#: Dvě palety téhož systému. Světlá je předloha, tmavá z ní vychází –
#: stejný akcent, obrácené neutrály. Barvy se drží v globálních jménech
#: modulu, protože z nich staví stylopis i jednotlivé widgety; přepnutí
#: režimu je tedy přepsání těchto jmen a překreslení (viz set_mode).
LIGHT = {
    "BG": "#f3f2f2",
    "SURFACE": "#eae9e9",
    "TEXT": "#201e1d",
    "ACCENT": "#ec3013",
    "ACCENT_600": "#dd2b0f",
    "ACCENT_700": "#ae1800",
    "ACCENT_100": "#fff2ef",
    "ON_ACCENT": "#f3f2f2",      # text na akcentní ploše
    "DIVIDER": "#8d8b8a",        # #201e1d při 40 % krytí na světlém pozadí
    "NEUTRAL_200": "#eae7e7",
    "NEUTRAL_300": "#d7d3d3",
    "NEUTRAL_400": "#bab6b6",
    "NEUTRAL_500": "#9b9797",
    "NEUTRAL_600": "#7d7979",
    "NEUTRAL_700": "#605d5d",
    "NEUTRAL_900": "#2d2b2b",
    "STAGE_DARK": "#141414",
    "STAGE_LIGHT": "#eae7e7",
    "TOOLTIP_BG": "#2d2b2b",
    "TOOLTIP_TEXT": "#f3f2f2",
}

DARK = {
    "BG": "#181716",
    "SURFACE": "#221f1e",
    "TEXT": "#f2efed",
    "ACCENT": "#ec3013",
    "ACCENT_600": "#f5492e",     # na tmavém pozadí musí hover zesvětlit
    "ACCENT_700": "#ff6448",
    "ACCENT_100": "#3a1710",
    "ON_ACCENT": "#ffffff",
    "DIVIDER": "#565150",
    "NEUTRAL_200": "#2b2827",
    "NEUTRAL_300": "#35312f",
    "NEUTRAL_400": "#4d4846",
    "NEUTRAL_500": "#807a78",
    "NEUTRAL_600": "#a49d9a",
    "NEUTRAL_700": "#c6bfbc",
    "NEUTRAL_900": "#ece8e6",
    "STAGE_DARK": "#0d0c0c",
    "STAGE_LIGHT": "#2b2827",
    "TOOLTIP_BG": "#ece8e6",
    "TOOLTIP_TEXT": "#181716",
}

_icon_cache: dict = {}

MODES = {"light": LIGHT, "dark": DARK}
_mode = "light"

globals().update(LIGHT)


def mode() -> str:
    """Název právě použité palety („light“ / „dark“)."""
    return _mode


def set_mode(name: str) -> bool:
    """Přepne paletu. Vrací True, když se něco změnilo.

    Samotné přebarvení okna má na starost :func:`refresh` a nový
    :func:`stylesheet` – tahle funkce jen vymění hodnoty barev."""
    global _mode
    if name not in MODES or name == _mode:
        return False
    _mode = name
    globals().update(MODES[name])
    _icon_cache.clear()          # ikony se kreslí v barvě textu
    return True


# Widgety, které mají vlastní stylopis (nejde je popsat globálním QSS),
# se sem přihlásí a po přepnutí palety se překreslí. Odkaz je slabý, aby
# zavřené okno nedrželo v paměti nic navíc.
_hooks: list = []


def on_change(callback, owner=None) -> None:
    """Zaregistruje překreslení widgetu po změně palety.

    U vázané metody stačí ona sama – drží se slabým odkazem, takže
    zavřené okno nic v paměti nedrží. U volné funkce (typicky lambda nad
    widgetem) předejte `owner`: hlídá se jeho životnost, protože na
    samotnou lambdu už nikdo jiný neodkazuje."""
    if owner is not None:
        _hooks.append((weakref.ref(owner), callback))
        return
    if hasattr(callback, "__self__"):
        try:
            _hooks.append((None, weakref.WeakMethod(callback)))
            return
        except TypeError:                # vestavěná metoda Qt (např. update)
            _hooks.append((weakref.ref(callback.__self__), callback))
            return
    _hooks.append((None, callback))


def refresh() -> None:
    """Zavolá všechna registrovaná překreslení; mrtvé odkazy zahodí."""
    alive = []
    for owner_ref, entry in list(_hooks):
        if owner_ref is not None and owner_ref() is None:
            continue                     # widget mezitím zanikl
        callback = entry() if isinstance(entry, weakref.WeakMethod) else entry
        if callback is None:
            continue
        alive.append((owner_ref, entry))
        try:
            callback()
        except RuntimeError:             # widget už v Qt neexistuje
            alive.pop()
    _hooks[:] = alive


# --------------------------------------------------------------- rozestupy --
SPACE_1, SPACE_2, SPACE_3, SPACE_4, SPACE_6 = 4, 8, 12, 16, 24

PANEL_WIDTH = 340
PANEL_COLLAPSED = 52

FONT_STACK = '"Archivo", "Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif'


def heading_font(size: int = 13, weight: int = 87) -> QFont:
    """Nadpisové písmo systému (Archivo 800, jinak nejtučnější dostupné)."""
    font = QFont()
    for family in ("Archivo", "Segoe UI Variable Display", "Segoe UI",
                   "DejaVu Sans", font.defaultFamily()):
        if family in QFontDatabase().families():
            font.setFamily(family)
            break
    font.setPixelSize(size)
    font.setWeight(weight)
    return font


# -------------------------------------------------------------------- ikony -
#: Obrysové ikony (sada Lucide) použité v předloze.
_ICONS = {
    "chev-l": "m15 18-6-6 6-6",
    "chev-r": "m9 18 6-6-6-6",
    "plus": "M5 12h14 M12 5v14",
    "minus": "M5 12h14",
    "maximize": ("M8 3H5a2 2 0 0 0-2 2v3 M21 8V5a2 2 0 0 0-2-2h-3 "
                 "M3 16v3a2 2 0 0 0 2 2h3 M16 21h3a2 2 0 0 0 2-2v-3"),
    "grid": "M3 3h7v7H3z M14 3h7v7h-7z M14 14h7v7h-7z M3 14h7v7H3z",
    "crosshair": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 3v3 M12 18v3 M3 12h3 M18 12h3",
    "ruler": ("M21.3 8.7 8.7 21.3a1 1 0 0 1-1.4 0l-4.6-4.6a1 1 0 0 1 0-1.4"
              "L15.3 2.7a1 1 0 0 1 1.4 0l4.6 4.6a1 1 0 0 1 0 1.4Z "
              "m14.5 12.5 2-2 m11.5 9.5 2-2 m8.5 6.5 2-2 m17.5 15.5 2-2"),
    "sun": ("M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v2 M12 20v2 m4.9 4.9 1.4 1.4 "
            "m17.7 17.7 1.4 1.4 M2 12h2 M20 12h2 m6.3 17.7-1.4 1.4 m19.1 4.9-1.4 1.4"),
    "moon": "M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z",
    "help": ("M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20 "
             "M9.09 9a3 3 0 1 1 5.83 1c0 2-3 3-3 3 M12 17h.01"),
    "x": "M18 6 6 18 m6 6 12 12",
    "menu": "M3 6h18 M3 12h18 M3 18h18",
    "save": ("M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5"
             "a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z M17 21v-7H7v7 M7 3v4h8"),
    "plug": "M12 22v-5 M9 8V2 M15 8V2 M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z",
    "search": "M11 3a8 8 0 1 0 0 16 8 8 0 0 0 0-16 m21 21-4.3-4.3",
    "camera": ("M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9"
               "a2 2 0 0 0-2-2h-3z M12 10a3 3 0 1 0 0 6 3 3 0 0 0 0-6"),
    "video": ("m16 13 5.2-3.6a1 1 0 0 1 1.6.8v9.6a1 1 0 0 1-1.6.8L16 17 M1 6h15v12H1z"),
    "timer": "M10 2h4 M12 14v-4 M12 6a8 8 0 1 0 0 16 8 8 0 0 0 0-16",
    "folder": ("M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.7-.9L9.1 3.9"
               "A2 2 0 0 0 7.4 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"),
    "refresh": ("M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8 M3 3v5h5 "
                "M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16 M16 16h5v5"),
    "aperture": ("M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20 m14.31 8 5.74 9.94 M9.69 8h11.48 "
                 "m7.38 12 5.74-9.94 M9.69 16 3.95 6.06 M14.31 16H2.83 m16.62 12-5.74 9.94"),
    "lightbulb": ("M15 14c.2-1 .7-1.7 1.5-2.7A5 5 0 0 0 18 8a6 6 0 0 0-12 0c0 1.2.5 2.3 "
                  "1.5 3.3.7 1 1.3 1.6 1.5 2.7 M9 18h6 M10 22h4"),
    "focus": "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3",
}


def icon(name: str, color: str = "", size: int = 16) -> QIcon:
    """Vrátí ikonu vykreslenou z SVG cesty v zadané barvě."""
    color = color or TEXT
    key = (name, color, size)
    if key in _icon_cache:
        return _icon_cache[key]
    path = _ICONS.get(name)
    if path is None:
        return QIcon()
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" '
           f'stroke-linejoin="round"><path d="{path}"/></svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    result = QIcon(pixmap)
    _icon_cache[key] = result
    return result


# ---------------------------------------------------------------- stylopis --
def stylesheet() -> str:
    """Qt stylopis odpovídající návrhovému systému."""
    return f"""
* {{
    font-family: {FONT_STACK};
    font-size: 13px;
    color: {TEXT};
}}
QWidget#root, QMainWindow, QDialog {{ background: {BG}; }}

/* ---------------------------------------------------------------- text -- */
QLabel[role="brand"] {{ font-size: 18px; font-weight: 800; letter-spacing: 0.02em; }}
QLabel[role="section"] {{
    font-size: 11px; font-weight: 600; letter-spacing: 1.1px;
    color: {NEUTRAL_700};
}}
QLabel[role="kicker"] {{
    font-size: 10px; font-weight: 600; letter-spacing: 1.0px; color: {ACCENT};
}}
QLabel[role="meta"] {{ font-size: 11px; color: {NEUTRAL_600}; }}
QLabel[role="value"] {{ font-size: 12px; font-weight: 800; }}
QLabel[role="field"] {{ font-size: 12px; color: {NEUTRAL_700}; }}
QLabel[role="empty-title"] {{ font-size: 20px; font-weight: 800; color: {NEUTRAL_500}; }}

/* --------------------------------------------------------------- tlačítka */
QPushButton {{
    background: transparent; border: 1px solid transparent; border-radius: 0;
    padding: 7px 11px; font-weight: 700; font-size: 13px;
}}
QPushButton:disabled {{ color: {NEUTRAL_500}; }}
QPushButton[variant="primary"] {{ background: {ACCENT}; color: {ON_ACCENT}; }}
QPushButton[variant="primary"]:hover {{ background: {ACCENT_600}; }}
QPushButton[variant="primary"]:pressed {{ background: {ACCENT_700}; }}
QPushButton[variant="primary"]:disabled {{ background: {NEUTRAL_400}; color: {ON_ACCENT}; }}
QPushButton[variant="secondary"] {{ border-color: {DIVIDER}; }}
QPushButton[variant="secondary"]:hover {{ background: {NEUTRAL_300}; }}
QPushButton[variant="secondary"]:pressed {{ background: {NEUTRAL_400}; }}
QPushButton[variant="ghost"] {{ color: {ACCENT}; padding: 5px 6px; text-align: left; }}
QPushButton[variant="ghost"]:hover {{ background: {ACCENT_100}; }}
QPushButton[variant="icon"] {{ border-color: {DIVIDER}; padding: 0; }}
QPushButton[variant="icon"]:hover {{ background: {NEUTRAL_300}; }}
QPushButton[variant="icon"]:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QToolButton {{
    background: transparent; border: 1px solid transparent; border-radius: 0;
    padding: 4px 6px; font-size: 12px;
}}
QToolButton:hover {{ background: {NEUTRAL_300}; }}

/* ------------------------------------------------------------- formuláře */
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {SURFACE}; border: 1px solid {DIVIDER}; border-radius: 0;
    padding: 5px 8px; min-height: 22px; selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {NEUTRAL_900};
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT};
}}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {NEUTRAL_500}; background: {NEUTRAL_200};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {BG}; border: 1px solid {DIVIDER};
    selection-background-color: {ACCENT}; selection-color: {ON_ACCENT}; outline: none;
}}
/* Úzká pole vedle posuvníků – bez odsazení by se do nich nevešlo „255". */
QSpinBox[role="inline"], QDoubleSpinBox[role="inline"] {{
    padding: 2px 3px; min-height: 20px;
}}
/* Pole s hodnotou vlastnosti: rámeček dává najevo, že se do něj dá psát. */
QSpinBox[role="value"], QDoubleSpinBox[role="value"] {{
    background: {BG}; border: 1px solid {DIVIDER}; font-weight: 800;
    font-size: 12px; padding: 2px 2px 2px 4px; min-height: 20px;
}}
QSpinBox[role="value"]:hover, QDoubleSpinBox[role="value"]:hover {{
    border-color: {NEUTRAL_900};
}}
QSpinBox[role="value"]:focus, QDoubleSpinBox[role="value"]:focus {{
    border-color: {ACCENT};
}}
/* Šipky číselníků kreslí styl Fusion sám – vlastní QSS je jen rozbíjí. */

/* ------------------------------------------------------------ zaškrtávátka */
QCheckBox {{ spacing: 8px; font-size: 13px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border: 2px solid {DIVIDER};
    background: {SURFACE}; border-radius: 0;
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:disabled {{ border-color: {NEUTRAL_400}; background: {NEUTRAL_200}; }}
QCheckBox:disabled {{ color: {NEUTRAL_500}; }}

/* -------------------------------------------------------------- posuvníky */
QSlider::groove:horizontal {{ height: 2px; background: {DIVIDER}; }}
QSlider::sub-page:horizontal {{ height: 2px; background: {ACCENT}; }}
QSlider::handle:horizontal {{
    width: 10px; height: 18px; margin: -8px 0; background: {ACCENT}; border-radius: 0;
}}
QSlider::handle:horizontal:hover {{ background: {ACCENT_600}; }}
QSlider::groove:horizontal:disabled {{ background: {NEUTRAL_300}; }}
QSlider::sub-page:horizontal:disabled {{ background: {NEUTRAL_400}; }}
QSlider::handle:horizontal:disabled {{ background: {NEUTRAL_400}; }}

/* ------------------------------------------------------------------ plochy */
QFrame[role="card"] {{ background: {SURFACE}; border: none; }}
QFrame[role="hline"] {{ background: {DIVIDER}; max-height: 2px; min-height: 2px; border: none; }}
QFrame[role="vline"] {{ background: {DIVIDER}; max-width: 1px; min-width: 1px; border: none; }}
QWidget[role="nav"], QWidget[role="toolbar"] {{ background: {BG}; }}
QWidget[role="panel"] {{ background: {BG}; }}
QWidget[role="statusbar"] {{ background: {BG}; }}

/* ------------------------------------------------------------------ ostatní */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {NEUTRAL_400}; min-height: 30px; border-radius: 0; }}
QScrollBar::handle:vertical:hover {{ background: {NEUTRAL_600}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {NEUTRAL_400}; min-width: 30px; }}

/* ----------------------------------------------------- dialogy a průběh -- */
QDialogButtonBox QPushButton, QMessageBox QPushButton {{
    border: 1px solid {DIVIDER}; padding: 6px 14px; min-width: 72px;
}}
QDialogButtonBox QPushButton:hover, QMessageBox QPushButton:hover {{
    background: {NEUTRAL_300};
}}
QDialogButtonBox QPushButton:default, QMessageBox QPushButton:default {{
    border-color: {ACCENT};
}}
QProgressBar {{
    background: {SURFACE}; border: 1px solid {DIVIDER}; border-radius: 0;
    min-height: 16px; text-align: center; color: {TEXT};
}}
QProgressBar::chunk {{ background: {ACCENT}; }}

/* ------------------------------------------------------------------ tabulky */
QTableWidget, QTableView {{
    background: {BG}; alternate-background-color: {SURFACE};
    gridline-color: {DIVIDER}; color: {TEXT};
    selection-background-color: {ACCENT}; selection-color: {ON_ACCENT};
    border: 1px solid {DIVIDER};
}}
QHeaderView {{ background: {SURFACE}; }}
QHeaderView::section {{
    background: {SURFACE}; color: {NEUTRAL_700}; border: none;
    border-bottom: 1px solid {DIVIDER}; border-right: 1px solid {DIVIDER};
    padding: 4px 6px; font-size: 11px; font-weight: 700;
}}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}
QSplitter::handle {{ background: {DIVIDER}; }}

QMenu {{ background: {BG}; border: 1px solid {DIVIDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 12px; }}
QMenu::item:selected {{ background: {ACCENT}; color: {ON_ACCENT}; }}
QMenu::separator {{ height: 1px; background: {DIVIDER}; margin: 4px 8px; }}

QPlainTextEdit {{
    background: {SURFACE}; border: 1px solid {DIVIDER}; border-radius: 0;
    font-family: "Consolas", "DejaVu Sans Mono", monospace; font-size: 11px;
    color: {NEUTRAL_700};
}}
QToolTip {{
    background: {TOOLTIP_BG}; color: {TOOLTIP_TEXT}; border: none; padding: 5px 8px;
}}
"""
