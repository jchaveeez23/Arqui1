# -*- coding: utf-8 -*-
import time
from datetime import datetime, timezone

import board
import adafruit_dht
import RPi.GPIO as GPIO
from RPLCD.i2c import CharLCD
from pymongo import MongoClient

# ===================== Configuración de Hardware =====================
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
# Si tu Pi es reciente y tienes errores de lectura, usa: use_pulseio=False
dht = adafruit_dht.DHT11(board.D4)

# GPIO para LED RGB (BCM) - cátodo común
PIN_R = 13   # Rojo
PIN_G = 19   # Verde (no usado)
PIN_B = 26   # Azul

# Buzzer activo
PIN_BUZZER = 6   # GPIO6

# Ventilador (control con transistor/MOSFET)
PIN_FAN = 5      # GPIO5

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_R, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_G, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_B, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_BUZZER, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIN_FAN, GPIO.OUT, initial=GPIO.LOW)

# Umbrales
THRESHOLD_ALERT = 27.0   # °C -> LED/Buzzer
FAN_ON_TEMP     = 23.0   # °C -> Ventilador ON
FAN_OFF_TEMP    = 22.5   # °C -> Ventilador OFF (histéresis)

BLINK_PERIOD  = 0.4      # s entre cambios rojo/azul
ALERT_WINDOW  = 5.0      # s de alerta
ALARM_COOLDOWN_S = 30    # evita registrar la alarma demasiadas veces

# Estado
fan_active = False
last_alarm_ts = 0.0

# ===================== Utilidades de I/O =====================
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

def update_fan(temp_c):
    """Control con histéresis + registro en MongoDB cuando cambia el estado."""
    if temp_c is None:
        return
    if (not fan_active) and (temp_c >= FAN_ON_TEMP):
        fan_on()
        log_cooler("Encendido", temp_c)
    elif fan_active and (temp_c <= FAN_OFF_TEMP):
        fan_off()
        log_cooler("Apagado", temp_c)

def blink_red_blue_with_buzzer(duration=ALERT_WINDOW, period=BLINK_PERIOD):
    """Parpadea rojo/azul y hace 'beep' con el buzzer durante 'duration' segundos."""
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

def show_lcd(line1="", line2=""):
    lcd.clear()
    lcd.write_string(line1[:16])
    if line2:
        lcd.cursor_pos = (1, 0)
        lcd.write_string(line2[:16])

def now_ts():
    return datetime.now(timezone.utc)

# ===================== MongoDB =====================
# URL de conexión a MongoDB Atlas (usa tu propia credencial/URI)
url = "mongodb+srv://TULIOADMIN:API-NEST-MONGO@cluster0.5vi63hb.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

client = MongoClient(url, tls=True, tlsAllowInvalidCertificates=False)
db = client.get_database("PRYECTO1_ACYE1")

# Colecciones
temp_collection      = db.get_collection("TEMPERATURE_SENSOR")  # lecturas sensor
cooler_collection    = db.get_collection("COOLER")               # eventos ventilador
alarm_rgb_collection = db.get_collection("ALARM_LED_RGB")        # eventos LED RGB
buzzer_collection    = db.get_collection("BUZZER")               # eventos buzzer

# ---- Funciones de guardado ----
def save_sensor_reading(temperature: float, humidity: float):
    try:
        doc = {
            "temperature": temperature,
            "humidity": humidity,
            "timestamp": now_ts()
        }
        temp_collection.insert_one(doc)
        print(" Lectura guardada en TEMPERATURE_SENSOR.")
    except Exception as e:
        print(f" Error guardando lectura: {e}")

def log_cooler(status: str, temp: float):
    try:
        doc = {
            "status": status,                  # 'Encendido' | 'Apagado'
            "temperature": temp,
            "timestamp": now_ts()
        }
        cooler_collection.insert_one(doc)
        print(f" Cooler {status} registrado.")
    except Exception as e:
        print(f" Error guardando COOLER: {e}")

def activate_alarm(temperature: float):
    """Registra activación de alarma (LED RGB + Buzzer) en ambas colecciones."""
    try:
        doc = {
            "status": "activated",
            "temperature": temperature,
            "timestamp": now_ts(),
            "event": "Alarma activada por alta temperatura"
        }
        alarm_rgb_collection.insert_one(doc)
        buzzer_collection.insert_one(doc)
        print(" Alarma activada registrada en ALARM_LED_RGB y BUZZER.")
    except Exception as e:
        print(f"Error guardando alarma: {e}")

# ===================== Programa principal =====================
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
                show_lcd("Temp: {:.1f}C".format(t), "Hum:  {:.1f}%".format(h))

                # Guarda lectura en Mongo
                save_sensor_reading(t, h)

                # Control del ventilador (con log en cambios)
                update_fan(t)

                # Alarma por alta temperatura (con cooldown de registros)
                if t >= THRESHOLD_ALERT:
                    now_s = time.time()
                    if now_s - last_alarm_ts >= ALARM_COOLDOWN_S:
                        activate_alarm(t)
                        last_alarm_ts = now_s
                    print("ALERTA!! >= {:.1f}C -> LED+Buzzer".format(THRESHOLD_ALERT))
                    show_lcd("ALERTA!!", "TEMPERATURA ALTA")
                    blink_red_blue_with_buzzer()  # ~5 s de alerta
                else:
                    led_off()
                    buzzer_off()
                    time.sleep(5)  # espera normal entre lecturas
            else:
                print("Lectura nula, reintentando...")
                show_lcd("Lectura nula", "Reintentando...")
                led_off(); buzzer_off(); fan_off()
                time.sleep(3)

        except RuntimeError as e:
            print("Error de lectura:", e.args[0])
            show_lcd("Error lectura", "Reintentando...")
            led_off(); buzzer_off(); fan_off()
            time.sleep(2)

except KeyboardInterrupt:
    print("\nPrograma detenido por el usuario.")
finally:
    # Cierre ordenado
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
    print("GPIO/LCD/FAN liberados y MongoDB cerrado.")
