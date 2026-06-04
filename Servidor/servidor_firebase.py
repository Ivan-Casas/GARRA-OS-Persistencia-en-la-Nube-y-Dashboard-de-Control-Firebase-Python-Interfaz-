"""
=========================================================================
OBJETIVO:
Servidor puente MQTT <-> Firebase para el proyecto GARRA-OS.

Este script corre en la PC y cumple TRES funciones simultaneas:

   1. ESCUCHA por MQTT toda la telemetria que la ESP32 publica
      (distancia HC-SR04, aceleracion MPU6050, golpes, bateria).

   2. ESCRIBE cada evento en Firebase Realtime Database con un
      timestamp del servidor. Se guardan 3 tipos de eventos:
         - "telemetria"  -> lecturas periodicas de sensores
         - "alerta"      -> golpes detectados o bateria baja (IA simple)
         - "actuador"    -> cambios de estado de OLED / servo / buzzer

   3. ESCUCHA cambios en el nodo /comandos de Firebase y los traduce
      a publicaciones MQTT hacia la ESP32 (control bidireccional desde
      el dashboard).

PRIVACIDAD: nunca se sube ningun frame de camara ni rostro. Solo datos
numericos y de estado. La rubrica lo exige explicitamente.

INTEGRANTES:
  - Alcala Ramos Luz Estefania
  - Bahena Mora Emilio Salvador
  - Casas Bastidas Jose Ivan
  - Fischer Gonzalez Patrick

PROYECTO: GARRA-OS - Agente Robotico Autonomo con Interfaz Cognitiva
DOCENTE : Ma. Veronica Tapia Ibarra
MATERIA : Sistemas Programables - Unidad 4
=========================================================================
"""

# -------------------------------------------------------------------------
# IMPORTS
# -------------------------------------------------------------------------

# paho-mqtt es el cliente MQTT de Python. Lo usamos para conectarnos al
# mismo broker que ya usa la ESP32 (broker.hivemq.com).
# Instalacion: pip install paho-mqtt
import paho.mqtt.client as mqtt

# firebase-admin es el SDK oficial de Google para hablar con Firebase
# desde un servidor de confianza. Lo usamos para escribir telemetria y
# para suscribirnos a cambios del nodo /comandos.
# Instalacion: pip install firebase-admin
import firebase_admin
from firebase_admin import credentials, db

# json para serializar/deserializar mensajes MQTT.
import json

# datetime para imprimir logs legibles en consola con hora local.
from datetime import datetime

# time para pequenas pausas.
import time


# -------------------------------------------------------------------------
# CONFIGURACION
# -------------------------------------------------------------------------

# Broker MQTT publico (mismo que la ESP32). En produccion habria que
# migrar a un broker propio con TLS, pero para el alcance del curso
# basta con Mosquitto publico.
BROKER  = "broker.hivemq.com"
PUERTO  = 1883

# ID del nodo (debe coincidir con el ID configurado en la ESP32).
# Esto nos permitiria escalar a varios robots en el futuro.
ID_NODO = "01"

# Topicos de SUBSCRIPCION: lo que la ESP32 publica y nosotros leemos.
TOP_DISTANCIA   = f"garraos/{ID_NODO}/sensor/distancia"
TOP_ACEL        = f"garraos/{ID_NODO}/sensor/aceleracion"
TOP_GOLPE       = f"garraos/{ID_NODO}/sensor/golpe"
TOP_BATERIA     = f"garraos/{ID_NODO}/sensor/bateria"
TOP_ESTADO      = f"garraos/{ID_NODO}/estado"      # online/offline (LWT)

# Topicos de PUBLICACION: comandos que mandamos a la ESP32.
TOP_CMD_SERVO   = f"garraos/{ID_NODO}/cmd/servo"
TOP_CMD_OLED    = f"garraos/{ID_NODO}/cmd/oled"
TOP_CMD_BUZZER  = f"garraos/{ID_NODO}/cmd/buzzer"
TOP_CMD_PARO    = f"garraos/{ID_NODO}/cmd/paro"

# Archivo de credenciales de Firebase (Service Account).
# Se descarga desde Firebase Console > Configuracion del proyecto >
# Cuentas de servicio > Generar nueva clave privada.
RUTA_CREDENCIALES = "firebase_credentials.json"

# URL de la Realtime Database (cambiar por la de tu proyecto).
URL_FIREBASE = "https://garra-os-default-rtdb.firebaseio.com/"


# -------------------------------------------------------------------------
# INICIALIZACION DE FIREBASE
# -------------------------------------------------------------------------

# Cargamos las credenciales del service account.
cred = credentials.Certificate(RUTA_CREDENCIALES)

# Inicializamos el SDK apuntando a la Realtime Database del proyecto.
firebase_admin.initialize_app(cred, {
    "databaseURL": URL_FIREBASE
})

