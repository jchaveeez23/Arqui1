# -*- coding: utf-8 -*-
import os
import time
from datetime import datetime, timezone

import board
import adafruit_dht
import RPi.GPIO as GPIO
from RPLCD.i2c import CharLCD

# --- MongoDB ---
import certifi
from pymongo import MongoClient, errors as pymongo_errors

# ================== CONFIGURACIÓN ==================
# LCD I2C
lcd = CharLCD(
    i2c_expander='PCF8574',
    address=0x27,   # según i2cdetect
    port=1,
    cols=16,
    rows=2,
    charmap='A02',
    auto_linebreaks=False
)

# DHT11 en GPIO4
dht = adafruit_dht.DHT11(board.D4)

# GPIO para LED RGB (cátodo común), buzzer y ventilador
PIN_R = 13
PIN_G = 19  # no usado
PIN_B = 26
PIN_BUZZER = 21
PIN_FAN = 20

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_R, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_G, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_B, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_BUZZER, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_FAN, GPIO.OUT, initial=GPIO.LOW)

# Umbrales
THRESHOLD_ALERT = 25.0      # °C -> LED + buzzer
FAN_ON_TEMP = 23.0          # °C -> Ventilador ON
FAN_OFF_TEMP = 22.5         # °C -> Ventilador OFF (histéresis)

BLINK_PERIOD = 0.4          # s
ALERT_WINDOW = 5.0          # s

# Estados
fan_active = False
alert_active = False

# ================ CONEXIÓN MONGODB =================
# Usa variable de entorno si existe; si no, usa tu URL directa.
MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb+srv://TULIOADMIN:API-NEST-MONGO@cluster0.5vi63hb.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
)

def connect_mongo():
    try:
        client = MongoClient(MONGODB_URI, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=8000)
        client.admin.command("ping")
        print("[MongoDB] Conectado.")
        db = client.get_database("sensor_data")

        col_temp   = db.get_collection("TEMPERATURE_SENSOR")
        col_cooler = db.get_collection("COOLER")
        col_alarm  = db.get_collection("ALARM_LED_RGB")
        col_buzzer = db.get_collection("BUZZER")

        # Índices por timestamp (se crean una sola vez)
        for c in (col_temp, col_cooler, col_alarm, col_buzzer):
            try:
                c.create_index([("timestamp", 1)], background=True)
            except Exception:
                pass

        return client, col_temp, col_cooler, col_alarm, col_buzzer
    except pymongo_errors.PyMongoError as e:
        print("[MongoDB] Error de conexión:", e)
        return None, None, None, None, None

mongo_client, col_temp, col_cooler, col_alarm, col_buzzer = connect_mongo()

# ================== LOGGERS ==================
def now_utc():
    return datetime.now(timezone.utc)

def log_temperature(temp_c, hum):
    if not col_temp: return
    try:
        col_temp.insert_one({
            "temperature": float(temp_c),
            "humidity": float(hum),
            "timestamp": now_utc()
        })
    except pymongo_errors.PyMongoError as e:
        print("[MongoDB] Error insert TEMPERATURE_SENSOR:", e)

def log_cooler(state, temp_c=None):
    # state: "ON" | "OFF"
    if not col_cooler: return
    try:
        col_cooler.insert_one({
            "state": state,
            "temperature": float(temp_c) if temp_c is not None else None,
            "timestamp": now_utc()
        })
    except pymongo_errors.PyMongoError as e:
        print("[MongoDB] Error insert COOLER:", e)

def log_alarm_rgb(state, temp_c=None):
    # state: "ON" | "OFF"
    if not col_alarm: return
    try:
        col_alarm.insert_one({
            "state": state,
            "mode": "blink",
            "colors": ["RED", "BLUE"],
            "reason": f"TEMP {'>=' if state=='ON' else '<'} {THRESHOLD_ALERT}",
            "temperature": float(temp_c) if temp_c is not None else None,
            "timestamp": now_utc()
        })
    except pymongo_errors.PyMongoError as e:
        print("[MongoDB] Error insert ALARM_LED_RGB:", e)

