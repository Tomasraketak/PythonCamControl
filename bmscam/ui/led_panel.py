"""Panel pro řízení osvětlení – 4 moduly FC101 (8× WS2812) přes Arduino."""

from typing import List, Optional

from PyQt5.QtCore import QEvent, QSettings, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QTextCursor
from PyQt5.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFrame,
                             QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPlainTextEdit, QPushButton, QSizePolicy, QSlider,
                             QSpinBox, QVBoxLayout, QWidget)

from .. import leds as leds_mod
from ..leds import (BAUD, DEFAULT_ROTATION, LEDS_PER_PANEL, PANEL_NAMES,
                    PANEL_SHORT, PANELS,
                    CHANNELS, PRESETS, LedProtocol, LedState, color_to_hex)
from ..serialio import (SerialLink, available, guess_arduino_port,
                        list_serial_ports, unavailable_reason)
from . import theme
from .widgets import (Card, SegmentedControl, Tag, button, hline, icon_button,
                      label, row)


def _swatch_style(color) -> str:
    r, g, b = color
    text = "#000000" if (r * 299 + g * 587 + b * 114) / 1000 > 140 else "#ffffff"
    return (f"QPushButton {{ background-color: rgb({r},{g},{b}); color: {text};"
            f"border: 1px solid {theme.DIVIDER}; padding: 3px; font-size: 11px;"
            "font-weight: 700; }"
            f"QPushButton:hover {{ border-color: {theme.ACCENT}; }}")


class PanelWidget(QFrame):
    """Jedna strana čtverce: zapnutí, jas, barva."""

    powerChanged = pyqtSignal(int, bool)
    brightnessChanged = pyqtSignal(int, int)
    colorChanged = pyqtSignal(int, tuple)
    soloRequested = pyqtSignal(int)
    copyToAllRequested = pyqtSignal(tuple)

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self._color = (255, 255, 255)
        self._updating = False
        self.setStyleSheet(f"PanelWidget {{ border: 1px solid {theme.DIVIDER}; }}")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(7, 5, 7, 6)
        lay.setSpacing(3)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(4)
        name = label(f"{index} · {PANEL_NAMES[index - 1]}", "kicker")
        name.setMinimumWidth(0)
        head.addWidget(name)
        head.addStretch(1)
        self.btn_solo = QPushButton("sólo")
        self.btn_solo.setToolTip(
            f"Rozsvítit pouze tuto stranu – osvětlení {PANEL_SHORT[index - 1]}")
        self.btn_solo.setStyleSheet(
            f"QPushButton {{ border:none; color:{theme.NEUTRAL_600}; font-size:10px;"
            "padding:0 3px; }"
            f"QPushButton:hover {{ color:{theme.ACCENT}; }}")
        self.btn_solo.setCursor(Qt.PointingHandCursor)
        self.btn_solo.clicked.connect(lambda: self.soloRequested.emit(self.index))
        head.addWidget(self.btn_solo)
        self.chk_on = QCheckBox()
        self.chk_on.setToolTip("Zapnout / vypnout tuto stranu")
        self.chk_on.toggled.connect(
            lambda on: self._emit(self.powerChanged, self.index, on))
        head.addWidget(self.chk_on)
        lay.addLayout(head)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 255)
        self.slider.setValue(255)
        self.slider.setMinimumWidth(40)
        self.slider.valueChanged.connect(self._onBrightness)
        body.addWidget(self.slider, 1)
        self.spin = QSpinBox()
        self.spin.setRange(0, 255)
        self.spin.setValue(255)
        self.spin.setProperty("role", "inline")
        self.spin.setButtonSymbols(QSpinBox.NoButtons)
        self.spin.setAlignment(Qt.AlignRight)
        self.spin.setKeyboardTracking(False)
        self.spin.setFixedWidth(34)
        self.spin.valueChanged.connect(self.slider.setValue)
        body.addWidget(self.spin)
        lay.addLayout(body)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(4)
        self.btn_color = QPushButton()
        self.btn_color.setCursor(Qt.PointingHandCursor)
        self.btn_color.setToolTip("Barva této strany")
        self.btn_color.setMinimumWidth(40)
        self.btn_color.clicked.connect(self._pickColor)
        bottom.addWidget(self.btn_color, 1)
        self.btn_copy = QPushButton("→")
        self.btn_copy.setFixedWidth(26)
        self.btn_copy.setToolTip("Použít tuto barvu na všechny strany")
        self.btn_copy.setStyleSheet(
            f"QPushButton {{ border:1px solid {theme.DIVIDER}; padding:3px 0;"
            "font-size:13px; font-weight:700; }"
            f"QPushButton:hover {{ background:{theme.NEUTRAL_300}; }}")
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.clicked.connect(
            lambda: self.copyToAllRequested.emit(self._color))
        bottom.addWidget(self.btn_copy)
        lay.addLayout(bottom)

        self.setColor(self._color)

    # ------------------------------------------------------------- pomocné --
    def _emit(self, signal, *args) -> None:
        if not self._updating:
            signal.emit(*args)

    def _onBrightness(self, value: int) -> None:
        was, self._updating = self._updating, True
        self.spin.setValue(value)
        self._updating = was
        self._emit(self.brightnessChanged, self.index, value)

    def _pickColor(self) -> None:
        chosen = QColorDialog.getColor(QColor(*self._color), self,
                                       f"Barva – {PANEL_NAMES[self.index - 1]}")
        if chosen.isValid():
            rgb = (chosen.red(), chosen.green(), chosen.blue())
            self.setColor(rgb)
            self._emit(self.colorChanged, self.index, rgb)

    # -------------------------------------------------------------- hodnoty -
    def setColor(self, color) -> None:
        self._color = tuple(int(c) for c in color)
        self.btn_color.setStyleSheet(_swatch_style(self._color))
        self.btn_color.setText(color_to_hex(self._color).upper())

    def color(self):
        return self._color

    def isOn(self) -> bool:
        return self.chk_on.isChecked()

    def brightness(self) -> int:
        return self.spin.value()

    def setState(self, on: bool, brightness: int, color) -> None:
        self._updating = True
        try:
            self.chk_on.setChecked(bool(on))
            self.slider.setValue(int(brightness))
            self.spin.setValue(int(brightness))
            self.setColor(color)
        finally:
            self._updating = False


