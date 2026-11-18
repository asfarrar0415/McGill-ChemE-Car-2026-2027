#!/usr/bin/env python3
"""
START  -> data logging to a new CSV begins and the motor lowers the contraption
          to the bottom limit switch. Logging KEEPS RECORDING after it stops.
RESET  -> logging stops and the CSV is closed. The contraption is NOT raised.
          If pressed mid-lowering, it also stops the motor.

Supported ADCs (--adc):
  ads1115   16-bit, I2C   (SDA=GPIO2, SCL=GPIO3)            [default]
  mcp3008   10-bit, SPI   (SCLK=GPIO11, MOSI=GPIO10, MISO=GPIO9, CE0=GPIO8)
  mcp3208   12-bit, SPI   (same wiring as MCP3008)
  digital   No ADC: reads a GPIO pin as on/off (use --pin)

PHOTOTRANSISTOR WIRING (all ADCs)
  Collector -> 3.3V
  Emitter   -> ADC input channel AND 10k resistor -> GND

USAGE
  python3 lower_log_reset.py                         # ADS1115, 10 Hz
  python3 lower_log_reset.py -a mcp3008 -c 0 -r 100 -o test
"""

import argparse
import csv
import signal
import sys
import threading
import time
from datetime import datetime

import lgpio

# ---------- Pins (BCM numbering) ----------
MOTOR_PIN = 18          # motor driver input (PWM)
SWITCH_PIN = 16         # bottom limit switch (other side to GND)
START_PIN = 25          # start button (other side to GND)
RESET_PIN = 24          # reset button (other side to GND)

# ---------- Motor settings ----------
PWM_FREQ = 1000         # Hz
MOTOR_SPEED = 60        # duty cycle, 0-100
MAX_RUN_SECONDS = 30    # safety timeout if the switch never triggers
DEBOUNCE_US = 20000     # 20 ms debounce

# On a Pi 5 the header is on gpiochip4 (use 0 on Pi 4 and earlier;
# newer OS images also expose it as gpiochip0 on Pi 5)
CHIP = 4


# ======================= ADC setup =======================
def make_ads1115(channel, vref):
    import board
    import busio
    import adafruit_ads1x15.ads1115 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn

    ads = ADS.ADS1115(busio.I2C(board.SCL, board.SDA))
    ads.gain = 1            # +/-4.096 V range
    ads.data_rate = 860
    chan = AnalogIn(ads, [ADS.P0, ADS.P1, ADS.P2, ADS.P3][channel])
    return ["raw_adc", "voltage_v"], lambda: (chan.value, round(chan.voltage, 5))


def make_mcp(kind, channel, vref):
    from gpiozero import MCP3008, MCP3208

    bits = 10 if kind == "mcp3008" else 12
    adc = (MCP3008 if kind == "mcp3008" else MCP3208)(channel=channel)
    full = (1 << bits) - 1

    def read():
        v = adc.value  # 0.0 - 1.0
        return round(v * full), round(v * vref, 5)

    return ["raw_adc", "voltage_v"], read


def make_digital(pin):
    from gpiozero import InputDevice

    dev = InputDevice(pin, pull_up=False)
    return ["state"], lambda: (int(dev.value),)


# ======================= CSV logger (runs in a thread) =======================
def log_data(path, header, read, rate, stop_event, stop_voltage, result):
    """Write one row per sample to `path` until stop_event is set."""
    interval = 1.0 / rate
    count = 0
    try:
        with open(path, "a", newline="") as f:
            writer = csv.writer(f)
            if f.tell() == 0:
                writer.writerow(["timestamp", "elapsed_s"] + header)

            start = time.monotonic()
            next_t = start
            last_flush = start

            while not stop_event.is_set():
                now = time.monotonic()
                values = list(read())
                writer.writerow([datetime.now().isoformat(timespec="milliseconds"),
                                 round(now - start, 4)] + values)
                count += 1

                if stop_voltage is not None and values[-1] > stop_voltage:
                    result["tripped"] = True
                    break

                if now - last_flush >= 1.0:
                    f.flush()
                    last_flush = now

                # Fixed-rate timing: skip ahead if we fall behind
                next_t += interval
                delay = next_t - time.monotonic()
                if delay > 0:
                    stop_event.wait(delay)      # wakes immediately when stopped
                else:
                    next_t = time.monotonic()

            f.flush()
    except Exception as e:                      # a logging problem must not stop the motor
        result["error"] = str(e)
    finally:
        result["samples"] = count


