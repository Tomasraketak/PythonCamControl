"""Sledování kontaminace witness sklíčka v temném poli.

Metoda je jednoduchá a stojí na tom, že v temném poli je čisté sklíčko
tmavé a každá částice, film nebo depozit svítí. Postup:

1. **Referenční snímek (bias).** Nasnímá se čisté sklíčko – průměr z více
   snímků, aby se potlačil šum. Zachytí se tím i to, co není kontaminace:
   nerovnoměrné osvětlení, prach na optice, horké pixely senzoru.
2. **Rozdíl.** Z každého měřeného snímku se bias odečte. Zbyde jen to, co
   přibylo.
3. **Práh.** Co je nad prahem, počítá se za kontaminaci. Práh se dá zadat
   absolutně, nebo – a to je obvykle lepší – jako násobek šumu pozadí
   (σ). Prahování podle σ se samo přizpůsobí expozici i zisku.
4. **Metriky.** Kolik procent plochy je pokryto, kolik je částic, jaká je
   jejich plocha a jak silný je celkový signál.

Modul je bez Qt a bez kamery, aby se dal testovat samostatně. Počítání
částic používá OpenCV, když je k dispozici; bez něj zůstanou plošné
metriky, které OpenCV nepotřebují.
"""

import csv
import os
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

#: režimy prahu
THRESHOLD_SIGMA = "sigma"
THRESHOLD_ABSOLUTE = "absolute"

#: popisky sloupců tabulky (pořadí = pořadí ve výstupu i v CSV)
COLUMNS: Sequence[Tuple[str, str, str]] = (
    # klíč,            záhlaví,              jednotka
    ("index",          "#",                  ""),
    ("time_s",         "Čas",                "s"),
    ("clock",          "Hodiny",             ""),
    ("coverage_pct",   "Pokrytí",            "%"),
    ("particles",      "Částic",             ""),
    ("particle_area_px", "Plocha částic",    "px"),
    ("area_um2",       "Plocha částic",      "µm²"),
    ("mean_signal",    "Průměrný signál",    "ADU"),
    ("max_signal",     "Maximum",            "ADU"),
    ("bg_sigma",       "Šum pozadí",         "ADU"),
    ("threshold",      "Práh",               "ADU"),
)


class Settings:
    """Nastavení měření – všechno, co jde v okně přenastavit."""

    def __init__(self, **kwargs):
        self.interval_s: float = 1.0        # jak často měřit
        self.threshold_mode: str = THRESHOLD_SIGMA
        self.sigma: float = 5.0             # práh = pozadí + sigma * šum
        self.absolute: float = 12.0         # práh v ADU nad bias
        self.min_area_px: int = 2           # menší skvrny = šum, ignorovat
        self.bias_frames: int = 16          # kolik snímků průměrovat do biasu
        self.um_per_px: float = 0.0         # 0 = nekalibrováno
        self.roi: Optional[Tuple[int, int, int, int]] = None   # x, y, w, h
        for key, value in kwargs.items():
            if not hasattr(self, key):
                raise KeyError(key)
            setattr(self, key, value)

    def to_dict(self) -> Dict:
        return {k: v for k, v in vars(self).items()}


class Bias:
    """Referenční snímek čistého sklíčka."""

    def __init__(self, mean: np.ndarray, frames: int = 1,
                 created: Optional[datetime] = None, note: str = ""):
        self.mean = np.asarray(mean, dtype=np.float32)
        self.frames = int(frames)
        self.created = created or datetime.now()
        self.note = note

    @property
    def shape(self) -> Tuple[int, int]:
        return self.mean.shape[0], self.mean.shape[1]

    @property
    def level(self) -> float:
        """Střední jas reference – kontrola, že sklíčko bylo opravdu tmavé."""
        return float(self.mean.mean())

    def describe(self) -> str:
        return ("{}×{} px · {} snímků · úroveň {:.1f} ADU · {}"
                .format(self.shape[1], self.shape[0], self.frames, self.level,
                        self.created.strftime("%d.%m.%Y %H:%M:%S")))

    # ------------------------------------------------------------ soubor ---
    def save(self, path: str) -> None:
        np.savez_compressed(path, mean=self.mean, frames=self.frames,
                            created=self.created.isoformat(), note=self.note)

    @classmethod
    def load(cls, path: str) -> "Bias":
        data = np.load(path, allow_pickle=False)
        created = datetime.now()
        try:
            created = datetime.fromisoformat(str(data["created"]))
        except (KeyError, ValueError):
            pass
        note = str(data["note"]) if "note" in data else ""
        return cls(data["mean"], int(data["frames"]), created, note)


