// Idle screen: snake-traced VR Varna logo, singer/song panel, or QR-code menu,
// for an SSD1306 128x64 I2C OLED on ESP32.
  //
  // Wiring (small OLED — your build omits GND/VCC; still tie module GND to ESP GND
  //   if the display is powered from the same board 3V3.):
  //   SDA -> GPIO 21
  //   SCL -> GPIO 22
  //   Volume potentiometer wiper -> GPIO 34 (ADC1, input-only). Outer legs to
  //     3V3 and GND (never 5V). Turn toward the 3V3 leg = louder. See POT_PIN.
  //   Buttons (mapped after GPIO discovery on your board; one physical switch was
  //   on GPIO35 which is input-only / no internal pull-up — not included here).
  //   SW1..SW12 -> GPIO 27, 2, 5, 17, 16, 4, 32, 18, 26, 25, 33, 13
  //   (SW8 was GPIO34 in the first bring-up; input-only pins have no internal
  //   pull-up, so SW8 was moved to GPIO18 for reliable tact switches to GND.)
  //
  // Libraries (install via Library Manager):
  //   - Adafruit GFX Library
  //   - Adafruit SSD1306
  //   The manual QR overlay uses a baked-in bitmap (`qr_manual_bitmap.h`);
  //   no extra QR library required.
  //   (BLE and WiFi come with the esp32 Arduino core.)
  //
  // Protocol with the companion Python script (send_song.py):
  //   1) Python finds BLE device "OLED-Music" and writes "SSID|PASSWORD" to
  //      the WiFi characteristic.
  //   2) ESP32 connects to Wi-Fi and notifies "IP:<addr>:<port>" back on the
  //      same characteristic (or "ERR:wifi" if the connection failed).
  //   3) Python opens a TCP socket to <addr>:<port>. Messages PC -> ESP are
  //      newline-terminated, '|'-separated, and dispatched by their first field:
  //        SONG|artist|title|holdms  - show the now-playing panel. holdms>0
  //            draws a countdown of that length; the panel then PERSISTS until
  //            the host sends another command, so it stays up exactly as long as
  //            the real clip plays. holdms=0 shows it with no countdown bar.
  //        RANK|label:score|label:score|label:score  - up to three rows, shown
  //            as a Top-3 leaderboard (pushed after every round).
  //        CD|<text>  - one big centered glyph (the 3-2-1-GO! pre-round
  //            countdown, mirrored from the PC).
  //        IDLE  - return to the idle VR Varna logo.
  //        RESET (or REBOOT)  - software reboot, same as the physical RESET
  //            button. The ESP acks "RESETTING" then restarts.
  //        artist|title  - legacy 2-field song; auto-hides after 10 s.
  //   4) Messages ESP -> Python over the same socket:
  //        BTN:<n>  - mapped switch n (1..BUTTON_COUNT) was pressed.
  //        VOL:<0..100>  - the GPIO34 volume knob moved (see POT_PIN).
  //
  // Local UI extras:
  //   - Holding SW1 (button 1) for 2 s on the idle screen swaps the display for
  //     a full-size QR code that links to https://labcoinremotemanual.pages.dev/.
  //     Any subsequent button press (or an incoming song from the Python side)
  //     dismisses the menu.

  #include <Wire.h>
  #include <Adafruit_GFX.h>
  #include <Adafruit_SSD1306.h>
  #include <WiFi.h>
  #include <BLEDevice.h>
  #include <BLEServer.h>
  #include <BLEUtils.h>
  #include <BLE2902.h>
  #include "freertos/FreeRTOS.h"
  #include "freertos/task.h"
  #include "note_v3.h"
  #include "qr_manual_bitmap.h"
  // --- Display ---------------------------------------------------------------
  #define SCREEN_WIDTH  128
  #define SCREEN_HEIGHT 64
  #define OLED_RESET    -1
  #define OLED_ADDR     0x3C   // try first; 0x3D is common on some modules
  #define OLED_ADDR_ALT 0x3D
  #define SDA_PIN       21
  #define SCL_PIN       22

  Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
  bool displayReady = false;
  bool bleStarted = false;
  unsigned long bootedAt = 0;
  unsigned long lastOledRetryAt = 0;
  const unsigned long BLE_START_DELAY_MS = 5000UL;
  const unsigned long OLED_RETRY_MS = 1000UL;

  // If loop() stops advancing (often I2C/display driver stuck after a hardware
  // fault), reboot automatically. This does not fix a hard brownout or damaged
  // regulator — only a firmware hang with the CPU still running.
  volatile uint32_t loopLastAliveMs = 0;
  const uint32_t LOOP_STALL_REBOOT_MS = 45000UL;
  const uint32_t LOOP_WATCHDOG_GRACE_MS = 20000UL;  // skip early boot (self-test, BLE delay)

  void loopHangMonitorTask(void* /*param*/) {
    for (;;) {
      vTaskDelay(pdMS_TO_TICKS(1000));
      uint32_t now = millis();
      if (now - bootedAt < LOOP_WATCHDOG_GRACE_MS) {
        continue;
      }
      uint32_t last = loopLastAliveMs;
      if (last != 0 && (now - last) > LOOP_STALL_REBOOT_MS) {
        Serial.printf("Main loop stalled (%lu ms); rebooting...\n",
                      (unsigned long)(now - last));
        delay(50);
        ESP.restart();
      }
    }
  }

  // --- Buttons ---------------------------------------------------------------
  // SW1..SWn, each wired between the GPIO and GND. GPIO34+ are input-only (no
  // internal pull-up on ESP32); the net must be biased on the PCB.
  const uint8_t BUTTON_PINS[] = {
    27, 2, 5, 17, 16, 4, 32, 18, 26, 25, 33, 13
  };
  const int BUTTON_COUNT = sizeof(BUTTON_PINS) / sizeof(BUTTON_PINS[0]);
  bool          buttonState[BUTTON_COUNT]   = {false}; // true = currently pressed
  unsigned long buttonChangeAt[BUTTON_COUNT] = {0};    // last edge time (debounce)
  const unsigned long BUTTON_DEBOUNCE_MS = 25;

  // --- Networking ------------------------------------------------------------
  #define TCP_PORT      3333
  #define SONG_HOLD_MS  10000UL

  // Random 128-bit UUIDs picked for this project.
  #define BLE_SERVICE_UUID   "7a9e0b91-2d6e-4a7f-9e3c-5a0f64c2e010"
  #define BLE_CHAR_WIFI_UUID "7a9e0b91-2d6e-4a7f-9e3c-5a0f64c2e011"

  BLECharacteristic* wifiChar = nullptr;
  WiFiServer tcpServer(TCP_PORT);
  WiFiClient tcpClient;
  bool tcpActive = false;
  bool wifiReady = false;
  String connectedSSID = "";

  // --- Volume potentiometer --------------------------------------------------
  // Wiper -> GPIO34 (ADC1_CH6). GPIO34 is INPUT-ONLY and lives on ADC1, so it
  // keeps reading while Wi-Fi is on (ADC2 pins return garbage once the radio is
  // up) and it physically can't drive a load — exactly what a volume knob wants.
  // Wire the outer legs to 3V3 and GND; never 5V (the ADC clamps near 3.3V).
  #define POT_PIN 34
  const int POT_ADC_MAX = 4095;            // 12-bit full scale
  const unsigned long POT_POLL_MS = 60UL;  // ~16 Hz is plenty for a knob
  unsigned long lastPotPollAt = 0;
  int potFiltered = -1;                    // EMA of the raw ADC (-1 = unset)
  int lastSentVolume = -1;                 // last 0..100 value pushed to the PC

  // --- Music note geometry (left half, centered at NOTE_CX / NOTE_CY) --------

  const int NOTE_CX = 32;
  const int NOTE_CY = 32;

  // Note head: ellipse in the XZ plane so it foreshortens while spinning.
  const int HEAD_SEG = 16;
  V3 head[HEAD_SEG];

  // Stem: right edge of the note head, straight up.
  const V3 stemBot = {  5.0f,   0.0f, 0.0f };
  const V3 stemTop = {  5.0f, -24.0f, 0.0f };

  // Flag: curve from the top of the stem outward and down.
  const int FLAG_PTS = 7;
  V3 flag[FLAG_PTS];

  // Shared animation phase for the idle logo spin.
  float angle = 0.0f;

  // --- VR Varna logo (idle) -------------------------------------------------
  // The logo is two diagonally-offset 1:1 square outlines with "VR" + "varna" set
  // in the middle, exactly like the brand artwork. Instead of spinning, the
  // outlines are traced as a single continuous pathway: the line grows from a
  // starting corner, completes both squares, then is "eaten" from the same
  // corner before the cycle repeats. This gives the appearing/disappearing
  // pathway effect requested for the idle screen.

  // Draws the portion of a rectangle's perimeter spanned by the parametric
  // range [t1, t2] (each in 0..1). t starts at the top-left corner and
  // advances clockwise: top edge, right edge, bottom edge, left edge.
  void drawRectPerimSegment(int rx, int ry, int rw, int rh, float t1, float t2) {
    if (rw < 2 || rh < 2) return;
    if (t1 < 0.0f) t1 = 0.0f;
    if (t2 > 1.0f) t2 = 1.0f;
    if (t1 >= t2) return;

    const float ws = (float)(rw - 1);
    const float hs = (float)(rh - 1);
    const float perim = 2.0f * ws + 2.0f * hs;
    const float startD = t1 * perim;
    const float endD   = t2 * perim;

    // Edge boundaries along the perimeter and their endpoint coordinates.
    const float ed[5] = { 0.0f, ws, ws + hs, 2.0f * ws + hs, 2.0f * ws + 2.0f * hs };
    const int   ex[5] = { rx,   rx + rw - 1, rx + rw - 1, rx,          rx };
    const int   ey[5] = { ry,   ry,          ry + rh - 1, ry + rh - 1, ry };

    for (int e = 0; e < 4; e++) {
      const float a = max(startD, ed[e]);
      const float b = min(endD,   ed[e + 1]);
      if (a >= b) continue;
      const float seg = ed[e + 1] - ed[e];
      const float u = (a - ed[e]) / seg;
      const float v = (b - ed[e]) / seg;
      const int x0 = ex[e] + (int)roundf((float)(ex[e + 1] - ex[e]) * u);
      const int y0 = ey[e] + (int)roundf((float)(ey[e + 1] - ey[e]) * u);
      const int x1 = ex[e] + (int)roundf((float)(ex[e + 1] - ex[e]) * v);
      const int y1 = ey[e] + (int)roundf((float)(ey[e + 1] - ey[e]) * v);
      display.drawLine(x0, y0, x1, y1, SSD1306_WHITE);
    }
  }

  void drawVRVarnaLogo() {
    // Two same-sized squares (1:1), offset diagonally — centered on the display.
    // Side length chosen so the stack clears the WiFi row (~y 56) on a 64 px-tall screen.
    const int S = 50;
    const int outerX = (SCREEN_WIDTH - S) / 2;
    const int outerY = 0;
    const int outerW = S;
    const int outerH = S;
    const int innerX = outerX + 8;
    const int innerY = outerY + 4;
    const int innerW = S;
    const int innerH = S;

    const float outerPerim = 2.0f * (outerW + outerH - 2);
    const float innerPerim = 2.0f * (innerW + innerH - 2);
    const float totalPerim = outerPerim + innerPerim;

    // Phase: 0..1 grows the pathway, 1..2 erases it from the start.
    const unsigned long CYCLE_MS = 6000UL;
    const float phase = (float)(millis() % CYCLE_MS) * 2.0f / (float)CYCLE_MS;

    float drawStart, drawEnd;
    if (phase < 1.0f) {
      drawStart = 0.0f;
      drawEnd   = phase * totalPerim;
    } else {
      drawStart = (phase - 1.0f) * totalPerim;
      drawEnd   = totalPerim;
    }

    if (drawEnd > 0.0f && drawStart < outerPerim) {
      const float a = max(0.0f, drawStart) / outerPerim;
      const float b = min(outerPerim, drawEnd) / outerPerim;
      drawRectPerimSegment(outerX, outerY, outerW, outerH, a, b);
    }
    if (drawEnd > outerPerim) {
      const float a = max(0.0f, drawStart - outerPerim) / innerPerim;
      const float b = min(innerPerim, drawEnd - outerPerim) / innerPerim;
      drawRectPerimSegment(innerX, innerY, innerW, innerH, a, b);
    }

    // Static brand text, centered in the inner square.
    display.setTextColor(SSD1306_WHITE);
    display.setTextWrap(false);
    const int textCx = innerX + innerW / 2;
    const int textCy = innerY + innerH / 2;
    display.setTextSize(2);
    display.setCursor(textCx - 12, textCy - 8);   // "VR" — 2x font, 16 px tall
    display.print("VR");
    display.setTextSize(1);
    display.setCursor(textCx - 14, textCy + 8);    // "varna"
    display.print("varna");
  }

  // --- Right-side state machine ---------------------------------------------
  enum RightState { RS_IDLE, RS_SONG, RS_QR, RS_RANK, RS_COUNT };
  RightState rightState = RS_IDLE;
  String singerName = "";
  String songName   = "";
  unsigned long songShownAt = 0;
  // Big centered countdown digit ("3"/"2"/"1"/"GO!"), mirrored from the PC.
  String countdownText = "";
  // A new SONG|... push stays on screen until the host changes it (so it lasts
  // for the whole clip); only the legacy "artist|title" path auto-hides.
  bool songAutoHide = false;
  unsigned long songHoldMs = SONG_HOLD_MS;  // countdown length; 0 = no bar
  // Top-3 leaderboard (RANK|label:score|...).
  String rankLabel[3];
  int    rankScore[3] = { -1, -1, -1 };
  int    rankCount = 0;

  // --- QR menu --------------------------------------------------------------
  // SW1 must be held this long on the idle screen before the QR menu appears.
  const unsigned long QR_HOLD_MS = 2000UL;

  // Latched while SW1 is held to prevent the same hold from re-entering the
  // QR menu after dismissal. Cleared when SW1 is released.
  bool qrTriggerArmed = false;

  // --- BLE callbacks ---------------------------------------------------------
  void connectWiFi(const String& ssid, const String& pass) {
    Serial.printf("Connecting to Wi-Fi '%s' (len=%d, pass_len=%d)...\n",
                  ssid.c_str(), ssid.length(), pass.length());
    wifiReady = false;
    connectedSSID = "";

    // Pause BLE advertising while WiFi is negotiating — on the classic ESP32
    // the two radios share the same 2.4 GHz front end and simultaneous activity
    // can cause the join to stall or fail.
    BLEDevice::getAdvertising()->stop();

    WiFi.disconnect(true, true);
    delay(200);
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    WiFi.begin(ssid.c_str(), pass.c_str());

    unsigned long t0 = millis();
    wl_status_t st = WiFi.status();
    while (st != WL_CONNECTED && millis() - t0 < 30000UL) {
      delay(250);
      st = WiFi.status();
    }

    if (st == WL_CONNECTED) {
      wifiReady = true;
      connectedSSID = ssid;
      tcpServer.begin();
      String msg = String("IP:") + WiFi.localIP().toString() + ":" + String(TCP_PORT);
      Serial.println(msg);
      if (wifiChar) {
        wifiChar->setValue(msg.c_str());
        wifiChar->notify();
      }
    } else {
      Serial.printf("Wi-Fi connect failed, status=%d\n", (int)st);
      if (wifiChar) {
        String err = String("ERR:wifi:") + String((int)st);
        wifiChar->setValue(err.c_str());
        wifiChar->notify();
      }
    }

    // Resume BLE advertising so further re-pairs still work.
    BLEDevice::getAdvertising()->start();
  }

  class WifiCharCB : public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic* c) override {
      String v = c->getValue();
      int bar = v.indexOf('|');
      if (bar < 0) return;
      String ssid = v.substring(0, bar);
      String pass = v.substring(bar + 1);
      connectWiFi(ssid, pass);
    }
  };

  class ServerCB : public BLEServerCallbacks {
    void onDisconnect(BLEServer* s) override {
      // Arduino ESP32 BLE stops advertising after a client disconnects; restart it.
      delay(200);
      BLEDevice::startAdvertising();
      Serial.println("BLE re-advertising");
    }
  };

  void setupBLE() {
    BLEDevice::init("OLED-Music");
    BLEServer* server = BLEDevice::createServer();
    server->setCallbacks(new ServerCB());
    BLEService* svc = server->createService(BLE_SERVICE_UUID);
    wifiChar = svc->createCharacteristic(
        BLE_CHAR_WIFI_UUID,
        BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_NOTIFY);
    wifiChar->setCallbacks(new WifiCharCB());
    wifiChar->addDescriptor(new BLE2902());
    svc->start();
    BLEAdvertising* adv = BLEDevice::getAdvertising();
    adv->addServiceUUID(BLE_SERVICE_UUID);
    adv->setScanResponse(true);
    BLEDevice::startAdvertising();
  }

  // --- TCP message handling --------------------------------------------------
  // Parse one line from the PC. Dispatch is by the first '|'-separated field:
  //   SONG|artist|title|holdms   now-playing; holdms>0 draws a countdown of that
  //                              length, then the panel persists until the host
  //                              changes it. holdms=0 = no bar.
  //   RANK|label:score|...       up to three rows -> Top-3 leaderboard.
  //   IDLE                       back to the idle logo.
  //   artist|title               legacy song, auto-hides after SONG_HOLD_MS.
  void processCommand(const String& line) {
    int bar = line.indexOf('|');
    String head = (bar < 0) ? line : line.substring(0, bar);
    String rest = (bar < 0) ? String("") : line.substring(bar + 1);
    String headUp = head;
    headUp.toUpperCase();

    if (headUp == "IDLE") {
      rightState = RS_IDLE;
      return;
    }

    if (headUp == "RESET" || headUp == "REBOOT") {
      // Software reboot — same effect as the physical RESET / EN button.
      Serial.println("Reset requested over network; restarting...");
      if (tcpActive && tcpClient.connected()) {
        tcpClient.print("RESETTING\n");
        tcpClient.flush();
      }
      delay(120);            // let the ack flush before the radios drop
      ESP.restart();
      return;                // not reached
    }

    if (headUp == "CD") {
      // CD|<text> — big centered countdown digit mirrored from the PC.
      int b = rest.indexOf('|');
      countdownText = (b < 0) ? rest : rest.substring(0, b);
      rightState = RS_COUNT;
      return;
    }

    if (headUp == "SONG") {
      int b1 = rest.indexOf('|');
      String artist = (b1 < 0) ? rest : rest.substring(0, b1);
      String tail   = (b1 < 0) ? String("") : rest.substring(b1 + 1);
      int b2 = tail.indexOf('|');
      String title  = (b2 < 0) ? tail : tail.substring(0, b2);
      String holdS  = (b2 < 0) ? String("") : tail.substring(b2 + 1);
      singerName = artist;
      songName   = title;
      songHoldMs = (unsigned long)(holdS.length() ? holdS.toInt() : 0);
      songAutoHide = false;
      rightState = RS_SONG;
      songShownAt = millis();
      Serial.printf("SONG: %s - %s (hold %lu ms)\n",
                    singerName.c_str(), songName.c_str(), songHoldMs);
      return;
    }

    if (headUp == "RANK") {
      rankCount = 0;
      String r = rest;
      while (rankCount < 3 && r.length() > 0) {
        int b = r.indexOf('|');
        String tok = (b < 0) ? r : r.substring(0, b);
        r = (b < 0) ? String("") : r.substring(b + 1);
        tok.trim();
        if (tok.length() == 0) continue;
        int colon = tok.lastIndexOf(':');
        if (colon < 0) {
          rankLabel[rankCount] = tok;
          rankScore[rankCount] = -1;
        } else {
          rankLabel[rankCount] = tok.substring(0, colon);
          rankScore[rankCount] = tok.substring(colon + 1).toInt();
        }
        rankCount++;
      }
      if (rankCount > 0) {
        rightState = RS_RANK;
        songShownAt = millis();
      }
      return;
    }

    // Legacy fallback: bare "artist|title" (auto-hides after SONG_HOLD_MS).
    if (bar >= 0) {
      singerName = head;
      songName   = rest;
      songHoldMs = SONG_HOLD_MS;
      songAutoHide = true;
      rightState = RS_SONG;
      songShownAt = millis();
      Serial.printf("Now showing: %s - %s\n",
                    singerName.c_str(), songName.c_str());
    }
  }

  void handleTCP() {
    if (!wifiReady) return;
    if (!tcpActive) {
      WiFiClient c = tcpServer.available();
      if (c) {
        tcpClient = c;
        tcpActive = true;
        // Re-send the current knob position to the freshly connected host.
        lastSentVolume = -1;
        Serial.println("TCP client connected");
      }
    }
    if (tcpActive) {
      if (!tcpClient.connected()) {
        tcpClient.stop();
        tcpActive = false;
        // Host went away: fall back to the idle logo instead of freezing on
        // whatever song / leaderboard was last shown.
        rightState = RS_IDLE;
        Serial.println("TCP client disconnected");
        return;
      }
      while (tcpClient.available()) {
        String line = tcpClient.readStringUntil('\n');
        line.trim();
        if (line.length() == 0) continue;
        processCommand(line);
      }
    }
  }

  // --- Buttons ---------------------------------------------------------------
  bool pinSupportsInternalPullup(uint8_t pin) {
    return pin <= 33;
  }

  void configureButtonPin(uint8_t pin) {
    pinMode(pin, pinSupportsInternalPullup(pin) ? INPUT_PULLUP : INPUT);
  }

  void setupButtons() {
    for (int i = 0; i < BUTTON_COUNT; i++) {
      configureButtonPin(BUTTON_PINS[i]);
      buttonState[i] = false;
      buttonChangeAt[i] = 0;
      Serial.printf("SW%d -> GPIO%u\n", i + 1, (unsigned)BUTTON_PINS[i]);
    }
  }

  void pollButtons() {
    unsigned long now = millis();
    for (int i = 0; i < BUTTON_COUNT; i++) {
      bool pressed = (digitalRead(BUTTON_PINS[i]) == LOW);
      if (pressed == buttonState[i]) continue;
      if (now - buttonChangeAt[i] < BUTTON_DEBOUNCE_MS) continue;
      buttonChangeAt[i] = now;
      buttonState[i] = pressed;
      if (pressed) {
        Serial.printf("Button %d pressed (GPIO%u)\n", i + 1, (unsigned)BUTTON_PINS[i]);
        // Any button press dismisses the QR menu and returns to idle. We arm
        // the QR trigger so SW1 must be released before another long-hold can
        // re-enter the menu.
        if (rightState == RS_QR) {
          rightState = RS_IDLE;
          qrTriggerArmed = true;
          Serial.println("QR menu dismissed via button");
        }
        if (tcpActive && tcpClient.connected()) {
          String msg = String("BTN:") + String(i + 1) + "\n";
          tcpClient.print(msg);
        }
      }
    }
  }

  // --- Volume potentiometer --------------------------------------------------
  void sendVolume(int vol) {
    if (tcpActive && tcpClient.connected()) {
      String msg = String("VOL:") + String(vol) + "\n";
      tcpClient.print(msg);
    }
  }

  void pollPotentiometer() {
    unsigned long now = millis();
    if (now - lastPotPollAt < POT_POLL_MS) return;
    lastPotPollAt = now;

    int raw = analogRead(POT_PIN);
    if (potFiltered < 0) potFiltered = raw;
    else potFiltered += (raw - potFiltered) / 4;   // light EMA smoothing

    // Map to 0..100 with guard bands so the knob reliably reaches a true 0 and
    // a true 100 despite ADC nonlinearity / saturation near the rails.
    const int DEAD_LO = POT_ADC_MAX * 2 / 100;
    const int DEAD_HI = POT_ADC_MAX * 5 / 100;
    int span = POT_ADC_MAX - DEAD_LO - DEAD_HI;
    if (span < 1) span = 1;
    int v = (int)((long)(potFiltered - DEAD_LO) * 100 / span);
    if (v < 0) v = 0;
    if (v > 100) v = 100;

    // Emit only on a meaningful change (or when newly pinned to a rail) so the
    // link isn't flooded with jitter.
    bool atRail = (v == 0 || v == 100);
    if (lastSentVolume < 0 ||
        abs(v - lastSentVolume) >= 2 ||
        (atRail && v != lastSentVolume)) {
      lastSentVolume = v;
      sendVolume(v);
    }
  }

  // --- Geometry setup and rotation ------------------------------------------
  void initGeometry() {
    for (int i = 0; i < HEAD_SEG; i++) {
      float t = (float)i * 2.0f * PI / HEAD_SEG;
      head[i] = { cosf(t) * 8.0f, 0.0f, sinf(t) * 5.5f };
    }
    for (int i = 0; i < FLAG_PTS; i++) {
      float t = (float)i / (FLAG_PTS - 1);
      flag[i] = { 5.0f + t * 11.0f, -24.0f + t * t * 14.0f, 0.0f };
    }
  }

  void rotY(V3& p, float a) {
    float c = cosf(a), s = sinf(a);
    float x =  p.x * c + p.z * s;
    float z = -p.x * s + p.z * c;
    p.x = x; p.z = z;
  }

  void project(V3 p, float a, int cx, int cy, int& sx, int& sy) {
    rotY(p, a);
    const float d = 70.0f;            // camera distance for perspective
    float f = d / (d + p.z);
    sx = (int)(cx + p.x * f);
    sy = (int)(cy + p.y * f + 10);
  }

  // --- Drawing: the spinning note -------------------------------------------
  void drawNote() {
    V3 c3 = { 0.0f, 0.0f, 0.0f };
    int cx, cy;
    project(c3, angle, NOTE_CX, NOTE_CY, cx, cy);
    for (int i = 0; i < HEAD_SEG; i++) {
      int x1, y1, x2, y2;
      project(head[i],                  angle, NOTE_CX, NOTE_CY, x1, y1);
      project(head[(i + 1) % HEAD_SEG], angle, NOTE_CX, NOTE_CY, x2, y2);
      display.fillTriangle(cx, cy, x1, y1, x2, y2, SSD1306_WHITE);
    }
    int sx1, sy1, sx2, sy2;
    project(stemTop, angle, NOTE_CX, NOTE_CY, sx1, sy1);
    project(stemBot, angle, NOTE_CX, NOTE_CY, sx2, sy2);
    display.drawLine(sx1, sy1, sx2, sy2, SSD1306_WHITE);
    for (int pass = 0; pass < 2; pass++) {
      for (int i = 0; i < FLAG_PTS - 1; i++) {
        int x1, y1, x2, y2;
        project(flag[i],     angle, NOTE_CX, NOTE_CY, x1, y1);
        project(flag[i + 1], angle, NOTE_CX, NOTE_CY, x2, y2);
        display.drawLine(x1 + pass, y1, x2 + pass, y2, SSD1306_WHITE);
      }
    }
    int fx1, fy1, fx2, fy2;
    project(flag[FLAG_PTS - 1], angle, NOTE_CX, NOTE_CY, fx1, fy1);
    V3 stemMid = { 5.0f, -14.0f, 0.0f };
    project(stemMid, angle, NOTE_CX, NOTE_CY, fx2, fy2);
    display.drawLine(fx1, fy1, fx2, fy2, SSD1306_WHITE);
  }

  // --- Drawing: the singer icon and song panel -------------------------------
  // Stylised silhouette with a microphone, rendered procedurally so it stays
  // crisp at any position. Centered at (cx, cy).
  void drawSingerIcon(int cx, int cy) {
    // Head.
    display.fillCircle(cx - 2, cy - 6, 4, SSD1306_WHITE);
    // Neck.
    display.fillRect(cx - 3, cy - 2, 3, 2, SSD1306_WHITE);
    // Shoulders / torso trapezoid.
    display.fillTriangle(cx - 10, cy + 6, cx - 3, cy,     cx + 5, cy + 6, SSD1306_WHITE);
    display.fillTriangle(cx - 3,  cy,     cx + 2, cy,     cx + 5, cy + 6, SSD1306_WHITE);
    // Microphone: handle + bulb to the upper right.
    display.drawLine(cx + 2, cy + 1, cx + 7, cy - 4, SSD1306_WHITE);
    display.drawLine(cx + 3, cy + 1, cx + 8, cy - 4, SSD1306_WHITE);
    display.fillCircle(cx + 9, cy - 5, 2, SSD1306_WHITE);
    display.drawPixel(cx + 11, cy - 6, SSD1306_WHITE);
  }

  // Draw text inside the window [x0, x0+w) at y. If text fits, it's centered.
  // Otherwise it scrolls right-to-left, with whitespace padding for a gap.
  void drawTextWindow(const String& s, int x0, int y, int w, unsigned long tms,
                      int maskLeftMin = 0) {
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setTextWrap(false);
    int textW = s.length() * 6;
    if (textW <= w) {
      display.setCursor(x0 + (w - textW) / 2, y);
      display.print(s);
      return;
    }
    const int gap = 18;                    // pixels of blank between repeats
    int period = textW + gap;
    int step = (int)((tms / 60) % period); // 1 pixel every 60 ms
    int startX = x0 - step;
    String doubled = s + "                  " + s;
    display.setCursor(startX, y);
    display.print(doubled);
    // Mask overflow outside the window so text doesn't bleed into other areas.
    int mw = x0 - maskLeftMin;
    if (mw > 0) {
      display.fillRect(maskLeftMin, y - 1, mw, 10, SSD1306_BLACK);
    }
    display.fillRect(x0 + w, y - 1, SCREEN_WIDTH - (x0 + w), 10, SSD1306_BLACK);
  }

  void drawSongPanel() {
    // Singer icon centered along the top.
    drawSingerIcon(SCREEN_WIDTH / 2, 10);

    // Two text rows spanning the full width (x: 0..127).
    drawTextWindow(singerName, 0, 26, SCREEN_WIDTH, millis());
    drawTextWindow(songName,   0, 40, SCREEN_WIDTH, millis() + 400);

    // Countdown bar centered along the bottom, full width minus margins. Driven
    // by songHoldMs (the real clip length); skipped entirely when 0. The bar
    // empties as the clip plays but the panel itself stays until the host
    // pushes the next command.
    if (songHoldMs > 0) {
      unsigned long elapsed = millis() - songShownAt;
      if (elapsed > songHoldMs) elapsed = songHoldMs;
      const int BAR_W_MAX = SCREEN_WIDTH - 8;
      int barW = BAR_W_MAX - (int)((long)BAR_W_MAX * elapsed / songHoldMs);
      if (barW < 0) barW = 0;
      display.drawRect(4, 58, BAR_W_MAX, 4, SSD1306_WHITE);
      display.fillRect(4, 58, barW, 4, SSD1306_WHITE);
    }
  }

  // --- Drawing: the Top-3 leaderboard ----------------------------------------
  // Three rows: a rank badge (filled disc for #1, outline for #2/#3), the player
  // label on the left, and the score right-aligned. Populated by RANK|... and
  // shown after every round.
  void drawRankPanel() {
    display.setTextSize(1);
    display.setTextWrap(false);
    display.setTextColor(SSD1306_WHITE);
    const char* hdr = "TOP 3";
    const int hw = (int)strlen(hdr) * 6;
    display.setCursor((SCREEN_WIDTH - hw) / 2, 0);
    display.print(hdr);
    display.drawFastHLine(0, 10, SCREEN_WIDTH, SSD1306_WHITE);

    int n = rankCount;
    if (n > 3) n = 3;
    const int top = 14;
    const int rowH = (SCREEN_HEIGHT - top) / 3;   // ~16 px per row
    for (int i = 0; i < n; i++) {
      const int cy = top + i * rowH + rowH / 2;
      const int badgeR = 6;
      const int bx = badgeR + 2;

      // Rank badge: #1 filled (number knocked out), #2/#3 outlined.
      if (i == 0) {
        display.fillCircle(bx, cy, badgeR, SSD1306_WHITE);
        display.setTextColor(SSD1306_BLACK);
      } else {
        display.drawCircle(bx, cy, badgeR, SSD1306_WHITE);
        display.setTextColor(SSD1306_WHITE);
      }
      display.setCursor(bx - 2, cy - 3);
      display.print(i + 1);
      display.setTextColor(SSD1306_WHITE);

      // Score right-aligned; label left-aligned after the badge.
      String score = (rankScore[i] >= 0) ? String(rankScore[i]) : String("");
      const int scoreW = score.length() * 6;
      const int scoreX = SCREEN_WIDTH - scoreW - 2;
      const int labelX = bx + badgeR + 5;
      display.setCursor(labelX, cy - 3);
      display.print(rankLabel[i]);
      if (score.length()) {
        display.setCursor(scoreX, cy - 3);
        display.print(score);
      }
    }
  }

  // --- Drawing: the big countdown digit --------------------------------------
  // Mirrors the PC's 3-2-1-GO! countdown as one large centered glyph. The text
  // size is chosen to fill the screen, shrinking if it would overflow.
  void drawCountdown() {
    if (countdownText.length() == 0) return;
    display.setTextWrap(false);
    display.setTextColor(SSD1306_WHITE);
    const int len = countdownText.length();
    int size = (len <= 1) ? 7 : (len <= 3 ? 4 : 2);   // default 6x8 font cell
    int tw = len * 6 * size;
    int th = 8 * size;
    while (size > 1 && (tw > SCREEN_WIDTH || th > SCREEN_HEIGHT)) {
      size--;
      tw = len * 6 * size;
      th = 8 * size;
    }
    display.setTextSize(size);
    display.setCursor((SCREEN_WIDTH - tw) / 2, (SCREEN_HEIGHT - th) / 2);
    display.print(countdownText);
  }

  // Standard WiFi symbol: stacked 90° arcs above a small bottom dot. The dot
  // sits at (cx, cyBottom); arcs ride above it. `show` is the number of arcs
  // currently lit (0..3): 3 = full strength, 0 = bare dot.
  void drawWifiSymbol(int cx, int cyBottom, int show) {
    if (show > 3) show = 3;
    if (show < 0) show = 0;
    const int radii[3] = {3, 6, 9};
    for (int i = 0; i < show; i++) {
      const int r = radii[i];
      // 90° arc centered on straight-up (-90°), drawn pixel-by-pixel.
      for (int a = -45; a <= 45; a++) {
        const float rad = a * (float)PI / 180.0f;
        const int dx = (int)roundf(sinf(rad) * r);
        const int dy = (int)roundf(-cosf(rad) * r);
        display.drawPixel(cx + dx, cyBottom + dy, SSD1306_WHITE);
      }
    }
    // Bottom dot (a small filled square reads better than a single pixel).
    display.fillRect(cx - 1, cyBottom - 1, 2, 2, SSD1306_WHITE);
  }

  // Bottom status row on the idle screensaver: WiFi glyph + SSID.
  void drawIdleStatusLine() {
    const int iconCx = 9;
    const int iconBottom = 62;
    const int textX = 22;
    const int textY = 56;

    const bool connected = (wifiReady && WiFi.status() == WL_CONNECTED);
    if (!connected) {
      // Animated arc count while searching: 1 -> 2 -> 3 arcs.
      const int show = 1 + (int)((millis() / 350) % 3);
      drawWifiSymbol(iconCx, iconBottom, show);
      return;
    }

    String ssid = WiFi.SSID();
    if (ssid.length() == 0) ssid = "?";
    // drawTextWindow paints a black mask to the left of x0 to clip scrolling
    // overflow. We let it cover the icon area first, then redraw the icon on
    // top so any text bleed is hidden.
    drawTextWindow(ssid, textX, textY, SCREEN_WIDTH - textX, millis());
    drawWifiSymbol(iconCx, iconBottom, 3);
  }

  // --- QR menu rendering ----------------------------------------------------
  void drawQRMenu() {
    // Full-screen white background. Inverting the OLED's normal polarity gives
    // phone cameras a proper light "quiet zone" around the QR — black dots on
    // a bright field is what most scanners are tuned for.
    display.fillScreen(SSD1306_WHITE);

    // Each module is 2 px on screen for a 58x58 QR (29 modules * 2 px),
    // centered horizontally. Vertical placement leaves a 6 px strip at the
    // bottom for the dismiss hint.
    const int moduleSize = 2;
    const uint8_t n = QR_MANUAL_MODULES;
    const int qrPx = n * moduleSize;
    const int qrX = (SCREEN_WIDTH - qrPx) / 2;
    const int qrY = 0;
    for (uint8_t y = 0; y < n; y++) {
      for (uint8_t x = 0; x < n; x++) {
        if (qrManualModuleDark(x, y)) {
          display.fillRect(qrX + x * moduleSize, qrY + y * moduleSize,
                           moduleSize, moduleSize, SSD1306_BLACK);
        }
      }
    }

    // Dismiss hint in black on the white background. The default 6x8 font is
    // 8 tall and the strip is 6 px high, so the lowest 2 px (descenders) clip
    // safely off the bottom.
    display.setTextSize(1);
    display.setTextColor(SSD1306_BLACK);
    display.setTextWrap(false);
    const char* hint = "Press any key to exit";
    const int textW = (int)strlen(hint) * 6;
    display.setCursor((SCREEN_WIDTH - textW) / 2, 58);
    display.print(hint);
  }

  void scanI2CBus() {
    Serial.printf("Scanning I2C on SDA=%u SCL=%u...\n", (unsigned)SDA_PIN, (unsigned)SCL_PIN);
    int found = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
      Wire.beginTransmission(addr);
      if (Wire.endTransmission() == 0) {
        Serial.printf("I2C device found at 0x%02X\n", (unsigned)addr);
        found++;
      }
    }
    if (found == 0) {
      Serial.println("No I2C devices found on this bus.");
    }
  }

  void showOledSelfTest() {
    display.clearDisplay();
    display.fillScreen(SSD1306_WHITE);
    display.display();
    delay(500);

    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.println("OLED init OK");
    display.printf("SDA:%u SCL:%u\n", (unsigned)SDA_PIN, (unsigned)SCL_PIN);
    display.println("Addr 0x3C/0x3D");
    display.display();
    delay(1500);
  }

  void showStatusScreen(const char* line1, const char* line2 = "") {
    if (!displayReady) return;
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.println(line1);
    if (line2[0] != '\0') {
      display.println(line2);
    }
    display.display();
  }

  bool beginOled() {
    if (display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
      Serial.printf("SSD1306 OK at 0x%02X\n", (unsigned)OLED_ADDR);
      return true;
    }
    if (display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR_ALT)) {
      Serial.printf("SSD1306 OK at 0x%02X\n", (unsigned)OLED_ADDR_ALT);
      return true;
    }
    Serial.println("SSD1306 not found at 0x3C or 0x3D");
    return false;
  }

  void retryOledIfNeeded() {
    if (displayReady) return;
    unsigned long now = millis();
    if (now - lastOledRetryAt < OLED_RETRY_MS) return;
    lastOledRetryAt = now;

    Serial.println("Retrying OLED init...");
    Wire.begin(SDA_PIN, SCL_PIN);
    Wire.setClock(50000);
    displayReady = beginOled();
    if (displayReady) {
      showOledSelfTest();
      showStatusScreen("OLED recovered", "Starting display...");
    }
  }

  // --- Arduino entry points --------------------------------------------------
  void setup() {
    Serial.begin(115200);
    delay(300);
    Serial.println();
    Serial.println("Booting OLED music logo");
    bootedAt = millis();
    loopLastAliveMs = millis();
    xTaskCreatePinnedToCore(
        loopHangMonitorTask,
        "loopHangMon",
        2048,
        nullptr,
        1,
        nullptr,
        0);
    Wire.begin(SDA_PIN, SCL_PIN);
    // Slower I2C helps marginal wiring; OLED is fixed to SDA=GPIO21, SCL=GPIO22.
    Wire.setClock(50000);
    scanI2CBus();

    displayReady = beginOled();
    if (displayReady) {
      showOledSelfTest();
      showStatusScreen("Display ready", "BLE starts in 5 sec");
    } else {
      Serial.println("OLED init failed; firmware will keep retrying instead of freezing.");
    }

    initGeometry();
    setupButtons();

    // Volume knob on ADC1 (GPIO34). 12-bit reads, 11 dB attenuation for the
    // full ~0..3.3 V swing of a pot wired across 3V3 / GND.
    analogReadResolution(12);
    analogSetPinAttenuation(POT_PIN, ADC_11db);
  }

  void loop() {
    loopLastAliveMs = millis();
    retryOledIfNeeded();

    if (displayReady && !bleStarted && millis() - bootedAt >= BLE_START_DELAY_MS) {
      Serial.println("Starting BLE...");
      showStatusScreen("Starting BLE...", "If reset, power issue");
      setupBLE();
      bleStarted = true;
      Serial.println("BLE advertising as 'OLED-Music'");
      showStatusScreen("BLE ready", "Starting display...");
      delay(500);
    }

    if (bleStarted) {
      handleTCP();
    }
    pollButtons();
    pollPotentiometer();

    if (!displayReady) {
      delay(100);
      return;
    }

    // Only legacy 2-field songs auto-hide; SONG|... pushes persist until the
    // host changes the screen, so they last as long as the clip actually plays.
    if (rightState == RS_SONG && songAutoHide &&
        millis() - songShownAt > songHoldMs) {
      rightState = RS_IDLE;
    }

    // Holding SW1 (button 1) for QR_HOLD_MS on the idle screen opens the QR
    // menu. The "armed" flag prevents the same hold from re-triggering the
    // menu after an immediate dismissal — SW1 must be released first.
    if (!buttonState[0]) {
      qrTriggerArmed = false;
    }
    if (rightState == RS_IDLE && buttonState[0] && !qrTriggerArmed &&
        (millis() - buttonChangeAt[0]) >= QR_HOLD_MS) {
      rightState = RS_QR;
      qrTriggerArmed = true;
      Serial.println("Entered QR menu (SW1 held)");
    }

    display.clearDisplay();
    switch (rightState) {
      case RS_IDLE:
        drawVRVarnaLogo();
        drawIdleStatusLine();
        break;
      case RS_SONG:
        drawSongPanel();
        break;
      case RS_RANK:
        drawRankPanel();
        break;
      case RS_COUNT:
        drawCountdown();
        break;
      case RS_QR:
        drawQRMenu();
        break;
    }
    display.display();
    loopLastAliveMs = millis();

    angle += 0.08f;
    if (angle > 2.0f * PI) angle -= 2.0f * PI;

    delay(25);
  }
