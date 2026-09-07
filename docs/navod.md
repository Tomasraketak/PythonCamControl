# Návod k obsluze

Provede vás programem od prvního spuštění po měření kontaminace. Popis
jednotlivých ovládacích prvků a jejich konstant v SDK je zvlášť
v [prehled.md](prehled.md); tenhle text popisuje postup práce.

---

## 1. Rozvržení okna

```
┌──────────┬─────────────────────────────────────┬──────────┐
│  levý    │                                     │  pravý   │
│  panel   │          živý obraz                 │  panel   │
│  kamera  │                                     │ osvětlení│
├──────────┴─────────────────────────────────────┴──────────┤
│  stavový řádek: rozlišení, FPS, počet snímků, hlášky      │
└───────────────────────────────────────────────────────────┘
```

* **Levý panel** – všechno kolem kamery, rozdělené do záložek
  (*Expozice*, *Barvy*, *Obraz*, *Ostření*, *Video*, *Dark*).
* **Pravý panel** – osvětlení přes Arduino (`Ctrl+L` ho schová i vyvolá).
* **☰ vpravo nahoře** – příkazy, které nemají vlastní tlačítko: pracovní
  složka, kalibrace měřítka, profily, diagnostika.
* Oba panely jde sbalit tlačítkem se šipkou a uvolnit tím celé okno pro obraz.

Ovládací prvky se sestavují podle toho, **co konkrétní kus kamery hlásí** –
když vaše kamera některou vlastnost nemá, prostě se nezobrazí. Prázdná
záložka tedy není chyba programu.

---

## 2. První spuštění

1. Zapojte kameru do USB 3.0 (modrý konektor) a spusťte `spustit.bat`, nebo
   `python main.py`.
2. Nahoře v levém panelu vyberte kameru ze seznamu a dejte **Připojit**
   (`F5`). Když je seznam prázdný, dejte **Znovu vyhledat** (`F6`).
3. Objeví se obraz. Když ne, projděte oddíl *Když SDK kameru nenajde*
   v [README](../README.md).

Bez kamery si program můžete celý vyzkoušet: `python main.py --demo`
nabídne simulovanou kameru, která se chová jako skutečná.

### Pracovní složka

**☰ → Pracovní složka** určuje, kam padají snímky, videa a měření. Nastavte
si ji hned na začátku – všechno ostatní z ní vychází a program si ji
pamatuje i po vypnutí.

---

## 3. Nastavení obrazu

Postupujte v tomhle pořadí, protože každý krok ovlivňuje ten další:

1. **Rozlišení** (záložka *Video*) – měnit se dá jen při zastaveném snímání,
   program si stream sám zastaví a znovu spustí. Během nahrávání to nejde
   vůbec (rozbil by se soubor) a program to odmítne.
2. **Expozice** (záložka *Expozice*) – nechte zapnutou automatiku, dokud si
   obraz nesrovnáte, pak ji **vypněte** a čas i zisk dolaďte ručně.
   Automatika mění jas mezi snímky, což vadí u časosběru i u měření
   kontaminace.
3. **Vyvážení bílé** (záložka *Barvy*) – u černobílé kamery nemá smysl.
   U barevné: *Zobrazení → Výběr oblasti pro WB*, vyberte myší kus bílého
   pozadí a dejte **Vyvážit**.
4. **Zaostření** (záložka *Ostření*) – ruční poloha, nebo jednorázové
   automatické zaostření (`Ctrl+F`).

### Přesné hodnoty

U každé veličiny je vedle posuvníku i vstupní pole. Hodnotu napíšete
z klávesnice a potvrdíte Enterem, nebo ji krokujete šipkami. Hodí se to
hlavně u expozičního času, kde má posuvník tisíce kroků a trefit se na
konkrétní číslo tažením je nemožné.

### Zoom a překryvy

Kolečko myši přibližuje, tažení posouvá, dvojklik vrátí obraz na velikost
okna. `Ctrl+0` je *Fit*, `Ctrl+1` je 1:1. Klávesy `G`, `K`, `M` zapínají
mřížku třetin, nitkový kříž a měřítko.

**Měřítko je potřeba zkalibrovat**, jinak ukazuje pixely: změřte objektovým
mikrometrem známou vzdálenost a zadejte poměr v **☰ → Kalibrace měřítka**.
Bez toho nedostanete plochu v µm² ani v měření kontaminace.

### Profily

Až budete s nastavením spokojení, uložte si ho: **Profil nastavení → Uložit**
v horní části levého panelu. Profil je obyčejný JSON a dá se přenést na jiný
počítač. Pro každý typ preparátu si můžete držet vlastní.

---

## 4. Snímání

| Co | Jak | Kam |
|---|---|---|
| Jeden snímek | `Ctrl+S` | pracovní složka, `snimek_RRRRMMDD_HHMMSS.jpg` |
| Video | `Ctrl+R`, znovu `Ctrl+R` ukončí | `video_RRRRMMDD_HHMMSS.mp4` |
| Časosběr | tlačítko *Časosběr* v záložce *Video* | vlastní podsložka `casosber_…` |

**Časosběr** si zakládá pro každý běh vlastní podsložku, aby se série
nemíchaly. Snímky v ní jdou po pořadí (`snimek_0001_…jpg`). Když se za celý
běh nepodaří uložit ani jeden, prázdná složka se po sobě smaže.

