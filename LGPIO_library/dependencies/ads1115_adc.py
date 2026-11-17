import time
from enum import Enum 
import lgpio
from .i2c_device import I2C_Device
 
# CONFIG REGISTER (16 bit): OS[15] MUX[14:12] PGA[11:9] MODE[8] DR[7:5]
#                           COMP_MODE[4] COMP_POL[3] COMP_LAT[2] COMP_QUE[1:0]
# See the ADS1115 datasheet for the full bit descriptions.
 
 
class REGISTERS(Enum):
    CONVERSION_REG = 0x00
    CONFIG_REG = 0x01
    REG_LO_THRESH = 0x02
    REG_HI_THRESH = 0x03
 
 
class SHIFTS(Enum):
    OS_SHIFT = 15
    MUX_SHIFT = 12
    PGA_SHIFT = 9
    MODE_SHIFT = 8
    DR_SHIFT = 5
    COMP_MODE_SHIFT = 4
    COMP_POL_SHIFT = 3
    COMP_LAT_SHIFT = 2
    COMP_QUE_SHIFT = 0
 
 
class FIELD_OPTIONS(Enum):
    # OS (bit 15). Writing 1 starts a single conversion; has no effect in continuous mode.
    OS_SINGLE = 0x1 << SHIFTS.OS_SHIFT.value
    OS_BUSY = 0x0 << SHIFTS.OS_SHIFT.value
    OS_READY = 0x1 << SHIFTS.OS_SHIFT.value
 
    # MUX (bits 14-12)
    MUX_AIN0_AIN1 = 0x0 << SHIFTS.MUX_SHIFT.value
    MUX_AIN0_AIN3 = 0x1 << SHIFTS.MUX_SHIFT.value
    MUX_AIN1_AIN3 = 0x2 << SHIFTS.MUX_SHIFT.value
    MUX_AIN2_AIN3 = 0x3 << SHIFTS.MUX_SHIFT.value
    MUX_AIN0_GND = 0x4 << SHIFTS.MUX_SHIFT.value
    MUX_AIN1_GND = 0x5 << SHIFTS.MUX_SHIFT.value
    MUX_AIN2_GND = 0x6 << SHIFTS.MUX_SHIFT.value
    MUX_AIN3_GND = 0x7 << SHIFTS.MUX_SHIFT.value
 
    # PGA (bits 11-9): full-scale range
    PGA_6_144V = 0x0 << SHIFTS.PGA_SHIFT.value
    PGA_4_096V = 0x1 << SHIFTS.PGA_SHIFT.value
    PGA_2_048V = 0x2 << SHIFTS.PGA_SHIFT.value
    PGA_1_024V = 0x3 << SHIFTS.PGA_SHIFT.value
    PGA_0_512V = 0x4 << SHIFTS.PGA_SHIFT.value
    PGA_0_256V = 0x5 << SHIFTS.PGA_SHIFT.value
 
    # MODE (bit 8)
    MODE_CONTINUOUS = 0x0 << SHIFTS.MODE_SHIFT.value
    MODE_SINGLE = 0x1 << SHIFTS.MODE_SHIFT.value
 
    # Data rate (bits 7-5)
    DR_8SPS = 0x0 << SHIFTS.DR_SHIFT.value
    DR_16SPS = 0x1 << SHIFTS.DR_SHIFT.value
    DR_32SPS = 0x2 << SHIFTS.DR_SHIFT.value
    DR_64SPS = 0x3 << SHIFTS.DR_SHIFT.value
    DR_128SPS = 0x4 << SHIFTS.DR_SHIFT.value
    DR_250SPS = 0x5 << SHIFTS.DR_SHIFT.value
    DR_475SPS = 0x6 << SHIFTS.DR_SHIFT.value
    DR_860SPS = 0x7 << SHIFTS.DR_SHIFT.value
 
    # Comparator
    COMP_MODE_TRAD = 0x0 << SHIFTS.COMP_MODE_SHIFT.value
    COMP_MODE_WINDOW = 0x1 << SHIFTS.COMP_MODE_SHIFT.value
    COMP_POL_ACTIVE_LOW = 0x0 << SHIFTS.COMP_POL_SHIFT.value
    COMP_POL_ACTIVE_HIGH = 0x1 << SHIFTS.COMP_POL_SHIFT.value
    COMP_LAT_NONLATCH = 0x0 << SHIFTS.COMP_LAT_SHIFT.value
    COMP_LAT_LATCH = 0x1 << SHIFTS.COMP_LAT_SHIFT.value
    COMP_QUE_1CONV = 0x0 << SHIFTS.COMP_QUE_SHIFT.value
    COMP_QUE_2CONV = 0x1 << SHIFTS.COMP_QUE_SHIFT.value
    COMP_QUE_4CONV = 0x2 << SHIFTS.COMP_QUE_SHIFT.value
    COMP_QUE_DISABLE = 0x3 << SHIFTS.COMP_QUE_SHIFT.value
 
 
