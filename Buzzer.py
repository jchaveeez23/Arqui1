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

# GPIO para LED RGB (BCM) - cátodo común
PIN_R = 13  # Rojo
PIN_G = 19  # Verde (no usado)
PIN_B = 26  # Azul

# Buzzer activo
PIN_BUZZER = 6  # elige un pin libre (ej. GPIO21, pin físico 40)

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_R, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_G, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_B, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_BUZZER, GPIO.OUT, initial=GPIO.LOW)

# Umbral de alerta
THRESHOLD = 27.0      # °C
BLINK_PERIOD = 0.4    # s entre cambios rojo/azul
ALERT_WINDOW = 5.0    # s de alerta antes de volver a medir

# ------------------ Utilidades LED/LCD/BUZZER ------------------
def led_off():
    GPIO.output(PIN_R, GPIO.LOW)
    GPIO.output(PIN_G, GPIO.LOW)
    GPIO.output(PIN_B, GPIO.LOW)

def led_red():
    # cátodo común: HIGH = encendido
    GPIO.output(PIN_R, GPIO.HIGH)
    GPIO.output(PIN_G, GPIO.LOW)
    GPIO.output(PIN_B, GPIO.LOW)

def led_blue():
    GPIO.output(PIN_R, GPIO.LOW)
    GPIO.output(PIN_G, GPIO.LOW)
    GPIO.output(PIN_B, GPIO.HIGH)

def buzzer_on():
    GPIO.output(PIN_BUZZER, GPIO.HIGH)  # activo con HIGH
def buzzer_off():
    GPIO.output(PIN_BUZZER, GPIO.LOW)

def blink_red_blue_with_buzzer(duration=ALERT_WINDOW, period=BLINK_PERIOD):
    """
    Parpadea rojo/azul y hace 'beep' con el buzzer durante 'duration' segundos.
    El beep dura period/2 encendido y period/2 apagado, sincronizado con el color.
    """
    end = time.time() + duration
    state = 0
    while time.time() < end:
        if state == 0:
            led_red()
        else:
            led_blue()
        # Beep ON la primera mitad del periodo
        buzzer_on()
        time.sleep(period / 2.0)
        # Beep OFF la segunda mitad del periodo
        buzzer_off()
        time.sleep(period / 2.0)
        state ^= 1
    # Apagar todo al terminar la ventana de alerta
    led_off()
    buzzer_off()

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
                    print("ALERTA: Temp >= {:.1f}C -> LED+Buzzer".format(THRESHOLD))
                    show_lcd("ALERTA TEMP!", "LED+Buzzer")
                    blink_red_blue_with_buzzer()  # ~5 s de alerta
                else:
                    # Estado normal
                    led_off()
                    buzzer_off()
                    time.sleep(5)  # espera normal entre lecturas
            else:
                print("Lectura nula, reintentando...")
                show_lcd("Lectura nula", "Reintentando...")
                led_off()
                buzzer_off()
                time.sleep(3)

        except RuntimeError as e:
            # Errores típicos del DHT11 (checksum/tiempos)
            print("Error de lectura:", e.args[0])
            show_lcd("Error lectura", "Reintentando...")
            led_off()
            buzzer_off()
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
    buzzer_off()
    GPIO.cleanup()
    print("GPIO/LCD liberados correctamente.")
