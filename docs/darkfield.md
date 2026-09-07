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
4. **Spusťte měření.** V zadaném intervalu se vyhodnotí snímek a přibude
   řádek do tabulky. **Tabulka a graf…** otevře okno s průběhem,
   **CSV…** ho uloží.

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
