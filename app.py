import os
from dotenv import load_dotenv
# Carga las variables de entorno desde .env
load_dotenv()

import re
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from sheets import guardar_gasto, obtener_resumen, guardar_foto_pendiente, obtener_config_usuario
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

    # Recuperar estado completo
    state           = get_state(sender)
    step            = state.get("step")
    nombre          = state.get("nombre")
    gasto           = state.get("gasto", {})
    proyectos       = state.get("proyectos", {})
    config_proyecto = state.get("config_proyecto")

    # Comando global cancelar o reinicio
    if msg_lower in ["cancelar", "cancel", "salir", "hola", "inicio", "menu"]:
        clear_state(sender)
        step = None 
        nombre = None

    # ── 1. VALIDACIÓN DE USUARIO Y SELECCIÓN DE PROYECTO ──
    if not nombre:
        try:
            config_usuario = obtener_config_usuario(sender)
            nombre = config_usuario.get("nombre")
            proyectos = config_usuario.get("proyectos", {})

            if not proyectos:
                msg.body("❌ No tienes proyectos asignados. Contacta al administrador.")
                clear_state(sender)
                return str(resp)

            lista_proyectos = list(proyectos.keys())
            if len(lista_proyectos) == 1:
                nombre_p = lista_proyectos[0]
                config_p = proyectos[nombre_p]
                new_state = {
                    "step": "menu", 
                    "nombre": nombre, 
                    "proyectos": proyectos, 
                    "config_proyecto": config_p,
                    "nombre_proyecto_actual": nombre_p
                }
                set_state(sender, new_state)
                msg.body(f"¡Hola {nombre}! 👋\nEstás en el proyecto *{nombre_p}*.\n\n1️⃣ *Nuevo gasto*\n2️⃣ *Ver resumen*\n📸 Envía una *foto*")
            else:
                set_state(sender, {"step": "elegir_proyecto", "nombre": nombre, "proyectos": proyectos})
                nombres_p = "\n".join([f"• {p}" for p in lista_proyectos])
                msg.body(f"¡Hola {nombre}! 👋\n\n¿En qué proyecto quieres trabajar?\n\n{nombres_p}")
            return str(resp)
        except Exception as e:
            clear_state(sender)
            msg.body(f"❌ Error de acceso: {e}")
            return str(resp)

    # ── 2. SELECCIÓN DE PROYECTO (Si tiene varios) ──
    if step == "elegir_proyecto":
        proyecto_elegido = next((p for p in proyectos if p.lower() == msg_lower), None)
        if proyecto_elegido:
            config_p = proyectos[proyecto_elegido]
            state.update({
                "step": "menu",
                "config_proyecto": config_p,
                "nombre_proyecto_actual": proyecto_elegido
            })
            set_state(sender, state)
            msg.body(f"✅ Proyecto: *{proyecto_elegido}*\n\n1️⃣ *Nuevo gasto*\n2️⃣ *Ver resumen*\n📸 Envía una *foto*")
        else:
            nombres_p = "\n".join([f"• {p}" for p in proyectos.keys()])
            msg.body(f"⚠️ Elige un proyecto de la lista:\n\n{nombres_p}")
        return str(resp)

    # Verificación de seguridad
    if not config_proyecto and step != "elegir_proyecto":
        msg.body("❌ Sesión expirada. Escribe *hola* para empezar de nuevo.")
        clear_state(sender)
        return str(resp)

    # ── 3. FOTO RECIBIDA ──
    if num_media > 0:
        media_url = request.form.get("MediaUrl0", "")
        nombre_p_actual = state.get("nombre_proyecto_actual") 
        msg.body(f"📸 Procesando foto para el proyecto: *{nombre_p_actual}*...")
        try:
            img_b64, mime = descargar_imagen(media_url)
            guardar_foto_pendiente({
                "quien":           nombre,
                "proyecto_nombre": nombre_p_actual,
                "imagen_b64":      img_b64,
                "mime_type":       mime
            }, config_proyecto)
            msg.body(f"✅ ¡Foto guardada en *{nombre_p_actual}*!\n\nEscribe *1* para un gasto manual o envía otra foto.")
        except Exception as e:
            msg.body(f"❌ Error al guardar la foto: {str(e)}")
        return str(resp)

    # ── 4. MENÚ PRINCIPAL ──
    if step == "menu":
        if msg_lower in ["1", "nuevo", "gasto"]:
            state["step"] = "descripcion"
            state["gasto"] = {}
            set_state(sender, state)
            msg.body("📝 ¿En qué gastaste? (Ej: Almuerzo)")
        elif msg_lower in ["2", "resumen"]:
            msg.body(obtener_resumen(config_proyecto["sheet_name"]))
        elif "procesar" in msg_lower:
            msg.body("⚙️ Ve a tu Google Sheet\nMenú *🧾 Boletas* → *Procesar fotos*")
        else:
            msg.body(f"📁 Proyecto: *{state.get('nombre_proyecto_actual')}*\n\n1️⃣ Nuevo gasto\n2️⃣ Resumen\n📸 Envía una foto")
        return str(resp)

    # ── 5. FLUJO GASTO MANUAL ──
    if step == "descripcion":
        gasto["descripcion"] = body
        state.update({"step": "categoria", "gasto": gasto})
        set_state(sender, state)
        msg.body("🏷️ *Categoría*\n\n" + "\n".join(CATEGORIAS))
        return str(resp)

    if step == "categoria":
        cat = MAP_CATEGORIA.get(msg_lower.replace(".", ""))
        if not cat:
            msg.body("⚠️ Elige una categoría válida (1-9)")
            return str(resp)
        gasto["categoria"] = cat
        state.update({"step": "metodo", "gasto": gasto})
        set_state(sender, state)
        msg.body("💳 *Método*\n\n" + "\n".join(METODOS))
        return str(resp)

    if step == "metodo":
        met = MAP_METODO.get(msg_lower.replace(".", ""))
        if not met:
            msg.body("⚠️ Elige un método válido (1-4)")
            return str(resp)
        gasto["metodo"] = met
        state.update({"step": "monto", "gasto": gasto})
        set_state(sender, state)
        msg.body("💰 ¿Cuánto fue? (Ej: 5000)")
        return str(resp)

    if step == "monto":
        monto_str = re.sub(r"[^\d.]", "", body)
        try:
            monto = float(monto_str)
            gasto["monto"] = monto
            gasto["quien"] = nombre
            
            # Recuperar el estado fresco para asegurar persistencia
            state = get_state(sender) 
            config_proyecto = state.get("config_proyecto")
            nombre_p = state.get("nombre_proyecto_actual")

            if not nombre_p or not config_proyecto:
                msg.body("❌ Sesión expirada. Escribe *hola* para reiniciar.")
                return str(resp)

            # Inyectar el nombre para que sheets.py lo use como 'proyecto'
            config_proyecto["nombre_proyecto_actual"] = nombre_p 

            guardar_gasto(gasto, config_proyecto)
            
            # Limpieza y retorno al menú
            state.update({"step": "menu", "gasto": {}})
            set_state(sender, state)
            msg.body(f"✅ *Gasto guardado en {nombre_p}*\n\n📝 {gasto['descripcion']}\n💰 {fmt(monto)}")
        except Exception as e:
            msg.body(f"❌ Error al guardar: {str(e)}\n\nEscribe *hola* para reiniciar.")
        return str(resp)

    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))