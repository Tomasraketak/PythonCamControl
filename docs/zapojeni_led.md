# Osvětlení: 4× FC101 (WS2812) kolem objektivu

Čtyři moduly FC101 tvoří strany čtverce okolo objektivu – prstencové
osvětlení, u kterého lze každou stranu ovládat zvlášť (jas i barvu), nebo
rozsvítit jen jednu stranu a získat tak šikmé osvětlení zvýrazňující reliéf
vzorku.

## Rozmístění a číslování

Modul je dlouhý 57,5 mm, takže čtverec má vnitřní stranu ≈ 58 mm a vnější
≈ 70 mm. Uprostřed zůstane otvor pro objektiv. Moduly se hodí přišroubovat
na tištěný nebo hliníkový rámeček, LED směřují dolů k vzorku.

Číslování v aplikaci **odpovídá pořadí zřetězení dat po směru hodinových
ručiček**, začíná se horní stranou:

```
                    ┌───────────────────────────┐
        D6 ──[470Ω]─►│ DIN   1 – HORNÍ    DOUT   │──┐
                    └───────────────────────────┘  │
        ┌──────────────┐                ┌──────────▼───┐
        │              │                │ DIN          │
        │  4 – LEVÝ    │    ◎ objektiv  │  2 – PRAVÝ   │
        │              │                │         DOUT │
        └──────▲───────┘                └──────────┬───┘
               │        ┌───────────────────────┐  │
               └────────│ DOUT   3 – DOLNÍ  DIN │◄─┘
                        └───────────────────────┘
```

Tok dat: `Arduino D6 → 1 (horní) → 2 (pravý) → 3 (dolní) → 4 (levý)`.
Výstup `DOUT` posledního modulu zůstane nezapojený.

Pokud si moduly zapojíte v jiném pořadí, stačí v aplikaci prohodit názvy
v `bmscam/leds.py` (`PANEL_NAMES`) – protokol ani sketch se nemění.

## Zapojení

| Vodič | Odkud | Kam |
|---|---|---|
| Data | Arduino Mega pin **D6** | přes odpor **330–470 Ω** na `DIN` modulu 1 |
| Data | `DOUT` modulu 1 → `DIN` modulu 2 | totéž pro 2→3 a 3→4 |
| +5 V | externí zdroj **5 V / 3 A** | `5V` (VCC) všech čtyř modulů |
| GND | externí zdroj | `GND` všech čtyř modulů |
| GND | externí zdroj | **GND Arduina** – společná zem je nutná |

Dále:

* **Kondenzátor 1000 µF / 10 V** (elektrolytický) mezi +5 V a GND hned
  u prvního modulu – potlačí proudové špičky při rozsvícení.
* **Odpor 330–470 Ω** v datové lince co nejblíž k prvnímu modulu.
* Datový vodič držte krátký (do ~50 cm) a veďte ho společně se zemí.

### Napájení – důležité

32 LED × max. 60 mA = **1,92 A** při plné bílé na plný jas. Proto:

* **Nenapájejte moduly z pinu 5V na Arduinu.** USB port dá dohromady jen
  asi 500 mA a deska se přetíží.
* Použijte samostatný zdroj 5 V, minimálně 2 A, s rezervou raději 3 A.
* Arduino zůstane napájené z USB kabelu od počítače (odtud jde i řízení).
* Sketch má navíc softwarovou pojistku
  `FastLED.setMaxPowerInVoltsAndMilliamps(5, 2000)` – knihovna sama sníží
  jas, kdyby odběr překročil 2 A. Limit si můžete v sketchi upravit.

Arduino Mega má 5V logiku, takže **převodník úrovní není potřeba** (na rozdíl
od ESP32 nebo Raspberry Pi s 3,3 V).

## Nahrání firmwaru

1. V Arduino IDE otevřete `arduino/bms_led_controller/bms_led_controller.ino`.
2. *Nástroje → Spravovat knihovny…* → nainstalujte **FastLED**.
3. *Nástroje → Vývojová deska* → **Arduino Mega 2560**, vyberte správný port.
4. Nahrajte sketch.
5. Ověření: *Nástroje → Sériový monitor*, rychlost **115200 Bd**, konec řádku
   „Nový řádek“. Po odeslání `PING` musí přijít:
   `READY BMSLED 1.0 PANELS=4 LEDS=8`.

Pak sériový monitor **zavřete** – port může používat jen jeden program.

## Ovládání z aplikace

V okně aplikace panel *Osvětlení (Arduino)* vpravo (zobrazí se i přes
*Zobrazení → Panel osvětlení*, `Ctrl+L`):

* **Připojení** – vyberte port desky a stiskněte *Připojit*. Po připojení se
  deska restartuje, aplikace počká a sama si vyžádá stav.
* **Všechny panely najednou** – hlavní vypínač, společný jas, barva
  z nabídky nebo vlastní z palety, tlačítka pro šikmé osvětlení
  (*shora / zprava / zdola / zleva*) a *kruhové* pro všechny strany.
* **Jednotlivé strany** – ovládací prvky jsou rozmístěné stejně jako moduly
  kolem objektivu. Každá strana má vlastní vypínač, jas, barvu, tlačítko
  *sólo* (rozsvítí jen ji) a *→ vše* (přenese barvu na ostatní).
* **Sériová konzole** – rozbalovací záznam komunikace a řádek pro ruční
  příkazy; hodí se při hledání závady.

Výsledný jas LED = barva × jas strany × hlavní jas. Vypnutá strana svítí
černě bez ohledu na jas.

## Příkazy protokolu

| Příkaz | Význam |
|---|---|
| `PING` | ohlášení desky a verze firmwaru |
| `STATE` | vypíše stav všech stran, zakončeno `OK` |
| `P <n> ON` / `OFF` | zapne/vypne stranu `n` (1–4) |
| `P <n> B <0-255>` | jas strany `n` |
| `P <n> C <r> <g> <b>` | barva strany `n` |
| `ALL ON` / `OFF` | zapne/vypne celé osvětlení |
| `ALL B <0-255>` | hlavní jas |
| `ALL C <r> <g> <b>` | barva všech stran |
| `ONLY <n>` | rozsvítí pouze stranu `n` |
| `SAVE` / `LOAD` | uloží / načte nastavení z EEPROM |

Každý příkaz odpoví `OK`, nebo `ERR <důvod>`.

## Poznámky k mikroskopii

* WS2812 míchá barvu ze tří úzkých spekter. Pro barevně věrné snímky
  nechte bílou na plné hodnotě (255, 255, 255), jas řiďte posuvníkem a
  v kameře udělejte vyvážení bílé (`Ctrl+W`) při tom jasu, na kterém budete
  snímat.
* Během série snímků (časosběr, ostření po krocích) jas neměňte – změna se
  projeví na expozici.
* Šikmé osvětlení (*sólo*) zvýrazní hrany a strukturu povrchu; postupné
  snímky ze čtyř stran se dají složit do jednoho s vyšším kontrastem reliéfu.
* Zabarvení jedné strany a protilehlé strany jinou barvou dobře ukáže sklon
  ploch – vyzkoušejte např. levý panel modrý, pravý oranžový.
