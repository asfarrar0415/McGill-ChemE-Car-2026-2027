
#!/usr/bin/env python3
"""
Hardware troubleshooting menu for the lowering contraption.
 
Run it on the Pi (stop your main script first, it would hold the pins):
    python3 diagnose.py            # auto-detects the GPIO chip
    python3 diagnose.py --chip 0   # force a chip number
 
Tests:
  1  Quick check     chip, idle state of every switch/button, GPIO18 readback
  2  Live monitor    prints every switch/button change as you press them
  3  Motor test      drives GPIO18 at a chosen duty cycle for a few seconds
  4  Direction test  runs both directions (H-bridge driver with IN1/IN2 pins)
  5  ADC test        reads a few samples from the ADC
  6  Set pins        change motor/direction pin numbers for this session
 
KEEP THE CONTRAPTION CLEAR before motor tests. Ctrl+C stops the motor.
"""
 
import argparse
import sys
import time
from contextlib import contextmanager
 
import lgpio
 
# Pull-up inputs: pressed = reads 0
INPUTS = {"bottom switch": 16, "upper switch": 17, "START": 25, "RESET": 24}
 
cfg = {"motor": 18, "dir1": None, "dir2": None, "pwm_freq": 1000}
 
 
# ---------------- helpers ----------------
def find_chip():
    """Open each gpiochip, print what it is, and pick the Pi header chip."""
    pick = None
    for c in range(6):
        try:
            h = lgpio.gpiochip_open(c)
        except Exception:
            continue
        try:
            _, lines, name, label = lgpio.gpio_get_chip_info(h)
        except Exception:
            lines, name, label = "?", "?", "?"
        print(f"  gpiochip{c}: {lines} lines, name={name}, label={label}")
        if pick is None and any(k in str(label).lower() for k in ("rp1", "bcm")):
            pick = c
        lgpio.gpiochip_close(h)
    return pick
 
 
@contextmanager
def claimed(h, outputs=(), inputs=()):
    """Claim pins for a test and always free them afterwards."""
    got = []
    try:
        for p in outputs:
            lgpio.gpio_claim_output(h, p, 0)
            got.append(p)
        for p in inputs:
            lgpio.gpio_claim_input(h, p, lgpio.SET_PULL_UP)
            got.append(p)
        yield
    finally:
        for p in got:
            try:
                lgpio.gpio_free(h, p)
            except Exception:
                pass
 
 
def state(h, pin):
    return "PRESSED" if lgpio.gpio_read(h, pin) == 0 else "open"
 
 
def motor_pins():
    return [p for p in (cfg["motor"], cfg["dir1"], cfg["dir2"]) if p is not None]
 
 
def motor_off(h):
    lgpio.tx_pwm(h, cfg["motor"], cfg["pwm_freq"], 0)
    for p in motor_pins():
        lgpio.gpio_write(h, p, 0)
 
 
def ask(prompt, default):
    raw = input(f"{prompt} [{default}]: ").strip()
    return type(default)(raw) if raw else default
 
 
def confirm_clear():
    return input("Is the contraption clear to move? (y/N): ").strip().lower() == "y"
 
 
