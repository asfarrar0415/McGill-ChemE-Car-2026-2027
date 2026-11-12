import lgpio
import time

# ---------- Pin configuration (BCM numbering) ----------
MOTOR_PWM_PIN = 18      # driver enable / PWM input
DIR_PIN_1 = 23          # driver IN1
DIR_PIN_2 = 22          # driver IN2
UPPER_SWITCH_PIN = 17   # upper limit switch (other side to GND)

# ---------- Settings ----------
CHIP = 4                # Pi 5 header = gpiochip4 (use 0 on Pi 4 and earlier)
PWM_FREQ = 1000         # Hz
RAISE_SPEED = 80        # duty cycle %, 0-100
MAX_RUN_SECONDS = 30    # safety timeout
DEBOUNCE_US = 20000     # 20 ms

h = lgpio.gpiochip_open(CHIP)

for pin in (MOTOR_PWM_PIN, DIR_PIN_1, DIR_PIN_2):
    lgpio.gpio_claim_output(h, pin, 0)

lgpio.gpio_claim_input(h, UPPER_SWITCH_PIN, lgpio.SET_PULL_UP)
lgpio.gpio_set_debounce_micros(h, UPPER_SWITCH_PIN, DEBOUNCE_US)


def at_top():
    return lgpio.gpio_read(h, UPPER_SWITCH_PIN) == 0   # pressed = 0


def motor_off():
    lgpio.tx_pwm(h, MOTOR_PWM_PIN, PWM_FREQ, 0)
    lgpio.gpio_write(h, MOTOR_PWM_PIN, 0)
    lgpio.gpio_write(h, DIR_PIN_1, 0)
    lgpio.gpio_write(h, DIR_PIN_2, 0)


try:
    if at_top():
        print("Already at the starting position")
    else:
        print("Resetting to the starting position...")

        # Direction "up" (swap these two lines if your motor runs backwards)
        lgpio.gpio_write(h, DIR_PIN_1, 0)
        lgpio.gpio_write(h, DIR_PIN_2, 1)
        lgpio.tx_pwm(h, MOTOR_PWM_PIN, PWM_FREQ, RAISE_SPEED)

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
    for pin in (MOTOR_PWM_PIN, DIR_PIN_1, DIR_PIN_2, UPPER_SWITCH_PIN):
        lgpio.gpio_free(h, pin)
    lgpio.gpiochip_close(h)
