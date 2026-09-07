"""Záložka Dark Field – sledování kontaminace witness sklíčka.

Panel drží nastavení, referenční snímek a naměřenou řadu. Snímky mu
dodává hlavní okno (jen ono má přístup ke kameře), takže tenhle modul
neví nic o SDK a dá se testovat samostatně.
"""

import os
from typing import Dict, List, Optional

from PyQt5.QtCore import QPointF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                             QFileDialog, QHBoxLayout, QHeaderView, QMessageBox,
                             QSizePolicy, QSpinBox, QSplitter, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from .. import darkfield as df
from . import theme
from .widgets import Card, SegmentedControl, button, hline, label, row

#: metriky nabízené v grafu (klíč -> popis)
PLOTTABLE = (
    ("coverage_pct", "Pokrytí plochy [%]"),
    ("particles", "Počet částic"),
    ("area_um2", "Plocha částic [µm²]"),
    ("mean_signal", "Průměrný signál [ADU]"),
    ("max_signal", "Maximum [ADU]"),
)


class TrendChart(QWidget):
    """Jednoduchý spojnicový graf průběhu jedné veličiny."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._times: List[float] = []
        self._values: List[float] = []
        self._lines = []
        self._title = ""

    def setSeries(self, times: List[float], values: List[float], title: str) -> None:
        self.setLines([(times, values, theme.ACCENT, "")], title)

    def setLines(self, lines, title: str) -> None:
        """Několik průběhů najednou – u vícekanálového měření jeden na kanál.

        `lines` je seznam (časy, hodnoty, barva, popisek)."""
        self._lines = [l for l in lines if len(l[1]) >= 1]
        self._title = title
        self._times = self._lines[0][0] if self._lines else []
        self._values = [v for line in self._lines for v in line[1]]
        self.update()

    # ------------------------------------------------------------ kreslení --
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.BG))
        pad_l, pad_r, pad_t, pad_b = 62, 12, 22, 26
        w = max(self.width() - pad_l - pad_r, 10)
        h = max(self.height() - pad_t - pad_b, 10)

        painter.setPen(QPen(QColor(theme.NEUTRAL_700), 1))
        painter.drawText(6, 14, self._title)

        if len(self._values) < 2 or not self._lines:
            painter.setPen(QColor(theme.NEUTRAL_500))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "Zatím není co vykreslit")
            return

        lo, hi = min(self._values), max(self._values)
        if hi - lo < 1e-9:
            hi, lo = hi + 1.0, lo - 1.0
        all_times = [t for line in self._lines for t in line[0]] or [0.0]
        t0, t1 = min(all_times), max(all_times)
        span = max(t1 - t0, 1e-9)

        # osy a vodicí čáry
        painter.setPen(QPen(QColor(theme.NEUTRAL_400), 1, Qt.DotLine))
        for i in range(5):
            y = pad_t + h * i / 4.0
            painter.drawLine(pad_l, int(y), pad_l + w, int(y))
        painter.setPen(QPen(QColor(theme.TEXT), 2))
        painter.drawLine(pad_l, pad_t, pad_l, pad_t + h)
        painter.drawLine(pad_l, pad_t + h, pad_l + w, pad_t + h)

        painter.setPen(QColor(theme.NEUTRAL_700))
        for i in range(5):
            value = hi - (hi - lo) * i / 4.0
            y = pad_t + h * i / 4.0
            painter.drawText(2, int(y) + 4, f"{value:,.3g}".replace(",", " "))
        painter.drawText(pad_l, self.height() - 6, f"{t0:.0f} s")
        painter.drawText(pad_l + w - 46, self.height() - 6, f"{t1:.0f} s")

        painter.setRenderHint(QPainter.Antialiasing, True)
        legend_x = pad_l + 6
        if len(self._lines) > 1:
            names = [l[3] for l in self._lines if l[3]]
            width = sum(painter.fontMetrics().width(n) + 12 for n in names)
            legend_x = max(pad_l + 6, self.width() - pad_r - width)
        for times, values, color, name in self._lines:
            points = QPolygonF()
            for t, value in zip(times, values):
                x = pad_l + w * (t - t0) / span
                y = pad_t + h * (1.0 - (value - lo) / (hi - lo))
                points.append(QPointF(x, y))
            if not points:
                continue
            painter.setPen(QPen(QColor(color), 2))
            if len(points) > 1:
                painter.drawPolyline(points)
            painter.setBrush(QColor(color))
            painter.drawEllipse(points[-1], 3, 3)
            if name:
                # Legenda patří nahoru k názvu – dole se tluče s popisky osy.
                painter.drawText(legend_x, 14, name)
                legend_x += painter.fontMetrics().width(name) + 12


class DarkFieldWindow(QDialog):
    """Okno s tabulkou a grafem průběhu."""

    def __init__(self, panel: "DarkFieldPanel"):
        super().__init__(panel)
        self.panel = panel
        self.setWindowTitle("Průběh kontaminace")
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.resize(920, 620)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SPACE_4, theme.SPACE_4,
                               theme.SPACE_4, theme.SPACE_4)
        lay.setSpacing(theme.SPACE_3)

        head = QHBoxLayout()
        head.addWidget(label("Veličina", "meta"))
        self.cmb_metric = QComboBox()
        for _, title in PLOTTABLE:
            self.cmb_metric.addItem(title)
        self.cmb_metric.currentIndexChanged.connect(self.refresh)
        head.addWidget(self.cmb_metric)
        head.addStretch(1)
        self.chk_follow = QCheckBox("Sledovat poslední řádek")
        self.chk_follow.setChecked(True)
        head.addWidget(self.chk_follow)
        btn_csv = button("Uložit CSV…", "secondary", "save")
        btn_csv.clicked.connect(self.panel.exportCsv)
        head.addWidget(btn_csv)
        btn_clear = button("Vymazat", "secondary")
        btn_clear.clicked.connect(self.panel.clearSeries)
        head.addWidget(btn_clear)
        lay.addLayout(head)

        splitter = QSplitter(Qt.Vertical)
        self.chart = TrendChart()
        splitter.addWidget(self.chart)
        self.table = QTableWidget(0, len(df.COLUMNS))
        self.table.setHorizontalHeaderLabels(
            [f"{title}\n[{unit}]" if unit else title
             for _, title, unit in df.COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        splitter.addWidget(self.table)
        splitter.setSizes([240, 380])
        lay.addWidget(splitter, 1)

        self.lbl_summary = label("", "meta")
        lay.addWidget(self.lbl_summary)
        self.refresh()

    def _fillRow(self, r: int, sample) -> None:
        for c, text in enumerate(sample.as_row()):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, c, item)

    def _afterChange(self) -> None:
        if self.chk_follow.isChecked() and self.panel.series.samples:
            self.table.scrollToBottom()
        self.lbl_summary.setText(self.panel.summaryText())

    def _chartLines(self, series, key):
        """Jedna čára u jednokanálového měření, tři u vícekanálového."""
        channels = series.channels()
        if channels in ([], [""]):
            return [(series.values("time_s"), series.values(key),
                     theme.ACCENT, "")]
        return [(series.values("time_s", c), series.values(key, c),
                 "#{:02x}{:02x}{:02x}".format(*df.CHANNEL_COLORS.get(c, (0, 0, 0))),
                 df.CHANNEL_TITLES.get(c, c)) for c in channels]

    def refresh(self) -> None:
        series = self.panel.series
        key, title = PLOTTABLE[max(0, self.cmb_metric.currentIndex())]
        self.chart.setLines(self._chartLines(series, key), title)
        self.table.setRowCount(len(series.samples))
        for r, sample in enumerate(series.samples):
            self._fillRow(r, sample)
        self._afterChange()

    def appendSample(self) -> None:
        """Doplní jen poslední řádek.

        Přestavovat při každém měření celou tabulku by u dlouhého běhu
        znamenalo kvadraticky rostoucí práci – po tisícovce měření by se
        okno zaseklo právě ve chvíli, kdy jsou data nejzajímavější."""
        series = self.panel.series
        if not series.samples:
            self.refresh()
            return
        key, title = PLOTTABLE[max(0, self.cmb_metric.currentIndex())]
        self.chart.setLines(self._chartLines(series, key), title)
        row_index = self.table.rowCount()
        if row_index != len(series.samples) - 1:
            self.refresh()                 # tabulka se rozešla s daty
            return
        self.table.insertRow(row_index)
        self._fillRow(row_index, series.samples[-1])
        self._afterChange()


class DarkFieldPanel(QWidget):
    """Levý panel záložky Dark Field."""

    #: hlavní okno má pořídit referenční snímek (průměr N snímků)
    biasRequested = pyqtSignal(int)
    #: měření spuštěno / zastaveno (parametr: interval v sekundách)
    measureToggled = pyqtSignal(bool, float)
    #: jednorázové změření právě teď
    sampleRequested = pyqtSignal()
    #: spočítat řadu znovu z uložených snímků
    reanalyzeRequested = pyqtSignal()
    #: uživatel změnil strop fronty v paměti (v MB)
    queueLimitChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bias = df.BiasSet()
        self.series = df.Series()
        self.window_: Optional[DarkFieldWindow] = None
        self._save_dir = os.path.expanduser("~")
        self._build()
        self._updateState()

    # ---------------------------------------------------------- sestavení ---
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, theme.SPACE_1, 0, theme.SPACE_1)
        lay.setSpacing(theme.SPACE_3)

        # --- reference
        card = Card("Referenční snímek")
        self.lbl_bias = label("Není pořízen.", "meta")
        self.lbl_bias.setWordWrap(True)
        card.add(self.lbl_bias)
        self.spin_bias_frames = QSpinBox()
        self.spin_bias_frames.setRange(1, 200)
        self.spin_bias_frames.setValue(16)
        self.spin_bias_frames.setFixedWidth(64)
        card.add(row(label("Průměrovat", "meta"), self.spin_bias_frames,
                     label("snímků", "meta")))
        self.btn_bias = button("Pořídit", "primary")
        self.btn_bias.clicked.connect(
            lambda: self.biasRequested.emit(self.spin_bias_frames.value()))
        btn_load = button("Načíst…", "secondary")
        btn_load.clicked.connect(self.loadBias)
        self.btn_bias_save = button("Uložit…", "secondary")
        self.btn_bias_save.clicked.connect(self.saveBias)
        card.add(row((self.btn_bias, 2), (btn_load, 2), (self.btn_bias_save, 2)))
        lay.addWidget(card)

        # --- nastavení měření
        card = Card("Vyhodnocení")
        self.seg_mode = SegmentedControl(["σ nad šumem", "Pevný práh"],
                                         compact=True)
        self.seg_mode.currentChanged.connect(self._onModeChanged)
        card.add(self.seg_mode)

        self.spin_sigma = QDoubleSpinBox()
        self.spin_sigma.setRange(0.5, 50.0)
        self.spin_sigma.setSingleStep(0.5)
        self.spin_sigma.setDecimals(1)
        self.spin_sigma.setValue(5.0)
        self.spin_sigma.setToolTip(
            "Za kontaminaci se počítá vše, co je o tolik násobků šumu "
            "nad pozadím. Vyšší číslo = přísnější práh.")
        card.add(row(label("Práh (σ)", "meta"), None, self.spin_sigma))

        self.spin_abs = QDoubleSpinBox()
        self.spin_abs.setRange(0.1, 255.0)
        self.spin_abs.setDecimals(1)
        self.spin_abs.setValue(12.0)
        self.spin_abs.setToolTip("Pevný práh v jednotkách jasu nad referencí.")
        card.add(row(label("Práh (ADU)", "meta"), None, self.spin_abs))

        self.spin_minarea = QSpinBox()
        self.spin_minarea.setRange(1, 10000)
        self.spin_minarea.setValue(3)
        self.spin_minarea.setToolTip(
            "Skvrny menší než tato plocha se nepočítají – odfiltruje "
            "to šum jednotlivých pixelů.")
        card.add(row(label("Min. částice", "meta"), None, self.spin_minarea,
                     label("px", "meta")))

        self.chk_multi = QCheckBox("Postupně po kanálech (R → G → B)")
        self.chk_multi.setToolTip(
            "Každé měření pořídí tři snímky – pod červeným, zeleným a modrým\n"
            "světlem. Kamera je černobílá, takže jde o měření ve třech úzkých\n"
            "pásmech. Reference se snímá stejným způsobem.")
        self.chk_multi.toggled.connect(self._onMultiToggled)
        card.add(self.chk_multi)

        head_exp = label("expozice", "meta")
        head_exp.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head_exp.setFixedWidth(72)
        head_focus = label("ostření", "meta")
        head_focus.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head_focus.setFixedWidth(64)
        card.add(row(None, head_exp, head_focus))

        self.channel_rows = {}
        for key in df.CHANNEL_ORDER:
            scale = QDoubleSpinBox()
            scale.setRange(0.05, 20.0)
            scale.setDecimals(2)
            scale.setSingleStep(0.1)
            scale.setValue(1.0)
            scale.setSuffix("×")
            scale.setFixedWidth(72)
            scale.setToolTip(
                "Násobek expozičního času pro tento kanál. Senzor bývá "
                "na modrou méně citlivý než na zelenou, takže se hodí "
                "delší expozice.")
            focus = QSpinBox()
            focus.setRange(-400, 400)
            focus.setValue(0)
            focus.setFixedWidth(64)
            focus.setToolTip(
                "Posun zaostření pro tento kanál v krocích ostřicího motorku.\n"
                "Barvy se lámou různě, takže ostří každá jinde. 0 = neměnit.")
            swatch = label("■", "meta")
            swatch.setStyleSheet("color: rgb({},{},{}); font-size: 15px;"
                                 .format(*df.CHANNEL_COLORS[key]))
            card.add(row(swatch, label(f"{df.CHANNEL_NM[key]} nm", "meta"),
                         None, scale, focus))
            self.channel_rows[key] = (scale, focus)

        self.spin_settle = QDoubleSpinBox()
        self.spin_settle.setRange(0.05, 10.0)
        self.spin_settle.setDecimals(2)
        self.spin_settle.setSingleStep(0.05)
        self.spin_settle.setValue(0.40)
        self.spin_settle.setSuffix(" s")
        self.spin_settle.setFixedWidth(84)
        self.spin_settle.setToolTip(
            "Prodleva po přepnutí barvy a expozice, než se snímek pořídí.\n"
            "Krátká prodleva změří ještě starý obraz – při pochybnostech "
            "prodlužte.")
        card.add(row(label("Ustálení", "meta"), None, self.spin_settle))

        self.chk_roi = QCheckBox("Měřit jen ve vybraném výřezu")
        self.chk_roi.setToolTip(
            "Použije výřez vybraný v obraze (Zobrazení → Výběr oblasti).")
        card.add(self.chk_roi)
        self.lbl_scale = label("", "meta")
        self.lbl_scale.setWordWrap(True)
        card.add(self.lbl_scale)
        lay.addWidget(card)

        # --- běh měření
        card = Card("Měření")
        self.spin_interval = QDoubleSpinBox()
        self.spin_interval.setRange(0.2, 3600.0)
        self.spin_interval.setDecimals(1)
        self.spin_interval.setValue(1.0)
        self.spin_interval.setSuffix(" s")
        self.spin_interval.setFixedWidth(84)
        self.spin_interval.setToolTip(
            "Jak často se měří. Rozbor 4K snímku trvá desetiny sekundy, "
            "takže krátký interval zbytečně zatěžuje počítač – "
            "kontaminace roste v minutách, ne v milisekundách.")
        card.add(row(label("Interval", "meta"), None, self.spin_interval))

        self.chk_store = QCheckBox("Ukládat snímky pro zpětný rozbor")
        self.chk_store.setChecked(True)
        self.chk_store.setToolTip(
            "Každé měření uloží snímek do vlastní podsložky. Rozbor se pak "
            "dá kdykoli zopakovat s jiným prahem, aniž by se muselo měřit "
            "znovu. Snímky zabírají místo na disku – kolik, ukazuje řádek "
            "pod tím.")
        card.add(self.chk_store)
        self.lbl_store = label("", "meta")
        self.lbl_store.setWordWrap(True)
        card.add(self.lbl_store)
        self.spin_queue = QSpinBox()
        self.spin_queue.setRange(64, 32768)
        self.spin_queue.setSingleStep(256)
        self.spin_queue.setValue(3072)
        self.spin_queue.setSuffix(" MB")
        self.spin_queue.setKeyboardTracking(False)
        self.spin_queue.setFixedWidth(96)
        self.spin_queue.setToolTip(
            "Kolik operační paměti smí zabrat fronta čekajících snímků.\n"
            "Jeden 4K snímek je 8 MB, takže 3072 MB vydrží asi 380 snímků –\n"
            "přes šest minut snímání po sekundě. Až se fronta zaplní, snímky\n"
            "se zahazují (a jdou dopočítat z archivu na disku).")
        self.spin_queue.valueChanged.connect(self.queueLimitChanged)
        card.add(row(label("Fronta v paměti", "meta"), None, self.spin_queue))
        self.lbl_pending = label("", "meta")
        self.lbl_pending.setWordWrap(True)
        card.add(self.lbl_pending)

        self.btn_measure = button("Spustit měření", "primary")
        self.btn_measure.setCheckable(True)
        self.btn_measure.toggled.connect(self._onMeasureToggled)
        btn_once = button("Změřit teď", "secondary")
        btn_once.clicked.connect(self.sampleRequested)
        card.add(row((self.btn_measure, 3), (btn_once, 2)))

        self.btn_table = button("Tabulka a graf…", "secondary")
        self.btn_table.clicked.connect(self.showTable)
        btn_csv = button("CSV…", "secondary")
        btn_csv.clicked.connect(self.exportCsv)
        card.add(row((self.btn_table, 3), (btn_csv, 2)))
        btn_again = button("Zpětný rozbor…", "secondary")
        btn_again.setToolTip(
            "Projde uložené snímky znovu s právě nastaveným prahem a "
            "sestaví z nich novou tabulku.")
        btn_again.clicked.connect(self.reanalyzeRequested)
        card.add(btn_again)
        lay.addWidget(card)

        # --- aktuální hodnoty
        card = Card("Poslední měření")
        self.lbl_values = label("Zatím nic naměřeno.", "meta")
        self.lbl_values.setWordWrap(True)
        card.add(self.lbl_values)
        lay.addWidget(card)

        lay.addStretch(1)
        self._onModeChanged(0)

    # -------------------------------------------------------------- stav ---
    def _onModeChanged(self, index: int) -> None:
        self.spin_sigma.setEnabled(index == 0)
        self.spin_abs.setEnabled(index == 1)

    def _onMeasureToggled(self, on: bool) -> None:
        if on and not self.bias:
            answer = QMessageBox.question(
                self, "Dark Field",
                "Není pořízený referenční snímek čistého sklíčka.\n\n"
                "Bez něj se za pozadí bere medián obrazu – měření pak "
                "ukáže jen výrazné částice a ne tenký film. Pokračovat?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                self.btn_measure.setChecked(False)
                return
        self.btn_measure.setText("Zastavit měření" if on else "Spustit měření")
        self.measureToggled.emit(on, self.spin_interval.value())

    def isMeasuring(self) -> bool:
        return self.btn_measure.isChecked()

    def stopMeasuring(self) -> None:
        if self.btn_measure.isChecked():
            self.btn_measure.setChecked(False)

    def setSaveDir(self, path: str) -> None:
        self._save_dir = path

    def setScaleInfo(self, um_per_px: float) -> None:
        self._um_per_px = um_per_px
        if um_per_px and abs(um_per_px - 1.0) > 1e-9:
            self.lbl_scale.setText(
                f"Měřítko {um_per_px:g} µm/px – plocha se přepočítá na µm².")
        else:
            self.lbl_scale.setText("Měřítko není zkalibrováno, plocha bude "
                                   "jen v pixelech (☰ → Kalibrace měřítka).")

    def settings(self, roi=None) -> df.Settings:
        """Nastavení podle ovládacích prvků."""
        return df.Settings(
            interval_s=self.spin_interval.value(),
            threshold_mode=(df.THRESHOLD_SIGMA if self.seg_mode.currentIndex() == 0
                            else df.THRESHOLD_ABSOLUTE),
            sigma=self.spin_sigma.value(),
            absolute=self.spin_abs.value(),
            min_area_px=self.spin_minarea.value(),
            bias_frames=self.spin_bias_frames.value(),
            um_per_px=getattr(self, "_um_per_px", 0.0),
            store_frames=self.chk_store.isChecked(),
            queue_mb=self.spin_queue.value(),
            multichannel=self.chk_multi.isChecked(),
            settle_ms=int(self.spin_settle.value() * 1000),
            exposure_scale={k: w[0].value() for k, w in self.channel_rows.items()},
            focus_offset={k: w[1].value() for k, w in self.channel_rows.items()},
            roi=roi if self.chk_roi.isChecked() else None)

    def isMultichannel(self) -> bool:
        return self.chk_multi.isChecked()

    def _onMultiToggled(self, on: bool) -> None:
        for scale, focus in self.channel_rows.values():
            scale.setEnabled(on)
            focus.setEnabled(on)
        self.spin_settle.setEnabled(on)
        self._updateState()

    def wantsStoredFrames(self) -> bool:
        return self.chk_store.isChecked()

    def setStoreInfo(self, store) -> None:
        """Řádek o tom, kam se snímky ukládají a kolik už zabírají."""
        if store is None:
            self.lbl_store.setText("")
            return
        size = store.bytes_used() / (1024.0 * 1024.0)
        self.lbl_store.setText("{} · {} snímků · {:.1f} MB"
                               .format(os.path.basename(store.directory),
                                       store.count, size))

    def setPendingInfo(self, pending: int) -> None:
        """Kolik snímků čeká na rozbor – aby bylo vidět, že se něco dopočítává."""
        self.lbl_pending.setText(
            "" if pending <= 1 else
            f"Čeká na rozbor: {pending - 1} snímků (dopočítají se se zpožděním)")

    def wantsRoi(self) -> bool:
        return self.chk_roi.isChecked()

    def applySettings(self, data: dict) -> None:
        """Obnoví nastavení rozboru z uloženého souboru.

        Neznámé a nesmyslné hodnoty se přeskočí – soubor mohl vzniknout
        v jiné verzi a kvůli jednomu poli nemá smysl zahodit zbytek."""
        if not isinstance(data, dict):
            return
        pairs = ((self.spin_interval, "interval_s"), (self.spin_sigma, "sigma"),
                 (self.spin_abs, "absolute"), (self.spin_minarea, "min_area_px"),
                 (self.spin_bias_frames, "bias_frames"),
                 (self.spin_queue, "queue_mb"))
        for widget, key in pairs:
            if key in data:
                try:
                    widget.setValue(type(widget.value())(data[key]))
                except (TypeError, ValueError):
                    pass
        mode = data.get("threshold_mode")
        if mode in (df.THRESHOLD_SIGMA, df.THRESHOLD_ABSOLUTE):
            self.seg_mode.setCurrentIndex(0 if mode == df.THRESHOLD_SIGMA else 1)
        if "store_frames" in data:
            self.chk_store.setChecked(bool(data["store_frames"]))
        if "roi" in data:
            self.chk_roi.setChecked(data["roi"] is not None)
        if "multichannel" in data:
            self.chk_multi.setChecked(bool(data["multichannel"]))
        if "settle_ms" in data:
            try:
                self.spin_settle.setValue(float(data["settle_ms"]) / 1000.0)
            except (TypeError, ValueError):
                pass
        for name, position in (("exposure_scale", 0), ("focus_offset", 1)):
            values = data.get(name)
            if not isinstance(values, dict):
                continue
            for key, widget in self.channel_rows.items():
                if key in values:
                    try:
                        widget[position].setValue(
                            type(widget[position].value())(values[key]))
                    except (TypeError, ValueError):
                        pass

    # ----------------------------------------------------------- reference --
    def setBias(self, bias, channel: str = "") -> None:
        """Uloží referenci; u vícekanálového měření pod klíč kanálu."""
        if isinstance(bias, df.BiasSet):
            self.bias = bias
        elif bias is None:
            self.bias = df.BiasSet()
        else:
            self.bias.put(channel, bias)
        self._updateState()

    def missingBias(self):
        """Kanály, ke kterým ještě není reference."""
        if not self.isMultichannel():
            return [] if self.bias.get("") else [""]
        return self.bias.missing(df.CHANNEL_ORDER)

    def setBiasProgress(self, taken: int, total: int) -> None:
        self.lbl_bias.setText(f"Snímám referenci… {taken}/{total}")

    def loadBias(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Načíst referenční snímek", self._save_dir,
            "Reference (*.npz);;Všechny soubory (*)")
        if not path:
            return
        try:
            self.setBias(df.BiasSet.load(path))
        except Exception as exc:                       # noqa: BLE001
            QMessageBox.warning(self, "Dark Field",
                                f"Referenci se nepodařilo načíst:\n{exc}")

    def saveBias(self) -> None:
        if not self.bias:
            return
        default = os.path.join(self._save_dir, "reference.npz")
        path, _ = QFileDialog.getSaveFileName(
            self, "Uložit referenční snímek", default, "Reference (*.npz)")
        if not path:
            return
        if not path.lower().endswith(".npz"):
            path += ".npz"
        try:
            self.bias.save(path)
        except Exception as exc:                       # noqa: BLE001
            QMessageBox.warning(self, "Dark Field",
                                f"Referenci se nepodařilo uložit:\n{exc}")

    # -------------------------------------------------------------- data ---
    def addSample(self, metrics: Dict[str, float], when=None) -> None:
        self.series.add(metrics, when)
        self._updateState()
        if self.window_ is not None and self.window_.isVisible():
            self.window_.appendSample()

    def setSeries(self, series: df.Series) -> None:
        """Nahradí řadu (po zpětném rozboru)."""
        self.series = series
        self._updateState()
        if self.window_ is not None:
            self.window_.refresh()

    def clearSeries(self) -> None:
        self.series.clear()
        self._updateState()
        if self.window_ is not None:
            self.window_.refresh()

    def showTable(self) -> None:
        if self.window_ is None:
            self.window_ = DarkFieldWindow(self)
        self.window_.refresh()
        self.window_.show()
        self.window_.raise_()

    def exportCsv(self) -> None:
        if not len(self.series):
            QMessageBox.information(self, "Dark Field",
                                    "Zatím není co uložit – nic se nezměřilo.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Uložit tabulku", df.default_csv_name(self._save_dir),
            "CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            self.series.to_csv(path, self.settings(), self.bias)
        except OSError as exc:
            QMessageBox.warning(self, "Dark Field",
                                f"Tabulku se nepodařilo uložit:\n{exc}")
            return
        QMessageBox.information(self, "Dark Field",
                                f"Uloženo {len(self.series)} měření do\n{path}")

    def autoSaveSeries(self, folder: str) -> str:
        """Uloží tabulku bez ptaní. Vrací cestu, nebo "" když není co uložit.

        Volá se při zastavení měření – naměřená řada se tím nikdy neztratí,
        i když si uživatel „Uložit CSV…“ nevzpomene."""
        if not len(self.series):
            return ""
        os.makedirs(folder, exist_ok=True)
        path = df.default_csv_name(folder)
        self.series.to_csv(path, self.settings(), self.bias)
        return path

    def summaryText(self) -> str:
        if not len(self.series):
            return "Zatím nic naměřeno."
        channels = self.series.channels()
        if channels not in ([], [""]):
            lines = [f"{len(self.series)} měření ve {len(channels)} kanálech"]
            for channel in channels:
                rows = self.series.rows(channel)
                if not rows:
                    continue
                lines.append("{}: pokrytí {:.4f} % · trend {:+.4f} %/min"
                             .format(df.CHANNEL_TITLES.get(channel, channel),
                                     rows[-1].coverage_pct,
                                     self.series.rate_per_minute(channel=channel)))
            return "\n".join(lines)
        last = self.series.samples[-1]
        rate = self.series.rate_per_minute()
        parts = [f"{len(self.series)} měření",
                 f"pokrytí {last.coverage_pct:.4f} %"]
        if last.particles >= 0:
            parts.append(f"{int(last.particles)} částic")
        if last.area_um2:
            parts.append(f"{last.area_um2:.0f} µm²")
        parts.append(f"trend {rate:+.4f} %/min")
        return " · ".join(parts)

    def _updateState(self) -> None:
        text = (self.bias.describe() if self.bias
                else "Není pořízen – změřte čisté sklíčko.")
        missing = self.missingBias()
        if self.bias and missing and missing != [""]:
            text += " · chybí: " + ", ".join(df.CHANNEL_TITLES[c] for c in missing)
        self.lbl_bias.setText(text)
        self.btn_bias_save.setEnabled(bool(self.bias))
        self.lbl_values.setText(self.summaryText())
        self.btn_table.setText("Tabulka a graf…" if not len(self.series)
                               else f"Tabulka a graf… ({len(self.series)})")
