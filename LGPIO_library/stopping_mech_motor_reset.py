import lgpio
import time

# ---------- Pin configuration (BCM numbering) ----------
MOTOR_PIN = 18          # -> transistor/MOSFET gate (via ~1k resistor)
UPPER_SWITCH_PIN = 17   # upper limit switch (other side to GND)

# ---------- Settings ----------
CHIP = 4                # Pi 5 header = gpiochip4 (use 0 on Pi 4 and earlier)
PWM_FREQ = 1000         # Hz
RAISE_SPEED = 80        # duty cycle %, 0-100 (set to 100 for full on)
MAX_RUN_SECONDS = 30    # safety timeout
DEBOUNCE_US = 20000     # 20 ms

h = lgpio.gpiochip_open(CHIP)

lgpio.gpio_claim_output(h, MOTOR_PIN, 0)
lgpio.gpio_claim_input(h, UPPER_SWITCH_PIN, lgpio.SET_PULL_UP)
lgpio.gpio_set_debounce_micros(h, UPPER_SWITCH_PIN, DEBOUNCE_US)


def at_top():
    return lgpio.gpio_read(h, UPPER_SWITCH_PIN) == 0   # pressed = 0


def motor_off():
    lgpio.tx_pwm(h, MOTOR_PIN, PWM_FREQ, 0)
    lgpio.gpio_write(h, MOTOR_PIN, 0)


try:
    if at_top():
        print("Already at the starting position")
    else:
        print("Resetting to the starting position...")
        lgpio.tx_pwm(h, MOTOR_PIN, PWM_FREQ, RAISE_SPEED)

        start = time.time()
        reached = False
        while time.time() - start < MAX_RUN_SECONDS:
            if at_top():
                reached = True
                break
            time.sleep(0.005)

        motor_off()

        if reached:
            print("Done: contraption is at the starting position")
        else:
            print("Timeout: upper switch never triggered, motor stopped for safety")

except KeyboardInterrupt:
    print("\nStopped by user")

finally:
    motor_off()
    lgpio.gpio_free(h, MOTOR_PIN)
    lgpio.gpio_free(h, UPPER_SWITCH_PIN)
    lgpio.gpiochip_close(h)
