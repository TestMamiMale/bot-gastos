// ============================================================
// APPS SCRIPT — Bot Gastos consolidado y corregido
// ============================================================

var GEMINI_API_KEY  = "AIzaSyAo6AYtTeQ2_B5P_-ZHjhc_wqXnOUtcn6s"; 

// IDs de Drive
var CONFIG_SHEET_ID = "1XR3LMN3fYfWM7LHDizUbgJ0AFfnUX9uruRSblwOxc0w";

var PROYECTOS_CONFIG = {
  "Personal": {
    carpeta:   "1IjhCG_jjosLt-hD9eKsFXMTmv6nGq02C",
    imagenes:  "1Zffh2FYq2uRI6gV9Z47b2KV1lwkHHw-a"
  },
  "Rendicion_1": {
    carpeta:   "1yJTZmQI4yol16iHTN-SXcinqjbKyap48",
    imagenes:  "1uKo6M9hYB8SjhSpn1hD4gNP56sWxu24o"
  }
};

// ── Routing ─────────────────────────────────────────────────
function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var action = data.action;

    if (action === "guardar_foto") return guardarFoto(data);
    if (action === "guardar_gasto") return guardarGasto(data);
    if (action === "obtener_config") return jsonResp(getUsuarioConfig(data.telefono));

    return jsonResp({ ok: false, error: "Acción no reconocida: " + action });
  } catch (err) {
    return jsonResp({ ok: false, error: err.toString() });
  }
}

function doGet(e) {
  try {
    var action = (e.parameter && e.parameter.action);
    if (action === "obtener_config") return jsonResp(getUsuarioConfig(e.parameter.telefono));
    if (action === "get_resumen") return getResumen(e.parameter.telefono);
    return jsonResp({ ok: false, error: "Acción GET no reconocida" });
  } catch (err) {
    return jsonResp({ ok: false, error: err.toString() });
  }
}

// ── Obtener Configuración (Para que Python no reciba undefined) ──
function getUsuarioConfig(telefono) {
  var ss = SpreadsheetApp.openById(CONFIG_SHEET_ID);
  var ws = ss.getSheetByName("Usuarios");
  if (!ws) return { ok: false, error: "Hoja Usuarios no encontrada" };

  var rows = ws.getDataRange().getValues();
  var telBusca = limpiarTel(telefono);
  var userData = null;

  for (var i = 1; i < rows.length; i++) {
    var telSheet = limpiarTel(String(rows[i][0]));
    if (telSheet === telBusca && String(rows[i][2]).toLowerCase() === "activo") {
      userData = {
        nombre: rows[i][1],
        proyectosNombres: String(rows[i][4]).split(",").map(function(p){ return p.trim(); })
      };
      break;
    }
  }

  if (!userData) return { ok: false, error: "Usuario no autorizado o inactivo" };

  var misProyectos = {};
  userData.proyectosNombres.forEach(function(pName) {
    if (PROYECTOS_CONFIG[pName]) {
      misProyectos[pName] = {
        folder_id: PROYECTOS_CONFIG[pName].imagenes,
        sheet_name: "Gastos",
        carpeta_padre: PROYECTOS_CONFIG[pName].carpeta
      };
    }
  });

  return { ok: true, nombre: userData.nombre, proyectos: misProyectos };
}

// ── Guardar Gasto ────────────────────────────────────────────
function guardarGasto(data) {
  var proyecto = data.proyecto; // Recibe 'nombre_proyecto_actual' desde sheets.py
  var config = PROYECTOS_CONFIG[proyecto];
  if (!config) return jsonResp({ ok: false, error: "Proyecto no encontrado: " + proyecto });

  var ss = abrirOCrearSheet(config.carpeta, "Gastos " + proyecto);
  var ws = ss.getSheetByName("Gastos") || ss.getSheets()[0];
  ws.setName("Gastos");

  if (ws.getLastRow() === 0) crearHeaders(ws);

  var now = new Date();
  ws.appendRow([
    formatDate(now), formatTime(now),
    data.quien || "", data.descripcion || "",
    data.categoria || "", data.metodo || "",
    data.monto || 0,
    "", "", "", "", "manual"
  ]);
  return jsonResp({ ok: true });
}

