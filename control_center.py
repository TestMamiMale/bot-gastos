import sys
import os
import subprocess
import requests
import webview
from dotenv import load_dotenv

load_dotenv()

class BotApi:
    """API que conecta la interfaz gráfica nativa con comandos del sistema macOS"""

    def check_status(self):
        """Monitorea los servicios y captura los detalles de error completos"""
        
        # 1. Flask Local
        flask_active = False
        flask_msg = "Apagado"
        flask_detail = "El servidor Flask no está escuchando en http://localhost:5000.\n\nSugerencia: Haz clic en el botón '▶ Iniciar' en la sección Servidor Local."
        try:
            r = requests.get('http://localhost:5000/', timeout=1)
            flask_active = True
            flask_msg = f"HTTP {r.status_code} OK"
            flask_detail = f"Servidor local respondiendo correctamente en la máquina.\n\nCódigo HTTP: {r.status_code}\nRuta: http://localhost:5000/"
        except requests.exceptions.ConnectionError:
            flask_msg = "Proceso detenido"
            flask_detail = "Error de Conexión: No hay ningún proceso escuchando en el puerto 5000 (ConnectionRefusedError).\n\nDetalle: La app no está iniciada en segundo plano."
        except Exception as e:
            flask_msg = f"Error: {type(e).__name__}"
            flask_detail = f"Excepción detectada al consultar Flask:\n{str(e)}"

        # 2. ngrok Tunnel
        ngrok_active = False
        ngrok_msg = "Sin túnel"
        ngrok_detail = "ngrok no está corriendo en http://localhost:4040.\n\nSugerencia: Usa el botón '🚀 Iniciar' para abrir el túnel estático."
        try:
            r = requests.get('http://localhost:4040/api/tunnels', timeout=1)
            if r.status_code == 200:
                tunnels = r.json().get('tunnels', [])
                if tunnels:
                    ngrok_active = True
                    public_url = tunnels[0].get('public_url', 'Desconocido')
                    proto = tunnels[0].get('proto', 'http')
                    ngrok_msg = "Túnel Activo"
                    ngrok_detail = f"Túnel ngrok operativo y enlazado exitosamente.\n\nProtocolo: {proto}\nURL Pública: {public_url}\nEndpoint API Local: http://localhost:4040"
                else:
                    ngrok_msg = "Sin túneles"
                    ngrok_detail = "El proceso ngrok está activo en el puerto 4040 pero no se encontró ningún túnel levantado."
        except requests.exceptions.ConnectionError:
            ngrok_msg = "Proceso no iniciado"
            ngrok_detail = "Error de Conexión: No se pudo contactar con la API local de ngrok en el puerto 4040."
        except Exception as e:
            ngrok_msg = f"Error: {type(e).__name__}"
            ngrok_detail = f"Error consultando ngrok:\n{str(e)}"

        # 3. Render
        render_active = False
        render_msg = "Sin respuesta"
        render_detail = "No se pudo obtener respuesta del servidor en Render."
        try:
            r = requests.post('https://bot-gastos-moy7.onrender.com/webhook', timeout=4)
            if r.status_code in [200, 400]:
                render_active = True
                render_msg = f"Online ({r.status_code})"
                render_detail = f"Servidor Render respondiendo correctamente en la nube.\n\nCódigo HTTP: {r.status_code}\nURL Webhook: https://bot-gastos-moy7.onrender.com/webhook\nEstado: Listo para recibir mensajes de producción."
            else:
                render_msg = f"HTTP {r.status_code}"
                render_detail = f"Render devolvió un código de error insospechado.\n\nCódigo HTTP: {r.status_code}\nRevisa la consola de Render para analizar los logs del servidor."
        except requests.exceptions.Timeout:
            render_msg = "Dormido (Timeout)"
            render_detail = "Timeout de Conexión (>4s):\nEl servidor en Render está 'dormido' por inactividad (característica del plan gratuito).\n\nSolución: UptimeRobot o un nuevo request lo despertará en 30-40 segundos."
        except requests.exceptions.ConnectionError:
            render_msg = "Error de red"
            render_detail = "Falla de red: No se pudo resolver el dominio o no hay acceso a internet en este momento."
        except Exception as e:
            render_msg = f"Error: {type(e).__name__}"
            render_detail = f"Detalle de la excepción:\n{str(e)}"

        # 4. Gemini API
        gemini_active = False
        gemini_msg = "Sin clave"
        gemini_detail = "No se encontró GEMINI_API_KEY en tu archivo .env local."
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}"
                r = requests.get(url, timeout=3)
                if r.status_code == 200:
                    gemini_active = True
                    gemini_msg = "API Key OK"
                    gemini_detail = f"Conexión con Google Gemini AI exitosa.\n\nAPI Key: {gemini_key[:6]}...{gemini_key[-4:]}\nEstado: Cuota disponible y autenticación válida."
                elif r.status_code in [400, 403]:
                    gemini_msg = f"HTTP {r.status_code} Error"
                    gemini_detail = f"Acceso denegado por Google AI (HTTP {r.status_code}).\n\nCausa: Tu GEMINI_API_KEY es incorrecta, fue revocada o no tiene los permisos requeridos."
                elif r.status_code == 429:
                    gemini_msg = "Cuota excedida"
                    gemini_detail = "Límite de peticiones alcanzado (HTTP 429 - Rate Limit Exceeded).\n\nEspera unos minutos a que se reinicie tu cuota gratuita de Gemini."
                else:
                    gemini_msg = f"HTTP {r.status_code}"
                    gemini_detail = f"Respuesta inesperada de Gemini:\nHTTP {r.status_code}"
            except Exception as e:
                gemini_msg = "Falla de red"
                gemini_detail = f"No se pudo conectar a los servidores de Google Gemini AI:\n{str(e)}"

        # 5. Git Status
        git_changes = "0 cambios"
        git_detail = "Repositorio local completamente sincronizado con la última versión guardada."
        try:
            out = subprocess.check_output(["git", "status", "--porcelain"]).decode('utf-8')
            lines = [l for l in out.split('\n') if l.strip()]
            if lines:
                git_changes = f"{len(lines)} cambios"
                archivos_str = "\n".join([f"• {l}" for l in lines[:8]])
                if len(lines) > 8:
                    archivos_str += f"\n... y {len(lines) - 8} más"
                git_detail = f"Archivos pendientes de commit:\n\n{archivos_str}\n\nEscribe una nota abajo y usa 'Push a Render' para guardar y desplegar."
            else:
                git_changes = "Repositorio limpio"
                git_detail = "No hay archivos modificados pendientes por guardar. Todo está en main."
        except Exception as e:
            git_changes = "Error Git"
            git_detail = f"Error ejecutando git status:\n{str(e)}"

        return {
            "flask": {"active": flask_active, "msg": flask_msg, "detail": flask_detail},
            "ngrok": {"active": ngrok_active, "msg": ngrok_msg, "detail": ngrok_detail},
            "render": {"active": render_active, "msg": render_msg, "detail": render_detail},
            "gemini": {"active": gemini_active, "msg": gemini_msg, "detail": gemini_detail},
            "git": {"msg": git_changes, "detail": git_detail}
        }

    # --- CONTROLES DE PROCESOS ---
    def start_flask(self):
        os.system("nohup python3 app.py > flask.log 2>&1 &")
        return "Flask iniciado"

    def stop_flask(self):
        os.system("pkill -f 'python3 app.py' || pkill -f 'python app.py'")
        os.system("kill -9 $(lsof -t -i:5000) 2>/dev/null")
        return "Flask detenido"

    def start_ngrok(self):
        os.system("nohup ngrok http --url=translate-punk-jokingly.ngrok-free.dev 5000 > /dev/null 2>&1 &")
        return "ngrok iniciado"

    def stop_ngrok(self):
        os.system("pkill -f ngrok")
        return "ngrok detenido"

    def kill_all(self):
        self.stop_flask()
        self.stop_ngrok()
        return "Procesos eliminados"

    def get_logs(self):
        if os.path.exists("flask.log"):
            try:
                out = subprocess.check_output(["tail", "-n", "10", "flask.log"]).decode('utf-8')
                return out if out else "Esperando actividad..."
            except:
                return "Error leyendo logs."
        return "No hay archivo flask.log."

    def open_url(self, platform):
        urls = {
            "twilio": "https://console.twilio.com/us1/develop/sms/settings/whatsapp-sandbox",
            "render": "https://dashboard.render.com",
            "github": "https://github.com",
            "ngrok": "http://localhost:4040",
            "aistudio": "https://aistudio.google.com/"
        }
        if platform in urls:
            os.system(f"open {urls[platform]}")
        return "URL abierta"

    def git_push(self, commit_message):
        if not commit_message:
            commit_message = "Actualización desde Control Center"
        try:
            subprocess.run(["git", "add", "."], check=True)
            subprocess.run(["git", "commit", "-m", commit_message], check=True)
            subprocess.run(["git", "push", "origin", "main"], check=True)
            return {"status": "success", "msg": "¡Desplegado en Render con éxito!"}
        except Exception as e:
            return {"status": "error", "msg": str(e)}


