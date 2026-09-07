# Sledování kontaminace v temném poli

Záložka **Dark** slouží k měření, jak na witness sklíčku přibývá depozit,
film a částice. Metoda stojí na tom, že v temném poli je čisté sklíčko
tmavé a všechno, co na něm ulpí, rozptyluje světlo a svítí.

## Postup měření

1. **Připravte osvětlení a expozici.** Sklíčko musí být tmavé a částice
   jasné. Vypněte automatickou expozici (záložka *Expozice*) – jinak se
   jas mění mezi snímky a měření nemá s čím porovnávat. Totéž platí pro
   zisk. Osvětlení nechte po celou dobu měření beze změny.
2. **Pořiďte referenční snímek.** Vložte čisté sklíčko a stiskněte
   **Pořídit**. Aplikace zprůměruje zadaný počet snímků (výchozích 16),
   čímž potlačí šum senzoru. Reference zachytí i to, co není kontaminace:
   nerovnoměrné osvětlení, prach na optice, vadné pixely. To všechno se
   pak z měření odečte.
   Referenci jde uložit (`.npz`) a příště načíst – ale jen když se od té
   doby nezměnila expozice, zisk, osvětlení ani rozlišení.
3. **Nastavte práh.** Viz níže.
4. **Spusťte měření.** V zadaném intervalu (výchozích 10 s) se vyhodnotí
   snímek a přibude řádek do tabulky. **Tabulka a graf…** otevře okno
   s průběhem, **CSV…** ho uloží.

## Měření po kanálech (R → G → B)

Kamera je černobílá, ale osvětlení umí svítit jen jednou složkou RGB.
Snímek pořízený pod jednou barvou je tedy měření v úzkém pásmu, a tři
snímky za sebou dají tři vlnové délky: 625, 520 a 470 nm.

Zaškrtnutí **Postupně po kanálech** to zapne. Každé měření pak proběhne
takto:

1. osvětlení se přepne na červenou, nastaví se expozice a ostření kanálu,
2. počká se dobu **Ustálení**, než se to projeví v obrazu,
3. pořídí se a vyhodnotí snímek,
4. totéž pro zelenou a modrou,
5. expozice, ostření i barva osvětlení se vrátí do původního stavu.

Reference se snímá stejným způsobem – vznikne jedna pro každý kanál a
uloží se všechny do jednoho `.npz`. Bez toho by měření nedávalo smysl:
sklíčko má pod každou barvou jiný jas.

### Expozice a ostření po kanálech

Každá barva se láme jinak, takže ostří jinde, a senzor na ni má jinou
citlivost. Proto má každý kanál dvě vlastní čísla:

* **expozice** – násobek expozičního času nastaveného v záložce
  *Expozice*. Modrá typicky potřebuje delší čas než zelená.
* **ostření** – posun polohy ostřicího motorku v jeho krocích. 0 znamená
  neměnit.

Obojí se hledá pokusem: zapněte kanál tlačítkem *Jediný kanál* v panelu
osvětlení, dolaďte obraz ručně a rozdíl proti základnímu nastavení zadejte
sem.

### Na co si dát pozor

* **Režim vyžaduje ruční expozici.** Se zapnutou automatikou by se čas
  měnil sám a násobky by neznamenaly nic; aplikace to odmítne spustit.
* **Potřebuje připojené Arduino** – barvy rozsvěcí ono.
* Jeden cyklus trvá zhruba `3 × (ustálení + doba rozboru)`. Při ustálení
  0,4 s a 4K snímcích počítejte s dvěma až třemi sekundami, takže interval
  pod pět sekund nemá smysl.
* Tabulka i graf pak vedou tři řady zvlášť; ve sloupci **Kanál** je vidět,
  ke které barvě řádek patří. Uložené snímky mají barvu v názvu, takže
  zpětný rozbor si na každý vezme referenci jeho kanálu.

## Zpětný rozbor

Práh se dobře nastavuje až tehdy, když víte, jak data vypadají – jenže to
je obvykle po měření, ne před ním. Proto se s každým měřením ukládá i
samotný snímek, ze kterého se počítalo.

Zaškrtávátko **Ukládat snímky pro zpětný rozbor** (výchozí stav) založí
pro každý běh podsložku `darkfield_RRRRMMDD_HHMMSS` v pracovní složce.
Tlačítko **Zpětný rozbor…** pak celou řadu spočítá znovu podle právě
nastaveného prahu, minimální velikosti částice a výřezu. Původní tabulka
se nahradí, takže si ji předtím případně uložte do CSV.

