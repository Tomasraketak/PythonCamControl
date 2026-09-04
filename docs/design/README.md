# Zdrojový návrh rozhraní

Podklady, podle kterých je postavené současné rozhraní aplikace.

| Soubor | Obsah |
|---|---|
| `CamControl - Redesign.dc.html` | cílová podoba rozhraní (výchozí předloha) |
| `CamControl - Puvodni.dc.html` | podoba rozhraní před přepracováním |
| `_ds/modernist-styles.css` | design system Modernist – barvy, písmo, komponenty |
| `_ds/modernist-readme.md` | popis pravidel design systému |

Soubory `.dc.html` se otevřou v prohlížeči; obsahují návrh jako statické HTML.

## Jak se návrh promítá do aplikace

Hodnoty z design systému jsou přepsané do `bmscam/ui/theme.py`, ze kterého
vychází celý Qt stylopis. Když se změní barva nebo rozestup tam, promítne se
to do celé aplikace.

| Prvek návrhu | Odpovídá v kódu |
|---|---|
| barvy, rozestupy, písmo, ikony | `bmscam/ui/theme.py` |
| `.card`, `.seg`, `.tag`, boční panely | `bmscam/ui/widgets.py` |
| posuvníky a přepínače vlastností | `bmscam/ui/controls.py` |
| plocha s obrazem, proužky, prázdný stav | `bmscam/ui/video_view.py` |
| panel osvětlení | `bmscam/ui/led_panel.py` |
| horní lišta, nástrojová lišta, stavový řádek | `bmscam/ui/main_window.py` |

Návrh počítá s písmem **Archivo**. Pokud v systému není, použije se
Segoe UI (Windows), jinak systémové bezpatkové písmo – rozvržení se nemění.
