"""Stavební prvky rozhraní podle návrhového systému „Modernist"."""

from typing import Iterable, List, Optional

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                             QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from . import theme


# ------------------------------------------------------------------ popisky --
def label(text: str, role: str = "", parent=None) -> QLabel:
    widget = QLabel(text, parent)
    if role:
        widget.setProperty("role", role)
    if role == "section":
        widget.setText(text.upper())
    elif role == "kicker":
        widget.setText(text.upper())
    return widget


def hline() -> QFrame:
    line = QFrame()
    line.setProperty("role", "hline")
    line.setFixedHeight(2)
    return line


def vline(height: int = 24) -> QFrame:
    line = QFrame()
    line.setProperty("role", "vline")
    line.setFixedSize(1, height)
    return line


# ----------------------------------------------------------------- tlačítka --
def button(text: str = "", variant: str = "secondary", icon_name: str = "",
           tooltip: str = "", parent=None) -> QPushButton:
    """Tlačítko v jedné ze tří podob systému: primary / secondary / ghost."""
    btn = QPushButton(text, parent)
    btn.setProperty("variant", variant)
    btn.setCursor(Qt.PointingHandCursor)
    if icon_name:
        btn._icon_name = icon_name
        btn._icon_variant = variant
        btn.setIconSize(QSize(15, 15))
        _refresh_text_icon(btn)
        theme.on_change(lambda b=btn: _refresh_text_icon(b), btn)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def icon_button(icon_name: str, tooltip: str = "", checkable: bool = False,
                size: int = 34, parent=None) -> QPushButton:
    """Čtvercové tlačítko jen s ikonou, volitelně přepínací."""
    btn = QPushButton(parent)
    btn.setProperty("variant", "icon")
    btn.setCheckable(checkable)
    btn.setFixedSize(size, size)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setIconSize(QSize(16, 16))
    btn._icon_name = icon_name
    _refresh_icon(btn)
    theme.on_change(lambda b=btn: _refresh_icon(b), btn)
    if checkable:
        btn.toggled.connect(lambda _=False, b=btn: _refresh_icon(b))
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def _refresh_text_icon(btn: QPushButton) -> None:
    """Ikona u textového tlačítka – barvu určuje varianta a paleta."""
    variant = getattr(btn, "_icon_variant", "secondary")
    color = theme.ON_ACCENT if variant == "primary" else (
        theme.ACCENT if variant == "ghost" else theme.TEXT)
    btn.setIcon(theme.icon(btn._icon_name, color, 15))


def _refresh_icon(btn: QPushButton) -> None:
    color = theme.ON_ACCENT if btn.isChecked() else theme.TEXT
    btn.setIcon(theme.icon(btn._icon_name, color, 16))


def set_icon(btn: QPushButton, icon_name: str) -> None:
    btn._icon_name = icon_name
    _refresh_icon(btn)


# --------------------------------------------------------------------- karta -
class Card(QFrame):
    """Plocha se světlejším pozadím a volitelným červeným nadtitulkem."""

    def __init__(self, kicker: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("role", "card")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3,
                                     theme.SPACE_3, theme.SPACE_3)
        self._lay.setSpacing(theme.SPACE_2)
        if kicker:
            self._lay.addWidget(label(kicker, "kicker"))

    def layout(self) -> QVBoxLayout:
        return self._lay

    def add(self, widget) -> None:
        if isinstance(widget, QWidget):
            self._lay.addWidget(widget)
        else:
            self._lay.addLayout(widget)


