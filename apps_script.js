// ============================================================
// APPS SCRIPT — Bot de Gastos con fotos batch
// ============================================================

var GEMINI_API_KEY = "TU_GEMINI_API_KEY_AQUI";
var DRIVE_FOLDER_ID = "TU_CARPETA_ID_AQUI"; // carpeta donde guardar fotos

var SHEET_GASTOS  = "Gastos";
var SHEET_FOTOS   = "Fotos Pendientes";

function doPost(e) {
  try {
    var data   = JSON.parse(e.postData.contents);
    var action = data.action || "guardar_gasto";
    if (action === "guardar_foto")     return guardarFoto(data);
    if (action === "actualizar_batch") return actualizarBatch(data);
    return guardarGasto(data);
  } catch (err) {
    return jsonResp({ ok: false, error: err.toString() });
  }
}

function doGet(e) {
  try {
    return getResumen();
  } catch (err) {
    return jsonResp({ ok: false, error: err.toString() });
  }
}

// ── Guardar gasto manual ─────────────────────────────────────
function guardarGasto(data) {
  var ws  = getOrCreateSheet(SHEET_GASTOS, headersGastos());
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

// ── Guardar foto pendiente ────────────────────────────────────
function guardarFoto(data) {
  // 1. Subir imagen a Drive
  var folder  = DriveApp.getFolderById(DRIVE_FOLDER_ID);
  var blob    = Utilities.newBlob(
    Utilities.base64Decode(data.imagen_b64),
    data.mime_type || "image/jpeg",
    "boleta_" + new Date().getTime() + ".jpg"
  );
  var file = folder.createFile(blob);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  var fotoUrl = file.getUrl();

  // 2. Agregar fila en Gastos como pendiente
  var ws  = getOrCreateSheet(SHEET_GASTOS, headersGastos());
  var now = new Date();
  ws.appendRow([
    formatDate(now), formatTime(now),
    data.quien || "", "⏳ Pendiente análisis",
    "", "", 0, "", "", "", fotoUrl, "foto_pendiente"
  ]);
  var rowId = ws.getLastRow();

  // 3. Registrar en hoja Fotos Pendientes
  var wsFotos = getOrCreateSheet(SHEET_FOTOS, ["Row ID","Quién","Foto URL","Fecha","Estado"]);
  wsFotos.appendRow([rowId, data.quien || "", fotoUrl, now, "pendiente"]);

  return jsonResp({ ok: true, row_id: rowId, foto_url: fotoUrl });
}

// ── Obtener resumen para el bot ──────────────────────────────
function getResumen() {
  var ws = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_GASTOS);
  if (!ws || ws.getLastRow() <= 1) return jsonResp({ ok: true, gastos: [], total: 0, fotos_pendientes: 0 });

  var rows   = ws.getDataRange().getValues();
  var gastos = [];
  var pendientes = 0;

  for (var i = 1; i < rows.length; i++) {
    var estado = rows[i][11];
    if (estado === "foto_pendiente") { pendientes++; continue; }
    gastos.push({
      fecha:       rows[i][0],
      quien:       rows[i][2],
      descripcion: rows[i][3],
      categoria:   rows[i][4],
      metodo:      rows[i][5],
      monto:       rows[i][6]
    });
  }

  var total = gastos.reduce(function(s,g){ return s+(Number(g.monto)||0); }, 0);
  return jsonResp({ ok: true, gastos: gastos, total: total, fotos_pendientes: pendientes });
}

