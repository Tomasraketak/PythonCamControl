"""Nalezení knihoven Qt dřív, než se PyQt5 vůbec načte.

Nejčastější příčina hlášky

    qt.qpa.plugin: Could not find the Qt platform plugin "windows" in ""

je to, že Qt hledá zásuvné moduly (`platforms\\qwindows.dll`) jinde, než kde
je má PyQt5. Cestu totiž ovlivňují proměnné prostředí `QT_PLUGIN_PATH`
a `QT_QPA_PLATFORM_PLUGIN_PATH` a ty umí přepsat kdokoli – jiná instalace Qt
v systému, Anaconda, nebo balíček `opencv-python`, který si při importu
`cv2` nastaví vlastní adresář se zásuvnými moduly.

Tenhle modul proto proměnné nastaví na adresář, který patří k právě
běžícímu PyQt5, a totéž zopakuje ještě jednou těsně před vytvořením
QApplication (tedy až po importu `cv2`).
"""

import os
import sys
from typing import List, Optional

#: podadresáře, ve kterých mívají různé sestavy PyQt5 zásuvné moduly
_PLUGIN_SUBDIRS = ("Qt5/plugins", "Qt/plugins", "plugins")


def _plugin_name() -> str:
    """Soubor zásuvného modulu platformy pro tento operační systém."""
    if os.name == "nt":
        return "qwindows.dll"
    if sys.platform == "darwin":
        return "libqcocoa.dylib"
    return "libqxcb.so"


def plugins_dir() -> Optional[str]:
    """Adresář `plugins` patřící k nainstalovanému PyQt5, nebo None."""
    try:
        import PyQt5
    except ImportError:
        return None
    base = os.path.dirname(os.path.abspath(PyQt5.__file__))
    for sub in _PLUGIN_SUBDIRS:
        candidate = os.path.join(base, *sub.split("/"))
        if os.path.isdir(os.path.join(candidate, "platforms")):
            return candidate
    return None


def prepare() -> Optional[str]:
    """Nasměruje proměnné prostředí na zásuvné moduly z PyQt5.

    Vrátí použitý adresář, nebo None, když se nenašel (pak necháváme
    prostředí být – hledání si řídí Qt samo).
    """
    if os.environ.get("BMSCAM_KEEP_QT_ENV"):
        return None
    directory = plugins_dir()
    if not directory:
        return None
    os.environ["QT_PLUGIN_PATH"] = directory
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(directory, "platforms")
    return directory


def apply_library_path() -> None:
    """Přidá adresář se zásuvnými moduly přímo do seznamu cest Qt.

    Volá se až po importu PyQt5 – na rozdíl od proměnných prostředí tohle
    už žádný jiný balíček nepřepíše.
    """
    directory = prepare()
    if not directory:
        return
    try:
        from PyQt5.QtCore import QCoreApplication
    except ImportError:
        return
    if directory not in QCoreApplication.libraryPaths():
        QCoreApplication.addLibraryPath(directory)


def report() -> List[str]:
    """Řádky s diagnostikou prostředí Qt (pro přepínač --doctor)."""
    def item(name, value):
        return "{:<28}{}".format(name + ":", value)

    lines = [item("Python", f"{sys.version.split()[0]} ({sys.executable})"),
             item("Systém", sys.platform)]
    try:
        import PyQt5
        from PyQt5.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
        lines.append(item("PyQt5", f"{PYQT_VERSION_STR} (Qt {QT_VERSION_STR})"))
        lines.append(item("balíček", os.path.dirname(PyQt5.__file__)))
    except ImportError as exc:
        lines.append(item("PyQt5", f"NENAINSTALOVÁNO ({exc})"))
        lines.append(item("", "řešení:  pip install PyQt5"))
        return lines

    directory = plugins_dir()
    if directory:
        lines.append(item("zásuvné moduly", directory))
        plugin = os.path.join(directory, "platforms", _plugin_name())
        found = "nalezen" if os.path.exists(plugin) else "CHYBÍ"
        lines.append(item("modul platformy", f"{plugin}  – {found}"))
        if found != "nalezen":
            lines.append(item("", "řešení:  pip install --force-reinstall PyQt5 PyQt5-Qt5"))
    else:
        lines.append(item("zásuvné moduly",
                          "NENALEZENY – instalace PyQt5 je neúplná"))
        lines.append(item("", "řešení:  pip install --force-reinstall PyQt5 PyQt5-Qt5"))

    for name in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
                 "QT_QPA_PLATFORM", "QT_DEBUG_PLUGINS"):
        lines.append(item(name, os.environ.get(name, "(nenastaveno)")))

    try:
        from PyQt5.QtCore import QCoreApplication
        for path in QCoreApplication.libraryPaths():
            lines.append(item("cesta Qt", path))
    except Exception:
        pass
    return lines


#: co poradit uživateli, když se okno přesto nepodaří otevřít
HELP_TEXT = """
Nepodařilo se spustit grafické rozhraní Qt.

Co vyzkoušet:
  1) python main.py --doctor        vypíše, kde Qt hledá zásuvné moduly
  2) pip install --force-reinstall PyQt5 PyQt5-Qt5
  3) Máte-li v systému nastavenou proměnnou QT_PLUGIN_PATH nebo
     QT_QPA_PLATFORM_PLUGIN_PATH (typicky od Anacondy nebo jiné
     instalace Qt), zrušte ji a spusťte znovu.
  4) Podrobný výpis hledání:  set QT_DEBUG_PLUGINS=1 && python main.py
"""
