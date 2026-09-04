"""Hlavní okno aplikace BMS Cam Control."""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

from PyQt5.QtCore import QSettings, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QImage, QKeySequence, QPixmap
from PyQt5.QtWidgets import (QAction, QActionGroup, QApplication, QComboBox,
                             QDockWidget,
                             QDialog, QDialogButtonBox, QDoubleSpinBox,
                             QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                             QLabel, QMainWindow, QMessageBox, QPlainTextEdit,
                             QPushButton, QScrollArea, QSpinBox, QSplitter,
                             QStatusBar, QTabWidget, QToolBar, QVBoxLayout,
                             QWidget)

from ..backends import (EVENT_DISCONNECT, EVENT_ERROR, EVENT_IMAGE,
                        CameraBackend, CameraError, diagnostics,
                        enumerate_devices, open_device)
from ..spec import (GROUP_ORDER, GROUP_TITLES, GROUP_TOOLTIPS, KIND_ACTION,
                    KIND_READONLY, DeviceInfo, PropSpec)
from .controls import PropertyPanel
from .led_panel import LedPanel
from .video_view import VideoView

APP_NAME = "BMS Cam Control"
IMAGE_FILTER = "JPEG (*.jpg);;PNG (*.png);;TIFF (*.tif);;BMP (*.bmp)"
VIDEO_FILTER = "MP4 (*.mp4);;Matroska (*.mkv);;ASF (*.asf)"


