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


def set_led(brightness=0, pulse_speed=255, pulse_table=0,
            pulse_asleep=False, pulse_awake=False):
    v = brightness & 0xFF
    v |= (pulse_speed & 0x1FF) << 8
    v |= (pulse_table & 0x3) << 17
    v |= pulse_asleep << 19
    v |= pulse_awake << 20
    dev.write(ecodes.EV_MSC, ecodes.MSC_PULSELED, v)


def on_connect(client, _userdata, _flags, _reason_code, _properties):
    # (Re)subscribe on every (re)connect
    client.subscribe(f"{PREFIX}/led/#")
    client.publish(f"{PREFIX}/status", "online", retain=True)


def on_message(_client, _userdata, msg):
    payload = msg.payload.decode(errors="replace").strip().lower()
    try:
        if msg.topic == f"{PREFIX}/led/brightness":
            # 0-255; also cancels pulsing
            set_led(brightness=max(0, min(255, int(payload))))
        elif msg.topic == f"{PREFIX}/led/pulse":
            if payload in ("off", "false", "0"):
                set_led(brightness=0)
            else:
                # "on"/"true" -> normal speed, or a number 0-510
                speed = 255 if payload in ("on", "true") \
                    else max(0, min(510, int(payload)))
                set_led(pulse_speed=speed, pulse_awake=True)
    except ValueError:
        pass  # ignore malformed payloads


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.will_set(f"{PREFIX}/status", "offline", retain=True)
client.connect(BROKER, PORT)
client.loop_start()

pressed_at = None
long_fired = False

# The PowerMate's encoder emits 2 counts per minimum physical step, in
# separate USB reports ~8ms apart. Accumulate rotation and flush after a
# short quiet window so one step becomes one message.
FLUSH_S = int(os.environ.get("PM_ROTATE_FLUSH_MS", "30")) / 1000
pending = {"rotate": 0, "rotate_pressed": 0}
flush_at = None


def flush_rotation():
    global flush_at
    for sub in pending:
        if pending[sub]:
            client.publish(f"{PREFIX}/{sub}", pending[sub])
            pending[sub] = 0
    flush_at = None


while True:
    deadlines = []
    if pressed_at is not None and not long_fired:
        deadlines.append(pressed_at + LONG_PRESS_S)
    if flush_at is not None:
        deadlines.append(flush_at)
    timeout = None
    if deadlines:
        timeout = max(0, min(deadlines) - time.monotonic())
    r, _, _ = select.select([dev], [], [], timeout)
    now = time.monotonic()

    if r:
        for ev in dev.read():
            if ev.type == ecodes.EV_REL and ev.code == ecodes.REL_DIAL:
                sub = "rotate_pressed" if pressed_at is not None else "rotate"
                pending[sub] += ev.value
                flush_at = now + FLUSH_S
            elif ev.type == ecodes.EV_KEY and ev.code == ecodes.BTN_0:
                flush_rotation()  # keep event ordering sane around clicks
                if ev.value == 1:
                    pressed_at = now
                    long_fired = False
                elif pressed_at is not None:
                    if not long_fired:
                        client.publish(f"{PREFIX}/button", "click")
                    pressed_at = None

    if pressed_at is not None and not long_fired:
        if now >= pressed_at + LONG_PRESS_S:
            client.publish(f"{PREFIX}/button", "long_press")
            long_fired = True
    if flush_at is not None and now >= flush_at:
        flush_rotation()
