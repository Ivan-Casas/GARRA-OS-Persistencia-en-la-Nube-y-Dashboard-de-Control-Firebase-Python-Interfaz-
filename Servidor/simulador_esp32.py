"""
=========================================================================
OBJETIVO: Simulador de la ESP32 GARRA-OS para probar el servidor Firebase
          y el dashboard SIN tener el hardware fisico conectado.

          Este script publica datos falsos pero realistas en los mismos
          topicos MQTT que usaria la ESP32 real, y se suscribe a los
          topicos de comandos para imprimir en consola lo que llega
          desde el dashboard (simulando los actuadores).

INTEGRANTES:
  - Alcala Ramos Luz Estefania
  - Bahena Mora Emilio Salvador
  - Casas Bastidas Jose Ivan
  - Fischer Gonzalez Patrick

PROYECTO: GARRA-OS - Simulador de hardware para pruebas
=========================================================================
"""

import paho.mqtt.client as mqtt
import json
import time
import random
import math
from datetime import datetime


# -------------------------------------------------------------------------
# CONFIGURACION (debe coincidir con servidor_firebase.py)
# -------------------------------------------------------------------------
BROKER  = "broker.hivemq.com"   # Mismo broker que el servidor
PUERTO  = 1883
ID_NODO = "01"

# Topicos donde PUBLICAMOS telemetria (haciendo de ESP32).
TOP_DISTANCIA = f"garraos/{ID_NODO}/sensor/distancia"
TOP_ACEL      = f"garraos/{ID_NODO}/sensor/aceleracion"
TOP_GOLPE     = f"garraos/{ID_NODO}/sensor/golpe"
TOP_BATERIA   = f"garraos/{ID_NODO}/sensor/bateria"
TOP_ESTADO    = f"garraos/{ID_NODO}/estado"

# Topicos donde NOS SUSCRIBIMOS para recibir ordenes del dashboard.
TOP_CMD_TODOS = f"garraos/{ID_NODO}/cmd/#"


# -------------------------------------------------------------------------
# ESTADO INTERNO SIMULADO
# -------------------------------------------------------------------------
# Variables que cambian con el tiempo para que la simulacion se sienta viva.
bateria_actual    = 95.0          # arranca cargado
distancia_actual  = 50.0          # cm
contador_ciclos   = 0
servo_actual      = 90
emocion_actual    = "neutro"


def ahora_str():
    return datetime.now().strftime("%H:%M:%S")


# -------------------------------------------------------------------------
# CALLBACKS
# -------------------------------------------------------------------------
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[{ahora_str()}] [SIM] Conectado al broker {BROKER}")
        # Avisamos al servidor que estamos "online".
        client.publish(TOP_ESTADO, "online", retain=True)
        # Nos suscribimos a TODOS los comandos.
        client.subscribe(TOP_CMD_TODOS)
        print(f"[{ahora_str()}] [SIM] Escuchando comandos del dashboard...")
    else:
        print(f"[{ahora_str()}] [SIM] Error de conexion, codigo {rc}")


def on_message(client, userdata, msg):
    """Cuando el dashboard manda una orden, la imprimimos como si fuera
    la accion fisica del robot."""
    global servo_actual, emocion_actual

    topico = msg.topic
    payload = msg.payload.decode("utf-8", errors="ignore")

    if topico.endswith("/cmd/servo"):
        servo_actual = int(payload)
        print(f"[{ahora_str()}] [HW] >>> Servo del cuello -> {servo_actual}°")

    elif topico.endswith("/cmd/oled"):
        emocion_actual = payload
        caras = {"feliz": "︶‿︶", "neutro": "— —", "alerta": "◉ ◉"}
        cara = caras.get(payload, "?")
        print(f"[{ahora_str()}] [HW] >>> OLED mostrando: {payload}  {cara}")

    elif topico.endswith("/cmd/buzzer"):
        try:
            data = json.loads(payload)
            print(f"[{ahora_str()}] [HW] >>> 🔊 BEEP ({data.get('freq', '?')} Hz, {data.get('ms', '?')} ms)")
        except json.JSONDecodeError:
            print(f"[{ahora_str()}] [HW] >>> Buzzer: {payload}")

    elif topico.endswith("/cmd/paro"):
        if payload in ("1", "true", "True"):
            print(f"[{ahora_str()}] [HW] >>> 🛑 PARO DE EMERGENCIA - Todos los actuadores apagados")


# -------------------------------------------------------------------------
# CICLO DE PUBLICACION DE TELEMETRIA
# -------------------------------------------------------------------------
def simular_telemetria(client):
    """Cada llamada genera una lectura realista y la publica."""
    global bateria_actual, distancia_actual, contador_ciclos

    contador_ciclos += 1

    # --- DISTANCIA ULTRASONICA ---
    # Simulamos un obstaculo que se acerca y se aleja en patron senoidal.
    base = 50 + 40 * math.sin(contador_ciclos / 8)
    distancia_actual = max(5, base + random.uniform(-3, 3))
    client.publish(TOP_DISTANCIA, f"{distancia_actual:.1f}")

    # --- ACELERACION (MPU6050) ---
    # Gravedad apuntando hacia abajo en Z, con ruido en los tres ejes.
    acc = {
        "x": round(random.uniform(-0.2, 0.2), 3),
        "y": round(random.uniform(-0.2, 0.2), 3),
        "z": round(9.81 + random.uniform(-0.1, 0.1), 3)
    }
    client.publish(TOP_ACEL, json.dumps(acc))

    # --- BATERIA ---
    # Descarga lenta pero constante.
    bateria_actual = max(5, bateria_actual - 0.05)
    client.publish(TOP_BATERIA, f"{bateria_actual:.1f}")

    # --- GOLPE OCASIONAL ---
    # Cada ~30 ciclos disparamos un golpe para que aparezca una alerta.
    if contador_ciclos % 30 == 0:
        print(f"[{ahora_str()}] [SIM] *** Simulando golpe en el chasis ***")
        client.publish(TOP_GOLPE, "1")

    # Log compacto en consola
    print(f"[{ahora_str()}] [SIM] dist={distancia_actual:5.1f}cm  "
          f"bat={bateria_actual:5.1f}%  acc=({acc['x']:+.2f},{acc['y']:+.2f},{acc['z']:+.2f})")


# -------------------------------------------------------------------------
# ARRANQUE
# -------------------------------------------------------------------------
client = mqtt.Client(client_id=f"sim_garraos_{ID_NODO}",
                     callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

# Last Will and Testament: si el simulador se cae, el broker avisa "offline".
client.will_set(TOP_ESTADO, "offline", retain=True)

print(f"[{ahora_str()}] [SIM] Conectando a {BROKER}:{PUERTO}...")
client.connect(BROKER, PUERTO, keepalive=60)

# Arrancamos el loop de MQTT en segundo plano (no bloquea).
client.loop_start()

# Bucle principal: publicamos cada 2 segundos.
try:
    print(f"[{ahora_str()}] [SIM] Iniciando publicacion de telemetria (Ctrl+C para detener)...")
    print("-" * 75)
    while True:
        simular_telemetria(client)
        time.sleep(2)
except KeyboardInterrupt:
    print(f"\n[{ahora_str()}] [SIM] Simulador detenido por el usuario.")
    client.publish(TOP_ESTADO, "offline", retain=True)
    time.sleep(0.5)
    client.loop_stop()
    client.disconnect()