FSR_MAP = {
    FIELD_OPTIONS.PGA_6_144V: 6.144,
    FIELD_OPTIONS.PGA_4_096V: 4.096,
    FIELD_OPTIONS.PGA_2_048V: 2.048,
    FIELD_OPTIONS.PGA_1_024V: 1.024,
    FIELD_OPTIONS.PGA_0_512V: 0.512,
    FIELD_OPTIONS.PGA_0_256V: 0.256,
}
 
DEFAULT_OFFSET_MV = 1483.0   # one calibration value (the old code had 1483 and 1486)
 
 
class ADS1115(I2C_Device):
    """ADS1115 in continuous mode. Defaults: AIN1 vs GND, +/-4.096 V, 128 SPS."""
 
    def __init__(self, addr=0x48, i2c_bus=1,
                 os_bit=FIELD_OPTIONS.OS_BUSY,
                 mux_bit=FIELD_OPTIONS.MUX_AIN1_GND,
                 pga_bit=FIELD_OPTIONS.PGA_4_096V,
                 mode_bit=FIELD_OPTIONS.MODE_CONTINUOUS,
                 sps_bit=FIELD_OPTIONS.DR_128SPS,
                 comp_bit=FIELD_OPTIONS.COMP_QUE_DISABLE,
                 offset_mv=DEFAULT_OFFSET_MV):
        super().__init__(addr, i2c_bus)
        self._FSR = FSR_MAP[pga_bit]
        self._pga_bit = pga_bit
        self._offset_mv = offset_mv
        self._config = (os_bit.value | mux_bit.value | pga_bit.value |
                        mode_bit.value | sps_bit.value | comp_bit.value)
 
    # ---------- configuration ----------
    def set_pga_bit(self, pga_bit):
        """Updates the voltage scale. Also rebuilds the config word so the
        scale used to convert readings always matches what the chip uses."""
        self._config = (self._config & ~(0x7 << SHIFTS.PGA_SHIFT.value)) | pga_bit.value
        self._pga_bit = pga_bit
        self._FSR = FSR_MAP[pga_bit]
 
    def set_config(self, config):
        self._config = config
 
    def get_config(self):
        return self._config
 
    def get_pga_bit(self):
        return self._pga_bit
 
    def write_configuration(self, config=None):
        if config is None:
            config = self._config
        buf = bytes([REGISTERS.CONFIG_REG.value, (config >> 8) & 0xFF, config & 0xFF])
        res = lgpio.i2c_write_device(self.get_handle(), buf)
        code = res[0] if isinstance(res, (list, tuple)) else res
        if code < 0:
            raise IOError(f"I2C write error: {code}")
        return res
 
    # ---------- reading ----------
    def read_word(self):
        handle = self.get_handle()
        # Point at the conversion register, then read 2 bytes
        res = lgpio.i2c_write_device(handle, bytes([REGISTERS.CONVERSION_REG.value]))
        if res < 0:
            raise IOError(f"I2C write error: {res}")
        count, buf = lgpio.i2c_read_device(handle, 2)
        if count != 2:
            raise IOError(f"I2C read error: got {count} bytes")
        return (buf[0] << 8) | buf[1]
 
    def read_word_and_clean_data(self):
        """Returns volts."""
        return self._clean_data(self.read_word())
 
    def get_adjusted_mvs(self):
        """Returns millivolts with the calibration offset removed."""
        return self.read_word_and_clean_data() * 1000.0 - self._offset_mv
 
    def _clean_data(self, read_data):
        if read_data & 0x8000:          # two's complement
            read_data -= 1 << 16
        return read_data * (self._FSR / 32768.0)
 
 
def init_ads1115(addr=0x48, bus=1, offset_mv=DEFAULT_OFFSET_MV):
    """Create, configure and return a ready-to-read ADS1115."""
    ads = ADS1115(addr=addr, i2c_bus=bus, offset_mv=offset_mv)
    ads.write_configuration()
    time.sleep(0.05)                    # let the first conversion finish
    return ads
 
 
if __name__ == "__main__":
    adc = init_ads1115()
    start = time.time()
    try:
        while True:
            try:
                print(f"{time.time() - start:8.3f} s  {adc.get_adjusted_mvs():10.2f} mV")
            except IOError as e:
                print(f"read error: {e}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("closing")
    finally:
        adc.close()
 