# Referencias a los nodos principales de la BD. Las dejamos como globales
# para no estar pidiendolas en cada callback.
ref_telemetria = db.reference("/telemetria")   # ultima lectura por sensor
ref_eventos    = db.reference("/eventos")      # log historico (timestamped)
ref_alertas    = db.reference("/alertas")      # ultimas N alertas
ref_estado     = db.reference("/estado")       # online/offline + ultima_act
ref_comandos   = db.reference("/comandos")     # lo que el dashboard escribe

print("[FB] Firebase inicializado correctamente.")


# -------------------------------------------------------------------------
# FUNCIONES AUXILIARES
# -------------------------------------------------------------------------

def ahora_str():
    """Devuelve la hora actual en formato legible para logs de consola."""
    return datetime.now().strftime("%H:%M:%S")


def registrar_evento(tipo, datos):
    """
    Guarda un evento en Firebase con timestamp del SERVIDOR (no del
    cliente) para evitar problemas de relojes desincronizados.

    'tipo' es una de las 3 categorias exigidas por la rubrica:
       - "telemetria" -> lectura periodica de sensores
       - "alerta"     -> golpe detectado, bateria critica, etc.
       - "actuador"   -> cambio de estado de OLED, servo o buzzer
    """
    # firebase.database.ServerValue.TIMESTAMP es el patron oficial para
    # que la marca de tiempo la ponga el SERVIDOR de Firebase. Asi
    # garantizamos consistencia entre nodos y entre dispositivos.
    paquete = {
        "tipo": tipo,
        "datos": datos,
        "timestamp": {".sv": "timestamp"}   # marca generada por Firebase
    }

    # push() crea una clave unica ordenable por tiempo (mejor que set()
    # para historicos). Devuelve la referencia al nuevo nodo.
    ref_eventos.push(paquete)

    # Si es alerta, ademas la guardamos en /alertas para tenerla a la
    # mano en el dashboard sin tener que filtrar todo el historico.
    if tipo == "alerta":
        ref_alertas.push(paquete)
        # Mantenemos solo las ULTIMAS 5 alertas (lo pide la rubrica).
        # Leemos todas, ordenamos por key y borramos las antiguas.
        todas = ref_alertas.get() or {}
        if len(todas) > 5:
            # Ordenadas por key (push() genera keys cronologicas).
            sobrantes = sorted(todas.keys())[:-5]
            for k in sobrantes:
                ref_alertas.child(k).delete()


# -------------------------------------------------------------------------
# CALLBACKS DE MQTT
# -------------------------------------------------------------------------

def on_connect(client, userdata, flags, rc, properties=None):
    """Callback cuando nos conectamos exitosamente al broker MQTT."""
    if rc == 0:
        print(f"[{ahora_str()}] [MQTT] Conectado al broker {BROKER}")
        # Nos suscribimos a TODOS los topicos del nodo. El '#' es comodin
        # MQTT que captura cualquier sub-topico.
        client.subscribe(f"garraos/{ID_NODO}/#")
        # Marcamos el sistema como online en Firebase.
        ref_estado.update({
            "online": True,
            "ultima_actualizacion": {".sv": "timestamp"}
        })
    else:
        print(f"[{ahora_str()}] [MQTT] Error de conexion, codigo {rc}")


def on_message(client, userdata, msg):
    """
    Callback que se dispara CADA vez que llega un mensaje MQTT.
    Aqui hacemos el ruteo: segun el topico, escribimos en una rama u
    otra de Firebase y, si corresponde, generamos una alerta.
    """
    # Decodificamos el payload de bytes a string.
    payload = msg.payload.decode("utf-8", errors="ignore")
    topico  = msg.topic

    # Log local para depuracion (no se sube a Firebase).
    print(f"[{ahora_str()}] [MQTT<-] {topico} = {payload}")

    # --- 1. DISTANCIA ULTRASONICA -----------------------------------------
    if topico == TOP_DISTANCIA:
        try:
            distancia = float(payload)
        except ValueError:
            return
        # Actualizamos la ultima lectura (el dashboard la lee de aqui).
        ref_telemetria.child("distancia_cm").set(distancia)
        # Logueamos como telemetria.
        registrar_evento("telemetria", {"sensor": "distancia", "valor": distancia})
        # IA simple: si hay un obstaculo muy cerca, alerta.
        if distancia < 10:
            registrar_evento("alerta", {
                "fuente": "ultrasonico",
                "mensaje": f"Obstaculo muy cercano ({distancia:.1f} cm)",
                "severidad": "media"
            })

    # --- 2. ACELERACION MPU6050 -------------------------------------------
    elif topico == TOP_ACEL:
        try:
            acc = json.loads(payload)   # {"x":..., "y":..., "z":...}
        except json.JSONDecodeError:
            return
        ref_telemetria.child("aceleracion").set(acc)
        registrar_evento("telemetria", {"sensor": "aceleracion", "valor": acc})

    # --- 3. GOLPE DETECTADO (IA del MPU) ----------------------------------
    elif topico == TOP_GOLPE:
        # La ESP32 ya hizo el procesamiento (umbral en magnitud). Aqui
        # solo lo registramos como alerta de alta severidad.
        registrar_evento("alerta", {
            "fuente": "mpu6050",
            "mensaje": "Golpe detectado en el chasis",
            "severidad": "alta"
        })

    # --- 4. BATERIA -------------------------------------------------------
    elif topico == TOP_BATERIA:
        try:
            bateria = float(payload)
        except ValueError:
            return
        ref_telemetria.child("bateria_pct").set(bateria)
        registrar_evento("telemetria", {"sensor": "bateria", "valor": bateria})
        if bateria < 20:
            registrar_evento("alerta", {
                "fuente": "bateria",
                "mensaje": f"Bateria baja ({bateria:.0f}%)",
                "severidad": "media"
            })

    # --- 5. ESTADO (LWT = Last Will and Testament) ------------------------
    elif topico == TOP_ESTADO:
        # La ESP32 envia "online" al conectar y, gracias al LWT,
        # el broker envia "offline" si se cae sin avisar.
        ref_estado.update({
            "online": (payload == "online"),
            "ultima_actualizacion": {".sv": "timestamp"}
        })


