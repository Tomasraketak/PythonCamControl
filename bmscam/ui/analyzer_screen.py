"""Obrazovka „Analýza“ – dávkové vyhodnocení nafocených sérií.

Portováno z aplikace DarkFieldAnalyzer (`gui.py`, revize 5353d84) do
PyQt5 a do vzhledu BMS Cam Control. Výpočty se nekopírovaly: volá se
přímo převzaté jádro v :mod:`bmscam.dfa`, takže obě aplikace dají na
stejných datech stejná čísla.

Obrazovka umí totéž co původní program:

* vybrat složku s měřením (nebo celý strom podsložek),
* zvolit referenční pozadí – z prvních snímků série, nebo ze souborů
  `reference/*.npz`, které ukládá záznamová část této aplikace,
* srovnat drift sklíčka podle „souhvězdí“ prachových částic,
* nastavit všechny prahy analýzy,
* projít výsledek snímek po snímku s barevnou klasifikační maskou,
* uložit tabulku CSV, souhrn JSON a souhrnné grafy,
* načíst dřív uloženou analýzu (CSV) bez opakovaného počítání,
* přečíst si výklad metody.
"""

import csv
import os
import traceback
from datetime import datetime
from typing import List, Optional, Tuple

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                             QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel,
                             QMessageBox, QProgressBar, QScrollArea, QSpinBox,
                             QSplitter, QTabWidget, QTableWidget,
                             QTableWidgetItem, QTextBrowser, QVBoxLayout,
                             QWidget)

from .. import workspace
from ..dfa import analyzer as core
from ..dfa import exporter, frameio, help_text, reference as refmod
from . import theme
from .dfa_viewer import ImageViewerWidget
from .widgets import Card, button, label, row

#: volby převodu barevného snímku na intenzitu (stejné jako v původní aplikaci)
MONO_CHOICES = (
    ("luma", "Vážený jas – Rec.601 (doporučeno)"),
    ("prumer", "Průměr kanálů"),
    ("maximum", "Maximum kanálů"),
    ("r", "Jen červený kanál"),
    ("g", "Jen zelený kanál"),
    ("b", "Jen modrý kanál"),
)

BINNING_CHOICES = ((0, "Automaticky (doporučeno)"), (1, "Plné rozlišení"),
                   (2, "Poloviční – binning 2×2"), (4, "Čtvrtinové – binning 4×4"))

REFERENCE_CHOICES = (("auto", "Automaticky (reference, jinak série)"),
                     ("reference", "Jen ze složky reference"),
                     ("serie", "Jen z prvních snímků série"))

CROP_CHOICES = (("auto", "podle driftu"), ("fixed", "pevných 90 %"), ("none", "žádný"))


class AnalysisWorker(QThread):
    """Analýza série ve vlastním vlákně, aby okno nezamrzlo."""

    progress_signal = pyqtSignal(int, int, object)
    finished_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str, str)

    def __init__(self, image_paths: List[str], params):
        super().__init__()
        self.image_paths = image_paths
        self.params = params
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:                                   # pragma: no cover
        try:
            result = core.analyze_series(
                self.image_paths, self.params,
                progress=lambda done, total, metrics:
                    self.progress_signal.emit(done, total, metrics),
                should_cancel=lambda: self._cancelled)
            self.finished_signal.emit(result)
        except Exception as exc:                             # noqa: BLE001
            self.error_signal.emit(str(exc), traceback.format_exc())


