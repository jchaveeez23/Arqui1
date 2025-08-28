# -*- coding: utf-8 -*-
import time
import board
import adafruit_dht
import RPi.GPIO as GPIO
from RPLCD.i2c import CharLCD

# ------------------ Configuración ------------------
# LCD I2C
lcd = CharLCD(
    i2c_expander='PCF8574',
    address=0x27,   
    port=1,
    cols=16,
    rows=2,
    charmap='A02',
    auto_linebreaks=False
)

# DHT11 en GPIO4
dht = adafruit_dht.DHT11(board.D4)

# GPIO para LED RGB (BCM)
PIN_R = 13  # Rojo
PIN_G = 19  # Verde (no lo usamos, pero lo dejamos apagado)
PIN_B = 26  # Azul

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_R, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_G, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_B, GPIO.OUT, initial=GPIO.LOW)

# Umbral de alerta
THRESHOLD = 27.0      # °C
BLINK_PERIOD = 0.4    # s entre cambios rojo/azul
ALERT_WINDOW = 5.0    # s de parpadeo antes de volver a medir

# ------------------ Utilidades LED/LCD ------------------
def led_off():
    GPIO.output(PIN_R, GPIO.LOW)
    GPIO.output(PIN_G, GPIO.LOW)
    GPIO.output(PIN_B, GPIO.LOW)

def led_red():
    GPIO.output(PIN_R, GPIO.HIGH)  # cátodo común: HIGH = encendido
    GPIO.output(PIN_G, GPIO.LOW)
    GPIO.output(PIN_B, GPIO.LOW)

def led_blue():
    GPIO.output(PIN_R, GPIO.LOW)
    GPIO.output(PIN_G, GPIO.LOW)
    GPIO.output(PIN_B, GPIO.HIGH)

def blink_red_blue(duration=ALERT_WINDOW, period=BLINK_PERIOD):
    """Parpadea rojo/azul durante 'duration' segundos."""
    end = time.time() + duration
    state = 0
    while time.time() < end:
        if state == 0:
            led_red()
        else:
            led_blue()
        state ^= 1
        time.sleep(period)
    led_off()

def show_lcd(line1="", line2=""):
    lcd.clear()
    lcd.write_string(line1[:16])
    if line2:
        lcd.cursor_pos = (1, 0)
        lcd.write_string(line2[:16])

# ------------------ Programa principal ------------------
try:
    show_lcd("Leyendo DHT11", "Espere...")
    time.sleep(1)

    while True:
        try:
            t = dht.temperature   # °C
            h = dht.humidity      # %
            if t is not None and h is not None:
                print("Temperatura: {:.1f} C".format(t))
                print("Humedad: {:.1f} %".format(h))
                show_lcd("Temp: {:.1f}C".format(t),
                         "Hum:  {:.1f}%".format(h))

                if t >= THRESHOLD:
                    # Alerta: parpadeo rojo/azul hasta la próxima medición
                    print("ALERTA: Temp >= {:.1f}C -> LED parpadea".format(THRESHOLD))
                    show_lcd("ALERTA TEMP!", "Parpadeo LED")
                    blink_red_blue()   # ~5 s parpadeando
                else:
                    led_off()
                    time.sleep(5)      # espera normal entre lecturas
            else:
                print("Lectura nula, reintentando...")
                show_lcd("Lectura nula", "Reintentando...")
                led_off()
                time.sleep(3)

        except RuntimeError as e:
            # Errores típicos del DHT11 (checksum/tiempos)
            print("Error de lectura:", e.args[0])
            show_lcd("Error lectura", "Reintentando...")
            led_off()
            time.sleep(2)

except KeyboardInterrupt:
    print("\nPrograma detenido por el usuario.")
finally:
    try:
        dht.exit()
    except Exception:
        pass
    try:
        show_lcd("Hasta luego :)")
        time.sleep(0.5)
        lcd.clear()
        lcd.close(clear=True)
    except Exception:
        pass
    led_off()
    GPIO.cleanup()
    print("GPIO/LCD liberados correctamente.")
