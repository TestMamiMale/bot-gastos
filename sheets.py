import os
import requests

APPS_SCRIPT_URL = os.environ.get("APPS_SCRIPT_URL")

def _post(payload: dict, timeout: int = 30) -> dict:
    """Helper para enviar peticiones POST a Google Apps Script."""
    if not APPS_SCRIPT_URL:
        raise Exception("APPS_SCRIPT_URL no está configurada en las variables de entorno.")
    r = requests.post(APPS_SCRIPT_URL, json=payload, timeout=timeout)
    if r.status_code not in (200, 201):
        raise Exception(f"Error al llamar a Apps Script: {r.status_code}")
    result = r.json()
    if not result.get("ok"):
        raise Exception(result.get("error", "Error desconocido desde Apps Script"))
    return result

def obtener_config_usuario(telefono: str) -> dict:
    """
    Solicita la configuración del usuario y sus proyectos asociados a Google Apps Script.
    Apps Script realiza el cruce: Usuario -> Proyectos -> Tipos_Proyecto (Categorías y Métodos).
    """
    try:
        r = requests.get(
            APPS_SCRIPT_URL,
            params={"action": "obtener_config", "telefono": telefono},
            timeout=15
        )
        if r.status_code not in (200, 201):
            raise Exception(f"Error de conexión con Apps Script: HTTP {r.status_code}")
        
        data = r.json()
        if not data.get("ok"):
            raise Exception(data.get("error", "Usuario no registrado en la hoja de configuración."))
        
        return {
            "nombre": data.get("nombre"),
            "proyectos": data.get("proyectos", {})
        }
    except Exception as e:
        raise Exception(f"Error al obtener configuración de usuario: {str(e)}")

def guardar_gasto(gasto: dict, config_proyecto: dict):
    if not config_proyecto:
        raise Exception("Configuración de proyecto no encontrada.")

    payload = {
        "action":      "guardar_gasto",
        "proyecto":    config_proyecto.get("nombre_proyecto_actual"),
        "descripcion": gasto.get("descripcion", ""),
        "categoria":   gasto.get("categoria", ""),
        "metodo":      gasto.get("metodo", ""),
        "monto":       float(gasto.get("monto", 0)),
        "quien":       gasto.get("quien", "")
    }
    return _post(payload, timeout=15)

def guardar_foto_pendiente(data: dict, config_proyecto: dict):
    if not config_proyecto:
        raise Exception("Sesión de proyecto perdida. Escribe *hola*.")

    payload = {
        "action":     "guardar_foto",
        "proyecto":   data.get("proyecto_nombre"),
        "quien":      data.get("quien", ""),
        "imagen_b64": data.get("imagen_b64", ""),
        "mime_type":  data.get("mime_type", "image/jpeg")
    }
    return _post(payload, timeout=30)

def obtener_resumen(telefono: str) -> str:
    """Solicita el resumen procesado directamente a Google Apps Script"""
    try:
        r = requests.get(
            APPS_SCRIPT_URL,
            params={"action": "get_resumen", "telefono": telefono},
            timeout=20
        ) 
        data = r.json()
        
        if data.get("ok"):
            return data.get("resumen")
        else:
            return f"❌ Error: {data.get('error', 'No se pudo obtener el resumen')}"
            
    except Exception as e:
        return f"❌ No pude conectar con el servidor: {str(e)}"