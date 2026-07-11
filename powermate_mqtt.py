import os
import select
import time

import paho.mqtt.client as mqtt
from evdev import InputDevice, ecodes

DEVICE = os.environ.get("PM_DEVICE", "/dev/input/powermate")
BROKER = os.environ.get("PM_BROKER", "localhost")
PORT = int(os.environ.get("PM_PORT", "1883"))
PREFIX = os.environ.get("PM_TOPIC_PREFIX", "powermate").rstrip("/")
LONG_PRESS_S = int(os.environ.get("PM_LONG_PRESS_MS", "600")) / 1000

dev = InputDevice(DEVICE)
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.will_set(f"{PREFIX}/status", "offline", retain=True)
client.connect(BROKER, PORT)
client.loop_start()
client.publish(f"{PREFIX}/status", "online", retain=True)

pressed_at = None
long_fired = False

while True:
    timeout = None
    if pressed_at is not None and not long_fired:
        timeout = max(0, pressed_at + LONG_PRESS_S - time.monotonic())
    r, _, _ = select.select([dev], [], [], timeout)

    if not r:  # held past threshold -> long press, suppress the click
        client.publish(f"{PREFIX}/button", "long_press")
        long_fired = True
        continue

    for ev in dev.read():
        if ev.type == ecodes.EV_REL and ev.code == ecodes.REL_DIAL:
            sub = "rotate_pressed" if pressed_at is not None else "rotate"
            client.publish(f"{PREFIX}/{sub}", ev.value)
        elif ev.type == ecodes.EV_KEY and ev.code == ecodes.BTN_0:
            if ev.value == 1:
                pressed_at = time.monotonic()
                long_fired = False
            elif pressed_at is not None:
                if not long_fired:
                    client.publish(f"{PREFIX}/button", "click")
                pressed_at = None
