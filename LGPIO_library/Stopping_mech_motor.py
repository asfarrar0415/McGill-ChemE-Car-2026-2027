import lgpio
import time

MOTOR_PIN = 18          # BCM GPIO18 -> motor driver input
SWITCH_PIN = 23         # BCM GPIO23 -> bottom limit switch (other side to GND)

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

# Switch input with internal pull-up (pressed = pin reads 0)
lgpio.gpio_claim_input(h, SWITCH_PIN, lgpio.SET_PULL_UP)
lgpio.gpio_set_debounce_micros(h, SWITCH_PIN, DEBOUNCE_US)

def motor_off():
    lgpio.tx_pwm(h, MOTOR_PIN, PWM_FREQ, 0)   # 0% duty
    lgpio.gpio_write(h, MOTOR_PIN, 0)

def switch_pressed():
    return lgpio.gpio_read(h, SWITCH_PIN) == 0

try:
    if switch_pressed():
        print("Already at the bottom, not starting")
    else:
        print("Lowering...")
        lgpio.tx_pwm(h, MOTOR_PIN, PWM_FREQ, MOTOR_SPEED)

        start = time.time()
        reached = False
        while time.time() - start < MAX_RUN_SECONDS:
            if switch_pressed():
                reached = True
                break
            time.sleep(0.005)               # poll every 5 ms

        motor_off()

        if reached:
            print("Done: contraption is at the bottom")
        else:
            print("Timeout: switch never triggered, motor stopped for safety")

finally:
    motor_off()
    lgpio.gpio_free(h, MOTOR_PIN)
    lgpio.gpio_free(h, SWITCH_PIN)
    lgpio.gpiochip_close(h)