class BiasCollector:
    """Sbírá snímky a průměruje je do referenčního snímku."""

    def __init__(self, count: int):
        self.count = max(1, int(count))
        self._sum: Optional[np.ndarray] = None
        self._taken = 0

    @property
    def taken(self) -> int:
        return self._taken

    @property
    def done(self) -> bool:
        return self._taken >= self.count

    def add(self, gray: np.ndarray) -> bool:
        """Přidá snímek; vrátí True, když je jich dost."""
        gray = np.asarray(gray, dtype=np.float32)
        if self._sum is None:
            self._sum = np.zeros(gray.shape, dtype=np.float64)
        elif self._sum.shape != gray.shape:
            raise ValueError("Rozlišení se během snímání reference změnilo.")
        self._sum += gray
        self._taken += 1
        return self.done

    def result(self) -> Bias:
        if self._sum is None or not self._taken:
            raise ValueError("Nebyl přidán žádný snímek.")
        return Bias(self._sum / self._taken, self._taken)


class Sample:
    """Jedno měření."""

    __slots__ = tuple(key for key, _, _ in COLUMNS) + ("when",)

    def __init__(self, **values):
        for key in self.__slots__:
            setattr(self, key, values.get(key, 0))

    def as_row(self) -> List[str]:
        out = []
        for key, _, _ in COLUMNS:
            value = getattr(self, key)
            if key == "particles":
                # -1 = bez OpenCV se částice nepočítají
                out.append("–" if int(value) < 0 else f"{int(value)}")
            elif key in ("index", "particle_area_px"):
                out.append(f"{int(value)}")
            elif key == "clock":
                out.append(str(value))
            elif key == "coverage_pct":
                out.append(f"{value:.4f}")
            elif key == "area_um2":
                out.append(f"{value:.1f}" if value else "–")
            else:
                out.append(f"{value:.2f}")
        return out


# ------------------------------------------------------------------ rozbor --

def to_gray(frame, pixel_order: str = "rgb") -> np.ndarray:
    """Z snímku backendu (RGB888) udělá šedotónové pole.

    Kamera je černobílá, takže R = G = B a stačí jeden kanál; u barevného
    zdroje se použije průměr, aby se nic neztratilo."""
    raw = np.frombuffer(bytes(frame.data), dtype=np.uint8)
    raw = raw[: frame.stride * frame.height].reshape(frame.height, frame.stride)
    pixels = raw[:, : frame.width * 3].reshape(frame.height, frame.width, 3)
    first, third = pixels[:, :, 0], pixels[:, :, 2]
    if np.array_equal(first[::32, ::32], third[::32, ::32]):
        return first.astype(np.float32)        # černobílý obraz
    return pixels.mean(axis=2, dtype=np.float32)


def crop(gray: np.ndarray, roi: Optional[Tuple[int, int, int, int]]) -> np.ndarray:
    if not roi:
        return gray
    x, y, w, h = (int(v) for v in roi)
    x, y = max(0, x), max(0, y)
    return gray[y:y + max(1, h), x:x + max(1, w)]


def _label_particles(mask: np.ndarray, min_area_px: int) -> Tuple[int, int]:
    """Vrátí (počet částic, jejich plochu v px). Bez OpenCV vrátí (-1, plocha)."""
    area = int(mask.sum())
    try:
        import cv2
    except ImportError:
        return -1, area
    count, _, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8)
    if count <= 1:
        return 0, 0
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep = areas >= max(1, int(min_area_px))
    return int(keep.sum()), int(areas[keep].sum())