Ukládá se šedotónový snímek v uint8 – přesně to, z čeho rozbor počítá,
takže zpětný rozbor dá se stejným nastavením bit po bitu stejná čísla
jako živé měření. Když je po ruce OpenCV, jde snímek do PNG; v temném
poli je skoro celý černý, takže se komprimuje na zlomek. Řádek pod
zaškrtávátkem průběžně ukazuje, kolik už archiv zabírá – když místo
na disku není, ukládání vypněte, měření samo poběží dál.

Zpětný rozbor umí načíst i složku ze starších běhů, ne jen z toho
posledního.

## Výkon

Rozbor 4K snímku trvá kolem desetiny sekundy. Aby kvůli němu neztuhlo
okno, běží ve vlastním vlákně – v obsluze snímku se dělá jen šedotónová
kopie, dokud jsou data platná. Fronta má hloubku jedna: když rozbor
nestíhá zadaný interval, snímek se **zahodí** místo aby se hromadil,
a po zastavení měření to program napíše do stavového řádku. Když se to
stává, prodlužte interval.

Úroveň pozadí a šum se počítají z rovnoměrného vzorku pixelů, ne z celého
snímku. Na 4K je to rozdíl mezi stovkami milisekund a jednotkami
milisekund, a na výsledku se to neprojeví: obojí je odhad statistiky
pozadí, které zabírá drtivou většinu plochy. **Prahuje se pak celý
snímek**, takže se žádná částice neztratí.

## Práh

* **σ nad šumem** (výchozí) – práh se počítá jako *pozadí + σ × šum*.
  Šum se odhaduje robustně z odchylky od mediánu, takže ho samotné
  částice nenafouknou. Tenhle režim se sám přizpůsobí expozici i zisku
  a je vhodný pro většinu měření. Výchozí σ = 5 znamená, že náhodný šum
  projde přes práh přibližně jednou z milionu pixelů.
* **Pevný práh** – hodnota v jednotkách jasu (ADU) nad referencí. Používá
  se, když je potřeba porovnávat měření mezi sebou v absolutních číslech.

**Min. částice** odfiltruje skvrny menší než zadaný počet pixelů. Jeden
až dva jasné pixely bývají šum, ne částice.

## Co se měří

| Sloupec | Význam |
|---|---|
| Pokrytí [%] | podíl plochy, který je nad prahem – hlavní ukazatel |
| Částic | počet oddělených skvrn (vyžaduje OpenCV) |
| Plocha částic [px] / [µm²] | jejich celková plocha; µm² jen po kalibraci měřítka |
| Průměrný signál [ADU] | jak jasné částice jsou – rozliší silný depozit od slabého filmu |
| Maximum [ADU] | nejjasnější bod snímku |
| Šum pozadí [ADU] | odhad šumu; skokový růst znamená změnu podmínek |
| Práh [ADU] | práh, který se pro daný snímek použil |

Panel navíc ukazuje **trend** – směrnici posledních měření v % za minutu,
tedy jak rychle kontaminace přibývá.

## Na co si dát pozor

* **Bez reference** se za pozadí bere medián snímku. Měření pak ukáže
  jednotlivé částice, ale ne rovnoměrný film – ten se v mediánu ztratí.
* **Změna expozice, zisku nebo osvětlení uprostřed měření** posune celý
  obraz a vypadá jako skoková kontaminace. Poznáte to podle sloupce
  *Šum pozadí* a podle toho, že se změna projeví naráz.
* **Změna rozlišení** referenci znehodnotí – aplikace to pozná a řekne si
  o novou.
* **Počet částic** potřebuje OpenCV (`pip install opencv-python`). Bez něj
  zůstanou plošné metriky a ve sloupci *Částic* je pomlčka.
* Měří se to, co kamera vidí. Prach na objektivu, který se pohne, je
  neodlišitelný od prachu na sklíčku.

## Výřez

Zaškrtnutí **Měřit jen ve vybraném výřezu** omezí rozbor na oblast
vybranou v obraze (☰ → *Výběr oblasti*). Hodí se, když je v záběru
i držák sklíčka nebo okraj s odlesky. Výřez se použije i pro referenci,
takže ji po změně výřezu pořiďte znovu.

## Formát CSV

Oddělovačem je středník a soubor je v UTF-8 s BOM, takže ho český Excel
otevře správně rovnou. V hlavičce jsou zakomentované řádky s nastavením
měření a s popisem reference, aby šlo z odstupu poznat, za jakých
podmínek data vznikla.
