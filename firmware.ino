#include <Servo.h>
Servo pan, tilt;
int panAngle = 90, tiltAngle = 90;

void setup() {
  Serial.begin(115200);
  pan.attach(9);
  tilt.attach(10);
  pan.write(panAngle);
  tilt.write(tiltAngle);
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');   // expects "120,80\n"
    int comma = line.indexOf(',');
    if (comma > 0) {
      panAngle  = constrain(line.substring(0, comma).toInt(), 20, 160);
      tiltAngle = constrain(line.substring(comma + 1).toInt(), 45, 135);
      pan.write(panAngle);
      tilt.write(tiltAngle);
    }
  }
}