def log_buzzer(state, temp_c=None):
    # state: "ON" | "OFF"
    if not col_buzzer: return
    try:
        col_buzzer.insert_one({
            "state": state,
            "reason": f"TEMP {'>=' if state=='ON' else '<'} {THRESHOLD_ALERT}",
            "temperature": float(temp_c) if temp_c is not None else None,
            "timestamp": now_utc()
        })
    except pymongo_errors.PyMongoError as e:
        print("[MongoDB] Error insert BUZZER:", e)

# ================== UTILIDADES HW ==================
def show_lcd(line1="", line2=""):
    lcd.clear()
    lcd.write_string(line1[:16])
    if line2:
        lcd.cursor_pos = (1, 0)
        lcd.write_string(line2[:16])

def led_off():
    GPIO.output(PIN_R, GPIO.LOW); GPIO.output(PIN_G, GPIO.LOW); GPIO.output(PIN_B, GPIO.LOW)

def led_red():
    GPIO.output(PIN_R, GPIO.HIGH); GPIO.output(PIN_G, GPIO.LOW); GPIO.output(PIN_B, GPIO.LOW)

def led_blue():
    GPIO.output(PIN_R, GPIO.LOW); GPIO.output(PIN_G, GPIO.LOW); GPIO.output(PIN_B, GPIO.HIGH)

def buzzer_on():  GPIO.output(PIN_BUZZER, GPIO.HIGH)
def buzzer_off(): GPIO.output(PIN_BUZZER, GPIO.LOW)

def fan_on():
    global fan_active
    GPIO.output(PIN_FAN, GPIO.HIGH)
    if not fan_active:
        print("FAN: ON")
        log_cooler("ON", last_temp)
    fan_active = True

def fan_off():
    global fan_active
    GPIO.output(PIN_FAN, GPIO.LOW)
    if fan_active:
        print("FAN: OFF")
        log_cooler("OFF", last_temp)
    fan_active = False

def update_fan(temp_c):
    if temp_c is None: return
    if (not fan_active) and (temp_c >= FAN_ON_TEMP):
        fan_on()
    elif fan_active and (temp_c <= FAN_OFF_TEMP):
        fan_off()

def blink_red_blue_with_buzzer(duration=ALERT_WINDOW, period=BLINK_PERIOD):
    end = time.time() + duration
    state = 0
    while time.time() < end:
        led_red() if state == 0 else led_blue()
        buzzer_on()
        time.sleep(period / 2.0)
        buzzer_off()
        time.sleep(period / 2.0)
        state ^= 1
    led_off(); buzzer_off()

# ================== MAIN LOOP ==================
last_temp = None

try:
    show_lcd("Leyendo DHT11", "Espere...")
    time.sleep(1)

    while True:
        try:
            t = dht.temperature   # °C
            h = dht.humidity      # %
            if t is not None and h is not None:
                last_temp = t

                print(f"Temperatura: {t:.1f} C")
                print(f"Humedad: {h:.1f} %")
                show_lcd(f"Temp: {t:.1f}C", f"Hum:  {h:.1f}%")

                # ---- Mongo: lectura ----
                log_temperature(t, h)

                # ---- Ventilador ----
                update_fan(t)

                # ---- Alarma (LED + buzzer) con detección de transición ----
                if t >= THRESHOLD_ALERT:
                    if not alert_active:
                        alert_active = True
                        log_alarm_rgb("ON", t)
                        log_buzzer("ON", t)
                    show_lcd("ALERTA TEMP!", "LED+Buzzer")
                    blink_red_blue_with_buzzer()
                else:
                    if alert_active:
                        alert_active = False
                        log_alarm_rgb("OFF", t)
                        log_buzzer("OFF", t)
                    led_off()
                    buzzer_off()
                    time.sleep(5)

            else:
                print("Lectura nula, reintentando...")
                show_lcd("Lectura nula", "Reintentando...")
                led_off(); buzzer_off()
                # Apaga ventilador por seguridad (opcional)
                fan_off()
                time.sleep(3)

        except RuntimeError as e:
            print("Error de lectura:", e.args[0] if e.args else e)
            show_lcd("Error lectura", "Reintentando...")
            led_off(); buzzer_off()
            # opcional: fan_off()
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
    print("GPIO/LCD/FAN liberados correctamente.")
