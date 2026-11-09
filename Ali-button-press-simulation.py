import lgpio
import time

#Button press simulation: have the signal go from 1 -> 0 -> 1 just like a button being pressed. 

#Asking the chip for access to pins with a handle (like a access ticket)
#chip 0 or 4, control the pins
handle = lgpio.gpiochip_open(0)

#choosing pin: 
pinOutput = 17 
#The other end goes to ground

#use try to be able to release the pin if things crash.
try: 
    #setting the pin as output: 
    lgpio.gpio_claim_output(handle, pinOutput, 1)#(handle, pin, state)
    ###---------signal on for 100ms
    time.sleep(0.5)#s 
    
    
    lgpio.gpio_write(handle, pinOutput, 0)
    print("Signal is off; circuit conncected to ground")
    ###---------signal off for 100ms
    time.sleep(0.5)#s  

    #button_released: 
    lgpio.gpio_write(handle, pinOutput, 1)
finally:
    #Releasing teh pin to not have it locked: 
    lgpio.gpio_free(handle, pinOutput) # free pin
 #    lgpio.gpiochip_close(handle) free chip 

#if we are simulating receiving a signal
pinB = 27
#lgpio.SET_PULL_UP reads the inicial high voltage as the circuit is open
#when the button is pressed and connects to ground, and the signal goes to 0

try:
    #lgpio.SET_PULL_UP reads the current signal as 1
    lgpio.gpio_claim_input(handle, pinB, lgpio.SET_PULL_UP)

    #looping a finite amount of time here so the programm ends:
    for x in range (100):
        time.sleep(0.1)# 10 ms * 100 = runs for 10s
        state = lgpio.gpio_read(handle, pinB )
        #if the voltage drops lower than the standard set by lgpio.SET_PULL_UP state = 0
        if state == 0:
            print("Button is being pressed")
finally:
    lgpio.gpio_free(handle, pinB)
    lgpio.gpiochip_close(handle)