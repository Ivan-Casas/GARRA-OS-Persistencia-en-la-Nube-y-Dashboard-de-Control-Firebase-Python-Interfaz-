/* =========================================================================
   OBJETIVO: Logica del dashboard GARRA-OS. Conecta con Firebase Realtime
             Database usando el SDK modular v10, muestra telemetria en
             tiempo real (suscripcion 'onValue'), pinta las ultimas 5
             alertas y escribe en /comandos para controlar los actuadores
             a traves del puente Python -> MQTT -> ESP32.

   INTEGRANTES:
     - Alcala Ramos Luz Estefania
     - Bahena Mora Emilio Salvador
     - Casas Bastidas Jose Ivan
     - Fischer Gonzalez Patrick

   PROYECTO: GARRA-OS - Agente Robotico Autonomo con Interfaz Cognitiva
   DOCENTE : Ma. Veronica Tapia Ibarra
   ========================================================================= */

// ---- Imports del SDK modular de Firebase v10 (cargado desde CDN) -------
import { initializeApp }
  from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
import { getDatabase, ref, onValue, set, query, limitToLast, orderByKey }
  from "https://www.gstatic.com/firebasejs/10.12.0/firebase-database.js";
import { getAuth, signInAnonymously }
  from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";


// ---- CONFIGURACION DE FIREBASE -----------------------------------------
// Estos valores se obtienen en: Firebase Console -> Configuracion del
// proyecto -> Apps -> Web App -> "SDK setup and configuration".
// NOTA: la apiKey de cliente NO es secreta, esta disenada para vivir
// en el front-end. La seguridad real la dan las "Rules" de la DB.
const firebaseConfig = {
  apiKey:            "AIzaSyDALAxw2vZpoqGUylpOB7O350SvD22_Rxo",
  authDomain:        "garra-os.firebaseapp.com",
  databaseURL:       "https://garra-os-default-rtdb.firebaseio.com/",
  projectId:         "garra-os",
  storageBucket:     "garra-os.firebasestorage.app",
  messagingSenderId: "816213685385",
  appId:             "1:816213685385:web:d3246c1750db4804510258"
};

// ---- INICIALIZACION ----------------------------------------------------
const app  = initializeApp(firebaseConfig);
const db   = getDatabase(app);
const auth = getAuth(app);

// Autenticacion anonima para cumplir la regla "auth != null" en la BD.
// En produccion se cambiaria por login real (Google/email).
signInAnonymously(auth)
  .then(() => console.log("[Auth] Sesion anonima iniciada"))
  .catch(err => console.error("[Auth] Error:", err));


// ---- REFERENCIAS A NODOS ------------------------------------------------
const refEstado     = ref(db, "/estado");
const refTelemetria = ref(db, "/telemetria");
// Solo las ULTIMAS 5 alertas (lo exige la rubrica). Firebase nos lo
// resuelve del lado del servidor con query() + limitToLast().
const refAlertas    = query(ref(db, "/alertas"), orderByKey(), limitToLast(5));
const refComandos   = ref(db, "/comandos");


// ---- HELPERS DE UI ------------------------------------------------------
const $ = (id) => document.getElementById(id);

function flash(elem) {
  // Pequeno destello visual cuando un valor se actualiza.
  elem.classList.remove("flash");
  void elem.offsetWidth; // truco para reiniciar la animacion CSS
  elem.classList.add("flash");
}

function formatHora(ts) {
  if (!ts) return "—";
  const d = new Date(ts);
  return d.toLocaleTimeString("es-MX", { hour12: false });
}


// ---- 1. ESTADO ONLINE/OFFLINE -------------------------------------------
onValue(refEstado, (snap) => {
  const data = snap.val() || {};
  const pill = $("status-pill");
  const txt  = $("status-text");

  if (data.online === true) {
    pill.classList.remove("offline");
    pill.classList.add("online");
    txt.textContent = "Sistema en línea";
  } else {
    pill.classList.remove("online");
    pill.classList.add("offline");
    txt.textContent = "Sistema fuera de línea";
  }

  if (data.ultima_actualizacion) {
    $("sys-ultima").textContent = formatHora(data.ultima_actualizacion);
  }
});


