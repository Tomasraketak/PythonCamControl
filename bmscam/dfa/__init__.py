"""Rozbor temného pole – jádro převzaté z projektu DarkFieldAnalyzer.

Zdroj: https://github.com/Tomasraketak/DarkFieldAnalyzer (revize
``5353d84``). Moduly :mod:`analyzer`, :mod:`alignment`, :mod:`imageops`,
:mod:`frameio`, :mod:`reference`, :mod:`exporter` a :mod:`help_text` jsou
sem převzaté **beze změny výpočtů** – upravily se jen importy na relativní
a matplotlib se načítá až při kreslení grafů. Díky tomu dá BMS Cam Control
na stejných datech stejná čísla jako DarkFieldAnalyzer.

Modul :mod:`live` navíc počítá jeden snímek za běhu měření, aby se stejná
metoda dala použít i živě u kamery.
"""

from .live import (available, analyze_frame, build_anchor, resolve_binning,
                   apply_binning, estimate_noise, separate_haze,
                   cleanliness_score, params_from_settings,
                   AUTO_BINNING_TARGET_HEIGHT)

__all__ = ["available", "analyze_frame", "build_anchor", "resolve_binning",
           "apply_binning", "estimate_noise", "separate_haze",
           "cleanliness_score", "params_from_settings",
           "AUTO_BINNING_TARGET_HEIGHT"]
