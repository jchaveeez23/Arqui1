# -*- coding: utf-8 -*-
import os
import time
from datetime import datetime, timezone

import board
import adafruit_dht
import RPi.GPIO as GPIO
from RPLCD.i2c import CharLCD

from pymongo import MongoClient, errors


# ------------------ MongoDB ------------------
#gg

# Opción B: directo (descomenta si no usarás .env)
url =  "mongodb+srv://TULIOADMIN:API-NEST-MONGO@cluster0.5vi63hb.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DB_NAME     = "PRYECTO1_ACYE1"


client = MongoClient(url, serverSelectionTimeoutMS=5000)
db = client.get_database(DB_NAME)

# Colecciones solicitadas
temp_collection      = db.get_collection("temp")
cooler_collection    = db.get_collection("cooler")
alarm_rgb_collection = db.get_collection("alarm_rgb")
buzzer_collection    = db.get_collection("buzzer")

# Índices útiles (no fallar si ya existen)
try:
    temp_collection.create_index([("timestamp", -1)])
    cooler_collection.create_index([("timestamp", -1)])
    alarm_rgb_collection.create_index([("timestamp", -1)])
    buzzer_collection.create_index([("timestamp", -1)])
except Exception:
    pass

# ------------------ Configuración HW ------------------
# LCD I2C
lcd = CharLCD(
    i2c_expander='PCF8574',
    address=0x27,   # 0x27 visto en tu i2cdetect
    port=1,
    cols=16,
    rows=2,
    charmap='A02',
    auto_linebreaks=False
)

# DHT11 en GPIO4
dht = adafruit_dht.DHT11(board.D4)

# LED RGB (cátodo común)
PIN_R = 13
PIN_G = 19  # no usado
PIN_B = 26

# Buzzer activo
PIN_BUZZER = 21

# Ventilador (5V con transistor/MOSFET)
PIN_FAN = 20

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_R, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_G, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_B, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_BUZZER, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_FAN, GPIO.OUT, initial=GPIO.LOW)

# Umbrales
ALERT_ON_TEMP  = 27.0  # activar alarma
ALERT_OFF_TEMP = 26.5  # desactivar alarma (histeresis)
FAN_ON_TEMP    = 23.0  # encender ventilador
FAN_OFF_TEMP   = 22.5  # apagar ventilador (histeresis)

BLINK_PERIOD = 0.4   # s
ALERT_WINDOW = 5.0   # s

# Estados
fan_active   = False
alert_active = False  # para registrar activación/desactivación una sola vez

# ------------------ Utilidades HW ------------------
def led_off():
    GPIO.output(PIN_R, GPIO.LOW)
    GPIO.output(PIN_G, GPIO.LOW)
    GPIO.output(PIN_B, GPIO.LOW)

def led_red():
    GPIO.output(PIN_R, GPIO.HIGH)
    GPIO.output(PIN_G, GPIO.LOW)
    GPIO.output(PIN_B, GPIO.LOW)

def led_blue():
    GPIO.output(PIN_R, GPIO.LOW)
    GPIO.output(PIN_G, GPIO.LOW)
    GPIO.output(PIN_B, GPIO.HIGH)

def buzzer_on():  GPIO.output(PIN_BUZZER, GPIO.HIGH)
def buzzer_off(): GPIO.output(PIN_BUZZER, GPIO.LOW)

def fan_on():
    global fan_active
    GPIO.output(PIN_FAN, GPIO.HIGH)
    if not fan_active:
        print("FAN: ON")
    fan_active = True

def fan_off():
    global fan_active
    GPIO.output(PIN_FAN, GPIO.LOW)
    if fan_active:
        print("FAN: OFF")
    fan_active = False

def show_lcd(line1="", line2=""):
    lcd.clear()
    lcd.write_string(line1[:16])
    if line2:
        lcd.cursor_pos = (1, 0)
        lcd.write_string(line2[:16])

def blink_red_blue_with_buzzer(duration=ALERT_WINDOW, period=BLINK_PERIOD):
    end = time.time() + duration
    state = 0
    while time.time() < end:
        (led_red if state == 0 else led_blue)()
        buzzer_on()
        time.sleep(period / 2.0)
        buzzer_off()
        time.sleep(period / 2.0)
        state ^= 1
    led_off()
    buzzer_off()

