# GARRA-OS - Persistencia en la Nube y Dashboard de Control


**Instituto Tecnológico de León**
Ingeniería en Sistemas Computacionales — Sistemas Programables

**Unidad 4: Comunicaciones**

**Docente:** Ma. Verónica Tapia Ibarra

## Integrantes
- Alcalá Ramos Luz Estefanía
- Bahena Mora Emilio Salvador
- Casas Bastidas José Iván
- Fischer González Patrick

---

## Arquitectura

```
   ESP32 (GARRA-OS)              PC servidor                    Navegador
   ┌──────────────┐              ┌─────────────┐              ┌──────────────┐
   │ Sensores +   │ ── MQTT ──▶ │   Python    │ ── escribe ─▶│  Firebase    │
   │ Actuadores   │ ◀── MQTT ── │   puente    │ ◀── stream ──│  Realtime DB │
   │ (firmware/)  │              │ (servidor/) │              └──────┬───────┘
   └──────────────┘              └─────────────┘                     │
                                                                     │ onValue
                                                                     ▼
                                                              ┌──────────────┐
                                                              │  Dashboard   │
                                                              │ (dashboard/) │
                                                              └──────────────┘
```

El robot publica telemetría por MQTT. El script Python escucha, registra todo en
Firebase con timestamp del servidor y, a la vez, escucha cambios en `/comandos`
(cuando el usuario toca un botón en la web) y los retransmite por MQTT a la ESP32.

## Estructura del repositorio

El proyecto está organizado por **entornos de ejecución**, para no mezclar el
código que corre en el microcontrolador con el que corre en la PC ni con la
documentación administrativa.

```
GARRA-OS-Firebase/
│
├── Firmware/                          # ► MicroPython — corre DENTRO de la ESP32
│   └── README.md                      #   (sensores, actuadores, MQTT del robot)
│
├── Servidor/                          # ► Python estándar — corre en la PC (Servidor Perimetral)
│   ├── servidor_firebase.py           #   Puente MQTT ↔ Firebase
│   ├── simulador_esp32.py             #   Simulador de hardware para pruebas sin ESP32
│   ├── requirements.txt               #   Dependencias de Python
│   ├── firebase_credentials.example.json   # Plantilla de credenciales
│   └── firebase_credentials.json      #   (REAL · va en .gitignore · NO se sube)
│
├── Dashboard/                         # ► Interfaz web (front-end)
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── logo.gif
│
├── Firebase/                          # ► Configuración de la nube
│   └── firebase_rules.json            #   Reglas de seguridad de la Realtime DB
│
├── Documentación Técnica/             # ► Documentación técnica
│   └── Reporte_Unidad3_GARRA-OS.docx
│
├── .git
└── README.md
```

## Instalación y ejecución

### 1) Crear el proyecto en Firebase

1. Entrar a [Firebase Console](https://console.firebase.google.com/) y crear un proyecto llamado `garra-os`.
2. Habilitar **Realtime Database** (modo de prueba al inicio).
3. Pegar el contenido de `firebase/firebase_rules.json` en la pestaña **Reglas** y publicar.
4. **Cuentas de servicio → Generar nueva clave privada** y guardar el JSON descargado como `servidor/firebase_credentials.json`.
5. **Habilitar Autenticación anónima** en Authentication → Sign-in method.
6. Crear una **app Web** y copiar el `firebaseConfig` en `dashboard/app.js`.

### 2) Correr el servidor Python (Servidor Perimetral)

```bash
cd servidor
pip install -r requirements.txt
python servidor_firebase.py
```

Para probar sin hardware físico, en otra terminal:

```bash
cd servidor
python simulador_esp32.py
```

### 3) Servir el dashboard

```bash
cd dashboard
python -m http.server 8080
```

Y abrir `http://localhost:8080`.

> Flujo de tres terminales: (1) `servidor_firebase.py`, (2) `simulador_esp32.py`,
> (3) servidor HTTP del dashboard.

## Eventos registrados en Firebase

Cada evento se guarda en `/eventos/{push_id}` con esta forma:

```json
{
  "tipo": "telemetria" | "alerta" | "actuador",
  "datos": { ... },
  "timestamp": 1716847200000
}
```

| Tipo         | Origen                            | Ejemplo de `datos`                                   |
| ------------ | --------------------------------- | ---------------------------------------------------- |
| `telemetria` | Sensores HC-SR04 / MPU / batería  | `{ "sensor": "distancia", "valor": 24.7 }`           |
| `alerta`     | IA simple (golpe, obstáculo, bat) | `{ "fuente": "mpu6050", "mensaje": "...", "severidad": "alta" }` |
| `actuador`   | Cambios disparados desde el dash  | `{ "actuador": "servo", "valor": 120 }`              |

El timestamp lo pone **el servidor de Firebase** (`{".sv": "timestamp"}`), no el
cliente, para mantener consistencia entre dispositivos.

## Privacidad

El sistema **no almacena imágenes ni datos faciales** en Firebase. Toda la
información subida es numérica (distancias, aceleraciones, porcentaje de batería)
o de estado (online/offline, severidad de alertas). Esto cumple el requisito
explícito de la rúbrica.

## Control bidireccional

Desde el dashboard se puede mover el **servo del cuello** (0°–180°), cambiar la
**emoción de la OLED** (feliz / neutro / alerta), emitir un **beep del buzzer**
(1000 Hz, 300 ms) y disparar un **paro de emergencia**. Cada acción escribe en
`/comandos/...` y el servidor Python la transforma en una publicación MQTT.

## Broker MQTT

Se utiliza el broker público **HiveMQ** (`broker.hivemq.com:1883`), el mismo que
usa la ESP32 y el simulador.
