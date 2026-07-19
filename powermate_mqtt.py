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
# connect_async + loop_start: the network thread owns the connection and
# retries with backoff (re-resolving DNS each time), so an unreachable
# or not-yet-resolvable broker at boot never crashes the service.
client.reconnect_delay_set(min_delay=1, max_delay=30)
client.connect_async(BROKER, PORT)
client.loop_start()

pressed_at = None
long_fired = False

# Normally the device emits 1 tick per step (pass-through, default 1).
# On marginal USB links (Pi undervoltage etc.) every report can arrive
# duplicated ~8ms apart; setting PM_TICKS_PER_STEP=2 divides by counting,
# emitting one event per 2 raw ticks, on the tick completing the step.
TICKS_PER_STEP = int(os.environ.get("PM_TICKS_PER_STEP", "1"))
acc = {"rotate": 0, "rotate_pressed": 0}

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
            acc[sub] += ev.value
            while abs(acc[sub]) >= TICKS_PER_STEP:
                step = 1 if acc[sub] > 0 else -1
                client.publish(f"{PREFIX}/{sub}", step)
                acc[sub] -= TICKS_PER_STEP * step
        elif ev.type == ecodes.EV_KEY and ev.code == ecodes.BTN_0:
            if ev.value == 1:
                pressed_at = time.monotonic()
                long_fired = False
            elif pressed_at is not None:
                if not long_fired:
                    client.publish(f"{PREFIX}/button", "click")
                pressed_at = None
