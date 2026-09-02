# Přehled ovládacích prvků

Které prvky se v aplikaci objeví, závisí na tom, co kamera hlásí přes
`Uvcham_range()`. Níže je úplný seznam podporovaných vlastností a jejich
konstant v SDK.

| Panel | Prvek | Konstanta SDK (uvcham) | Nativní SDK (toupcam) |
|---|---|---|---|
| Expozice | Automatická expozice | `UVCHAM_AEXPO` | `put_AutoExpoEnable` |
| Expozice | Expoziční čas | `UVCHAM_EXPOTIME` | `put_ExpoTime` |
| Expozice | Zisk | `UVCHAM_AGAIN` | `put_ExpoAGain` |
| Expozice | Cílový jas AE | `UVCHAM_AEXPOTARGET` | `put_AutoExpoTarget` |
| Expozice | Frekvence sítě | `UVCHAM_HZ` | `put_HZ` |
| Bílá | Režim WB | `UVCHAM_WBMODE` | – |
| Bílá | Vyvážit bílou nyní | `UVCHAM_WBMODE = 3` | `AwbOnce` |
| Bílá | Oblast pro WB (ROI) | `UVCHAM_WBROI*` | – |
| Bílá | Teplota barev / odstín | `UVCHAM_TEMP`, `UVCHAM_TINT` | `put_TempTint` |
| Bílá | Zisky R/G/B | `UVCHAM_WBRED/GREEN/BLUE` | `put_WhiteBalanceGain` |
| Obraz | Jas, kontrast, sytost, odstín, gama | `UVCHAM_BRIGHTNESS`, … | `put_Brightness`, … |
| Obraz | Ostrost, potlačení šumu | `UVCHAM_SHARPNESS`, `UVCHAM_DENOISE` | – |
| Obraz | Černobíle / negativ | `UVCHAM_CHROME`, `UVCHAM_NEGATIVE` | `put_Chrome`, `put_Negative` |
| Obraz | Převrácení | `UVCHAM_FLIPHORZ/VERT` | `put_HFlip`, `put_VFlip` |
| Ostření | Režim ostření | `UVCHAM_AFMODE` | `put_AFMode` |
| Ostření | Poloha ostření | `UVCHAM_AFPOSITION`, `…_ABSOLUTE` | – |
| Ostření | Zóna a stav ostření | `UVCHAM_AFZONE`, `UVCHAM_AFFEEDBACK` | `get_AFState` |
| Ostření | Jas osvětlení | `UVCHAM_LIGHT_ADJUSTMENT` | – |
| Ostření | Digitální zoom | `UVCHAM_ZOOM` (jen zápis) | – |
| Video | Rozlišení / kodek | `UVCHAM_RES`, `UVCHAM_CODEC` | `put_eSize` |
| Video | Datový tok | `UVCHAM_BPS` | – |
| Video | Reálný čas / pozastavení | `UVCHAM_REALTIME`, `UVCHAM_PAUSE` | `put_RealTime`, `Pause` |

## Průběh práce s SDK

```
Uvcham_enum   →  Uvcham_open  →  nastavení formátu a rozlišení
              →  Uvcham_start (pull mode, bez bufferu)
              →  callback UVCHAM_EVENT_IMAGE  →  Uvcham_pull
              →  Uvcham_close
```

Callback přichází z interního vlákna knihovny, aplikace jej proto přeposílá
Qt signálem do hlavního vlákna a teprve tam vyzvedne snímek.
