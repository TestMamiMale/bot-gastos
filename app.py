
import os
# Las variables se leen desde .env solo en local
if os.path.exists(".env"):
    for line in open(".env"):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k, v)
import re
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from sheets import guardar_gasto, obtener_resumen, guardar_foto_pendiente
from state import get_state, set_state, clear_state

app = Flask(__name__)

TWILIO_SID   = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")

CATEGORIAS = [
    "1. 🍽️ Comida", "2. 🚌 Transporte", "3. 🏠 Hogar",
    "4. 💊 Salud", "5. 🎮 Entretenimiento", "6. 👕 Ropa",
    "7. 📚 Educación", "8. 💼 Trabajo", "9. Otro"
]
METODOS = [
    "1. 💳 Débito", "2. 💳 Crédito",
    "3. 💵 Efectivo", "4. 📱 Transferencia"
]
MAP_CATEGORIA = {
    "1":"🍽️ Comida","comida":"🍽️ Comida",
    "2":"🚌 Transporte","transporte":"🚌 Transporte",
    "3":"🏠 Hogar","hogar":"🏠 Hogar",
    "4":"💊 Salud","salud":"💊 Salud",
    "5":"🎮 Entretenimiento","entretenimiento":"🎮 Entretenimiento",
    "6":"👕 Ropa","ropa":"👕 Ropa",
    "7":"📚 Educación","educación":"📚 Educación","educacion":"📚 Educación",
    "8":"💼 Trabajo","trabajo":"💼 Trabajo",
    "9":"Otro","otro":"Otro"
}
MAP_METODO = {
    "1":"💳 Débito","débito":"💳 Débito","debito":"💳 Débito",
    "2":"💳 Crédito","crédito":"💳 Crédito","credito":"💳 Crédito",
    "3":"💵 Efectivo","efectivo":"💵 Efectivo",
    "4":"📱 Transferencia","transferencia":"📱 Transferencia"
}

def fmt(monto):
    return f"${int(monto):,}".replace(",", ".")

def descargar_imagen(url):
    """Descarga imagen desde Twilio con autenticación"""
    r = requests.get(url, auth=(TWILIO_SID, TWILIO_TOKEN), timeout=15)
    if r.status_code != 200:
        raise Exception(f"No se pudo descargar la imagen: {r.status_code}")
    content_type = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
    import base64
    return base64.b64encode(r.content).decode("utf-8"), content_type