# ---------------- tests ----------------
def quick_check(h):
    print("\n-- Quick check --")
    with claimed(h, inputs=INPUTS.values()):
        time.sleep(0.05)
        print("Idle state (nothing pressed, so everything should say 'open'):")
        bad = []
        for name, pin in INPUTS.items():
            s = state(h, pin)
            print(f"  GPIO{pin:<2} {name:<14} {s}")
            if s == "PRESSED":
                bad.append(name)
 
    if bad:
        print("\nProblems:")
        for name in bad:
            if name == "bottom switch":
                print("  * bottom switch reads pressed -> the motor never starts "
                      "('Already at the bottom'). Wired normally-closed, or shorted to GND?")
            elif name == "RESET":
                print("  * RESET reads pressed -> lowering is aborted instantly. "
                      "Button wired normally-closed, or pin shorted?")
            elif name == "START":
                print("  * START reads pressed -> it would trigger by itself. Check wiring.")
            else:
                print(f"  * {name} reads pressed while idle. Check wiring.")
    else:
        print("\nAll inputs idle correctly.")
 
    print(f"\nGPIO{cfg['motor']} output readback (write 1/0, read the pin):")
    try:
        with claimed(h, outputs=[cfg["motor"]]):
            lgpio.gpio_write(h, cfg["motor"], 1)
            hi = lgpio.gpio_read(h, cfg["motor"])
            lgpio.gpio_write(h, cfg["motor"], 0)
            lo = lgpio.gpio_read(h, cfg["motor"])
        print(f"  wrote 1 -> read {hi}, wrote 0 -> read {lo}")
        if (hi, lo) != (1, 0):
            print("  * Pin did not follow what was written: shorted, or another "
                  "program/overlay is using it.")
        else:
            print("  Pin works. If the motor still doesn't move, check the driver/"
                  "MOSFET, motor power, common ground, and direction pins.")
    except Exception as e:
        print(f"  * Could not claim GPIO{cfg['motor']}: {e}\n"
              "    (another script still running? stop it first)")
 
 
def live_monitor(h):
    print("\n-- Live monitor -- press each switch/button; Ctrl+C to stop.")
    with claimed(h, inputs=INPUTS.values()):
        last = {}
        t0 = time.monotonic()
        try:
            while True:
                for name, pin in INPUTS.items():
                    s = state(h, pin)
                    if last.get(pin) != s:
                        print(f"  {time.monotonic() - t0:7.2f}s  GPIO{pin:<2} {name:<14} {s}")
                        last[pin] = s
                time.sleep(0.01)
        except KeyboardInterrupt:
            print("\n  stopped")
 
 
def run_motor(h, duty, seconds, direction=None):
    """direction: None (no direction pins), 'A' or 'B'."""
    with claimed(h, outputs=motor_pins()):
        if direction and cfg["dir1"] is not None:
            lgpio.gpio_write(h, cfg["dir1"], 1 if direction == "A" else 0)
        if direction and cfg["dir2"] is not None:
            lgpio.gpio_write(h, cfg["dir2"], 0 if direction == "A" else 1)
        try:
            lgpio.tx_pwm(h, cfg["motor"], cfg["pwm_freq"], duty)
            t0 = time.monotonic()
            while time.monotonic() - t0 < seconds:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("  interrupted")
        finally:
            motor_off(h)
 
 
def motor_test(h):
    print("\n-- Motor test --")
    print(f"Drives GPIO{cfg['motor']}; direction pins: {cfg['dir1']}, {cfg['dir2']} "
          "(None = not used; set them with option 6 for an H-bridge).")
    duty = ask("Duty cycle %, 1-100", 60)
    seconds = ask("Seconds, 1-5", 2)
    seconds = max(1, min(5, seconds))
    if not confirm_clear():
        return
    # With direction pins set, test one direction; use option 4 to test both
    print(f"Running at {duty}% for {seconds}s ...")
    run_motor(h, max(1, min(100, duty)), seconds, "A" if cfg["dir1"] is not None else None)
    print("Done. Did it move?\n"
          "  yes -> the motor path works; the problem is in the switch/button states\n"
          "  no  -> driver/MOSFET, motor supply, common ground, or direction pins")
 
 
def direction_test(h):
    print("\n-- Direction test (H-bridge) --")
    if cfg["dir1"] is None and cfg["dir2"] is None:
        print("No direction pins set. Use option 6 first (e.g. 14 and 15).")
        return
    duty = ask("Duty cycle %, 1-100", 60)
    if not confirm_clear():
        return
    for d in ("A", "B"):
        print(f"Direction {d} for 2 s ...")
        run_motor(h, max(1, min(100, duty)), 2, d)
        time.sleep(0.5)
    print("Done. If neither direction moved, check the driver's power and enable "
          "pin. If it moved but the wrong way for lowering, swap the two "
          "direction values in your main script.")
 
 
