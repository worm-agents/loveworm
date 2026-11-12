"""Servidor local del dashboard (solo escucha en 127.0.0.1)."""
import os
import socket
import subprocess
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from loveworm.dashboard.worker import INSTAGRAM_ENABLED, Bot

PROJECT_ROOT = Path(__file__).resolve().parents[2]

app = Flask(__name__)
bot = Bot(PROJECT_ROOT)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def state():
    return jsonify(bot.state())


@app.get("/api/chat/<match_id>")
def chat(match_id):
    return jsonify(bot.chat(match_id))


@app.post("/api/start")
def start():
    bot.submit("start")
    return jsonify(ok=True)


@app.post("/api/swipe")
def swipe():
    body = request.get_json(force=True)
    try:
        # se guardan para que el panel los recuerde la próxima vez
        bot.guardar_swipes({"cantidad": body.get("amount", 10), "ratio": body.get("ratio", 72.5),
                            "pausa": body.get("sleep", 5)})
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    cfg = bot.settings["swipes"]
    bot.submit("swipe", amount=cfg["cantidad"], ratio=cfg["ratio"], sleep=cfg["pausa"])
    return jsonify(ok=True)


@app.post("/api/swipes/config")
def swipes_config():
    try:
        bot.guardar_swipes(request.get_json(force=True))
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True)


@app.post("/api/stop")
def stop():
    bot.submit("stop")
    return jsonify(ok=True)


@app.post("/api/refresh")
def refresh():
    bot.submit("refresh")
    return jsonify(ok=True)


@app.post("/api/instagram/connect")
def connect_instagram():
    if not INSTAGRAM_ENABLED:
        return jsonify(ok=False, error="Instagram está desactivado por ahora"), 400
    bot.submit("connect_instagram")
    return jsonify(ok=True)


# sends a message the user reviewed in the dashboard; nothing is sent without this click
@app.post("/api/send")
def send():
    body = request.get_json(force=True)
    match_id = str(body.get("match_id", ""))
    text = str(body.get("text", "")).strip()
    if not match_id or not text:
        return jsonify(ok=False, error="Falta el mensaje"), 400
    bot.submit("send", match_id=match_id, text=text)
    return jsonify(ok=True)


@app.post("/api/drafts/<match_id>/generate")
def generate_draft(match_id):
    bot.generate_draft(match_id)
    return jsonify(ok=True)


@app.post("/api/drafts/<match_id>/discard")
def discard_draft(match_id):
    bot.discard_draft(match_id)
    return jsonify(ok=True)


@app.post("/api/reanalyze/<match_id>")
def reanalyze(match_id):
    bot.reanalyze(match_id)
    return jsonify(ok=True)


# --- cupos: las 5 conversaciones en juego ---

@app.post("/api/cupos/<match_id>/activar")
def activar_cupo(match_id):
    bot.activar_cupo(match_id)
    return jsonify(ok=True)


@app.post("/api/cupos/<match_id>/soltar")
def soltar_cupo(match_id):
    bot.soltar_cupo(match_id)
    return jsonify(ok=True)


@app.post("/api/cupos/<match_id>/liberar")
def liberar_cupo(match_id):
    bot.liberar_cupo(match_id)
    return jsonify(ok=True)


@app.post("/api/llm/resume")
def resume_llm():
    bot.resume_llm()
    return jsonify(ok=True)


@app.get("/api/settings")
def get_settings():
    return jsonify(bot.get_settings())


@app.post("/api/settings")
def save_settings():
    body = request.get_json(force=True)

    def campo(nombre, tipo):
        # lo que no viene se conserva: cada control de la interfaz manda solo lo suyo
        return tipo(body[nombre]) if body.get(nombre) is not None else None

    try:
        bot.update_settings(instructions=campo("instructions", str), model=campo("model", str),
                            model_borrador=campo("model_borrador", str), api=body.get("api"),
                            auto_drafts=campo("auto_drafts", bool), auto_send=campo("auto_send", bool),
                            estilo_opts=body.get("estilo"), max_activas=campo("max_activas", int),
                            tope_diario=campo("tope_diario", int), fisico_opts=body.get("fisico"),
                            sobre_mi=campo("sobre_mi", str), envio=body.get("envio"),
                            agenda=body.get("agenda"))
    except (TypeError, ValueError) as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True)


@app.post("/api/mi_perfil/releer")
def releer_mi_perfil():
    bot.submit("mi_perfil")
    return jsonify(ok=True)


@app.post("/api/guia/regenerar")
def regenerar_guia():
    bot.regenerar_guia()
    return jsonify(ok=True)


@app.post("/api/chrome/<accion>")
def chrome_window(accion):
    """Mostrar u ocultar el Chrome del bot (corre fuera de la vista para no robar el foco)."""
    if accion not in ("mostrar", "ocultar"):
        return jsonify(ok=False, error="Acción inválida"), 404
    try:
        ok = bot.mostrar_chrome() if accion == "mostrar" else bot.ocultar_chrome()
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200]), 500
    if not ok:
        return jsonify(ok=False, error="El navegador no está abierto"), 400
    return jsonify(ok=True)


@app.post("/api/close")
def close():
    bot.submit("close")
    return jsonify(ok=True)


def _close_leftover_chrome():
    """Closing the server window skips the atexit cleanup, so the bot's chrome and its chromedriver
    stay open and keep an inherited copy of the old server socket. Close them before starting."""
    profile = str(PROJECT_ROOT / "chrome_profile").replace("\\", "/")
    script = ("Get-CimInstance Win32_Process -Filter \"name='chrome.exe' or name='undetected_chromedriver.exe'\" | "
              "Where-Object { $_.Name -eq 'undetected_chromedriver.exe' -or "
              f"($_.CommandLine -and $_.CommandLine.Replace('\\', '/') -like '*{profile}*') }} | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _port_free(port):
    # windows lets two sockets share a port unless the bind is exclusive
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if hasattr(s, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def main():
    if os.name == "nt":
        _close_leftover_chrome()
        time.sleep(1)
    if not _port_free(5000):
        raise SystemExit("El puerto 5000 está ocupado: ya hay otro dashboard abierto. Cerralo y volvé a probar.")
    print("Dashboard en http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)