"""Záchytná síť na neodchycené výjimky.

PyQt5 od verze 5.5 volá při neodchycené výjimce ve slotu ``qFatal``, tedy
**ukončí celý proces** – uživatel vidí jen zmizelé okno a v terminálu
traceback. Jedna chyba v obsluze kliknutí tak zahodí rozdělané měření.

Tenhle modul nastaví ``sys.excepthook`` tak, aby se výjimka ukázala
v dialogu a program běžel dál. Stejný postup má i původní
DarkFieldAnalyzer (``gui.install_exception_hook``).
"""

import sys
import traceback

_installed = False


def install(app_name: str = "BMS Cam Control") -> None:
    """Zapne dialog místo pádu. Opakované volání nic nezkazí."""
    global _installed
    if _installed:
        return
    _installed = True
    previous = sys.excepthook

    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc_value, exc_tb)
            return
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        sys.stderr.write(details)
        try:
            from PyQt5.QtWidgets import QApplication, QMessageBox
            if QApplication.instance() is None:
                return
            box = QMessageBox(QMessageBox.Critical, app_name,
                              "V programu nastala chyba:\n{}: {}\n\n"
                              "Aplikace běží dál, ale tahle akce se "
                              "nedokončila.".format(exc_type.__name__, exc_value))
            box.setDetailedText(details)
            box.exec_()
        except Exception:                                   # noqa: BLE001
            pass                                            # dialog není důležitější než běh

    sys.excepthook = hook
