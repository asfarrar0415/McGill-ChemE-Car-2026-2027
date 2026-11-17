from .board import Board
 
class I2C_Device:
    """Minimal I2C base class. Handles come from the shared Board singleton.
 
    (Your original i2c_device.py wasn't included, so this is a drop-in
    replacement exposing the same methods ADS1115 uses.)
    """
 
    def __init__(self, addr, i2c_bus):
        self._addr = addr
        self._bus = i2c_bus
        self._handle = Board().get_i2c_handle(i2c_bus, addr)
 
    def get_handle(self):
        return self._handle
 
    def get_addr(self):
        return self._addr
 
    def close(self):
        Board().close_i2c_device(self._bus, self._addr)