// ---- 2. TELEMETRIA EN VIVO ----------------------------------------------
onValue(refTelemetria, (snap) => {
  const t = snap.val() || {};

  // Distancia ----------------------------------------------------------
  if (typeof t.distancia_cm === "number") {
    const elem = $("val-distancia");
    elem.textContent = t.distancia_cm.toFixed(1);
    flash(elem);
    // Barra: lo mapeamos a un rango de 0..100 cm.
    const pct = Math.min(100, (t.distancia_cm / 100) * 100);
    $("bar-distancia").style.width = pct + "%";
  }

  // Aceleracion -------------------------------------------------------
  if (t.aceleracion && typeof t.aceleracion === "object") {
    const a = t.aceleracion;
    if (typeof a.x === "number") { $("acc-x").textContent = a.x.toFixed(2); flash($("acc-x")); }
    if (typeof a.y === "number") { $("acc-y").textContent = a.y.toFixed(2); flash($("acc-y")); }
    if (typeof a.z === "number") { $("acc-z").textContent = a.z.toFixed(2); flash($("acc-z")); }
  }

  // Bateria -----------------------------------------------------------
  if (typeof t.bateria_pct === "number") {
    const elem = $("val-bateria");
    elem.textContent = Math.round(t.bateria_pct);
    flash(elem);
    $("bar-bateria").style.width = t.bateria_pct + "%";
    // Color segun nivel.
    const bar = $("bar-bateria");
    if (t.bateria_pct < 20)      bar.style.background = "linear-gradient(90deg,#ef4444,#f87171)";
    else if (t.bateria_pct < 50) bar.style.background = "linear-gradient(90deg,#fbbf24,#fcd34d)";
    else                         bar.style.background = "linear-gradient(90deg,#34d399,#10b981)";
  }
});


// ---- 3. ALERTAS (HISTORIAL DINAMICO DE LAS ULTIMAS 5) -------------------
onValue(refAlertas, (snap) => {
  const lista = $("alert-list");
  lista.innerHTML = "";

  // Recolectamos las alertas (vienen ordenadas por key cronologica
  // gracias a push() en el servidor Python).
  const alertas = [];
  snap.forEach((child) => alertas.push(child.val()));

  if (alertas.length === 0) {
    lista.innerHTML = '<li class="alert-empty">Sin alertas registradas todavía…</li>';
    return;
  }

  // Las invertimos para mostrar la mas reciente arriba.
  alertas.reverse().forEach((alerta) => {
    const d        = alerta.datos || {};
    const severity = d.severidad || "media";
    const fuente   = (d.fuente || "—").toUpperCase();
    const msg      = d.mensaje || "Alerta sin descripción";
    const hora     = formatHora(alerta.timestamp);

    const li = document.createElement("li");
    li.className = `alert-item sev-${severity}`;
    li.innerHTML = `
      <div class="alert-content">
        <p class="alert-msg">${msg}</p>
        <div class="alert-meta">
          <span class="alert-source">${fuente}</span>
          <span>${hora}</span>
        </div>
      </div>
    `;
    lista.appendChild(li);
  });
});


// ---- 4. CONTROL: SERVO DEL CUELLO --------------------------------------
const slider  = $("servo-slider");
const display = $("servo-display");

slider.addEventListener("input", () => {
  display.textContent = slider.value + "°";
});

// "change" se dispara cuando el usuario suelta el slider -> evita inundar
// Firebase con escrituras durante el arrastre.
slider.addEventListener("change", () => {
  const angulo = parseInt(slider.value, 10);
  set(ref(db, "/comandos/servo"), angulo)
    .then(() => console.log("[CMD] Servo ->", angulo))
    .catch(err => console.error("[CMD] Error servo:", err));
});


// ---- 5. CONTROL: EMOCION EN OLED ---------------------------------------
const botonesEmo = document.querySelectorAll(".emotion-btn");
botonesEmo.forEach((btn) => {
  btn.addEventListener("click", () => {
    const emo = btn.dataset.emo;
    botonesEmo.forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    set(ref(db, "/comandos/oled"), emo)
      .then(() => console.log("[CMD] OLED ->", emo))
      .catch(err => console.error("[CMD] Error OLED:", err));
  });
});


// ---- 6. CONTROL: BUZZER -------------------------------------------------
$("btn-buzzer").addEventListener("click", () => {
  // Mandamos un objeto con frecuencia y duracion. El servidor lo
  // serializa a JSON antes de publicar por MQTT.
  set(ref(db, "/comandos/buzzer"), { freq: 1000, ms: 300 })
    .then(() => console.log("[CMD] Buzzer beep enviado"))
    .catch(err => console.error("[CMD] Error buzzer:", err));
});


// ---- 7. CONTROL: PARO DE EMERGENCIA ------------------------------------
$("btn-paro").addEventListener("click", () => {
  if (!confirm("¿Confirmar paro de emergencia? Se apagarán todos los actuadores.")) {
    return;
  }
  set(ref(db, "/comandos/paro"), true)
    .then(() => {
      console.log("[CMD] PARO DE EMERGENCIA enviado");
      // Reseteamos visualmente el slider/emocion a estado neutro.
      slider.value = 90; display.textContent = "90°";
      botonesEmo.forEach(b => b.classList.remove("active"));
      // Limpiamos el flag despues de 1s (para que pueda volver a usarse).
      setTimeout(() => set(ref(db, "/comandos/paro"), false), 1000);
    })
    .catch(err => console.error("[CMD] Error paro:", err));
});


console.log("[GARRA-OS] Dashboard inicializado.");
