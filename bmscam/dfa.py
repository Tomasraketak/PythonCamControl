"""Jádro rozboru temného pole převzaté z projektu **DarkFieldAnalyzer**.

Zdroj: https://github.com/Tomasraketak/DarkFieldAnalyzer (`analyzer.py`,
`imageops.py`). Tam se metoda odladila na skutečných sériích, tady je
přenesená na jeden snímek, aby šla počítat živě během měření.

Řetězec jednoho snímku:

1. **Rozdíl proti referenci** ve float32 a **bez ořezu na nulu** – záporná
   část je jediný nezkreslený odhad šumu pozadí.
2. **Oddělení oparu.** Nízkofrekvenční složka (kondenzace, zamlžení) se
   odhadne na silně zmenšeném obraze morfologickým otevřením a Gaussem,
   takže ji bodové částice neznečistí. ``sharp = diff − opar``.
3. **Práh z ostré složky.** Šum se odhaduje z **rozdílů sousedních pixelů**
   (MAD × 1,4826 / √2), ne z celkového rozdělení – struktura scény (zaschlý
   film, rozostřené halo) tak práh nevyžene nahoru a jemné částice nezmizí.
4. **Segmentace** ``connectedComponentsWithStats`` s ``CV_32S`` (u zašuměného
   4K snímku snadno vznikne přes 65 535 objektů, ``CV_16U`` by spadl).
5. **Klasifikace** na mikročástice / shluky / vlákna z momentů druhého řádu,
   takže šikmé vlákno pod 45° už není shluk.
6. **Metriky**: pokrytí (částice i opar), počty podle druhu, signál, ostrost,
   nehomogenita a souhrnné skóre čistoty.

Modul potřebuje OpenCV. Bez něj se v :mod:`bmscam.darkfield` použije
jednodušší původní metoda – ta OpenCV nevyžaduje.
"""

import math
from typing import Dict, Optional, Tuple

import numpy as np

#: Nad tento počet kontaminovaných pixelů se přeskočí výpočet momentů
#: (ochrana paměti u extrémně zašuměných snímků) a použije se opsaný obdélník.
MOMENT_PIXEL_LIMIT = 6_000_000

#: Cílová výška obrazu pro automatickou volbu binningu.
AUTO_BINNING_TARGET_HEIGHT = 1200


def resolve_binning(image_height: int, binning: int = 0) -> int:
    """Kolikrát zmenšit obraz před rozborem (0 = zvolit podle rozlišení).

    Binning je průměrování 2×2 nebo 4×4 (INTER_AREA), takže se nic
    nezahazuje náhodně jako u podvzorkování – navíc zlepšuje poměr
    signál/šum. Na 4K to je hlavní důvod, proč rozbor stíhá: bez něj se
    prahováním u šumu označí statisíce jednopixelových objektů a jejich
    segmentace trvá vteřiny."""
    if binning and int(binning) > 0:
        return max(1, int(binning))
    factor = 1
    while image_height // factor > AUTO_BINNING_TARGET_HEIGHT and factor < 4:
        factor *= 2
    return factor