// ── Procesar fotos con Gemini (desde menú del Sheet) ─────────
function procesarFotosPendientes() {
  var ss      = SpreadsheetApp.getActiveSpreadsheet();
  var wsGastos = ss.getSheetByName(SHEET_GASTOS);
  var wsFotos  = ss.getSheetByName(SHEET_FOTOS);
  if (!wsFotos) { SpreadsheetApp.getUi().alert("No hay fotos pendientes."); return; }

  var filasFotos = wsFotos.getDataRange().getValues();
  var pendientes = [];
  for (var i = 1; i < filasFotos.length; i++) {
    if (filasFotos[i][4] === "pendiente") {
      pendientes.push({ fila_fotos: i + 1, row_id: filasFotos[i][0], quien: filasFotos[i][1], foto_url: filasFotos[i][2] });
    }
  }

  if (pendientes.length === 0) { SpreadsheetApp.getUi().alert("✅ No hay fotos pendientes."); return; }

  var procesadas = 0;
  var errores    = 0;

  pendientes.forEach(function(p) {
    ss.toast("Analizando foto " + (procesadas + errores + 1) + " de " + pendientes.length, "⏳ Gemini...", 15);
    try {
      // Descargar imagen desde Drive
      var fileId  = p.foto_url.match(/[-\w]{25,}/);
      if (!fileId) throw new Error("No se pudo extraer ID del archivo");
      var file    = DriveApp.getFileById(fileId[0]);
      var bytes   = file.getBlob().getBytes();
      var base64  = Utilities.base64Encode(bytes);
      var mime    = file.getMimeType();

      var datos = analizarConGemini(base64, mime);
      var rowId = parseInt(p.row_id);

      // Actualizar fila en Gastos
      wsGastos.getRange(rowId, 4).setValue(datos.descripcion_productos || datos.empresa || "Sin detalle");
      wsGastos.getRange(rowId, 5).setValue(datos.categoria_sugerida    || "Otro");
      wsGastos.getRange(rowId, 6).setValue(datos.metodo_pago           || "");
      wsGastos.getRange(rowId, 7).setValue(datos.total                 || 0);
      wsGastos.getRange(rowId, 8).setValue(datos.empresa               || "");
      wsGastos.getRange(rowId, 9).setValue(datos.rut_emisor            || "");
      wsGastos.getRange(rowId, 10).setValue(datos.numero_documento     || "");
      wsGastos.getRange(rowId, 12).setValue("✅ analizado (" + (datos.confianza || 0) + "%)");

      // Marcar como procesado
      wsFotos.getRange(p.fila_fotos, 5).setValue("procesado");
      procesadas++;
    } catch(err) {
      wsGastos.getRange(parseInt(p.row_id), 12).setValue("❌ error: " + err.toString().substring(0,50));
      errores++;
    }
    Utilities.sleep(3000);
  });

  SpreadsheetApp.getUi().alert(
    "✅ Proceso completado\n\n" +
    "✔ Analizadas: " + procesadas + "\n" +
    "✖ Errores: "    + errores
  );
}

// ── Analizar imagen con Gemini ───────────────────────────────
function analizarConGemini(base64, mimeType) {
  var prompt =
    "Analiza esta boleta o factura chilena. " +
    "Responde SOLO con JSON válido sin texto adicional ni backticks:\n" +
    '{"empresa":"","rut_emisor":"","tipo_documento":"boleta|factura|voucher|ticket",' +
    '"numero_documento":"","fecha":"DD/MM/YYYY","hora":"HH:MM",' +
    '"descripcion_productos":"","monto_neto":0,"iva":0,"total":0,' +
    '"metodo_pago":"debito|credito|efectivo|transferencia|prepago|no_visible",' +
    '"ultimos_4_tarjeta":"","codigo_autorizacion":"",' +
    '"categoria_sugerida":"Comida|Transporte|Hogar|Salud|Entretenimiento|Ropa|Educacion|Trabajo|Otro",' +
    '"confianza":0,"notas":""}\n' +
    "Reglas: total como número sin puntos ni $. Si hay 2 documentos del mismo gasto combínalos. confianza 0-100.";

  var payload = {
    contents: [{ parts: [
      { text: prompt },
      { inline_data: { mime_type: mimeType, data: base64 } }
    ]}],
    generationConfig: { temperature: 0.1, maxOutputTokens: 1024 }
  };

  var url  = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key=" + GEMINI_API_KEY;
  var resp = UrlFetchApp.fetch(url, { method:"post", contentType:"application/json", payload:JSON.stringify(payload), muteHttpExceptions:true });

  if (resp.getResponseCode() === 503) {
    Utilities.sleep(10000);
    resp = UrlFetchApp.fetch(url, { method:"post", contentType:"application/json", payload:JSON.stringify(payload), muteHttpExceptions:true });
  }
  if (resp.getResponseCode() !== 200) throw new Error("Gemini " + resp.getResponseCode());

  var texto  = JSON.parse(resp.getContentText()).candidates[0].content.parts[0].text;
  var limpio = texto.trim().replace(/```json/g,"").replace(/```/g,"").replace(/[\u201C\u201D]/g,'"').trim();
  var match  = limpio.match(/\{[\s\S]*\}/);
  if (!match) throw new Error("JSON inválido");
  return JSON.parse(match[0]);
}

// ── Helpers ──────────────────────────────────────────────────
function headersGastos() {
  return ["Fecha","Hora","Quién","Descripción","Categoría","Método de pago","Monto","Empresa","RUT","N° Doc","Foto URL","Estado"];
}

function getOrCreateSheet(name, headers) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var ws = ss.getSheetByName(name);
  if (!ws) {
    ws = ss.insertSheet(name);
    ws.appendRow(headers);
    ws.getRange(1,1,1,headers.length).setFontWeight("bold").setBackground("#34A853").setFontColor("white");
  }
  return ws;
}

function formatDate(d) { return Utilities.formatDate(d, "America/Santiago", "dd/MM/yyyy"); }
function formatTime(d) { return Utilities.formatDate(d, "America/Santiago", "HH:mm"); }
function jsonResp(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// ── Menú en el Sheet ─────────────────────────────────────────
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🤖 Bot Gastos")
    .addItem("📸 Procesar fotos pendientes", "procesarFotosPendientes")
    .addToUi();
}
