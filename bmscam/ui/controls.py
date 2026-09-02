"""Obecné ovládací prvky sestavované automaticky podle PropSpec."""

from typing import Callable, Dict, Iterable, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                             QGridLayout, QHBoxLayout, QLabel, QPushButton,
                             QSizePolicy, QSlider, QSpinBox, QToolButton,
                             QVBoxLayout, QWidget)

from ..spec import (AF_FEEDBACK_TEXT, KIND_ACTION, KIND_CHECK, KIND_COMBO,
                    KIND_READONLY, KIND_SLIDER, PropSpec)


class PropRow(QWidget):
    """Jeden řádek ovládání jedné vlastnosti."""

    valueChanged = pyqtSignal(str, int)     # klíč, syrová hodnota
    actionTriggered = pyqtSignal(str)

    def __init__(self, spec: PropSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self._updating = False
        self._build()
        if spec.tip:
            self.setToolTip(spec.tip)

    # ------------------------------------------------------------- sestavení
    def _build(self) -> None:
        spec = self.spec
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(2)

        if spec.kind == KIND_SLIDER:
            head = QHBoxLayout()
            head.addWidget(QLabel(spec.label))
            head.addStretch(1)
            self.spin = self._makeSpin()
            head.addWidget(self.spin)
            self.reset = QToolButton()
            self.reset.setText("⟲")
            self.reset.setToolTip(f"Zpět na výchozí ({spec.format(spec.default)})")
            self.reset.setAutoRaise(True)
            self.reset.clicked.connect(lambda: self.setValue(spec.default, emit=True))
            head.addWidget(self.reset)
            lay.addLayout(head)
            self.slider = QSlider(Qt.Horizontal)
            self.slider.setRange(spec.minimum, spec.maximum)
            self.slider.setValue(spec.default)
            self.slider.valueChanged.connect(self._onSlider)
            lay.addWidget(self.slider)

        elif spec.kind == KIND_CHECK:
            self.check = QCheckBox(spec.label)
            self.check.toggled.connect(
                lambda on: self._emit(1 if on else 0))
            lay.addWidget(self.check)

        elif spec.kind == KIND_COMBO:
            head = QHBoxLayout()
            head.addWidget(QLabel(spec.label))
            head.addStretch(1)
            self.combo = QComboBox()
            items = list(spec.items) or [str(i) for i in range(spec.minimum, spec.maximum + 1)]
            self.combo.addItems(items[: spec.maximum - spec.minimum + 1] or items)
            self.combo.currentIndexChanged.connect(
                lambda i: self._emit(spec.minimum + i))
            head.addWidget(self.combo)
            lay.addLayout(head)

        elif spec.kind == KIND_READONLY:
            head = QHBoxLayout()
            head.addWidget(QLabel(spec.label))
            head.addStretch(1)
            self.value_label = QLabel("–")
            self.value_label.setStyleSheet("font-weight: 600;")
            head.addWidget(self.value_label)
            lay.addLayout(head)

        elif spec.kind == KIND_ACTION:
            self.button = QPushButton(spec.label)
            self.button.clicked.connect(lambda: self.actionTriggered.emit(self.spec.key))
            lay.addWidget(self.button)

    def _makeSpin(self):
        spec = self.spec
        if spec.decimals:
            spin = QDoubleSpinBox()
            spin.setDecimals(spec.decimals)
            spin.setRange(spec.minimum * spec.scale, spec.maximum * spec.scale)
            spin.setSingleStep(max((spec.maximum - spec.minimum) * spec.scale / 100.0, 10 ** -spec.decimals))
            spin.setValue(spec.default * spec.scale)
        else:
            spin = QSpinBox()
            spin.setRange(spec.minimum, spec.maximum)
            spin.setValue(spec.default)
        if spec.unit:
            spin.setSuffix(" " + spec.unit)
        spin.setKeyboardTracking(False)
        spin.setMinimumWidth(96)
        spin.valueChanged.connect(self._onSpin)
        return spin

    # ------------------------------------------------------------- hodnoty --
    def _emit(self, raw: int) -> None:
        if not self._updating:
            self.valueChanged.emit(self.spec.key, int(raw))

    def _onSlider(self, raw: int) -> None:
        if self._updating:
            return
        self._updating = True
        self._setSpin(raw)
        self._updating = False
        self._emit(raw)

    def _onSpin(self, shown) -> None:
        if self._updating:
            return
        raw = int(round(shown / self.spec.scale)) if self.spec.decimals else int(shown)
        self._updating = True
        self.slider.setValue(raw)
        self._updating = False
        self._emit(raw)

    def _setSpin(self, raw: int) -> None:
        if self.spec.decimals:
            self.spin.setValue(raw * self.spec.scale)
        else:
            self.spin.setValue(int(raw))

    def setValue(self, raw: int, emit: bool = False) -> None:
        """Nastaví zobrazenou hodnotu (bez zpětného zápisu do kamery)."""
        spec = self.spec
        self._updating = True
        try:
            if spec.kind == KIND_SLIDER:
                raw = max(spec.minimum, min(int(raw), spec.maximum))
                self.slider.setValue(raw)
                self._setSpin(raw)
            elif spec.kind == KIND_CHECK:
                self.check.setChecked(bool(raw))
            elif spec.kind == KIND_COMBO:
                idx = int(raw) - spec.minimum
                if 0 <= idx < self.combo.count():
                    self.combo.setCurrentIndex(idx)
            elif spec.kind == KIND_READONLY:
                if spec.key == "affeedback":
                    self.value_label.setText(AF_FEEDBACK_TEXT.get(int(raw), str(raw)))
                else:
                    self.value_label.setText(spec.format(int(raw)))
        finally:
            self._updating = False
        if emit:
            self._emit(raw)

    def value(self) -> int:
        spec = self.spec
        if spec.kind == KIND_SLIDER:
            return self.slider.value()
        if spec.kind == KIND_CHECK:
            return 1 if self.check.isChecked() else 0
        if spec.kind == KIND_COMBO:
            return spec.minimum + self.combo.currentIndex()
        return 0

    def setControlEnabled(self, on: bool) -> None:
        for name in ("slider", "spin", "check", "combo", "button", "reset"):
            w = getattr(self, name, None)
            if w is not None:
                w.setEnabled(on)


class PropertyPanel(QWidget):
    """Panel se skupinou vlastností."""

    valueChanged = pyqtSignal(str, int)
    actionTriggered = pyqtSignal(str)

    def __init__(self, specs: Iterable[PropSpec], parent=None):
        super().__init__(parent)
        self.rows: Dict[str, PropRow] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        for spec in specs:
            row = PropRow(spec)
            row.valueChanged.connect(self.valueChanged)
            row.actionTriggered.connect(self.actionTriggered)
            self.rows[spec.key] = row
            lay.addWidget(row)
        lay.addStretch(1)

    def setValues(self, values: Dict[str, int]) -> None:
        for key, val in values.items():
            row = self.rows.get(key)
            if row is not None:
                row.setValue(val)

    def setRowEnabled(self, key: str, on: bool) -> None:
        row = self.rows.get(key)
        if row is not None:
            row.setControlEnabled(on)

    def keys(self):
        return self.rows.keys()
