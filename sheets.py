import os
import requests
from datetime import datetime

APPS_SCRIPT_URL = os.environ.get("APPS_SCRIPT_URL")

def guardar_gasto(gasto: dict):
    payload = {
        "action":      "guardar_gasto",
        "descripcion": gasto.get("descripcion", ""),
        "categoria":   gasto.get("categoria", ""),
        "metodo":      gasto.get("metodo", ""),
        "monto":       float(gasto.get("monto", 0)),
        "quien":       gasto.get("quien", "")
    }
    r = requests.post(APPS_SCRIPT_URL, json=payload, timeout=15)
    if r.status_code not in (200, 201):
        raise Exception(f"Error al guardar: {r.status_code}")
    result = r.json()
    if not result.get("ok"):
        raise Exception(result.get("error", "Error desconocido"))

def guardar_foto_pendiente(data: dict):
    payload = {
        "action":      "guardar_foto",
        "quien":       data.get("quien", ""),
        "imagen_b64":  data.get("imagen_b64", ""),
        "mime_type":   data.get("mime_type", "image/jpeg")
    }
    r = requests.post(APPS_SCRIPT_URL, json=payload, timeout=30)
    if r.status_code not in (200, 201):
        raise Exception(f"Error al guardar foto: {r.status_code}")
    result = r.json()
    if not result.get("ok"):
        raise Exception(result.get("error", "Error desconocido"))

def obtener_resumen() -> str:
    try:
        r = requests.get(APPS_SCRIPT_URL, timeout=15)
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
