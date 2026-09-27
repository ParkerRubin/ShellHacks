// JARVIS pan/tilt head
// Receives "pan,tilt\n" at 115200 baud (e.g. "120,80") and glides the servos there smoothly.
// Wiring: pan servo signal -> pin 9, tilt servo signal -> pin 10.
// Power the servos from a separate 5V supply if you can (connect its GND to the Arduino GND).
// Running two servos off the Arduino's 5V pin often browns out: jitter, resets, or no movement.

#include <Servo.h>

const int PAN_PIN  = 9;
const int TILT_PIN = 10;

const int PAN_MIN  = 20,  PAN_MAX  = 160;   // keep in sync with jarvis.py limits
const int TILT_MIN = 45,  TILT_MAX = 135;

// Eased glide: covers 25% of the remaining distance each tick, capped at MAX_STEP.
// Big moves are fast, and it slows down as it lands so it doesn't overshoot or wobble.
// jarvis.py mirrors these three numbers to estimate where the head is mid-move, so keep them in sync.
const float EASE           = 0.25;
const float MAX_STEP       = 4.0;   // degrees per tick (~265 deg/s top speed)
const unsigned long TICK_MS = 15;   // update rate (~66 Hz)

Servo pan, tilt;
float panPos = 90, tiltPos = 90;
int panTarget = 90, tiltTarget = 90;
unsigned long lastTick = 0;

char buf[24];
byte len = 0;

float glide(float pos, int target) {
  float d = target - pos;
  if (fabs(d) <= 0.5) return target;         // close enough: land exactly
  return pos + constrain(d * EASE, -MAX_STEP, MAX_STEP);
}

void handleLine(char *s) {
  if (s[0] == '?') {                         // "?" -> report position
    Serial.print("POS ");
    Serial.print((int)panPos);
    Serial.print(',');
    Serial.println((int)tiltPos);
    return;
  }
  char *comma = strchr(s, ',');
  if (!comma) return;
  *comma = '\0';
  panTarget  = constrain(atoi(s), PAN_MIN, PAN_MAX);
  tiltTarget = constrain(atoi(comma + 1), TILT_MIN, TILT_MAX);
}

void wiggle() {                               // startup test so you can hear/see it's alive
  int moves[][2] = {{70, 90}, {110, 90}, {90, 75}, {90, 105}, {90, 90}};
  for (int i = 0; i < 5; i++) {
    pan.write(moves[i][0]);
    tilt.write(moves[i][1]);
    delay(250);
  }
}

void setup() {
  Serial.begin(115200);
  pan.attach(PAN_PIN);
  tilt.attach(TILT_PIN);
  pan.write(90);
  tilt.write(90);
  delay(300);
  wiggle();
  Serial.println("JARVIS servo ready");
}

void loop() {
  // non-blocking line reader
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (len) { buf[len] = '\0'; handleLine(buf); len = 0; }
    } else if (len < sizeof(buf) - 1) {
      buf[len++] = c;
    }
  }

  // glide toward the target
  if (millis() - lastTick >= TICK_MS) {
    lastTick = millis();
    panPos  = glide(panPos,  panTarget);
    tiltPos = glide(tiltPos, tiltTarget);
    pan.write((int)(panPos + 0.5));
    tilt.write((int)(tiltPos + 0.5));
  }
}