def adc_test():
    print("\n-- ADC test --")
    kind = input("ADC type ads1115/mcp3008/mcp3208 [ads1115]: ").strip() or "ads1115"
    ch = ask("Channel", 0)
    try:
        if kind == "ads1115":
            import board
            import busio
            import adafruit_ads1x15.ads1115 as ADS
            from adafruit_ads1x15.analog_in import AnalogIn
            ads = ADS.ADS1115(busio.I2C(board.SCL, board.SDA))
            chan = AnalogIn(ads, [ADS.P0, ADS.P1, ADS.P2, ADS.P3][ch])
            read = lambda: f"raw={chan.value} {chan.voltage:.4f} V"
        else:
            from gpiozero import MCP3008, MCP3208
            adc = (MCP3008 if kind == "mcp3008" else MCP3208)(channel=ch)
            read = lambda: f"value={adc.value:.4f} ({adc.value * 3.3:.3f} V at 3.3 V ref)"
        for _ in range(10):
            print("  ", read())
            time.sleep(0.2)
        print("Cover/uncover the phototransistor and rerun: the value should change.")
    except Exception as e:
        print(f"  * ADC failed: {e}")
        print("    Check: I2C/SPI enabled in raspi-config, wiring, and "
              "`sudo i2cdetect -y 1` shows 0x48 for an ADS1115.")
 
 
def set_pins():
    print("\n-- Set pins (this session only) --")
    cfg["motor"] = ask("Motor PWM pin", cfg["motor"])
    for key, label in (("dir1", "Direction pin IN1"), ("dir2", "Direction pin IN2")):
        raw = input(f"{label} (blank = none) [{cfg[key]}]: ").strip()
        if raw:
            cfg[key] = int(raw)
        elif raw == "" and cfg[key] is not None:
            keep = input("  clear it? (y/N): ").strip().lower() == "y"
            cfg[key] = None if keep else cfg[key]
 
 
# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser(description="Contraption hardware troubleshooting")
    ap.add_argument("--chip", type=int, default=None, help="gpiochip number")
    args = ap.parse_args()
 
    print("Scanning GPIO chips:")
    detected = find_chip()
    chip = args.chip if args.chip is not None else detected
    if chip is None:
        sys.exit("No GPIO chip could be opened. Is lgpio installed? "
                 "(sudo apt install python3-lgpio)")
    print(f"Using gpiochip{chip}"
          f"{'' if args.chip is None else ' (from --chip)'}")
    print("Header chip: gpiochip4 on a Pi 5 (older images) or gpiochip0 "
          "(newer images and Pi 4 and earlier).")
 
    h = lgpio.gpiochip_open(chip)
    menu = {
        "1": ("Quick check", lambda: quick_check(h)),
        "2": ("Live monitor", lambda: live_monitor(h)),
        "3": ("Motor test", lambda: motor_test(h)),
        "4": ("Direction test", lambda: direction_test(h)),
        "5": ("ADC test", adc_test),
        "6": ("Set pins", set_pins),
    }
    try:
        while True:
            print("\n=== Troubleshooting menu ===")
            for k, (name, _) in menu.items():
                print(f"  {k}  {name}")
            print("  q  Quit")
            choice = input("> ").strip().lower()
            if choice == "q":
                break
            if choice in menu:
                try:
                    menu[choice][1]()
                except KeyboardInterrupt:
                    print("\n  interrupted")
                except Exception as e:
                    print(f"  * Test failed: {e}")
            else:
                print("  Pick a number from the menu, or q.")
    finally:
        try:
            with claimed(h, outputs=motor_pins()):
                motor_off(h)
        except Exception:
            pass
        lgpio.gpiochip_close(h)
 
 
if __name__ == "__main__":
    main()
 