def apply_binning(image: np.ndarray, binning: int) -> np.ndarray:
    if binning <= 1:
        return image
    cv2 = _cv2()
    h, w = image.shape[:2]
    return cv2.resize(image, (max(1, w // binning), max(1, h // binning)),
                      interpolation=cv2.INTER_AREA)


def _cv2():
    import cv2                                   # noqa: PLC0415
    return cv2


def available() -> bool:
    """True, když je k dispozici OpenCV, bez kterého tenhle rozbor neběží."""
    try:
        _cv2()
    except ImportError:
        return False
    return True


# --------------------------------------------------------------- šum a opar --
def estimate_noise(image: np.ndarray, sample_limit: int = 250_000
                   ) -> Tuple[float, float]:
    """Robustní odhad (medián, σ) šumu pozadí na podvzorku.

    Šum se odhaduje z rozdílů sousedních pixelů. Nezkreslí ho struktura
    scény (kontaminace je prostorově souvislá, šum se mění od pixelu
    k pixelu) a funguje i u snímků, které samy vstoupily do reference –
    tam je přes polovinu pixelů rozdílu přesně nulová, klasický MAD vyjde
    téměř nulový, práh spadne pod šum a rozbor „najde“ desetitisíce
    neexistujících částic."""
    if image.size == 0:
        return 0.0, 1.0
    step = max(1, int(math.sqrt(image.size / max(1, sample_limit))))
    patch = image[::step, ::step].astype(np.float32, copy=False)
    sample = patch.ravel()
    if sample.size == 0:
        return 0.0, 1.0

    median = float(np.median(sample))
    sigma = 0.0
    if patch.ndim == 2 and patch.shape[1] > 1:
        deltas = (patch[:, 1:] - patch[:, :-1]).ravel()
        sigma = (float(np.median(np.abs(deltas - np.median(deltas))))
                 * 1.4826 / math.sqrt(2.0))
    if not np.isfinite(sigma) or sigma <= 0.25:
        # Záložní odhady pro degenerované případy (dokonale hladké pozadí).
        mad_sigma = float(np.median(np.abs(sample - median))) * 1.4826
        lower_sigma = median - float(np.percentile(sample, 15.87))
        sigma = max(mad_sigma, lower_sigma)
    if not np.isfinite(sigma) or sigma <= 0.25:
        sigma = 0.25
    return median, sigma


def separate_haze(diff: np.ndarray, downscale: int = 16
                  ) -> Tuple[np.ndarray, np.ndarray]:
    """Rozdělí diferenci na nízkofrekvenční opar a jeho zmenšenou verzi."""
    cv2 = _cv2()
    h, w = diff.shape[:2]
    small_w = max(16, w // downscale)
    small_h = max(16, h // downscale)
    small = cv2.resize(diff, (small_w, small_h), interpolation=cv2.INTER_AREA)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    small = cv2.morphologyEx(small, cv2.MORPH_OPEN, kernel)
    small = cv2.GaussianBlur(small, (0, 0), sigmaX=2.0, sigmaY=2.0)
    haze_full = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    return haze_full, small


# ------------------------------------------------------------- tvary částic --
def shape_descriptors(labels: np.ndarray, n_labels: int, stats: np.ndarray
                      ) -> Tuple[np.ndarray, np.ndarray]:
    """(protáhlost, délka hlavní osy) pro každý objekt z momentů 2. řádu."""
    cv2 = _cv2()
    elongation = np.ones(n_labels, dtype=np.float64)
    major_axis = np.zeros(n_labels, dtype=np.float64)
    widths = stats[:, cv2.CC_STAT_WIDTH].astype(np.float64)
    heights = stats[:, cv2.CC_STAT_HEIGHT].astype(np.float64)

    flat = labels.ravel()
    nz = np.flatnonzero(flat)
    if nz.size == 0:
        return elongation, major_axis
    if nz.size > MOMENT_PIXEL_LIMIT:            # pojistka proti vyčerpání paměti
        max_dim = np.maximum(widths, heights)
        min_dim = np.maximum(np.minimum(widths, heights), 1.0)
        return max_dim / min_dim, max_dim

    lab = flat[nz].astype(np.int64, copy=False)
    ys, xs = np.divmod(nz, labels.shape[1])
    ys = ys.astype(np.float64, copy=False)
    xs = xs.astype(np.float64, copy=False)

    counts = np.maximum(np.bincount(lab, minlength=n_labels).astype(np.float64), 1.0)
    mx = np.bincount(lab, weights=xs, minlength=n_labels) / counts
    my = np.bincount(lab, weights=ys, minlength=n_labels) / counts
    # +1/12 = rozptyl rovnoměrného rozdělení uvnitř pixelu (diskrétní korekce)
    cxx = np.bincount(lab, weights=xs * xs, minlength=n_labels) / counts - mx * mx + 1.0 / 12.0
    cyy = np.bincount(lab, weights=ys * ys, minlength=n_labels) / counts - my * my + 1.0 / 12.0
    cxy = np.bincount(lab, weights=xs * ys, minlength=n_labels) / counts - mx * my

    tmp = np.sqrt(np.maximum(0.0, (cxx - cyy) ** 2 + 4.0 * cxy * cxy))
    lam_major = 0.5 * (cxx + cyy + tmp)
    lam_minor = np.maximum(0.0, 0.5 * (cxx + cyy - tmp))
    major_axis = 4.0 * np.sqrt(np.maximum(lam_major, 0.0))
    minor_axis = 4.0 * np.sqrt(lam_minor)
    elongation = major_axis / np.maximum(minor_axis, 1.0)
    return elongation, major_axis


class ParticleStats:
    """Roztřídění objektů jednoho snímku."""

    def __init__(self, lut: np.ndarray):
        self.category_lut = lut
        self.point_count = self.point_area_px = 0
        self.cluster_count = self.cluster_area_px = 0
        self.fiber_count = self.fiber_area_px = 0
        self.fiber_total_length_px = 0.0
        self.areas = np.zeros(0, dtype=np.float64)


def classify_components(labels, n_labels, stats, settings,
                        binning: int = 1) -> ParticleStats:
    """Rozdělí objekty na mikročástice, shluky a vlákna.

    Prahy plochy i délky se zadávají v pixelech **plného** rozlišení, aby
    nastavení nezáviselo na zvoleném binningu."""
    cv2 = _cv2()
    result = ParticleStats(np.zeros(max(n_labels, 1), dtype=np.uint8))
    if n_labels <= 1:
        return result
    lut = result.category_lut

    area_factor = 1.0 / float(max(1, binning) ** 2)
    length_factor = 1.0 / float(max(1, binning))
    min_area = max(1.0, float(settings.min_area_px) * area_factor)
    cluster_min = max(min_area + 1.0,
                      float(settings.cluster_min_area_px) * area_factor)
    min_fiber_len = max(3.0, float(settings.fiber_min_length_px) * length_factor)
    aspect_limit = max(1.2, float(settings.fiber_aspect_ratio))

    areas = stats[:, cv2.CC_STAT_AREA].astype(np.float64)
    elongation, major_axis = shape_descriptors(labels, n_labels, stats)

    valid = areas >= min_area
    valid[0] = False                                  # pozadí
    is_fiber = valid & (elongation >= aspect_limit) & (major_axis >= min_fiber_len)
    is_cluster = valid & ~is_fiber & (areas >= cluster_min)
    is_point = valid & ~is_fiber & ~is_cluster

    lut[is_point] = 1
    lut[is_cluster] = 2
    lut[is_fiber] = 3
    result.point_count = int(is_point.sum())
    result.point_area_px = int(areas[is_point].sum())
    result.cluster_count = int(is_cluster.sum())
    result.cluster_area_px = int(areas[is_cluster].sum())
    result.fiber_count = int(is_fiber.sum())
    result.fiber_area_px = int(areas[is_fiber].sum())
    result.fiber_total_length_px = float(major_axis[is_fiber].sum())
    result.areas = areas[valid]
    return result


# ------------------------------------------------------------------ doplňky --
def spatial_distribution(mask: np.ndarray, zones: int = 8
                         ) -> Tuple[float, float, float]:
    """Nehomogenita (0–100 %) a těžiště kontaminace (0–100 % šířky/výšky)."""
    cv2 = _cv2()
    mask_u8 = mask.astype(np.uint8, copy=False) if mask.dtype != np.uint8 else mask
    h, w = mask_u8.shape[:2]
    moments = cv2.moments(mask_u8, binaryImage=True)
    if moments["m00"] <= 0:
        return 0.0, 50.0, 50.0
    cx_pct = float(moments["m10"] / moments["m00"] / max(w, 1) * 100.0)
    cy_pct = float(moments["m01"] / moments["m00"] / max(h, 1) * 100.0)
    grid = cv2.resize((mask_u8 > 0).astype(np.float32), (zones, zones),
                      interpolation=cv2.INTER_AREA)
    mean_zone = float(grid.mean())
    if mean_zone <= 1e-9:
        return 0.0, cx_pct, cy_pct
    cv_score = float(grid.std()) / mean_zone
    heterogeneity = 100.0 * min(1.0, cv_score / math.sqrt(zones * zones - 1))
    return heterogeneity, cx_pct, cy_pct


def focus_score(image: np.ndarray, max_width: int = 960) -> float:
    """Ostrost obrazu jako rozptyl Laplaciánu (pozná rozostření i otřes)."""
    cv2 = _cv2()
    h, w = image.shape[:2]
    small = image[::max(1, w // max_width), ::max(1, w // max_width)] \
        if w > max_width else image
    return float(cv2.Laplacian(small, cv2.CV_32F, ksize=3).var())


def cleanliness_score(coverage_pct: float, haze_mean_adu: float,
                      density_per_mpx: float) -> float:
    """Souhrnný index čistoty 0–100 % (100 % = dokonale čisté sklíčko).

    Každá složka je saturující exponenciála, takže skóre je spojité a
    neskočí skokem na nulu. Rozpočet: pokrytí 45 b., opar 30 b., hustota
    částic 25 b."""
    p_cov = 45.0 * (1.0 - math.exp(-max(0.0, coverage_pct) / 2.0))
    p_haze = 30.0 * (1.0 - math.exp(-max(0.0, haze_mean_adu) / 8.0))
    p_part = 25.0 * (1.0 - math.exp(-max(0.0, density_per_mpx) / 120.0))
    return float(max(0.0, min(100.0, round(100.0 - (p_cov + p_haze + p_part), 1))))


# ------------------------------------------------------------ rozbor snímku --
def analyze_frame(gray: np.ndarray, reference: Optional[np.ndarray],
                  settings) -> Dict[str, float]:
    """Spočítá metriky jednoho snímku podle metody DarkFieldAnalyzeru."""
    cv2 = _cv2()
    image = np.ascontiguousarray(gray, dtype=np.float32)
    if reference is None:
        # Bez reference je pozadím nízkofrekvenční složka samotného snímku;
        # konstanta by nechala nerovnoměrné osvětlení v obraze.
        bias = np.full_like(image, float(np.median(image)))
    else:
        bias = np.asarray(reference, dtype=np.float32)
        if bias.shape[:2] != image.shape[:2]:
            bias = cv2.resize(bias, (image.shape[1], image.shape[0]),
                              interpolation=cv2.INTER_AREA)

    binning = resolve_binning(image.shape[0], int(getattr(settings, "binning", 0)))
    if binning > 1:
        image = apply_binning(image, binning)
        bias = apply_binning(bias, binning)
    px_scale = float(binning * binning)       # px po binningu → px plného rozlišení

    h, w = image.shape[:2]
    total_pixels = float(h * w)

    diff = cv2.subtract(image, bias)
    haze_full, haze_small = separate_haze(diff)
    bg_level, bg_sigma = estimate_noise(diff)
    sharp = cv2.subtract(diff, haze_full)

    sharp_median, sharp_sigma = estimate_noise(sharp)
    if settings.threshold_mode == "absolute":
        threshold = float(settings.absolute)
    else:
        threshold = sharp_median + float(settings.sigma) * sharp_sigma
    threshold = max(threshold, float(settings.min_threshold_adu), 0.5)

    mask_sharp = (sharp > threshold).astype(np.uint8)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask_sharp, connectivity=8, ltype=cv2.CV_32S)
    particles = classify_components(labels, n_labels, stats, settings, binning)
    classified = particles.category_lut[labels]
    mask_particles = classified > 0

    haze_thr = float(settings.haze_threshold)
    haze_mask_small = haze_small > haze_thr
    haze_pixels = int(haze_mask_small.sum())
    haze_pct = 100.0 * haze_pixels / float(haze_small.size) if haze_small.size else 0.0
    haze_mean = float(haze_small[haze_mask_small].mean()) if haze_pixels else 0.0
    haze_max = float(haze_small.max()) if haze_small.size else 0.0

    mask_total = mask_particles | (haze_full > haze_thr)
    total_area = int(mask_total.sum())
    coverage_pct = 100.0 * total_area / total_pixels if total_pixels else 0.0

    if total_area:
        integrated = float(np.sum(diff, where=mask_total, dtype=np.float64))
        mean_signal = integrated / total_area
    else:
        integrated = mean_signal = 0.0
    max_signal = float(diff.max()) if diff.size else 0.0

    heterogeneity, cx_pct, cy_pct = spatial_distribution(mask_total)
    areas = particles.areas
    count = int(areas.size)
    megapixels = total_pixels * px_scale / 1e6
    density = count / megapixels if megapixels > 0 else 0.0
    scale = float(settings.um_per_px)
    particle_area = int(round((particles.point_area_px + particles.cluster_area_px
                               + particles.fiber_area_px) * px_scale))

    return {
        "coverage_pct": coverage_pct,
        "particles": count,
        "particle_area_px": particle_area,
        "area_um2": total_area * px_scale * scale * scale if scale else 0.0,
        "mean_signal": mean_signal,
        "max_signal": max_signal,
        "bg_level": bg_level,
        "bg_sigma": bg_sigma,
        "threshold": threshold,
        "snr": mean_signal / bg_sigma if bg_sigma > 0 else 0.0,
        "haze_pct": haze_pct,
        "haze_mean": haze_mean,
        "haze_max": haze_max,
        "points": particles.point_count,
        "clusters": particles.cluster_count,
        "fibers": particles.fiber_count,
        "fiber_len_px": particles.fiber_total_length_px * binning,
        "density_mpx": density,
        "mean_area_px": float(areas.mean()) * px_scale if count else 0.0,
        "max_area_px": int(areas.max() * px_scale) if count else 0,
        "heterogeneity_pct": heterogeneity,
        "centroid_x_pct": cx_pct,
        "centroid_y_pct": cy_pct,
        "focus": focus_score(image),
        "saturated_px": int((image >= float(settings.saturation_adu)).sum() * px_scale),
        "cleanliness": cleanliness_score(coverage_pct, haze_mean, density),
        "binning": binning,
    }
