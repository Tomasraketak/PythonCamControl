"""Rozbor temného pole ve vlastním vlákně.

Rozbor 4K snímku je práce na stovky milisekund: dvakrát medián, prahování
a označkování částic přes osm milionů pixelů, k tomu zápis snímku na disk.
Když tohle běželo přímo v obsluze snímku, stálo celé okno – nešlo scrollovat
ani přepnout záložku. Proto je to tady odsunuté do vlastního vlákna a hlavní
okno si nechává jen to nejlevnější: vytáhnout ze snímku šedotónovou kopii,
dokud jsou data platná.

Fronta má hloubku jedna. Když rozbor nestíhá, další snímek se zahodí místo
toho, aby se hromadil – u měření po sekundách je lepší jedno měření vynechat
než mít frontu, která roste do paměti a zpožďuje se za skutečností.
"""

from typing import Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from .. import darkfield as df


class _Worker(QObject):
    """Vlastní výpočet – žije ve vlákně, nesahá na žádný widget."""

    sampleReady = pyqtSignal(object, object)    # metriky, čas pořízení
    biasProgress = pyqtSignal(int, int)
    biasReady = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()                     # dávka hotová, můžeš poslat další

    def __init__(self):
        super().__init__()
        self._collector: Optional[df.BiasCollector] = None

    @pyqtSlot(int)
    def startBias(self, count: int) -> None:
        self._collector = df.BiasCollector(count)
        self.biasProgress.emit(0, self._collector.count)

    @pyqtSlot()
    def cancelBias(self) -> None:
        self._collector = None

    @pyqtSlot(object, object, object, object, object, object)
    def process(self, gray, bias, settings, when, store, channel) -> None:
        try:
            collector = self._collector
            if collector is not None:
                if collector.add(df.crop(gray, settings.roi)):
                    self._collector = None
                    self.biasProgress.emit(collector.taken, collector.count)
                    self.biasReady.emit(collector.result())
                else:
                    self.biasProgress.emit(collector.taken, collector.count)
                return
            if store is not None:
                store.save(gray, when, channel or "")
            metrics = df.analyze(df.crop(gray, settings.roi), bias, settings)
            metrics["channel"] = channel or ""
            self.sampleReady.emit(metrics, when)
        except Exception as exc:                          # noqa: BLE001
            self._collector = None
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class DarkFieldRunner(QObject):
    """Obsluha vlákna – hlavní okno mluví jen s ní."""

    sampleReady = pyqtSignal(object, object)
    biasProgress = pyqtSignal(int, int)
    biasReady = pyqtSignal(object)
    failed = pyqtSignal(str)

    _submit = pyqtSignal(object, object, object, object, object, object)
    _startBias = pyqtSignal(int)
    _cancelBias = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self.collecting_bias = False
        self.dropped = 0                # kolik snímků se zahodilo, když se nestíhalo

        self._thread = QThread()
        self._thread.setObjectName("dark-field")
        self._worker = _Worker()
        self._worker.moveToThread(self._thread)

        self._submit.connect(self._worker.process)
        self._startBias.connect(self._worker.startBias)
        self._cancelBias.connect(self._worker.cancelBias)
        self._worker.sampleReady.connect(self.sampleReady)
        self._worker.biasProgress.connect(self.biasProgress)
        self._worker.biasReady.connect(self._onBiasReady)
        self._worker.failed.connect(self._onFailed)
        self._worker.finished.connect(self._onFinished)
        self._thread.start()

    # ------------------------------------------------------------ zadání ---
    def submit(self, gray, bias, settings, when, store=None, channel="") -> bool:
        """Pošle snímek k rozboru. False = vlákno nestíhá, snímek se zahodil."""
        if self.busy:
            self.dropped += 1
            return False
        self.busy = True
        self._submit.emit(gray, bias, settings, when, store, channel)
        return True

    def startBias(self, count: int) -> None:
        self.collecting_bias = True
        self._startBias.emit(count)

    def cancelBias(self) -> None:
        self.collecting_bias = False
        self._cancelBias.emit()

    # ------------------------------------------------------------ zpětně ---
    def _onFinished(self) -> None:
        self.busy = False

    def _onBiasReady(self, bias) -> None:
        self.collecting_bias = False
        self.biasReady.emit(bias)

    def _onFailed(self, message: str) -> None:
        self.collecting_bias = False
        self.failed.emit(message)

    # ------------------------------------------------------------ konec ----
    def shutdown(self) -> None:
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)