# ------------------ Persistencia en Mongo ------------------
def save_temp_reading(temp_c, hum):
    """Guarda cada lectura en 'temp'."""
    try:
        doc = {
            "temperature": float(temp_c) if temp_c is not None else None,
            "humidity": float(hum) if hum is not None else None,
            "timestamp": datetime.now(timezone.utc)
        }
        temp_collection.insert_one(doc)
        # print("Mongo: temp ok")
    except errors.PyMongoError as e:
        print("Mongo ERROR temp:", e)

def log_cooler(status, temp_c=None):
    """Registra cambios de estado del ventilador en 'cooler'."""
    try:
        doc = {
            "timestamp": datetime.now(timezone.utc),
            "status": status,                  # 'Encendido' / 'Apagado'
            "temperature": float(temp_c) if temp_c is not None else None
        }
        cooler_collection.insert_one(doc)
        print(f"Mongo cooler: {status}")
    except errors.PyMongoError as e:
        print("Mongo ERROR cooler:", e)

def log_alarm_rgb(event, temp_c=None):
    """Registra activación/desactivación de alarma RGB en 'alarm_rgb'."""
    try:
        doc = {
            "timestamp": datetime.now(timezone.utc),
            "event": event,                    # 'activated' / 'deactivated'
            "temperature": float(temp_c) if temp_c is not None else None,
            "description": "Alarma RGB por temperatura"
        }
        alarm_rgb_collection.insert_one(doc)
        print(f"Mongo alarm_rgb: {event}")
    except errors.PyMongoError as e:
        print("Mongo ERROR alarm_rgb:", e)

def log_buzzer(event, temp_c=None):
    """Registra activación/desactivación del buzzer en 'buzzer'."""
    try:
        doc = {
            "timestamp": datetime.now(timezone.utc),
            "event": event,                    # 'activated' / 'deactivated'
            "temperature": float(temp_c) if temp_c is not None else None,
            "description": "Buzzer por temperatura"
        }
        buzzer_collection.insert_one(doc)
        print(f"Mongo buzzer: {event}")
    except errors.PyMongoError as e:
        print("Mongo ERROR buzzer:", e)

# ------------------ Lógica de control con histéresis ------------------
def update_fan(temp_c):
    """Controla estado del ventilador y registra cambios en Mongo."""
    if temp_c is None:
        return
    if (not fan_active) and (temp_c >= FAN_ON_TEMP):
        fan_on()
        log_cooler("Encendido", temp_c)
    elif fan_active and (temp_c <= FAN_OFF_TEMP):
        fan_off()
        log_cooler("Apagado", temp_c)

def update_alarm(temp_c):
    """Controla alarma (RGB + buzzer) con histéresis y registra en Mongo."""
    global alert_active
    if temp_c is None:
        return

    # Activar
    if (not alert_active) and (temp_c >= ALERT_ON_TEMP):
        alert_active = True
        log_alarm_rgb("activated", temp_c)
        log_buzzer("activated", temp_c)
        print(f"ALERTA: Temp >= {ALERT_ON_TEMP:.1f}C")
        show_lcd("ALERTA TEMP!", "LED+Buzzer")
        blink_red_blue_with_buzzer()

    # Desactivar
    elif alert_active and (temp_c <= ALERT_OFF_TEMP):
        alert_active = False
        log_alarm_rgb("deactivated", temp_c)
        log_buzzer("deactivated", temp_c)
        led_off()
        buzzer_off()

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

                # Guardar lectura
                save_temp_reading(t, h)

                # Control ventilador y alarma (con log)
                update_fan(t)
                update_alarm(t)

                # Si no hay alerta activa, espera normal
                if not alert_active:
                    time.sleep(5)
            else:
                print("Lectura nula, reintentando...")
                show_lcd("Lectura nula", "Reintentando...")
                led_off(); buzzer_off(); fan_off()
                time.sleep(3)

        except RuntimeError as e:
            print("Error de lectura:", e.args[0])
            show_lcd("Error lectura", "Reintentando...")
            led_off(); buzzer_off()
            # decisión: por seguridad apaga fan si lo prefieres
            # fan_off()
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
    led_off(); buzzer_off(); fan_off()
    GPIO.cleanup()
    try:
        client.close()
    except Exception:
        pass
    print("GPIO/LCD/FAN cerrados. MongoDB cerrado.")
