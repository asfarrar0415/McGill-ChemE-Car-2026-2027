
#!/usr/bin/env python3
"""
Press START -> the motor lowers the contraption AND IR phototransistor data is
logged to a CSV while the motor runs. Logging stops when the motor stops
(bottom switch reached, or the safety timeout). Each run gets its own CSV file.
 
Supported ADCs (--adc):
  ads1115   16-bit, I2C   (SDA=GPIO2, SCL=GPIO3)            [default]
  mcp3008   10-bit, SPI   (SCLK=GPIO11, MOSI=GPIO10, MISO=GPIO9, CE0=GPIO8)
  mcp3208   12-bit, SPI   (same wiring as MCP3008)
  digital   No ADC: reads a GPIO pin as on/off (use --pin)
 
PHOTOTRANSISTOR WIRING (all ADCs)
  Collector -> 3.3V
  Emitter   -> ADC input channel AND 10k resistor -> GND
 
SETUP
  sudo raspi-config     # Interface Options -> enable I2C (ads1115) or SPI (mcp30xx)
  pip install adafruit-circuitpython-ads1x15 gpiozero spidev --break-system-packages
 
USAGE
  python3 lower_and_log.py                         # ADS1115, 10 Hz
  python3 lower_and_log.py -a mcp3008 -c 0 -r 100 -o test
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
 
 
# ======================= Motor / GPIO =======================
def main():
    p = argparse.ArgumentParser(description="Lower the contraption on START and log IR data to CSV")
    p.add_argument("-o", "--output", default="ir_data",
                   help="CSV filename prefix (a timestamp is added per run)")
    p.add_argument("-r", "--rate", type=float, default=10, help="samples per second")
    p.add_argument("-a", "--adc", default="ads1115",
                   choices=["ads1115", "mcp3008", "mcp3208", "digital"])
    p.add_argument("-c", "--channel", type=int, default=0, help="ADC channel number")
    p.add_argument("--vref", type=float, default=3.3, help="MCP30xx reference voltage")
    p.add_argument("--pin", type=int, default=17, help="GPIO pin, BCM (digital only)")
    p.add_argument("--stop-voltage", type=float, default=None,
                   help="stop LOGGING if voltage exceeds this (ADC modes only; off by default). "
                        "The motor keeps running until the bottom switch.")
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
    h = lgpio.gpiochip_open(CHIP)
    lgpio.gpio_claim_output(h, MOTOR_PIN, 0)
    for pin in (SWITCH_PIN, START_PIN):
        lgpio.gpio_claim_input(h, pin, lgpio.SET_PULL_UP)       # pressed = reads 0
        lgpio.gpio_set_debounce_micros(h, pin, DEBOUNCE_US)
 
    def pressed(pin):
        return lgpio.gpio_read(h, pin) == 0
 
    def motor_off():
        lgpio.tx_pwm(h, MOTOR_PIN, PWM_FREQ, 0)
        lgpio.gpio_write(h, MOTOR_PIN, 0)
 
    def lower_and_log():
        if pressed(SWITCH_PIN):
            print("Already at the bottom, not starting")
            return
 
        path = f"{args.output}_{datetime.now():%Y%m%d_%H%M%S}.csv"
        stop_logging = threading.Event()
        result = {}
        logger = threading.Thread(
            target=log_data,
            args=(path, header, read, args.rate, stop_logging, stop_voltage, result))
 
        print(f"Lowering... logging to {path}")
        logger.start()                                  # logging begins as the motor starts
        reached = False
        try:
            lgpio.tx_pwm(h, MOTOR_PIN, PWM_FREQ, MOTOR_SPEED)
            start = time.monotonic()
            while time.monotonic() - start < MAX_RUN_SECONDS:
                if pressed(SWITCH_PIN):
                    reached = True
                    break
                time.sleep(0.005)
        finally:
            motor_off()                                 # motor stops first, always
            stop_logging.set()
            logger.join(timeout=5)
 
        print("Done: contraption is at the bottom" if reached else
              "Timeout: switch never triggered, motor stopped for safety")
        print(f"Saved {result.get('samples', 0)} samples to {path}")
        if result.get("tripped"):
            print("Note: logging stopped early (stop-voltage exceeded)")
        if "error" in result:
            print(f"Logging error: {result['error']}")
 
    try:
        print("Ready. Press the START button to lower and log (Ctrl+C to quit).")
        while True:
            if pressed(START_PIN):
                print("Start button pressed")
                lower_and_log()
                while pressed(START_PIN):               # wait for release
                    time.sleep(0.01)
                print("Waiting for the next press...")
            time.sleep(0.01)
 
    except KeyboardInterrupt:
        print("\nStopped by user")
 
    finally:
        motor_off()
        for pin in (MOTOR_PIN, SWITCH_PIN, START_PIN):
            lgpio.gpio_free(h, pin)
        lgpio.gpiochip_close(h)
 
 
if __name__ == "__main__":
    main()
 