# ======================= Main =======================
def main():
    p = argparse.ArgumentParser(description="START lowers + logs, RESET stops logging")
    p.add_argument("-o", "--output", default="ir_data",
                   help="CSV filename prefix (a timestamp is added per run)")
    p.add_argument("-r", "--rate", type=float, default=10, help="samples per second")
    p.add_argument("-a", "--adc", default="ads1115",
                   choices=["ads1115", "mcp3008", "mcp3208", "digital"])
    p.add_argument("-c", "--channel", type=int, default=0, help="ADC channel number")
    p.add_argument("--vref", type=float, default=3.3, help="MCP30xx reference voltage")
    p.add_argument("--pin", type=int, default=17, help="GPIO pin, BCM (digital only)")
    p.add_argument("--stop-voltage", type=float, default=None,
                   help="stop LOGGING if voltage exceeds this (ADC modes only; off by default)")
    args = p.parse_args()

    if args.rate <= 0:
        sys.exit("Rate must be greater than 0")

    # ---- ADC ----
    if args.adc == "ads1115":
        if not 0 <= args.channel <= 3:
            sys.exit("ADS1115 channel must be 0-3")
        header, read = make_ads1115(args.channel, args.vref)
    elif args.adc in ("mcp3008", "mcp3208"):
        if not 0 <= args.channel <= 7:
            sys.exit("MCP30xx channel must be 0-7")
        header, read = make_mcp(args.adc, args.channel, args.vref)
    else:
        header, read = make_digital(args.pin)
    stop_voltage = None if args.adc == "digital" else args.stop_voltage

    # Make `kill`/systemd stops run the cleanup below, like Ctrl+C does
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))

    # ---- GPIO ----
    input_pins = (SWITCH_PIN, START_PIN, RESET_PIN)

    h = lgpio.gpiochip_open(CHIP)
    lgpio.gpio_claim_output(h, MOTOR_PIN, 0)
    for pin in input_pins:
        lgpio.gpio_claim_input(h, pin, lgpio.SET_PULL_UP)       # pressed = reads 0
        lgpio.gpio_set_debounce_micros(h, pin, DEBOUNCE_US)

    def pressed(pin):
        return lgpio.gpio_read(h, pin) == 0

    def wait_for_release(pin):
        while pressed(pin):
            time.sleep(0.01)

    def motor_off():
        lgpio.tx_pwm(h, MOTOR_PIN, PWM_FREQ, 0)
        lgpio.gpio_write(h, MOTOR_PIN, 0)

    def lower():
        """Lower until the bottom switch. Returns reached/timeout/aborted."""
        if pressed(SWITCH_PIN):
            return "reached"
        result = "timeout"
        try:
            lgpio.tx_pwm(h, MOTOR_PIN, PWM_FREQ, MOTOR_SPEED)
            start = time.monotonic()
            while time.monotonic() - start < MAX_RUN_SECONDS:
                if pressed(SWITCH_PIN):
                    result = "reached"
                    break
                if pressed(RESET_PIN):          # RESET mid-move stops the motor
                    result = "aborted"
                    break
                time.sleep(0.005)
        finally:
            motor_off()
        return result

    # ---- logging control ----
    run = {"thread": None, "stop": None, "result": None, "path": None}

    def start_logging():
        run["path"] = f"{args.output}_{datetime.now():%Y%m%d_%H%M%S}.csv"
        run["stop"] = threading.Event()
        run["result"] = {}
        run["thread"] = threading.Thread(
            target=log_data,
            args=(run["path"], header, read, args.rate, run["stop"], stop_voltage, run["result"]))
        run["thread"].start()
        print(f"Logging to {run['path']}")

    def stop_logging():
        """Safe to call more than once."""
        if run["thread"] is None:
            return
        run["stop"].set()
        run["thread"].join(timeout=5)
        res = run["result"]
        print(f"Logging stopped: {res.get('samples', 0)} samples saved to {run['path']}")
        if res.get("tripped"):
            print("Note: logging stopped early (stop-voltage exceeded)")
        if "error" in res:
            print(f"Logging error: {res['error']}")
        run["thread"] = None

    # ---- one START -> RESET cycle ----
    def run_cycle():
        start_logging()
        try:
            if pressed(SWITCH_PIN):
                print("Already at the bottom, skipping lowering")
                outcome = "reached"
            else:
                print("Lowering...")
                outcome = lower()

            if outcome == "reached":
                print("At the bottom. Still recording. Press RESET to stop logging.")
            elif outcome == "timeout":
                print("Timeout: bottom switch never triggered, motor stopped for safety. "
                      "Still recording. Press RESET to stop logging.")
            else:
                print("Lowering aborted by RESET, motor stopped")

            if outcome != "aborted":
                warned = False
                while not pressed(RESET_PIN):
                    if not warned and not run["thread"].is_alive():
                        print("Warning: the logger has stopped on its own")
                        warned = True
                    time.sleep(0.01)
                print("Reset button pressed")
        finally:
            stop_logging()      # always closes the CSV

    try:
        print("Ready. START = lower + log, RESET = stop logging (Ctrl+C to quit).")
        while True:
            if pressed(START_PIN):
                print("Start button pressed")
                run_cycle()
                wait_for_release(START_PIN)
                wait_for_release(RESET_PIN)
                print("Waiting for the next START press...")

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nStopped by user")

    finally:
        motor_off()
        stop_logging()
        for pin in (MOTOR_PIN,) + input_pins:
            lgpio.gpio_free(h, pin)
        lgpio.gpiochip_close(h)


if __name__ == "__main__":
    main()
