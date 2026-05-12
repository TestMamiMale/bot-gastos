import os
import requests
from datetime import datetime

APPS_SCRIPT_URL = os.environ.get("APPS_SCRIPT_URL")

def _post(payload: dict, timeout: int = 30) -> dict:
    """Función helper para enviar datos a Google Apps Script."""
    r = requests.post(APPS_SCRIPT_URL, json=payload, timeout=timeout)
    if r.status_code not in (200, 201):
        raise Exception(f"Error al llamar a Apps Script: {r.status_code}")
    result = r.json()
    if not result.get("ok"):
        raise Exception(result.get("error", "Error desconocido desde Apps Script"))
    return result

def obtener_config_usuario(telefono: str) -> dict:
    """Solicita la configuración dinámica al Apps Script"""
    # Usamos la acción 'obtener_config' que acabamos de crear en el JS
    result = _post({"action": "obtener_config", "telefono": telefono})
    return {
        "nombre":    result.get("nombre", ""),
        "proyectos": result.get("proyectos", {})
    }

# sheets.py

def guardar_gasto(gasto: dict, config_proyecto: dict):
    if not config_proyecto:
        raise Exception("Configuración de proyecto no encontrada.")

    payload = {
        "action":      "guardar_gasto",
        "proyecto":    config_proyecto.get("nombre_proyecto_actual"), # Clave EXACTA para el JS
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
        "proyecto":   data.get("proyecto_nombre"), # Clave vinculada al PROYECTOS_CONFIG del JS 
        "quien":      data.get("quien", ""),
        "imagen_b64": data.get("imagen_b64", ""),
        "mime_type":  data.get("mime_type", "image/jpeg")
    }
    return _post(payload, timeout=30)

def obtener_resumen(telefono: str) -> str:
    """Solicita el resumen procesado directamente a Google Apps Script"""
    try:
        # IMPORTANTE: Cambiamos 'sheet_name' por 'telefono' para que Google sepa quién eres 
        r = requests.get(
            APPS_SCRIPT_URL,
            params={"action": "get_resumen", "telefono": telefono},
            timeout=20) 
        data = r.json()
        
        if data.get("ok"):
            # Google Apps Script ya entrega el texto armado en el campo 'resumen' 
            return data.get("resumen")
        else:
            return f"❌ Error: {data.get('error', 'No se pudo obtener el resumen')}"
            
    except Exception as e:
        return f"❌ No pude conectar con el servidor: {str(e)}"