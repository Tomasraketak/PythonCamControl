/*
  BMS LED Controller — řízení 4 modulů FC101 (8× WS2812) z aplikace BMS Cam Control.
  ---------------------------------------------------------------------------------
  Deska:    Arduino Mega 2560 (funguje i na Uno/Nano)
  Knihovna: FastLED (Nástroje → Spravovat knihovny → "FastLED")
  Zapojení: viz docs/zapojeni_led.md

  Moduly jsou zřetězené za sebou (DOUT → DIN), takže tvoří jeden pás 32 LED.
  Panel = jeden modul = 8 po sobě jdoucích LED.

  Komunikace: sériová linka, 115200 Bd, příkazy ukončené znakem nového řádku.

    PING                     -> READY BMSLED <verze> PANELS=4 LEDS=8
    STATE                    -> vypíše stav všech panelů, zakončeno OK
    P <n> ON | OFF           -> zapne/vypne panel n (1..4)
    P <n> B <0-255>          -> jas panelu n
    P <n> C <r> <g> <b>      -> barva panelu n
    ALL ON | OFF             -> zapne/vypne všechny panely
    ALL B <0-255>            -> společný (hlavní) jas
    ALL C <r> <g> <b>        -> barva všech panelů
    ONLY <n>                 -> zapne pouze panel n, ostatní zhasne (šikmé osvětlení)
    SAVE                     -> uloží nastavení do EEPROM
    LOAD                     -> načte nastavení z EEPROM
    HELP                     -> nápověda

  Každý příkaz odpoví řádkem "OK" nebo "ERR <důvod>".
*/

#include <FastLED.h>
#include <EEPROM.h>

// ------------------------------------------------------------------ nastavení
#define LED_PIN         6      // datový vodič k prvnímu modulu (přes odpor 330–470 Ω)
#define PANELS          4      // počet modulů FC101
#define LEDS_PER_PANEL  8      // LED na jednom modulu
#define SERIAL_BAUD     115200

// Pojistka proti přetížení zdroje: FastLED sám sníží jas tak, aby se odběr
// vešel do zadaného limitu. 2000 mA odpovídá zdroji 5 V / 3 A s rezervou.
#define MAX_MILLIAMPS   2000

#define NUM_LEDS   (PANELS * LEDS_PER_PANEL)
#define VERSION    "1.0"
#define EEPROM_MAGIC 0x42
#define EEPROM_ADDR  0

CRGB leds[NUM_LEDS];

struct PanelState {
  bool    on;
  uint8_t brightness;
  uint8_t r, g, b;
};

struct Settings {
  uint8_t     magic;
  bool        masterOn;
  uint8_t     masterBrightness;
  PanelState  panel[PANELS];
};

Settings cfg;

char    cmdBuf[64];
uint8_t cmdLen = 0;

// -------------------------------------------------------------------- pomocné
void defaults() {
  cfg.magic = EEPROM_MAGIC;
  cfg.masterOn = true;
  cfg.masterBrightness = 128;
  for (uint8_t i = 0; i < PANELS; i++) {
    cfg.panel[i] = { true, 255, 255, 255, 255 };   // bílá, plný jas panelu
  }
}

void applyLeds() {
  for (uint8_t p = 0; p < PANELS; p++) {
    uint8_t scale = 0;
    if (cfg.masterOn && cfg.panel[p].on) {
      scale = (uint16_t)cfg.panel[p].brightness * cfg.masterBrightness / 255;
    }
    CRGB color = CRGB(cfg.panel[p].r, cfg.panel[p].g, cfg.panel[p].b);
    color.nscale8_video(scale);
    for (uint8_t i = 0; i < LEDS_PER_PANEL; i++) {
      leds[p * LEDS_PER_PANEL + i] = color;
    }
  }
  FastLED.show();
}

void printState() {
  Serial.print(F("STATE MASTER "));
  Serial.print(cfg.masterOn ? 1 : 0);
  Serial.print(' ');
  Serial.println(cfg.masterBrightness);
  for (uint8_t p = 0; p < PANELS; p++) {
    Serial.print(F("STATE "));
    Serial.print(p + 1);          Serial.print(' ');
    Serial.print(cfg.panel[p].on ? 1 : 0); Serial.print(' ');
    Serial.print(cfg.panel[p].brightness); Serial.print(' ');
    Serial.print(cfg.panel[p].r); Serial.print(' ');
    Serial.print(cfg.panel[p].g); Serial.print(' ');
    Serial.println(cfg.panel[p].b);
  }
}

void printBanner() {
  Serial.print(F("READY BMSLED "));
  Serial.print(F(VERSION));
  Serial.print(F(" PANELS="));
  Serial.print(PANELS);
  Serial.print(F(" LEDS="));
  Serial.println(LEDS_PER_PANEL);
}

/* Vrátí číslo z tokenu, nebo -1 při chybě. */
long numArg(char *tok) {
  if (tok == NULL) return -1;
  for (char *c = tok; *c; c++) {
    if (*c < '0' || *c > '9') return -1;
  }
  return atol(tok);
}

bool inRange(long v) { return v >= 0 && v <= 255; }

