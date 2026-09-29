import os
import re
import json
import base64
import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
import google.generativeai as genai

from sheets import guardar_gasto, obtener_resumen, guardar_foto_pendiente, obtener_config_usuario
from state import get_state, set_state, clear_state

load_dotenv()

app = Flask(__name__)

# Configuración de Gemini API
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Credenciales de Twilio (Entorno de Pruebas)
TWILIO_SID   = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")

# Credenciales de Meta Cloud API (Entorno de Producción)
META_TOKEN   = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUM_ID = os.environ.get("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")


def fmt(monto):
    """Formatea el monto en pesos chilenos."""
    try:
        return f"${int(float(monto)):,}".replace(",", ".")
    except Exception:
        return f"${monto}"


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
    r = requests.post(url, json=payload, headers=headers, timeout=15)
    print(f"[META OUTGOING]: {r.status_code} - {r.text}")
    return r.json()


def descargar_imagen_twilio(url):
    """Descarga imagen desde Twilio con autenticación HTTP Basic."""
    r = requests.get(url, auth=(TWILIO_SID, TWILIO_TOKEN), timeout=15)
    if r.status_code != 200:
        raise Exception(f"No se pudo descargar la imagen de Twilio: {r.status_code}")
    content_type = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
    return base64.b64encode(r.content).decode("utf-8"), content_type


