"""Hlavní okno aplikace BMS Cam Control."""

import glob
import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

from PyQt5.QtCore import QSettings, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QKeySequence
from PyQt5.QtWidgets import (QAction, QComboBox, QDialog, QDialogButtonBox,
                             QDoubleSpinBox, QFileDialog, QFormLayout,
                             QHBoxLayout, QLabel, QMainWindow, QMenu,
                             QMessageBox, QPlainTextEdit, QScrollArea,
                             QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout,
                             QWidget)

from ..backends import (EVENT_DISCONNECT, EVENT_ERROR, EVENT_IMAGE,
                        CameraBackend, CameraError, diagnostics,
                        enumerate_devices, open_device)
from ..spec import (GROUP_ORDER, GROUP_TITLES, GROUP_TOOLTIPS, KIND_ACTION,
                    KIND_READONLY, DeviceInfo, PropSpec)
from . import theme
from .controls import PropertyPanel
from .led_panel import LedPanel
from .video_view import VideoView
from .widgets import (Card, SegmentedControl, SidePanel, Tag, button, hline,
                      icon_button, label, row, vline)

APP_NAME = "BMS Cam Control"
VIDEO_FILTER = "MP4 (*.mp4);;Matroska (*.mkv);;ASF (*.asf)"


class MainWindow(QMainWindow):
    """Okno s bočními panely a živým náhledem uprostřed."""

    cameraEvent = pyqtSignal(int)        # přemostění z vlákna SDK do GUI

    def __init__(self, prefer_demo: bool = False, include_demo: bool = True):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1600, 940)

        self.settings = QSettings("BMS", "CamControl")
        self.camera: Optional[CameraBackend] = None
        self.devices: List[DeviceInfo] = []
        self.panels: Dict[str, PropertyPanel] = {}
        self.specs: Dict[str, PropSpec] = {}
        self._prefer_demo = prefer_demo
        self._include_demo = include_demo

        self._frames = 0
        self._frames_total = 0
        self._last_paint = 0.0
        self._fps = 0.0
        self._fps_since = time.time()
        self._recording_since: Optional[float] = None
        self._timelapse_count = 0

        self.save_dir = self.settings.value(
            "save_dir", os.path.join(os.path.expanduser("~"), "BMSCam"))

        self._buildActions()
        self._buildUi()
        self.cameraEvent.connect(self._onCameraEvent)

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._onUiTimer)
        self.ui_timer.start(500)

        self.timelapse_timer = QTimer(self)
        self.timelapse_timer.timeout.connect(self._onTimelapse)

        self.view.um_per_px = float(self.settings.value("um_per_px", 1.0))
        self.refreshDevices()
        self.refreshProfiles()
        self._updateEnabled()

    # ================================================================ akce ===
    def _buildActions(self) -> None:
        """Akce jsou navázané na okno, takže zkratky fungují i bez nabídky."""
        def act(text, slot, shortcut=None, checkable=False):
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.setCheckable(checkable)
            (action.toggled if checkable else action.triggered).connect(
                lambda *_: slot())
            self.addAction(action)
            return action

        self.act_connect = act("Připojit / odpojit kameru", self.toggleConnect, "F5")
        self.act_search = act("Hledat kamery", self.refreshDevices, "F6")
        self.act_snap = act("Uložit snímek", lambda: self.snapshot(), "Ctrl+S")
        self.act_record = act("Nahrávat video", self.toggleRecord, "Ctrl+R")
        self.act_wb = act("Vyvážit bílou", lambda: self.doAction("wb_once"), "Ctrl+W")
        self.act_focus = act("Zaostřit", lambda: self.doAction("af_once"), "Ctrl+F")
        self.act_reset = act("Obnovit výchozí hodnoty", self.resetDefaults)
        self.act_fit = act("Přizpůsobit oknu", self.zoomFit, "Ctrl+0")
        self.act_zoom1 = act("Skutečná velikost 1:1", self.zoomActual, "Ctrl+1")
        self.act_zoom_in = act("Přiblížit", lambda: self.view.zoomBy(1.25),
                               QKeySequence.ZoomIn)
        self.act_zoom_out = act("Oddálit", lambda: self.view.zoomBy(1 / 1.25),
                                QKeySequence.ZoomOut)
        self.act_grid = act("Mřížka třetin", self._onOverlay, "G", True)
        self.act_cross = act("Nitkový kříž", self._onOverlay, "K", True)
        self.act_scale = act("Měřítko", self._onOverlay, "M", True)
        self.act_calibrate = act("Kalibrace měřítka…", self.calibrate)
        self.act_roi = act("Výběr oblasti pro WB", self._onRoiMode, None, True)
        self.act_roi_clear = act("Zrušit výběr oblasti", self.view_clear_roi)
        self.act_leds = act("Panel osvětlení", self._toggleLedPanel, "Ctrl+L", True)
        self.act_leds.setChecked(True)
        self.act_fullscreen = act("Celá obrazovka", self._onFullscreen, "F11", True)
        self.act_profile_save = act("Uložit profil nastavení…", self.saveProfile)
        self.act_profile_load = act("Načíst profil nastavení…", self.loadProfile)
        self.act_dir = act("Složka pro ukládání…", self.chooseSaveDir)
        self.act_diag = act("Diagnostika SDK…", self.showDiagnostics)
        self.act_shortcuts = act("Klávesové zkratky…", self.showShortcuts, "F1")
        self.act_about = act("O aplikaci…", self.showAbout)
        self.act_quit = act("Konec", self.close, "Ctrl+Q")

    # ================================================================== UI ===
    def _buildUi(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._buildNav())
        outer.addWidget(hline())
        outer.addWidget(self._buildToolbar())
        outer.addWidget(hline())

        self.view = VideoView()
        self.view.zoomChanged.connect(self._onZoomChanged)
        self.view.roiSelected.connect(self._onRoiSelected)

        self.left_panel = SidePanel("Ovládání kamery", "left")
        self._fillLeftPanel()
        self.right_panel = SidePanel("Osvětlení", "right")
        self.led_panel = LedPanel()
        self.led_panel.logMessage.connect(
            lambda text: self.statusMessage(text, 3000))
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QScrollArea.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll.setWidget(self.led_panel)
        self.right_panel.add(right_scroll)
        self.right_panel.toggle_button.clicked.connect(
            lambda: self.act_leds.setChecked(not self.right_panel.is_collapsed()))

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        middle.addWidget(self.left_panel)
        middle.addWidget(self._vsep())
        middle.addWidget(self.view, 1)
        middle.addWidget(self._vsep())
        middle.addWidget(self.right_panel)
        outer.addLayout(middle, 1)

        outer.addWidget(hline())
        outer.addWidget(self._buildStatusBar())
        self.setCentralWidget(root)
        self._updateDirLabel()

    @staticmethod
    def _vsep() -> QWidget:
        sep = QWidget()
        sep.setFixedWidth(2)
        sep.setStyleSheet(f"background: {theme.DIVIDER};")
        return sep

    # ------------------------------------------------------------ horní lišta
    def _buildNav(self) -> QWidget:
        nav = QWidget()
        nav.setProperty("role", "nav")
        nav.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(nav)
        lay.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_3)

        lay.addWidget(label("BMS CAM CONTROL", "brand"))
        self.tag_camera = Tag("Nepřipojeno")
        lay.addWidget(self.tag_camera)
        lay.addStretch(1)

        menu_button = icon_button("menu", "Další akce")
        menu_button.setMenu(self._buildMenu())
        lay.addWidget(menu_button)
        lay.addWidget(icon_button("help", "Klávesové zkratky (F1)"))
        lay.itemAt(lay.count() - 1).widget().clicked.connect(self.showShortcuts)

        self.btn_connect = button("Připojit kameru", "primary", "plug")
        self.btn_connect.clicked.connect(self.toggleConnect)
        lay.addWidget(self.btn_connect)
        return nav

    def _buildMenu(self) -> QMenu:
        menu = QMenu(self)
        for action in (self.act_snap, self.act_record, self.act_dir):
            menu.addAction(action)
        menu.addSeparator()
        for action in (self.act_profile_save, self.act_profile_load):
            menu.addAction(action)
        menu.addSeparator()
        for action in (self.act_wb, self.act_focus, self.act_reset, self.act_search):
            menu.addAction(action)
        menu.addSeparator()
        for action in (self.act_calibrate, self.act_roi, self.act_roi_clear,
                       self.act_leds, self.act_fullscreen):
            menu.addAction(action)
        menu.addSeparator()
        for action in (self.act_diag, self.act_shortcuts, self.act_about,
                       self.act_quit):
            menu.addAction(action)
        return menu

    def _buildToolbar(self) -> QWidget:
        bar = QWidget()
        bar.setProperty("role", "toolbar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_2)
        lay.setSpacing(theme.SPACE_2)

        self.seg_zoom = SegmentedControl(["Fit", "1:1"])
        self.seg_zoom.setFixedWidth(120)
        self.seg_zoom.currentChanged.connect(
            lambda i: self.zoomFit() if i == 0 else self.zoomActual())
        lay.addWidget(self.seg_zoom)
        lay.addWidget(vline())

        btn_out = icon_button("minus", "Oddálit")
        btn_out.clicked.connect(lambda: self.view.zoomBy(1 / 1.25))
        lay.addWidget(btn_out)
        self.lbl_zoom = label("100 %", "value")
        self.lbl_zoom.setAlignment(Qt.AlignCenter)
        self.lbl_zoom.setFixedWidth(58)
        lay.addWidget(self.lbl_zoom)
        btn_in = icon_button("plus", "Přiblížit")
        btn_in.clicked.connect(lambda: self.view.zoomBy(1.25))
        lay.addWidget(btn_in)
        lay.addWidget(vline())

        for icon_name, action, tip in (("grid", self.act_grid, "Mřížka třetin (G)"),
                                       ("crosshair", self.act_cross, "Nitkový kříž (K)"),
                                       ("ruler", self.act_scale, "Měřítko (M)")):
            btn = icon_button(icon_name, tip, checkable=True)
            btn.toggled.connect(action.setChecked)
            action.toggled.connect(btn.setChecked)
            lay.addWidget(btn)
        lay.addStretch(1)

        self.btn_stage = icon_button("moon", "Světlé pozadí náhledu", checkable=True)
        self.btn_stage.toggled.connect(self._onStageLight)
        lay.addWidget(self.btn_stage)
        return bar

    # ------------------------------------------------------------ levý panel -
    def _fillLeftPanel(self) -> None:
        panel = self.left_panel

        profile_box = QWidget()
        profile_lay = QVBoxLayout(profile_box)
        profile_lay.setContentsMargins(0, 0, 0, 0)
        profile_lay.setSpacing(4)
        profile_lay.addWidget(label("Profil nastavení", "field"))
        self.cmb_profile = QComboBox()
        self.cmb_profile.activated.connect(self._onProfileSelected)
        btn_profile_save = icon_button("save", "Uložit současné nastavení jako profil", size=32)
        btn_profile_save.clicked.connect(self.saveProfile)
        profile_lay.addLayout(row((self.cmb_profile, 1), btn_profile_save))
        panel.add(profile_box)

        card = Card("Kamera")
        self.cmb_device = QComboBox()
        self.cmb_device.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLength)
        self.cmb_device.setMinimumContentsLength(10)
        card.add(self.cmb_device)
        self.btn_connect_side = button("Připojit", "primary", "plug")
        self.btn_connect_side.clicked.connect(self.toggleConnect)
        btn_search = button("Hledat", "secondary", "search")
        btn_search.clicked.connect(self.refreshDevices)
        card.add(row((self.btn_connect_side, 2), (btn_search, 1)))

        self.cmb_res = QComboBox()
        self.cmb_res.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLength)
        self.cmb_res.setMinimumContentsLength(10)
        self.cmb_res.currentIndexChanged.connect(self._onResolutionChanged)
        card.add(row(label("Rozlišení", "meta"), None, (self.cmb_res, 3)))
        self.cmb_codec = QComboBox()
        self.cmb_codec.currentIndexChanged.connect(self._onCodecChanged)
        card.add(row(label("Kodek", "meta"), None, (self.cmb_codec, 3)))
        self.lbl_info = label("–", "meta")
        self.lbl_info.setWordWrap(True)
        card.add(self.lbl_info)
        panel.add(card)

        self.seg_tabs = SegmentedControl([GROUP_TITLES[g] for g in GROUP_ORDER],
                                         compact=True)
        self.seg_tabs.currentChanged.connect(lambda i: self.tabs.setCurrentIndex(i))
        panel.add(self.seg_tabs)

        self.tabs = QStackedWidget()
        self.tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        panel.add(self.tabs)
        panel.add(hline())

        capture = Card("Snímání")
        self.btn_snap = button("Uložit snímek", "primary", "camera")
        self.btn_snap.clicked.connect(lambda: self.snapshot())
        self.btn_record = button("Nahrát video", "secondary", "video")
        self.btn_record.clicked.connect(self.toggleRecord)
        capture.add(row((self.btn_snap, 1), (self.btn_record, 1)))

        self.btn_timelapse = button("Časosběr", "secondary", "timer")
        self.btn_timelapse.setCheckable(True)
        self.btn_timelapse.toggled.connect(self.toggleTimelapse)
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(1, 3600)
        self.spin_interval.setValue(int(self.settings.value("timelapse_interval", 10)))
        self.spin_interval.setFixedWidth(62)
        self.spin_interval.setAlignment(Qt.AlignCenter)
        capture.add(row((self.btn_timelapse, 1), self.spin_interval,
                        label("s / snímek", "meta")))

        self.lbl_dir = label("", "meta")
        self.lbl_dir.setWordWrap(True)
        capture.add(self.lbl_dir)
        btn_dir = button("Změnit složku pro ukládání…", "ghost", "folder")
        btn_dir.clicked.connect(self.chooseSaveDir)
        capture.add(btn_dir)
        panel.add(capture)
        self._updateDirLabel()

    # ----------------------------------------------------------- stavový řádek
    def _buildStatusBar(self) -> QWidget:
        bar = QWidget()
        bar.setProperty("role", "statusbar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SPACE_4, 6, theme.SPACE_4, 6)
        lay.setSpacing(theme.SPACE_3)

        self.tag_status = Tag("Nepřipojeno")
        self.lbl_res = label("–", "meta")
        self.lbl_fps = label("0,0 fps", "meta")
        self.lbl_frames = label("0 snímků", "meta")
        self.lbl_message = label("", "meta")
        self.lbl_savedir = label("", "meta")

        lay.addWidget(self.tag_status)
        for widget in (self.lbl_res, self.lbl_fps, self.lbl_frames):
            lay.addWidget(vline(14))
            lay.addWidget(widget)
        lay.addWidget(vline(14))
        lay.addWidget(self.lbl_message)
        lay.addStretch(1)
        lay.addWidget(self.lbl_savedir)
        return bar

    def statusMessage(self, text: str, msec: int = 4000) -> None:
        self.lbl_message.setText(text)
        QTimer.singleShot(msec, lambda: self.lbl_message.setText("")
                          if self.lbl_message.text() == text else None)

    # ============================================================ zařízení ===
    def refreshDevices(self) -> None:
        self.devices = enumerate_devices(include_demo=self._include_demo)
        self.cmb_device.clear()
        for dev in self.devices:
            self.cmb_device.addItem(str(dev))
        if not self.devices:
            self.cmb_device.addItem("— žádná kamera nenalezena —")
        elif self._prefer_demo:
            index = next((i for i, d in enumerate(self.devices)
                          if d.backend == "demo"), 0)
            self.cmb_device.setCurrentIndex(index)
        for btn in (self.btn_connect, self.btn_connect_side):
            btn.setEnabled(bool(self.devices))

    def toggleConnect(self) -> None:
        if self.camera is not None:
            self.disconnectCamera()
        else:
            self.connectCamera()

    def connectCamera(self) -> None:
        if not self.devices:
            self.refreshDevices()
        index = max(self.cmb_device.currentIndex(), 0)
        if index >= len(self.devices):
            QMessageBox.warning(self, APP_NAME, "Není vybrána žádná kamera.")
            return
        try:
            self.camera = open_device(self.devices[index])
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME,
                                 f"Kameru se nepodařilo otevřít:\n\n{exc}")
            self.camera = None
            return

        self.specs = dict(self.camera.props())
        self._buildPanels()
        self._fillResolutions()
        self._loadValues()
        self._showInfo()
        try:
            self.camera.start(self._sdkCallback)
        except CameraError as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))
            self.disconnectCamera()
            return
        self._frames = self._frames_total = 0
        name = self.devices[index].name
        for btn, text in ((self.btn_connect, "Odpojit kameru"),
                          (self.btn_connect_side, "Odpojit")):
            btn.setText(text)
        self.tag_camera.set_active(True, "Připojeno")
        self.tag_status.set_active(True, name)
        self._updateEnabled()

    def disconnectCamera(self) -> None:
        if self.btn_timelapse.isChecked():
            self.btn_timelapse.setChecked(False)
        if self.camera is not None:
            try:
                self.camera.close()
            except Exception:
                pass
            self.camera = None
        self._recording_since = None
        self.view.clear()
        self.view.set_stats({})
        self.view.set_recording(None)
        while self.tabs.count():
            widget = self.tabs.widget(0)
            self.tabs.removeWidget(widget)
            widget.deleteLater()
        self.panels.clear()
        self.specs.clear()
        self.cmb_res.clear()
        self.cmb_codec.clear()
        for btn, text in ((self.btn_connect, "Připojit kameru"),
                          (self.btn_connect_side, "Připojit")):
            btn.setText(text)
        self.tag_camera.set_active(False, "Nepřipojeno")
        self.tag_status.set_active(False, "Nepřipojeno")
        self.lbl_res.setText("–")
        self.lbl_info.setText("–")
        self._updateEnabled()

    # ------------------------------------------------------------- panely ---
    def _buildPanels(self) -> None:
        while self.tabs.count():
            widget = self.tabs.widget(0)
            self.tabs.removeWidget(widget)
            widget.deleteLater()
        self.panels.clear()
        for position, group in enumerate(GROUP_ORDER):
            specs = [s for s in self.specs.values()
                     if s.group == group and not s.hidden]
            specs.sort(key=lambda s: (s.kind == KIND_ACTION, s.kind == KIND_READONLY))
            panel = PropertyPanel(specs)
            panel.valueChanged.connect(self._onPropChanged)
            panel.actionTriggered.connect(self.doAction)
            self.panels[group] = panel
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setWidget(panel)
            self.tabs.addWidget(scroll)
            self.seg_tabs.buttons[position].setEnabled(bool(specs))
            self.seg_tabs.buttons[position].setToolTip(GROUP_TOOLTIPS[group])
        self.seg_tabs.setCurrentIndex(0)
        self.tabs.setCurrentIndex(0)

    def _fillResolutions(self) -> None:
        self.cmb_res.blockSignals(True)
        self.cmb_res.clear()
        for width, height in self.camera.resolutions():
            self.cmb_res.addItem(f"{width} × {height} · {width * height / 1e6:.1f} Mpx")
        try:
            self.cmb_res.setCurrentIndex(self.camera.get_resolution())
        except Exception:
            pass
        self.cmb_res.blockSignals(False)
        self.cmb_res.setEnabled(self.cmb_res.count() > 1)

        self.cmb_codec.blockSignals(True)
        self.cmb_codec.clear()
        codecs = self.camera.codecs()
        self.cmb_codec.addItems(codecs or ["–"])
        if codecs:
            try:
                self.cmb_codec.setCurrentIndex(self.camera.get_codec())
            except Exception:
                pass
        self.cmb_codec.blockSignals(False)
        self.cmb_codec.setEnabled(len(codecs) > 1)

    def _loadValues(self) -> None:
        values: Dict[str, int] = {}
        for key, spec in self.specs.items():
            if spec.kind == KIND_ACTION or spec.write_only:
                continue
            try:
                values[key] = self.camera.get(key)
            except Exception:
                values[key] = spec.default
        for panel in self.panels.values():
            panel.setValues(values)
        self._applyDependencies(values)
        self._updateStats(values)

    def _applyDependencies(self, values: Dict[str, int]) -> None:
        auto_expo = bool(values.get("aexpo", 0))
        for key in ("expotime", "again"):
            self._setRowEnabled(key, not auto_expo)
        wbmode = values.get("wbmode")
        manual_wb = wbmode is None or wbmode == 0
        for key in ("wbred", "wbgreen", "wbblue", "temp", "tint"):
            self._setRowEnabled(key, manual_wb)
        afmode = values.get("afmode")
        for key in ("afposition", "afposition_abs"):
            self._setRowEnabled(key, afmode in (None, 0))

    def _setRowEnabled(self, key: str, on: bool) -> None:
        for panel in self.panels.values():
            if key in panel.keys():
                panel.setRowEnabled(key, on)

    def _updateStats(self, values: Dict[str, int]) -> None:
        """Údaje do proužku přes obraz."""
        stats = {}
        if "expotime" in values and "expotime" in self.specs:
            stats["EXP"] = self.specs["expotime"].format(values["expotime"])
        if "again" in values and "again" in self.specs:
            stats["GAIN"] = self.specs["again"].format(values["again"])
        if "temp" in values:
            stats["WB"] = f"{values['temp']} K"
        self.view.set_stats(stats)

    def _showInfo(self) -> None:
        """Krátký řádek s údaji o kameře – bez opakování jejího názvu."""
        info = dict(self.camera.info()) if self.camera else {}
        info.pop("Kamera", None)
        self.lbl_info.setText(" · ".join(f"{k} {v}" for k, v in info.items()) or "–")

    # ============================================================== stream ===
    def _sdkCallback(self, event: int) -> None:
        self.cameraEvent.emit(event)

    def _onCameraEvent(self, event: int) -> None:
        if self.camera is None:
            return
        if event & EVENT_IMAGE:
            self._onImage()
        if event & EVENT_DISCONNECT:
            self.disconnectCamera()
            QMessageBox.warning(self, APP_NAME, "Kamera byla odpojena.")
        elif event & EVENT_ERROR:
            self.disconnectCamera()
            QMessageBox.warning(self, APP_NAME, "Došlo k chybě při přenosu obrazu.")

    def _onImage(self) -> None:
        frame = self.camera.pull()
        if frame is None:
            return
        self._frames += 1
        self._frames_total += 1
        now = time.time()
        if now - self._last_paint < 0.03:      # náhled max ~33 fps
            return
        self._last_paint = now
        self.view.setImage(self._toQImage(frame))

    def _toQImage(self, frame) -> QImage:
        order = getattr(self.camera, "pixel_order", "rgb")
        fmt = QImage.Format_RGB888
        if order == "bgr":
            fmt = getattr(QImage, "Format_BGR888", QImage.Format_RGB888)
        image = QImage(frame.data, frame.width, frame.height, frame.stride, fmt)
        if fmt == QImage.Format_RGB888 and order == "bgr":
            image = image.rgbSwapped()         # starší Qt bez Format_BGR888
        return image

    # ============================================================ vlastnosti =
    def _onPropChanged(self, key: str, value: int) -> None:
        if self.camera is None:
            return
        try:
            self.camera.set(key, value)
        except CameraError as exc:
            self.statusMessage(f"{key}: {exc}")
            return
        if key in ("aexpo", "wbmode", "afmode"):
            QTimer.singleShot(50, self._loadValues)

    def doAction(self, key: str) -> None:
        if self.camera is None or key not in self.specs:
            return
        try:
            self.camera.action(key)
        except CameraError as exc:
            self.statusMessage(str(exc))
            return
        self.statusMessage(f"{self.specs[key].label} – provedeno", 2500)
        QTimer.singleShot(300, self._loadValues)

    def resetDefaults(self) -> None:
        if self.camera is None:
            return
        if QMessageBox.question(self, APP_NAME,
                                "Obnovit všechny výchozí hodnoty kamery?"
                                ) != QMessageBox.Yes:
            return
        for key, spec in self.specs.items():
            if spec.kind in (KIND_ACTION, KIND_READONLY):
                continue
            try:
                self.camera.set(key, spec.default)
            except Exception:
                pass
        self._loadValues()

    def _onResolutionChanged(self, index: int) -> None:
        if self.camera is None or index < 0:
            return
        was_running = self.camera.is_running()
        try:
            if was_running:
                self.camera.stop()
            self.camera.set_resolution(index)
            if was_running:
                self.camera.start(self._sdkCallback)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME,
                                f"Rozlišení se nepodařilo změnit:\n{exc}")
            return
        self.view.clear()
        self.statusMessage("Rozlišení změněno", 2000)

    def _onCodecChanged(self, index: int) -> None:
        if self.camera is None or index < 0 or not self.camera.codecs():
            return
        was_running = self.camera.is_running()
        try:
            if was_running:
                self.camera.stop()
            self.camera.set_codec(index)
            if was_running:
                self.camera.start(self._sdkCallback)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Kodek se nepodařilo změnit:\n{exc}")

    # ============================================================== snímání ==
    def _ensureDir(self) -> str:
        os.makedirs(self.save_dir, exist_ok=True)
        return self.save_dir

    @staticmethod
    def _stamp() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def snapshot(self, silent: bool = False) -> Optional[str]:
        if not self.view.hasImage():
            if not silent:
                QMessageBox.information(self, APP_NAME, "Není k dispozici žádný obraz.")
            return None
        image = self.view.image().copy()
        path = os.path.join(self._ensureDir(), f"snimek_{self._stamp()}.jpg")
        if image.save(path, quality=95):
            self.statusMessage(f"Uloženo: {os.path.basename(path)}")
            return path
        if not silent:
            QMessageBox.warning(self, APP_NAME, f"Snímek se nepodařilo uložit:\n{path}")
        return None

    def toggleRecord(self) -> None:
        if self.camera is None:
            return
        if self._recording_since is not None:
            try:
                self.camera.record_stop()
            except Exception as exc:
                QMessageBox.warning(self, APP_NAME, str(exc))
            self._recording_since = None
            self.btn_record.setText("Nahrát video")
            self.view.set_recording(None)
            self.statusMessage("Nahrávání ukončeno", 3000)
            return
        if not self.camera.supports_record:
            QMessageBox.information(
                self, APP_NAME,
                "Toto SDK neumí nahrávat video přímo.\n"
                "Použijte funkci Časosběr nebo nahrávejte přes HDMI výstup.")
            return
        path = os.path.join(self._ensureDir(), f"video_{self._stamp()}.mp4")
        path, _ = QFileDialog.getSaveFileName(self, "Nahrát video do souboru",
                                              path, VIDEO_FILTER)
        if not path:
            return
        try:
            self.camera.record_start(path)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME,
                                f"Nahrávání se nepodařilo spustit:\n{exc}")
            return
        self._recording_since = time.time()
        self.btn_record.setText("Zastavit nahrávání")

    def toggleTimelapse(self, on: bool) -> None:
        if on:
            self.settings.setValue("timelapse_interval", self.spin_interval.value())
            self._timelapse_count = 0
            self.timelapse_timer.start(self.spin_interval.value() * 1000)
            self.btn_timelapse.setText("Zastavit časosběr")
        else:
            self.timelapse_timer.stop()
            self.btn_timelapse.setText("Časosběr")

    def _onTimelapse(self) -> None:
        if self.snapshot(silent=True):
            self._timelapse_count += 1
            self.statusMessage(f"Časosběr: uloženo {self._timelapse_count} snímků", 3000)

    def chooseSaveDir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Složka pro ukládání",
                                                self.save_dir)
        if path:
            self.save_dir = path
            self.settings.setValue("save_dir", path)
            self._updateDirLabel()
            self.refreshProfiles()

    def _updateDirLabel(self) -> None:
        text = f"Ukládat do: {self.save_dir}"
        self.lbl_dir.setText(text)
        if hasattr(self, "lbl_savedir"):     # stavový řádek vzniká později
            self.lbl_savedir.setText(text)

    # ============================================================== profily ==
    def refreshProfiles(self) -> None:
        """Naplní nabídku profilů podle souborů *.json ve složce pro ukládání."""
        self.cmb_profile.blockSignals(True)
        self.cmb_profile.clear()
        self.cmb_profile.addItem("Výchozí", "")
        for path in sorted(glob.glob(os.path.join(self.save_dir, "*.json"))):
            self.cmb_profile.addItem(os.path.splitext(os.path.basename(path))[0], path)
        self.cmb_profile.blockSignals(False)

    def _onProfileSelected(self, index: int) -> None:
        path = self.cmb_profile.itemData(index)
        if path:
            self.applyProfile(path)
        elif self.camera is not None:
            self.resetDefaults()

    def saveProfile(self) -> None:
        if self.camera is None:
            self.statusMessage("Profil lze uložit až po připojení kamery.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Uložit profil nastavení",
            os.path.join(self._ensureDir(), "profil.json"), "JSON (*.json)")
        if not path:
            return
        data = {"backend": self.camera.name, "values": {}}
        for key, spec in self.specs.items():
            if spec.kind in (KIND_ACTION, KIND_READONLY) or spec.write_only or spec.hidden:
                continue
            try:
                data["values"][key] = self.camera.get(key)
            except Exception:
                pass
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self.refreshProfiles()
        self.statusMessage(f"Profil uložen: {os.path.basename(path)}")

    def loadProfile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Načíst profil nastavení",
                                              self.save_dir, "JSON (*.json)")
        if path:
            self.applyProfile(path)

    def applyProfile(self, path: str) -> None:
        if self.camera is None:
            self.statusMessage("Profil lze použít až po připojení kamery.")
            return
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        skipped = []
        for key, value in (data.get("values") or {}).items():
            if key not in self.specs:
                skipped.append(key)
                continue
            try:
                self.camera.set(key, int(value))
            except Exception:
                skipped.append(key)
        self._loadValues()
        message = "Profil „{}“ načten.".format(os.path.basename(path))
        if skipped:
            message += f" Nepoužito: {', '.join(sorted(skipped))}"
        self.statusMessage(message, 5000)

    # ============================================================ zobrazení ==
    def zoomFit(self) -> None:
        self.view.fitToWindow()
        self.seg_zoom.setCurrentIndex(0)

    def zoomActual(self) -> None:
        self.view.setZoom(1.0)
        self.seg_zoom.setCurrentIndex(1)

    def _onOverlay(self) -> None:
        self.view.show_grid = self.act_grid.isChecked()
        self.view.show_cross = self.act_cross.isChecked()
        self.view.show_scale = self.act_scale.isChecked()
        self.view.update()

    def _onStageLight(self, light: bool) -> None:
        self.view.set_light_stage(light)
        from .widgets import set_icon
        set_icon(self.btn_stage, "sun" if light else "moon")
        self.btn_stage.setToolTip("Tmavé pozadí náhledu" if light
                                  else "Světlé pozadí náhledu")

    def _onRoiMode(self) -> None:
        self.view.roi_mode = self.act_roi.isChecked()
        if self.view.roi_mode:
            self.statusMessage("Tažením myši vyberte oblast pro vyvážení bílé.", 5000)

    def view_clear_roi(self) -> None:
        self.view.clearRoi()

    def _onRoiSelected(self, rect) -> None:
        if self.camera is None:
            return
        mapping = (("wbroileft", rect.x()), ("wbroitop", rect.y()),
                   ("wbroiwidth", rect.width()), ("wbroiheight", rect.height()))
        applied = False
        for key, value in mapping:
            try:
                self.camera.set(key, value)
                applied = True
            except Exception:
                pass
        if applied:
            try:
                self.camera.set("wbmode", 2)
            except Exception:
                pass
            self._loadValues()
            self.statusMessage("Oblast pro vyvážení bílé nastavena.")
        else:
            self.statusMessage("Kamera nepodporuje vyvážení bílé podle oblasti.")

    def _onZoomChanged(self, scale: float) -> None:
        self.lbl_zoom.setText(f"{scale * 100:.0f} %")

    def _toggleLedPanel(self) -> None:
        panel = getattr(self, "right_panel", None)     # může se volat před sestavením
        if panel is not None:
            panel.set_collapsed(not self.act_leds.isChecked())

    def _onFullscreen(self) -> None:
        if self.act_fullscreen.isChecked():
            self.showFullScreen()
        else:
            self.showNormal()

    def calibrate(self) -> None:
        dialog = CalibrationDialog(self.view.um_per_px, self)
        if dialog.exec_() == QDialog.Accepted:
            self.view.um_per_px = dialog.value()
            self.settings.setValue("um_per_px", self.view.um_per_px)
            self.act_scale.setChecked(True)
            self._onOverlay()

    # ================================================================ časovač
    def _onUiTimer(self) -> None:
        now = time.time()
        elapsed = max(now - self._fps_since, 0.001)
        self._fps_since = now
        self._fps = self._frames / elapsed
        self._frames = 0
        self.lbl_fps.setText(f"{self._fps:.1f} fps".replace(".", ","))
        self.lbl_frames.setText(f"{self._frames_total} snímků")
        if self._recording_since is not None:
            self.view.set_recording(int(now - self._recording_since))
        if self.camera is None:
            return
        if self.view.hasImage():
            image = self.view.image()
            self.lbl_res.setText(f"{image.width()} × {image.height()}")
        self._refreshLive()

    def _refreshLive(self) -> None:
        values = {}
        for key, spec in self.specs.items():
            if not spec.live or spec.write_only:
                continue
            if key in ("expotime", "again") and not self._isAuto("aexpo"):
                continue
            if key in ("wbred", "wbgreen", "wbblue", "temp", "tint") \
                    and self._isManual("wbmode"):
                continue
            try:
                values[key] = self.camera.get(key)
            except Exception:
                continue
        for panel in self.panels.values():
            panel.setValues(values)
        if values:
            merged = dict(values)
            for key in ("expotime", "again", "temp"):
                if key not in merged and key in self.specs:
                    row_widget = self._findRow(key)
                    if row_widget is not None:
                        merged[key] = row_widget.value()
            self._updateStats(merged)

    def _isAuto(self, key: str) -> bool:
        row_widget = self._findRow(key)
        return bool(row_widget.value()) if row_widget else False

    def _isManual(self, key: str) -> bool:
        row_widget = self._findRow(key)
        return row_widget.value() == 0 if row_widget else True

    def _findRow(self, key: str):
        for panel in self.panels.values():
            if key in panel.rows:
                return panel.rows[key]
        return None

    def _updateEnabled(self) -> None:
        on = self.camera is not None
        for widget in (self.btn_snap, self.btn_record, self.btn_timelapse,
                       self.spin_interval, self.seg_tabs, self.tabs):
            widget.setEnabled(on)
        if on and not self.camera.supports_record:
            self.btn_record.setToolTip("Toto SDK neumí nahrávat video – použijte Časosběr.")
        else:
            self.btn_record.setToolTip("")

    # ============================================================== dialogy ==
    def showDiagnostics(self) -> None:
        text = "\n".join(diagnostics())
        text += ("\n\nPozn.: uvcham.dll funguje jen ve Windows. "
                 "Pro Linux vložte libtoupcam.so do bmscam/lib/<x64|x86>/ "
                 "nebo nastavte proměnnou BMSCAM_TOUPCAM_LIB.")
        dialog = QDialog(self)
        dialog.setWindowTitle("Diagnostika SDK")
        dialog.resize(760, 340)
        lay = QVBoxLayout(dialog)
        edit = QPlainTextEdit(text)
        edit.setReadOnly(True)
        lay.addWidget(edit)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(dialog.reject)
        lay.addWidget(box)
        dialog.exec_()

    def showShortcuts(self) -> None:
        ShortcutDialog(self).exec_()

    def showAbout(self) -> None:
        from .. import __version__
        QMessageBox.about(self, "O aplikaci", ABOUT_TEXT.format(version=__version__))

    # ================================================================ zavření
    def closeEvent(self, event) -> None:
        self.timelapse_timer.stop()
        self.ui_timer.stop()
        self.led_panel.shutdown()
        self.disconnectCamera()
        super().closeEvent(event)