class MainWindow(QMainWindow):
    """Okno s živým náhledem vlevo ovládacími panely."""

    cameraEvent = pyqtSignal(int)        # přemostění z vlákna SDK do GUI

    def __init__(self, prefer_demo: bool = False, include_demo: bool = True):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 880)

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
        self._recording_since: Optional[float] = None
        self._timelapse_count = 0
        self._snap_count = 0

        self.save_dir = self.settings.value(
            "save_dir", os.path.join(os.path.expanduser("~"), "BMSCam"))

        self._buildUi()
        self._buildActions()
        self.cameraEvent.connect(self._onCameraEvent)

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._onUiTimer)
        self.ui_timer.start(500)

        self.timelapse_timer = QTimer(self)
        self.timelapse_timer.timeout.connect(self._onTimelapse)

        self.refreshDevices()
        self._updateEnabled()
        geometry = self.settings.value("window_state")
        if geometry is not None:
            self.restoreState(geometry)

    # ================================================================= UI ====
    def _buildUi(self) -> None:
        self.view = VideoView()
        self.view.zoomChanged.connect(self._onZoomChanged)
        self.view.roiSelected.connect(self._onRoiSelected)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.tabBar().setExpanding(False)

        self.side = QWidget()
        self.side.setMinimumWidth(400)
        side_lay = QVBoxLayout(self.side)
        side_lay.setContentsMargins(6, 6, 6, 6)
        side_lay.addWidget(self._buildDeviceBox())
        side_lay.addWidget(self.tabs, 1)
        side_lay.addWidget(self._buildCaptureBox())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.side)
        splitter.addWidget(self.view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 980])
        self.setCentralWidget(splitter)

        self.led_dock = QDockWidget("Osvětlení (Arduino)", self)
        self.led_dock.setObjectName("ledDock")
        self.led_dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        self.led_panel = LedPanel()
        scroll_led = QScrollArea()
        scroll_led.setWidgetResizable(True)
        scroll_led.setFrameShape(QScrollArea.NoFrame)
        scroll_led.setWidget(self.led_panel)
        scroll_led.setMinimumWidth(430)
        self.led_dock.setWidget(scroll_led)
        self.addDockWidget(Qt.RightDockWidgetArea, self.led_dock)
        QTimer.singleShot(0, lambda: self.resizeDocks(
            [self.led_dock], [450], Qt.Horizontal))
        self.led_panel.logMessage.connect(
            lambda text: self.status.showMessage(text, 3000))

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.lbl_state = QLabel("Nepřipojeno")
        self.status.setStyleSheet("QStatusBar::item { border: 0; }"
                                  "QStatusBar QLabel { padding: 0 10px;"
                                  " border-left: 1px solid palette(mid); }")
        self.lbl_res = QLabel("–")
        self.lbl_fps = QLabel("0,0 fps")
        self.lbl_frames = QLabel("0 snímků")
        self.lbl_rec = QLabel("")
        for w in (self.lbl_state, self.lbl_res, self.lbl_fps, self.lbl_frames, self.lbl_rec):
            self.status.addPermanentWidget(w)

    def _buildDeviceBox(self) -> QGroupBox:
        box = QGroupBox("Kamera")
        lay = QVBoxLayout(box)
        self.cmb_device = QComboBox()
        self.cmb_device.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        lay.addWidget(self.cmb_device)

        row = QHBoxLayout()
        self.btn_connect = QPushButton("Připojit")
        self.btn_connect.clicked.connect(self.toggleConnect)
        self.btn_refresh = QPushButton("Hledat")
        self.btn_refresh.clicked.connect(self.refreshDevices)
        row.addWidget(self.btn_connect, 2)
        row.addWidget(self.btn_refresh, 1)
        lay.addLayout(row)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.cmb_res = QComboBox()
        self.cmb_res.currentIndexChanged.connect(self._onResolutionChanged)
        form.addRow("Rozlišení:", self.cmb_res)
        self.cmb_codec = QComboBox()
        self.cmb_codec.currentIndexChanged.connect(self._onCodecChanged)
        form.addRow("Kodek:", self.cmb_codec)
        lay.addLayout(form)

        self.lbl_info = QLabel("–")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet("color: palette(mid); font-size: 11px;")
        lay.addWidget(self.lbl_info)
        return box

    def _buildCaptureBox(self) -> QGroupBox:
        box = QGroupBox("Snímání")
        lay = QVBoxLayout(box)

        row = QHBoxLayout()
        self.btn_snap = QPushButton("Uložit snímek")
        self.btn_snap.clicked.connect(lambda: self.snapshot())
        self.btn_record = QPushButton("Nahrát video")
        self.btn_record.clicked.connect(self.toggleRecord)
        row.addWidget(self.btn_snap)
        row.addWidget(self.btn_record)
        lay.addLayout(row)

        tl = QHBoxLayout()
        self.btn_timelapse = QPushButton("Časosběr")
        self.btn_timelapse.setCheckable(True)
        self.btn_timelapse.toggled.connect(self.toggleTimelapse)
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(1, 3600)
        self.spin_interval.setValue(int(self.settings.value("timelapse_interval", 10)))
        self.spin_interval.setSuffix(" s")
        self.spin_interval.setToolTip("Interval mezi automaticky ukládanými snímky")
        tl.addWidget(self.btn_timelapse)
        tl.addWidget(self.spin_interval)
        lay.addLayout(tl)

        self.lbl_dir = QLabel()
        self.lbl_dir.setWordWrap(True)
        self.lbl_dir.setStyleSheet("color: palette(mid); font-size: 11px;")
        btn_dir = QPushButton("Změnit složku pro ukládání…")
        btn_dir.clicked.connect(self.chooseSaveDir)
        lay.addWidget(self.lbl_dir)
        lay.addWidget(btn_dir)
        self._updateDirLabel()
        return box

    # -------------------------------------------------------------- akce ----
    def _buildActions(self) -> None:
        bar = self.menuBar()

        m_file = bar.addMenu("&Soubor")
        self._addAction(m_file, "Uložit &snímek", self.snapshot, "Ctrl+S")
        self._addAction(m_file, "Nahrávat &video", self.toggleRecord, "Ctrl+R")
        self._addAction(m_file, "Složka pro &ukládání…", self.chooseSaveDir)
        m_file.addSeparator()
        self._addAction(m_file, "Uložit &profil nastavení…", self.saveProfile)
        self._addAction(m_file, "&Načíst profil nastavení…", self.loadProfile)
        m_file.addSeparator()
        self._addAction(m_file, "&Konec", self.close, "Ctrl+Q")

        m_cam = bar.addMenu("&Kamera")
        self.act_connect = self._addAction(m_cam, "&Připojit / odpojit", self.toggleConnect, "F5")
        self._addAction(m_cam, "&Hledat kamery", self.refreshDevices, "F6")
        m_cam.addSeparator()
        self._addAction(m_cam, "Vyvážit &bílou", lambda: self.doAction("wb_once"), "Ctrl+W")
        self._addAction(m_cam, "&Zaostřit", lambda: self.doAction("af_once"), "Ctrl+F")
        self._addAction(m_cam, "Obnovit &výchozí hodnoty", self.resetDefaults)
        m_cam.addSeparator()
        self._addAction(m_cam, "&Diagnostika SDK…", self.showDiagnostics)

        m_view = bar.addMenu("&Zobrazení")
        self._addAction(m_view, "Přizpůsobit oknu", self.view.fitToWindow, "Ctrl+0")
        self._addAction(m_view, "Skutečná velikost 1:1", lambda: self.view.setZoom(1.0), "Ctrl+1")
        self._addAction(m_view, "Přiblížit", lambda: self.view.zoomBy(1.25), QKeySequence.ZoomIn)
        self._addAction(m_view, "Oddálit", lambda: self.view.zoomBy(1 / 1.25), QKeySequence.ZoomOut)
        m_view.addSeparator()
        self.act_grid = self._addAction(m_view, "&Mřížka třetin", self._onOverlay, "G", True)
        self.act_cross = self._addAction(m_view, "&Nitkový kříž", self._onOverlay, "K", True)
        self.act_scale = self._addAction(m_view, "Měřít&ko", self._onOverlay, "M", True)
        self._addAction(m_view, "&Kalibrace měřítka…", self.calibrate)
        m_view.addSeparator()
        self.act_roi = self._addAction(m_view, "Výběr oblasti pro &WB (ROI)", self._onRoiMode, None, True)
        self._addAction(m_view, "Zrušit výběr oblasti", self.view.clearRoi)
        m_view.addSeparator()
        self.act_leds = self.led_dock.toggleViewAction()
        self.act_leds.setText("Panel &osvětlení")
        self.act_leds.setShortcut("Ctrl+L")
        m_view.addAction(self.act_leds)
        m_view.addSeparator()
        self.act_fullscreen = self._addAction(m_view, "Celá obrazovka", self._onFullscreen, "F11", True)

        m_help = bar.addMenu("&Nápověda")
        self._addAction(m_help, "Klávesové &zkratky…", self.showShortcuts)
        self._addAction(m_help, "&O aplikaci…", self.showAbout)

        tb = QToolBar("Hlavní")
        tb.setObjectName("mainToolBar")
        tb.setIconSize(QSize(16, 16))
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb)
        tb.addAction(self.act_connect)
        tb.addSeparator()
        tb.addAction(self._mkAction("Snímek", self.snapshot))
        tb.addAction(self._mkAction("Video", self.toggleRecord))
        tb.addSeparator()
        tb.addAction(self._mkAction("Fit", self.view.fitToWindow))
        tb.addAction(self._mkAction("1:1", lambda: self.view.setZoom(1.0)))
        tb.addAction(self._mkAction("+", lambda: self.view.zoomBy(1.25)))
        tb.addAction(self._mkAction("−", lambda: self.view.zoomBy(1 / 1.25)))
        tb.addSeparator()
        tb.addAction(self.act_grid)
        tb.addAction(self.act_cross)
        tb.addAction(self.act_scale)
        tb.addSeparator()
        tb.addAction(self.act_leds)
        self.lbl_zoom = QLabel("  100 %  ")
        tb.addWidget(self.lbl_zoom)

    def _addAction(self, menu, text, slot, shortcut=None, checkable=False) -> QAction:
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(shortcut)
        act.setCheckable(checkable)
        (act.toggled if checkable else act.triggered).connect(lambda *_: slot())
        menu.addAction(act)
        return act

    def _mkAction(self, text, slot) -> QAction:
        act = QAction(text, self)
        act.triggered.connect(lambda *_: slot())
        return act

    # ============================================================ zařízení ===
    def refreshDevices(self) -> None:
        self.devices = enumerate_devices(include_demo=self._include_demo)
        self.cmb_device.clear()
        for dev in self.devices:
            self.cmb_device.addItem(str(dev))
        if not self.devices:
            self.cmb_device.addItem("— žádná kamera nenalezena —")
        elif self._prefer_demo:
            idx = next((i for i, d in enumerate(self.devices) if d.backend == "demo"), 0)
            self.cmb_device.setCurrentIndex(idx)
        self.btn_connect.setEnabled(bool(self.devices))

    def toggleConnect(self) -> None:
        if self.camera is not None:
            self.disconnectCamera()
        else:
            self.connectCamera()

    def connectCamera(self) -> None:
        if not self.devices:
            self.refreshDevices()
        idx = max(self.cmb_device.currentIndex(), 0)
        if idx >= len(self.devices):
            QMessageBox.warning(self, APP_NAME, "Není vybrána žádná kamera.")
            return
        try:
            self.camera = open_device(self.devices[idx])
        except (CameraError, Exception) as exc:
            QMessageBox.critical(self, APP_NAME, f"Kameru se nepodařilo otevřít:\n\n{exc}")
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
        self.btn_connect.setText("Odpojit")
        self.lbl_state.setText(f"Připojeno – {self.devices[idx].name}")
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
        self.tabs.clear()
        self.panels.clear()
        self.specs.clear()
        self.cmb_res.clear()
        self.cmb_codec.clear()
        self.btn_connect.setText("Připojit")
        self.lbl_state.setText("Nepřipojeno")
        self.lbl_res.setText("–")
        self.lbl_rec.setText("")
        self.lbl_info.setText("–")
        self._updateEnabled()

    # ------------------------------------------------------------- panely ---
    def _buildPanels(self) -> None:
        self.tabs.clear()
        self.panels.clear()
        for group in GROUP_ORDER:
            specs = [s for s in self.specs.values()
                     if s.group == group and not s.hidden]
            if not specs:
                continue
            specs.sort(key=lambda s: (s.kind == KIND_ACTION, s.kind == KIND_READONLY))
            panel = PropertyPanel(specs)
            panel.valueChanged.connect(self._onPropChanged)
            panel.actionTriggered.connect(self.doAction)
            self.panels[group] = panel
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setWidget(panel)
            idx = self.tabs.addTab(scroll, GROUP_TITLES[group])
            self.tabs.setTabToolTip(idx, GROUP_TOOLTIPS[group])

    def _fillResolutions(self) -> None:
        self.cmb_res.blockSignals(True)
        self.cmb_res.clear()
        for w, h in self.camera.resolutions():
            mp = w * h / 1e6
            self.cmb_res.addItem(f"{w} × {h}  ({mp:.1f} MPx)")
        try:
            self.cmb_res.setCurrentIndex(self.camera.get_resolution())
        except Exception:
            pass
        self.cmb_res.blockSignals(False)
        self.cmb_res.setEnabled(self.cmb_res.count() > 1)

        self.cmb_codec.blockSignals(True)
        self.cmb_codec.clear()
        codecs = self.camera.codecs()
        self.cmb_codec.addItems(codecs)
        if codecs:
            try:
                self.cmb_codec.setCurrentIndex(self.camera.get_codec())
            except Exception:
                pass
        self.cmb_codec.blockSignals(False)
        self.cmb_codec.setEnabled(len(codecs) > 1)

    def _loadValues(self) -> None:
        """Načte aktuální hodnoty z kamery do ovládacích prvků."""
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

    def _applyDependencies(self, values: Dict[str, int]) -> None:
        """Zašedne prvky, které v daném režimu nemají smysl."""
        auto_expo = bool(values.get("aexpo", 0))
        for key in ("expotime", "again"):
            self._setRowEnabled(key, not auto_expo)
        wbmode = values.get("wbmode")
        manual_wb = wbmode is None or wbmode == 0
        for key in ("wbred", "wbgreen", "wbblue", "temp", "tint"):
            self._setRowEnabled(key, manual_wb)
        afmode = values.get("afmode")
        self._setRowEnabled("afposition", afmode in (None, 0))
        self._setRowEnabled("afposition_abs", afmode in (None, 0))

    def _setRowEnabled(self, key: str, on: bool) -> None:
        for panel in self.panels.values():
            if key in panel.keys():
                panel.setRowEnabled(key, on)

    def _showInfo(self) -> None:
        info = self.camera.info() if self.camera else {}
        self.lbl_info.setText("   ".join(f"{k}: {v}" for k, v in info.items()) or "–")

    # ============================================================== stream ===
    def _sdkCallback(self, event: int) -> None:
        """Běží ve vlákně SDK – jen přepošle signál do GUI."""
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
        fmt = QImage.Format_RGB888
        if getattr(self.camera, "pixel_order", "rgb") == "bgr":
            fmt = getattr(QImage, "Format_BGR888", QImage.Format_RGB888)
        img = QImage(frame.data, frame.width, frame.height, frame.stride, fmt)
        if fmt == QImage.Format_RGB888 and getattr(self.camera, "pixel_order", "rgb") == "bgr":
            img = img.rgbSwapped()             # starší Qt bez Format_BGR888
        return img

    # ============================================================ vlastnosti =
    def _onPropChanged(self, key: str, value: int) -> None:
        if self.camera is None:
            return
        try:
            self.camera.set(key, value)
        except CameraError as exc:
            self.status.showMessage(f"{key}: {exc}", 4000)
            return
        if key in ("aexpo", "wbmode", "afmode"):
            QTimer.singleShot(50, self._loadValues)

    def doAction(self, key: str) -> None:
        if self.camera is None or key not in self.specs:
            return
        try:
            self.camera.action(key)
        except CameraError as exc:
            self.status.showMessage(str(exc), 4000)
            return
        self.status.showMessage(f"{self.specs[key].label} – provedeno", 2500)
        QTimer.singleShot(300, self._loadValues)

    def resetDefaults(self) -> None:
        if self.camera is None:
            return
        if QMessageBox.question(self, APP_NAME,
                                "Obnovit všechny výchozí hodnoty kamery?") != QMessageBox.Yes:
            return
        for key, spec in self.specs.items():
            if spec.kind == KIND_ACTION or spec.kind == KIND_READONLY:
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
            QMessageBox.warning(self, APP_NAME, f"Rozlišení se nepodařilo změnit:\n{exc}")
            return
        self.view.clear()
        self.status.showMessage("Rozlišení změněno", 2000)

    def _onCodecChanged(self, index: int) -> None:
        if self.camera is None or index < 0:
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

    def _stamp(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def snapshot(self, silent: bool = False) -> Optional[str]:
        if not self.view.hasImage():
            if not silent:
                QMessageBox.information(self, APP_NAME, "Není k dispozici žádný obraz.")
            return None
        image = self.view.image().copy()
        path = os.path.join(self._ensureDir(), f"snimek_{self._stamp()}.jpg")
        if image.save(path, quality=95):
            self._snap_count += 1
            self.status.showMessage(f"Uloženo: {path}", 4000)
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
            self.lbl_rec.setText("")
            self.status.showMessage("Nahrávání ukončeno", 3000)
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
            QMessageBox.warning(self, APP_NAME, f"Nahrávání se nepodařilo spustit:\n{exc}")
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
            self.status.showMessage(f"Časosběr: uloženo {self._timelapse_count} snímků", 3000)

    def chooseSaveDir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Složka pro ukládání", self.save_dir)
        if path:
            self.save_dir = path
            self.settings.setValue("save_dir", path)
            self._updateDirLabel()

    def _updateDirLabel(self) -> None:
        self.lbl_dir.setText(f"Ukládat do: {self.save_dir}")

    # ============================================================== profily ==
    def saveProfile(self) -> None:
        if self.camera is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Uložit profil nastavení",
            os.path.join(self.save_dir, "profil.json"), "JSON (*.json)")
        if not path:
            return
        data = {"backend": self.camera.name, "values": {}}
        for key, spec in self.specs.items():
            if spec.kind in (KIND_ACTION, KIND_READONLY) or spec.write_only:
                continue
            if spec.hidden:
                continue
            try:
                data["values"][key] = self.camera.get(key)
            except Exception:
                pass
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self.status.showMessage(f"Profil uložen: {path}", 4000)

    def loadProfile(self) -> None:
        if self.camera is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Načíst profil nastavení",
                                              self.save_dir, "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        skipped = []
        for key, val in (data.get("values") or {}).items():
            if key not in self.specs:
                skipped.append(key)
                continue
            try:
                self.camera.set(key, int(val))
            except Exception:
                skipped.append(key)
        self._loadValues()
        msg = "Profil načten."
        if skipped:
            msg += f" Nepoužito: {', '.join(sorted(skipped))}"
        self.status.showMessage(msg, 5000)

    # ============================================================ zobrazení ==
    def _onOverlay(self) -> None:
        self.view.show_grid = self.act_grid.isChecked()
        self.view.show_cross = self.act_cross.isChecked()
        self.view.show_scale = self.act_scale.isChecked()
        self.view.update()

    def _onRoiMode(self) -> None:
        self.view.roi_mode = self.act_roi.isChecked()
        if self.view.roi_mode:
            self.status.showMessage(
                "Tažením myši vyberte oblast pro vyvážení bílé.", 5000)

    def _onRoiSelected(self, rect) -> None:
        """Předá vybraný obdélník kameře jako WB ROI (pokud to SDK umí)."""
        if self.camera is None:
            return
        mapping = (("wbroileft", rect.x()), ("wbroitop", rect.y()),
                   ("wbroiwidth", rect.width()), ("wbroiheight", rect.height()))
        applied = False
        for key, val in mapping:
            try:
                self.camera.set(key, val)
                applied = True
            except Exception:
                pass
        if applied:
            try:
                self.camera.set("wbmode", 2)
            except Exception:
                pass
            self._loadValues()
            self.status.showMessage("Oblast pro vyvážení bílé nastavena.", 4000)
        else:
            self.status.showMessage(
                "Kamera nepodporuje vyvážení bílé podle oblasti.", 4000)

    def _onZoomChanged(self, scale: float) -> None:
        self.lbl_zoom.setText(f"  {scale * 100:.0f} %  ")

    def _onFullscreen(self) -> None:
        if self.act_fullscreen.isChecked():
            self.showFullScreen()
        else:
            self.showNormal()

    def calibrate(self) -> None:
        dlg = CalibrationDialog(self.view.um_per_px, self)
        if dlg.exec_() == QDialog.Accepted:
            self.view.um_per_px = dlg.value()
            self.settings.setValue("um_per_px", self.view.um_per_px)
            self.act_scale.setChecked(True)
            self._onOverlay()

    # ================================================================ časovač
    def _onUiTimer(self) -> None:
        now = time.time()
        elapsed = max(now - getattr(self, "_fps_since", now - 0.5), 0.001)
        self._fps_since = now
        self._fps = self._frames / elapsed
        self._frames = 0
        self.lbl_fps.setText(f"{self._fps:.1f} fps".replace(".", ","))
        self.lbl_frames.setText(f"{self._frames_total} snímků")
        if self._recording_since is not None:
            el = int(time.time() - self._recording_since)
            self.lbl_rec.setText(f"● REC {el // 60:02d}:{el % 60:02d}")
        if self.camera is None:
            return
        if self.view.hasImage():
            img = self.view.image()
            self.lbl_res.setText(f"{img.width()} × {img.height()}")
        self._refreshLive()

    def _refreshLive(self) -> None:
        """Obnoví hodnoty, které si kamera mění sama (auto režimy)."""
        values = {}
        for key, spec in self.specs.items():
            if not spec.live or spec.write_only:
                continue
            if key in ("expotime", "again") and not self._isAuto("aexpo"):
                continue
            if key in ("wbred", "wbgreen", "wbblue", "temp", "tint") and self._isManual("wbmode"):
                continue
            try:
                values[key] = self.camera.get(key)
            except Exception:
                continue
        for panel in self.panels.values():
            panel.setValues(values)

    def _isAuto(self, key: str) -> bool:
        panel_row = self._findRow(key)
        return bool(panel_row.value()) if panel_row else False

    def _isManual(self, key: str) -> bool:
        row = self._findRow(key)
        return row.value() == 0 if row else True

    def _findRow(self, key: str):
        for panel in self.panels.values():
            if key in panel.rows:
                return panel.rows[key]
        return None

    def _updateEnabled(self) -> None:
        on = self.camera is not None
        for w in (self.btn_snap, self.btn_record, self.btn_timelapse, self.spin_interval):
            w.setEnabled(on)
        self.tabs.setEnabled(on)
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
        dlg = QDialog(self)
        dlg.setWindowTitle("Diagnostika SDK")
        dlg.resize(720, 320)
        lay = QVBoxLayout(dlg)
        edit = QPlainTextEdit(text)
        edit.setReadOnly(True)
        lay.addWidget(edit)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(dlg.reject)
        lay.addWidget(box)
        dlg.exec_()

    def showShortcuts(self) -> None:
        QMessageBox.information(self, "Klávesové zkratky", SHORTCUTS_TEXT)

    def showAbout(self) -> None:
        from .. import __version__
        QMessageBox.about(self, "O aplikaci", ABOUT_TEXT.format(version=__version__))

    # ================================================================ zavření
    def closeEvent(self, event) -> None:
        self.timelapse_timer.stop()
        self.ui_timer.stop()
        self.settings.setValue("window_state", self.saveState())
        self.led_panel.shutdown()
        self.disconnectCamera()
        super().closeEvent(event)


