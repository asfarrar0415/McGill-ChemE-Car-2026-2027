import time 
import lgpio
 
# ---------- Defaults (BCM numbering) ----------
MOTOR_PWM_PIN = 18      # driver enable / PWM input
DIR_PIN_1 = 14          # driver IN1
DIR_PIN_2 = 15          # driver IN2
LOWER_SWITCH_PIN = 16   # lower limit switch (other side to GND)
UPPER_SWITCH_PIN = 17   # upper limit switch (other side to GND)
 
PWM_FREQ = 1000         # Hz
LOWER_SPEED = 60        # duty cycle %, 0-100
RAISE_SPEED = 80
MAX_RUN_SECONDS = 30    # safety timeout per move
DEBOUNCE_US = 20000     # 20 ms
 
REACHED, TIMEOUT, ABORTED = "reached", "timeout", "aborted"
 
 
class StoppingMech:
    """
    Lowers/raises the contraption between two limit switches.
 
    It does NOT watch any buttons and does NOT open its own GPIO chip.
    The caller passes in an open lgpio handle and decides when to move.
    Each move returns "reached", "timeout" or "aborted".
    """
 
    def __init__(self, h, pwm_pin=MOTOR_PWM_PIN, dir1=DIR_PIN_1, dir2=DIR_PIN_2,
                 lower_pin=LOWER_SWITCH_PIN, upper_pin=UPPER_SWITCH_PIN,
                 pwm_freq=PWM_FREQ, lower_speed=LOWER_SPEED, raise_speed=RAISE_SPEED,
                 max_run_seconds=MAX_RUN_SECONDS):
        self.h = h
        self.pwm_pin, self.dir1, self.dir2 = pwm_pin, dir1, dir2
        self.lower_pin, self.upper_pin = lower_pin, upper_pin
        self.pwm_freq = pwm_freq
        self.lower_speed, self.raise_speed = lower_speed, raise_speed
        self.max_run_seconds = max_run_seconds
        self._outputs = (pwm_pin, dir1, dir2)
        self._inputs = (lower_pin, upper_pin)
        self._claimed = False
        self._claim()
 
    # ---------- pin setup ----------
    def _claim(self):
        for pin in self._outputs:
            lgpio.gpio_claim_output(self.h, pin, 0)
        for pin in self._inputs:
            lgpio.gpio_claim_input(self.h, pin, lgpio.SET_PULL_UP)
            lgpio.gpio_set_debounce_micros(self.h, pin, DEBOUNCE_US)
        self._claimed = True
 
    def close(self):
        """Stop the motor and release the pins (not the chip handle)."""
        if not self._claimed:
            return
        self.motor_off()
        for pin in self._outputs + self._inputs:
            try:
                lgpio.gpio_free(self.h, pin)
            except Exception:
                pass
        self._claimed = False
 
    # ---------- state ----------
    def _pressed(self, pin):
        return lgpio.gpio_read(self.h, pin) == 0
 
    def at_top(self):
        return self._pressed(self.upper_pin)
 
    def at_bottom(self):
        return self._pressed(self.lower_pin)
 
    def motor_off(self):
        lgpio.tx_pwm(self.h, self.pwm_pin, self.pwm_freq, 0)
        lgpio.gpio_write(self.h, self.pwm_pin, 0)
        lgpio.gpio_write(self.h, self.dir1, 0)
        lgpio.gpio_write(self.h, self.dir2, 0)
 
    # ---------- movement ----------
    def _move(self, direction, speed, stop_pin, abort=None):
        if self._pressed(stop_pin):
            return REACHED
 
        # Swap these two values if your motor runs backwards
        down = direction == "down"
        lgpio.gpio_write(self.h, self.dir1, 1 if down else 0)
        lgpio.gpio_write(self.h, self.dir2, 0 if down else 1)
        lgpio.tx_pwm(self.h, self.pwm_pin, self.pwm_freq, speed)
 
        result = TIMEOUT
        try:
            start = time.monotonic()
            while time.monotonic() - start < self.max_run_seconds:
                if self._pressed(stop_pin):
                    result = REACHED
                    break
                if abort and abort():
                    result = ABORTED
                    break
                time.sleep(0.005)
        finally:
            self.motor_off()
        return result
 
    def lower(self, abort=None):
        """Lower until the bottom switch. abort() is polled during the move."""
        return self._move("down", self.lower_speed, self.lower_pin, abort)
 
    def raise_to_top(self, abort=None):
        """Raise until the top switch. abort() is polled during the move."""
        return self._move("up", self.raise_speed, self.upper_pin, abort)
 