@app.route("/webhook", methods=["POST"])
def webhook():
    sender    = request.form.get("From", "")
    body      = request.form.get("Body", "").strip()
    num_media = int(request.form.get("NumMedia", 0))
    msg_lower = body.lower()

    resp = MessagingResponse()
    msg  = resp.message()

    state  = get_state(sender)
    step   = state.get("step", "menu")
    gasto  = state.get("gasto", {})
    nombre = state.get("nombre", "")

    # Comando global cancelar
    if msg_lower in ["cancelar", "cancel", "salir"]:
        set_state(sender, {"step": "menu", "nombre": nombre})
        msg.body("❌ Operación cancelada.\n\nEscribe *hola* para volver al menú.")
        return str(resp)

    # ── PRIMER USO: pedir nombre ──
    if not nombre and step != "registro_nombre":
        set_state(sender, {"step": "registro_nombre", "gasto": {}, "nombre": ""})
        msg.body("👋 ¡Hola! Soy tu asistente de gastos 💰\n\nEs tu primera vez — ¿cuál es tu nombre?")
        return str(resp)

    if step == "registro_nombre":
        nombre = body.strip().title()
        set_state(sender, {"step": "menu", "nombre": nombre, "gasto": {}})
        msg.body(
            f"¡Perfecto, {nombre}! Ya te registré 🙌\n\n"
            "¿Qué quieres hacer?\n\n"
            "1️⃣ *Nuevo gasto* (manual)\n"
            "2️⃣ *Ver resumen*\n"
            "📸 O envía una *foto de boleta* para registrar automáticamente"
        )
        return str(resp)

    # ── FOTO RECIBIDA ──
    if num_media > 0:
        media_url = request.form.get("MediaUrl0", "")
        try:
            msg.body(f"📸 Recibí tu boleta, {nombre}. Guardando como pendiente de análisis...")
            img_b64, mime = descargar_imagen(media_url)
            guardar_foto_pendiente({
                "quien":      nombre,
                "imagen_b64": img_b64,
                "mime_type":  mime
            })
            set_state(sender, {"step": "menu", "nombre": nombre, "gasto": {}})
            msg.body(
                f"✅ Foto guardada, {nombre}.\n\n"
                "La boleta quedó en la pestaña *Fotos Pendientes* del Sheet.\n"
                "Cuando quieras analizarla escribe *procesar fotos*.\n\n"
                "¿Qué más quieres hacer?\n"
                "1️⃣ *Nuevo gasto* (manual)\n"
                "2️⃣ *Ver resumen*"
            )
        except Exception as e:
            msg.body(f"❌ Error al guardar la foto: {str(e)}\n\nIntenta de nuevo.")
        return str(resp)

    # ── MENÚ PRINCIPAL ──
    if step == "menu":
        if msg_lower in ["hola","hola!","hi","buenas","menu","menú","inicio","1","nuevo gasto","nuevo"]:
            set_state(sender, {"step": "descripcion", "gasto": {}, "nombre": nombre})
            msg.body(
                f"✏️ *Nuevo gasto* — {nombre}\n\n"
                "¿En qué gastaste? Escribe una descripción breve.\n\n"
                "_Ej: Almuerzo, Uber, Supermercado_"
            )
        elif msg_lower in ["2","resumen","ver resumen","mis gastos","gastos"]:
            msg.body(obtener_resumen())
        elif msg_lower in ["procesar fotos","procesar","analizar fotos","analizar"]:
            msg.body(
                "⚙️ Para analizar las fotos pendientes con IA:\n\n"
                "1. Abre tu Google Sheet\n"
                "2. Menú *🧾 Boletas* → *▶️ Procesar fotos pendientes*\n\n"
                "El script analiza cada foto con Gemini y completa los datos automáticamente."
            )
        else:
            msg.body(
                f"Hola {nombre} 👋\n\n"
                "¿Qué quieres hacer?\n\n"
                "1️⃣ *Nuevo gasto* (manual)\n"
                "2️⃣ *Ver resumen*\n"
                "📸 Envía una *foto de boleta* para registrar automáticamente"
            )
        return str(resp)

    # ── PASO 1: DESCRIPCIÓN ──
    if step == "descripcion":
        if len(body) < 2:
            msg.body("Por favor escribe una descripción más detallada 📝")
            return str(resp)
        gasto["descripcion"] = body
        set_state(sender, {"step": "categoria", "gasto": gasto, "nombre": nombre})
        msg.body("🏷️ *Categoría*\n\n¿Qué tipo de gasto es?\n\n" + "\n".join(CATEGORIAS) + "\n\n_Escribe el número o el nombre_")
        return str(resp)

    # ── PASO 2: CATEGORÍA ──
    if step == "categoria":
        key = msg_lower.replace(".", "").strip()
        categoria = MAP_CATEGORIA.get(key)
        if not categoria:
            msg.body("⚠️ No reconocí esa categoría. Elige una:\n\n" + "\n".join(CATEGORIAS))
            return str(resp)
        gasto["categoria"] = categoria
        set_state(sender, {"step": "metodo", "gasto": gasto, "nombre": nombre})
        msg.body("💳 *Método de pago*\n\n¿Con qué pagaste?\n\n" + "\n".join(METODOS) + "\n\n_Escribe el número o el nombre_")
        return str(resp)

    # ── PASO 3: MÉTODO ──
    if step == "metodo":
        key = msg_lower.replace(".", "").strip()
        metodo = MAP_METODO.get(key)
        if not metodo:
            msg.body("⚠️ No reconocí ese método. Elige uno:\n\n" + "\n".join(METODOS))
            return str(resp)
        gasto["metodo"] = metodo
        set_state(sender, {"step": "monto", "gasto": gasto, "nombre": nombre})
        msg.body("💰 *Monto*\n\n¿Cuánto fue?\n\n_Ej: 5000_")
        return str(resp)

    # ── PASO 4: MONTO ──
    if step == "monto":
        monto_str = re.sub(r"[^\d.]", "", body)
        try:
            monto = float(monto_str)
            if monto <= 0: raise ValueError
        except ValueError:
            msg.body("⚠️ Ingresa un monto válido.\n\n_Ej: 5000_")
            return str(resp)

        gasto["monto"] = monto
        gasto["quien"] = nombre
        try:
            guardar_gasto(gasto)
        except Exception as e:
            msg.body(f"❌ Error al guardar: {str(e)}\n\nIntenta de nuevo.")
            set_state(sender, {"step": "menu", "nombre": nombre})
            return str(resp)

        set_state(sender, {"step": "menu", "nombre": nombre})
        msg.body(
            f"✅ *¡Gasto registrado, {nombre}!*\n\n"
            f"📝 {gasto['descripcion']}\n"
            f"🏷️ {gasto['categoria']}\n"
            f"💳 {gasto['metodo']}\n"
            f"💰 {fmt(monto)}\n\n"
            "¿Qué más quieres hacer?\n\n"
            "1️⃣ *Nuevo gasto*\n"
            "2️⃣ *Ver resumen*\n"
            "📸 O envía una *foto de boleta*"
        )
        return str(resp)

    # Fallback
    set_state(sender, {"step": "menu", "nombre": nombre})
    msg.body("No entendí eso 🤔\n\nEscribe *hola* para ver el menú.")
    return str(resp)

@app.route("/", methods=["GET"])
def health():
    return "Bot de gastos activo ✅", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
