import os
import re
import requests
from dotenv import load_dotenv
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from sheets import guardar_gasto, obtener_resumen, guardar_foto_pendiente, obtener_config_usuario
from state import get_state, set_state, clear_state

load_dotenv()

app = Flask(__name__)

TWILIO_SID   = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")

def fmt(monto):
    return f"${int(monto):,}".replace(",", ".")

def descargar_imagen(url):
    """Descarga imagen desde Twilio con autenticación."""
    r = requests.get(url, auth=(TWILIO_SID, TWILIO_TOKEN), timeout=15)
    if r.status_code != 200:
        raise Exception(f"No se pudo descargar la imagen: {r.status_code}")
    content_type = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
    import base64
    return base64.b64encode(r.content).decode("utf-8"), content_type

def obtener_opcion_dinamica(entrada_usuario: str, lista_opciones: list) -> str:
    """
    Busca coincidencia entre la opción que escribe el usuario ('1', '1.', '2')
    y el elemento de la lista (ej: '1. 🍽️ Comida').
    """
    num_limpio = entrada_usuario.replace(".", "").strip()
    
    # Busca por prefijo "1." o "1 "
    for opcion in lista_opciones:
        if opcion.startswith(f"{num_limpio}.") or opcion.startswith(f"{num_limpio} "):
            return opcion
            
    # Si ingresa el número ordinal directo
    if num_limpio.isdigit():
        idx = int(num_limpio) - 1
        if 0 <= idx < len(lista_opciones):
            return lista_opciones[idx]
            
    return None

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "Bot de Gastos activo 🚀", 200

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
    config_proyecto = state.get("config_proyecto", {})

    # Comando global cancelar o reinicio
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
                msg.body(f"¡Hola {nombre}! 👋\nEstás en el proyecto *{nombre_p}*.\n\n1. *Nuevo gasto*\n2. *Ver resumen*\n📸 Envía una foto")
            else:
                set_state(sender, {"step": "elegir_proyecto", "nombre": nombre, "proyectos": proyectos})
                nombres_p = "\n".join([f"• {p}" for p in lista_proyectos])
                msg.body(f"¡Hola {nombre}! 👋\n\n¿En qué proyecto quieres trabajar?\n\n{nombres_p}")
            return str(resp)
        except Exception as e:
            clear_state(sender)
            msg.body(f"❌ Error de acceso: {e}")
            return str(resp)

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
            msg.body(f"📌 Proyecto: *{proyecto_elegido}*\n\n1. *Nuevo gasto*\n2. *Ver resumen*\n📸 Envía una foto")
        else:
            nombres_p = "\n".join([f"• {p}" for p in proyectos.keys()])
            msg.body(f"❌ Elige un proyecto de la lista:\n\n{nombres_p}")
        return str(resp)

    # Verificación de seguridad
    if not config_proyecto and step != "elegir_proyecto":
        msg.body("⚠️ Sesión expirada. Escribe *hola* para empezar de nuevo.")
        clear_state(sender)
        return str(resp)

    # 3. FOTO RECIBIDA 
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

    # 4. MENÚ PRINCIPAL 
    if step == "menu":
        if msg_lower in ["1", "nuevo", "gasto"]:
            state["step"] = "descripcion"
            state["gasto"] = {}
            set_state(sender, state)
            msg.body("✏️ ¿En qué gastaste? (Ej: Almuerzo de trabajo)")
        elif msg_lower in ["2", "resumen"]:
            msg.body(obtener_resumen(sender))
        elif "procesar" in msg_lower:
            msg.body("📲 Ve a tu Google Sheet\nMenú *Boletas* ➡️ *Procesar fotos*")
        else:
            msg.body(f"📌 Proyecto: *{state.get('nombre_proyecto_actual')}*\n\n1. Nuevo gasto\n2. Resumen\n📸 Envía una foto")
        return str(resp)

    # 5. FLUJO GASTO MANUAL DINÁMICO 
    if step == "descripcion":
        gasto["descripcion"] = body
        state.update({"step": "categoria", "gasto": gasto})
        set_state(sender, state)
        
        categorias = config_proyecto.get("categorias", [])
        if not categorias:
            categorias = ["1. 🍽️ Comida", "2. 🚌 Transporte", "3. 📦 Otro"]

        msg.body("🏷️ *Selecciona una categoría:*\n\n" + "\n".join(categorias))
        return str(resp)

    if step == "categoria":
        categorias = config_proyecto.get("categorias", [])
        cat_seleccionada = obtener_opcion_dinamica(msg_lower, categorias)
        
        if not cat_seleccionada:
            msg.body(f"❌ Elige una opción válida (1 al {len(categorias)})")
            return str(resp)

        gasto["categoria"] = cat_seleccionada
        state.update({"step": "metodo", "gasto": gasto})
        set_state(sender, state)

        metodos = config_proyecto.get("metodos", [])
        if not metodos:
            metodos = ["1. 💳 Débito", "2. 💵 Efectivo"]

        msg.body("💳 *Selecciona el método de pago:*\n\n" + "\n".join(metodos))
        return str(resp)

    if step == "metodo":
        metodos = config_proyecto.get("metodos", [])
        met_seleccionado = obtener_opcion_dinamica(msg_lower, metodos)

        if not met_seleccionado:
            msg.body(f"❌ Elige una opción válida (1 al {len(metodos)})")
            return str(resp)

        gasto["metodo"] = met_seleccionado
        state.update({"step": "monto", "gasto": gasto})
        set_state(sender, state)
        msg.body("💵 ¿Cuánto fue? (Ej: 5000)")
        return str(resp)

    if step == "monto":
        monto_str = re.sub(r"[^\d.]", "", body)
        try:
            monto = float(monto_str)
            gasto["monto"] = monto
            gasto["quien"] = nombre
            
            nombre_p = state.get("nombre_proyecto_actual")

            if not nombre_p or not config_proyecto:
                msg.body("⚠️ Sesión expirada. Escribe *hola* para reiniciar.")
                return str(resp)

            config_proyecto["nombre_proyecto_actual"] = nombre_p 

            guardar_gasto(gasto, config_proyecto)
            
            state.update({"step": "menu", "gasto": {}})
            set_state(sender, state)
            msg.body(f"✅ *Gasto guardado en {nombre_p}*\n\n📝 {gasto['descripcion']}\n🏷️ {gasto['categoria']}\n💳 {gasto['metodo']}\n💰 {fmt(monto)}")
        except Exception as e:
            msg.body(f"❌ Error al guardar: {str(e)}\n\nEscribe *hola* para reiniciar.")
        return str(resp)

    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))