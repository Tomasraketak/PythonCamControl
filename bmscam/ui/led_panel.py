"""Panel pro řízení osvětlení – 4 moduly FC101 (8× WS2812) přes Arduino."""

from typing import List, Optional

from PyQt5.QtCore import QSettings, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QTextCursor
from PyQt5.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFrame,
                             QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QPlainTextEdit, QPushButton,
                             QSizePolicy, QSlider, QSpinBox, QToolButton,
                             QVBoxLayout, QWidget)

from ..leds import (BAUD, LEDS_PER_PANEL, PANEL_NAMES, PANEL_SHORT, PANELS,
                    PRESETS, LedProtocol, LedState, color_to_hex)
from ..serialio import (SerialLink, available, guess_arduino_port,
                        list_serial_ports, unavailable_reason)


def _swatch_style(color) -> str:
    r, g, b = color
    text = "#000000" if (r * 299 + g * 587 + b * 114) / 1000 > 140 else "#ffffff"
    return (f"background-color: rgb({r},{g},{b}); color: {text};"
            "border: 1px solid palette(mid); padding: 4px 8px;")


class PanelWidget(QGroupBox):
    """Ovládání jednoho modulu: zapnutí, jas, barva."""

    powerChanged = pyqtSignal(int, bool)
    brightnessChanged = pyqtSignal(int, int)
    colorChanged = pyqtSignal(int, tuple)
    soloRequested = pyqtSignal(int)
    copyToAllRequested = pyqtSignal(tuple)

    def __init__(self, index: int, parent=None):
        super().__init__(f"{index}. {PANEL_NAMES[index - 1]}", parent)
        self.index = index
        self._color = (255, 255, 255)
        self._updating = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 6)
        lay.setSpacing(4)

        top = QHBoxLayout()
        self.chk_on = QCheckBox("Zapnuto")
        self.chk_on.toggled.connect(
            lambda on: self._emit(self.powerChanged, self.index, on))
        top.addWidget(self.chk_on)
        top.addStretch(1)
        self.btn_solo = QToolButton()
        self.btn_solo.setText("sólo")
        self.btn_solo.setToolTip(
            f"Rozsvítit pouze tuto stranu – osvětlení {PANEL_SHORT[index - 1]}")
        self.btn_solo.setAutoRaise(True)
        self.btn_solo.clicked.connect(lambda: self.soloRequested.emit(self.index))
        top.addWidget(self.btn_solo)
        lay.addLayout(top)

        row = QHBoxLayout()
        row.addWidget(QLabel("Jas"))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 255)
        self.slider.setValue(255)
        self.slider.valueChanged.connect(self._onBrightness)
        row.addWidget(self.slider, 1)
        self.spin = QSpinBox()
        self.spin.setRange(0, 255)
        self.spin.setValue(255)
        self.spin.setKeyboardTracking(False)
        self.spin.setMaximumWidth(64)
        self.spin.valueChanged.connect(self.slider.setValue)
        row.addWidget(self.spin)
        lay.addLayout(row)

        bottom = QHBoxLayout()
        self.btn_color = QPushButton("Barva…")
        self.btn_color.clicked.connect(self._pickColor)
        bottom.addWidget(self.btn_color, 1)
        self.btn_copy = QToolButton()
        self.btn_copy.setText("→ vše")
        self.btn_copy.setToolTip("Použít tuto barvu na všechny panely")
        self.btn_copy.setAutoRaise(True)
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
        self._updating, was = True, self._updating
        self.spin.setValue(value)
        self._updating = was
        self._emit(self.brightnessChanged, self.index, value)

    def _pickColor(self) -> None:
        current = QColor(*self._color)
        chosen = QColorDialog.getColor(current, self, f"Barva panelu {self.index}")
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
        self._pending_brightness = {}
        self._history: List[str] = []
        self._history_pos = 0

        self._buildUi()

        self.link.opened.connect(self._onOpened)
        self.link.closed.connect(self._onClosed)
        self.link.failed.connect(self._onFailed)
        self.link.lineReceived.connect(self._onLine)
        self.link.lineSent.connect(lambda t: self._log(f"» {t}", "#2a7"))

        # sloučení rychlých pohybů posuvníkem do jednoho příkazu
        self._send_timer = QTimer(self)
        self._send_timer.setSingleShot(True)
        self._send_timer.setInterval(60)
        self._send_timer.timeout.connect(self._flushBrightness)

        # po každé změně si vyžádáme skutečný stav z desky
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
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
        lay.addWidget(self._buildConnectionBox())
        lay.addWidget(self._buildMasterBox())
        lay.addWidget(self._buildPanelsBox())
        lay.addWidget(self._buildConsoleBox())
        lay.addStretch(1)

    def _buildConnectionBox(self) -> QGroupBox:
        box = QGroupBox("Připojení k Arduinu")
        lay = QVBoxLayout(box)
        row = QHBoxLayout()
        self.cmb_port = QComboBox()
        self.cmb_port.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_port.setMinimumWidth(180)
        row.addWidget(self.cmb_port, 1)
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["9600", "19200", "38400", "57600", "115200", "250000"])
        self.cmb_baud.setCurrentText(str(self.settings.value("led_baud", BAUD)))
        row.addWidget(self.cmb_baud)
        self.btn_ports = QPushButton("Hledat")
        self.btn_ports.clicked.connect(self.refreshPorts)
        row.addWidget(self.btn_ports)
        self.btn_connect = QPushButton("Připojit")
        self.btn_connect.clicked.connect(self.toggleConnection)
        row.addWidget(self.btn_connect)
        lay.addLayout(row)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color: palette(mid); font-size: 11px;")
        lay.addWidget(self.lbl_status)
        return box

    def _buildMasterBox(self) -> QGroupBox:
        box = QGroupBox("Všechny panely najednou")
        lay = QVBoxLayout(box)

        row = QHBoxLayout()
        self.chk_master = QCheckBox("Osvětlení zapnuto")
        self.chk_master.toggled.connect(self._onMasterPower)
        row.addWidget(self.chk_master)
        row.addStretch(1)
        self.btn_off = QPushButton("Zhasnout vše")
        self.btn_off.clicked.connect(lambda: self.chk_master.setChecked(False))
        row.addWidget(self.btn_off)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Hlavní jas"))
        self.slider_master = QSlider(Qt.Horizontal)
        self.slider_master.setRange(0, 255)
        self.slider_master.setValue(128)
        self.slider_master.valueChanged.connect(self._onMasterBrightness)
        row.addWidget(self.slider_master, 1)
        self.spin_master = QSpinBox()
        self.spin_master.setRange(0, 255)
        self.spin_master.setValue(128)
        self.spin_master.setKeyboardTracking(False)
        self.spin_master.valueChanged.connect(self.slider_master.setValue)
        row.addWidget(self.spin_master)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Barva"))
        self.cmb_preset = QComboBox()
        for name, rgb in PRESETS:
            self.cmb_preset.addItem(name, rgb)
        self.cmb_preset.activated.connect(self._onPreset)
        row.addWidget(self.cmb_preset, 1)
        self.btn_master_color = QPushButton("Vlastní…")
        self.btn_master_color.clicked.connect(self._pickMasterColor)
        row.addWidget(self.btn_master_color)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Šikmé osvětlení"))
        self.dir_buttons = []
        for i, short in enumerate(PANEL_SHORT, start=1):
            btn = QPushButton(short)
            btn.setToolTip(f"Rozsvítit pouze stranu „{PANEL_NAMES[i - 1]}“")
            btn.clicked.connect(lambda _, n=i: self._onSolo(n))
            row.addWidget(btn)
            self.dir_buttons.append(btn)
        btn_ring = QPushButton("kruhové")
        btn_ring.setToolTip("Rozsvítit všechny čtyři strany")
        btn_ring.clicked.connect(lambda: self.chk_master.setChecked(True) or
                                 self._send(LedProtocol.all_power(True)))
        row.addWidget(btn_ring)
        lay.addLayout(row)
        return box

    def _buildPanelsBox(self) -> QGroupBox:
        """Panely rozmístěné tak, jak leží moduly kolem objektivu."""
        box = QGroupBox("Jednotlivé strany")
        grid = QGridLayout(box)
        grid.setSpacing(6)
        self.panels: List[PanelWidget] = []
        for i in range(PANELS):
            widget = PanelWidget(i + 1)
            widget.powerChanged.connect(self._onPanelPower)
            widget.brightnessChanged.connect(self._onPanelBrightness)
            widget.colorChanged.connect(self._onPanelColor)
            widget.soloRequested.connect(self._onSolo)
            widget.copyToAllRequested.connect(self._onCopyToAll)
            self.panels.append(widget)

        # 1 = horní, 2 = pravý, 3 = dolní, 4 = levý
        grid.addWidget(self.panels[0], 0, 0, 1, 3)
        grid.addWidget(self.panels[3], 1, 0)
        grid.addWidget(self._buildCenterHint(), 1, 1)
        grid.addWidget(self.panels[1], 1, 2)
        grid.addWidget(self.panels[2], 2, 0, 1, 3)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 3)
        return box

    def _buildCenterHint(self) -> QWidget:
        """Střed čtverce – místo, kde je objektiv a vzorek."""
        hint = QLabel("◎\nobjektiv")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color: palette(mid); border: 1px dashed palette(mid);"
                           "border-radius: 6px; padding: 6px;")
        hint.setToolTip("Rozmístění ovládacích prvků odpovídá poloze modulů "
                        "kolem objektivu.")
        return hint

    def _buildConsoleBox(self) -> QGroupBox:
        box = QGroupBox("Sériová konzole")
        box.setCheckable(True)
        box.setChecked(False)
        lay = QVBoxLayout(box)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(500)
        self.console.setMinimumHeight(110)
        font = QFont("Consolas" if hasattr(QFont, "Monospace") else "monospace")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        self.console.setFont(font)
        lay.addWidget(self.console)

        row = QHBoxLayout()
        self.edit_cmd = QLineEdit()
        self.edit_cmd.setPlaceholderText("Příkaz pro Arduino, např. P 1 C 255 0 0")
        self.edit_cmd.returnPressed.connect(self._sendManual)
        self.edit_cmd.installEventFilter(self)
        row.addWidget(self.edit_cmd, 1)
        btn_send = QPushButton("Odeslat")
        btn_send.clicked.connect(self._sendManual)
        row.addWidget(btn_send)
        btn_clear = QPushButton("Vyčistit")
        btn_clear.clicked.connect(self.console.clear)
        row.addWidget(btn_clear)
        lay.addLayout(row)

        # obsah se schová, dokud uživatel skupinu nezaškrtne
        for w in (self.console, self.edit_cmd, btn_send, btn_clear):
            box.toggled.connect(w.setVisible)
            w.setVisible(False)
        return box

    def eventFilter(self, obj, event):
        """Šipky nahoru/dolů procházejí historii odeslaných příkazů."""
        from PyQt5.QtCore import QEvent
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
        for device, label in ports:
            self.cmb_port.addItem(f"{device} – {label}", device)
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
            idx = self.cmb_port.findData(preferred)
            if idx >= 0:
                self.cmb_port.setCurrentIndex(idx)
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
        self._log(f"— port {port} otevřen, čekám na start desky —", "#888")
        # Arduino se po otevření portu restartuje
        QTimer.singleShot(int(SerialLink.BOOT_DELAY * 1000), self._handshake)

    def _handshake(self) -> None:
        if self.link.is_open():
            self.link.send(LedProtocol.ping())
            self.link.send(LedProtocol.state())

    def _onClosed(self) -> None:
        self._setConnected(False)
        self._log("— port uzavřen —", "#888")

    def _onFailed(self, message: str) -> None:
        self.lbl_status.setText(message)
        self._log(f"CHYBA: {message}", "#c33")

    def _setConnected(self, on: bool) -> None:
        self.btn_connect.setText("Odpojit" if on else "Připojit")
        self.cmb_port.setEnabled(not on)
        self.cmb_baud.setEnabled(not on)
        self.btn_ports.setEnabled(not on)
        for widget in (self.chk_master, self.slider_master, self.spin_master,
                       self.cmb_preset, self.btn_master_color, self.btn_off,
                       self.edit_cmd, *self.panels, *getattr(self, "dir_buttons", [])):
            widget.setEnabled(on)
        if not on:
            self.lbl_status.setText(
                "Nepřipojeno." if available() else unavailable_reason())

    # ================================================================ příjem =
    def _onLine(self, line: str) -> None:
        color = "#c33" if LedProtocol.is_error(line) else "#37c"
        self._log(f"« {line}", color)
        if LedProtocol.is_banner(line):
            info = LedProtocol.parse_banner(line)
            self.lbl_status.setText(
                f"Připojeno k {self.link.port_name()} – firmware {info.get('version', '?')}, "
                f"{info.get('panels', PANELS)} panely × {info.get('leds', LEDS_PER_PANEL)} LED")
            self.link.send(LedProtocol.state())
        elif LedProtocol.parse_state(line, self.state):
            self._applyStateToUi()

    def _applyStateToUi(self) -> None:
        self.chk_master.blockSignals(True)
        self.slider_master.blockSignals(True)
        self.spin_master.blockSignals(True)
        try:
            self.chk_master.setChecked(self.state.master_on)
            self.slider_master.setValue(self.state.master_brightness)
            self.spin_master.setValue(self.state.master_brightness)
        finally:
            self.chk_master.blockSignals(False)
            self.slider_master.blockSignals(False)
            self.spin_master.blockSignals(False)
        for i, widget in enumerate(self.panels):
            panel = self.state.panels[i]
            widget.setState(panel.on, panel.brightness, panel.color)

    # =============================================================== odeslání
    def _send(self, command: str) -> None:
        if self.link.send(command):
            self._sync_timer.start()

    def _queueBrightness(self, key, command_builder) -> None:
        """Posuvník generuje mnoho hodnot – odešleme až tu poslední."""
        self._pending_brightness[key] = command_builder
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
        current = QColor(*self.panels[0].color())
        chosen = QColorDialog.getColor(current, self, "Barva všech panelů")
        if chosen.isValid():
            self._setAllColor((chosen.red(), chosen.green(), chosen.blue()))

    def _setAllColor(self, rgb) -> None:
        for widget in self.panels:
            widget.setColor(rgb)
        self._send(LedProtocol.all_color(rgb))

    # ------------------------------------------------------------ jednotlivé
    def _onPanelPower(self, index: int, on: bool) -> None:
        self._send(LedProtocol.panel_power(index, on))

    def _onPanelBrightness(self, index: int, value: int) -> None:
        self._queueBrightness(
            f"p{index}", lambda i=index, v=value: LedProtocol.panel_brightness(i, v))

    def _onPanelColor(self, index: int, rgb) -> None:
        self._send(LedProtocol.panel_color(index, rgb))

    def _onSolo(self, index: int) -> None:
        self._send(LedProtocol.only(index))

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

    def _log(self, text: str, color: str = "#333") -> None:
        self.console.appendHtml(
            f'<span style="color:{color}">{_escape(text)}</span>')
        self.console.moveCursor(QTextCursor.End)
        self.logMessage.emit(text)

    # ================================================================ zavření
    def shutdown(self) -> None:
        if self.link.is_open():
            self.link.close()


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