class LedPanel(QWidget):
    """Celý panel osvětlení včetně připojení k desce a konzole."""

    logMessage = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("BMS", "CamControl")
        self.link = SerialLink(self)
        self.state = LedState()
        self.rotation = int(self.settings.value("led_rotation", DEFAULT_ROTATION))
        self._pending_brightness = {}
        self._history: List[str] = []
        self._history_pos = 0

        self._buildUi()

        self.link.opened.connect(self._onOpened)
        self.link.closed.connect(self._onClosed)
        self.link.failed.connect(self._onFailed)
        self.link.lineReceived.connect(self._onLine)
        self.link.lineSent.connect(lambda t: self._log(f"» {t}", "#2a7a55"))

        self._send_timer = QTimer(self)
        self._send_timer.setSingleShot(True)
        self._send_timer.setInterval(60)
        self._send_timer.timeout.connect(self._flushBrightness)

        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(250)
        self._sync_timer.timeout.connect(
            lambda: self.link.is_open() and self.link.send(LedProtocol.state()))

        self.refreshPorts()
        self._setConnected(False)

    # =================================================================== UI ==
    def _buildUi(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SPACE_4)
        lay.addWidget(self._buildConnectionCard())
        lay.addWidget(self._buildMasterBox())
        lay.addWidget(hline())
        lay.addWidget(self._buildSidesBox())
        lay.addWidget(self._buildConsoleBox())
        lay.addStretch(1)

    def _buildConnectionCard(self) -> Card:
        card = Card()
        self.tag_link = Tag("Nepřipojeno")
        card.add(row(label("Arduino", "kicker"), None, self.tag_link))

        self.cmb_port = QComboBox()
        self.cmb_port.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLength)
        self.cmb_port.setMinimumContentsLength(8)
        self.cmb_port.setMinimumWidth(90)
        card.add(self.cmb_port)

        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["9600", "19200", "38400", "57600", "115200", "250000"])
        self.cmb_baud.setCurrentText(str(self.settings.value("led_baud", BAUD)))
        self.cmb_baud.setFixedWidth(92)
        self.btn_ports = button("Hledat", "secondary")
        self.btn_ports.clicked.connect(self.refreshPorts)
        self.btn_connect = button("Připojit", "primary")
        self.btn_connect.clicked.connect(self.toggleConnection)
        card.add(row(self.cmb_baud, (self.btn_ports, 1), (self.btn_connect, 1)))

        self.lbl_status = label("", "meta")
        self.lbl_status.setWordWrap(True)
        card.add(self.lbl_status)
        return card

    def _buildMasterBox(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SPACE_3)

        self.chk_master = QCheckBox("Osvětlení zapnuto")
        self.chk_master.toggled.connect(self._onMasterPower)
        self.btn_off = button("Zhasnout vše", "ghost")
        self.btn_off.clicked.connect(lambda: self.chk_master.setChecked(False))
        lay.addLayout(row(self.chk_master, None, self.btn_off))

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(QLabel("Hlavní jas"))
        head.addStretch(1)
        self.spin_master = QSpinBox()
        self.spin_master.setRange(0, 255)
        self.spin_master.setValue(128)
        self.spin_master.setProperty("role", "inline")
        self.spin_master.setButtonSymbols(QSpinBox.NoButtons)
        self.spin_master.setAlignment(Qt.AlignRight)
        self.spin_master.setKeyboardTracking(False)
        self.spin_master.setFixedWidth(42)
        head.addWidget(self.spin_master)
        lay.addLayout(head)

        self.slider_master = QSlider(Qt.Horizontal)
        self.slider_master.setRange(0, 255)
        self.slider_master.setValue(128)
        self.slider_master.valueChanged.connect(self._onMasterBrightness)
        self.spin_master.valueChanged.connect(self.slider_master.setValue)
        lay.addWidget(self.slider_master)

        self.cmb_preset = QComboBox()
        for name, rgb in PRESETS:
            self.cmb_preset.addItem(name, rgb)
        self.cmb_preset.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLength)
        self.cmb_preset.setMinimumContentsLength(6)
        self.cmb_preset.activated.connect(self._onPreset)
        self.btn_master_color = button("Vlastní…", "secondary")
        self.btn_master_color.clicked.connect(self._pickMasterColor)
        lay.addLayout(row((self.cmb_preset, 1), self.btn_master_color))

        lay.addWidget(label("Jediný kanál", "field"))
        channels = QHBoxLayout()
        channels.setContentsMargins(0, 0, 0, 0)
        channels.setSpacing(4)
        self.channel_buttons = {}
        for key, name, rgb, typical, span in CHANNELS:
            btn = button(f"{typical} nm")
            btn.setStyleSheet(_swatch_style(rgb))
            btn.setToolTip(
                f"{name} kanál – rozsvítí všechny čtyři strany jen touto "
                f"složkou.\nVlnová délka {span}, typicky kolem {typical} nm.")
            btn.clicked.connect(lambda _=False, c=rgb: self._setAllColor(c))
            channels.addWidget(btn, 1)
            self.channel_buttons[key] = btn
        lay.addLayout(channels)

        lay.addWidget(label("Šikmé osvětlení", "field"))
        self.seg_direction = SegmentedControl(["H", "P", "D", "L", "◎"],
                                             compact=True, preselect=False)
        for index, short in enumerate(PANEL_SHORT):
            self.seg_direction.buttons[index].setToolTip(
                f"Rozsvítit pouze stranu „{PANEL_NAMES[index]}“ – osvětlení {short}")
        self.seg_direction.buttons[4].setToolTip("Rozsvítit všechny čtyři strany")
        self.seg_direction.currentChanged.connect(self._onDirection)
        self.dir_buttons = self.seg_direction.buttons
        lay.addWidget(self.seg_direction)
        return box

    def _buildSidesBox(self) -> QWidget:
        """Strany rozmístěné tak, jak leží moduly kolem objektivu."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(label("Jednotlivé strany", "section"))

        self.panels: List[PanelWidget] = []
        for i in range(PANELS):
            widget = PanelWidget(i + 1)
            widget.powerChanged.connect(self._onPanelPower)
            widget.brightnessChanged.connect(self._onPanelBrightness)
            widget.colorChanged.connect(self._onPanelColor)
            widget.soloRequested.connect(self._onSolo)
            widget.copyToAllRequested.connect(self._onCopyToAll)
            self.panels.append(widget)

        lay.addWidget(self._buildCross())

        grid = QGridLayout()
        grid.setSpacing(5)
        grid.addWidget(self.panels[0], 0, 0, 1, 2)      # horní
        grid.addWidget(self.panels[3], 1, 0)            # levá
        grid.addWidget(self.panels[1], 1, 1)            # pravá
        grid.addWidget(self.panels[2], 2, 0, 1, 2)      # dolní
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        # Který modul leží nahoře, závisí na tom, kde se připojil datový
        # vodič. Bez tohohle přepínače by se to dalo spravit jen přepájením.
        self.cmb_rotation = QComboBox()
        for steps in range(PANELS):
            self.cmb_rotation.addItem(
                "1. modul: {}".format(PANEL_NAMES[steps % PANELS].lower()), steps)
        self.cmb_rotation.setToolTip(
            "Kde ve skutečnosti leží modul, který sketch adresuje jako první.\n"
            "Zkuste „sólo“ u horní strany – když se rozsvítí jiná, přepněte "
            "sem tu, která se rozsvítila.")
        index = self.cmb_rotation.findData(self.rotation)
        self.cmb_rotation.setCurrentIndex(max(0, index))
        self.cmb_rotation.activated.connect(self._onRotationChosen)
        lay.addLayout(row(label("Natočení", "meta"), None, (self.cmb_rotation, 2)))
        return box

    def _buildCross(self) -> QWidget:
        """Zapínání stran rozmístěné do kříže – jako moduly kolem objektivu.

        Podrobné ovládání (jas, barva) zůstává v kartách pod tím; tady jde
        jen o to, aby šlo stranu zhasnout tam, kde ve skutečnosti leží."""
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)

        self.cross_buttons: List[QPushButton] = []
        for index in range(PANELS):
            btn = QPushButton(PANEL_NAMES[index])
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip("Zapnout / vypnout osvětlení {}"
                           .format(PANEL_SHORT[index]))
            btn.setStyleSheet(
                f"QPushButton {{ border:1px solid {theme.DIVIDER}; padding:6px 4px;"
                "font-size:11px; }"
                f"QPushButton:checked {{ background:{theme.ACCENT}; color:white;"
                f" border-color:{theme.ACCENT}; }}")
            btn.clicked.connect(
                lambda on, i=index: self.panels[i].chk_on.setChecked(on))
            # karta a tlačítko v kříži ukazují jeden a týž stav
            self.panels[index].chk_on.toggled.connect(
                lambda on, i=index: self._syncCross(i, on))
            self.cross_buttons.append(btn)

        middle = label("objektiv", "meta")
        middle.setAlignment(Qt.AlignCenter)

        grid.addWidget(self.cross_buttons[0], 0, 1)     # horní
        grid.addWidget(self.cross_buttons[3], 1, 0)     # levá
        grid.addWidget(middle, 1, 1)
        grid.addWidget(self.cross_buttons[1], 1, 2)     # pravá
        grid.addWidget(self.cross_buttons[2], 2, 1)     # dolní
        for column in range(3):
            grid.setColumnStretch(column, 1)
        return box

    def _syncCross(self, index: int, on: bool) -> None:
        button_ = self.cross_buttons[index]
        if button_.isChecked() != on:
            button_.blockSignals(True)
            button_.setChecked(on)
            button_.blockSignals(False)

    def _buildConsoleBox(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SPACE_2)

        self.btn_console = QPushButton("▸  SÉRIOVÁ KONZOLE")
        self.btn_console.setCheckable(True)
        self.btn_console.setCursor(Qt.PointingHandCursor)
        self.btn_console.setStyleSheet(
            f"QPushButton {{ border:1px solid {theme.DIVIDER}; padding:6px 10px;"
            f"text-align:left; font-size:11px; font-weight:600; letter-spacing:1px;"
            f"color:{theme.NEUTRAL_700}; }}"
            f"QPushButton:hover {{ background:{theme.NEUTRAL_300}; }}")
        self.btn_console.toggled.connect(self._onConsoleToggled)
        lay.addWidget(self.btn_console)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(500)
        self.console.setFixedHeight(120)
        self.console.setVisible(False)
        lay.addWidget(self.console)

        self.console_row = QWidget()
        row_lay = QHBoxLayout(self.console_row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(theme.SPACE_2)
        self.edit_cmd = QLineEdit()
        self.edit_cmd.setPlaceholderText("např. P 1 C 255 0 0")
        self.edit_cmd.returnPressed.connect(self._sendManual)
        self.edit_cmd.installEventFilter(self)
        row_lay.addWidget(self.edit_cmd, 1)
        btn_send = button("Odeslat", "secondary")
        btn_send.clicked.connect(self._sendManual)
        row_lay.addWidget(btn_send)
        btn_clear = icon_button("x", "Vyčistit záznam", size=30)
        btn_clear.clicked.connect(self.console.clear)
        row_lay.addWidget(btn_clear)
        self.console_row.setVisible(False)
        lay.addWidget(self.console_row)
        return box

    def _onConsoleToggled(self, on: bool) -> None:
        self.btn_console.setText(("▾  " if on else "▸  ") + "SÉRIOVÁ KONZOLE")
        self.console.setVisible(on)
        self.console_row.setVisible(on)

    def eventFilter(self, obj, event):
        """Šipky nahoru/dolů procházejí historii odeslaných příkazů."""
        if obj is self.edit_cmd and event.type() == QEvent.KeyPress and self._history:
            if event.key() == Qt.Key_Up:
                self._history_pos = max(0, self._history_pos - 1)
                self.edit_cmd.setText(self._history[self._history_pos])
                return True
            if event.key() == Qt.Key_Down:
                self._history_pos = min(len(self._history), self._history_pos + 1)
                self.edit_cmd.setText(
                    self._history[self._history_pos]
                    if self._history_pos < len(self._history) else "")
                return True
        return super().eventFilter(obj, event)

    # ============================================================= připojení =
    def refreshPorts(self) -> None:
        self.cmb_port.clear()
        if not available():
            self.cmb_port.addItem("pyserial není nainstalovaná")
            self.cmb_port.setEnabled(False)
            self.btn_connect.setEnabled(False)
            self.lbl_status.setText(unavailable_reason())
            return
        ports = list_serial_ports()
        for device, description in ports:
            self.cmb_port.addItem(f"{device} – {description}", device)
        if not ports:
            self.cmb_port.addItem("— žádný sériový port —")
            self.btn_connect.setEnabled(False)
            self.lbl_status.setText(
                "Nenalezen žádný sériový port. Připojte Arduino USB kabelem "
                "a stiskněte Hledat.")
            return
        self.btn_connect.setEnabled(True)
        preferred = self.settings.value("led_port") or guess_arduino_port()
        if preferred:
            index = self.cmb_port.findData(preferred)
            if index >= 0:
                self.cmb_port.setCurrentIndex(index)
        self.lbl_status.setText("Vyberte port a stiskněte Připojit.")

    def toggleConnection(self) -> None:
        if self.link.is_open():
            self.link.close()
            return
        port = self.cmb_port.currentData()
        if not port:
            return
        baud = int(self.cmb_baud.currentText())
        self.lbl_status.setText(f"Připojuji k {port}…")
        if self.link.open(port, baud):
            self.settings.setValue("led_port", port)
            self.settings.setValue("led_baud", baud)

    def _onOpened(self, port: str) -> None:
        self._setConnected(True)
        self._log(f"— port {port} otevřen, čekám na start desky —", theme.NEUTRAL_600)
        QTimer.singleShot(int(SerialLink.BOOT_DELAY * 1000), self._handshake)

    def _handshake(self) -> None:
        if self.link.is_open():
            self.link.send(LedProtocol.ping())
            self.link.send(LedProtocol.state())

    def _onClosed(self) -> None:
        self._setConnected(False)
        self._log("— port uzavřen —", theme.NEUTRAL_600)

    def _onFailed(self, message: str) -> None:
        self.lbl_status.setText(message)
        self._log(f"CHYBA: {message}", theme.ACCENT)

    def _setConnected(self, on: bool) -> None:
        if not on:
            self.seg_direction.clearSelection()
        self.btn_connect.setText("Odpojit" if on else "Připojit")
        self.tag_link.set_active(on, "Připojeno" if on else "Nepřipojeno")
        self.cmb_port.setEnabled(not on)
        self.cmb_baud.setEnabled(not on)
        self.btn_ports.setEnabled(not on)
        for widget in (self.chk_master, self.slider_master, self.spin_master,
                       self.cmb_preset, self.btn_master_color, self.btn_off,
                       self.edit_cmd, self.seg_direction, *self.panels):
            widget.setEnabled(on)
        if not on:
            self.lbl_status.setText(
                "Nepřipojeno." if available() else unavailable_reason())

    # ============================================================= nastavení =
    def workspaceSettings(self) -> dict:
        """Nastavení osvětlení pro uložení do souboru."""
        return {
            "port": self.link.port_name() if self.link.is_open() else "",
            "rotation": self.rotation,
            "master_on": self.chk_master.isChecked(),
            "master_brightness": self.spin_master.value(),
            "panels": [{"on": w.isOn(), "brightness": w.brightness(),
                        "color": list(w.color())} for w in self.panels],
        }

    def applyWorkspaceSettings(self, data: dict) -> None:
        """Obnoví nastavení ze souboru a pošle je do Arduina, když je připojené.

        Ovládací prvky se nastaví vždycky, i bez připojené desky – po
        připojení se pak dá stav odeslat tlačítkem, nic se neztratí."""
        if not isinstance(data, dict):
            return
        if "rotation" in data:
            self.setRotation(int(data["rotation"]))

        for entry, widget in zip(data.get("panels") or [], self.panels):
            if not isinstance(entry, dict):
                continue
            color = entry.get("color") or widget.color()
            widget.setState(bool(entry.get("on", True)),
                            int(entry.get("brightness", widget.brightness())),
                            tuple(int(c) for c in color)[:3])
            if self.link.is_open():
                wire = self._wire(widget.index)
                self._send(LedProtocol.panel_color(wire, widget.color()))
                self._send(LedProtocol.panel_brightness(wire, widget.brightness()))
                self._send(LedProtocol.panel_power(wire, widget.isOn()))

        if "master_brightness" in data:
            value = int(data["master_brightness"])
            for widget in (self.slider_master, self.spin_master):
                widget.blockSignals(True)
                widget.setValue(value)
                widget.blockSignals(False)
            if self.link.is_open():
                self._send(LedProtocol.all_brightness(value))
        if "master_on" in data:
            on = bool(data["master_on"])
            self.chk_master.blockSignals(True)
            self.chk_master.setChecked(on)
            self.chk_master.blockSignals(False)
            if self.link.is_open():
                self._send(LedProtocol.all_power(on))

    # ================================================================ příjem =
    def _onLine(self, line: str) -> None:
        color = theme.ACCENT if LedProtocol.is_error(line) else "#2b6cb0"
        self._log(f"« {line}", color)
        if LedProtocol.is_banner(line):
            info = LedProtocol.parse_banner(line)
            self.lbl_status.setText(
                f"{self.link.port_name()} · firmware {info.get('version', '?')} · "
                f"{info.get('panels', PANELS)} × {info.get('leds', LEDS_PER_PANEL)} LED")
            self.link.send(LedProtocol.state())
        elif LedProtocol.parse_state(line, self.state):
            self._applyStateToUi()

    def _applyStateToUi(self) -> None:
        for widget in (self.chk_master, self.slider_master, self.spin_master):
            widget.blockSignals(True)
        try:
            self.chk_master.setChecked(self.state.master_on)
            self.slider_master.setValue(self.state.master_brightness)
            self.spin_master.setValue(self.state.master_brightness)
        finally:
            for widget in (self.chk_master, self.slider_master, self.spin_master):
                widget.blockSignals(False)
        # Arduino hlásí čísla modulů, ne strany – přerovnat podle natočení.
        for wire, panel in enumerate(self.state.panels, start=1):
            widget = self.panels[leds_mod.gui_index(wire, self.rotation)]
            widget.setState(panel.on, panel.brightness, panel.color)

    # =============================================================== odeslání
    def _send(self, command: str) -> None:
        if self.link.send(command):
            self._sync_timer.start()

    def _queueBrightness(self, key, builder) -> None:
        """Posuvník generuje mnoho hodnot – odešleme až tu poslední."""
        self._pending_brightness[key] = builder
        self._send_timer.start()

    def _flushBrightness(self) -> None:
        pending, self._pending_brightness = self._pending_brightness, {}
        for builder in pending.values():
            self._send(builder())

    # ------------------------------------------------------------- hlavní ---
    def _onMasterPower(self, on: bool) -> None:
        self._send(LedProtocol.all_power(on))

    def _onMasterBrightness(self, value: int) -> None:
        self.spin_master.blockSignals(True)
        self.spin_master.setValue(value)
        self.spin_master.blockSignals(False)
        self._queueBrightness("master", lambda v=value: LedProtocol.all_brightness(v))

    def _onPreset(self, index: int) -> None:
        rgb = self.cmb_preset.itemData(index)
        if rgb:
            self._setAllColor(tuple(rgb))

    def _pickMasterColor(self) -> None:
        chosen = QColorDialog.getColor(QColor(*self.panels[0].color()), self,
                                       "Barva všech stran")
        if chosen.isValid():
            self._setAllColor((chosen.red(), chosen.green(), chosen.blue()))

    def setAllColor(self, rgb) -> None:
        """Veřejná cesta k obarvení všech stran (používá měření po kanálech)."""
        self._setAllColor(tuple(int(c) for c in rgb)[:3])

    def _setAllColor(self, rgb) -> None:
        for widget in self.panels:
            widget.setColor(rgb)
        self._send(LedProtocol.all_color(rgb))

    def _onDirection(self, index: int) -> None:
        if index >= PANELS:
            self.chk_master.setChecked(True)
            self._send(LedProtocol.all_power(True))
        else:
            self._onSolo(index + 1)

    # ------------------------------------------------------------ jednotlivé
    def _wire(self, index: int) -> int:
        """Ze strany zobrazené v aplikaci udělá číslo modulu na sběrnici."""
        return leds_mod.wire_index(index - 1, self.rotation)

    def setRotation(self, rotation: int) -> None:
        """Nastaví, o kolik stran je zřetězení modulů natočené."""
        self.rotation = int(rotation) % PANELS
        self.settings.setValue("led_rotation", self.rotation)
        if hasattr(self, "cmb_rotation"):
            index = self.cmb_rotation.findData(self.rotation)
            if index >= 0 and index != self.cmb_rotation.currentIndex():
                self.cmb_rotation.blockSignals(True)
                self.cmb_rotation.setCurrentIndex(index)
                self.cmb_rotation.blockSignals(False)

    def _onRotationChosen(self, index: int) -> None:
        self.setRotation(self.cmb_rotation.itemData(index))
        if self.link.is_open():
            self.link.send(LedProtocol.state())   # ať se stav přerovná

    def _onPanelPower(self, index: int, on: bool) -> None:
        self._send(LedProtocol.panel_power(self._wire(index), on))

    def _onPanelBrightness(self, index: int, value: int) -> None:
        wire = self._wire(index)
        self._queueBrightness(
            f"p{wire}", lambda i=wire, v=value: LedProtocol.panel_brightness(i, v))

    def _onPanelColor(self, index: int, rgb) -> None:
        self._send(LedProtocol.panel_color(self._wire(index), rgb))

    def _onSolo(self, index: int) -> None:
        self._send(LedProtocol.only(self._wire(index)))

    def _onCopyToAll(self, rgb) -> None:
        self._setAllColor(tuple(rgb))

    # ================================================================ konzole
    def _sendManual(self) -> None:
        text = self.edit_cmd.text().strip()
        if not text:
            return
        self._send(text)
        self._history.append(text)
        self._history_pos = len(self._history)
        self.edit_cmd.clear()

    def _log(self, text: str, color: str = theme.NEUTRAL_700) -> None:
        self.console.appendHtml(
            f'<span style="color:{color}">{_escape(text)}</span>')
        self.console.moveCursor(QTextCursor.End)
        self.logMessage.emit(text)

    # ================================================================ zavření
    def shutdown(self) -> None:
        if self.link.is_open():
            self.link.close()


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
