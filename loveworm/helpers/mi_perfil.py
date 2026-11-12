"""Tu propio perfil de Tinder (lo que ven tus matches) para el prompt de los borradores.

Se lee con la API en cada refresco. Las fotos se describen con Claude una sola vez y se vuelven a
describir solo si cambiaste las fotos. Sin esto, cuando te comentan una foto ("la papa de corazón
me mata") el bot no sabe de qué le hablan.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import requests


def _edad(birth_date):
    if not birth_date:
        return None
    try:
        born = datetime.fromisoformat(str(birth_date).replace("Z", "+00:00")).date()
    except ValueError:
        return None
    hoy = date.today()
    return hoy.year - born.year - ((hoy.month, hoy.day) < (born.month, born.day))


def _nombre(valor):
    """Tinder a veces manda {"name": "..."} y a veces el texto directo."""
    if isinstance(valor, dict):
        return str(valor.get("name") or valor.get("displayed") or "").strip()
    return str(valor or "").strip()


def _fotos(user):
    fotos = []
    for p in user.get("photos") or []:
        url = p.get("url") or ""
        # los videos (loops) no se pueden describir como imagen
        if not url.startswith("https://") or p.get("type") == "video" or ".mp4" in url:
            continue
        fotos.append({"id": str(p.get("id") or url), "url": url})
    return fotos


def datos(user: dict) -> dict:
    """Lo que interesa del perfil, sin el ruido de la API."""
    trabajos = []
    for j in user.get("jobs") or []:
        titulo, empresa = _nombre(j.get("title")), _nombre(j.get("company"))
        trabajos.append(" en ".join(t for t in (titulo, empresa) if t))
    intereses = [_nombre(i) for i in ((user.get("user_interests") or {}).get("selected_interests") or [])]
    descriptores = []
    for d in user.get("selected_descriptors") or []:
        opciones = ", ".join(_nombre(c) for c in d.get("choice_selections") or [] if _nombre(c))
        if opciones:
            descriptores.append(f"{_nombre(d)}: {opciones}" if _nombre(d) else opciones)
    intent = user.get("relationship_intent") or {}
    tema = user.get("spotify_theme_track") or {}
    artistas = ", ".join(_nombre(a) for a in tema.get("artists") or [])
    return {
        "nombre": user.get("name") or "",
        "edad": _edad(user.get("birth_date")),
        "bio": (user.get("bio") or "").strip(),
        "trabajo": [t for t in trabajos if t],
        "estudios": [s for s in (_nombre(x) for x in user.get("schools") or []) if s],
        "ciudad": _nombre(user.get("city")),
        "intereses": [i for i in intereses if i],
        "datos": descriptores,
        "busca": str(intent.get("body_text") or intent.get("title_text") or "").strip(),
        "tema": " - ".join(t for t in (tema.get("name") or "", artistas) if t),
        "fotos": _fotos(user),
    }


def clave_fotos(d: dict) -> str:
    return "|".join(f["id"] for f in d.get("fotos") or [])


def bajar_fotos(fotos: list[dict], carpeta: Path) -> list[str]:
    """Descarga las fotos para que Claude las mire. Devuelve las rutas en el mismo orden."""
    carpeta.mkdir(parents=True, exist_ok=True)
    for viejo in carpeta.glob("*.jpg"):
        viejo.unlink()
    rutas = []
    for i, f in enumerate(fotos, 1):
        r = requests.get(f["url"], timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        if "image" not in r.headers.get("Content-Type", ""):
            raise ValueError(f"la foto {i} no es una imagen ({r.headers.get('Content-Type')})")
        ruta = carpeta / f"{i}.jpg"
        ruta.write_bytes(r.content)
        rutas.append(str(ruta.resolve()))
    return rutas


FOTOS_SYSTEM = (
    "Describís las fotos del perfil de Tinder del dueño de la cuenta. Sus matches las ven y muchas veces "
    "las comentan en el chat (ej: 'la papa de corazón me mata', 'qué hacías en esa montaña'), así que "
    "la descripción tiene que servir para entender esos comentarios. Español rioplatense, concreto."
)

FOTOS_SCHEMA = {
    "type": "object",
    "properties": {
        "fotos": {
            "type": "array",
            "description": "una entrada por foto, en el mismo orden en que te las pasaron",
            "items": {"type": "string",
                      "description": "1 o 2 oraciones: dónde está, qué hace, qué tiene puesto y cualquier objeto, "
                                     "comida, animal, cartel o detalle llamativo o gracioso que alguien podría "
                                     "comentar. Si hay otra gente, decí cuántos sin describirlos."},
        },
        "aspecto": {"type": "string",
                    "description": "cómo es físicamente el dueño (el que se repite en las fotos): pelo, barba, "
                                   "anteojos, estilo. Una oración."},
    },
    "required": ["fotos", "aspecto"],
    "additionalProperties": False,
}


def describir(rutas: list[str], ask, model) -> dict:
    """ask: llm.ask. Devuelve {"fotos": [descripción por foto], "aspecto": str}."""
    prompt = f"Son {len(rutas)} fotos, en el orden en que aparecen en el perfil."
    out = ask(FOTOS_SYSTEM, prompt, FOTOS_SCHEMA, model=model, imagenes=rutas, timeout=400)
    descripciones = [str(d).strip() for d in out.get("fotos") or []]
    descripciones += [""] * (len(rutas) - len(descripciones))
    return {"fotos": descripciones[:len(rutas)], "aspecto": str(out.get("aspecto") or "").strip()}


def bloque_prompt(perfil: dict | None) -> str:
    """El perfil en texto para el prompt del borrador."""
    if not perfil or not perfil.get("nombre"):
        return ""
    lineas = ["TU PERFIL DE TINDER (lo que la otra persona ve de vos; si comenta algo de tu perfil o tus "
              "fotos, sale de acá)"]
    nombre = perfil["nombre"] + (f", {perfil['edad']} años" if perfil.get("edad") else "")
    lineas.append(f"Nombre: {nombre}")
    for etiqueta, clave in (("Bio", "bio"), ("Vivís en", "ciudad"), ("Buscás", "busca"), ("Tu tema", "tema")):
        if perfil.get(clave):
            lineas.append(f"{etiqueta}: {perfil[clave]}")
    for etiqueta, clave in (("Trabajo", "trabajo"), ("Estudios", "estudios"), ("Intereses", "intereses"),
                            ("Datos", "datos")):
        if perfil.get(clave):
            lineas.append(f"{etiqueta}: " + "; ".join(perfil[clave]))
    if perfil.get("aspecto"):
        lineas.append(f"Tu aspecto: {perfil['aspecto']}")
    descritas = [f.get("descripcion") for f in perfil.get("fotos") or []]
    if any(descritas):
        lineas.append("Tus fotos, en orden:")
        lineas += [f"{i}. {d or '(sin describir)'}" for i, d in enumerate(descritas, 1)]
    return "\n".join(lineas)


def cargar(ruta: Path) -> dict:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def guardar(ruta: Path, perfil: dict):
    ruta.parent.mkdir(exist_ok=True)
    ruta.write_text(json.dumps(perfil, ensure_ascii=False, indent=2), encoding="utf-8")