class AnalyzerScreen(QWidget):
    """Celá obrazovka analýzy: vlevo nastavení, vpravo výsledky."""

    statusMessage = pyqtSignal(str, int)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.base_dir = str(settings.value("analyzer_base_dir", "")
                            or workspace.default_save_dir())
        self.reference_dir = settings.value("analyzer_reference_dir", "") or ""
        self.selected_folder: Optional[str] = None
        self.result = None
        self.worker: Optional[AnalysisWorker] = None
        self._build()
        self.refreshFolders()
        self._restore()

    # ---------------------------------------------------------- sestavení ---
    def _build(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_4, theme.SPACE_3,
                                 theme.SPACE_4, theme.SPACE_3)
        outer.setSpacing(theme.SPACE_3)

        split = QSplitter(Qt.Horizontal)
        left = QScrollArea()
        left.setWidgetResizable(True)
        left.setFrameShape(QScrollArea.NoFrame)
        left.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left.setWidget(self._buildControls())
        left.setMinimumWidth(360)
        left.setMaximumWidth(460)
        split.addWidget(left)
        split.addWidget(self._buildTabs())
        split.setStretchFactor(1, 1)
        outer.addWidget(split, 1)

    def _buildControls(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, theme.SPACE_2, 0)
        lay.setSpacing(theme.SPACE_3)

        # --- 1. složka
        card = Card("1 · Složka s měřeními")
        self.lbl_base = label("", "meta")
        self.lbl_base.setWordWrap(True)
        card.add(self.lbl_base)
        btn_browse = button("Vybrat složku…", "secondary", "folder")
        btn_browse.clicked.connect(self.chooseBaseDir)
        btn_reload = button("Obnovit", "secondary", "refresh")
        btn_reload.clicked.connect(self.refreshFolders)
        card.add(row((btn_browse, 2), (btn_reload, 1)))

        self.tbl_folders = QTableWidget(0, 2)
        self.tbl_folders.setHorizontalHeaderLabels(["Měření", "Snímků"])
        self.tbl_folders.verticalHeader().setVisible(False)
        self.tbl_folders.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_folders.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_folders.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl_folders.setMinimumHeight(120)
        from PyQt5.QtWidgets import QHeaderView
        header = self.tbl_folders.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.tbl_folders.setColumnWidth(1, 70)
        self.tbl_folders.itemSelectionChanged.connect(self._onFolderSelected)
        card.add(self.tbl_folders)
        lay.addWidget(card)

        # --- 1b. reference a drift
        card = Card("2 · Referenční pozadí a drift")
        self.cmb_reference = QComboBox()
        for key, title in REFERENCE_CHOICES:
            self.cmb_reference.addItem(title, key)
        self.cmb_reference.setToolTip(
            "Odkud se vezme pozadí. „Reference“ jsou soubory reference/*.npz,\\n"
            "které ukládá záznamová část této aplikace.")
        self.cmb_reference.currentIndexChanged.connect(self.updateReferenceInfo)
        card.add(row(label("Zdroj", "meta"), None, (self.cmb_reference, 3)))

        btn_ref = button("Složka s referencemi…", "secondary", "folder")
        btn_ref.clicked.connect(self.chooseReferenceDir)
        btn_ref_clear = button("Hledat sám", "secondary")
        btn_ref_clear.clicked.connect(self.clearReferenceDir)
        card.add(row((btn_ref, 2), (btn_ref_clear, 1)))
        self.lbl_reference = label("", "meta")
        self.lbl_reference.setWordWrap(True)
        card.add(self.lbl_reference)

        self.chk_align = QCheckBox("Srovnat drift sklíčka / kamery")
        self.chk_align.setChecked(True)
        self.chk_align.setToolTip(
            "Sklíčko se během měření posune o jednotky pixelů. Statické\\n"
            "částice se pak s referencí přestanou krýt a projeví se jako\\n"
            "nová kontaminace. Zarovnání je posune zpět podle „souhvězdí“\\n"
            "prachových částic.")
        card.add(self.chk_align)
        self.cmb_crop = QComboBox()
        for key, title in CROP_CHOICES:
            self.cmb_crop.addItem(title, key)
        self.chk_align.toggled.connect(self.cmb_crop.setEnabled)
        card.add(row(label("Ořez", "meta"), None, (self.cmb_crop, 3)))
        self.chk_rotation = QCheckBox("Odhadovat i pootočení")
        self.chk_rotation.setChecked(True)
        card.add(self.chk_rotation)
        lay.addWidget(card)

        # --- 2. parametry
        card = Card("3 · Parametry analýzy")
        self.cmb_binning = QComboBox()
        for value, title in BINNING_CHOICES:
            self.cmb_binning.addItem(title, value)
        card.add(row(label("Rozlišení", "meta"), None, (self.cmb_binning, 3)))

        self.spin_bias = QSpinBox()
        self.spin_bias.setRange(1, 50)
        self.spin_bias.setValue(3)
        card.add(row(label("Snímků na bias", "meta"), None, self.spin_bias))

        self.cmb_bias_method = QComboBox()
        self.cmb_bias_method.addItem("medián (odolný)", "median")
        self.cmb_bias_method.addItem("průměr", "mean")
        card.add(row(label("Metoda biasu", "meta"), None, (self.cmb_bias_method, 3)))

        self.cmb_mono = QComboBox()
        for key, title in MONO_CHOICES:
            self.cmb_mono.addItem(title, key)
        self.cmb_mono.setToolTip(
            "Týká se jen barevných snímků – černobílé se použijí tak, jak jsou.")
        card.add(row(label("Barvu na jas", "meta"), None, (self.cmb_mono, 3)))

        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("σ nad šumem", "sigma")
        self.cmb_mode.addItem("Pevný práh", "absolute")
        card.add(row(label("Režim prahu", "meta"), None, (self.cmb_mode, 3)))

        self.spin_sigma = self._spin(0.5, 30.0, 4.0, step=0.5)
        card.add(row(label("Sigma [× σ]", "meta"), None, self.spin_sigma))
        self.spin_abs = self._spin(1.0, 255.0, 12.0)
        card.add(row(label("Pevný práh [ADU]", "meta"), None, self.spin_abs))
        self.spin_haze = self._spin(0.5, 60.0, 4.0, step=0.5)
        card.add(row(label("Práh zamlžení [ADU]", "meta"), None, self.spin_haze))
        self.spin_saturation = self._spin(100.0, 255.0, 250.0)
        card.add(row(label("Hotspot od [ADU]", "meta"), None, self.spin_saturation))

        self.spin_min_area = QSpinBox()
        self.spin_min_area.setRange(1, 200)
        self.spin_min_area.setValue(3)
        card.add(row(label("Min. částice [px]", "meta"), None, self.spin_min_area))
        self.spin_cluster = QSpinBox()
        self.spin_cluster.setRange(20, 20000)
        self.spin_cluster.setSingleStep(20)
        self.spin_cluster.setValue(100)
        card.add(row(label("Shluk od [px]", "meta"), None, self.spin_cluster))
        self.spin_aspect = self._spin(1.5, 20.0, 2.8)
        card.add(row(label("Protáhlost vlákna", "meta"), None, self.spin_aspect))
        self.spin_fiber_len = QSpinBox()
        self.spin_fiber_len.setRange(3, 500)
        self.spin_fiber_len.setValue(12)
        card.add(row(label("Min. délka vlákna [px]", "meta"), None, self.spin_fiber_len))
        self.spin_scale = self._spin(0.0, 1000.0, 1.0, decimals=4)
        card.add(row(label("Měřítko [µm/px]", "meta"), None, self.spin_scale))
        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(0, 16)
        self.spin_workers.setValue(0)
        self.spin_workers.setToolTip("0 = automaticky podle počtu jader.")
        card.add(row(label("Vláken CPU", "meta"), None, self.spin_workers))

        self.chk_roi = QCheckBox("Jen výřez (ROI)")
        card.add(self.chk_roi)
        self.spin_roi = []
        roi_row = QHBoxLayout()
        roi_row.setContentsMargins(0, 0, 0, 0)
        roi_row.setSpacing(4)
        for name in ("x", "y", "š", "v"):
            roi_row.addWidget(label(name, "meta"))
            spin = QSpinBox()
            spin.setRange(0, 20000)
            spin.setMinimumWidth(52)
            spin.setEnabled(False)
            roi_row.addWidget(spin, 1)
            self.spin_roi.append(spin)
        self.chk_roi.toggled.connect(
            lambda on: [spin.setEnabled(on) for spin in self.spin_roi])
        card.add(roi_row)

        self.chk_exclude_bias = QCheckBox("Vynechat bias snímky z výsledků")
        self.chk_exclude_bias.setChecked(True)
        self.chk_exclude_bias.setToolTip(
            "Snímky použité pro bias se porovnávají samy se sebou, takže "
            "jejich hodnoty nejsou srovnatelné se zbytkem řady.")
        card.add(self.chk_exclude_bias)

        btn_defaults = button("Obnovit výchozí hodnoty", "ghost", "refresh")
        btn_defaults.clicked.connect(self.resetDefaults)
        card.add(btn_defaults)
        lay.addWidget(card)

        # --- 3. spuštění
        card = Card("4 · Spuštění a export")
        self.btn_start = button("Spustit analýzu", "primary", "aperture")
        self.btn_start.clicked.connect(self.startAnalysis)
        self.btn_stop = button("Zastavit", "secondary")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stopAnalysis)
        card.add(row((self.btn_start, 2), (self.btn_stop, 1)))

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        card.add(self.progress)

        self.btn_export = button("Uložit výsledky…", "secondary", "save")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.exportResults)
        btn_load = button("Načíst hotovou…", "secondary", "folder")
        btn_load.setToolTip("Zobrazí dřív uloženou tabulku CSV bez počítání.")
        btn_load.clicked.connect(self.loadFinished)
        card.add(row((self.btn_export, 1), (btn_load, 1)))

        self.lbl_status = label("Vyberte složku se snímky.", "meta")
        self.lbl_status.setWordWrap(True)
        card.add(self.lbl_status)
        lay.addWidget(card)
        lay.addStretch(1)
        return box

    @staticmethod
    def _spin(low: float, high: float, value: float, step: float = 1.0,
              decimals: int = 2) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin.setKeyboardTracking(False)
        spin.setFixedWidth(96)
        return spin

    def _buildTabs(self) -> QTabWidget:
        self.tabs = QTabWidget()

        self.viewer = ImageViewerWidget()
        self.tabs.addTab(self.viewer, "Snímky")

        self.tbl_results = QTableWidget(0, len(exporter.CSV_COLUMNS))
        self.tbl_results.setHorizontalHeaderLabels(
            [name for name, _, _ in exporter.CSV_COLUMNS])
        self.tbl_results.verticalHeader().setVisible(False)
        self.tbl_results.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabs.addTab(self.tbl_results, "Tabulka")

        self.txt_summary = QTextBrowser()
        self.tabs.addTab(self.txt_summary, "Souhrn")

        graphs = QWidget()
        graph_lay = QVBoxLayout(graphs)
        graph_lay.setContentsMargins(0, 0, 0, 0)
        self.lbl_graphs = QLabel("Grafy se vykreslí po dokončení analýzy.")
        self.lbl_graphs.setAlignment(Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.lbl_graphs)
        graph_lay.addWidget(scroll)
        self.tabs.addTab(graphs, "Grafy")

        self.guide = QTextBrowser()
        self.guide.setOpenExternalLinks(True)
        self.tabs.addTab(self.guide, "Průvodce")
        self._applyDocumentTheme()
        theme.on_change(self._applyDocumentTheme)
        return self.tabs

    def _applyDocumentTheme(self) -> None:
        """Dokumenty (průvodce, souhrn) přebarví podle palety."""
        self.guide.setHtml(theme.document_html(help_text.HELP_HTML))
        if self.result is not None:
            self.fillSummary(self.result)

    @staticmethod
    def _document(html: str) -> str:
        """Souhrn si barvy bere z palety – vlastní žádné nemá."""
        return "<style>{}</style>{}".format(theme.document_css(), html)

    # -------------------------------------------------------------- složky --
    def chooseBaseDir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Složka s měřeními", self.base_dir)
        if folder:
            self.base_dir = folder
            self.settings.setValue("analyzer_base_dir", folder)
            self.refreshFolders()

    def refreshFolders(self) -> None:
        self.lbl_base.setText("Prohledávám: " + self.base_dir)
        self.tbl_folders.setRowCount(0)
        if not os.path.isdir(self.base_dir):
            self.lbl_status.setText("Zvolená složka neexistuje.")
            return
        # Procházení stromu se snímky může na síťovém disku chvíli trvat;
        # chyba čtení (práva, odpojený disk) nesmí obrazovku shodit.
        try:
            folders = frameio.list_measurement_folders(self.base_dir)
        except OSError as exc:
            self.lbl_status.setText(f"Složku nejde přečíst: {exc}")
            return
        for index, (path, count) in enumerate(folders):
            self.tbl_folders.insertRow(index)
            name = os.path.basename(path) or path
            if os.path.normpath(path) == os.path.normpath(self.base_dir):
                name += "  (tato složka)"
            item = QTableWidgetItem(name)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.tbl_folders.setItem(index, 0, item)
            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(Qt.AlignCenter)
            self.tbl_folders.setItem(index, 1, count_item)
        if folders:
            self.tbl_folders.selectRow(0)
            self.lbl_status.setText(f"Nalezeno {len(folders)} složek se snímky.")
        else:
            self.selected_folder = None
            self.lbl_status.setText(
                "V této složce ani v podsložkách nejsou snímky (PNG/TIFF/BMP/JPG).")
        self.updateReferenceInfo()

    def _onFolderSelected(self) -> None:
        # Slot Qt: výjimka odsud by v PyQt5 shodila celou aplikaci.
        try:
            self._selectFolder()
        except Exception as exc:                            # noqa: BLE001
            self.lbl_status.setText(f"Složku nejde vybrat: {exc}")

    def _selectFolder(self) -> None:
        row_index = self.tbl_folders.currentRow()
        item = self.tbl_folders.item(row_index, 0) if row_index >= 0 else None
        if item is not None:
            self.selected_folder = item.data(Qt.UserRole)
            self.lbl_status.setText("Vybráno: " + os.path.basename(self.selected_folder))
        self.updateReferenceInfo()

    # ----------------------------------------------------------- reference --
    def chooseReferenceDir(self) -> None:
        start = self.reference_dir or self.base_dir
        folder = QFileDialog.getExistingDirectory(
            self, "Složka s referencemi (*.npz)", start)
        if folder:
            self.reference_dir = folder
            self.settings.setValue("analyzer_reference_dir", folder)
            self.updateReferenceInfo()

    def clearReferenceDir(self) -> None:
        self.reference_dir = ""
        self.settings.setValue("analyzer_reference_dir", "")
        self.updateReferenceInfo()

    def updateReferenceInfo(self) -> None:
        """Napíše, která reference by se pro vybrané měření použila.

        Celé tělo je odolné vůči výjimkám: běží jako slot Qt a neodchycená
        výjimka ve slotu PyQt5 ukončí celý proces, ne jen tuhle akci."""
        try:
            self.lbl_reference.setText(self._referenceInfo())
        except Exception as exc:                            # noqa: BLE001
            self.lbl_reference.setText(f"Reference nejde přečíst: {exc}")

    def _referenceInfo(self) -> str:
        mode = self.cmb_reference.currentData()
        if mode == "serie":
            return "Pozadí se spočítá z prvních snímků série."
        folder = self.reference_dir or (
            refmod.find_reference_dir(self.selected_folder or self.base_dir) or "")
        if not folder:
            return "Složka s referencemi nenalezena – pozadí se vezme ze série."
        records = refmod.list_references(folder)
        if not records:
            return f"Ve složce {folder} nejsou žádné reference (*.npz)."
        latest = records[-1]
        return "{}: {} referencí, poslední {} ({})".format(
            os.path.basename(folder) or folder, len(records),
            latest.name, latest.label)

    # ---------------------------------------------------------- parametry ---
    def params(self):
        """Parametry analýzy podle ovládacích prvků."""
        roi = None
        if self.chk_roi.isChecked():
            values = [int(spin.value()) for spin in self.spin_roi]
            if values[2] > 0 and values[3] > 0:
                roi = tuple(values)
        return core.AnalysisParams(
            bias_frames=self.spin_bias.value(),
            bias_method=self.cmb_bias_method.currentData(),
            threshold_mode=self.cmb_mode.currentData(),
            sigma=self.spin_sigma.value(),
            absolute_threshold=self.spin_abs.value(),
            haze_threshold=self.spin_haze.value(),
            min_area_px=self.spin_min_area.value(),
            cluster_min_area_px=self.spin_cluster.value(),
            fiber_aspect_ratio=self.spin_aspect.value(),
            fiber_min_length_px=self.spin_fiber_len.value(),
            saturation_adu=self.spin_saturation.value(),
            um_per_px=self.spin_scale.value(),
            binning=self.cmb_binning.currentData(),
            roi=roi,
            workers=self.spin_workers.value(),
            exclude_bias_from_series=self.chk_exclude_bias.isChecked(),
            reference_mode=self.cmb_reference.currentData(),
            reference_dir=self.reference_dir or None,
            mono_mode=self.cmb_mono.currentData(),
            align_frames=self.chk_align.isChecked(),
            align_crop_mode=self.cmb_crop.currentData(),
            align_rotation=self.chk_rotation.isChecked(),
        )

    def resetDefaults(self) -> None:
        defaults = core.AnalysisParams()
        self.spin_bias.setValue(defaults.bias_frames)
        self.spin_sigma.setValue(defaults.sigma)
        self.spin_abs.setValue(defaults.absolute_threshold)
        self.spin_haze.setValue(defaults.haze_threshold)
        self.spin_saturation.setValue(defaults.saturation_adu)
        self.spin_min_area.setValue(defaults.min_area_px)
        self.spin_cluster.setValue(defaults.cluster_min_area_px)
        self.spin_aspect.setValue(defaults.fiber_aspect_ratio)
        self.spin_fiber_len.setValue(defaults.fiber_min_length_px)
        self.spin_scale.setValue(defaults.um_per_px)
        self.spin_workers.setValue(defaults.workers)
        self.cmb_binning.setCurrentIndex(0)
        self.cmb_mode.setCurrentIndex(0)
        self.chk_align.setChecked(defaults.align_frames)
        self.chk_rotation.setChecked(defaults.align_rotation)
        self.chk_exclude_bias.setChecked(defaults.exclude_bias_from_series)
        self.chk_roi.setChecked(False)

    # ------------------------------------------------------------- rozbor ---
    def startAnalysis(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        folder = self.selected_folder
        if not folder or not os.path.isdir(folder):
            QMessageBox.information(self, "Analýza",
                                    "Nejdřív vyberte složku se snímky.")
            return
        paths = frameio.list_image_files(folder)
        if not paths:
            QMessageBox.information(self, "Analýza",
                                    "Ve složce nejsou žádné snímky.")
            return
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lbl_status.setText(f"Počítám {len(paths)} snímků…")
        self.worker = AnalysisWorker(paths, self.params())
        self.worker.progress_signal.connect(self._onProgress)
        self.worker.finished_signal.connect(self._onFinished)
        self.worker.error_signal.connect(self._onError)
        self.worker.start()

    def stopAnalysis(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.lbl_status.setText("Ruším analýzu…")

    def _onProgress(self, done: int, total: int, _metrics) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        self.lbl_status.setText(f"Snímek {done}/{total}")

    def _onError(self, message: str, details: str) -> None:
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        box = QMessageBox(QMessageBox.Critical, "Analýza",
                          f"Analýza selhala:\\n{message}", QMessageBox.Ok, self)
        box.setDetailedText(details)
        box.exec_()

    def _onFinished(self, result) -> None:
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.result = result
        metrics = list(result.metrics)
        self.btn_export.setEnabled(bool(metrics))
        self.fillTable(metrics)
        self.fillSummary(result)
        if result.bias is not None and self.selected_folder:
            paths = frameio.list_image_files(self.selected_folder)
            self.viewer.set_dataset(paths, result.bias, result.params,
                                    result.alignment)
        self.renderGraphs(metrics)
        note = " (zrušeno)" if result.cancelled else ""
        self.lbl_status.setText(
            "Hotovo: {} snímků za {:.1f} s{}".format(
                len(metrics), result.elapsed_s, note))
        self.statusMessage.emit(
            f"Analýza dokončena: {len(metrics)} snímků", 6000)
        if result.warnings:
            QMessageBox.warning(self, "Analýza",
                                "\\n".join(str(w) for w in result.warnings[:8]))

    # ------------------------------------------------------------ výstupy ---
    #: Kolik řádků se do tabulky vypíše. Víc už jen zdržuje – tabulka Qt
    #: staví každou buňku jako samostatný objekt a u dlouhé série by se okno
    #: na několik sekund zaseklo. Celá data jsou v exportu CSV.
    MAX_TABLE_ROWS = 2000

    def fillTable(self, metrics) -> None:
        shown = list(metrics)[: self.MAX_TABLE_ROWS]
        if len(metrics) > len(shown):
            self.lbl_status.setText(
                "V tabulce je prvních {} z {} snímků – celá data uložte do CSV."
                .format(len(shown), len(metrics)))
        metrics = shown
        self.tbl_results.setRowCount(len(metrics))
        for r, item in enumerate(metrics):
            for c, (name, attr, spec) in enumerate(exporter.CSV_COLUMNS):
                if name == "Časové razítko":
                    text = item.timestamp.strftime("%H:%M:%S")
                elif name == "Bias snímek":
                    text = "ano" if item.is_bias_frame else ""
                else:
                    text = exporter._fmt(getattr(item, attr), spec, False)
                cell = QTableWidgetItem(text)
                if c > 3:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_results.setItem(r, c, cell)
        self.tbl_results.resizeColumnsToContents()

    def fillSummary(self, result) -> None:
        data = exporter.summarize(result)
        if not data:
            self.txt_summary.setHtml(self._document("<p>Žádná data.</p>"))
            return
        phases = "".join(f"<li>{name}: <b>{count}</b> snímků</li>"
                         for name, count in data["faze"].items())
        warnings = "".join(f"<li>{item}</li>" for item in data["varovani"]) \
            or "<li>žádná</li>"
        notes = "".join(f"<li>{item}</li>" for item in data.get("poznamky", []))
        bias = result.bias
        if bias is None:
            background = "neznámé"
        elif bias.is_external:
            background = ("reference <b>{}</b> ({}), srovnání úrovně {:+.2f} ADU"
                          .format(os.path.basename(bias.reference_path or ""),
                                  bias.reference_label, bias.level_offset_adu))
        else:
            background = "prvních {} snímků série ({})".format(
                bias.frames_used, result.params.bias_method)
        model = result.alignment
        if model is None:
            drift = "snímky se nesrovnávaly"
        else:
            aligned = sum(1 for m in result.metrics if m.align_ok)
            crop = (", ořez {}×{} px".format(model.crop[2], model.crop[3])
                    if model.crop else "")
            drift = "největší <b>{:.1f} px</b>, zarovnáno {}/{} snímků{}".format(
                model.measured_drift_px, aligned, len(result.metrics), crop)
        self.txt_summary.setHtml(self._document("""
        <h2>Souhrn měření</h2>
        <table cellpadding='6'>
          <tr><td><b>Referenční pozadí</b></td><td>{background}</td></tr>
          <tr><td><b>Drift scény</b></td><td>{drift}</td></tr>
          <tr><td><b>Snímků</b></td><td>{pocet}</td></tr>
          <tr><td><b>Délka měření</b></td><td>{delka:.2f} s</td></tr>
          <tr><td><b>Průměrné pokrytí</b></td><td>{prumer:.3f} %</td></tr>
          <tr><td><b>Maximum pokrytí</b></td><td>{maxi:.3f} % v čase {maxcas:.2f} s</td></tr>
          <tr><td><b>Průměrná čistota</b></td><td>{cistota:.1f} / 100</td></tr>
          <tr><td><b>Částic na začátku → na konci</b></td><td>{zac} → {kon}</td></tr>
          <tr><td><b>Nejrychlejší nárůst</b></td><td>{rust:.3f} %/s</td></tr>
          <tr><td><b>Doba výpočtu</b></td><td>{cas:.2f} s</td></tr>
        </table>
        <h3>Zastoupení fází</h3><ul>{phases}</ul>
        {notes_block}
        <h3>Upozornění</h3><ul>{warnings}</ul>
        """.format(background=background, drift=drift,
                   pocet=data["pocet_snimku"], delka=data["delka_mereni_s"],
                   prumer=data["pokryti_prumer_pct"], maxi=data["pokryti_max_pct"],
                   maxcas=data["pokryti_max_cas_s"],
                   cistota=data["cistota_prumer_pct"],
                   zac=data["castic_na_zacatku"], kon=data["castic_na_konci"],
                   rust=data["max_rychlost_pokryti_pct_s"],
                   cas=data["cas_analyzy_s"], phases=phases,
                   notes_block=("<h3>Poznámky</h3><ul>" + notes + "</ul>") if notes else "",
                   warnings=warnings)))

    def renderGraphs(self, metrics) -> None:
        """Vykreslí souhrnné grafy do obrázku (matplotlib je volitelný)."""
        if not metrics:
            return
        folder = self.selected_folder or self.base_dir
        target = os.path.join(folder, "_grafy_nahled.png")
        try:
            exporter.export_summary_plots(metrics, target)
        except Exception as exc:                            # noqa: BLE001
            self.lbl_graphs.setText(
                "Grafy se nevykreslily: {}\\n\\nTabulka i souhrn fungují dál."
                .format(exc))
            return
        pixmap = QPixmap(target)
        if pixmap.isNull():
            self.lbl_graphs.setText("Grafy se nepodařilo načíst.")
            return
        self.lbl_graphs.setPixmap(
            pixmap.scaledToWidth(min(1200, pixmap.width()),
                                 Qt.SmoothTransformation))
        self.lbl_graphs.setToolTip(target)

    def exportResults(self) -> None:
        if self.result is None or not self.result.metrics:
            return
        folder = self.selected_folder or self.base_dir
        name = os.path.basename(folder) or "mereni"
        default = os.path.join(
            folder, "analyza_{}_{}.csv".format(
                name, datetime.now().strftime("%Y%m%d_%H%M%S")))
        path, _ = QFileDialog.getSaveFileName(
            self, "Uložit výsledky analýzy", default, "CSV (*.csv)")
        if not path:
            return
        try:
            written = exporter.export_all(self.result, path, folder_name=name)
        except Exception as exc:                            # noqa: BLE001
            QMessageBox.warning(self, "Analýza",
                                f"Uložení selhalo:\\n{exc}")
            return
        QMessageBox.information(
            self, "Analýza",
            "Uloženo:\\n" + "\\n".join(str(v) for v in written.values()))

    def loadFinished(self) -> None:
        """Zobrazí dřív uloženou tabulku CSV bez opakovaného počítání."""
        start = self.selected_folder or self.base_dir
        path, _ = QFileDialog.getOpenFileName(
            self, "Načíst hotovou analýzu", start, "CSV (*.csv);;Vše (*)")
        if not path:
            return
        try:
            header, rows = self._readCsv(path)
        except OSError as exc:
            QMessageBox.warning(self, "Analýza", f"Soubor nejde přečíst:\\n{exc}")
            return
        if not rows:
            QMessageBox.information(self, "Analýza",
                                    "V souboru nejsou žádné řádky s daty.")
            return
        self.tbl_results.setColumnCount(len(header))
        self.tbl_results.setHorizontalHeaderLabels(header)
        self.tbl_results.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, text in enumerate(values[:len(header)]):
                self.tbl_results.setItem(r, c, QTableWidgetItem(text))
        self.tbl_results.resizeColumnsToContents()
        self.tabs.setCurrentIndex(1)
        self.lbl_status.setText(
            "Načteno {} řádků z {}".format(len(rows), os.path.basename(path)))
        self.statusMessage.emit("Načtena hotová analýza: "
                                + os.path.basename(path), 6000)

    @staticmethod
    def _readCsv(path: str) -> Tuple[List[str], List[List[str]]]:
        """Přečte CSV z exportu: komentáře přeskočí, vrátí hlavičku a řádky."""
        header: List[str] = []
        rows: List[List[str]] = []
        with open(path, newline="", encoding="utf-8-sig") as handle:
            for values in csv.reader(handle, delimiter=";"):
                if not values or not any(values):
                    continue
                if values[0].startswith("#"):
                    continue
                if not header:
                    header = values
                    continue
                rows.append(values)
        return header, rows

    # ------------------------------------------------------------ paměť ----
    def _restore(self) -> None:
        value = self.settings.value("analyzer_params")
        if not isinstance(value, dict):
            return
        for key, widget in self._persisted().items():
            if key not in value:
                continue
            try:
                if isinstance(widget, QComboBox):
                    index = widget.findData(value[key])
                    widget.setCurrentIndex(index if index >= 0 else 0)
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value[key]))
                else:
                    widget.setValue(type(widget.value())(value[key]))
            except (TypeError, ValueError):
                pass

    def saveState(self) -> None:
        """Uloží nastavení analýzy (volá hlavní okno při zavření)."""
        data = {}
        for key, widget in self._persisted().items():
            if isinstance(widget, QComboBox):
                data[key] = widget.currentData()
            elif isinstance(widget, QCheckBox):
                data[key] = widget.isChecked()
            else:
                data[key] = widget.value()
        self.settings.setValue("analyzer_params", data)

    def _persisted(self):
        return {
            "binning": self.cmb_binning, "bias_frames": self.spin_bias,
            "bias_method": self.cmb_bias_method, "mono": self.cmb_mono,
            "mode": self.cmb_mode, "sigma": self.spin_sigma,
            "absolute": self.spin_abs, "haze": self.spin_haze,
            "saturation": self.spin_saturation, "min_area": self.spin_min_area,
            "cluster": self.spin_cluster, "aspect": self.spin_aspect,
            "fiber_len": self.spin_fiber_len, "scale": self.spin_scale,
            "workers": self.spin_workers, "reference": self.cmb_reference,
            "align": self.chk_align, "crop": self.cmb_crop,
            "rotation": self.chk_rotation, "roi": self.chk_roi,
            "exclude_bias": self.chk_exclude_bias,
        }
