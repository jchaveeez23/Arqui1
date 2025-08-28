# -*- coding: utf-8 -*-
import time
import board
import adafruit_dht
from RPLCD.i2c import CharLCD

# --- Config LCD I²C (0x27 según i2cdetect) ---
lcd = CharLCD(
    i2c_expander='PCF8574',
    address=0x27,
    port=1,
    cols=16,
    rows=2,
    charmap='A02',         # si ves caracteres raros, prueba 'A00'
    auto_linebreaks=False
)

# --- Sensor DHT11 en GPIO4 ---
dht = adafruit_dht.DHT11(board.D4)

def show(msg1="", msg2=""):
    """Imprime dos líneas en la LCD (16x2)."""
    lcd.clear()
    lcd.write_string(msg1[:16])
    if msg2:
        lcd.cursor_pos = (1, 0)
        lcd.write_string(msg2[:16])

try:
    show("Leyendo DHT11", "Espere...")
    time.sleep(1)

    while True:
        try:
            t = dht.temperature         # °C
            h = dht.humidity            # %
            if t is not None and h is not None:
                # Consola
                print("Temperatura: {:.1f} C".format(t))
                print("Humedad: {:.1f} %".format(h))
                # LCD
                show("Temp: {:.1f}C".format(t),
                     "Hum:  {:.1f}%".format(h))
            else:
                print("Lectura nula, reintento")
                show("Lectura nula", "Reintentando...")
        except RuntimeError as e:
            # Errores típicos del DHT11 (checksum/tiempos)
            print("Error de lectura:", e.args[0])
            show("Error lectura", "Reintentando...")
            time.sleep(2)
        time.sleep(5)

except KeyboardInterrupt:
    print("\nPrograma detenido por el usuario.")
finally:
    try:
        dht.exit()
    except Exception:
        pass
    try:
        show("Hasta luego :)")
        time.sleep(0.5)
        lcd.clear()
        lcd.close(clear=True)
    except Exception:
        pass
    print("GPIO y LCD liberados correctamente.")