# ------------------------------------------------------------ sbalitelný blok
class Collapsible(QWidget):
    """Blok ovládání, který jde sbalit pod jeden řádek.

    Panel měření má hodně voleb, ale většina se nastaví jednou a pak se jich
    nikdo nedotkne. Sbalené bloky zkracují panel na to, co se používá denně,
    a zbytek nechají na jedno kliknutí."""

    def __init__(self, title: str, expanded: bool = False, parent=None):
        super().__init__(parent)
        self._title = title
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SPACE_1)

        self.button = QPushButton()
        self.button.setCheckable(True)
        self.button.setChecked(expanded)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.toggled.connect(self._onToggled)
        lay.addWidget(self.button)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, theme.SPACE_1)
        self.body_layout.setSpacing(theme.SPACE_2)
        lay.addWidget(self.body)

        self._applyTheme()
        theme.on_change(self._applyTheme)
        self._onToggled(expanded)

    def add(self, item) -> None:
        if isinstance(item, QWidget):
            self.body_layout.addWidget(item)
        else:
            self.body_layout.addLayout(item)

    def setExpanded(self, expanded: bool) -> None:
        self.button.setChecked(bool(expanded))

    def isExpanded(self) -> bool:
        return self.button.isChecked()

    def _onToggled(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.button.setText(("▾  " if expanded else "▸  ") + self._title.upper())

    def _applyTheme(self) -> None:
        self.button.setStyleSheet(
            f"QPushButton {{ border:none; border-top:1px solid {theme.DIVIDER};"
            f"padding:6px 0; text-align:left; font-size:11px; font-weight:600;"
            f"letter-spacing:1px; color:{theme.NEUTRAL_700}; }}"
            f"QPushButton:hover {{ color:{theme.ACCENT}; }}")


# --------------------------------------------------------------- štítek stavu
class Tag(QLabel):
    """Obrysový štítek – „Nepřipojeno" / „Připojeno"."""

    def __init__(self, text: str = "", active: bool = False, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._active = active
        self.set_active(active)
        theme.on_change(self._applyTheme)

    def set_active(self, active: bool, text: Optional[str] = None) -> None:
        if text is not None:
            self.setText(text)
        self._active = active
        self._applyTheme()

    def _applyTheme(self) -> None:
        active = self._active
        if active:
            self.setStyleSheet(
                f"border:1px solid {theme.ACCENT}; background:{theme.ACCENT};"
                f"color:{theme.ON_ACCENT}; font-size:11px; padding:2px 9px;")
        else:
            self.setStyleSheet(
                f"border:1px solid {theme.ACCENT}; color:{theme.ACCENT};"
                "font-size:11px; padding:2px 9px;")


# ---------------------------------------------------------- segmentový ovladač
class SegmentedControl(QWidget):
    """Řada přepínačů v jednom rámečku – náhrada za záložky."""

    currentChanged = pyqtSignal(int)

    def __init__(self, options: Iterable[str], parent=None,
                 compact: bool = False, preselect: bool = True):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._compact = compact
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: List[QPushButton] = []
        for index, text in enumerate(options):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.group.addButton(btn, index)
            lay.addWidget(btn)
            self.buttons.append(btn)
        self._applyTheme()
        theme.on_change(self._applyTheme)
        if self.buttons and preselect:
            self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self.currentChanged) if hasattr(
            self.group, "idClicked") else self.group.buttonClicked[int].connect(
            self.currentChanged)

    def _applyTheme(self) -> None:
        """Vlastní stylopis prvku – přebarvuje se s paletou."""
        compact = self._compact
        self.setStyleSheet(
            f"SegmentedControl {{ border: 1px solid {theme.DIVIDER}; }}")
        for index, btn in enumerate(self.buttons):
            border = "" if index == 0 else f"border-left: 1px solid {theme.DIVIDER};"
            padding = "6px 6px" if compact else "7px 10px"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; border: none; {border}
                    padding: {padding}; font-size: {'11px' if compact else '12px'};
                    font-weight: 600; color: {theme.TEXT};
                }}
                QPushButton:hover:!checked {{ background: {theme.NEUTRAL_300}; }}
                QPushButton:checked {{
                    background: {theme.ACCENT}; color: {theme.ON_ACCENT};
                }}
                QPushButton:disabled {{ color: {theme.NEUTRAL_500}; }}
            """)

    def setCurrentIndex(self, index: int, emit: bool = True) -> None:
        """Přepne volbu. Ohlásí to stejně jako kliknutí, ale jen při změně –
        jinak by se program mohl zacyklit. S ``emit=False`` jen srovná
        zobrazený stav podle skutečnosti, aniž by se něco spouštělo."""
        if not 0 <= index < len(self.buttons) or self.currentIndex() == index:
            return
        self.buttons[index].setChecked(True)
        if emit:
            self.currentChanged.emit(index)

    def currentIndex(self) -> int:
        return self.group.checkedId()

    def clearSelection(self) -> None:
        """Zruší zvýraznění – žádná z voleb není označená."""
        self.group.setExclusive(False)
        for btn in self.buttons:
            btn.setChecked(False)
        self.group.setExclusive(True)

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)


# --------------------------------------------------------- sbalitelný panel --
class SidePanel(QWidget):
    """Boční panel s hlavičkou a tlačítkem pro sbalení."""

    def __init__(self, title: str, side: str = "left", parent=None):
        super().__init__(parent)
        self.setProperty("role", "panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._side = side
        self._collapsed = False
        self.setFixedWidth(theme.PANEL_WIDTH)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QWidget()
        head_lay = QHBoxLayout(head)
        head_lay.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        self.title = label(title, "section")
        self.toggle_button = icon_button(
            "chev-l" if side == "left" else "chev-r",
            "Sbalit panel", size=30)
        self.toggle_button.clicked.connect(self.toggle)
        if side == "left":
            head_lay.addWidget(self.title)
            head_lay.addStretch(1)
            head_lay.addWidget(self.toggle_button)
        else:
            head_lay.addWidget(self.toggle_button)
            head_lay.addStretch(1)
            head_lay.addWidget(self.title)
        outer.addWidget(head)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(theme.SPACE_4, 0, theme.SPACE_4, theme.SPACE_4)
        self.body_layout.setSpacing(theme.SPACE_4)
        outer.addWidget(self.body, 1)

    # ------------------------------------------------------------- sbalení --
    def is_collapsed(self) -> bool:
        return self._collapsed

    def toggle(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.body.setVisible(not collapsed)
        self.title.setVisible(not collapsed)
        self.setFixedWidth(theme.PANEL_COLLAPSED if collapsed else theme.PANEL_WIDTH)
        opposite = {"chev-l": "chev-r", "chev-r": "chev-l"}
        set_icon(self.toggle_button, opposite[self.toggle_button._icon_name])
        self.toggle_button.setToolTip("Rozbalit panel" if collapsed else "Sbalit panel")

    def add(self, widget, stretch: int = 0) -> None:
        if isinstance(widget, QWidget):
            self.body_layout.addWidget(widget, stretch)
        else:
            self.body_layout.addLayout(widget, stretch)


# ------------------------------------------------------------------ řádky ----
def row(*widgets, spacing: int = theme.SPACE_2) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for item in widgets:
        if item is None:
            lay.addStretch(1)
        elif isinstance(item, QWidget):
            lay.addWidget(item)
        elif isinstance(item, tuple):
            lay.addWidget(item[0], item[1])
        else:
            lay.addLayout(item)
    return lay
