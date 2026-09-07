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

#: Kanály vícekanálového měření. Kamera je černobílá, ale osvětlení umí
#: svítit jen jednou složkou – snímek pořízený pod jednou vlnovou délkou
#: je tedy měření v úzkém pásmu. Každá barva se láme jinak, takže má
#: vlastní zaostření i expozici; proto se u každé dá zadat násobek
#: expozičního času a posun ostření.
CHANNEL_ORDER = ("red", "green", "blue")
CHANNEL_TITLES = {"red": "Červená", "green": "Zelená", "blue": "Modrá"}
CHANNEL_COLORS = {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255)}
CHANNEL_NM = {"red": 625, "green": 520, "blue": 470}


def channel_title(key: str) -> str:
    """Popisek kanálu i s vlnovou délkou."""
    if key not in CHANNEL_TITLES:
        return str(key)
    return "{} {} nm".format(CHANNEL_TITLES[key], CHANNEL_NM[key])

#: popisky sloupců tabulky (pořadí = pořadí ve výstupu i v CSV)
COLUMNS: Sequence[Tuple[str, str, str]] = (
    # klíč,            záhlaví,              jednotka
    ("index",          "#",                  ""),
    ("time_s",         "Čas",                "s"),
    ("clock",          "Hodiny",             ""),
    ("channel",        "Kanál",              ""),
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
        self.store_frames: bool = True      # ukládat snímky pro zpětný rozbor
        self.queue_mb: int = 3072           # kolik RAM smí zabrat fronta rozboru
        self.multichannel: bool = False     # měřit postupně pod R, G a B
        self.settle_ms: int = 400           # co počkat po přepnutí barvy
        # násobek expozičního času a posun ostření pro každý kanál
        self.exposure_scale: Dict[str, float] = {k: 1.0 for k in CHANNEL_ORDER}
        self.focus_offset: Dict[str, int] = {k: 0 for k in CHANNEL_ORDER}
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


class BiasSet:
    """Reference k měření – buď jedna, nebo jedna pro každý kanál.

    Jednokanálové měření používá klíč "" (prázdný řetězec), vícekanálové
    klíče „red“, „green“ a „blue“. Držet obojí v jednom objektu je
    jednodušší než dvě větve všude, kde se s referencí pracuje.
    """

    def __init__(self, items: Optional[Dict[str, Bias]] = None):
        self.items: Dict[str, Bias] = dict(items or {})

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    def get(self, channel: str = "") -> Optional[Bias]:
        """Reference pro kanál; když pro něj není, zkusí se jednokanálová."""
        return self.items.get(channel) or self.items.get("")

    def put(self, channel: str, bias: Bias) -> None:
        self.items[channel] = bias

    def missing(self, channels: Sequence[str]) -> List[str]:
        """Kanály, pro které reference chybí."""
        return [c for c in channels if c not in self.items]

    def describe(self) -> str:
        if not self.items:
            return "Není pořízena."
        if set(self.items) == {""}:
            return self.items[""].describe()
        parts = []
        for key in CHANNEL_ORDER:
            if key in self.items:
                parts.append("{}: {:.1f} ADU / {} sn."
                             .format(CHANNEL_TITLES[key],
                                     self.items[key].level,
                                     self.items[key].frames))
        first = next(iter(self.items.values()))
        return "{}×{} px · {}".format(first.shape[1], first.shape[0],
                                      " · ".join(parts))

    # ------------------------------------------------------------ soubor ---
    def save(self, path: str, note: str = "") -> None:
        """Uloží sadu; „note“ je popis podmínek, za kterých vznikla.

        Popis se ukládá do souboru schválně – reference bez informace
        o expozici a osvětlení se po pár týdnech nedá k ničemu použít."""
        data = {}
        for channel, bias in self.items.items():
            tag = channel or "mono"
            data[f"mean_{tag}"] = bias.mean
            data[f"frames_{tag}"] = bias.frames
            data[f"created_{tag}"] = bias.created.isoformat()
            data[f"note_{tag}"] = note or bias.note
        if not data:
            raise ValueError("Není co uložit – reference není pořízená.")
        data["note"] = note
        np.savez_compressed(path, **data)

    def note(self) -> str:
        """Popis podmínek uložený u reference (prázdný, když chybí)."""
        for bias in self.items.values():
            if bias.note:
                return bias.note
        return ""

    @classmethod
    def load(cls, path: str) -> "BiasSet":
        """Načte sadu; přečte i starší soubor s jedinou referencí."""
        data = np.load(path, allow_pickle=False)
        items: Dict[str, Bias] = {}
        if "mean" in data:                      # starší formát jedné reference
            created = datetime.now()
            try:
                created = datetime.fromisoformat(str(data["created"]))
            except (KeyError, ValueError):
                pass
            items[""] = Bias(data["mean"], int(data["frames"]), created)
            return cls(items)
        for key in data.files:
            if not key.startswith("mean_"):
                continue
            tag = key[len("mean_"):]
            channel = "" if tag == "mono" else tag
            created = datetime.now()
            try:
                created = datetime.fromisoformat(str(data[f"created_{tag}"]))
            except (KeyError, ValueError):
                pass
            frames = int(data[f"frames_{tag}"]) if f"frames_{tag}" in data else 1
            note = str(data[f"note_{tag}"]) if f"note_{tag}" in data else ""
            items[channel] = Bias(data[key], frames, created, note)
        if not items:
            raise ValueError("Soubor neobsahuje žádnou referenci.")
        return cls(items)


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
            if key == "channel":
                out.append(channel_title(value) if value else "–")
            elif key == "particles":
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

def to_gray_u8(frame, pixel_order: str = "rgb") -> np.ndarray:
    """Z snímku backendu (RGB888) udělá šedotónové pole v uint8.

    Kamera je černobílá, takže R = G = B a stačí jeden kanál; u barevného
    zdroje se použije průměr, aby se nic neztratilo.

    Vrací uint8, a to schválně: na 4K snímku je to 8 MB místo 33 MB ve
    float32. Tahle funkce běží ve vlákně GUI (data snímku platí jen do
    dalšího snímku), takže musí být co nejlevnější – přepočet na float
    si udělá až rozbor ve vlastním vlákně."""
    # Bez bytes(): kopie celé vyrovnávací paměti navíc je na 4K 24 MB.
    # Čte se hned po pull() ve stejném vlákně, takže data drží.
    raw = np.frombuffer(frame.data, dtype=np.uint8)
    raw = raw[: frame.stride * frame.height].reshape(frame.height, frame.stride)
    pixels = raw[:, : frame.width * 3].reshape(frame.height, frame.width, 3)
    first, third = pixels[:, :, 0], pixels[:, :, 2]
    if np.array_equal(first[::32, ::32], third[::32, ::32]):
        return np.ascontiguousarray(first)     # černobílý obraz
    return pixels.mean(axis=2).astype(np.uint8)


def to_gray(frame, pixel_order: str = "rgb") -> np.ndarray:
    """Totéž jako :func:`to_gray_u8`, ale ve float32 pro přímý rozbor."""
    return to_gray_u8(frame, pixel_order).astype(np.float32)


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


#: nad tolik pixelů se pozadí odhaduje ze vzorku, ne z celého snímku
_STATS_SAMPLE_LIMIT = 400_000


def background_stats(diff: np.ndarray) -> Tuple[float, float]:
    """Vrátí (úroveň pozadí, šum) – robustně, přes medián a MAD.

    Medián a MAD se počítají z rovnoměrného vzorku pixelů, ne z celého
    snímku. Na 4K je to rozdíl mezi stovkami milisekund a jednotkami
    milisekund a na výsledku se to neprojeví: obojí je odhad statistiky
    pozadí, které zabírá drtivou většinu plochy, takže pár set tisíc
    vzorků dá stejné číslo jako osm milionů. Prahuje se pak celý snímek,
    takže žádná částice se neztratí."""
    sample = diff
    if diff.size > _STATS_SAMPLE_LIMIT:
        step = int(np.ceil(np.sqrt(diff.size / _STATS_SAMPLE_LIMIT)))
        sample = diff[::step, ::step]
    median = float(np.median(sample))
    mad = float(np.median(np.abs(sample - median)))
    sigma = mad * 1.4826 or float(sample.std()) or 1.0
    return median, sigma


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

    median, sigma = background_stats(diff)

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

    def rows(self, channel: Optional[str] = None) -> List["Sample"]:
        """Měření, volitelně jen pro jeden kanál."""
        if channel is None:
            return list(self.samples)
        return [s for s in self.samples if s.channel == channel]

    def channels(self) -> List[str]:
        """Kanály, které se v řadě vyskytly, v ustáleném pořadí."""
        seen = {s.channel for s in self.samples}
        ordered = [c for c in CHANNEL_ORDER if c in seen]
        return ordered + sorted(seen - set(ordered))

    def values(self, key: str, channel: Optional[str] = None) -> List[float]:
        return [float(getattr(s, key)) for s in self.rows(channel)]

    def rate_per_minute(self, key: str = "coverage_pct", window: int = 10,
                        channel: Optional[str] = None) -> float:
        """Sklon posledních měření – jak rychle kontaminace přibývá."""
        samples = self.rows(channel)
        if len(samples) < 2:
            return 0.0
        recent = samples[-max(2, window):]
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


# ------------------------------------------------------------------ archiv --

class FrameStore:
    """Složka se snímky měření, aby šel rozbor zopakovat zpětně.

    Ukládá se šedotónový snímek v uint8 – tedy přesně to, z čeho rozbor
    počítá, bez ztráty. Když je po ruce OpenCV, jde do PNG (v temném poli
    je snímek skoro celý černý a komprese ho srazí na zlomek); jinak do
    komprimovaného .npy. Díky tomu se dá po měření změnit práh nebo
    minimální velikost částice a spočítat všechno znovu, aniž by se
    muselo měřit od začátku.
    """

    PREFIX = "df_"

    def __init__(self, directory: str):
        self.directory = directory
        self.count = 0

    @staticmethod
    def _cv2():
        try:
            import cv2
        except ImportError:
            return None
        return cv2

    def save(self, gray: np.ndarray, when: Optional[datetime] = None,
             channel: str = "") -> str:
        """Uloží snímek a vrátí cestu k němu.

        Kanál je součástí názvu, aby zpětný rozbor věděl, pod jakou barvou
        snímek vznikl, a mohl na něj vzít správnou referenci."""
        when = when or datetime.now()
        os.makedirs(self.directory, exist_ok=True)
        data = np.asarray(gray)
        if data.dtype != np.uint8:
            data = np.clip(data, 0, 255).astype(np.uint8)
        stamp = when.strftime("%Y%m%d_%H%M%S_%f")[:-3]
        tag = f"{channel}_" if channel in CHANNEL_TITLES else ""
        base = os.path.join(self.directory,
                            f"{self.PREFIX}{self.count + 1:05d}_{tag}{stamp}")
        cv2 = self._cv2()
        if cv2 is not None:
            path = base + ".png"
            # Soubor otevírá Python, ne OpenCV. cv2.imwrite si totiž cestu
            # převádí do systémového kódování a na Windows selže na každé
            # diakritice – třeba na jménu uživatele ve složce Downloads.
            ok, encoded = cv2.imencode(".png", data)
            if not ok:
                raise OSError(f"Snímek se nepodařilo zakódovat: {path}")
            with open(path, "wb") as fh:
                fh.write(encoded.tobytes())
        else:
            path = base + ".npz"
            np.savez_compressed(path, gray=data)
        self.count += 1
        return path

    def bytes_used(self) -> int:
        return sum(os.path.getsize(p) for p in self.frames())

    def frames(self) -> List[str]:
        return self.list_frames(self.directory)

    # ------------------------------------------------------------ čtení ---
    @classmethod
    def list_frames(cls, directory: str) -> List[str]:
        """Snímky ve složce, seřazené podle názvu (a tím i podle času)."""
        try:
            names = os.listdir(directory)
        except OSError:
            return []
        keep = [n for n in sorted(names)
                if n.startswith(cls.PREFIX) and n.endswith((".png", ".npz"))]
        return [os.path.join(directory, n) for n in keep]

    @staticmethod
    def load_frame(path: str) -> np.ndarray:
        if path.endswith(".npz"):
            with np.load(path, allow_pickle=False) as data:
                return np.asarray(data["gray"])
        cv2 = FrameStore._cv2()
        if cv2 is None:
            raise ValueError(
                "Snímky ve formátu PNG umí načíst jen OpenCV "
                "(pip install opencv-python).")
        # Čte se přes numpy ze stejného důvodu, z jakého se přes něj zapisuje:
        # cv2.imread neumí cestu s diakritikou.
        with open(path, "rb") as fh:
            raw = np.frombuffer(fh.read(), dtype=np.uint8)
        image = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError(f"Snímek se nepodařilo načíst: {path}")
        return image

    @staticmethod
    def frame_channel(path: str) -> str:
        """Kanál z názvu souboru; prázdný řetězec u jednokanálového měření."""
        stem = os.path.splitext(os.path.basename(path))[0]
        for part in stem.split("_"):
            if part in CHANNEL_TITLES:
                return part
        return ""

    @staticmethod
    def frame_time(path: str) -> Optional[datetime]:
        """Čas z názvu souboru – df_00007_20260907_143012_250.png."""
        stem = os.path.splitext(os.path.basename(path))[0]
        parts = stem.split("_")
        if len(parts) < 4:
            return None
        try:
            return datetime.strptime("_".join(parts[-3:]), "%Y%m%d_%H%M%S_%f")
        except ValueError:
            try:
                return datetime.strptime("_".join(parts[-3:-1]), "%Y%m%d_%H%M%S")
            except ValueError:
                return None


def reference(bias, channel: str = "") -> Optional[Bias]:
    """Referenci vytáhne z BiasSet, nebo propustí samotný Bias / None."""
    if isinstance(bias, BiasSet):
        return bias.get(channel)
    return bias


def reanalyze(paths: Sequence[str], bias, settings: Settings,
              progress=None) -> "Series":
    """Projde uložené snímky znovu a sestaví z nich novou řadu měření.

    `progress(hotovo, celkem)` smí vrátit False a rozbor tím zastavit –
    okno tak může nabídnout tlačítko Zrušit."""
    series = Series()
    total = len(paths)
    for done, path in enumerate(paths, 1):
        gray = FrameStore.load_frame(path)
        channel = FrameStore.frame_channel(path)
        metrics = analyze(crop(gray, settings.roi), reference(bias, channel),
                          settings)
        metrics["channel"] = channel
        series.add(metrics, FrameStore.frame_time(path))
        if progress is not None and progress(done, total) is False:
            break
    return series
