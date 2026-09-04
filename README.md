# BMS Cam Control

Ovládací program s grafickým rozhraním pro mikroskopovou kameru
**BMS Microscopes RJ45 8MP 4K UHD Multioutput HDMI**, postavený nad
originálním SDK `uvcham` (verze 1.29030.20250722).

Podrobný soupis ovládacích prvků a jejich konstant v SDK je v [docs/prehled.md](docs/prehled.md).

Rozhraní vychází z návrhového systému **Modernist** – ostré tvary bez zaoblení,
červený akcent, sbalitelné boční panely a široká plocha pro živý obraz.
Zdrojový návrh je v [docs/design](docs/design/).

## Co program umí

* **Živý náhled** přes celý střed okna, s plynulým zoomem (kolečko myši),
  posunem tažením, režimy *Fit* / *1:1*, odečtem polohy a barvy pixelu pod
  kurzorem, proužkem s aktuální expozicí a ukazatelem nahrávání. Pozadí náhledu
  jde přepnout mezi tmavým a světlým.
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
  a znovu vyvolat z nabídky *Profil nastavení* v horní části levého panelu.
* **Sbalitelné panely** – levý (kamera) i pravý (osvětlení) panel se dají
  sbalit tlačítkem se šipkou a uvolnit tak celé okno pro obraz.
* **Osvětlení** – řízení čtyř modulů FC101 (8× WS2812) uspořádaných do stran
  čtverce kolem objektivu přes Arduino Mega: každá strana zvlášť (zapnutí, jas,
  barva), všechny najednou, i šikmé osvětlení jednou stranou. Podrobnosti
  a zapojení v [docs/zapojeni_led.md](docs/zapojeni_led.md).
* **Simulovaný režim** – aplikaci lze celou vyzkoušet i bez připojené kamery
  (`python main.py --demo`).

Ovládací prvky se **sestavují podle toho, co konkrétní kus kamery hlásí**.
Co firmware nepodporuje, se v panelu vůbec neobjeví – program tedy funguje
i s jinými modely postavenými na stejném SDK.

## Požadavky a připojení kamery

| | |
|---|---|
| Systém | Windows 7 a novější, 64bit (Windows 11 vyhovuje) |
| Python | 3.8 – 3.12, 64bitový (32bitový funguje také, načte se `lib/x86`) |
| Připojení kamery | **USB** – přiložené SDK ovládá kameru přes USB rozhraní |

**Důležité k „multioutput“ kameře:** knihovna `uvcham.dll` vyhledává kameru
podle USB identifikátorů (VID `0547`). Ovládání z této aplikace tedy funguje
jen tehdy, je-li kamera připojená **USB kabelem** k počítači. Výstupy HDMI
a RJ45 pracují samostatně (obraz do monitoru, resp. do sítě) a přes ně kameru
z počítače ovládat nelze. Jestli kamera USB vidíte, ověříte příkazem:

```bat
python main.py --list
```

Vypíše nalezené kamery a stav SDK. Pokud se v seznamu objeví jen simulovaná
kamera, není kamera připojená přes USB nebo chybí ovladač.