# -------------------------------------------------------------------------
# LISTENER DE COMANDOS (Firebase -> MQTT)
# -------------------------------------------------------------------------

def on_comando_firebase(event):
    """
    Se dispara cuando el dashboard escribe en /comandos.
    'event.path' indica que sub-nodo cambio ('/servo', '/oled', etc.)
    'event.data' es el nuevo valor.

    Esta es la pieza clave del CONTROL BIDIRECCIONAL: el usuario toca
    un boton en la web -> Firebase notifica -> nosotros publicamos en
    MQTT -> la ESP32 actua sobre el hardware.
    """
    # En el primer 'snapshot' Firebase manda TODO el nodo. Lo ignoramos
    # porque solo nos interesan cambios POSTERIORES.
    if event.path == "/" and event.data is None:
        return
    if event.path == "/":
        print(f"[{ahora_str()}] [FB] Snapshot inicial de /comandos ignorado.")
        return

    # event.path viene como "/servo", "/oled", etc.
    sub = event.path.strip("/")
    valor = event.data
    print(f"[{ahora_str()}] [FB->] Comando recibido: {sub} = {valor}")

    # Mapeo de comando -> topico MQTT.
    if sub == "servo":
        # Esperamos un entero 0..180 (angulo del cuello).
        cliente_mqtt.publish(TOP_CMD_SERVO, str(valor))
        registrar_evento("actuador", {"actuador": "servo", "valor": valor})

    elif sub == "oled":
        # Esperamos "feliz" / "alerta" / "neutro".
        cliente_mqtt.publish(TOP_CMD_OLED, str(valor))
        registrar_evento("actuador", {"actuador": "oled", "valor": valor})

    elif sub == "buzzer":
        # Esperamos un objeto {"freq": 1000, "ms": 300} o "off".
        if isinstance(valor, dict):
            cliente_mqtt.publish(TOP_CMD_BUZZER, json.dumps(valor))
        else:
            cliente_mqtt.publish(TOP_CMD_BUZZER, str(valor))
        registrar_evento("actuador", {"actuador": "buzzer", "valor": valor})

    elif sub == "paro":
        # Paro de emergencia: cualquier valor "truthy" lo dispara.
        if valor:
            cliente_mqtt.publish(TOP_CMD_PARO, "1")
            registrar_evento("actuador", {"actuador": "paro_emergencia", "valor": True})


# -------------------------------------------------------------------------
# ARRANQUE
# -------------------------------------------------------------------------

# Cliente MQTT. Lo dejamos como global para que on_comando_firebase
# pueda publicar.
cliente_mqtt = mqtt.Client(client_id=f"puente_garraos_{ID_NODO}",
                           callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
cliente_mqtt.on_connect = on_connect
cliente_mqtt.on_message = on_message

# Conectamos.
print(f"[{ahora_str()}] [MQTT] Conectando a {BROKER}:{PUERTO}...")
cliente_mqtt.connect(BROKER, PUERTO, keepalive=60)

# Suscripcion al nodo /comandos de Firebase (stream, no polling).
# Esto es CLAVE: 'listen()' abre un canal SSE que nos notifica en
# milisegundos cuando alguien escribe desde el dashboard.
print(f"[{ahora_str()}] [FB] Escuchando cambios en /comandos...")
ref_comandos.listen(on_comando_firebase)

# loop_forever() bloquea el hilo principal procesando mensajes MQTT.
# El listener de Firebase ya corre en su propio hilo, asi que ambos
# canales funcionan en paralelo.
try:
    cliente_mqtt.loop_forever()
except KeyboardInterrupt:
    print(f"\n[{ahora_str()}] Servidor detenido por el usuario.")
    # Antes de salir marcamos el sistema como offline.
    ref_estado.update({
        "online": False,
        "ultima_actualizacion": {".sv": "timestamp"}
    })
    cliente_mqtt.disconnect()
