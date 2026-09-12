# Manuál: měření kontaminace witness sklíčka

Kompletní návod k aplikaci **BMS Cam Control** – od zapnutí kamery po
vyhodnocené měření. Předpokládá jen to, že máte sestavený mikroskop,
osvětlení a nainstalovaný program.

Kratší verze pro rychlý start je v [navod.md](navod.md), výklad samotné
metody v [darkfield.md](darkfield.md) a přímo v aplikaci na obrazovce
*Analýza* v záložce **Průvodce**.

---

## 1. Co aplikace dělá

V temném poli je čistý povrch sklíčka **tmavý** – světlo se od něj odráží
mimo objektiv. Každá částice, vlákno nebo film světlo rozptýlí a v obraze
**svítí**. Aplikace z toho dělá číslo:

1. nasnímá **referenci** čistého sklíčka (průměr N snímků),
2. od každého měřeného snímku referenci **odečte**,
3. co zbude nad prahem, změří: kolik procent plochy je pokryto, kolik je
   částic, jak jsou velké a jestli jde o prach, shluk, vlákno nebo opar.

Aplikace má dvě obrazovky (přepínač **Kamera / Analýza** nahoře):

| Obrazovka | K čemu |
|---|---|
| **Kamera** | živé snímání, osvětlení, měření v reálném čase |
| **Analýza** | dávkové vyhodnocení už nafocených sérií, prohlížení snímků |

Obě počítají **stejným jádrem**, takže výsledky jsou porovnatelné.

---

## 2. Příprava měření

### 2.1 Kamera

1. **Připojit kameru** (tlačítko vpravo nahoře nebo `F5`).
2. Zvolte **rozlišení** (karta *Kamera* vlevo). Měnit se dá jen při
   zastaveném snímání; program si stream sám zastaví a spustí.
3. Přepněte obraz na **Černobíle** (přepínač v horní liště). Pro temné pole
   je to čistší: odpadne demozaikování i barevný šum.
4. **Zaostřete** (záložka *Ostření*, `Ctrl+F` pro jednorázové zaostření).

### 2.2 Expozice – nejdůležitější krok

1. V záložce *Expozice* nechte zapnutou automatiku, dokud si obraz
   nesrovnáte.
2. Pak **automatiku vypněte** a čas i zisk dolaďte ručně.
3. Ověřte, že opravdu drží: ☰ → **Kontrola stálosti expozice…** deset
   sekund sleduje hodnoty i střední jas obrazu a řekne, jestli se něco
   nehýbe.

> **Proč to tolik řeším:** měření porovnává snímky mezi sebou. Když
> automatika mezi snímky změní expozici, změní se jas celého obrazu a
> analýza to uvidí jako přibývající zamlžení. Jedna zapomenutá automatika
> dokáže znehodnotit celé několikahodinové měření.

### 2.3 Osvětlení

V pravém panelu (`Ctrl+L`):

1. Připojte Arduino (**Hledat** → **Připojit**).
2. Nastavte **hlavní jas** a barvu. Pro temné pole se nejčastěji používá
   bílá nebo jediný kanál.
3. Jednotlivé strany se zapínají v kříži uprostřed panelu – rozmístění
   odpovídá tomu, jak moduly leží kolem objektivu.
4. **Natočení** (combo pod kartami stran) srovná popisky s realitou: dejte
   sólo horní straně a vyberte tu, která se doopravdy rozsvítila.

Tlačítka **625 / 520 / 470 nm** rozsvítí jen červený, zelený nebo modrý
kanál – černobílá kamera tak měří v úzkém pásmu.

### 2.4 Kam se ukládá

Výchozí složka je `Downloads\BMS fotky` přihlášeného uživatele. Změní se
ikonou složky v kartě *Snímání* nebo ☰ → *Složka pro ukládání…*.
Uvnitř vznikají podsložky:

```
BMS fotky\
├── darkfield_20260912_101500_pla_120C\   snímky jednoho měření + CSV
├── reference\                            reference (.npz) + popis (.json)
└── nastavení\                            uložená nastavení (.json)
```

---

## 3. Měření (obrazovka Kamera, záložka *Dark*)

### 3.1 Vzorek

Nahoře v panelu vyplňte, co měříte:

* **Materiál** – Blank (bez vzorku), epoxid vytvrzený / nevytvrzený, PLA,
  PETG, kaptonová páska, nebo *Vlastní…* s libovolným názvem.
* **Teplota** – na kolik stupňů je vzorek zahříván (0 = neuvedeno).

Údaje se propíší do **názvu složky se snímky, názvu CSV, hlavičky tabulky
i popisku grafu**, takže se měření nedají splést.

### 3.2 Reference

Vložte **čisté sklíčko** a dejte **Pořídit**. Zprůměruje se 16 snímků.

Reference se uloží sama do podsložky `reference` i s popisem podmínek
(expozice, zisk, osvětlení, práh). Z reference se zároveň postaví **kotva
zarovnání**: najdou se v ní horké pixely a „souhvězdí“ statických částic,
podle kterého se pak srovnává drift. U popisu reference je vidět, kolik
částic kotva má.

> **Reference stárne.** Když spustíte měření a reference je starší než
> **dvě minuty** (nebo žádná není), program si ji pořídí sám a hned po ní
> měření rozjede. Nemusíte na to myslet.

### 3.3 Nastavení vyhodnocení

