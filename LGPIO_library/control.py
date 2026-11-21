
#!/usr/bin/env python3
"""
Main control loop.
 
One thread (the caller of Controller.run) owns the START/RESET buttons, the car
motor, and the sequence. A single worker thread records ADC data, and an
optional one logs the encoder.
 
Cycle:
  IDLE -> START pressed -> start recording -> LOWERING (stopping mech)
       -> RUNNING (car motor on) until the algorithm trips, RESET is pressed,
          or MAX_CAR_RUN_SECONDS passes
       -> car off, stop recording -> RESETTING (mech back to top) -> IDLE
 
If LOWER_SECONDS is set, the mech lowers for that long (ignoring the bottom
switch) and the algorithm + car motor start as soon as it stops.
RESET while IDLE raises the mech to the top (manual homing).
RESET at any other time stops every motor (car + mech) immediately, if still
running. Pressing RESET again during a raise stops that raise too.
"""
import threading
import time
import traceback
from datetime import datetime
 
import lgpio
 
from dependencies.ads1115 import init_ads1115
from dependencies.algorithm import algo
from dependencies.board import Board
from dependencies.ls7366r_encoder_control import run_ls7366r
from dependencies.stopping_mech_motor import StoppingMech, REACHED, ABORTED
 
# ---------- Pins (BCM) ----------
START = 25
RESET = 24
CAR_MOTOR = 23           # drive through a transistor/MOSFET, never the pin directly
 
# ---------- Settings ----------
CHIP = 0                 # gpiochip number; run `gpiodetect` (4 on some Pi 5 images)
DEBOUNCE_US = 20000
POLL_S = 0.02
 
LOG_RATE_HZ = 10
STOP_ABOVE_MV = 3700.0   # stop when the reading is at or above this many mV (3.7 V)
STOP_CONSECUTIVE = 5     # ...for this many samples IN A ROW (5 = 0.5 s at 10 Hz)
STOP_BELOW_MV = None     # TODO: ...or when it falls below this
MAX_CAR_RUN_SECONDS = 120    # watchdog: car always stops after this
USE_ENCODER = False      # True = also log encoder distance/speed (needs SPI + LS7366R)
 
