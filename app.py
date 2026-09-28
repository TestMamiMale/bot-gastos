import os
import re
import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from sheets import guardar_gasto, obtener_resumen, guardar_foto_pendiente, obtener_config_usuario
from state import get_state, set_state, clear_state

load_dotenv()

app = Flask(__name__)

# Credenciales de Twilio (Entorno de Pruebas)
TWILIO_SID   = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")

# Credenciales de Meta Cloud API (Entorno de Producción)
META_TOKEN   = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUM_ID = os.environ.get("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")

def fmt(monto):
    return f"${int(monto):,}".replace(",", ".")

def enviar_mensaje_meta(to_number: str, texto: str):
    """Envía un mensaje de respuesta a través de Meta Cloud API."""
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUM_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {"body": texto}
    }
    r = requests.post(url, json=payload, headers=headers, timeout=10)
    
    # IMPRIME LA RESPUESTA DE META EN LOS LOGS DE RENDER
    print(f"[META OUTGOING]: {r.status_code} - {r.text}")
    
    return r.json()

def descargar_imagen_twilio(url):
    """Descarga imagen desde Twilio con autenticación HTTP Basic."""
    r = requests.get(url, auth=(TWILIO_SID, TWILIO_TOKEN), timeout=15)
    if r.status_code != 200:
        raise Exception(f"No se pudo descargar la imagen de Twilio: {r.status_code}")
    content_type = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
    import base64
    return base64.b64encode(r.content).decode("utf-8"), content_type

def obtener_opcion_dinamica(entrada_usuario: str, lista_opciones: list) -> str:
    """Busca coincidencia entre la opción ingresada ('1', '1.') y la lista de opciones."""
    num_limpio = entrada_usuario.replace(".", "").strip()
    
    for opcion in lista_opciones:
        if opcion.startswith(f"{num_limpio}.") or opcion.startswith(f"{num_limpio} "):
            return opcion
            
    if num_limpio.isdigit():
        idx = int(num_limpio) - 1
        if 0 <= idx < len(lista_opciones):
            return lista_opciones[idx]
            
    return None

