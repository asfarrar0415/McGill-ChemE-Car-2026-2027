print("bottom:", lgpio.gpio_read(h, SWITCH_PIN),
      "start:", lgpio.gpio_read(h, START_PIN),
      "reset:", lgpio.gpio_read(h, RESET_PIN))
