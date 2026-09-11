"""Rozbor temného pole ve vlastním vlákně.

Rozbor 4K snímku je práce na stovky milisekund: dvakrát medián, prahování
a označkování částic přes osm milionů pixelů, k tomu zápis snímku na disk.
Když tohle běželo přímo v obsluze snímku, stálo celé okno – nešlo scrollovat
ani přepnout záložku. Proto je to tady odsunuté do vlastního vlákna a hlavní
okno si nechává jen to nejlevnější: vytáhnout ze snímku šedotónovou kopii,
dokud jsou data platná.

Snímky, které rozbor nestíhá zpracovat hned, čekají ve frontě a dopočítají
se se zpožděním – během měření se graf plní tak, jak výsledky přicházejí,
a zbytek se dopočítá po jeho zastavení. Fronta je omezená objemem dat
(ne počtem snímků), aby se při dlouhém měření nevyčerpala paměť: jeden
šedotónový 4K snímek zabere v RAM osm megabajtů, takže tři gigabajty stačí
zhruba na šest minut snímání po sekundě. Teprve při překročení limitu se
snímek zahodí – a když se přitom archivují na disk, dá se dopočítat zpětným
rozborem.
"""

from collections import deque
from typing import Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from .. import darkfield as df


def _build_anchor(reference, settings):
    """Kotva zarovnání; chyba nesmí shodit pořízení reference."""
    try:
        from .. import dfa
        return dfa.build_anchor(reference, settings)
    except Exception:                                  # noqa: BLE001
        return None


class _Worker(QObject):
    """Vlastní výpočet – žije ve vlákně, nesahá na žádný widget."""

    sampleReady = pyqtSignal(object, object)    # metriky, čas pořízení
    biasProgress = pyqtSignal(int, int)
    biasReady = pyqtSignal(object)
    stackProgress = pyqtSignal(int, int)        # dílčí snímky do průměru
    failed = pyqtSignal(str)
    finished = pyqtSignal()                     # dávka hotová, můžeš poslat další

    def __init__(self):
        super().__init__()
        self._collector: Optional[df.BiasCollector] = None
        self._stacker: Optional[df.FrameStacker] = None

    @pyqtSlot()
    def cancelStack(self) -> None:
        self._stacker = None

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
                    bias = collector.result()
                    # Kotva zarovnání se staví z hotové reference – je to
                    # průměr snímků čistého sklíčka, tedy to nejklidnější,
                    # co k dispozici je. Stojí to desetiny sekundy, proto
                    # to patří sem do vlákna, ne do obsluhy okna.
                    bias.anchor = _build_anchor(bias.mean, settings)
                    self.biasReady.emit(bias)
                else:
                    self.biasProgress.emit(collector.taken, collector.count)
                return
            count = max(1, int(getattr(settings, "stack_frames", 1)))
            if count > 1:
                # Měří se až z průměru několika snímků; dílčí snímky se
                # nikam neukládají, na disk jde jen ten zprůměrovaný.
                stacker = self._stacker
                if stacker is None or stacker.count != count:
                    stacker = self._stacker = df.FrameStacker(count)
                if not stacker.add(gray, when, channel or ""):
                    self.stackProgress.emit(stacker.taken, stacker.count)
                    return
                self.stackProgress.emit(stacker.count, stacker.count)
                gray = stacker.result()
                self._stacker = None
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
    stackProgress = pyqtSignal(int, int)
    failed = pyqtSignal(str)

    _submit = pyqtSignal(object, object, object, object, object, object)
    _startBias = pyqtSignal(int)
    _cancelBias = pyqtSignal()
    _cancelStack = pyqtSignal()

    #: kolik dat smí čekat ve frontě v paměti (jeden 4K snímek = 8 MB);
    #: tři gigabajty vydrží asi 380 snímků, tedy přes šest minut po sekundě
    MAX_QUEUED_BYTES = 3 * 1024 * 1024 * 1024

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self.collecting_bias = False
        self.dropped = 0                # zahozené snímky (fronta byla plná)
        self.max_queued_bytes = self.MAX_QUEUED_BYTES
        self._queue = deque()
        self.queued_bytes = 0

        self._thread = QThread()
        self._thread.setObjectName("dark-field")
        self._worker = _Worker()
        self._worker.moveToThread(self._thread)

        self._submit.connect(self._worker.process)
        self._startBias.connect(self._worker.startBias)
        self._cancelBias.connect(self._worker.cancelBias)
        self._cancelStack.connect(self._worker.cancelStack)
        self._worker.sampleReady.connect(self.sampleReady)
        self._worker.biasProgress.connect(self.biasProgress)
        self._worker.biasReady.connect(self._onBiasReady)
        self._worker.stackProgress.connect(self.stackProgress)
        self._worker.failed.connect(self._onFailed)
        self._worker.finished.connect(self._onFinished)
        self._thread.start()

    # ------------------------------------------------------------ zadání ---
    def submit(self, gray, bias, settings, when, store=None, channel="") -> bool:
        """Zařadí snímek k rozboru.

        Vrací False jen tehdy, když je fronta plná a snímek se zahodil."""
        job = (gray, bias, settings, when, store, channel)
        if not self.busy:
            self.busy = True
            self._submit.emit(*job)
            return True
        size = int(getattr(gray, "nbytes", 0))
        if self.queued_bytes + size > self.max_queued_bytes and self._queue:
            self.dropped += 1
            return False
        self._queue.append(job)
        self.queued_bytes += size
        return True

    @property
    def pending(self) -> int:
        """Kolik snímků ještě čeká na rozbor (včetně právě počítaného)."""
        return len(self._queue) + (1 if self.busy else 0)

    def clearQueue(self) -> int:
        """Zahodí čekající frontu. Vrací počet zahozených snímků."""
        count = len(self._queue)
        self._queue.clear()
        self.queued_bytes = 0
        self.dropped += count
        return count

    def startBias(self, count: int) -> None:
        self.collecting_bias = True
        self._startBias.emit(count)

    def cancelBias(self) -> None:
        self.collecting_bias = False
        self._cancelBias.emit()

    def cancelStack(self) -> None:
        """Zahodí rozdělaný průměr (konec měření, změna nastavení)."""
        self._cancelStack.emit()

    # ------------------------------------------------------------ zpětně ---
    def _onFinished(self) -> None:
        if self._queue:
            job = self._queue.popleft()
            self.queued_bytes -= int(getattr(job[0], "nbytes", 0))
            self.queued_bytes = max(0, self.queued_bytes)
            self._submit.emit(*job)
            return
        self.busy = False

    def _onBiasReady(self, bias) -> None:
        self.collecting_bias = False
        self.biasReady.emit(bias)

    def _onFailed(self, message: str) -> None:
        self.collecting_bias = False
        self.failed.emit(message)

    # ------------------------------------------------------------ konec ----
    def shutdown(self) -> None:
        self._queue.clear()
        self.queued_bytes = 0
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)
