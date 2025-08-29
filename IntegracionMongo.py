# -*- coding: utf-8 -*-
import time
import board
import adafruit_dht
import RPi.GPIO as GPIO
from RPLCD.i2c import CharLCD

# ==== MONGODB (con CA bundle) ====
from datetime import datetime, timezone
from pymongo import MongoClient
import certifi

def utcnow():
    return datetime.now(timezone.utc)

url = "mongodb+srv://TULIOADMIN:API-NEST-MONGO@cluster0.5vi63hb.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

try:
    client = MongoClient(
        url,
        tls=True,
        tlsCAFile=certifi.where(),   # <- certificados raíz
        serverSelectionTimeoutMS=8000
    )
    client.admin.command("ping")
    print("MongoDB: conectado OK")
    db = client.get_database("PRYECTO1_ACYE1")

    temp_collection       = db.get_collection("TEMPERATURE_SENSOR")
    cooler_collection     = db.get_collection("COOLER")
    alarm_rgb_collection  = db.get_collection("ALARM_LED_RGB")
    buzzer_collection     = db.get_collection("BUZZER")
    MONGO_READY = True
except Exception as e:
    print("MongoDB: no disponible ->", e)
    client = db = None
    temp_collection = cooler_collection = alarm_rgb_collection = buzzer_collection = None
    MONGO_READY = False

def safe_insert(coll, doc):
    if not coll:
        return
    try:
        coll.insert_one(doc)
    except Exception as e:
        print("Mongo insert error:", e)

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
PIN_BUZZER = 6  # GPIO6

# Ventilador (control con transistor/MOSFET)
PIN_FAN = 5  # GPIO5

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_R, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_G, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_B, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_BUZZER, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_FAN, GPIO.OUT, initial=GPIO.LOW)

# Umbrales
THRESHOLD_ALERT = 27.0   # °C -> LED/Buzzer
FAN_ON_TEMP = 23.0       # °C -> Ventilador ON
FAN_OFF_TEMP = 22.5      # °C -> Ventilador OFF (histéresis)

BLINK_PERIOD = 0.4       # s entre cambios rojo/azul
ALERT_WINDOW = 5.0       # s de alerta antes de volver a medir

# Estados (para histéresis y logs sin spam)
fan_active = False
alert_active = False  # para registrar ON/OFF de alarma solo al cambiar

# ------------------ Utilidades LED/LCD/BUZZER/FAN ------------------
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

def buzzer_on():
    GPIO.output(PIN_BUZZER, GPIO.HIGH)

def buzzer_off():
    GPIO.output(PIN_BUZZER, GPIO.LOW)

def fan_on(temp=None):
    global fan_active
    GPIO.output(PIN_FAN, GPIO.HIGH)   # HIGH activa el transistor/MOSFET
    if not fan_active:
        print("FAN: ON")
        safe_insert(cooler_collection, {
            "ts": utcnow(),
            "state": "ON",
            "reason": f"TEMP>= {FAN_ON_TEMP:.1f}",
            "temp_c": float(temp) if temp is not None else None
        })
    fan_active = True

def fan_off(temp=None):
    global fan_active
    GPIO.output(PIN_FAN, GPIO.LOW)
    if fan_active:
        print("FAN: OFF")
        safe_insert(cooler_collection, {
            "ts": utcnow(),
            "state": "OFF",
            "reason": f"TEMP<= {FAN_OFF_TEMP:.1f}",
            "temp_c": float(temp) if temp is not None else None
        })
    fan_active = False

def update_fan(temp_c):
    """Control con histéresis para evitar prende/apaga rápido cerca del umbral."""
    if temp_c is None:
        return
    if (not fan_active) and (temp_c >= FAN_ON_TEMP):
        fan_on(temp_c)
    elif fan_active and (temp_c <= FAN_OFF_TEMP):
        fan_off(temp_c)

def blink_red_blue_with_buzzer(duration=ALERT_WINDOW, period=BLINK_PERIOD):
    """
    Parpadea rojo/azul y hace 'beep' con el buzzer durante 'duration' segundos.
    """
    end = time.time() + duration
    state = 0
    while time.time() < end:
        if state == 0:
            led_red()
        else:
            led_blue()
        buzzer_on()
        time.sleep(period / 2.0)
        buzzer_off()
        time.sleep(period / 2.0)
        state ^= 1
    led_off()
    buzzer_off()

def show_lcd(line1="", line2=""):
    lcd.clear()
    lcd.write_string(line1[:16])
    if line2:
        lcd.cursor_pos = (1, 0)
        lcd.write_string(line2[:16])

def set_alert_state(active, temp):
    """Loggea en Mongo el cambio de estado de la alarma (RGB y buzzer)."""
    global alert_active
    if active == alert_active:
        return
    alert_active = active
    state = "ON" if active else "OFF"
    trigger = f"TEMP>= {THRESHOLD_ALERT:.1f}C" if active else f"TEMP< {THRESHOLD_ALERT:.1f}C"
    doc = {"ts": utcnow(), "state": state, "trigger": trigger, "temp_c": float(temp) if temp is not None else None}
    safe_insert(alarm_rgb_collection, dict(doc, device="RGB"))
    safe_insert(buzzer_collection,   dict(doc, device="BUZZER"))

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

                # --- Mongo: guardar lectura ---
                safe_insert(temp_collection, {
                    "ts": utcnow(),
                    "temp_c": float(t),
                    "humidity": float(h)
                })

                # --- Control de ventilador ---
                update_fan(t)

                # --- Alerta de alta temperatura (LED + buzzer) ---
                if t >= THRESHOLD_ALERT:
                    # Cambio a ACTIVO si aplica (solo una vez por transición)
                    set_alert_state(True, t)
                    print("ALERTA!! >= {:.1f}C -> LED+Buzzer".format(THRESHOLD_ALERT))
                    show_lcd("ALERTA!!", "TEMPERATURA ALTA")
                    blink_red_blue_with_buzzer()  # ~5 s de alerta
                else:
                    # Si estaba activa, registramos OFF una sola vez
                    set_alert_state(False, t)
                    led_off()
                    buzzer_off()
                    time.sleep(5)  # espera normal entre lecturas

            else:
                print("Lectura nula, reintentando...")
                show_lcd("Lectura nula", "Reintentando...")
                led_off()
                buzzer_off()
                fan_off(t if t is not None else None)
                time.sleep(3)

        except RuntimeError as e:
            print("Error de lectura:", e.args[0])
            show_lcd("Error lectura", "Reintentando...")
            led_off()
            buzzer_off()
            fan_off(t if 't' in locals() else None)
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
    fan_off(None)
    GPIO.cleanup()
    print("GPIO/LCD/FAN liberados correctamente.")
