# contraption.py
import lgpio
import time

# ---------- Pin configuration (BCM numbering) ----------
MOTOR_PWM_PIN = 18      # driver enable / PWM input
DIR_PIN_1 = 14          # driver IN1
DIR_PIN_2 = 15          # driver IN2
LOWER_SWITCH_PIN = 16   # lower limit switch (other side to GND)
UPPER_SWITCH_PIN = 17   # upper limit switch (other side to GND)
START_BUTTON_PIN = 25   # start button (other side to GND)
RESET_BUTTON_PIN = 24   # reset button (other side to GND)

# ---------- Default settings ----------
CHIP = 4                # Pi 5 header = gpiochip4 (use 0 on Pi 4 and earlier)
PWM_FREQ = 1000         # Hz
LOWER_SPEED = 60        # duty cycle %, 0-100
RAISE_SPEED = 80
MAX_RUN_SECONDS = 30    # safety timeout per move
DEBOUNCE_US = 20000     # 20 ms


def run_stopping_mech_motor(should_stop=None, chip=CHIP, lower_speed=LOWER_SPEED,
                    raise_speed=RAISE_SPEED, max_run_seconds=MAX_RUN_SECONDS):
    """
    Wait for button presses and run the contraption:
      START button -> lower until the lower limit switch triggers
      RESET button -> raise until the upper limit switch triggers

    Blocks until Ctrl+C, or until should_stop() returns True
    (should_stop is an optional function you pass in; it is checked
    between button presses, not in the middle of a move).

    GPIO is always released and the motor turned off when this returns.
    """
    input_pins = (LOWER_SWITCH_PIN, UPPER_SWITCH_PIN,
                  START_BUTTON_PIN, RESET_BUTTON_PIN)
    output_pins = (MOTOR_PWM_PIN, DIR_PIN_1, DIR_PIN_2)

    h = lgpio.gpiochip_open(chip)

    def pressed(pin):
        return lgpio.gpio_read(h, pin) == 0

    def wait_for_release(pin):
        while pressed(pin):
            time.sleep(0.01)

    def motor_off():
        lgpio.tx_pwm(h, MOTOR_PWM_PIN, PWM_FREQ, 0)
        lgpio.gpio_write(h, MOTOR_PWM_PIN, 0)
        lgpio.gpio_write(h, DIR_PIN_1, 0)
        lgpio.gpio_write(h, DIR_PIN_2, 0)

    def move(direction, speed, stop_switch_pin, label):
        """Run the motor until stop_switch_pin is pressed or the timeout hits."""
        if pressed(stop_switch_pin):
            print(f"Already at the {label}")
            return True

        # Set direction (swap these if your motor runs backwards)
        if direction == "down":
            lgpio.gpio_write(h, DIR_PIN_1, 1)
            lgpio.gpio_write(h, DIR_PIN_2, 0)
        else:
            lgpio.gpio_write(h, DIR_PIN_1, 0)
            lgpio.gpio_write(h, DIR_PIN_2, 1)

        print(f"Moving {direction}...")
        lgpio.tx_pwm(h, MOTOR_PWM_PIN, PWM_FREQ, speed)

        start = time.time()
        reached = False
        while time.time() - start < max_run_seconds:
            if pressed(stop_switch_pin):
                reached = True
                break
            time.sleep(0.005)

        motor_off()

        if reached:
            print(f"Reached the {label}")
        else:
            print(f"Timeout: {label} switch never triggered, motor stopped for safety")
        return reached

    try:
        for pin in output_pins:
            lgpio.gpio_claim_output(h, pin, 0)
        for pin in input_pins:
            lgpio.gpio_claim_input(h, pin, lgpio.SET_PULL_UP)
            lgpio.gpio_set_debounce_micros(h, pin, DEBOUNCE_US)

        print("Ready. START = lower the contraption, RESET = raise it to the top.")
        while not (should_stop and should_stop()):
            if pressed(START_BUTTON_PIN):
                print("Start button pressed")
                move("down", lower_speed, LOWER_SWITCH_PIN, "bottom")
                wait_for_release(START_BUTTON_PIN)
                print("Waiting for the next button press...")

            elif pressed(RESET_BUTTON_PIN):
                print("Reset button pressed")
                move("up", raise_speed, UPPER_SWITCH_PIN, "top")
                wait_for_release(RESET_BUTTON_PIN)
                print("Waiting for the next button press...")

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nStopped by user")

    finally:
        motor_off()
        for pin in output_pins + input_pins:
            lgpio.gpio_free(h, pin)
        lgpio.gpiochip_close(h)


if __name__ == "__main__":
    run_contraption()
