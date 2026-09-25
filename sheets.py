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

def obtener_config_usuario(telefono):
    """
    Busca al usuario por teléfono, obtiene sus proyectos y resuelve dinámicamente 
    las categorías y métodos de pago según el Tipo de Proyecto asociado.
    """
    sheet_config = cliente_gspread.open_by_key(SPREADSHEET_CONFIG_ID)
    
    # 1. Obtener datos de Usuarios
    hoja_usuarios = sheet_config.worksheet("Usuarios").get_all_records()
    u_found = next((u for u in hoja_usuarios if str(u.get("Telefono", "")).strip() in str(telefono).strip()), None)
    
    if not u_found:
        raise Exception("Usuario no registrado.")

    nombre_usuario = u_found.get("Nombre", "Usuario")
    proyectos_usuario = [p.strip() for p in str(u_found.get("Proyectos", "")).split(",") if p.strip()]

    # 2. Cargar mapa de Tipos de Proyecto (Tipo -> {Categorias, Metodos})
    hoja_tipos = sheet_config.worksheet("Tipos_Proyecto").get_all_records()
    mapa_tipos = {}
    for t in hoja_tipos:
        tipo_nombre = str(t.get("Tipo_Proyecto", "")).strip()
        raw_cats = str(t.get("Categorias", "")).strip()
        raw_mets = str(t.get("Metodos", "")).strip()

        mapa_tipos[tipo_nombre] = {
            "categorias": [c.strip() for c in raw_cats.split("\n") if c.strip()],
            "metodos": [m.strip() for m in raw_mets.split("\n") if m.strip()]
        }

    # 3. Cruzar Proyectos con sus Tipos de Proyecto
    hoja_proyectos = sheet_config.worksheet("Proyectos").get_all_records()
    diccionario_proyectos = {}

    for row in hoja_proyectos:
        nombre_p = str(row.get("Proyecto", "")).strip()
        if nombre_p in proyectos_usuario:
            tipo_p = str(row.get("Tipo_Proyecto", "")).strip()
            
            # Obtener esquemas según Tipo_Proyecto (o usar fallback genérico)
            esquema = mapa_tipos.get(tipo_p, {
                "categorias": ["1. 🍽️ Comida", "2. 🚌 Transporte", "3. Otro"],
                "metodos": ["1. 💳 Débito", "2. 💵 Efectivo"]
            })

            diccionario_proyectos[nombre_p] = {
                "sheet_id": row.get("Sheet_ID"),
                "tipo_proyecto": tipo_p,
                "categorias": esquema["categorias"],
                "metodos": esquema["metodos"]
            }

    return {
        "nombre": nombre_usuario,
        "proyectos": diccionario_proyectos
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