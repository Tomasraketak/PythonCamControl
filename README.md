# BMS Cam Control

Ovládací program s grafickým rozhraním pro mikroskopovou kameru
**BMS Microscopes RJ45 8MP 4K UHD Multioutput HDMI**, postavený nad
originálním SDK `uvcham` (verze 1.29030.20250722).

**Jak s programem pracovat: [docs/manual.md](docs/manual.md)** (podrobný manuál
k měření) nebo [docs/navod.md](docs/navod.md) (rychlejší průvodce obsluhou).
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
  Každý časosběr si založí vlastní podsložku `casosber_RRRRMMDD_HHMMSS`
  v pracovní složce a snímky v ní čísluje (`snimek_0001_…jpg`), takže se
  jednotlivé série nemíchají dohromady. Po skončení nahrávání se soubor
  automaticky zkontroluje a aplikace upozorní, když s ním něco není v pořádku.
* **Dark Field** – záložka pro sledování kontaminace witness sklíčka
  v temném poli: referenční snímek čistého sklíčka (průměr z N snímků,
  uložitelný do souboru), pravidelné měření v nastavitelném intervalu,
  práh podle šumu (σ) nebo pevný, filtr nejmenší částice, volitelně jen
  ve vybraném výřezu. Volitelně **měří postupně pod červeným, zeleným
  a modrým světlem** (625 / 520 / 470 nm) – u každého kanálu se dá zadat
  vlastní násobek expozice a posun ostření, protože každá barva ostří
  jinde a senzor na ni má jinou citlivost. Reference se snímá stejně,
  jedna pro každý kanál. Výsledky se zapisují do tabulky s grafem průběhu
  a dají se uložit do CSV. Rozbor běží ve vlastním vlákně, takže okno
  zůstane ovladatelné, a s každým měřením se ukládá i snímek – celou řadu
  jde kdykoli **spočítat znovu** s jiným prahem (*Zpětný rozbor…*), aniž by
  se muselo měřit od začátku. Podrobně v [docs/darkfield.md](docs/darkfield.md).
* **Měřicí překryvy** – mřížka třetin, nitkový kříž a kalibrovatelné měřítko
  v mikrometrech (*Zobrazení → Kalibrace měřítka*).
* **Přesné hodnoty** – u každé veličiny je vedle posuvníku i vstupní pole.
  Hodnotu jde napsat z klávesnice a potvrdit Enterem, nebo krokovat šipkami;
  posuvník a pole se drží spolu. U expozičního času tak jde nastavit přesné
  číslo, na které by se posuvníkem trefovalo těžko.
* **Světlý a tmavý vzhled** – `Ctrl+D` nebo ikona v horní liště; obě palety
  vycházejí ze stejného návrhového systému a volba se pamatuje mezi
  spuštěními. Widgety s vlastním stylopisem se překreslují za běhu.
* **Barevně / černobíle** – přepínač v horní liště přepíná kameru mezi
  barevným a monochromatickým obrazem (vlastnost `chrome` v SDK). Pro temné
  pole a měření po kanálech je čistší černobílý režim; barevná nastavení se
  v něm zašednou.
* **Kompletní nastavení** – tlačítka *Uložit vše…* a *Načíst…* v horní části
  levého panelu uloží do jednoho souboru JSON **všechno**: vlastnosti kamery
  včetně rozlišení a kodeku, osvětlení (jas, barvy, natočení modulů), nastavení
  rozboru temného pole i snímání (pracovní složka, interval časosběru, měřítko).
  Soubor se dá přiložit k naměřeným datům, takže je za měsíc jasné, za jakých
  podmínek vznikla. Starší profily, které měly jen vlastnosti kamery, se načtou
  taky. Soubory leží v podsložce `nastavení` uvnitř pracovní složky.
* **Živě totéž co dávkově** – okno *Tabulka a graf* u kamery ukazuje stejné
  veličiny a stejná čísla jako tabulka na obrazovce *Analýza*, včetně
  rychlostí změn a klasifikace fáze děje; hlídá to test, který porovná
  dávkový a živý průchod stejnou sérií řádek po řádku.
