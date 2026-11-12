"""Cupo de conversaciones activas: como máximo 5 a la vez, con rotación a los 7 días.

Mantener 40 chats abiertos es imposible de revisar. Esta política elige las 5 que valen la
pena, deja el resto estacionadas y saca de circulación a quien no contestó en una semana para
meter a alguien nuevo en su lugar.

El estado vive en data/cupos.json. Nunca rota un chat con la cita confirmada. Si una rotada vuelve
a escribir, entra de nuevo sola.

Suelto, contra el cache guardado:
    .\\.venv\\Scripts\\python.exe -m loveworm.helpers.cupos
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from loveworm.helpers import interes

MAX_ACTIVAS = 1
DIAS_PARA_ROTAR = 7      # sin respuesta nuestra, se libera el cupo
DIAS_VIGENCIA = 21       # un chat más viejo que esto no se promueve


def _ts(valor):
    return interes._ts(valor)


def _ig(entry):
    return (entry.get("instagram") or {}).get("messages") or []


class Cupos:

    def __init__(self, path, max_activas=MAX_ACTIVAS):
        self.path = Path(path)
        self.max_activas = max_activas
        self.activas = {}   # match_id -> {"desde": iso}
        self.rotadas = {}   # match_id -> {"fecha": iso, "motivo": str}
        self._cargar()

    # --- estado ---

    def _cargar(self):
        try:
            datos = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return
        # "fijada" ya no existe: un chat fijado no rotaba nunca y no se entendía. Ahora todos rotan igual
        self.activas = {mid: {"desde": a.get("desde")} for mid, a in (datos.get("activas") or {}).items()}
        self.rotadas = datos.get("rotadas") or {}

    def _guardar(self):
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(json.dumps({"activas": self.activas, "rotadas": self.rotadas},
                                        ensure_ascii=False, indent=2), encoding="utf-8")

    def estado(self, match_id):
        if match_id in self.activas:
            return "activa"
        if match_id in self.rotadas:
            return "rotada"
        return "estacionada"

    def activar(self, match_id):
        """La suma a mano. Los 7 días sin respuesta se cuentan desde ahora, así no rota en el acto."""
        self.activas[match_id] = {"desde": datetime.now(timezone.utc).isoformat()}
        self.rotadas.pop(match_id, None)
        self._guardar()

    def soltar(self, match_id):
        """Le saca el cupo a mano."""
        self.activas.pop(match_id, None)
        self.rotadas[match_id] = {"fecha": datetime.now(timezone.utc).isoformat(), "motivo": "a mano"}
        self._guardar()

    def liberar(self, match_id):
        """La devuelve al pool, como si nunca hubiera estado activa."""
        self.activas.pop(match_id, None)
        self.rotadas.pop(match_id, None)
        self._guardar()

    # --- la política ---

    def revisar(self, cache, ahora=None):
        """Rota a quien se quedó sin respuesta y llena los cupos libres.

        Devuelve {"activas", "promovidas", "rotadas", "estacionadas"}.
        """
        ahora = ahora or datetime.now(timezone.utc)
        promovidas, rotadas = [], []

        for mid in list(self.activas):
            motivo = self._motivo_rotacion(mid, cache.get(mid) or {}, ahora)
            if motivo:
                self.activas.pop(mid)
                self.rotadas[mid] = {"fecha": ahora.isoformat(), "motivo": motivo}
                rotadas.append(mid)

        libres = self.max_activas - len(self.activas)
        if libres > 0:
            for mid in self._candidatas(cache, ahora)[:libres]:
                self.activas[mid] = {"desde": ahora.isoformat()}
                promovidas.append(mid)

        self._guardar()
        return {"activas": list(self.activas), "promovidas": promovidas, "rotadas": rotadas,
                "estacionadas": max(0, len(cache) - len(self.activas) - len(rotadas))}

    def _motivo_rotacion(self, mid, entry, ahora):
        if (entry.get("cita") or {}).get("estado") == "confirmada":
            return None

        # desde que entró al cupo: a una que sumaste a mano no se la rota por días de antes
        activa_desde = _ts(self.activas[mid].get("desde"))
        mensajes = entry.get("messages") or []
        if not mensajes:
            # nunca abrimos la charla: si el match ya es viejo, no merece el cupo
            matched = max(filter(None, (_ts(entry.get("matched")), activa_desde)), default=None)
            if matched and (ahora - matched).days >= DIAS_PARA_ROTAR:
                return "sin abrir"
            return None

        ultimo = mensajes[-1]
        if not ultimo.get("from_me"):
            return None  # escribió ella: la pelota no está de nuestro lado

        desde = _ts(ultimo.get("sent")) or _ts(entry.get("last_activity"))
        desde = max(filter(None, (desde, activa_desde)), default=None)
        if desde and (ahora - desde).days >= DIAS_PARA_ROTAR:
            return f"sin respuesta hace {(ahora - desde).days} días"
        return None

    def _candidatas(self, cache, ahora):
        """Chats que pueden ocupar un cupo, en orden de prioridad."""
        candidatas = []
        for mid, entry in cache.items():
            if mid in self.activas or entry.get("unmatch"):
                continue
            mensajes = entry.get("messages") or []
            ultimo = mensajes[-1] if mensajes else None

            rotada = self.rotadas.get(mid)
            if rotada:
                # solo vuelve si escribió después de que la sacamos
                if not ultimo or ultimo.get("from_me"):
                    continue
                if (_ts(ultimo.get("sent")) or ahora) <= (_ts(rotada.get("fecha")) or ahora):
                    continue

            score = interes.score_final(entry, ahora=ahora)

            if ultimo is None:
                prioridad, referencia = 2, _ts(entry.get("matched")) or ahora
            elif not ultimo.get("from_me"):
                prioridad, referencia = 1, _ts(ultimo.get("sent")) or ahora
            else:
                prioridad, referencia = 3, _ts(ultimo.get("sent")) or ahora

            if prioridad != 1 and (ahora - referencia).days > DIAS_VIGENCIA:
                continue

            candidatas.append((prioridad, score, referencia.timestamp(), mid))

        candidatas.sort(key=lambda c: (c[0], -c[1], -c[2]))
        return [c[3] for c in candidatas]

    def resumen(self, cache, ahora=None):
        """Para el dashboard: las activas con nombre y score, más los contadores."""
        ahora = ahora or datetime.now(timezone.utc)
        detalle = []
        for mid in self.activas:
            entry = cache.get(mid) or {}
            detalle.append({"id": mid, "nombre": entry.get("name", "?"),
                            "score": interes.score_final(entry, ahora=ahora)})
        detalle.sort(key=lambda d: d["score"], reverse=True)
        pausadas = [{"id": mid, "nombre": (cache.get(mid) or {}).get("name", "?"),
                     "motivo": r.get("motivo", ""), "fecha": r.get("fecha")}
                    for mid, r in self.rotadas.items()]
        pausadas.sort(key=lambda p: p["fecha"] or "", reverse=True)
        return {"cupo": self.max_activas, "usados": len(self.activas), "detalle": detalle,
                "rotadas": len(self.rotadas), "pausadas": pausadas[:30]}


# --- prueba suelta: muestra qué haría la política con tus chats de ahora ---

def _main():
    raiz = Path(__file__).resolve().parents[2]
    try:
        cache = json.loads((raiz / "data" / "dashboard_cache.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        print("No encontré data/dashboard_cache.json. Abrí el dashboard una vez.")
        return

    cupos = Cupos(raiz / "data" / "cupos.json")
    antes = set(cupos.activas)
    resultado = cupos.revisar(cache)

    print(f"Activas: {len(resultado['activas'])}/{MAX_ACTIVAS}\n")
    for d in cupos.resumen(cache)["detalle"]:
        print(f"  {d['score']:>3}  {d['nombre'][:28]}")

    if resultado["promovidas"]:
        print("\nPromovidas:")
        for mid in resultado["promovidas"]:
            print(f"  {cache.get(mid, {}).get('name', '?')}")
    if resultado["rotadas"]:
        print("\nRotadas:")
        for mid in resultado["rotadas"]:
            print(f"  {cache.get(mid, {}).get('name', '?')} — {cupos.rotadas[mid]['motivo']}")

    print(f"\nEstacionadas: {resultado['estacionadas']}  ·  rotadas históricas: {len(cupos.rotadas)}")
    print(f"({len(antes)} activas antes de correr esto)")


if __name__ == "__main__":
    _main()