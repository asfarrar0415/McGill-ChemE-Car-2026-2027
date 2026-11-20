
import time
 
import lgpio
 
from .i2c_device import I2C_Device
 
# INA226 registers
REG_CONFIG = 0x00
REG_SHUNT = 0x01        # shunt voltage, signed, 2.5 uV per bit
REG_BUS = 0x02          # bus voltage, 1.25 mV per bit
REG_MANUFACTURER = 0xFE
MANUFACTURER_ID = 0x5449
 
SHUNT_LSB_V = 2.5e-6
BUS_LSB_V = 1.25e-3
 
# Config-register field values
AVG_BITS = {1: 0, 4: 1, 16: 2, 64: 3, 128: 4, 256: 5, 512: 6, 1024: 7}
CT_BITS_US = {140: 0, 204: 1, 332: 2, 588: 3, 1100: 4, 2116: 5, 4156: 6, 8244: 7}
 
# Column names, in the order read_row() returns its values
INA226_HEADER = ("bus_v", "current_a", "resistance_ohm", "power_w")
 
 
class INA226(I2C_Device):
    """
    Reads the external power source through an INA226.
 
    Voltage    = bus voltage (VBUS pin)
    Current    = shunt voltage / shunt resistance (signed: negative = reversed)
    Resistance = voltage / |current|  (blank when the current is below
                 min_current_a, to avoid dividing by ~0)
    Power      = voltage * |current|
 
    Current is computed from the shunt-voltage register, so the INA226's
    calibration register isn't needed. Max measurable current is
    81.92 mV / shunt_ohms.
    """
 
    def __init__(self, addr=0x40, i2c_bus=1, shunt_ohms=0.1, averages=4,
                 conv_time_us=1100, min_current_a=0.001):
        super().__init__(addr, i2c_bus)
        if shunt_ohms <= 0:
            raise ValueError("shunt_ohms must be greater than 0")
        self.shunt_ohms = shunt_ohms
        self.min_current_a = min_current_a
        self._avg = AVG_BITS[averages]
        self._ct = CT_BITS_US[conv_time_us]
 
    # ---------- register access ----------
    def _write_reg(self, reg, value):
        res = lgpio.i2c_write_device(self.get_handle(),
                                     bytes([reg, (value >> 8) & 0xFF, value & 0xFF]))
        if res < 0:
            raise IOError(f"I2C write error: {res}")
 
    def _read_reg(self, reg):
        handle = self.get_handle()
        res = lgpio.i2c_write_device(handle, bytes([reg]))
        if res < 0:
            raise IOError(f"I2C write error: {res}")
        count, buf = lgpio.i2c_read_device(handle, 2)
        if count != 2:
            raise IOError(f"I2C read error: got {count} bytes")
        return (buf[0] << 8) | buf[1]
 
    # ---------- setup ----------
    def check_id(self):
        """True if the chip reports the INA226 manufacturer ID."""
        return self._read_reg(REG_MANUFACTURER) == MANUFACTURER_ID
 
    def configure(self):
        """Continuous shunt + bus conversion with the chosen averaging."""
        config = 0x4000 | (self._avg << 9) | (self._ct << 6) | (self._ct << 3) | 0x7
        self._write_reg(REG_CONFIG, config)
 
    # ---------- measurements ----------
    def read_bus_voltage(self):
        return (self._read_reg(REG_BUS) & 0x7FFF) * BUS_LSB_V
 
    def read_shunt_voltage(self):
        raw = self._read_reg(REG_SHUNT)
        if raw & 0x8000:                    # two's complement
            raw -= 1 << 16
        return raw * SHUNT_LSB_V
 
    def read_row(self):
        """Returns (bus_v, current_a, resistance_ohm, power_w); matches INA226_HEADER.
        resistance_ohm is None when the current is too small to be meaningful."""
        bus_v = self.read_bus_voltage()
        current = self.read_shunt_voltage() / self.shunt_ohms
        mag = abs(current)
        resistance = bus_v / mag if mag >= self.min_current_a else None
        return (round(bus_v, 4),
                round(current, 5),
                None if resistance is None else round(resistance, 3),
                round(bus_v * mag, 5))
 
 
def init_ina226(addr=0x40, bus=1, shunt_ohms=0.1, **kwargs):
    """Create, check and configure an INA226, ready to read."""
    ina = INA226(addr=addr, i2c_bus=bus, shunt_ohms=shunt_ohms, **kwargs)
    if not ina.check_id():
        print(f"Warning: device at 0x{addr:02X} did not report the INA226 ID "
              "(wrong address or a different chip?)")
    ina.configure()
    time.sleep(0.05)                        # let the first averaged conversion finish
    return ina
 
 
if __name__ == "__main__":
    dev = init_ina226()
    try:
        while True:
            v, i, r, p = dev.read_row()
            print(f"{v:8.4f} V  {i:9.5f} A  R={r} ohm  {p:9.5f} W")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        dev.close()
 
