"""Estado de la cita por chat: quién propuso, qué día, si quedó cerrado.

Sin esto el bot propone salir dos veces, o sigue empujando cuando el plan ya está cerrado,
porque cada borrador se escribe mirando solo el chat y sin memoria de dónde quedó la cosa.

El estado lo lee Claude junto con el análisis, así que no cuesta una llamada extra. Acá se
fusiona con guardas duras: una cita confirmada no se pierde porque el modelo tuvo una mala
lectura.

Suelto, contra el cache guardado:
    .\\.venv\\Scripts\\python.exe -m loveworm.helpers.citas
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

VERSION = "citas-v1"

ESTADOS = ("sin_proponer", "propuesta", "contrapropuesta", "confirmada", "hecha", "cancelada")

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

DEFAULT = {"estado": "sin_proponer", "dia": "", "momento": "", "lugar": "", "quien": "ninguno",
           "desde": None, "actualizado": None, "version": VERSION}

# estados en los que ya hay algo propuesto y no hay que volver a proponer
PROPUESTOS = ("propuesta", "contrapropuesta", "confirmada")


def _completar(d):
    c = dict(DEFAULT)
    if isinstance(d, dict):
        for k in DEFAULT:
            if d.get(k) is not None:
                c[k] = d[k]
    if c["estado"] not in ESTADOS:
        c["estado"] = "sin_proponer"
    return c


def leer(entry):
    """El estado de la cita de esa entrada del cache, completo."""
    return _completar((entry or {}).get("cita"))


def _normalizar(leido):
    if not isinstance(leido, dict):
        return dict(DEFAULT)
    estado = str(leido.get("estado") or "").strip().lower()
    if estado not in ESTADOS:
        estado = "sin_proponer"
    dia = str(leido.get("dia") or "").strip()
    try:
        date.fromisoformat(dia)
    except ValueError:
        dia = ""
    return {"estado": estado, "dia": dia,
            "momento": str(leido.get("momento") or "").strip()[:40],
            "lugar": str(leido.get("lugar") or "").strip()[:60],
            "quien": leido.get("quien") if leido.get("quien") in ("yo", "ella", "ninguno") else "ninguno",
            "desde": None, "actualizado": None, "version": VERSION}


def _vencida(cita, ahora):
    """Si el día confirmado ya pasó, la cita queda como hecha."""
    if cita["estado"] == "confirmada" and cita["dia"]:
        try:
            if date.fromisoformat(cita["dia"]) < ahora.date():
                cita["estado"] = "hecha"
        except ValueError:
            pass
    return cita


def aplicar(actual, leido, ahora=None):
    """Fusiona lo que leyó Claude con lo guardado. Las guardas van acá, no en el prompt."""
    ahora = ahora or datetime.now(timezone.utc)
    previo = _completar(actual)
    nuevo = _normalizar(leido)

    # el modelo no puede borrar un plan cerrado por una mala lectura
    if previo["estado"] == "confirmada" and nuevo["estado"] in ("sin_proponer", "propuesta"):
        nuevo["estado"] = "confirmada"
        for campo in ("dia", "momento", "lugar"):
            nuevo[campo] = nuevo[campo] or previo[campo]

    # confirmada sin día no sirve
    if nuevo["estado"] == "confirmada" and not nuevo["dia"]:
        nuevo["estado"] = "propuesta"

    mismo_plan = previo["estado"] == "confirmada" and nuevo["estado"] == "confirmada" \
        and previo["dia"] == nuevo["dia"]
    if mismo_plan:
        nuevo["desde"] = previo["desde"]           # no reinicia el reloj de un plan ya cerrado
    elif nuevo["estado"] != previo["estado"] or nuevo["dia"] != previo["dia"]:
        nuevo["desde"] = ahora.isoformat()
    else:
        nuevo["desde"] = previo["desde"]

    nuevo["actualizado"] = ahora.isoformat()
    return _vencida(nuevo, ahora)


def por_defecto(mensajes):
    """Estado para chats que nunca se analizaron porque ella no contestó. Que le hayamos escrito
    (un saludo, el primer mensaje) no es proponer una cita."""
    return _completar({"estado": "sin_proponer", "quien": "ninguno"})


def _dia_lindo(iso):
    try:
        d = date.fromisoformat(iso)
    except (ValueError, TypeError):
        return iso or ""
    return f"{DIAS[d.weekday()]} {d:%d/%m}"


def resumen(cita):
    partes = []
    if cita.get("dia"):
        partes.append(_dia_lindo(cita["dia"]))
    if cita.get("momento"):
        partes.append(f"a la {cita['momento']}")
    if cita.get("lugar"):
        partes.append(f"en {cita['lugar']}")
    return " ".join(partes) or "sin día ni lugar definido"


def bloque_prompt(cita):
    """Lo que el borrador necesita saber para no proponer dos veces ni empujar de más."""
    estado = (cita or {}).get("estado", "sin_proponer")
    if estado == "sin_proponer":
        return "ESTADO DE LA CITA: todavía nadie propuso salir."
    if estado == "propuesta":
        return ("ESTADO DE LA CITA: vos ya propusiste salir y la otra persona todavía no cerró. "
                "No vuelvas a proponer en este mensaje, seguí la charla.\n"
                f"Lo que quedó sobre la mesa: {resumen(cita)}")
    if estado == "contrapropuesta":
        return ("ESTADO DE LA CITA: la otra persona contrapropuso otro día o momento. "
                "Cerrá con lo que propuso, no insistas con tu propuesta anterior.\n"
                f"Lo que propuso: {resumen(cita)}")
    if estado == "confirmada":
        return ("ESTADO DE LA CITA: el plan ya está cerrado. No propongas nada más, "
                "solo mantené la charla y confirmá si hace falta.\n"
                f"Plan: {resumen(cita)}")
    if estado == "hecha":
        return ("ESTADO DE LA CITA: ya se vieron. No hace falta proponer otra salida todavía.")
    return "ESTADO DE LA CITA: el plan se canceló. Podés proponer uno nuevo cuando venga al caso."


def proximas(cache, ahora=None):
    """Citas confirmadas o hechas, para mostrar arriba en el dashboard."""
    hoy = (ahora or datetime.now(timezone.utc)).date()
    salida = []
    for mid, entry in cache.items():
        c = leer(entry)
        if c["estado"] in ("confirmada", "hecha") and c["dia"]:
            try:
                d = date.fromisoformat(c["dia"])
            except ValueError:
                continue
            if d >= hoy - timedelta(days=1):
                salida.append({"id": mid, "nombre": entry.get("name", "?"), "dia": c["dia"],
                               "cuando": resumen(c), "estado": c["estado"]})
    salida.sort(key=lambda x: x["dia"])
    return salida


# --- prueba suelta: en qué quedó cada chat ---

def _main():
    raiz = Path(__file__).resolve().parents[2]
    try:
        cache = json.loads((raiz / "data" / "dashboard_cache.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        print("No encontré data/dashboard_cache.json. Abrí el dashboard una vez.")
        return

    conteo = {}
    filas = []
    for entry in cache.values():
        c = leer(entry)
        conteo[c["estado"]] = conteo.get(c["estado"], 0) + 1
        if c["estado"] != "sin_proponer":
            filas.append((c["estado"], entry.get("name", "?"), resumen(c)))

    print("Estados:")
    for estado in ESTADOS:
        print(f"  {estado:<16} {conteo.get(estado, 0)}")
    if filas:
        print("\nCon algo propuesto:")
        for estado, nombre, detalle in filas:
            print(f"  {nombre[:24]:<24} {estado:<16} {detalle}")


if __name__ == "__main__":
    _main()