// ── Guardar Foto ─────────────────────────────────────────────
function guardarFoto(data) {
  var proyecto = data.proyecto;
  var config = PROYECTOS_CONFIG[proyecto];
  if (!config) return jsonResp({ ok: false, error: "Proyecto no encontrado: " + proyecto });

  var folder = DriveApp.getFolderById(config.imagenes);
  var blob = Utilities.newBlob(
    Utilities.base64Decode(data.imagen_b64),
    data.mime_type || "image/jpeg",
    "boleta_" + new Date().getTime() + ".jpg"
  );
  var file = folder.createFile(blob);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);

  var ss = abrirOCrearSheet(config.carpeta, "Gastos " + proyecto);
  var ws = ss.getSheetByName("Gastos") || ss.getSheets()[0];
  ws.setName("Gastos");
  if (ws.getLastRow() === 0) crearHeaders(ws);

  var now = new Date();
  ws.appendRow([
    formatDate(now), formatTime(now),
    data.quien || "", "⏳ Pendiente análisis",
    "", "", 0, "", "", "", file.getUrl(), "foto_pendiente"
  ]);

  var ssConfig = SpreadsheetApp.openById(CONFIG_SHEET_ID);
  var wsFotos = ssConfig.getSheetByName("Fotos Pendientes") || ssConfig.insertSheet("Fotos Pendientes");
  if (wsFotos.getLastRow() === 0) {
    wsFotos.appendRow(["Row ID","Proyecto","Sheet ID","Quién","Foto URL","Fecha","Estado"]);
    wsFotos.getRange(1,1,1,7).setFontWeight("bold").setBackground("#34A853").setFontColor("white");
  }
  wsFotos.appendRow([ws.getLastRow(), proyecto, ss.getId(), data.quien || "", file.getUrl(), now, "pendiente"]);

  return jsonResp({ ok: true, foto_url: file.getUrl() });
}

// ── Resumen ──────────────────────────────────────────────────
function getResumen(telefono) {
  var configResp = getUsuarioConfig(telefono);
  if (!configResp.ok) return jsonResp({ ok: true, proyectos: {}, fotos_pendientes: 0 });

  var resultado = {};
  var totalFotos = 0;

  Object.keys(configResp.proyectos).forEach(function(proyecto) {
    var config = PROYECTOS_CONFIG[proyecto];
    var folder = DriveApp.getFolderById(config.carpeta);
    var archivos = folder.getFilesByName("Gastos " + proyecto);
    
    if (!archivos.hasNext()) {
      resultado[proyecto] = { total: 0, gastos: [] };
      return;
    }

    var ss = SpreadsheetApp.open(archivos.next());
    var ws = ss.getSheetByName("Gastos");
    if (!ws || ws.getLastRow() <= 1) {
      resultado[proyecto] = { total: 0, gastos: [] };
      return;
    }

    var rows = ws.getDataRange().getValues();
    var gastos = [];
    var total = 0;

    for (var j = 1; j < rows.length; j++) {
      if (rows[j][11] === "foto_pendiente") { totalFotos++; continue; }
      var monto = Number(rows[j][6]) || 0;
      total += monto;
      gastos.push({ fecha: rows[j][0], quien: rows[j][2], descripcion: rows[j][3], monto: monto });
    }
    resultado[proyecto] = { total: total, gastos: gastos };
  });

  return jsonResp({ ok: true, proyectos: resultado, fotos_pendientes: totalFotos });
}

// ── Helpers de Drive ─────────────────────────────────────────
function abrirOCrearSheet(carpetaId, nombre) {
  var folder = DriveApp.getFolderById(carpetaId);
  var archivos = folder.getFilesByName(nombre);
  if (archivos.hasNext()) return SpreadsheetApp.open(archivos.next());
  
  var ss = SpreadsheetApp.create(nombre);
  var file = DriveApp.getFileById(ss.getId());
  folder.addFile(file);
  DriveApp.getRootFolder().removeFile(file);
  return ss;
}

function crearHeaders(ws) {
  var headers = ["Fecha","Hora","Quién","Descripción","Categoría","Método","Monto","Empresa","RUT","N° Doc","Foto URL","Estado"];
  ws.appendRow(headers);
  ws.getRange(1,1,1,headers.length).setFontWeight("bold").setBackground("#34A853").setFontColor("white");
  ws.setFrozenRows(1);
}

// ── Otros Helpers ────────────────────────────────────────────
function analizarConGemini(base64, mimeType) {
  var prompt = "Analiza esta boleta chilena. Responde SOLO JSON: {\"empresa\":\"\",\"rut_emisor\":\"\",\"total\":0,\"categoria_sugerida\":\"\",\"metodo_pago\":\"\"}";
  var payload = { contents: [{ parts: [{ text: prompt }, { inline_data: { mime_type: mimeType, data: base64 } }] }] };
  var url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=" + GEMINI_API_KEY;
  var resp = UrlFetchApp.fetch(url, { method:"post", contentType:"application/json", payload:JSON.stringify(payload) });
  var texto = JSON.parse(resp.getContentText()).candidates[0].content.parts[0].text;
  return JSON.parse(texto.replace(/```json/g,"").replace(/```/g,"").trim());
}

function limpiarTel(tel) { return String(tel).replace(/\D/g,"").slice(-9); }
function formatDate(d) { return Utilities.formatDate(d,"America/Santiago","dd/MM/yyyy"); }
function formatTime(d) { return Utilities.formatDate(d,"America/Santiago","HH:mm"); }
function jsonResp(obj) { return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON); }

function onOpen() {
  SpreadsheetApp.getUi().createMenu("🤖 Bot Gastos")
    .addItem("📸 Procesar fotos pendientes", "procesarFotosPendientes").addToUi();
}