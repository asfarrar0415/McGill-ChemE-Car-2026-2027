#!/usr/bin/env python3
"""
Log IR phototransistor readings from an external ADC on a Raspberry Pi to CSV.

Supported ADCs (--adc):
  ads1115   16-bit, I2C   (SDA=GPIO2, SCL=GPIO3)            [default]
  mcp3008   10-bit, SPI   (SCLK=GPIO11, MOSI=GPIO10, MISO=GPIO9, CE0=GPIO8)
  mcp3208   12-bit, SPI   (same wiring as MCP3008)
  digital   No ADC: reads a GPIO pin as on/off (use --pin)

PHOTOTRANSISTOR WIRING (all ADCs)
  Collector -> 3.3V
  Emitter   -> ADC input channel AND 10k resistor -> GND
  (More IR light -> higher voltage.) Keep the ADC's Vref/VDD at 3.3V.

SETUP
  sudo raspi-config     # Interface Options -> enable I2C (ads1115) or SPI (mcp30xx)
  pip install adafruit-circuitpython-ads1x15 gpiozero spidev --break-system-packages

USAGE
  python3 ir_logger.py                                   # ADS1115, 10 Hz, Ctrl+C to stop
  python3 ir_logger.py --adc mcp3008 -c 0 -r 100 -d 30 -o test.csv
"""

import argparse
import csv
import signal
import sys
import time
from datetime import datetime

running = True


def stop(signum, frame):
    global running
    running = False


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


def main():
    p = argparse.ArgumentParser(description="Log IR phototransistor data to CSV")
    p.add_argument("-o", "--output", default="ir_data.csv", help="output CSV file")
    p.add_argument("-r", "--rate", type=float, default=10, help="samples per second")
    p.add_argument("-d", "--duration", type=float, default=0,
                   help="seconds to record (0 = until Ctrl+C)")
    p.add_argument("-a", "--adc", default="ads1115",
                   choices=["ads1115", "mcp3008", "mcp3208", "digital"])
    p.add_argument("-c", "--channel", type=int, default=0, help="ADC channel number")
    p.add_argument("--vref", type=float, default=3.3, help="MCP30xx reference voltage")
    p.add_argument("--pin", type=int, default=17, help="GPIO pin, BCM (digital only)")
    args = p.parse_args()

    if args.rate <= 0:
        sys.exit("Rate must be greater than 0")

    if args.adc == "ads1115":
        if not 0 <= args.channel <= 3:
            sys.exit("ADS1115 channel must be 0-3")
        value_header, read = make_ads1115(args.channel, args.vref)
    elif args.adc in ("mcp3008", "mcp3208"):
        if not 0 <= args.channel <= 7:
            sys.exit("MCP30xx channel must be 0-7")
        value_header, read = make_mcp(args.adc, args.channel, args.vref)
    else:
        value_header, read = make_digital(args.pin)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    interval = 1.0 / args.rate
    print(f"Logging {args.adc} to {args.output} at {args.rate} Hz. Ctrl+C to stop.")

    with open(args.output, "a", newline="") as f:
        writer = csv.writer(f)
        if f.tell() == 0:
            writer.writerow(["timestamp", "elapsed_s"] + value_header)

        start = time.monotonic()
        next_t = start
        last_flush = start
        count = 0

        while running:
            now = time.monotonic()
            elapsed = now - start
            if args.duration and elapsed >= args.duration:
                break

            row = [datetime.now().isoformat(timespec="milliseconds"),
                   round(elapsed, 4)] + list(read())
            writer.writerow(row)
            count += 1

            if now - last_flush >= 1.0:
                f.flush()
                last_flush = now
                print(f"\r{count} samples | latest: {row[2:]}", end="", flush=True)

            next_t += interval
            delay = next_t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.monotonic()

    print(f"\nDone. {count} samples saved to {args.output}")


if __name__ == "__main__":
    main()