# ==============================================================================
# LÓGICA DE NEGOCIO PRINCIPAL (Compartida por Meta y Twilio)
# ==============================================================================
def procesar_mensaje(sender: str, body: str, num_media: int = 0, media_url: str = None) -> str:
    """Procesa la conversación y retorna el texto de respuesta del bot."""
    msg_lower = body.lower().strip()

    state           = get_state(sender)
    step            = state.get("step")
    nombre          = state.get("nombre")
    gasto           = state.get("gasto", {})
    proyectos       = state.get("proyectos", {})
    config_proyecto = state.get("config_proyecto", {})

    # Comando global de reinicio
    if msg_lower in ["cancelar", "cancel", "salir", "hola", "inicio", "menu"]:
        clear_state(sender)
        step = None 
        nombre = None

    # 1. VALIDACIÓN DE USUARIO Y SELECCIÓN DE PROYECTO
    if not nombre:
        try:
            config_usuario = obtener_config_usuario(sender)
            nombre = config_usuario.get("nombre")
            proyectos = config_usuario.get("proyectos", {})

            if not proyectos:
                clear_state(sender)
                return "❌ No tienes proyectos asignados. Contacta al administrador."

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
                return f"¡Hola {nombre}! 👋\nEstás en el proyecto *{nombre_p}*.\n\n1. *Nuevo gasto*\n2. *Ver resumen*\n📸 Envía una foto"
            else:
                set_state(sender, {"step": "elegir_proyecto", "nombre": nombre, "proyectos": proyectos})
                nombres_p = "\n".join([f"• {p}" for p in lista_proyectos])
                return f"¡Hola {nombre}! 👋\n\n¿En qué proyecto quieres trabajar?\n\n{nombres_p}"
        except Exception as e:
            clear_state(sender)
            return f"❌ Error de acceso: {e}"

    # 2. SELECCIÓN DE PROYECTO
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
            return f"📌 Proyecto: *{proyecto_elegido}*\n\n1. *Nuevo gasto*\n2. *Ver resumen*\n📸 Envía una foto"
        else:
            nombres_p = "\n".join([f"• {p}" for p in proyectos.keys()])
            return f"❌ Elige un proyecto de la lista:\n\n{nombres_p}"

    # Verificación de seguridad
    if not config_proyecto and step != "elegir_proyecto":
        clear_state(sender)
        return "⚠️ Sesión expirada. Escribe *hola* para empezar de nuevo."

    # 3. FOTO RECIBIDA (Vía Twilio)
    if num_media > 0 and media_url:
        nombre_p_actual = state.get("nombre_proyecto_actual") 
        try:
            img_b64, mime = descargar_imagen_twilio(media_url)
            guardar_foto_pendiente({
                "quien":           nombre,
                "proyecto_nombre": nombre_p_actual,
                "imagen_b64":      img_b64,
                "mime_type":       mime
            }, config_proyecto)
            return f"✅ ¡Foto guardada en *{nombre_p_actual}*!\n\nEscribe *1* para un gasto manual o envía otra foto."
        except Exception as e:
            return f"❌ Error al guardar la foto: {str(e)}"

    # 4. MENÚ PRINCIPAL
    if step == "menu":
        if msg_lower in ["1", "nuevo", "gasto"]:
            state["step"] = "descripcion"
            state["gasto"] = {}
            set_state(sender, state)
            return "✏️ ¿En qué gastaste? (Ej: Almuerzo de trabajo)"
        elif msg_lower in ["2", "resumen"]:
            return obtener_resumen(sender)
        else:
            return f"📌 Proyecto: *{state.get('nombre_proyecto_actual')}*\n\n1. Nuevo gasto\n2. Resumen\n📸 Envía una foto"

    # 5. FLUJO GASTO MANUAL DINÁMICO
    if step == "descripcion":
        gasto["descripcion"] = body
        state.update({"step": "categoria", "gasto": gasto})
        set_state(sender, state)
        
        categorias = config_proyecto.get("categorias", [])
        if not categorias:
            categorias = ["1. 🍽️ Comida", "2. 🚌 Transporte", "3. 📦 Otro"]

        return "🏷️ *Selecciona una categoría:*\n\n" + "\n".join(categorias)

    if step == "categoria":
        categorias = config_proyecto.get("categorias", [])
        cat_seleccionada = obtener_opcion_dinamica(msg_lower, categorias)
        
        if not cat_seleccionada:
            return f"❌ Elige una opción válida (1 al {len(categorias)})"

        gasto["categoria"] = cat_seleccionada
        state.update({"step": "metodo", "gasto": gasto})
        set_state(sender, state)

        metodos = config_proyecto.get("metodos", [])
        if not metodos:
            metodos = ["1. 💳 Débito", "2. 💵 Efectivo"]

        return "💳 *Selecciona el método de pago:*\n\n" + "\n".join(metodos)

    if step == "metodo":
        metodos = config_proyecto.get("metodos", [])
        met_seleccionado = obtener_opcion_dinamica(msg_lower, metodos)

        if not met_seleccionado:
            return f"❌ Elige una opción válida (1 al {len(metodos)})"

        gasto["metodo"] = met_seleccionado
        state.update({"step": "monto", "gasto": gasto})
        set_state(sender, state)
        return "💵 ¿Cuánto fue? (Ej: 5000)"

    if step == "monto":
        monto_str = re.sub(r"[^\d.]", "", body)
        try:
            monto = float(monto_str)
            gasto["monto"] = monto
            gasto["quien"] = nombre
            
            nombre_p = state.get("nombre_proyecto_actual")

            if not nombre_p or not config_proyecto:
                return "⚠️ Sesión expirada. Escribe *hola* para reiniciar."

            config_proyecto["nombre_proyecto_actual"] = nombre_p 
            guardar_gasto(gasto, config_proyecto)
            
            state.update({"step": "menu", "gasto": {}})
            set_state(sender, state)
            return f"✅ *Gasto guardado en {nombre_p}*\n\n📝 {gasto['descripcion']}\n🏷️ {gasto['categoria']}\n💳 {gasto['metodo']}\n💰 {fmt(monto)}"
        except Exception as e:
            return f"❌ Error al guardar: {str(e)}\n\nEscribe *hola* para reiniciar."

    return "Escribe *hola* para iniciar."


# ==============================================================================
# ENDPOINT 1: META CLOUD API (PRODUCCIÓN - Chip Prepago)
# URL Webhook: https://bot-gastos-moy7.onrender.com/webhook/meta
# ==============================================================================
@app.route("/webhook/meta", methods=["GET", "POST"])
def webhook_meta():
    # 1. Validación de Token GET requerida por Meta Developers
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("[META] ¡Webhook de Meta verificado con éxito!")
            return challenge, 200
        return "Token de verificación inválido", 403

    # 2. Recepción de mensajes POST desde Meta Cloud API
    data = request.get_json()
    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if messages:
            msg_obj = messages[0]
            sender = msg_obj.get("from")
            msg_type = msg_obj.get("type")

            body = ""
            if msg_type == "text":
                body = msg_obj.get("text", {}).get("body", "")

            # Procesa mediante la lógica unificada y responde a través de la API de Meta
            texto_respuesta = procesar_mensaje(sender, body)
            enviar_mensaje_meta(sender, texto_respuesta)

    except Exception as e:
        print(f"[META ERROR] Fallo al procesar mensaje: {e}")

    return jsonify({"status": "ok"}), 200


# ==============================================================================
# ENDPOINT 2: TWILIO SANDBOX (ENTORNO DE PRUEBAS)
# URL Webhook: https://bot-gastos-moy7.onrender.com/webhook
# ==============================================================================
@app.route("/webhook", methods=["GET", "POST"])
def webhook_twilio():
    if request.method == "GET":
        return "Bot de Gastos activo 🚀", 200

    sender    = request.form.get("From", "")
    body      = request.form.get("Body", "").strip()
    num_media = int(request.form.get("NumMedia", 0))
    media_url = request.form.get("MediaUrl0", "")

    resp = MessagingResponse()
    
    # Procesa mediante la lógica unificada y responde a través de TwiML
    texto_respuesta = procesar_mensaje(sender, body, num_media, media_url)
    resp.message().body(texto_respuesta)

    return str(resp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))