def extraer_gasto_con_gemini(texto_usuario: str, categorias_validas: list, metodos_validos: list) -> dict:
    """Extrae de una sola pasada los datos del gasto usando Gemini API."""
    prompt = f"""
    Eres un asistente contable para la rendición de gastos de proyectos.
    Analiza el siguiente texto ingresado por el usuario y extrae la información en formato JSON estricto.

    Mensaje del usuario: "{texto_usuario}"
    Categorías disponibles en el proyecto: {json.dumps(categorias_validas, ensure_ascii=False)}
    Métodos de pago disponibles: {json.dumps(metodos_validos, ensure_ascii=False)}

    Instrucciones:
    1. "monto": número (entero o flotante). Elimina puntos de miles o signos de moneda. Si no se detecta, retorna 0.
    2. "descripcion": breve resumen del gasto realizado.
    3. "categoria": la opción de 'Categorías disponibles' que mejor coincida con el gasto.
    4. "metodo": el método de pago que mejor coincida de la lista 'Métodos de pago'. Si no se menciona, usa la primera opción o "Débito".

    Responde ÚNICAMENTE con un objeto JSON con las claves: "monto", "descripcion", "categoria", "metodo".
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"[GEMINI ERROR]: {e}")
        # Extracción básica de respaldo en caso de falla de la API
        monto_match = re.search(r'\$?(\d+[\d\.]*)', texto_usuario)
        monto_val = float(monto_match.group(1).replace(".", "")) if monto_match else 0
        return {
            "monto": monto_val,
            "descripcion": texto_usuario,
            "categoria": categorias_validas[0] if categorias_validas else "Gastos Varios",
            "metodo": metodos_validos[0] if metodos_validos else "Débito"
        }


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

    # Comando global de reinicio / cancelación
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
                return (
                    f"¡Hola {nombre}! 👋\n"
                    f"Estás en el proyecto *{nombre_p}*.\n\n"
                    f"📝 *Para rendir un gasto*, escribe los datos en un solo mensaje:\n"
                    f"_Ejemplo: Almuerzo con equipo $18.500 con débito_\n\n"
                    f"O responde:\n"
                    f"1. *Ver resumen*\n"
                    f"2. *Cambiar proyecto*"
                )
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
            return (
                f"📌 Proyecto seleccionado: *{proyecto_elegido}*\n\n"
                f"📝 Escribe los datos del gasto en un solo mensaje para procesarlo.\n"
                f"_Ej: Pasajes de bus $5.000 efectivo_\n\n"
                f"O responde *1* para Ver Resumen."
            )
        else:
            nombres_p = "\n".join([f"• {p}" for p in proyectos.keys()])
            return f"❌ Elige un proyecto válido de la lista:\n\n{nombres_p}"

    # Verificación de seguridad de sesión
    if not config_proyecto and step != "elegir_proyecto":
        clear_state(sender)
        return "⚠️ Sesión expirada. Escribe *hola* para empezar de nuevo."

    # 3. PROCESAMIENTO DE FOTO ADJUNTA (Paso final de respaldo)
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

            # Si había un gasto guardado previo en confirmación, finaliza el ciclo
            state.update({"step": "menu", "gasto": {}})
            set_state(sender, state)
            return f"✅ ¡Foto de respaldo guardada exitosamente en *{nombre_p_actual}*!\n\nPuedes enviar otro gasto en un solo mensaje cuando desees."
        except Exception as e:
            return f"❌ Error al guardar la foto: {str(e)}\nIntenta enviarla nuevamente."

    # 4. PASO DE CONFIRMACIÓN DEL GASTO DETECTADO
    if step == "esperando_confirmacion":
        if msg_lower in ["si", "sí", "s", "correcto", "ok", "guardar"]:
            # Registrar el gasto en Google Sheets
            nombre_p = state.get("nombre_proyecto_actual")
            config_proyecto["nombre_proyecto_actual"] = nombre_p
            gasto["quien"] = nombre
            
            try:
                guardar_gasto(gasto, config_proyecto)
                state.update({"step": "esperando_foto"})
                set_state(sender, state)
                return (
                    f"✅ *Gasto registrado en {nombre_p}*\n\n"
                    f"📸 Ahora, por favor envía la **foto de la boleta o factura** para adjuntarla como respaldo del gasto."
                )
            except Exception as e:
                return f"❌ Error al guardar en la hoja: {str(e)}\nEscribe *hola* para reiniciar."
        else:
            state.update({"step": "menu", "gasto": {}})
            set_state(sender, state)
            return "🔄 Registro cancelado. Ingresa los datos del gasto nuevamente en un solo mensaje."

    # 5. MENÚ O ENTRADA DIRECTA DEL GASTO (ONE-SHOT PARSER)
    if msg_lower in ["1", "resumen"]:
        return obtener_resumen(sender)

    if msg_lower in ["2", "cambiar proyecto", "proyectos"]:
        set_state(sender, {"step": "elegir_proyecto", "nombre": nombre, "proyectos": proyectos})
        nombres_p = "\n".join([f"• {p}" for p in proyectos.keys()])
        return f"¿A qué proyecto deseas cambiarte?\n\n{nombres_p}"

    # Procesar cualquier texto descriptivo como un nuevo gasto usando Gemini
    categorias = config_proyecto.get("categorias", ["Alimentación", "Transporte", "Operación", "Otros"])
    metodos    = config_proyecto.get("metodos", ["Débito", "Efectivo", "Transferencia", "Factura"])

    datos = extraer_gasto_con_gemini(body, categorias, metodos)

    if not datos.get("monto") or float(datos.get("monto", 0)) <= 0:
        return (
            "⚠️ No pude detectar el monto del gasto.\n\n"
            "Por favor escribe el detalle con el monto explícito.\n"
            "_Ejemplo: Almuerzo $12.500 débito_"
        )

    # Actualizar estado a confirmación
    state.update({
        "step": "esperando_confirmacion",
        "gasto": datos
    })
    set_state(sender, state)

    return (
        f"📝 *Confirma los datos del gasto:*\n\n"
        f"• **Proyecto:** {state.get('nombre_proyecto_actual')}\n"
        f"• **Detalle:** {datos.get('descripcion')}\n"
        f"• **Monto:** {fmt(datos.get('monto'))}\n"
        f"• **Categoría:** {datos.get('categoria')}\n"
        f"• **Método:** {datos.get('metodo')}\n\n"
        f"¿Está correcto? Responde **SÍ** para guardar o escribe **cancelar**."
    )


# ==============================================================================
# ENDPOINT 1: META CLOUD API (PRODUCCIÓN - Chip Prepago)
# URL Webhook: https://bot-gastos-moy7.onrender.com/webhook/meta
# ==============================================================================
@app.route("/webhook/meta", methods=["GET", "POST"])
def webhook_meta():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("[META] Webhook de Meta verificado con éxito!")
            return challenge, 200
        return "Token de verificación inválido", 403

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

            # Procesa la lógica y responde a través de la API de Meta
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
    
    texto_respuesta = procesar_mensaje(sender, body, num_media, media_url)
    resp.message().body(texto_respuesta)

    return str(resp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))