class CalibrationDialog(QDialog):
    """Zadání měřítka v mikrometrech na pixel."""

    def __init__(self, current: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kalibrace měřítka")
        lay = QVBoxLayout(self)
        lay.setSpacing(theme.SPACE_3)
        lay.addWidget(label(
            "Zadejte, kolik mikrometrů odpovídá jednomu pixelu obrazu.\n"
            "Hodnotu zjistíte snímkem objektového mikrometru.", "field"))
        form = QFormLayout()
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(4)
        self.spin.setRange(0.0001, 10000.0)
        self.spin.setValue(current)
        self.spin.setSuffix(" µm/px")
        form.addRow("Měřítko:", self.spin)
        lay.addLayout(form)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def value(self) -> float:
        return self.spin.value()


class ShortcutDialog(QDialog):
    """Přehled klávesových zkratek v podobě podle návrhu."""

    SHORTCUTS = [
        ("Připojit / odpojit kameru", "F5"),
        ("Znovu vyhledat kamery", "F6"),
        ("Uložit snímek", "Ctrl+S"),
        ("Spustit / zastavit nahrávání", "Ctrl+R"),
        ("Vyvážení bílé", "Ctrl+W"),
        ("Zaostřit", "Ctrl+F"),
        ("Přizpůsobit oknu", "Ctrl+0"),
        ("Skutečná velikost 1:1", "Ctrl+1"),
        ("Přiblížit / oddálit", "Ctrl + / Ctrl −"),
        ("Mřížka / kříž / měřítko", "G / K / M"),
        ("Panel osvětlení", "Ctrl+L"),
        ("Celá obrazovka", "F11"),
        ("Ukončit", "Ctrl+Q"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Klávesové zkratky")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SPACE_6, theme.SPACE_4, theme.SPACE_6, theme.SPACE_4)
        lay.setSpacing(0)
        title = label("Klávesové zkratky", "brand")
        lay.addWidget(title)
        lay.addSpacing(theme.SPACE_3)
        for text, keys in self.SHORTCUTS:
            line = QWidget()
            line_lay = QHBoxLayout(line)
            line_lay.setContentsMargins(0, 7, 0, 7)
            line_lay.addWidget(QLabel(text))
            line_lay.addStretch(1)
            key_label = QLabel(keys)
            key_label.setStyleSheet(
                f"background:{theme.SURFACE}; border:1px solid {theme.DIVIDER};"
                "padding:2px 8px; font-weight:800; font-size:12px;")
            line_lay.addWidget(key_label)
            lay.addWidget(line)
            separator = QWidget()
            separator.setFixedHeight(1)
            separator.setStyleSheet(f"background:{theme.NEUTRAL_300};")
            lay.addWidget(separator)
        lay.addSpacing(theme.SPACE_3)
        lay.addWidget(label("Myš: kolečko = zoom, tažení = posun, "
                            "dvojklik = přizpůsobit oknu", "meta"))
        lay.addSpacing(theme.SPACE_3)
        close = button("Zavřít", "primary")
        close.clicked.connect(self.accept)
        lay.addLayout(row(None, close))


ABOUT_TEXT = """\
<b>BMS Cam Control {version}</b><br><br>
Ovládání mikroskopové kamery BMS Microscopes RJ45 8MP 4K UHD Multioutput HDMI.<br><br>
Postaveno nad SDK <i>uvcham</i> (Windows, uvcham.dll) a nad nativním
SDK <i>ToupTek</i> (libtoupcam). Osvětlení WS2812 se ovládá přes Arduino.
Bez připojeného hardwaru lze aplikaci vyzkoušet v simulovaném režimu.
"""
