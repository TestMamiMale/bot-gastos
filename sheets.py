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

def obtener_resumen(sheet_name: str) -> str:
    try:
        r = requests.get(
            APPS_SCRIPT_URL,
            params={"action": "get_resumen", "sheet_name": sheet_name},
            timeout=15)
        data = r.json()
    except Exception as e:
        return f"❌ No pude obtener el resumen: {str(e)}"

    gastos = data.get("gastos", [])
    if not gastos:
        return (
            "📊 *Resumen de gastos*\n\n"
            "Aún no hay gastos registrados.\n\n"
            "Escribe *1* para registrar el primero 💪"
        )

    total     = data.get("total", 0)
    total_mes = 0
    count_mes = 0
    cats      = {}
    personas  = {}
    mes_actual = datetime.now().strftime("%m/%Y")

    for g in gastos:
        monto = float(g.get("monto") or 0)
        quien = g.get("quien", "Desconocido")
        cat   = g.get("categoria", "Otro")
        cats[cat]     = cats.get(cat, 0) + monto
        personas[quien] = personas.get(quien, 0) + monto
        fecha = str(g.get("fecha", ""))
        if fecha.endswith(mes_actual):
            total_mes += monto
            count_mes += 1

    cats_sorted     = sorted(cats.items(), key=lambda x: x[1], reverse=True)
    personas_sorted = sorted(personas.items(), key=lambda x: x[1], reverse=True)

    lineas_cats = [
        f"{cat}: ${int(m):,} ({m/total*100:.0f}%)".replace(",", ".")
        for cat, m in cats_sorted
    ]
    lineas_personas = [
        f"👤 {q}: ${int(m):,} ({m/total*100:.0f}%)".replace(",", ".")
        for q, m in personas_sorted
    ]

    pendientes = data.get("fotos_pendientes", 0)
    aviso_fotos = f"\n\n⏳ *{pendientes} foto(s) pendiente(s) de analizar*\nEscribe *procesar fotos* para analizarlas." if pendientes > 0 else ""

    return (
        f"📊 *Resumen de gastos*\n\n"
        f"📅 Este mes: *${int(total_mes):,}* ({count_mes} gastos)\n"
        f"📁 Total histórico: *${int(total):,}* ({len(gastos)} gastos)\n\n"
        f"*Por persona:*\n" +
        "\n".join(f"  {l}" for l in lineas_personas) +
        "\n\n*Por categoría:*\n" +
        "\n".join(f"  • {l}" for l in lineas_cats) +
        aviso_fotos +
        "\n\n_Escribe *1* para registrar otro gasto_"
    ).replace(",", ".")