| Volba | Co dělá | Kdy sáhnout |
|---|---|---|
| **σ nad šumem** / **Pevný práh** | práh = medián + σ × šum, nebo pevná hodnota v ADU | σ se samo přizpůsobí expozici – nechte ho |
| **Práh (σ)** | 4 je výchozí | níž = citlivější a víc šumu, výš = jen výrazné částice |
| **Min. částice** | menší skvrny se ignorují | zvyšte, když se počítá šum |
| **Interval** | jak často vzniká měření (5 s) | kontaminace roste v minutách |
| **Průměrovat snímků** | kolik snímků se zprůměruje do jednoho měření (5) | 1 = průměrování vypnuté |
| **Ukládat snímky** | archiv pro zpětný rozbor | nechte zapnuté, pokud máte místo |

Pod **Rozšířené nastavení** jsou volby, které se nastaví jednou: práh
zamlžení, hranice shluku, protáhlost a délka vlákna, srovnání driftu,
rozlišení rozboru (binning) a výřez.

### 3.4 Spuštění

**Spustit měření.** Během každého intervalu se pořídí pět snímků (jeden za
sekundu), zprůměrují se, průměr se uloží jako PNG a vyhodnotí. Snímek se
předtím srovná na referenci podle prachu, odečte se reference a ořízne se
okraj, který po srovnání chybí.

Průběh sledujte v **Tabulka a graf…**. Výchozí veličina v grafu je
*Kontaminace – pokrytí plochy [%]* – tedy přesně to, co počítá i dávková
analýza.

**Zastavit měření** dopočítá zbytek fronty a tabulku sama uloží do CSV.
Další spuštění začíná s čistým grafem.

### 3.5 Měření po kanálech (volitelné)

Zaškrtávátko **Postupně po kanálech (R → G → B)**: každé měření pořídí tři
snímky, pod červeným, zeleným a modrým světlem. U každého kanálu se dá
zadat násobek expozice a posun ostření (každá barva ostří jinde). Reference
se snímá stejně. Režim potřebuje **připojené Arduino** a **vypnutou
automatiku expozice**.

---

## 4. Vyhodnocení (obrazovka Analýza)

1. **Vybrat složku…** – ukáže se seznam měření i s počtem snímků.
2. **Referenční pozadí** – ze složky `reference`, nebo z prvních snímků
   série. *Srovnat drift* zapněte vždy, když se sklíčko mohlo pohnout.
3. **Parametry** – stejné jako u živého měření; *Obnovit výchozí hodnoty*
   vrátí doporučené.
4. **Spustit analýzu** – běží ve vlastním vlákně, jde zastavit.
5. Výsledek vpravo:
   * **Snímky** – procházení snímek po snímku s barevnou maskou
     (azurová = zamlžení, žlutá = mikročástice, červená = shluky,
     zelená = vlákna, fialová = hotspoty, křížek = těžiště),
   * **Tabulka** – všechny metriky,
   * **Souhrn** – reference, drift, průměry, fáze děje,
   * **Grafy** – souhrnné grafy (potřebují `matplotlib`),
   * **Průvodce** – výklad metody.
6. **Uložit výsledky…** zapíše CSV + JSON + PNG s grafy.
   **Načíst hotovou…** zobrazí dřív uloženou tabulku bez počítání.

---

## 5. Jak číst čísla

| Sloupec | Význam |
|---|---|
| **Pokrytí [%]** | kolik procent plochy je kontaminováno (částice + opar) – hlavní číslo |
| **Opar [%]** | difuzní zamlžení, typicky kondenzace nebo tenký film |
| **Mikročástic / Shluků / Vláken** | rozklad podle tvaru a velikosti |
| **Hustota částic [1/Mpx]** | nezávislá na rozlišení, dobrá pro porovnání mezi sestavami |
| **Skóre čistoty [%]** | 100 = dokonale čisté; souhrn pokrytí, oparu a hustoty |
| **Práh [ADU]** | jaký práh se na snímek použil |
| **Šum pozadí σ [ADU]** | šum senzoru – když roste, je něco s expozicí |
| **Rychlost pokrytí [%/s]** | jak rychle kontaminace přibývá |
| **Fáze děje** | „nárůst / zamlžování“, „odpařování / ústup“, „stabilní“ |
| **Drift X/Y [px], Spárovaných částic** | jestli zarovnání zabralo |

**Porovnávat se dají jen měření se stejnou referencí, expozicí a
osvětlením.** Procenta pokrytí navíc závisí na ořezu – proto je živě pevný.

---

## 6. Typické potíže

| Projev | Příčina | Řešení |
|---|---|---|
| Pokrytí skáče nahoru bez důvodu | zapnutá automatika expozice | vypnout, ověřit *Kontrolou stálosti expozice* |
| Najednou stovky „nových“ částic | posunulo se sklíčko a zarovnání nezabralo | zkontrolovat *Spárovaných částic*; málo prachu = kotva nemá podle čeho srovnávat |
| Měření hlásí zahozené snímky | rozbor nestíhá interval | delší interval, větší binning, nebo větší fronta |
| Reference „nesedí“ | mezi referencí a měřením se změnila expozice nebo osvětlení | pořídit novou (stačí spustit měření – udělá se sama) |
| Prázdná záložka *Grafy* | chybí `matplotlib` | `pip install matplotlib` |
| Okno se neotevře | Qt nenašlo zásuvné moduly | `python main.py --doctor` |

---

## 7. Co si uložit k datům

Ke každému měření patří:

* složka `darkfield_…` se snímky a CSV,
* soubor reference z `reference\` (`.npz` + `.json`),
* soubor kompletního nastavení (**Uložit vše…** v levém panelu).

S touhle trojicí jde měření za rok zopakovat i vysvětlit.
