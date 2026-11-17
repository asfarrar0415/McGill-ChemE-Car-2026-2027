import threading
import lgpio
 
 
class Board:
    """Thread-safe singleton that owns every lgpio handle (GPIO chip, I2C, SPI)."""
 
    _instance = None
    _create_lock = threading.Lock()
 
    def __new__(cls):
        with cls._create_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._lock = threading.RLock()
                inst._gpio_handle = {}   # chip -> handle
                inst._i2c_handle = {}    # (bus, addr) -> handle
                inst._spi_handle = {}    # (bus, cs) -> handle
                cls._instance = inst
        return cls._instance
 
    # ---------- open ----------
    def get_gpio_handle(self, chip):
        with self._lock:
            if chip not in self._gpio_handle:
                self._gpio_handle[chip] = lgpio.gpiochip_open(chip)
            return self._gpio_handle[chip]
 
    def get_i2c_handle(self, bus, addr):
        """bus = I2C bus number (1 on a Pi), NOT the gpiochip number."""
        with self._lock:
            key = (bus, addr)
            if key not in self._i2c_handle:
                self._i2c_handle[key] = lgpio.i2c_open(bus, addr)
            return self._i2c_handle[key]
 
    def get_spi_handle(self, bus, cs, freq):
        with self._lock:
            key = (bus, cs)
            if key not in self._spi_handle:
                self._spi_handle[key] = lgpio.spi_open(bus, cs, freq)
            return self._spi_handle[key]
 
    # ---------- close ----------
    def close_i2c_device(self, bus, addr):
        with self._lock:
            handle = self._i2c_handle.pop((bus, addr), None)
            if handle is not None:
                lgpio.i2c_close(handle)
 
    def close_gpio(self):
        with self._lock:
            for handle in self._gpio_handle.values():
                lgpio.gpiochip_close(handle)
            self._gpio_handle = {}
 
    def close_i2c(self):
        with self._lock:
            for handle in self._i2c_handle.values():
                lgpio.i2c_close(handle)
            self._i2c_handle = {}
 
    def close_spi(self):
        with self._lock:
            for handle in self._spi_handle.values():
                lgpio.spi_close(handle)
            self._spi_handle = {}
 
    def close(self):
        """Close everything. Safe to call more than once, and to reopen afterwards."""
        self.close_i2c()
        self.close_spi()
        self.close_gpio()
 
