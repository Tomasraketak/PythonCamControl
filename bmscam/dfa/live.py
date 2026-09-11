"""Rozbor jednoho snímku za běhu měření – stejnou metodou jako dávkově.

Živé měření u kamery a dávkový rozbor složky musí dát **stejná čísla**,
jinak nemá smysl je porovnávat. Proto se tady nic nepočítá znovu: sestaví
se :class:`~bmscam.dfa.analyzer.AnalysisParams` z nastavení aplikace,
snímek se převede do geometrie rozboru (binning) a zavolá se přímo
:func:`~bmscam.dfa.analyzer.analyze_prepared_frame` z převzatého jádra.
Výsledné :class:`FrameMetrics` se jen přeloží na klíče sloupců tabulky.
"""

from dataclasses import replace as _replace
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
    ("area_px", "total_area_px"),
    ("integrated_signal", "integrated_signal_adu"),
    ("haze_only_pct", "haze_only_coverage_pct"),
    ("point_area_px", "point_area_px"),
    ("point_pct", "point_area_pct"),
    ("cluster_area_px", "cluster_area_px"),
    ("cluster_pct", "cluster_area_pct"),
    ("fiber_area_px", "fiber_area_px"),
    ("fiber_pct", "fiber_area_pct"),
    ("median_area_px", "median_particle_area_px"),
    ("p90_area_px", "p90_particle_area_px"),
    ("diameter_um", "mean_particle_diameter_um"),
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


def build_anchor(reference: np.ndarray, settings):
    """Sestaví kotvu zarovnání z referenčního snímku.

    U dávkové analýzy je kotvou první snímek série; živě je jí **reference
    čistého sklíčka**, protože právě proti ní se všechno odečítá. Na ní se
    najdou horké pixely a „souhvězdí“ statických částic, podle kterého se
    pak každé měření srovná zpátky.

    Ořez se spočítá **jednou a napevno** (podíl plochy z nastavení), ne
    podle naměřeného driftu jako v dávce: živě drift dopředu neznáme a
    měnit vyhodnocovanou plochu během běhu by rozhýbalo procenta pokrytí,
    která se mají porovnávat mezi sebou.

    Vrací model, nebo ``None``, když zarovnání není zapnuté nebo se na
    referenci nenašlo dost zřetelných částic."""
    if not getattr(settings, "align_frames", True):
        return None
    analyzer = _analyzer()
    from .alignment import (AlignmentModel, detect_stars, find_hot_pixels,
                            repair_hot_pixels, safe_crop_rect)

    params = params_from_settings(settings)
    anchor = np.ascontiguousarray(reference, dtype=np.float32)
    binning = params.resolve_binning(anchor.shape[0])
    anchor = analyzer.apply_binning(anchor, binning)

    hot_mask = find_hot_pixels(anchor)
    anchor = repair_hot_pixels(anchor, hot_mask)
    stars = detect_stars(anchor, hot_mask=hot_mask,
                         star_count=params.align_star_count,
                         sigma=params.align_star_sigma)

    model = AlignmentModel(
        anchor=stars, anchor_path="reference", binning=binning,
        max_shift_px=int(params.align_max_shift_px),
        min_matches=int(params.align_min_matches),
        star_count=int(params.align_star_count),
        star_sigma=float(params.align_star_sigma),
        hot_mask=hot_mask,
        hot_pixel_count=int(hot_mask.sum()) if hot_mask is not None else 0,
        estimate_rotation=bool(params.align_rotation))

    if stars.count < params.align_min_matches:
        model.usable = False
        model.notes.append(
            "Na referenci se našlo jen {} zřetelných částic (potřeba {}) – "
            "zarovnání se nepoužije.".format(stars.count, params.align_min_matches))
        return model

    fraction = float(getattr(settings, "align_crop_fraction", 0.95))
    full_shape = (anchor.shape[0] * binning, anchor.shape[1] * binning)
    model.crop, model.crop_fraction = safe_crop_rect(
        full_shape, drift_px=0.0, mode="fixed", fraction=fraction)
    return model


def analyze_frame(gray: np.ndarray, reference: Optional[np.ndarray],
                  settings, when: Optional[datetime] = None,
                  anchor=None) -> Dict[str, float]:
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

    # --- srovnání driftu podle souhvězdí částic ---------------------------
    shift = None
    if anchor is not None and getattr(anchor, "usable", False):
        from .alignment import repair_hot_pixels, warp_to_anchor
        image = repair_hot_pixels(image, anchor.hot_mask)
        shift = anchor.measure(image)
        if shift.ok and not shift.is_identity:
            image = warp_to_anchor(image, shift)
        from .alignment import intersect_roi
        roi = intersect_roi(params.roi, anchor.crop)
        params = _replace(params, roi=roi)

    # Výřez se uplatní na snímek i na referenci stejně – po srovnání chybí
    # u okraje pruh, který do měření nepatří.
    image = analyzer.crop_to_roi(image, params.roi, binning)
    bias = analyzer.crop_to_roi(bias, params.roi, binning)

    stamp = when or datetime.now()
    metrics, _ = analyzer.analyze_prepared_frame(
        image, bias, params, index=0, filename="", filepath="",
        timestamp=stamp, t0=stamp, binning=binning)
    out = metrics_to_dict(metrics)
    out["binning"] = binning
    # Posun se do metrik zapisuje jen tehdy, když se opravdu použil –
    # odhad z jednoho páru částic je nesmysl a v tabulce by mátl.
    applied = shift is not None and shift.ok
    out["align_dx"] = float(shift.dx * binning) if applied else 0.0
    out["align_dy"] = float(shift.dy * binning) if applied else 0.0
    out["align_stars"] = int(shift.matched) if shift is not None else 0
    out["align_ok"] = 1 if applied else 0
    return out