## Instalace (Windows – doporučeno)


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
python main.py --doctor   # diagnostika Qt, když nejde otevřít okno
```

## Klávesové zkratky

Ovládání je bez klasické nabídky – všechny příkazy jsou pod tlačítkem **☰**
vpravo nahoře, přehled zkratek pod **?** (nebo `F1`).

| Zkratka | Akce |
|---|---|
| `F1` | přehled klávesových zkratek |
| `F5` / `F6` | připojit–odpojit / znovu vyhledat kamery |
| `Ctrl+S` | uložit snímek |
| `Ctrl+R` | spustit / zastavit nahrávání |
| `Ctrl+W` / `Ctrl+F` | vyvážení bílé / zaostřit |
| `Ctrl+0` / `Ctrl+1` | přizpůsobit oknu / velikost 1:1 |
| `Ctrl +` / `Ctrl -` | přiblížit / oddálit |
| `G` / `K` / `M` | mřížka / nitkový kříž / měřítko |
| `Ctrl+L` | zobrazit / skrýt panel osvětlení |
| `F11` | celá obrazovka |

Myš: kolečko = zoom, tažení = posun obrazu, dvojklik = přizpůsobit oknu.

## Osvětlení WS2812 (Arduino)

Čtyři moduly FC101 tvoří strany čtverce okolo objektivu. Do Arduina Mega se
nahraje sketch `arduino/bms_led_controller/bms_led_controller.ino` (potřebuje
knihovnu **FastLED**), deska se připojí USB kabelem a v aplikaci se ovládá
panelem *Osvětlení (Arduino)* vpravo (`Ctrl+L`).

Ovládací prvky jsou rozmístěné stejně jako moduly kolem objektivu, takže je
hned vidět, která strana se ovládá. Kromě jasu a barvy každé strany zvlášť
jsou k dispozici tlačítka pro šikmé osvětlení (*shora / zprava / zdola /
zleva*), které zvýrazní reliéf vzorku.

> **Napájení:** 32 LED odebírá při plné bílé až 1,9 A – moduly potřebují
> samostatný zdroj 5 V / 3 A a společnou zem s Arduinem. Nikdy je nenapájejte
> z pinu 5V na desce. Kompletní schéma zapojení, seznam součástek a popis
> protokolu najdete v [docs/zapojeni_led.md](docs/zapojeni_led.md).

## Když aplikace nejde spustit

Hláška

```
qt.qpa.plugin: Could not find the Qt platform plugin "windows" in ""
```

znamená, že Qt nenašlo své zásuvné moduly (`platforms\qwindows.dll`). Cestu
k nim ovlivňují proměnné prostředí `QT_PLUGIN_PATH`
a `QT_QPA_PLATFORM_PLUGIN_PATH` a přepsat je umí kdekterá jiná instalace Qt
v systému – Anaconda, MSYS2 nebo i balíček `opencv-python`.

Aplikace si proto obě proměnné při startu sama nastaví na adresář patřící
k nainstalovanému PyQt5 a totéž zopakuje ještě jednou těsně před otevřením
okna. Když to přesto nestačí:

```bat
python main.py --doctor
```

Výpis ukáže, kde Qt hledá a jestli tam soubor `qwindows.dll` je. Podle toho:

* **modul platformy CHYBÍ** – instalace PyQt5 je neúplná:
  `pip install --force-reinstall PyQt5 PyQt5-Qt5`
* **PyQt5 NENAINSTALOVÁNO** – `pip install PyQt5`, nebo spouštíte jiný Python,
  než do kterého jste instalovali (výpis ukazuje cestu k použitému `python.exe`)
* **cesty ukazují jinam** – v systému máte natvrdo nastavenou proměnnou
  `QT_PLUGIN_PATH`; zrušte ji a spusťte znovu

Podrobný výpis hledání zapnete přes `set QT_DEBUG_PLUGINS=1 && python main.py`.

## Když SDK kameru nenajde

Kamera se hlásí i jako běžné UVC zařízení, takže aplikace umí obraz zobrazit
i bez SDK výrobce – přes OpenCV. Stačí doinstalovat:

```bat
pip install opencv-python
```

V seznamu kamer se pak objeví položka *UVC kamera #0*. Je to **záložní režim**:
obraz a základní veličiny fungují, ale ovladač nehlásí rozsahy hodnot, takže
jsou jen orientační. Pro plné ovládání používejte backend `uvcham`.

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
    qtenv.py                  nalezení knihoven Qt (řeší chybu qwindows.dll)
    spec.py                   katalog vlastností kamery (popisky, rozsahy, skupiny)
    uvcham.py                 modul z originálního SDK (nezměněný)
    toupcam_ctypes.py         binding pro nativní SDK ToupTek
    lib/x64, lib/x86          knihovny SDK
    backends/
        base.py               společné rozhraní backendů
        uvcham_backend.py     kamera přes uvcham.dll (Windows)
        toupcam_backend.py    kamera přes libtoupcam (Linux / macOS)
        demo.py               simulovaná kamera
    leds.py                   protokol osvětlení (bez závislosti na Qt)
    serialio.py               sériová linka k Arduinu
    backends/
        uvc_opencv.py         záložní obraz přes OpenCV (UVC)
    ui/
        theme.py              barvy, písmo, ikony a stylopis (Modernist)
        widgets.py            stavební prvky – karty, segmentové ovladače, panely
        main_window.py        hlavní okno, snímání, profily
        controls.py           ovládací prvky generované z popisu vlastností
        video_view.py         plocha s obrazem, zoom, překryvy, výběr ROI
        led_panel.py          panel osvětlení (Arduino)
arduino/bms_led_controller/   sketch pro Arduino Mega (FastLED)
tests/test_smoke.py           testy bez hardwaru
docs/zapojeni_led.md          zapojení osvětlení a popis protokolu
docs/design/                  zdrojový návrh rozhraní a jeho design system
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