**Nahrávání** ukončete vždycky tlačítkem, ne zavřením programu. Rejstřík se
do souboru zapisuje až na konci; bez něj video nepůjde přehrát. Po skončení
si program soubor sám prohlédne a ozve se, když s ním něco není v pořádku –
nejčastěji jde o kodek, který Windows Media Player neumí (`0xC00D36C4`).
Kterýkoli soubor jde prohlédnout i dodatečně:

```bash
python main.py --check-video ZAZNAM.MP4
```

> **Místo na disku.** 4K záznam spolkne řádově gigabajt za minutu a časosběr
> po sekundách roste podobně. Když na disku dojde místo, video se utne
> uprostřed a nepůjde přehrát. Před delším během se na volné místo podívejte.

---

## 5. Osvětlení

Pravý panel (`Ctrl+L`) ovládá čtyři moduly WS2812 kolem objektivu. Prvky
jsou rozmístěné stejně jako moduly ve skutečnosti, takže je hned vidět,
která strana se ovládá.

* Každá strana zvlášť: zapnutí, jas, barva.
* **Vše** ovládá všechny čtyři najednou.
* **Šikmé osvětlení** (*shora / zprava / zdola / zleva*) rozsvítí jednu
  stranu – tím vynikne reliéf vzorku. Pro temné pole je tohle základ.
* **Jediný kanál** – tři tlačítka *625 / 520 / 470 nm* rozsvítí všechny
  strany jen červenou, zelenou nebo modrou složkou. Vlnová délka je
  vypsaná přímo na tlačítku, přesný rozsah v bublině. Hodí se, když vzorek
  kontrastuje líp v části spektra, a v temném poli, kde na vlnové délce
  závisí rozptyl na částicích. Než začnete měřit kontaminaci, kanál
  vyberte a už s ním nehýbejte – změna barvy znehodnotí referenci.

Zapojení, seznam součástek a protokol jsou v [zapojeni_led.md](zapojeni_led.md).

---

## 6. Měření kontaminace (Dark Field)

Celý postup i s vysvětlením metody je v [darkfield.md](darkfield.md), tady
je jen shrnutí kroků:

1. **Připravte osvětlení** pro temné pole a **vypněte automatiku expozice
   i zisku**. Od téhle chvíle už s osvětlením ani expozicí nehýbejte –
   měření porovnává snímky mezi sebou.
2. Vložte **čisté sklíčko** a v záložce *Dark* dejte **Pořídit** referenci.
   Zprůměruje se 16 snímků (jde změnit). Referenci si můžete **Uložit** a
   příště jen **Načíst**.
3. Vyměňte sklíčko za měřené, nastavte **interval** (výchozí 10 s) a dejte
   **Spustit měření**.
4. Průběh sledujte v **Tabulka a graf…**, výsledky uložte tlačítkem **CSV…**
   (středníky a BOM, takže to český Excel otevře rovnou).

### Zpětný rozbor

Pokud necháte zapnuté **Ukládat snímky pro zpětný rozbor** (výchozí stav),
každé měření uloží snímek do podsložky `darkfield_RRRRMMDD_HHMMSS`. Tlačítko
**Zpětný rozbor…** pak celou řadu spočítá znovu s právě nastaveným prahem,
minimální velikostí částice nebo výřezem – bez toho, abyste museli měřit
znovu.

Tohle je nejužitečnější věc na celé záložce: práh se dá dobře nastavit
až tehdy, když víte, jak data vypadají. Nechte měření běžet, pak si prahem
pohrajte a rozbor pusťte znovu.

Snímky ale zabírají místo (řádek pod zaškrtávátkem ukazuje kolik). Když ho
nemáte nazbyt, ukládání vypněte – měření samo poběží dál, jen ho nepůjde
zopakovat.

### Když měření nestíhá

Rozbor 4K snímku trvá desetiny sekundy a běží ve vlastním vlákně, aby
neblokoval okno. Když ho nastavíte na kratší interval, než jak dlouho rozbor
trvá, snímky se **zahazují** místo aby se hromadily – po zastavení měření to
program napíše do stavového řádku. Kontaminace roste v minutách, takže
interval 10 s je pro většinu měření až až; pod 1 s nemá smysl chodit.

---

## 7. Když se něco nedaří

| Příznak | Kde hledat |
|---|---|
| Okno se vůbec neotevře, hláška o `qwindows.dll` | `python main.py --doctor`, README → *Když aplikace nejde spustit* |
| Kamera není v seznamu | README → *Když SDK kameru nenajde* |
| Nahrané video nejde přehrát | `python main.py --check-video SOUBOR`, README → *Když nejde přehrát video* |
| Prázdná záložka bez ovládacích prvků | kamera tu skupinu vlastností nehlásí – není to chyba |
| Měření kontaminace skáče nahoru a dolů | zapnutá automatika expozice nebo zisku, případně se hnulo osvětlení |
| Plocha částic jen v pixelech | není zkalibrované měřítko (**☰ → Kalibrace měřítka**) |
| Ve sloupci *Částic* je pomlčka | chybí OpenCV: `pip install opencv-python` |

Ať se stane cokoli, `python main.py --list` vypíše, co program o kameře a SDK
ví, a `--doctor` totéž o prostředí Qt. S výpisem z těchhle dvou příkazů se
problém hledá mnohem líp než bez něj.
