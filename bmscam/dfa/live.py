"""Rozbor jednoho snímku za běhu měření – stejnou metodou jako dávkově.

Živé měření u kamery a dávkový rozbor složky musí dát **stejná čísla**,
jinak nemá smysl je porovnávat. Proto se tady nic nepočítá znovu: sestaví
se :class:`~bmscam.dfa.analyzer.AnalysisParams` z nastavení aplikace,
snímek se převede do geometrie rozboru (binning) a zavolá se přímo
:func:`~bmscam.dfa.analyzer.analyze_prepared_frame` z převzatého jádra.
Výsledné :class:`FrameMetrics` se jen přeloží na klíče sloupců tabulky.
"""

from datetime import datetime
from typing import Dict, Optional

import numpy as np


def available() -> bool:
    """True, když jsou k dispozici knihovny, které rozbor potřebuje."""
    try:
        from . import analyzer                      # noqa: F401
    except ImportError:
        return False
    return True


def _analyzer():
    from . import analyzer
    return analyzer


AUTO_BINNING_TARGET_HEIGHT = 1200


def resolve_binning(image_height: int, binning: int = 0) -> int:
    """Kolikrát zmenšit obraz před rozborem (0 = zvolit podle rozlišení).

    Binning je průměrování 2×2 nebo 4×4 (INTER_AREA), takže se nic
    nezahazuje náhodně jako u podvzorkování – navíc zlepšuje poměr
    signál/šum. Na 4K je to hlavní důvod, proč rozbor stíhá: bez něj
    prahování šumu označí statisíce jednopixelových objektů."""
    params = _analyzer().AnalysisParams(binning=int(binning or 0))
    return params.resolve_binning(int(image_height))


def apply_binning(image: np.ndarray, binning: int) -> np.ndarray:
    return _analyzer().apply_binning(image, int(binning))


def estimate_noise(image, sample_limit: int = 250_000):
    from .imageops import estimate_noise as fn
    return fn(image, sample_limit)


def separate_haze(diff, downscale: int = 16):
    from .imageops import separate_haze as fn
    return fn(diff, downscale)


def cleanliness_score(coverage_pct: float, haze_mean_adu: float,
                      density_per_mpx: float) -> float:
    return _analyzer().compute_cleanliness_score(
        coverage_pct, haze_mean_adu, density_per_mpx)


#: pole nastavení aplikace, která mají v AnalysisParams stejný význam
_DIRECT = (
    ("threshold_mode", "threshold_mode"),
    ("sigma", "sigma"),
    ("absolute", "absolute_threshold"),
    ("min_threshold_adu", "min_threshold_adu"),
    ("haze_threshold", "haze_threshold"),
    ("min_area_px", "min_area_px"),
    ("cluster_min_area_px", "cluster_min_area_px"),
    ("fiber_aspect_ratio", "fiber_aspect_ratio"),
    ("fiber_min_length_px", "fiber_min_length_px"),
    ("saturation_adu", "saturation_adu"),
    ("um_per_px", "um_per_px"),
    ("binning", "binning"),
    ("bias_frames", "bias_frames"),
)


def params_from_settings(settings):
    """Přeloží nastavení aplikace na parametry převzatého jádra."""
    values = {}
    for ours, theirs in _DIRECT:
        value = getattr(settings, ours, None)
        if value is not None:
            values[theirs] = value
    values["roi"] = getattr(settings, "roi", None)
    return _analyzer().AnalysisParams(**values)


#: FrameMetrics → klíče sloupců tabulky aplikace
_METRIC_MAP = (
    ("coverage_pct", "total_coverage_pct"),
    ("particles", "total_particle_count"),
    ("area_um2", "total_area_um2"),
    ("mean_signal", "mean_signal_adu"),
    ("max_signal", "max_signal_adu"),
    ("bg_level", "bg_level_adu"),
    ("bg_sigma", "bg_noise_sigma"),
    ("threshold", "applied_threshold"),
    ("snr", "snr"),
    ("haze_pct", "haze_coverage_pct"),
    ("haze_mean", "haze_mean_adu"),
    ("haze_max", "haze_max_adu"),
    ("points", "point_count"),
    ("clusters", "cluster_count"),
    ("fibers", "fiber_count"),
    ("fiber_len_px", "fiber_total_length_px"),
    ("density_mpx", "particle_density_per_mpx"),
    ("mean_area_px", "mean_particle_area_px"),
    ("max_area_px", "max_particle_area_px"),
    ("heterogeneity_pct", "spatial_heterogeneity_pct"),
    ("centroid_x_pct", "centroid_x_pct"),
    ("centroid_y_pct", "centroid_y_pct"),
    ("focus", "focus_score"),
    ("saturated_px", "saturated_pixels_count"),
    ("cleanliness", "cleanliness_score"),
)


def metrics_to_dict(metrics) -> Dict[str, float]:
    """Metriky převzatého jádra přeložené na klíče sloupců aplikace."""
    out = {ours: getattr(metrics, theirs) for ours, theirs in _METRIC_MAP}
    out["particle_area_px"] = int(metrics.point_area_px + metrics.cluster_area_px
                                  + metrics.fiber_area_px)
    return out


def analyze_frame(gray: np.ndarray, reference: Optional[np.ndarray],
                  settings, when: Optional[datetime] = None) -> Dict[str, float]:
    """Spočítá metriky jednoho snímku převzatým jádrem rozboru.

    Snímek i reference se nejdřív převedou do geometrie rozboru (binning),
    protože jádro počítá s tím, že je dostane hotové – stejně jako
    v dávkovém režimu."""
    analyzer = _analyzer()
    image = np.ascontiguousarray(gray, dtype=np.float32)
    params = params_from_settings(settings)
    binning = params.resolve_binning(image.shape[0])

    if reference is None:
        # Bez pořízené reference je pozadím konstanta z mediánu snímku.
        # Nerovnoměrné osvětlení pak zůstane v obraze jako opar – proto je
        # reference pro poctivé měření pořád nutná.
        bias = np.full_like(image, float(np.median(image)))
    else:
        bias = np.asarray(reference, dtype=np.float32)

    image = analyzer.apply_binning(image, binning)
    bias = analyzer.apply_binning(bias, binning)

    stamp = when or datetime.now()
    metrics, _ = analyzer.analyze_prepared_frame(
        image, bias, params, index=0, filename="", filepath="",
        timestamp=stamp, t0=stamp, binning=binning)
    out = metrics_to_dict(metrics)
    out["binning"] = binning
    return out