# Lower the mech for this many seconds instead of waiting for the bottom switch,
# then start the algorithm. Set to None to go back to using the bottom switch.
LOWER_SECONDS = 2.0
 
 
class Controller:
    def __init__(self, on_status=print):
        """on_status(text) is called on every state change
        (hook your dashboard in here, e.g. on_status=dashboard.update_reset)."""
        self.on_status = on_status
        self.shutdown = threading.Event()    # set to end run()
        self.h = None
        self.mech = None
        self.ads = None
        self._pins = ()
 
    # ---------- helpers ----------
    def _status(self, text):
        print(f"[{text}]")
        try:
            self.on_status(text)
        except Exception:
            traceback.print_exc()
 
    def _pressed(self, pin):
        return lgpio.gpio_read(self.h, pin) == 0
 
    def _abort(self):
        """Used while lowering/running: RESET or shutdown cancels."""
        return self.shutdown.is_set() or self._pressed(RESET)
 
    def _wait_for_release(self, pin):
        while self._pressed(pin) and not self.shutdown.is_set():
            time.sleep(POLL_S)
        time.sleep(0.05)
 
    def _car(self, on):
        lgpio.gpio_write(self.h, CAR_MOTOR, 1 if on else 0)
 
    def _stop_motors(self):
        """Cut every motor (car + stopping mech). Safe to call repeatedly:
        it does nothing if they are already stopped."""
        try:
            self._car(False)
        except Exception:
            traceback.print_exc()
        try:
            if self.mech:
                self.mech.motor_off()
        except Exception:
            traceback.print_exc()
 
    # ---------- setup / teardown ----------
    def setup(self):
        self.h = Board().get_gpio_handle(CHIP)     # the one and only chip handle
 
        lgpio.gpio_claim_output(self.h, CAR_MOTOR, 0)
        for pin in (START, RESET):                 # plain input + pull-up, no alert claim
            lgpio.gpio_claim_input(self.h, pin, lgpio.SET_PULL_UP)
            lgpio.gpio_set_debounce_micros(self.h, pin, DEBOUNCE_US)
        self._pins = (CAR_MOTOR, START, RESET)
 
        self.mech = StoppingMech(self.h)
        self.ads = init_ads1115()
 
    def cleanup(self):
        self.shutdown.set()
        try:
            if self.h is not None:
                self._car(False)
        except Exception:
            pass
        if self.mech:
            self.mech.close()
        if self.ads:
            self.ads.close()
        for pin in self._pins:
            try:
                lgpio.gpio_free(self.h, pin)
            except Exception:
                pass
        Board().close()
        print("closed")
 
    # ---------- one run ----------
    def run_cycle(self):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stop_logging = threading.Event()
        logger_done = threading.Event()
        result = {}
 
        def logger():
            try:
                result.update(algo(
                    read=self.ads.get_adjusted_mvs,
                    output=f"run_{stamp}.csv",
                    rate=LOG_RATE_HZ,
                    header=("mv",),
                    stop_value=STOP_ABOVE_MV,
                    stop_below=STOP_BELOW_MV,
                    stop_count=STOP_CONSECUTIVE,
                    should_stop=stop_logging.is_set,
                    verbose=False))
            except Exception:
                traceback.print_exc()
            finally:
                logger_done.set()      # a crashed logger also ends the run (car goes off)
 
        threads = [threading.Thread(target=logger, name="logger")]
        if USE_ENCODER:
            threads.append(threading.Thread(
                target=run_ls7366r, name="encoder",
                args=(stop_logging,), kwargs={"output": f"encoder_{stamp}.csv"}))
 
        try:
            self._status("LOWERING")
            if LOWER_SECONDS is None:
                for t in threads:                  # switch mode: record a baseline while lowering
                    t.start()
                outcome = self.mech.lower(abort=self._abort)
            else:
                outcome = self.mech.lower_for(LOWER_SECONDS, abort=self._abort)
 
            if outcome == REACHED:
                if LOWER_SECONDS is not None:      # timed mode: algorithm starts once the mech stops
                    for t in threads:
                        t.start()
                self._status("RUNNING")
                self._car(True)
                deadline = time.monotonic() + MAX_CAR_RUN_SECONDS
                reason = "algorithm finished"
                while not logger_done.is_set():
                    if self._abort():
                        reason = "RESET pressed" if not self.shutdown.is_set() else "shutdown"
                        break
                    if time.monotonic() > deadline:
                        reason = "watchdog timeout"
                        break
                    logger_done.wait(POLL_S)
                self._car(False)
                print(f"Car stopped: {reason}")
            else:
                print(f"Lowering ended with '{outcome}', car not started")
        finally:
            self._stop_motors()        # RESET (or any exit): every motor off, whatever happened
            stop_logging.set()
            for t in threads:
                if t.is_alive():                   # threads that never started can't be joined
                    t.join(timeout=5)
            if result:
                print(f"Log: {result}")
 
            # The RESET press that ended the run must be released first, otherwise
            # it would immediately cancel the raise below.
            self._wait_for_release(RESET)
            self._status("RESETTING")
            # A NEW RESET press (or shutdown) stops the raise
            if self.mech.raise_to_top(abort=self._abort) == ABORTED:
                self._stop_motors()
                self._status("STOPPED")
            self._wait_for_release(RESET)
 
    # ---------- main loop ----------
    def run(self):
        try:
            self.setup()
            while not self.shutdown.is_set():
                self._status("IDLE")
                pin = None
                while pin is None and not self.shutdown.is_set():
                    if self._pressed(START):
                        pin = START
                    elif self._pressed(RESET):
                        pin = RESET
                    else:
                        time.sleep(POLL_S)
                if pin is None:
                    break
 
                self._wait_for_release(pin)
                if pin == START:
                    self.run_cycle()
                else:
                    self._status("RESETTING")
                    # Pressing RESET again stops the raise
                    if self.mech.raise_to_top(abort=self._abort) == ABORTED:
                        self._stop_motors()
                        self._status("STOPPED")
                        self._wait_for_release(RESET)   # don't re-trigger from the same press
        except KeyboardInterrupt:
            print("\nStopped by user")
        except Exception:
            traceback.print_exc()
        finally:
            self.cleanup()
 
 
if __name__ == "__main__":
    Controller().run()
 
