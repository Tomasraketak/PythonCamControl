# BMS Cam Control

Ovládací program s grafickým rozhraním pro mikroskopovou kameru
**BMS Microscopes RJ45 8MP 4K UHD Multioutput HDMI**, postavený nad
originálním SDK `uvcham` (verze 1.29030.20250722).

Podrobný soupis ovládacích prvků a jejich konstant v SDK je v [docs/prehled.md](docs/prehled.md).

## Co program umí

* **Živý náhled** s plynulým zoomem (kolečko myši), posunem tažením,
  režimy *Přizpůsobit oknu* / *1:1* a odečtem polohy a barvy pixelu pod kurzorem.
* **Expozice** – automatika, expoziční čas, zisk, cílový jas AE, potlačení
  blikání osvětlení (50 / 60 Hz / DC).
* **Vyvážení bílé** – ruční / automatické / podle vybrané oblasti, jednorázové
  vyvážení jedním tlačítkem, teplota barev a odstín, zisky R/G/B.
  Oblast pro WB se vybere myší přímo v obraze (*Zobrazení → Výběr oblasti pro WB*).
* **Obraz** – jas, kontrast, sytost, odstín, gama, ostrost, potlačení šumu,
  černobílý režim, negativ, převrácení vodorovně i svisle.
* **Zaostření a osvětlení** – režim ostření (ruční / automatické / jednorázové),
  poloha ostření absolutně i relativně, zóna ostření, indikace stavu ostření,
  jas zdroje světla, digitální zoom.
* **Video / přenos** – volba rozlišení a kodeku, datový tok, režim reálného času,
  pozastavení snímání, aktuální snímková frekvence.
* **Snímání** – uložení snímku (Ctrl+S), nahrávání videa do `.mp4` / `.mkv` /
  `.asf` přímo přes SDK a **časosběr** (automatické snímky v zadaném intervalu).
* **Měřicí překryvy** – mřížka třetin, nitkový kříž a kalibrovatelné měřítko
  v mikrometrech (*Zobrazení → Kalibrace měřítka*).
* **Profily nastavení** – všechna nastavení kamery se dají uložit do JSON
  a později znovu načíst.
* **Simulovaný režim** – aplikaci lze celou vyzkoušet i bez připojené kamery
  (`python main.py --demo`).

Ovládací prvky se **sestavují podle toho, co konkrétní kus kamery hlásí**.
Co firmware nepodporuje, se v panelu vůbec neobjeví – program tedy funguje
i s jinými modely postavenými na stejném SDK.

## Instalace (Windows – doporučeno)

Potřebujete Python 3.8 nebo novější.

```bat
git clone https://github.com/tomasraketak/PythonCamControl.git
cd PythonCamControl
spustit.bat
```

`spustit.bat` při prvním spuštění vytvoří virtuální prostředí, doinstaluje
závislosti a spustí aplikaci. Ručně totéž:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Knihovna `uvcham.dll` je součástí repozitáře (`bmscam/lib/x64`, `bmscam/lib/x86`)
a načte se automaticky podle toho, zda běžíte na 32- nebo 64bitovém Pythonu.
Ovladač kamery musí být nainstalovaný, kamera se hlásí jako UVC zařízení.

## Spuštění

```bash
python main.py            # normální provoz
python main.py --connect  # rovnou připojí první nalezenou kameru
python main.py --demo     # simulovaná kamera, bez hardwaru
python main.py --no-demo  # v seznamu nabídne jen skutečné kamery
python main.py --list     # vypíše nalezené kamery a stav SDK a skončí
```

## Klávesové zkratky

| Zkratka | Akce |
|---|---|
| `F5` / `F6` | připojit–odpojit / znovu vyhledat kamery |
| `Ctrl+S` | uložit snímek |
| `Ctrl+R` | spustit / zastavit nahrávání |
| `Ctrl+W` / `Ctrl+F` | vyvážení bílé / zaostřit |
| `Ctrl+0` / `Ctrl+1` | přizpůsobit oknu / velikost 1:1 |
| `Ctrl +` / `Ctrl -` | přiblížit / oddálit |
| `G` / `K` / `M` | mřížka / nitkový kříž / měřítko |
| `F11` | celá obrazovka |

Myš: kolečko = zoom, tažení = posun obrazu, dvojklik = přizpůsobit oknu.

## Linux

`uvcham.dll` je knihovna pro Windows. Na Linuxu se použije nativní SDK
ToupTek – stačí vložit `libtoupcam.so` do `bmscam/lib/x64/` (resp. `x86/`)
nebo na ni ukázat proměnnou prostředí:

```bash
export BMSCAM_TOUPCAM_LIB=/cesta/k/libtoupcam.so
python main.py
```

Přiložená `bmscam/lib/x86/libtoupcam.so` je **32bitová** – buď použijte
32bitový Python, nebo si stáhněte 64bitovou variantu od výrobce.
Nativní SDK neumí nahrávat video přímo, místo toho použijte *Časosběr*.
Stav obou SDK ukáže *Kamera → Diagnostika SDK*.

## Struktura projektu

```
main.py                       spouštěč
bmscam/
    app.py                    zpracování parametrů příkazové řádky
    spec.py                   katalog vlastností kamery (popisky, rozsahy, skupiny)
    uvcham.py                 modul z originálního SDK (nezměněný)
    toupcam_ctypes.py         binding pro nativní SDK ToupTek
    lib/x64, lib/x86          knihovny SDK
    backends/
        base.py               společné rozhraní backendů
        uvcham_backend.py     kamera přes uvcham.dll (Windows)
        toupcam_backend.py    kamera přes libtoupcam (Linux / macOS)
        demo.py               simulovaná kamera
    ui/
        main_window.py        hlavní okno, menu, snímání, profily
        controls.py           ovládací prvky generované z popisu vlastností
        video_view.py         plocha s obrazem, zoom, překryvy, výběr ROI
tests/test_smoke.py           testy bez hardwaru
docs/uvcham.h                 hlavičkový soubor SDK (reference)
```

## Testy

```bash
python tests/test_smoke.py     # nebo: python -m pytest tests
```

Testy běží bez kamery i bez displeje (Qt v režimu `offscreen`).

## Poznámky

* Program pracuje v režimu *pull mode* – snímky se vyzvedávají až v okně
  aplikace, takže nemůže dojít k záměně snímků.
* Rozlišení a kodek jde podle SDK měnit jen při zastaveném streamu; aplikace
  proto stream sama zastaví, přepne a znovu spustí.
* Binární knihovny SDK (`uvcham.dll`, `libtoupcam.so`) jsou majetkem výrobce
  kamery a jsou zde přiloženy pro pohodlí; řiďte se jejich licencí.
