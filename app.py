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


def descargar_imagen_meta(media_id: str):
    """Obtiene la URL y descarga la imagen enviada por WhatsApp Meta Cloud API."""
    url_info = f"https://graph.facebook.com/v19.0/{media_id}"
    headers = {"Authorization": f"Bearer {META_TOKEN}"}
    
    res_info = requests.get(url_info, headers=headers, timeout=10)
    if res_info.status_code != 200:
        raise Exception(f"Error al obtener URL de imagen de Meta: {res_info.status_code}")
    
    media_data = res_info.json()
    download_url = media_data.get("url")
    mime_type = media_data.get("mime_type", "image/jpeg").split(";")[0]

    res_img = requests.get(download_url, headers=headers, timeout=15)
    if res_img.status_code != 200:
        raise Exception(f"Error al descargar imagen desde Meta: {res_img.status_code}")
        
    return base64.b64encode(res_img.content).decode("utf-8"), mime_type


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
    4. "metodo": el método de pago que mejor coincida de la lista 'Métodos de pago'. Si no se menciona, usa "Débito".

    Responde ÚNICAMENTE con un objeto JSON con las claves: "monto", "descripcion", "categoria", "metodo".
    """
    
    modelos_a_probar = ['gemini-2.5-flash', 'gemini-1.5-flash']
    
    for nombre_modelo in modelos_a_probar:
        try:
            model = genai.GenerativeModel(nombre_modelo)
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            print(f"[GEMINI SUCCESS]: Procesado con éxito usando {nombre_modelo}")
            return json.loads(response.text)
        except Exception as e:
            print(f"[GEMINI ERROR {nombre_modelo}]: {e}")
            continue

    # Fallback si la API no responde
    print("[GEMINI FALLBACK]: Extracción por Regex")
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
def procesar_mensaje(sender: str, body: str, media_b64: str = None, mime_type: str = None) -> str:
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
                    f"_Ejemplo: Almuerzo con equipo $18.500 débito comida_\n\n"
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
                f"_Ej: Pasajes de bus $5.000 efectivo transporte_\n\n"
                f"O responde *1* para Ver Resumen."
            )
        else:
            nombres_p = "\n".join([f"• {p}" for p in proyectos.keys()])
            return f"❌ Elige un proyecto válido de la lista:\n\n{nombres_p}"

    # Verificación de seguridad de sesión
    if not config_proyecto and step != "elegir_proyecto":
        clear_state(sender)
        return "⚠️ Sesión expirada. Escribe *hola* para empezar de nuevo."

    # 3. PROCESAMIENTO DE FOTO RECIBIDA (Meta o Twilio)
    if media_b64:
        nombre_p_actual = state.get("nombre_proyecto_actual")
        try:
            guardar_foto_pendiente({
                "quien":           nombre,
                "proyecto_nombre": nombre_p_actual,
                "imagen_b64":      media_b64,
                "mime_type":       mime_type or "image/jpeg"
            }, config_proyecto)

            # Restablecer estado al menú principal
            state.update({"step": "menu", "gasto": {}})
            set_state(sender, state)
            return f"✅ ¡Foto de respaldo guardada exitosamente en *{nombre_p_actual}*!\n\nPuedes enviar otro gasto en un solo mensaje cuando desees."
        except Exception as e:
            return f"❌ Error al guardar la foto: {str(e)}\nIntenta enviarla nuevamente."

    # 4. PASO DE ESPERA DE FOTO (Maneja el caso si el usuario escribe texto en lugar de enviar foto)
    if step == "esperando_foto" and not media_b64:
        if msg_lower in ["omitir", "saltar", "no", "despues", "después"]:
            state.update({"step": "menu", "gasto": {}})
            set_state(sender, state)
            return "👍 Entendido, el gasto quedó registrado sin foto. Escribe tu próximo gasto cuando gustes."
        else:
            return (
                "📸 Aún estoy esperando la **foto de la boleta o factura** para respaldar el gasto anterior.\n\n"
                "Por favor envíala como imagen o escribe *omitir* para continuar sin foto."
            )

    # 5. PASO DE CONFIRMACIÓN DEL GASTO DETECTADO
    if step == "esperando_confirmacion":
        if msg_lower in ["si", "sí", "s", "correcto", "ok", "guardar"]:
            nombre_p = state.get("nombre_proyecto_actual")
            config_proyecto["nombre_proyecto_actual"] = nombre_p
            gasto["quien"] = nombre
            
            try:
                guardar_gasto(gasto, config_proyecto)
                state.update({"step": "esperando_foto"})
                set_state(sender, state)
                return (
                    f"✅ *Gasto registrado en {nombre_p}*\n\n"
                    f"📸 Ahora, por favor envía la **foto de la boleta o factura** para adjuntarla como respaldo del gasto (o escribe *omitir*)."
                )
            except Exception as e:
                return f"❌ Error al guardar en la hoja: {str(e)}\nEscribe *hola* para reiniciar."
        else:
            state.update({"step": "menu", "gasto": {}})
            set_state(sender, state)
            return "🔄 Registro cancelado. Ingresa los datos del gasto nuevamente en un solo mensaje."

   # 6. MENÚ O ENTRADA DIRECTA DEL GASTO (ONE-SHOT PARSER)
    if msg_lower in ["1", "resumen"]:
        return obtener_resumen(sender)

    if msg_lower in ["2", "cambiar proyecto", "proyectos"]:
        set_state(sender, {"step": "elegir_proyecto", "nombre": nombre, "proyectos": proyectos})
        nombres_p = "\n".join([f"• {p}" for p in proyectos.keys()])
        return f"¿A qué proyecto deseas cambiarte?\n\n{nombres_p}"

    # === [FILTRO DE SEGURIDAD PARA AHORRAR TOKENS DE GEMINI] ===
    # Si el mensaje viene vacío o tiene menos de 2 caracteres (pings/peticiones vacías),
    # NO llamamos a Gemini y respondemos directo con el menú básico.
    if not body or len(body.strip()) < 2:
        return (
            f"📌 Proyecto actual: *{state.get('nombre_proyecto_actual')}*\n\n"
            f"📝 *Para rendir un gasto*, escribe el detalle en un solo mensaje:\n"
            f"_Ej: Almuerzo $15.000 débito_\n\n"
            f"O responde:\n"
            f"1. *Ver resumen*\n"
            f"2. *Cambiar proyecto*"
        )
    # ============================================================

    # Procesar cualquier texto descriptivo válido como un nuevo gasto usando Gemini
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
            media_b64 = None
            mime_type = None

            if msg_type == "text":
                body = msg_obj.get("text", {}).get("body", "")
            elif msg_type == "image":
                image_info = msg_obj.get("image", {})
                media_id = image_info.get("id")
                body = image_info.get("caption", "")
                if media_id:
                    try:
                        media_b64, mime_type = descargar_imagen_meta(media_id)
                    except Exception as e:
                        print(f"[META IMAGE DOWNLOAD ERROR]: {e}")

            # Procesa la lógica y responde
            texto_respuesta = procesar_mensaje(sender, body, media_b64=media_b64, mime_type=mime_type)
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

    media_b64 = None
    mime_type = None

    if num_media > 0 and media_url:
        try:
            media_b64, mime_type = descargar_imagen_twilio(media_url)
        except Exception as e:
            print(f"[TWILIO MEDIA ERROR]: {e}")

    resp = MessagingResponse()
    texto_respuesta = procesar_mensaje(sender, body, media_b64=media_b64, mime_type=mime_type)
    resp.message().body(texto_respuesta)

    return str(resp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