HTML_UI = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { user-select: none; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    </style>
</head>
<body class="bg-gray-900 text-gray-100 p-5 relative">

    <!-- HEADER -->
    <div class="flex justify-between items-center mb-4 border-b border-gray-800 pb-3">
        <div>
            <h1 class="text-base font-bold text-white flex items-center gap-2">
                🤖 Bot Control Center <span class="text-[10px] bg-indigo-900 text-indigo-300 px-2 py-0.5 rounded-full font-normal">v2.3</span>
            </h1>
            <p class="text-[11px] text-gray-400">Haz clic sobre cualquier tarjeta para ver el diagnóstico completo</p>
        </div>
        <button onclick="updateStatus()" class="bg-gray-800 hover:bg-gray-700 text-xs px-2.5 py-1 rounded text-gray-300 border border-gray-700 transition">
            🔄 Sincronizar
        </button>
    </div>

    <!-- TARJETAS DE ESTADO -->
    <div class="grid grid-cols-5 gap-2 mb-4">
        <div onclick="openModal('Flask Local (5000)', lastData.flask.detail)" class="bg-gray-800/80 hover:bg-gray-700/80 cursor-pointer p-2 rounded-lg border border-gray-700 transition" id="card-flask">
            <span class="text-[10px] text-gray-400 block mb-0.5">Flask (5000)</span>
            <span id="st-flask" class="text-[11px] font-semibold text-yellow-400">...</span>
            <p id="msg-flask" class="text-[9px] text-gray-400 truncate mt-1">...</p>
        </div>
        
        <div onclick="openModal('ngrok Tunnel', lastData.ngrok.detail)" class="bg-gray-800/80 hover:bg-gray-700/80 cursor-pointer p-2 rounded-lg border border-gray-700 transition" id="card-ngrok">
            <span class="text-[10px] text-gray-400 block mb-0.5">ngrok Tunnel</span>
            <span id="st-ngrok" class="text-[11px] font-semibold text-yellow-400">...</span>
            <p id="msg-ngrok" class="text-[9px] text-gray-400 truncate mt-1">...</p>
        </div>

        <div onclick="openModal('Render Nube', lastData.render.detail)" class="bg-gray-800/80 hover:bg-gray-700/80 cursor-pointer p-2 rounded-lg border border-gray-700 transition" id="card-render">
            <span class="text-[10px] text-gray-400 block mb-0.5">Render Nube</span>
            <span id="st-render" class="text-[11px] font-semibold text-yellow-400">...</span>
            <p id="msg-render" class="text-[9px] text-gray-400 truncate mt-1">...</p>
        </div>

        <div onclick="openModal('Gemini API', lastData.gemini.detail)" class="bg-gray-800/80 hover:bg-gray-700/80 cursor-pointer p-2 rounded-lg border border-gray-700 transition" id="card-gemini">
            <span class="text-[10px] text-gray-400 block mb-0.5">Gemini API</span>
            <span id="st-gemini" class="text-[11px] font-semibold text-yellow-400">...</span>
            <p id="msg-gemini" class="text-[9px] text-gray-400 truncate mt-1">...</p>
        </div>

        <div onclick="openModal('Git Status', lastData.git.detail)" class="bg-gray-800/80 hover:bg-gray-700/80 cursor-pointer p-2 rounded-lg border border-gray-700 transition" id="card-git">
            <span class="text-[10px] text-gray-400 block mb-0.5">Git Status</span>
            <span id="st-git" class="text-[11px] font-semibold text-gray-300">...</span>
            <p id="msg-git" class="text-[9px] text-gray-400 truncate mt-1">...</p>
        </div>
    </div>

    <!-- BOTONES DE ACCESO RÁPIDO EXTERNO -->
    <div class="mb-4">
        <span class="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block mb-1.5">Consolas de Administración</span>
        <div class="grid grid-cols-5 gap-1.5">
            <button onclick="pywebview.api.open_url('twilio')" class="bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-700 text-[10px] py-1 px-1.5 rounded-lg transition text-center">🔴 Twilio</button>
            <button onclick="pywebview.api.open_url('render')" class="bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-700 text-[10px] py-1 px-1.5 rounded-lg transition text-center">☁️ Render</button>
            <button onclick="pywebview.api.open_url('aistudio')" class="bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-700 text-[10px] py-1 px-1.5 rounded-lg transition text-center">✨ Gemini AI</button>
            <button onclick="pywebview.api.open_url('github')" class="bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-700 text-[10px] py-1 px-1.5 rounded-lg transition text-center">🐙 GitHub</button>
            <button onclick="pywebview.api.open_url('ngrok')" class="bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-700 text-[10px] py-1 px-1.5 rounded-lg transition text-center">🔍 ngrok 4040</button>
        </div>
    </div>

    <!-- CONTROLES LOCALES -->
    <div class="grid grid-cols-2 gap-3 mb-4">
        <div class="bg-gray-800 p-3 rounded-lg border border-gray-700">
            <h2 class="text-xs font-semibold text-gray-300 mb-2">Servidor Local (app.py)</h2>
            <div class="flex gap-2">
                <button onclick="pywebview.api.start_flask().then(updateStatus)" class="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-[11px] py-1.5 rounded-md transition">▶ Iniciar</button>
                <button onclick="pywebview.api.stop_flask().then(updateStatus)" class="flex-1 bg-rose-600 hover:bg-rose-500 text-white font-medium text-[11px] py-1.5 rounded-md transition">■ Detener</button>
            </div>
        </div>

        <div class="bg-gray-800 p-3 rounded-lg border border-gray-700">
            <div class="flex justify-between items-center mb-2">
                <h2 class="text-xs font-semibold text-gray-300">Túnel ngrok</h2>
                <button onclick="pywebview.api.kill_all().then(updateStatus)" class="text-[10px] text-rose-400 hover:underline">⚡ Kill All</button>
            </div>
            <div class="flex gap-2">
                <button onclick="pywebview.api.start_ngrok().then(updateStatus)" class="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-[11px] py-1.5 rounded-md transition">🚀 Iniciar</button>
                <button onclick="pywebview.api.stop_ngrok().then(updateStatus)" class="flex-1 bg-rose-600 hover:bg-rose-500 text-white font-medium text-[11px] py-1.5 rounded-md transition">🛑 Detener</button>
            </div>
        </div>
    </div>

    <!-- GIT DEPLOY -->
    <div class="bg-gray-800 p-3 rounded-lg border border-gray-700 mb-3">
        <div class="flex gap-2 mb-1">
            <input type="text" id="commit-msg" placeholder="Mensaje de cambio..." class="flex-1 bg-gray-900 border border-gray-700 rounded-md px-2.5 py-1 text-xs text-gray-200 focus:outline-none focus:border-indigo-500">
            <button onclick="deployGit()" class="bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs py-1 px-3 rounded-md transition">⬆️ Push a Render</button>
        </div>
        <p id="deploy-out" class="text-[10px] text-gray-400"></p>
    </div>

    <!-- LOGS LOCALES -->
    <div class="bg-black/60 p-2.5 rounded-lg border border-gray-800 font-mono text-[10px] text-green-400 h-24 overflow-y-auto" id="logs-container">
        Cargando logs...
    </div>

    <!-- VENTANA EMERGENTE (MODAL DE DIAGNÓSTICO) -->
    <div id="modal" class="fixed inset-0 bg-black/80 backdrop-blur-sm hidden flex items-center justify-center p-4 z-50">
        <div class="bg-gray-800 border border-gray-700 rounded-xl p-5 max-w-md w-full shadow-2xl">
            <div class="flex justify-between items-center mb-3">
                <h3 id="modal-title" class="text-sm font-bold text-white">Diagnóstico de Servicio</h3>
                <button onclick="closeModal()" class="text-gray-400 hover:text-white text-xs bg-gray-700 px-2 py-1 rounded">✕ Cerrar</button>
            </div>
            <pre id="modal-content" class="text-xs text-gray-300 font-mono bg-gray-900 p-3 rounded-lg border border-gray-700 whitespace-pre-wrap leading-relaxed max-h-60 overflow-y-auto"></pre>
        </div>
    </div>

    <script>
        let lastData = {};

        function openModal(title, detail) {
            document.getElementById('modal-title').innerText = title;
            document.getElementById('modal-content').innerText = detail || "Sin información de diagnóstico disponible.";
            document.getElementById('modal').classList.remove('hidden');
        }

        function closeModal() {
            document.getElementById('modal').classList.add('hidden');
        }

        function updateStatus() {
            pywebview.api.check_status().then(res => {
                lastData = res;

                // Flask
                document.getElementById('st-flask').innerHTML = res.flask.active ? '🟢 Activo' : '🔴 Off';
                document.getElementById('st-flask').className = res.flask.active ? 'text-[11px] font-semibold text-emerald-400' : 'text-[11px] font-semibold text-rose-400';
                document.getElementById('msg-flask').innerText = res.flask.msg;

                // ngrok
                document.getElementById('st-ngrok').innerHTML = res.ngrok.active ? '🟢 Activo' : '🔴 Off';
                document.getElementById('st-ngrok').className = res.ngrok.active ? 'text-[11px] font-semibold text-emerald-400' : 'text-[11px] font-semibold text-rose-400';
                document.getElementById('msg-ngrok').innerText = res.ngrok.msg;

                // Render
                document.getElementById('st-render').innerHTML = res.render.active ? '🟢 Online' : '🔴 Off';
                document.getElementById('st-render').className = res.render.active ? 'text-[11px] font-semibold text-emerald-400' : 'text-[11px] font-semibold text-rose-400';
                document.getElementById('msg-render').innerText = res.render.msg;

                // Gemini
                document.getElementById('st-gemini').innerHTML = res.gemini.active ? '🟢 OK' : '🔴 Error';
                document.getElementById('st-gemini').className = res.gemini.active ? 'text-[11px] font-semibold text-emerald-400' : 'text-[11px] font-semibold text-rose-400';
                document.getElementById('msg-gemini').innerText = res.gemini.msg;

                // Git
                document.getElementById('st-git').innerHTML = '📄 Repo';
                document.getElementById('msg-git').innerText = res.git.msg;
            });
        }

        function updateLogs() {
            pywebview.api.get_logs().then(logs => {
                document.getElementById('logs-container').innerText = logs;
            });
        }

        function deployGit() {
            const msg = document.getElementById('commit-msg').value;
            const out = document.getElementById('deploy-out');
            out.innerText = "⏳ Subiendo a GitHub...";
            out.className = "text-[10px] text-yellow-400";

            pywebview.api.git_push(msg).then(res => {
                if (res.status === 'success') {
                    out.innerText = "✅ " + res.msg;
                    out.className = "text-[10px] text-emerald-400";
                    document.getElementById('commit-msg').value = "";
                    updateStatus();
                } else {
                    out.innerText = "❌ Error: " + res.msg;
                    out.className = "text-[10px] text-rose-400";
                }
            });
        }

        setInterval(updateStatus, 4000);
        setInterval(updateLogs, 2500);
        window.addEventListener('pywebviewready', () => {
            updateStatus();
            updateLogs();
        });
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    api = BotApi()
    window = webview.create_window(
        title='Bot Control Center v2.3',
        html=HTML_UI,
        js_api=api,
        width=630,
        height=560,
        resizable=False
    )
    webview.start()