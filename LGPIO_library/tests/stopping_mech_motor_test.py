import lgpio
import time

MOTOR_PIN = 18          # BCM GPIO18 -> motor driver input
SWITCH_PIN = 16         # BCM GPIO16 -> bottom limit switch (other side to GND)
START_PIN = 25          # BCM GPIO25 -> start button (other side to GND)

PWM_FREQ = 1000         # Hz
MOTOR_SPEED = 60        # duty cycle, 0-100
MAX_RUN_SECONDS = 30    # safety timeout if the switch never triggers
DEBOUNCE_US = 20000     # 20 ms debounce

# On a Pi 5 the header is on gpiochip4 (use 0 on Pi 4 and earlier;
# newer OS images also expose it as gpiochip0 on Pi 5)
CHIP = 4

h = lgpio.gpiochip_open(CHIP)

# Motor output, starts low (off)
lgpio.gpio_claim_output(h, MOTOR_PIN, 0)

# Inputs with internal pull-up (pressed = pin reads 0)
for pin in (SWITCH_PIN, START_PIN):
    lgpio.gpio_claim_input(h, pin, lgpio.SET_PULL_UP)
    lgpio.gpio_set_debounce_micros(h, pin, DEBOUNCE_US)


def motor_off():
    lgpio.tx_pwm(h, MOTOR_PIN, PWM_FREQ, 0)   # 0% duty
    lgpio.gpio_write(h, MOTOR_PIN, 0)


def pressed(pin):
    return lgpio.gpio_read(h, pin) == 0


def lower():
    if pressed(SWITCH_PIN):
        print("Already at the bottom, not starting")
        return

    print("Lowering...")
    lgpio.tx_pwm(h, MOTOR_PIN, PWM_FREQ, MOTOR_SPEED)

    start = time.monotonic()
    reached = False
    while time.monotonic() - start < MAX_RUN_SECONDS:
        if pressed(SWITCH_PIN):
            reached = True
            break
        time.sleep(0.005)               # poll every 5 ms

    motor_off()

    if reached:
        print("Done: contraption is at the bottom")
    else:
        print("Timeout: switch never triggered, motor stopped for safety")


try:
    print("Ready. Press the START button to lower the contraption (Ctrl+C to quit).")
    while True:
        if pressed(START_PIN):
            print("Start button pressed")
            lower()

            # Wait for release so a held button doesn't retrigger
            while pressed(START_PIN):
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