class CalibrationDialog(QDialog):
    """Zadání měřítka v mikrometrech na pixel."""

    def __init__(self, current: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kalibrace měřítka")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Zadejte, kolik mikrometrů odpovídá jednomu pixelu obrazu.\n"
            "Hodnotu zjistíte snímkem objektového mikrometru."))
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


SHORTCUTS_TEXT = """\
F5           připojit / odpojit kameru
F6           znovu vyhledat kamery
Ctrl+S       uložit snímek
Ctrl+R       spustit / zastavit nahrávání
Ctrl+W       vyvážení bílé
Ctrl+F       zaostřit
Ctrl+0       přizpůsobit oknu
Ctrl+1       skutečná velikost 1:1
Ctrl + / −   přiblížit / oddálit
G / K / M    mřížka / nitkový kříž / měřítko
F11          celá obrazovka
Ctrl+Q       ukončit

Myš:  kolečko = zoom, tažení = posun, dvojklik = přizpůsobit oknu
"""

ABOUT_TEXT = """\
<b>BMS Cam Control {version}</b><br><br>
Ovládání mikroskopové kamery BMS Microscopes RJ45 8MP 4K UHD Multioutput HDMI.<br><br>
Postaveno nad SDK <i>uvcham</i> (Windows, uvcham.dll) a nad nativním
SDK <i>ToupTek</i> (libtoupcam). Bez připojeného hardwaru lze aplikaci
vyzkoušet v simulovaném režimu.
"""
