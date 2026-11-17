#!/usr/bin/python
# LS7366R quadrature counter driver for the Raspberry Pi.
# Based on https://github.com/fbolanos/LS7366R (Federico Bolanos), with fixes.
import csv
import struct
import time
from functools import reduce
 
import spidev
 
class LS7366R:
    # Commands
    CLEAR_COUNTER = 0x20
    CLEAR_STATUS = 0x30
    READ_COUNTER = 0x60
    READ_STATUS = 0x70
    WRITE_DTR = 0x98
    LOAD_COUNTER = 0xE0
    LOAD_OTR = 0xE4
    WRITE_MODE0 = 0x88
    WRITE_MODE1 = 0x90
 
    # Count modes (MDR0). The original code used 0x01 and named it "FOURX".
    # By the datasheet 0x01 = x1, 0x02 = x2, 0x03 = x4. Default kept at 0x01 so
    # your existing counts-per-revolution calibration still holds; if you want
    # true x4 counting, pass quad_mode=LS7366R.X4_COUNT and recalibrate.
    X1_COUNT = 0x01
    X2_COUNT = 0x02
    X4_COUNT = 0x03
 
    # Byte modes (MDR1)
    FOURBYTE_COUNTER = 0x00
    THREEBYTE_COUNTER = 0x01
    TWOBYTE_COUNTER = 0x02
    ONEBYTE_COUNTER = 0x03
    BYTE_MODE = [ONEBYTE_COUNTER, TWOBYTE_COUNTER, THREEBYTE_COUNTER, FOURBYTE_COUNTER]
 
    EN_CNTR = 0x00
    DIS_CNTR = 0x04
 
    def __init__(self, cs_line, max_speed_hz, byte_mode, quad_mode=X1_COUNT):
        """byte_mode is 1-4 (counter width in bytes)."""
        if byte_mode not in (1, 2, 3, 4):
            raise ValueError("byte_mode must be 1-4")
        self.byte_mode = byte_mode
 
        self.spi = spidev.SpiDev()
        self.spi.open(0, cs_line)
        self.spi.max_speed_hz = max_speed_hz
 
        self.clear_counter()
        self.clear_status()
        self.spi.xfer2([self.WRITE_MODE0, quad_mode])
        time.sleep(0.1)
        self.spi.xfer2([self.WRITE_MODE1, self.BYTE_MODE[self.byte_mode - 1]])
 
    def close(self):
        self.spi.close()
 
    def clear_counter(self):
        self.spi.xfer2([self.CLEAR_COUNTER])
 
    def clear_status(self):
        self.spi.xfer2([self.CLEAR_STATUS])
 
    def load_counter(self, enc_val):
        data = struct.pack(">I", enc_val & 0xFFFFFFFF)[-self.byte_mode:]
        self.spi.xfer2([self.WRITE_DTR] + list(data))    # bytes -> ints (no ord() in Python 3)
        self.spi.xfer2([self.LOAD_COUNTER])
 
    def read_counter(self):
        """Signed count (two's complement), so reverse motion is negative."""
        data = self.spi.xfer2([self.READ_COUNTER] + [0] * self.byte_mode)
        value = reduce(lambda a, b: (a << 8) + b, data[1:], 0)
        bits = 8 * self.byte_mode
        if value >= 1 << (bits - 1):
            value -= 1 << bits
        return value
 
    def read_status(self):
        return self.spi.xfer2([self.READ_STATUS, 0xFF])[1]
 
 
def run_ls7366r(stop_event, output="LS7366R_speed_and_distance_data.csv",
                cs_line=1, speed_hz=1_000_000, byte_mode=4, interval=0.5,
                counts_per_rev=3575.0855, circumference_mm=219.8):
    """
    Log distance (m) and speed (m/s) to a CSV until stop_event is set.
    Speed is the change in distance over the real elapsed time of each sample.
    Run it in a thread: threading.Thread(target=run_ls7366r, args=(event,)).
    """
    encoder = LS7366R(cs_line, speed_hz, byte_mode)
    try:
        with open(output, "a", newline="") as f:
            writer = csv.writer(f)
            if f.tell() == 0:
                writer.writerow(["elapsed_s", "distance_m", "speed_m_s"])
 
            start = last_t = time.monotonic()
            last_dist = 0.0
            while not stop_event.is_set():
                now = time.monotonic()
                dist = encoder.read_counter() / counts_per_rev * circumference_mm / 1000.0
                dt = now - last_t
                speed = (dist - last_dist) / dt if dt > 0 else 0.0
                writer.writerow([round(now - start, 3), round(dist, 5), round(speed, 5)])
                f.flush()
                last_t, last_dist = now, dist
                stop_event.wait(interval)
    finally:
        encoder.close()
 
 
if __name__ == "__main__":
    import threading
 
    stop = threading.Event()
    t = threading.Thread(target=run_ls7366r, args=(stop,))
    t.start()
    try:
        while t.is_alive():
            time.sleep(0.2)
    except KeyboardInterrupt:
        stop.set()
        t.join()
        print("All done, bye bye.")
 
