"""Hlavní okno aplikace BMS Cam Control."""

import glob
import json
import os
import shutil
import time
from datetime import datetime
from typing import Dict, List, Optional

from PyQt5.QtCore import QSettings, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QKeySequence
from PyQt5.QtWidgets import (QAction, QApplication, QComboBox, QDialog,
                             QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QHBoxLayout, QLabel, QMainWindow,
                             QMenu, QMessageBox, QPlainTextEdit,
                             QProgressDialog, QScrollArea, QSizePolicy,
                             QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from ..backends import (EVENT_DISCONNECT, EVENT_ERROR, EVENT_IMAGE,
                        CameraBackend, CameraError, diagnostics,
                        enumerate_devices, open_device)
from .. import darkfield, videocheck, workspace
from ..spec import (GROUP_ORDER, GROUP_TITLES, GROUP_TOOLTIPS, KIND_ACTION,
                    KIND_READONLY, DeviceInfo, PropSpec)
from . import theme
from .controls import PropertyPanel
from .darkfield_panel import DarkFieldPanel
from .darkfield_worker import DarkFieldRunner
from .led_panel import LedPanel
from .video_view import VideoView
from .widgets import (Card, SegmentedControl, SidePanel, Tag, button, hline,
                      icon_button, label, row, set_icon, vline)

APP_NAME = "BMS Cam Control"
DARKFIELD_TITLE = "Dark"
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
        self._record_path: Optional[str] = None
        self._timelapse_count = 0
        self._timelapse_dir: Optional[str] = None
        self._df_pending = False          # čeká se na snímek k rozboru
        self._df_store = None             # složka se snímky pro zpětný rozbor
        self._df_stack_left = 0           # kolik dílčích snímků do průměru zbývá
        self._df_stack_last = 0.0         # čas posledního dílčího snímku
        self._df_last_bias_frame = 0.0    # kdy naposled šel snímek do reference
        self._mc_queue: List[str] = []    # kanály, které v cyklu ještě zbývají
        self._mc_channel = ""             # kanál, který se právě snímá
        self._mc_mode = ""                # "measure" / "bias" / "" = neběží
        self._mc_base = {}                # expozice a ostření před cyklem
        self._mc_led_color = None         # barva osvětlení před cyklem

        self.save_dir = self.settings.value("save_dir",
                                            workspace.default_save_dir())

        # Uložený vzhled se použije ještě před stavbou oken, aby widgety
        # rovnou vznikly ve správných barvách a nemusely se přebarvovat.
        if str(self.settings.value("dark_mode", "false")).lower() in ("true", "1"):
            theme.set_mode("dark")
            app = QApplication.instance()
            if app is not None:
                app.setStyleSheet(theme.stylesheet())

        self._buildActions()
        self._buildUi()
        self.cameraEvent.connect(self._onCameraEvent)

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._onUiTimer)
        self.ui_timer.start(500)

        self.timelapse_timer = QTimer(self)
        self.timelapse_timer.timeout.connect(self._onTimelapse)

        self.df_timer = QTimer(self)
        self.df_timer.timeout.connect(self._requestSample)

        self.df_runner = DarkFieldRunner(self)
        self.df_runner.sampleReady.connect(self._onDarkFieldSample)
        self.df_runner.biasProgress.connect(self.df_panel.setBiasProgress)
        self.df_runner.stackProgress.connect(self.df_panel.setStackProgress)
        self.df_runner.biasReady.connect(self._onBiasReady)
        self.df_runner.failed.connect(self._onDarkFieldFailed)

        self.view.um_per_px = float(self.settings.value("um_per_px", 1.0))
        self.df_panel.setSaveDir(self.save_dir)
        try:
            queue_mb = int(self.settings.value("df_queue_mb", 0))
        except (TypeError, ValueError):
            queue_mb = 0
        if queue_mb:
            self.df_panel.spin_queue.setValue(queue_mb)
        self._onQueueLimitChanged(self.df_panel.spin_queue.value())
        self.df_panel.setScaleInfo(self.view.um_per_px)
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
        self.act_profile_save = act("Uložit kompletní nastavení…", self.saveProfile)
        self.act_profile_load = act("Načíst kompletní nastavení…", self.loadProfile)
        self.act_dir = act("Složka pro ukládání…", self.chooseSaveDir)
        self.act_diag = act("Diagnostika SDK…", self.showDiagnostics)
        self.act_checkvideo = act("Zkontrolovat nahrané video…", self.checkVideo)
        self.act_checkexpo = act("Kontrola stálosti expozice…", self.checkExposure)
        self.act_shortcuts = act("Klávesové zkratky…", self.showShortcuts, "F1")
        self.act_about = act("O aplikaci…", self.showAbout)
        self.act_dark = act("Tmavý vzhled", self.toggleDarkMode, "Ctrl+D", True)
        self.act_dark.setChecked(theme.mode() == "dark")
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
        self.toolbar = self._buildToolbar()
        outer.addWidget(self.toolbar)
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
        camera_page = QWidget()
        camera_page.setLayout(middle)

        # Obrazovka rozboru se staví až při prvním přepnutí: táhne s sebou
        # OpenCV, které se na Windows nesmí načíst dřív než zásuvné moduly Qt.
        self.analyzer = None
        self.screens = QStackedWidget()
        self.screens.addWidget(camera_page)
        self.screens.addWidget(QWidget())
        outer.addWidget(self.screens, 1)

        outer.addWidget(hline())
        outer.addWidget(self._buildStatusBar())
        self.setCentralWidget(root)
        self._updateDirLabel()

    @staticmethod
    def _vsep() -> QWidget:
        sep = QWidget()
        sep.setFixedWidth(2)
        sep.setStyleSheet(f"background: {theme.DIVIDER};")
        theme.on_change(
            lambda w=sep: w.setStyleSheet(f"background: {theme.DIVIDER};"), sep)
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
        lay.addSpacing(theme.SPACE_4)

        # Dvě obrazovky: snímání u kamery a dávkový rozbor nafocených sérií.
        self.seg_screen = SegmentedControl(["Kamera", "Analýza"])
        self.seg_screen.setFixedWidth(180)
        self.seg_screen.currentChanged.connect(self.showScreen)
        lay.addWidget(self.seg_screen)
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

    def showScreen(self, index: int) -> None:
        """Přepne mezi obrazovkou kamery a obrazovkou rozboru."""
        index = 1 if int(index) else 0
        if index == 1 and self.analyzer is None and not self._buildAnalyzer():
            self.seg_screen.setCurrentIndex(0, emit=False)
            return
        self.screens.setCurrentIndex(index)
        # Lišta s přiblížením a panel osvětlení patří ke kameře; u rozboru
        # by jen mátly, protože se týkají živého obrazu.
        self.toolbar.setVisible(index == 0)
        self.right_panel.setVisible(index == 0 and self.act_leds.isChecked())
        if self.seg_screen.currentIndex() != index:
            self.seg_screen.setCurrentIndex(index, emit=False)
        if index == 1 and self.analyzer is not None:
            self.analyzer.refreshFolders()
        self.statusMessage("Obrazovka: "
                           + ("analýza sérií" if index else "kamera"), 3000)

    def _buildAnalyzer(self) -> bool:
        """Postaví obrazovku analýzy. Vrací False, když to nejde.

        Obrazovka táhne OpenCV a celé jádro rozboru, takže se staví až
        tady – a její vznik trvá i sekundy, proto přesýpací hodiny.
        Selhání (chybějící OpenCV) se hlásí dialogem, ne pádem: uživatel
        má dál k dispozici celou práci s kamerou."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.statusMessage("Připravuji analýzu…", 4000)
        QApplication.processEvents()
        try:
            from .analyzer_screen import AnalyzerScreen
            screen = AnalyzerScreen(self.settings)
        except Exception as exc:                           # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(
                self, APP_NAME,
                "Obrazovku analýzy nejde otevřít:\n{}\n\n"
                "Nejčastěji chybí knihovna OpenCV – nainstaluje se příkazem\n"
                "pip install opencv-python".format(exc))
            self.statusMessage("Analýza není k dispozici: " + str(exc), 8000)
            return False
        QApplication.restoreOverrideCursor()
        self.analyzer = screen
        self.analyzer.statusMessage.connect(self.statusMessage)
        placeholder = self.screens.widget(1)
        self.screens.removeWidget(placeholder)
        placeholder.deleteLater()
        self.screens.addWidget(self.analyzer)
        return True

    def _buildMenu(self) -> QMenu:
        menu = QMenu(self)
        for action in (self.act_snap, self.act_record, self.act_checkvideo,
                       self.act_dir):
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
        menu.addSeparator()
        menu.addAction(self.act_dark)
        for action in (self.act_checkexpo, self.act_diag, self.act_shortcuts, self.act_about,
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

        # Kamera umí oba režimy; přepínač je tady, protože se s ním hýbe
        # při práci často – v seznamu vlastností by se hledal špatně.
        self.seg_color = SegmentedControl(["Barevně", "Černobíle"])
        self.seg_color.setFixedWidth(160)
        self.seg_color.setToolTip(
            "Barevný, nebo černobílý obraz.\n"
            "Černobílý režim se hodí pro temné pole a měření po kanálech – "
            "odpadne demozaikování a barevný šum.")
        self.seg_color.setEnabled(False)
        self.seg_color.currentChanged.connect(
            lambda index: self.setMonochrome(index == 1))
        lay.addWidget(self.seg_color)
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

        self.btn_dark = icon_button("sun" if theme.mode() == "dark" else "moon",
                                    "", checkable=False)
        self.btn_dark.clicked.connect(self.toggleDarkMode)
        self._updateDarkButton()
        lay.addWidget(self.btn_dark)
        return bar

    def _updateDarkButton(self) -> None:
        dark = theme.mode() == "dark"
        set_icon(self.btn_dark, "sun" if dark else "moon")
        self.btn_dark.setToolTip(
            ("Světlý vzhled aplikace (Ctrl+D)" if dark
             else "Tmavý vzhled aplikace (Ctrl+D)"))

    # ------------------------------------------------------------ levý panel -
    def _fillLeftPanel(self) -> None:
        panel = self.left_panel

        profile_box = QWidget()
        profile_lay = QVBoxLayout(profile_box)
        profile_lay.setContentsMargins(0, 0, 0, 0)
        profile_lay.setSpacing(4)
        profile_lay.addWidget(label("Kompletní nastavení", "field"))
        self.cmb_profile = QComboBox()
        self.cmb_profile.setToolTip(
            "Uložená nastavení ve složce pro ukládání. Výběrem se použije.")
        self.cmb_profile.activated.connect(self._onProfileSelected)
        profile_lay.addWidget(self.cmb_profile)
        btn_profile_save = button("Uložit vše…", "secondary", "save")
        btn_profile_save.setToolTip(
            "Uloží kameru, osvětlení, rozbor temného pole i nastavení "
            "snímání do jednoho souboru JSON.")
        btn_profile_save.clicked.connect(self.saveProfile)
        btn_profile_load = button("Načíst…", "secondary", "folder")
        btn_profile_load.setToolTip("Načte nastavení ze souboru.")
        btn_profile_load.clicked.connect(self.loadProfile)
        profile_lay.addLayout(row((btn_profile_save, 1), (btn_profile_load, 1)))
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
        # Kodek se v panelu nezobrazuje – nastavuje se jednou za život a
        # zabíral místo, které je potřeba pro rozbor temného pole. Volba
        # zůstává v paměti aplikace, takže se pořád ukládá i načítá.
        self.cmb_codec = QComboBox()
        self.cmb_codec.setVisible(False)
        self.cmb_codec.currentIndexChanged.connect(self._onCodecChanged)
        # Údaje o kameře na jeden řádek; celé znění je v tooltipu. Tři
        # řádky tady chyběly dole u rozboru temného pole.
        self.lbl_info = label("–", "meta")
        self.lbl_info.setWordWrap(False)
        card.add(self.lbl_info)
        panel.add(card)

        self.seg_tabs = SegmentedControl(
            [GROUP_TITLES[g] for g in GROUP_ORDER] + [DARKFIELD_TITLE],
            compact=True)
        self.seg_tabs.currentChanged.connect(lambda i: self.tabs.setCurrentIndex(i))
        panel.add(self.seg_tabs)

        self.tabs = QStackedWidget()
        self.tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.df_panel = DarkFieldPanel()
        self.df_panel.biasRequested.connect(self.startBiasCapture)
        self.df_panel.measureToggled.connect(self._onDarkFieldToggled)
        self.df_panel.queueLimitChanged.connect(self._onQueueLimitChanged)
        self.df_panel.sampleRequested.connect(lambda: self._requestSample(True))
        self.df_panel.reanalyzeRequested.connect(self.reanalyzeDarkField)
        self.df_scroll = QScrollArea()
        self.df_scroll.setWidgetResizable(True)
        self.df_scroll.setFrameShape(QScrollArea.NoFrame)
        self.df_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.df_scroll.setWidget(self.df_panel)
        self.tabs.addWidget(self.df_scroll)
        # Rozbor temného pole má nejvíc ovládání, takže volné místo v panelu
        # dostane přednostně tahle část – ať se v ní nemusí tolik scrollovat.
        self.tabs.setMinimumHeight(380)
        panel.add(self.tabs, 1)
        panel.add(hline())

        # Snímání zabíralo pět řádků, přestože se používá zřídka: dva
        # popisky odsud jsou i ve stavovém řádku a složka se mění výjimečně.
        # Zůstal jeden řádek tlačítek plus časosběr.
        capture = Card("Snímání")
        capture.layout().setContentsMargins(theme.SPACE_3, theme.SPACE_2,
                                            theme.SPACE_3, theme.SPACE_2)
        capture.layout().setSpacing(theme.SPACE_1)
        self.btn_snap = button("Snímek", "primary", "camera")
        self.btn_snap.clicked.connect(lambda: self.snapshot())
        self.btn_record = button("Video", "secondary", "video")
        self.btn_record.clicked.connect(self.toggleRecord)
        btn_dir = icon_button("folder", "Změnit složku pro ukládání…", size=30)
        btn_dir.clicked.connect(self.chooseSaveDir)
        capture.add(row((self.btn_snap, 2), (self.btn_record, 2), btn_dir))

        self.btn_timelapse = button("Časosběr", "secondary", "timer")
        self.btn_timelapse.setCheckable(True)
        self.btn_timelapse.toggled.connect(self.toggleTimelapse)
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(1, 3600)
        self.spin_interval.setValue(int(self.settings.value("timelapse_interval", 10)))
        self.spin_interval.setFixedWidth(62)
        self.spin_interval.setAlignment(Qt.AlignCenter)
        self.spin_interval.setToolTip("Interval časosběru v sekundách")
        capture.add(row((self.btn_timelapse, 1), self.spin_interval,
                        label("s", "meta")))

        # Popisek složky zůstává jen ve stavovém řádku dole; tady byl podruhé.
        self.lbl_dir = label("", "meta")
        self.lbl_dir.setVisible(False)
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
        # Název bývá delší než panel; QComboBox by ho jen uřízl, proto se
        # zkracuje s výpustkou a celý zůstává v tooltipu.
        metrics = self.cmb_device.fontMetrics()
        width = max(120, self.cmb_device.width() - 34)
        for index, dev in enumerate(self.devices):
            text = str(dev)
            self.cmb_device.addItem(metrics.elidedText(text, Qt.ElideRight, width))
            self.cmb_device.setItemData(index, text, Qt.ToolTipRole)
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
        # Záznam musí skončit dřív, než se zavře kamera – jinak zůstane
        # soubor bez rejstříku a nepůjde přehrát.
        if self.isRecording():
            self.stopRecording(verify=False)
        self.df_panel.stopMeasuring()
        self.df_runner.cancelBias()
        self._df_pending = False
        self._mc_queue = []
        self._mc_mode = ""
        self._mc_channel = ""
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
        for index in reversed(range(self.tabs.count())):
            widget = self.tabs.widget(index)
            if widget is self.df_scroll:      # Dark Field drží data, ten zůstává
                continue
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
            self.tabs.insertWidget(position, scroll)
            self.seg_tabs.buttons[position].setEnabled(bool(specs))
            self.seg_tabs.buttons[position].setToolTip(GROUP_TOOLTIPS[group])
        self.seg_tabs.buttons[len(GROUP_ORDER)].setToolTip(
            "Sledování kontaminace witness sklíčka v temném poli")
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
        mono = bool(values.get("chrome", 0))
        self.seg_color.setEnabled("chrome" in self.specs)
        if "chrome" in values:
            self.seg_color.setCurrentIndex(1 if mono else 0, emit=False)
        # v černobílém režimu nemá barevné doladění co ovlivnit
        for key in ("saturation", "hue", "wbmode", "wbred", "wbgreen",
                    "wbblue", "temp", "tint"):
            if mono:
                self._setRowEnabled(key, False)
        auto_expo = bool(values.get("aexpo", 0))
        for key in ("expotime", "again"):
            self._setRowEnabled(key, not auto_expo)
        wbmode = values.get("wbmode")
        manual_wb = (wbmode is None or wbmode == 0) and not mono
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
        text = " · ".join(f"{k} {v}" for k, v in info.items()) or "–"
        self.lbl_info.setToolTip(text)
        metrics = self.lbl_info.fontMetrics()
        self.lbl_info.setText(metrics.elidedText(
            text, Qt.ElideRight, max(120, self.lbl_info.width() or 240)))

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
        if self._df_pending or self.df_runner.collecting_bias:
            self._darkFieldFrame(frame)
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

    # ============================================================ dark field =
    def _grayFrame(self, frame):
        """Šedotónová podoba snímku pro rozbor."""
        return darkfield.to_gray(frame, getattr(self.camera, "pixel_order", "rgb"))

    def _darkFieldRoi(self):
        """Výřez v souřadnicích obrazu, pokud si ho uživatel vybral."""
        if not self.df_panel.wantsRoi():
            return None
        rect = self.view.roi()
        if rect.isNull() or rect.width() < 2 or rect.height() < 2:
            return None
        return (rect.x(), rect.y(), rect.width(), rect.height())

    def startBiasCapture(self, frames: int) -> None:
        """Začne sbírat snímky čistého sklíčka do referenčního snímku."""
        if self.camera is None or not self.camera.is_running():
            QMessageBox.information(self, APP_NAME,
                                    "Nejdřív připojte kameru a spusťte obraz.")
            return
        self._df_last_bias_frame = 0.0
        self._bias_frames = frames
        if self.df_panel.isMultichannel():
            if not self._startChannelCycle("bias"):
                return
            self.statusMessage("Snímám referenci po kanálech…", 4000)
            return
        self.df_runner.startBias(frames)
        self.statusMessage("Snímám referenci čistého sklíčka…", 4000)

    def _onBiasReady(self, bias) -> None:
        self.df_panel.setBias(bias, self._mc_channel)
        if self._mc_mode == "bias":
            self._nextChannel()
            return
        self.statusMessage("Reference pořízena", 4000)
        self._autoSaveBias()

    def _onDarkFieldSample(self, metrics, when) -> None:
        self.df_panel.addSample(metrics, when)
        self.df_panel.setPendingInfo(self.df_runner.pending)
        if self._df_store is not None:
            self.df_panel.setStoreInfo(self._df_store)
        if self._mc_mode == "measure":
            self._nextChannel()

    # ------------------------------------------------- měření po kanálech ---
    def _startChannelCycle(self, mode: str) -> bool:
        """Rozjede cyklus R → G → B. Vrací False, když to nejde."""
        if self.camera is None or not self.camera.is_running():
            QMessageBox.information(self, APP_NAME,
                                    "Nejdřív připojte kameru a spusťte obraz.")
            return False
        if not self.led_panel.link.is_open():
            QMessageBox.information(
                self, APP_NAME,
                "Měření po kanálech potřebuje osvětlení přes Arduino – "
                "jednotlivé barvy rozsvěcí ono.\n\nPřipojte desku v panelu "
                "osvětlení, nebo režim vypněte.")
            self.df_panel.stopMeasuring()
            return False
        if self._mc_mode:
            return False                      # cyklus už běží, nepřekrývat
        try:
            auto = self.camera.get("aexpo") if "aexpo" in self.specs else 0
        except Exception:
            auto = 0
        if auto:
            # Násobky expozice se počítají z hodnoty naměřené na začátku
            # cyklu. Se zapnutou automatikou se ta hodnota mění sama, takže
            # by násobek neznamenal vůbec nic a po cyklu by se nebylo kam
            # vracet.
            QMessageBox.information(
                self, APP_NAME,
                "Měření po kanálech potřebuje ruční expozici.\n\n"
                "Zapnutá automatika mění expoziční čas sama, takže by "
                "násobky u jednotlivých barev neplatily. Vypněte ji "
                "v záložce Expozice a nastavte čas ručně.")
            self.df_panel.stopMeasuring()
            return False

        self._mc_mode = mode
        self._mc_queue = list(darkfield.CHANNEL_ORDER)
        self._mc_base = {}
        for key in ("expotime", "afposition"):
            if key in self.specs:
                try:
                    self._mc_base[key] = self.camera.get(key)
                except Exception:
                    pass
        self._mc_led_color = self.led_panel.panels[0].color()
        self._nextChannel()
        return True

    def _nextChannel(self) -> None:
        """Přepne na další kanál, nebo cyklus ukončí."""
        if not self._mc_queue:
            self._finishChannelCycle()
            return
        self._mc_channel = self._mc_queue.pop(0)
        settings = self.df_panel.settings(self._darkFieldRoi())
        self._applyChannel(self._mc_channel, settings)
        # Po přepnutí barvy i expozice musí projít pár snímků, než se to
        # v obrazu projeví – teprve pak má smysl měřit.
        QTimer.singleShot(max(50, int(settings.settle_ms)), self._armChannel)

    def _applyChannel(self, channel: str, settings) -> None:
        """Rozsvítí kanál a nastaví jeho expozici a ostření."""
        self.led_panel.setAllColor(darkfield.CHANNEL_COLORS[channel])
        base = self._mc_base
        if "expotime" in base and "expotime" in self.specs:
            scale = float(settings.exposure_scale.get(channel, 1.0))
            self._setClamped("expotime", int(round(base["expotime"] * scale)))
        offset = int(settings.focus_offset.get(channel, 0))
        if offset and "afposition" in base and "afposition" in self.specs:
            self._setClamped("afposition", base["afposition"] + offset)

    def _setClamped(self, key: str, value: int) -> None:
        spec = self.specs.get(key)
        if spec is not None:
            value = max(spec.minimum, min(int(value), spec.maximum))
        try:
            self.camera.set(key, int(value))
        except Exception:
            pass

    def _armChannel(self) -> None:
        """Osvětlení i expozice se ustálily – teď se snímá."""
        if not self._mc_mode:
            return
        if self._mc_mode == "bias":
            self._df_last_bias_frame = 0.0
            self.df_runner.startBias(self._bias_frames)
        else:
            self._armStack()

    def _finishChannelCycle(self) -> None:
        """Vrátí expozici, ostření i barvu osvětlení do původního stavu."""
        mode, self._mc_mode = self._mc_mode, ""
        self._mc_channel = ""
        for key, value in self._mc_base.items():
            self._setClamped(key, value)
        if self._mc_led_color is not None:
            self.led_panel.setAllColor(self._mc_led_color)
            self._mc_led_color = None
        self._loadValues()
        if mode == "bias":
            self.statusMessage("Reference pořízena pro všechny tři kanály", 5000)
            self._autoSaveBias()

    def _onQueueLimitChanged(self, megabytes: int) -> None:
        """Strop fronty rozboru v paměti; drží se i po zavření aplikace."""
        self.df_runner.max_queued_bytes = max(1, int(megabytes)) * 1024 * 1024
        self.settings.setValue("df_queue_mb", int(megabytes))
        self.statusMessage(
            "Fronta rozboru smí zabrat {} MB (asi {} snímků ve 4K)"
            .format(int(megabytes), max(1, int(megabytes) // 8)), 5000)

    def _onDarkFieldFailed(self, message: str) -> None:
        self._df_pending = False
        self.df_panel.stopMeasuring()
        QMessageBox.warning(self, APP_NAME, f"Rozbor obrazu selhal:\n{message}")

    def _onDarkFieldToggled(self, on: bool, interval: float) -> None:
        if on:
            if self.camera is None or not self.camera.is_running():
                QMessageBox.information(self, APP_NAME,
                                        "Nejdřív připojte kameru a spusťte obraz.")
                self.df_panel.stopMeasuring()
                return
            self._df_store = None
            if self.df_panel.wantsStoredFrames():
                try:
                    self._df_store = darkfield.FrameStore(self._makeDarkFieldDir())
                except OSError as exc:
                    QMessageBox.warning(self, APP_NAME,
                                        f"Složku pro snímky nejde založit:\n{exc}")
                    self.df_panel.stopMeasuring()
                    return
            self.df_panel.setStoreInfo(self._df_store)
            # Každé spuštění začíná s čistou tabulkou i grafem – předchozí
            # řada se uložila při zastavení, takže se nic neztratí.
            self.df_panel.clearSeries()
            self.df_runner.dropped = 0
            if not self.isMonochrome():
                # Z barevného obrazu se šeď počítá průměrem složek; jde to,
                # ale demozaikování přidá šum, který v černobílém režimu není.
                self.statusMessage(
                    "Pozor: kamera snímá barevně. Pro temné pole je přesnější "
                    "černobílý režim (přepínač nahoře).", 8000)
            self.df_timer.start(max(200, int(interval * 1000)))
            self._requestSample()          # první měření hned, ne až za interval
            self.statusMessage(f"Měření kontaminace běží po {interval:g} s", 4000)
        else:
            self.df_timer.stop()
            self._df_pending = False
            self._df_stack_left = 0
            self.df_runner.cancelStack()
            if self._mc_mode:
                self._mc_queue = []
                self._finishChannelCycle()
            self._drainPending()
            self.df_panel.setPendingInfo(0)
            saved = self._autoSaveSeries()
            if saved:
                self.statusMessage("Měření uloženo: " + saved, 8000)
            elif self.df_runner.dropped:
                self.statusMessage(
                    "Měření zastaveno – {} snímků se nestihlo zpracovat."
                    .format(self.df_runner.dropped), 8000)
            else:
                self.statusMessage("Měření kontaminace zastaveno", 3000)
            if self.df_runner.dropped and self._df_store is not None:
                self._offerDroppedReanalysis()

    def _drainPending(self) -> None:
        """Počká, než se dopočítají snímky, které ještě čekají ve frontě.

        Měření se zastavuje, ale zbývající snímky jsou už pořízené – dopočítat
        je stojí jen čas, zatímco zahodit je znamená díru v řadě."""
        pending = self.df_runner.pending
        if pending <= 1:
            return
        dialog = QProgressDialog(
            "Dopočítávám zbývající snímky…", "Zahodit zbytek", 0, pending, self)
        dialog.setWindowTitle(APP_NAME)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        while self.df_runner.pending:
            if dialog.wasCanceled():
                self.df_runner.clearQueue()
                break
            dialog.setValue(pending - self.df_runner.pending)
            dialog.setLabelText("Dopočítávám zbývající snímky… ({})"
                                .format(self.df_runner.pending))
            QApplication.processEvents()
            time.sleep(0.01)
        dialog.close()

    def _offerDroppedReanalysis(self) -> None:
        """Nabídne dopočítání snímků, na které se nevešla fronta.

        Zahodit se snímek může jen při přeplněné frontě; když se přitom
        archivoval na disk, není důvod o to měření přijít."""
        folder = self._df_store.directory
        paths = darkfield.FrameStore.list_frames(folder)
        if not paths:
            return
        answer = QMessageBox.question(
            self, APP_NAME,
            "{} snímků se do fronty nevešlo a rozbor je vynechal.\n\n"
            "Uložené snímky ale na disku jsou – spočítat celé měření znovu "
            "z nich ({} snímků)?".format(self.df_runner.dropped, len(paths)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            self._runReanalysis(paths)

    def _autoSaveSeries(self) -> str:
        """Uloží naměřenou řadu do CSV hned po zastavení měření.

        Ukládá se ke snímkům toho běhu, když se archivovaly; jinak do
        pracovní složky. Chyba zápisu měření nezastaví – jen se ohlásí."""
        folder = (self._df_store.directory if self._df_store is not None
                  else self.save_dir)
        try:
            return self.df_panel.autoSaveSeries(folder)
        except OSError as exc:
            self.statusMessage(f"Tabulku se nepodařilo uložit: {exc}", 8000)
            return ""

    def _biasNote(self) -> str:
        """Jednořádkový popis podmínek, za kterých reference vznikla."""
        parts = [datetime.now().strftime("%d.%m.%Y %H:%M:%S")]
        sample = self.df_panel.sampleLabel()
        if sample:
            parts.append(sample)
        if self.camera is not None:
            for key, title in self.EXPO_WATCHED:
                if key not in self.specs:
                    continue
                try:
                    parts.append(f"{title} {self.camera.get(key)}")
                except Exception:
                    pass
        leds = self.led_panel.workspaceSettings()
        parts.append("osvětlení {} ({})".format(
            leds.get("master_brightness"),
            "zap" if leds.get("master_on") else "vyp"))
        settings = self.df_panel.settings(self._darkFieldRoi())
        parts.append("práh {} {:g}".format(
            settings.threshold_mode,
            settings.sigma if settings.threshold_mode == darkfield.THRESHOLD_SIGMA
            else settings.absolute))
        return " · ".join(str(p) for p in parts)

    def _autoSaveBias(self) -> None:
        """Uloží referenci hned po pořízení, i s popisem nastavení.

        Reference bez záznamu expozice a osvětlení se za týden nedá
        použít, proto se vedle .npz ukládá i celé nastavení v JSON."""
        bias = self.df_panel.bias
        if not bias:
            return
        folder = os.path.join(self._ensureDir(), "reference")
        stamp = self._stamp()
        note = self._biasNote()
        try:
            os.makedirs(folder, exist_ok=True)
            tag = self.df_panel.sampleTag()
            suffix = f"_{tag}" if tag else ""
            path = os.path.join(folder, f"reference_{stamp}{suffix}.npz")
            bias.save(path, note)
            data = workspace.new(
                camera=self._cameraSettings(),
                leds=self.led_panel.workspaceSettings(),
                darkfield=self.df_panel.settings(self._darkFieldRoi()).to_dict(),
                capture=self._captureSettings())
            data["reference"] = {"file": os.path.basename(path), "note": note,
                                 "describe": bias.describe()}
            workspace.save(
                os.path.join(folder, f"reference_{stamp}{suffix}.json"), data)
        except (OSError, ValueError) as exc:
            self.statusMessage(f"Referenci se nepodařilo uložit: {exc}", 8000)
            return
        self.statusMessage("Reference uložena: " + path, 8000)

    def _makeDarkFieldDir(self) -> str:
        """Každé měření dostane vlastní podsložku – stejně jako časosběr.

        V názvu je i vzorek (materiál a teplota), aby se složky daly
        rozeznat bez otevírání."""
        tag = self.df_panel.sampleTag()
        name = f"darkfield_{self._stamp()}" + (f"_{tag}" if tag else "")
        base = os.path.join(self._ensureDir(), name)
        folder, index = base, 2
        while os.path.exists(folder):
            folder = f"{base}_{index}"
            index += 1
        os.makedirs(folder)
        return folder

    def _requestSample(self, announce: bool = False) -> None:
        """Označí, že se má vyhodnotit nejbližší příchozí snímek."""
        if self.camera is None or not self.camera.is_running():
            if announce:
                QMessageBox.information(self, APP_NAME,
                                        "Není k dispozici žádný obraz.")
            return
        if self._df_stack_left:
            return              # předchozí dávka se ještě sbírá, tenhle tik vynecháme
        if self.df_panel.isMultichannel():
            if self._mc_mode:
                return          # předchozí cyklus ještě běží, tenhle vynecháme
            self._startChannelCycle("measure")
            return
        self._armStack()

    def _armStack(self) -> None:
        """Otevře novou dávku dílčích snímků pro jedno měření."""
        self._df_stack_left = max(1, self.df_panel.stackFrames())
        self._df_stack_last = 0.0
        self._df_pending = True

    def _stackStep(self) -> float:
        """Rozestup dílčích snímků – interval rozdělený mezi ně."""
        count = max(1, self.df_panel.stackFrames())
        if count <= 1:
            return 0.0
        return max(0.05, self.df_panel.spin_interval.value() / count)

    def _darkFieldFrame(self, frame) -> None:
        """Předá snímek k rozboru do vlákna.

        Tady, ve vlákně GUI, se udělá jen šedotónová kopie – data snímku
        platí jen do příchodu dalšího, takže je nejde vlákna nechat číst
        přímo. Všechno ostatní (medián, prahování, zápis na disk) běží
        až tam."""
        collecting = self.df_runner.collecting_bias
        if collecting:
            if self.df_runner.busy:
                return                      # reference se sbírá po jednom

            # Reference se sbírá po dávkách, ne z každého snímku za sebou –
            # jinak by okno na dobu snímání ztuhlo.
            now = time.time()
            if now - self._df_last_bias_frame < 0.1:
                return
            self._df_last_bias_frame = now
        elif not self._df_pending:
            return
        else:
            # Dílčí snímky se sbírají po celý interval, ne co nejrychleji –
            # jinak by průměr popsal jediný okamžik místo celého intervalu.
            step = self._stackStep()
            if step and time.time() - self._df_stack_last < step:
                return

        try:
            gray = darkfield.to_gray_u8(
                frame, getattr(self.camera, "pixel_order", "rgb"))
        except Exception as exc:                       # noqa: BLE001
            self._df_pending = False
            self.df_runner.cancelBias()
            self.statusMessage(f"Rozbor obrazu selhal: {exc}")
            return

        settings = self.df_panel.settings(self._darkFieldRoi())
        # Do archivu jde vždycky celý snímek, ne jen výřez – zpětný rozbor
        # si pak může vybrat jinou oblast.
        store = None if collecting else self._df_store
        bias = self.df_panel.bias.get(self._mc_channel)
        if self.df_runner.submit(gray, bias, settings, datetime.now(), store,
                                 self._mc_channel):
            if not collecting:
                self._df_stack_last = time.time()
                self._df_stack_left = max(0, self._df_stack_left - 1)
                self._df_pending = self._df_stack_left > 0

    def reanalyzeDarkField(self) -> None:
        """Spočítá měření znovu ze snímků uložených na disku."""
        start = (self._df_store.directory if self._df_store is not None
                 else self._ensureDir())
        folder = QFileDialog.getExistingDirectory(
            self, "Složka se snímky měření", start)
        if not folder:
            return
        paths = darkfield.FrameStore.list_frames(folder)
        if not paths:
            QMessageBox.information(
                self, APP_NAME,
                "V té složce nejsou žádné uložené snímky měření.\n\n"
                "Ukládají se jen tehdy, když je při měření zapnuté "
                "„Ukládat snímky pro zpětný rozbor“.")
            return
        if len(self.df_panel.series):
            answer = QMessageBox.question(
                self, APP_NAME,
                "Současná tabulka ({} měření) se nahradí novým rozborem "
                "{} snímků. Pokračovat?".format(len(self.df_panel.series),
                                                len(paths)),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return

        self._runReanalysis(paths)

    def _runReanalysis(self, paths) -> None:
        """Spočítá řadu ze zadaných souborů a nahradí jí tabulku."""
        dialog = QProgressDialog("Počítám znovu…", "Zrušit", 0, len(paths), self)
        dialog.setWindowTitle(APP_NAME)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)

        def progress(done: int, total: int) -> bool:
            dialog.setValue(done)
            dialog.setLabelText(f"Počítám znovu… {done}/{total}")
            QApplication.processEvents()
            return not dialog.wasCanceled()

        settings = self.df_panel.settings(self._darkFieldRoi())
        try:
            series = darkfield.reanalyze(paths, self.df_panel.bias, settings,
                                         progress)
        except (ValueError, OSError) as exc:
            dialog.close()
            QMessageBox.warning(self, APP_NAME,
                                f"Zpětný rozbor selhal:\n{exc}")
            return
        dialog.close()
        self.df_panel.setSeries(series)
        self.statusMessage(f"Zpětně vyhodnoceno {len(series)} snímků", 6000)
        self.df_panel.showTable()

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

    def setMonochrome(self, mono: bool) -> None:
        """Přepne kameru mezi barevným a černobílým obrazem."""
        if self.camera is None or "chrome" not in self.specs:
            self.statusMessage("Kamera přepínání barevného režimu nenabízí.", 5000)
            return
        try:
            self.camera.set("chrome", 1 if mono else 0)
        except CameraError as exc:
            self.statusMessage(f"Barevný režim: {exc}", 6000)
            return
        self._loadValues()
        self.statusMessage("Obraz: " + ("černobílý" if mono else "barevný"), 4000)

    def isMonochrome(self) -> bool:
        if self.camera is None or "chrome" not in self.specs:
            return False
        try:
            return bool(self.camera.get("chrome"))
        except Exception:                                  # noqa: BLE001
            return False

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
        if not self._allowStreamRestart("Rozlišení"):
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
        if not self._allowStreamRestart("Kodek"):
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

    def snapshot(self, silent: bool = False, directory: Optional[str] = None,
                 name: Optional[str] = None) -> Optional[str]:
        """Uloží snímek; ve výchozím stavu do pracovní složky."""
        if not self.view.hasImage():
            if not silent:
                QMessageBox.information(self, APP_NAME, "Není k dispozici žádný obraz.")
            return None
        image = self.view.image().copy()
        folder = directory or self._ensureDir()
        path = os.path.join(folder, name or f"snimek_{self._stamp()}.jpg")
        if image.save(path, quality=95):
            if directory is None:
                self.statusMessage(f"Uloženo: {os.path.basename(path)}")
            return path
        if not silent:
            QMessageBox.warning(self, APP_NAME, f"Snímek se nepodařilo uložit:\n{path}")
        return None

    def isRecording(self) -> bool:
        return self._recording_since is not None

    def _allowStreamRestart(self, what: str) -> bool:
        """Během nahrávání nesmí dojít k zastavení streamu.

        Zastavení by SDK přerušilo zápis a soubor by zůstal nedokončený –
        bez rejstříku, tedy nepřehratelný."""
        if not self.isRecording():
            return True
        QMessageBox.information(
            self, APP_NAME,
            f"{what} nelze měnit během nahrávání – záznam by zůstal "
            "nedokončený a nešel by přehrát.\n\nNejdřív zastavte nahrávání.")
        self._fillResolutions()
        return False

    def toggleRecord(self) -> None:
        if self.camera is None:
            return
        if self.isRecording():
            self.stopRecording()
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
        path = self._fixVideoSuffix(path)
        if not self._enoughFreeSpace(os.path.dirname(path) or ".", 1000):
            return
        try:
            self.camera.record_start(path)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME,
                                f"Nahrávání se nepodařilo spustit:\n{exc}")
            return
        self._record_path = path
        self._recording_since = time.time()
        self.btn_record.setText("Zastavit nahrávání")

    def _enoughFreeSpace(self, folder: str, need_mb: int) -> bool:
        """Varuje, když na disku dochází místo.

        Zaplněný disk je nejtišší způsob, jak přijít o záznam: zápis se
        zastaví uprostřed, rejstřík se nedopíše a soubor nejde přehrát."""
        try:
            free_mb = shutil.disk_usage(folder).free / 1e6
        except OSError:
            return True
        if free_mb >= need_mb:
            return True
        answer = QMessageBox.question(
            self, APP_NAME,
            f"Na disku zbývá jen {free_mb:.0f} MB.\n\n"
            "Když místo dojde uprostřed nahrávání, soubor zůstane "
            "nedokončený a nepůjde přehrát. Pokračovat?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    @staticmethod
    def _fixVideoSuffix(path: str) -> str:
        """SDK pozná kontejner jen podle přípony – vynutí ji.

        Bez známé přípony se zapíše soubor, který pak neotevře žádný
        přehrávač."""
        if videocheck.suffix_is_supported(path):
            return path
        base = os.path.splitext(path)[0] if os.path.splitext(path)[1] else path
        return base + ".mp4"

    def stopRecording(self, verify: bool = True) -> None:
        """Ukončí záznam a ověří, že vznikl použitelný soubor."""
        if not self.isRecording():
            return
        path, self._record_path = self._record_path, None
        self._recording_since = None
        self.btn_record.setText("Nahrát video")
        self.view.set_recording(None)
        try:
            self.camera.record_stop()
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME,
                                f"Nahrávání se nepodařilo ukončit:\n{exc}")
            return
        if not verify or not path:
            self.statusMessage("Nahrávání ukončeno", 3000)
            return
        report = videocheck.inspect(path)
        if report.problem or report.complete is False or \
                report.playable_in_windows is False:
            self._showVideoReport(report)
        else:
            self.statusMessage(
                "Uloženo: {} ({:.1f} MB)".format(os.path.basename(path),
                                                 report.size / 1e6), 6000)

    def _showVideoReport(self, report: "videocheck.VideoReport") -> None:
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        broken = bool(report.problem) or report.complete is False
        box.setIcon(QMessageBox.Warning if broken else QMessageBox.Information)
        box.setText(os.path.basename(report.path))
        box.setInformativeText(report.verdict())
        box.setDetailedText("\n".join(report.lines()))
        box.exec_()

    # ================================================= kontrola expozice ===
    #: co se při kontrole sleduje – klíč vlastnosti a popisek
    EXPO_WATCHED = (("aexpo", "automatika expozice"), ("expotime", "expoziční čas"),
                    ("again", "zisk"), ("aexpotarget", "cílový jas AE"),
                    ("light", "jas zdroje světla"))

    def checkExposure(self, seconds: float = 10.0) -> Optional[str]:
        """Ověří, jestli kameře nekolísá jas, když má být expozice ruční.

        Hlavičkový soubor SDK zná jediný přepínač automatiky
        (UVCHAM_AEXPO) a aplikace do něj sama nesahá. To ale neříká nic
        o tom, co si dělá firmware kamery – a to jde zjistit jen měřením.
        Proto se tady po zadanou dobu čtou hodnoty zpátky z kamery a
        zároveň se sleduje střední jas obrazu."""
        if self.camera is None or not self.camera.is_running():
            QMessageBox.information(self, APP_NAME,
                                    "Nejdřív připojte kameru a spusťte obraz.")
            return None

        watched = [(key, title) for key, title in self.EXPO_WATCHED
                   if key in self.specs]
        first, changes = {}, {}
        levels = []

        dialog = QProgressDialog("Sleduji expozici…", "Zrušit", 0, 100, self)
        dialog.setWindowTitle(APP_NAME)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        deadline = time.time() + max(2.0, float(seconds))
        began = time.time()
        try:
            while time.time() < deadline and not dialog.wasCanceled():
                for key, _ in watched:
                    try:
                        value = self.camera.get(key)
                    except Exception:
                        continue
                    if key not in first:
                        first[key] = value
                    elif value != first[key]:
                        changes.setdefault(key, set()).add(value)
                frame = self.camera.pull()
                if frame is not None:
                    try:
                        gray = darkfield.to_gray_u8(
                            frame, getattr(self.camera, "pixel_order", "rgb"))
                        levels.append(float(gray[::8, ::8].mean()))
                    except Exception:
                        pass
                elapsed = time.time() - began
                dialog.setValue(int(100 * elapsed / (deadline - began)))
                QApplication.processEvents()
                time.sleep(0.1)
        finally:
            dialog.close()

        report = self._exposureReport(watched, first, changes, levels)
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Information)
        box.setText(report[0])
        box.setInformativeText(report[1])
        box.setDetailedText(report[2])
        box.exec_()
        return report[1]

    @staticmethod
    def _exposureReport(watched, first, changes, levels):
        """Sestaví (nadpis, závěr, podrobnosti) z naměřených hodnot."""
        lines = []
        for key, title in watched:
            if key not in first:
                lines.append(f"{title}: kamera hodnotu nehlásí")
            elif key in changes:
                seen = ", ".join(str(v) for v in sorted(changes[key]))
                lines.append(f"{title}: MĚNILA SE ({first[key]} → {seen})")
            else:
                lines.append(f"{title}: stálá na {first[key]}")

        drift = 0.0
        if levels:
            drift = max(levels) - min(levels)
            lines.append("")
            lines.append("Střední jas obrazu: {} vzorků, {:.2f} až {:.2f} ADU, "
                         "rozkmit {:.2f}".format(len(levels), min(levels),
                                                 max(levels), drift))

        auto_on = first.get("aexpo", 0)
        moved = [title for key, title in watched if key in changes]
        if auto_on:
            head = "Automatika expozice je zapnutá."
            verdict = ("Kamera si expozici řídí sama – to je v pořádku pro "
                       "běžné pozorování, ale pro měření kontaminace ji vypněte "
                       "(záložka Expozice → Automatická expozice).")
        elif moved:
            head = "Něco mění nastavení expozice na pozadí."
            verdict = ("Přestože je automatika vypnutá, změnilo se: "
                       + ", ".join(moved)
                       + ". Měření, které porovnává snímky mezi sebou, tím "
                         "utrpí. Podívejte se do podrobností, která hodnota "
                         "utíká.")
        elif drift > 2.0:
            head = "Hodnoty drží, ale jas obrazu kolísá."
            verdict = ("Nastavení expozice se nezměnilo, přesto se střední "
                       "jas pohnul o {:.2f} ADU. To bývá skutečná změna scény "
                       "nebo osvětlení – zkontrolujte, že LED svítí stabilně "
                       "a že do mikroskopu nejde okolní světlo.".format(drift))
        else:
            head = "Expozice je stabilní."
            verdict = ("Za dobu sledování se nezměnila žádná sledovaná hodnota "
                       "a jas obrazu se držel v rozkmitu {:.2f} ADU. Nic na "
                       "pozadí expozici nedorovnává.".format(drift))
        return head, verdict, "\n".join(lines)

    def checkVideo(self) -> None:
        """Rozbor libovolného nahraného souboru (nabídka ☰)."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Zkontrolovat video", self.save_dir,
            "Video (*.mp4 *.mkv *.asf);;Všechny soubory (*)")
        if path:
            self._showVideoReport(videocheck.inspect(path))

    def toggleTimelapse(self, on: bool) -> None:
        if on:
            self.settings.setValue("timelapse_interval", self.spin_interval.value())
            self._timelapse_count = 0
            try:
                self._timelapse_dir = self._makeTimelapseDir()
            except OSError as exc:
                self.btn_timelapse.setChecked(False)
                QMessageBox.warning(self, APP_NAME,
                                    f"Složku pro časosběr nelze vytvořit:\n{exc}")
                return
            self.timelapse_timer.start(self.spin_interval.value() * 1000)
            self.btn_timelapse.setText("Zastavit časosběr")
            self.statusMessage("Časosběr ukládá do složky "
                               + os.path.basename(self._timelapse_dir), 6000)
        else:
            self.timelapse_timer.stop()
            self.btn_timelapse.setText("Časosběr")
            folder, self._timelapse_dir = self._timelapse_dir, None
            if folder is not None:
                if self._timelapse_count:
                    self.statusMessage(
                        f"Časosběr ukončen: {self._timelapse_count} snímků ve složce "
                        + os.path.basename(folder), 8000)
                else:
                    # prázdnou složku po sobě neuklízíme jen tak – jen když
                    # do ní opravdu nic nespadlo
                    try:
                        os.rmdir(folder)
                    except OSError:
                        pass

    def _makeTimelapseDir(self) -> str:
        """Každý časosběr dostane vlastní podsložku, ať se snímky nemíchají."""
        base = os.path.join(self._ensureDir(), f"casosber_{self._stamp()}")
        folder, index = base, 2
        while os.path.exists(folder):        # dvakrát ve stejné vteřině
            folder = f"{base}_{index}"
            index += 1
        os.makedirs(folder)
        return folder

    def _onTimelapse(self) -> None:
        name = f"snimek_{self._timelapse_count + 1:04d}_{self._stamp()}.jpg"
        if self.snapshot(silent=True, directory=self._timelapse_dir, name=name):
            self._timelapse_count += 1
            self.statusMessage(f"Časosběr: uloženo {self._timelapse_count} snímků "
                               "do " + os.path.basename(self._timelapse_dir or ""),
                               3000)

    def chooseSaveDir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Složka pro ukládání",
                                                self.save_dir)
        if path:
            self.save_dir = path
            self.settings.setValue("save_dir", path)
            self.df_panel.setSaveDir(path)
            self._updateDirLabel()
            self.refreshProfiles()

    def _settingsDir(self) -> str:
        """Podsložka „nastavení“ v pracovní složce; založí se, když chybí."""
        try:
            return workspace.settings_dir(self._ensureDir())
        except OSError:
            return self.save_dir

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
        found = sorted(glob.glob(os.path.join(self._settingsDir(), "*.json")))
        # starší verze ukládaly nastavení přímo do pracovní složky
        found += sorted(glob.glob(os.path.join(self.save_dir, "*.json")))
        for path in found:
            self.cmb_profile.addItem(os.path.splitext(os.path.basename(path))[0], path)
        self.cmb_profile.blockSignals(False)

    def _onProfileSelected(self, index: int) -> None:
        path = self.cmb_profile.itemData(index)
        if path:
            self.applyProfile(path)
        elif self.camera is not None:
            self.resetDefaults()

    def _cameraSettings(self) -> Optional[Dict]:
        """Vlastnosti kamery tak, jak je právě hlásí."""
        if self.camera is None:
            return None
        values = {}
        for key, spec in self.specs.items():
            if spec.kind in (KIND_ACTION, KIND_READONLY) or spec.write_only or spec.hidden:
                continue
            try:
                values[key] = self.camera.get(key)
            except Exception:
                pass
        data = {"backend": self.camera.name, "values": values}
        try:
            index = self.camera.get_resolution()
            data["resolution"] = index
            size = self.camera.resolutions()[index]
            data["resolution_size"] = [size[0], size[1]]
        except Exception:
            pass
        try:
            data["codec"] = self.camera.get_codec()
        except Exception:
            pass
        return data

    def _captureSettings(self) -> Dict:
        return {"save_dir": self.save_dir,
                "timelapse_interval": self.spin_interval.value(),
                "um_per_px": self.view.um_per_px}

    def saveProfile(self) -> None:
        """Uloží celé nastavení – kameru, osvětlení, rozbor i snímání."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Uložit kompletní nastavení",
            workspace.default_name(self._settingsDir()), "JSON (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        data = workspace.new(
            camera=self._cameraSettings(),
            leds=self.led_panel.workspaceSettings(),
            darkfield=self.df_panel.settings(self._darkFieldRoi()).to_dict(),
            capture=self._captureSettings())
        try:
            workspace.save(path, data)
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self.refreshProfiles()
        note = "" if self.camera is not None else " (bez kamery – ta se neuložila)"
        self.statusMessage(f"Nastavení uloženo: {os.path.basename(path)}{note}", 6000)

    def loadProfile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Načíst kompletní nastavení",
                                              self._settingsDir(), "JSON (*.json)")
        if path:
            self.applyProfile(path)

    def applyProfile(self, path: str) -> None:
        """Použije uložené nastavení. Chybějící oddíly se prostě přeskočí."""
        try:
            data = workspace.load(path)
        except workspace.WorkspaceError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return

        done, skipped = [], []

        camera = workspace.section(data, "camera")
        if camera.get("values"):
            if self.camera is None:
                skipped.append("kamera (není připojená)")
            else:
                done.append(self._applyCameraSettings(camera))

        leds = workspace.section(data, "leds")
        if leds:
            self.led_panel.applyWorkspaceSettings(leds)
            done.append("osvětlení" + ("" if self.led_panel.link.is_open()
                                       else " (deska nepřipojena, jen ovládání)"))

        dark = workspace.section(data, "darkfield")
        if dark:
            self.df_panel.applySettings(dark)
            done.append("Dark Field")

        capture = workspace.section(data, "capture")
        if capture:
            self._applyCaptureSettings(capture)
            done.append("snímání")

        message = "Načteno z „{}“: {}".format(os.path.basename(path),
                                              ", ".join(done) or "nic známého")
        if skipped:
            message += " · přeskočeno: " + ", ".join(skipped)
        self.statusMessage(message, 8000)

    def _applyCameraSettings(self, camera: Dict) -> str:
        """Nastaví kameru; vrátí popis pro hlášku."""
        # Rozlišení a kodek jdou měnit jen při zastaveném streamu, takže se
        # musí vyřídit dřív než vlastnosti – jinak by se stream restartoval
        # až po nich a část nastavení by se ztratila.
        if not self.isRecording():
            for key, setter in (("resolution", self.camera.set_resolution),
                                ("codec", self.camera.set_codec)):
                if key not in camera:
                    continue
                try:
                    if int(camera[key]) != (self.camera.get_resolution()
                                            if key == "resolution"
                                            else self.camera.get_codec()):
                        self._restartWith(setter, int(camera[key]))
                except Exception:
                    pass

        failed = []
        for key, value in (camera.get("values") or {}).items():
            if key not in self.specs:
                failed.append(key)
                continue
            try:
                self.camera.set(key, int(value))
            except Exception:
                failed.append(key)
        self._loadValues()
        self._fillResolutions()
        text = "kamera ({} vlastností)".format(
            len(camera.get("values") or {}) - len(failed))
        if failed:
            text += ", nepoužito: " + ", ".join(sorted(failed))
        return text

    def _restartWith(self, setter, value: int) -> None:
        """Zastaví stream, něco přenastaví a zase ho spustí."""
        running = self.camera.is_running()
        if running:
            self.camera.stop()
        setter(value)
        if running:
            self.camera.start(self._sdkCallback)

    def _applyCaptureSettings(self, capture: Dict) -> None:
        if capture.get("save_dir"):
            self.save_dir = str(capture["save_dir"])
            self.settings.setValue("save_dir", self.save_dir)
            self.df_panel.setSaveDir(self.save_dir)
            self._updateDirLabel()
            self.refreshProfiles()
        if "timelapse_interval" in capture:
            try:
                self.spin_interval.setValue(int(capture["timelapse_interval"]))
            except (TypeError, ValueError):
                pass
        scale = capture.get("um_per_px")
        if scale:
            try:
                self.view.um_per_px = float(scale)
            except (TypeError, ValueError):
                pass
            else:
                self.settings.setValue("um_per_px", self.view.um_per_px)
                self.df_panel.setScaleInfo(self.view.um_per_px)

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

    def toggleDarkMode(self) -> None:
        """Přepne světlý a tmavý vzhled aplikace."""
        self.setDarkMode(theme.mode() != "dark")

    def setDarkMode(self, dark: bool) -> None:
        if not theme.set_mode("dark" if dark else "light"):
            return
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet())
        theme.refresh()              # widgety s vlastním stylopisem
        self._updateDarkButton()
        if self.act_dark.isChecked() != dark:
            self.act_dark.blockSignals(True)
            self.act_dark.setChecked(dark)
            self.act_dark.blockSignals(False)
        self.settings.setValue("dark_mode", dark)
        self.view.update()
        self.statusMessage("Vzhled: " + ("tmavý" if dark else "světlý"), 3000)

    def _onStageLight(self, light: bool) -> None:
        self.view.set_light_stage(light)
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
            self.df_panel.setScaleInfo(self.view.um_per_px)
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
        self.df_timer.stop()
        self.df_runner.shutdown()
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
        ("Světlý / tmavý vzhled", "Ctrl+D"),
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
