import ssl
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt

BROKER   = "aaf5d2bb04bd4381bf8a96e2d7d371bf.s1.eu.hivemq.cloud"
PORT     = 8883
USERNAME = "hivemq.webclient.1756602313426"
PASSWORD = "l01U:us#*op2TSZ5G?dP"

BASE_TOPIC = "#"   # escuchamos TODOS los tópicos

# LEDs individuales
LED_PINS = {"1": 25, "2": 24, "3": 23}

# LED RGB
RGB_PINS = {"RED": 22, "GREEN": 27, "BLUE": 17}

# Servo (puerta)
SERVO_PIN = 18  # usa un pin con PWM (BCM 18 recomendado)

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

# Inicializa LEDs individuales
for pin in LED_PINS.values():
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

# Inicializa LED RGB
for pin in RGB_PINS.values():
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

# Inicializa servo
GPIO.setup(SERVO_PIN, GPIO.OUT)
servo = GPIO.PWM(SERVO_PIN, 50)  # PWM a 50Hz
servo.start(0)

def set_rgb(color: str):
    """Enciende SOLO el color indicado en la LED RGB"""
    if color == "OFF":
        for p in RGB_PINS.values():
            GPIO.output(p, GPIO.LOW)
        return
    for cname, pin in RGB_PINS.items():
        GPIO.output(pin, GPIO.HIGH if cname == color else GPIO.LOW)

def set_servo(angle):
    """Mueve el servo al ángulo indicado (0 a 180)"""
    duty = 2 + (angle / 18)  # conversión ángulo -> ciclo de trabajo
    GPIO.output(SERVO_PIN, True)
    servo.ChangeDutyCycle(duty)
    print(f"🔧 Servo -> {angle}°")

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Conectado a HiveMQ")
        client.subscribe(BASE_TOPIC)
        print(f"📡 Suscrito a: {BASE_TOPIC}")
    else:
        print("❌ Error al conectar. Código:", rc)

def on_message(client, userdata, msg):
    payload = msg.payload.decode(errors="ignore").strip().upper()
    print(f"{msg.topic} = {payload}")

    parts = msg.topic.split("/")

    # LED RGB
    if len(parts) == 2 and parts[0].upper() == "LED" and parts[1].upper() == "RGB":
        if payload in ("RED", "GREEN", "BLUE", "OFF"):
            set_rgb(payload)
        return

    # LEDs individuales
    if len(parts) == 2 and parts[0].upper() == "LED":
        led_id = parts[1]
        pin = LED_PINS.get(led_id)
        if pin:
            if payload == "ON":
                GPIO.output(pin, GPIO.HIGH)
                print(f"💡 LED {led_id} ENCENDIDA")
            elif payload == "OFF":
                GPIO.output(pin, GPIO.LOW)
                print(f"💡 LED {led_id} APAGADA")
        return

    # Servo (ENTRANCE)
    if parts[0].upper() == "ENTRANCE":
        if payload == "ON":
            set_servo(90)   # abre la puerta
            print("🚪 Puerta ABIERTA (90°)")
        elif payload == "OFF":
            set_servo(0)    # cierra la puerta
            print("🚪 Puerta CERRADA (0°)")
        else:
            print("⚠ Usa: ON u OFF para ENTRANCE")
        return

    print("⚠ Tópico no válido")

client = mqtt.Client(protocol=mqtt.MQTTv311)
client.username_pw_set(USERNAME, PASSWORD)
client.tls_set(tls_version=ssl.PROTOCOL_TLS, cert_reqs=ssl.CERT_REQUIRED)
client.tls_insecure_set(False)

client.on_connect = on_connect
client.on_message = on_message

try:
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_forever()
except KeyboardInterrupt:
    print("\n🛑 Saliendo...")
finally:
    servo.stop()
    GPIO.cleanup()