def analyze(gray: np.ndarray, bias: Optional[Bias],
            settings: Settings) -> Dict[str, float]:
    """Porovná snímek s referencí a spočítá metriky kontaminace."""
    gray = np.asarray(gray, dtype=np.float32)
    if bias is not None:
        if bias.mean.shape != gray.shape:
            raise ValueError(
                "Referenční snímek má jiné rozlišení ({}×{}) než obraz "
                "({}×{}). Pořiďte referenci znovu."
                .format(bias.mean.shape[1], bias.mean.shape[0],
                        gray.shape[1], gray.shape[0]))
        diff = gray - bias.mean
    else:
        # bez reference se za pozadí bere medián snímku
        diff = gray - float(np.median(gray))

    # šum pozadí: robustní odhad z odchylky od mediánu (MAD),
    # aby ho samotné částice nenafoukly
    median = float(np.median(diff))
    mad = float(np.median(np.abs(diff - median)))
    sigma = mad * 1.4826 or float(diff.std()) or 1.0

    if settings.threshold_mode == THRESHOLD_ABSOLUTE:
        threshold = float(settings.absolute)
    else:
        threshold = median + float(settings.sigma) * sigma

    mask = diff > threshold
    particles, particle_area = _label_particles(mask, settings.min_area_px)
    if particles < 0:                       # bez OpenCV
        particle_area = int(mask.sum())

    total = float(diff.size)
    above = diff[mask]
    scale = float(settings.um_per_px)
    return {
        "coverage_pct": 100.0 * particle_area / total if total else 0.0,
        "particles": particles,
        "particle_area_px": particle_area,
        "area_um2": particle_area * scale * scale if scale else 0.0,
        "mean_signal": float(above.mean()) if above.size else 0.0,
        "max_signal": float(diff.max()) if diff.size else 0.0,
        "bg_sigma": sigma,
        "threshold": threshold,
    }


class Series:
    """Průběh měření – řádky tabulky a jejich export."""

    def __init__(self):
        self.samples: List[Sample] = []
        self.started: Optional[datetime] = None

    def __len__(self) -> int:
        return len(self.samples)

    def clear(self) -> None:
        self.samples.clear()
        self.started = None

    def add(self, metrics: Dict[str, float], when: Optional[datetime] = None) -> Sample:
        when = when or datetime.now()
        if self.started is None:
            self.started = when
        sample = Sample(index=len(self.samples) + 1,
                        time_s=(when - self.started).total_seconds(),
                        clock=when.strftime("%H:%M:%S"),
                        when=when, **metrics)
        self.samples.append(sample)
        return sample

    def values(self, key: str) -> List[float]:
        return [float(getattr(s, key)) for s in self.samples]

    def rate_per_minute(self, key: str = "coverage_pct", window: int = 10) -> float:
        """Sklon posledních měření – jak rychle kontaminace přibývá."""
        if len(self.samples) < 2:
            return 0.0
        recent = self.samples[-max(2, window):]
        times = np.array([s.time_s for s in recent], dtype=float)
        values = np.array([float(getattr(s, key)) for s in recent], dtype=float)
        span = times[-1] - times[0]
        if span <= 0:
            return 0.0
        slope = np.polyfit(times, values, 1)[0]
        return float(slope * 60.0)

    # ------------------------------------------------------------ export ---
    def to_csv(self, path: str, settings: Optional[Settings] = None,
               bias: Optional[Bias] = None) -> None:
        """Uloží tabulku do CSV (středníky, aby to otevřel český Excel)."""
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(["# BMS Cam Control – měření kontaminace"])
            if self.started:
                writer.writerow(["# začátek", self.started.isoformat(" ", "seconds")])
            if bias is not None:
                writer.writerow(["# reference", bias.describe()])
            if settings is not None:
                for key, value in sorted(settings.to_dict().items()):
                    writer.writerow([f"# {key}", value])
            writer.writerow([f"{title} [{unit}]" if unit else title
                             for _, title, unit in COLUMNS])
            for sample in self.samples:
                writer.writerow(sample.as_row())


def default_csv_name(folder: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(folder, f"kontaminace_{stamp}.csv")