// ------------------------------------------------------------------- příkazy
void handleCommand(char *line) {
  char *cmd = strtok(line, " \t");
  if (cmd == NULL) return;

  for (char *c = cmd; *c; c++) *c = toupper(*c);

  // ---------------------------------------------------------------- PING ---
  if (!strcmp(cmd, "PING")) {
    printBanner();
    return;
  }

  // --------------------------------------------------------------- STATE ---
  if (!strcmp(cmd, "STATE")) {
    printState();
    Serial.println(F("OK"));
    return;
  }

  // ---------------------------------------------------------------- HELP ---
  if (!strcmp(cmd, "HELP")) {
    Serial.println(F("PING | STATE | P <n> ON|OFF|B <v>|C <r> <g> <b>"));
    Serial.println(F("ALL ON|OFF|B <v>|C <r> <g> <b> | ONLY <n> | SAVE | LOAD"));
    Serial.println(F("OK"));
    return;
  }

  // ---------------------------------------------------------------- SAVE ---
  if (!strcmp(cmd, "SAVE")) {
    EEPROM.put(EEPROM_ADDR, cfg);
    Serial.println(F("OK"));
    return;
  }

  if (!strcmp(cmd, "LOAD")) {
    Settings stored;
    EEPROM.get(EEPROM_ADDR, stored);
    if (stored.magic != EEPROM_MAGIC) {
      Serial.println(F("ERR nic ulozeno"));
      return;
    }
    cfg = stored;
    applyLeds();
    Serial.println(F("OK"));
    return;
  }

  // ---------------------------------------------------------------- ONLY ---
  if (!strcmp(cmd, "ONLY")) {
    long n = numArg(strtok(NULL, " \t"));
    if (n < 1 || n > PANELS) { Serial.println(F("ERR cislo panelu")); return; }
    for (uint8_t p = 0; p < PANELS; p++) cfg.panel[p].on = (p == n - 1);
    cfg.masterOn = true;
    applyLeds();
    Serial.println(F("OK"));
    return;
  }

  // ------------------------------------------------------- P <n> ... / ALL --
  bool all = !strcmp(cmd, "ALL");
  if (!all && strcmp(cmd, "P")) {
    Serial.println(F("ERR neznamy prikaz"));
    return;
  }

  int8_t target = -1;               // -1 = všechny panely
  if (!all) {
    long n = numArg(strtok(NULL, " \t"));
    if (n < 1 || n > PANELS) { Serial.println(F("ERR cislo panelu")); return; }
    target = n - 1;
  }

  char *sub = strtok(NULL, " \t");
  if (sub == NULL) { Serial.println(F("ERR chybi parametr")); return; }
  for (char *c = sub; *c; c++) *c = toupper(*c);

  if (!strcmp(sub, "ON") || !strcmp(sub, "OFF")) {
    bool on = !strcmp(sub, "ON");
    if (all) {
      cfg.masterOn = on;
      for (uint8_t p = 0; p < PANELS; p++) cfg.panel[p].on = on;
    } else {
      cfg.panel[target].on = on;
      if (on) cfg.masterOn = true;
    }
  } else if (!strcmp(sub, "B")) {
    long v = numArg(strtok(NULL, " \t"));
    if (!inRange(v)) { Serial.println(F("ERR jas 0-255")); return; }
    if (all) cfg.masterBrightness = v;
    else     cfg.panel[target].brightness = v;
  } else if (!strcmp(sub, "C")) {
    long r = numArg(strtok(NULL, " \t"));
    long g = numArg(strtok(NULL, " \t"));
    long b = numArg(strtok(NULL, " \t"));
    if (!inRange(r) || !inRange(g) || !inRange(b)) {
      Serial.println(F("ERR barva 0-255"));
      return;
    }
    for (uint8_t p = 0; p < PANELS; p++) {
      if (all || p == target) {
        cfg.panel[p].r = r; cfg.panel[p].g = g; cfg.panel[p].b = b;
      }
    }
  } else {
    Serial.println(F("ERR neznamy parametr"));
    return;
  }

  applyLeds();
  Serial.println(F("OK"));
}

// ---------------------------------------------------------------- setup/loop
void setup() {
  Serial.begin(SERIAL_BAUD);
  FastLED.addLeds<WS2812B, LED_PIN, GRB>(leds, NUM_LEDS);
  FastLED.setMaxPowerInVoltsAndMilliamps(5, MAX_MILLIAMPS);
  FastLED.setBrightness(255);       // vlastní stmívání řešíme po panelech

  Settings stored;
  EEPROM.get(EEPROM_ADDR, stored);
  if (stored.magic == EEPROM_MAGIC) cfg = stored;
  else                              defaults();

  applyLeds();
  printBanner();
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdLen > 0) {
        cmdBuf[cmdLen] = '\0';
        handleCommand(cmdBuf);
        cmdLen = 0;
      }
    } else if (cmdLen < sizeof(cmdBuf) - 1) {
      cmdBuf[cmdLen++] = c;
    } else {
      cmdLen = 0;                   // příliš dlouhý řádek zahodíme
      Serial.println(F("ERR prilis dlouhy prikaz"));
    }
  }
}