* **Obrazovka „Analýza“** – celý [DarkFieldAnalyzer](https://github.com/Tomasraketak/DarkFieldAnalyzer)
  uvnitř aplikace: výběr složky s měřením, volba reference, srovnání driftu
  sklíčka, všechny parametry rozboru, procházení snímek po snímku s barevnou
  klasifikační maskou, tabulka, souhrn, grafy, export a průvodce metodou.
  Jádro je vendorované v `bmscam/dfa/`, takže obě aplikace dávají na stejných
  datech stejná čísla.
* **Rozbor podle DarkFieldAnalyzeru** – metoda je převzatá z projektu
  [DarkFieldAnalyzer](https://github.com/Tomasraketak/DarkFieldAnalyzer):
  binning, oddělení difuzního oparu, práh z šumu měřeného mezi sousedními
  pixely, klasifikace na mikročástice / shluky / vlákna a skóre čistoty.
* **Vzorek v datech** – materiál (epoxid vytvrzený i nevytvrzený, PLA, PETG,
  kaptonová páska) a teplota vzorku se propíšou do názvů složek a souborů,
  hlavičky CSV i popisků grafu.
* **Průměrování snímků** – jedno měření temného pole vzniká z průměru
  několika snímků (výchozích pět za pět sekund); ukládá se a vyhodnocuje
  jen ten zprůměrovaný PNG, čímž šum senzoru klesne na 45 %.
* **Nic se neztratí** – zastavení měření uloží tabulku do CSV samo a nové
  spuštění začne s čistým grafem; snímky, na které rozbor nestačí, čekají ve
  frontě a dopočítají se (zbytek po zastavení měření), místo aby se zahazovaly; pořízená reference se ukládá automaticky
  i s popisem podmínek, za kterých vznikla.
* **Kontrola stálosti expozice** (☰ → *Kontrola stálosti expozice…*) – sleduje
  deset sekund hodnoty čtené z kamery i střední jas obrazu a řekne, jestli
  expozici něco nedorovnává na pozadí. Před měřením kontaminace se to vyplatí
  spustit.
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
python main.py --check-video ZAZNAM.MP4   # proč nejde přehrát video
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

Řádek **Jediný kanál** rozsvítí všechny čtyři strany jen jednou složkou RGB.
Každý čip WS2812 má tři samostatné LED s úzkým pásmem, takže se osvětlení
chová jako (široké) pásmové filtrování – u vzorků, které v některé části
spektra kontrastují líp, i v temném poli, kde na vlnové délce závisí rozptyl.

| Kanál | Typicky | Rozsah |
|---|---|---|
| Červená | 625 nm | 620–630 nm |
| Zelená | 520 nm | 515–530 nm |
| Modrá | 470 nm | 465–475 nm |

Údaje jsou z katalogových listů běžných WS2812B; kus od kusu se liší.

**Natočení modulů.** Který modul sketch adresuje jako první, závisí na tom,
kde se připojil datový vodič – popisky stran pak nemusí sedět na skutečnost.
Combo *Natočení* pod jednotlivými stranami to srovná: dejte „sólo“ horní
straně a vyberte tu, která se doopravdy rozsvítila. Výchozí hodnota je
*1. modul: pravý*, což odpovídá zapojení, na kterém se to zkoušelo.

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

## Když nejde přehrát nahrané video

Windows u vadného videa hlásí kód `0xC00D36C4`
(`MF_E_UNSUPPORTED_BYTESTREAM_TYPE`) – *tomuhle souboru nerozumím*. Příčiny
jsou dvě a je potřeba je rozlišit:

1. **Soubor není dokončený.** Kontejner MP4 má na konci rejstřík (`moov`),
   který se zapíše až při ukončení nahrávání. Když se zápis přeruší – dojde
   místo na disku, zavře se aplikace, odpojí se kamera nebo se během
   záznamu změní rozlišení – zůstanou v souboru jen data bez rejstříku
   a žádný přehrávač je neotevře.
2. **Soubor je v pořádku, jen ho neumí *tenhle* přehrávač.** Aplikace
   „Filmy a TV“ zvládne prakticky jen H.264 a HEVC. Když SDK zapíše MJPEG
   nebo MPEG-4 Part 2, Windows couvnou se stejným kódem – a VLC přitom
   video přehraje bez problémů.

Který případ nastal, řekne rozbor souboru:

```bat
python main.py --check-video C:\Users\...\video_20260904_144632.mp4
```

Totéž je v aplikaci pod **☰ → Zkontrolovat nahrané video…** a spouští se
samo po každém ukončeném nahrávání.

Aplikace proti prvnímu případu dělá tři věci: hlídá volné místo před
spuštěním záznamu, nedovolí během nahrávání změnit rozlišení ani kodek
(zastavení streamu by soubor přerušilo) a při zavření okna nebo odpojení
kamery záznam nejdřív řádně ukončí.

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
    workspace.py              kompletní nastavení v jednom souboru (bez Qt)
    qtenv.py                  nalezení knihoven Qt (řeší chybu qwindows.dll)
    videocheck.py             rozbor nahraného videa (proč nejde přehrát)
    darkfield.py              rozbor kontaminace v temném poli (bez Qt)
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
        darkfield_panel.py    záložka Dark Field – tabulka a graf kontaminace
        darkfield_worker.py   rozbor temného pole ve vlastním vlákně
arduino/bms_led_controller/   sketch pro Arduino Mega (FastLED)
tests/test_smoke.py           testy bez hardwaru
docs/manual.md                podrobný manuál k měření (příprava → vyhodnocení)
docs/navod.md                 návod k obsluze krok za krokem
docs/zapojeni_led.md          zapojení osvětlení a popis protokolu
docs/darkfield.md             postup měření kontaminace v temném poli
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
* Ve vlákně GUI se nedělá nic těžkého: rozbor temného pole má vlastní vlákno
  a simulovaná kamera si obraz kreslí ve svém. Do obsluhy snímku patří jen
  to, co musí proběhnout, dokud data snímku platí.
* Binární knihovny SDK (`uvcham.dll`, `libtoupcam.so`) jsou majetkem výrobce
  kamery a jsou zde přiloženy pro pohodlí; řiďte se jejich licencí.
