"""Filtro por características físicas antes de dar like, con CLIP zero-shot y local.

No manda fotos a ningún lado: el modelo corre en tu máquina. Cada atributo se compara
contra un par de descripciones (positiva y negativa) y queda una probabilidad, tomando
la mejor foto de cada uno.

Cada rasgo es "quiero" (obligatorio), "evitar" (excluir) o da igual. Pasa quien tiene todos
los que quiero y ninguno de los que evito.

Modos:
  sombra  no decide, solo anota en data/fisico_swipes.jsonl (para ver qué haría)
  activo  decide: likea si pasa, si no descarta

Si algo falla (foto que no baja, modelo que no carga, tarjeta que cambió) devuelve None
y el swipe sigue con el ratio de siempre. Un filtro que traba el bot es peor que no tenerlo.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import random
import re
import threading
import time
from pathlib import Path

import requests
from PIL import Image
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
from selenium.webdriver.common.by import By

# windows sin modo desarrollador no soporta symlinks: el aviso de HF es ruido puro
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# descripciones por atributo: (positivas, negativas). CLIP anda mejor con frases enteras
# que con palabras sueltas, y mejor si la frase describe la foto y no a la persona.
# Cada atributo se puntúa con su propio softmax, así que no compiten entre ellos.
ATRIBUTOS = {
    "morocha": (["a photo of a woman with long dark brown hair",
                 "a photo of a brunette woman"],
                ["a photo of a woman with blonde hair",
                 "a photo of a woman with light brown hair"]),
    "rubia": (["a photo of a blonde woman"], ["a photo of a brunette woman"]),
    "delgada": (["a photo of a slim thin woman", "a photo of a slender woman"],
                ["a photo of a curvy woman with a fuller figure",
                 "a photo of a plus size woman"]),
    "tatuajes": (["a photo of a woman with visible tattoos"], ["a photo of a woman without tattoos"]),
    "ojos claros": (["a close up portrait of a woman with light blue or green eyes"],
                    ["a close up portrait of a woman with dark brown eyes"]),
    "busto grande": (["a photo of a woman with a large bust", "a photo of a busty woman"],
                     ["a photo of a woman with a small bust", "a photo of a flat chested woman"]),
    "pelo largo": (["a photo of a woman with long hair"], ["a photo of a woman with short hair"]),
    "lentes": (["a photo of a woman wearing glasses"], ["a photo of a woman without glasses"]),
    "sonrisa": (["a photo of a smiling happy woman"], ["a photo of a serious woman with a neutral face"]),
}

DEFAULT = {
    "activo": False,
    "modo": "sombra",              # sombra | activo
    "max_vistos": 60,              # corta el swipe después de N tarjetas evaluadas
    "min_fotos": 1,                # menos fotos que esto → no decide
    "max_fotos": 9,                # fotos que se miran por perfil (Tinder permite hasta 9)
    "obligatorio": [],             # quiero: si falta uno, no le da like
    "excluir": [],                 # evitar: si aparece uno, no le da like
    "modelo": "ViT-B-32",
    "checkpoint": "laion2b_s34b_b79k",
    "fallback": "like",            # like | dislike, cuando no hay veredicto
    "corte": 0.55,                 # probabilidad para dar un atributo por presente
    "corte_incierto": 0.08,        # si ningún atributo se aparta de 0.5, no decide
}

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_CACHE_MAX = 5000
_modelo = None
_modelo_lock = threading.Lock()


def completar(opciones):
    cfg = dict(DEFAULT)
    cfg.update({k: v for k, v in (opciones or {}).items() if k in DEFAULT})
    cfg["activo"] = bool(cfg["activo"])
    try:
        cfg["max_fotos"] = max(1, min(9, int(cfg["max_fotos"])))
    except (TypeError, ValueError):
        cfg["max_fotos"] = DEFAULT["max_fotos"]
    if cfg["modo"] not in ("sombra", "activo"):
        cfg["modo"] = "sombra"
    cfg["excluir"] = [a for a in (cfg.get("excluir") or []) if a in ATRIBUTOS]
    # si un rasgo viene en las dos listas, evitar gana
    cfg["obligatorio"] = [a for a in (cfg.get("obligatorio") or [])
                          if a in ATRIBUTOS and a not in cfg["excluir"]]
    return cfg


def descripciones():
    """Para la interfaz: atributos disponibles."""
    return list(ATRIBUTOS)


def disponible():
    """Si están instaladas las dependencias del filtro (requirements-fisico.txt, varios GB por torch)."""
    import importlib.util
    return all(importlib.util.find_spec(m) for m in ("open_clip", "torch"))


def _cargar_modelo(nombre, checkpoint):
    """Singleton: cargar los pesos tarda unos segundos y no se puede repetir por tarjeta."""
    global _modelo
    with _modelo_lock:
        if _modelo is not None:
            return _modelo
        import open_clip
        import torch

        modelo, _, preproceso = open_clip.create_model_and_transforms(nombre, pretrained=checkpoint, device="cpu")
        modelo.eval()
        _modelo = (modelo, preproceso, open_clip.get_tokenizer(nombre), torch)
        return _modelo


def _clave(fotos):
    return hashlib.md5("|".join(fotos).encode()).hexdigest()[:16]


class Filtro:

    def __init__(self, driver, root, opciones=None, log=print, api=None):
        self.driver = driver
        # TinderApi: trae todas las fotos de cada perfil. Sin ella solo se ven las de la tarjeta
        self.api = api
        self._indice = {}      # id de foto -> urls de todas las fotos de ese perfil
        self._fallos_api = 0
        self.cfg = completar(opciones)
        self.log = log
        self.root = Path(root) / "data"
        # v2: las probabilidades son la mejor foto de cada rasgo; las de v1 eran promedios y no sirven
        self.cache_path = self.root / "fisico_cache_v2.json"
        self.swipes_path = self.root / "fisico_swipes.jsonl"
        self.cache = self._cargar_cache()
        self.vistos = 0
        self.likes = 0
        self.rechazos = 0
        self.inciertos = 0
        self.ultimo_error = None
        self._prompts = None

    # --- lectura de la tarjeta ---

    def fotos(self):
        """URLs de las fotos de la tarjeta visible, sin abrir el perfil. Vacío si no hay."""
        encontradas = []
        for xpath in ("//div[@aria-label='Profile slider']",
                      "//img[contains(@src, 'images-ssl.gotinder.com')]"):
            try:
                for el in self.driver.find_elements(By.XPATH, xpath):
                    url = self._url_de(el)
                    if url and url not in encontradas:
                        encontradas.append(url)
            except (StaleElementReferenceException, WebDriverException):
                continue
            if encontradas:
                break
        return encontradas[: self.cfg["max_fotos"]]

    @staticmethod
    def _url_de(elemento):
        try:
            if elemento.tag_name == "img":
                url = elemento.get_attribute("src") or ""
            else:
                url = elemento.value_of_css_property("background-image") or ""
                url = url.split('"')[1] if '"' in url else ""
        except (StaleElementReferenceException, WebDriverException):
            return None
        # las de perfil vienen con el id de la persona adelante y un hash atrás
        if not url.startswith("https://"):
            return None
        return re.sub(r"(?<=\.jpg).*$", "?image_size=640x800", url) if "?" not in url else url

    def _cargar_recs(self):
        """Pide el mazo a la API y anota las fotos completas de cada perfil."""
        data = self.api._request("GET", "/v2/recs/core?locale=es")["data"]
        if len(self._indice) > 400:
            self._indice.clear()
        for rec in data.get("results", []):
            fotos = [p.get("url") for p in (rec.get("user") or {}).get("photos") or [] if p.get("url")]
            if not fotos:
                continue
            # la tarjeta muestra una foto cualquiera: se indexa por el id de cada una
            for url in fotos:
                for pid in _UUID.findall(url):
                    self._indice[pid] = fotos

    def _perfil_completo(self, visibles):
        """Todas las fotos del perfil (hasta max_fotos). Si la API no sirve, las de la tarjeta."""
        if self.api is None or self._fallos_api >= 3:
            return visibles
        ids = _UUID.findall(visibles[0])
        if not ids:
            return visibles
        for intento in range(2):
            for pid in ids:
                if pid in self._indice:
                    return self._indice[pid][: self.cfg["max_fotos"]]
            if intento == 0:
                try:
                    self._cargar_recs()
                    self._fallos_api = 0
                except Exception as exc:
                    self._fallos_api += 1
                    self.ultimo_error = f"recs: {exc}"
                    if self._fallos_api >= 3:
                        self.log("Filtro físico: la API de fotos falla, se usan solo las fotos de la tarjeta.")
                    return visibles
        return visibles

    # --- evaluación ---

    def _vectores_texto(self):
        if self._prompts is None:
            modelo, _, tokenizer, torch = _cargar_modelo(self.cfg["modelo"], self.cfg["checkpoint"])
            prompts, indices = [], []
            for nombre, (positivas, negativas) in ATRIBUTOS.items():
                prompts.extend(positivas + negativas)
                # una sola entrada por atributo: (nombre, cantidad de prompts, cuántos son positivos)
                indices.append((nombre, len(positivas) + len(negativas), len(positivas)))
            with torch.no_grad():
                tokens = tokenizer(prompts)
                vectores = modelo.encode_text(tokens)
                vectores /= vectores.norm(dim=-1, keepdim=True)
            self._prompts = (vectores, indices, modelo)
        return self._prompts

    def _bajar(self, url):
        respuesta = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        respuesta.raise_for_status()
        if "image" not in respuesta.headers.get("Content-Type", ""):
            raise ValueError(f"no es una imagen ({respuesta.headers.get('Content-Type')})")
        imagen = Image.open(io.BytesIO(respuesta.content)).convert("RGB")
        # recorte central: saca fondo y gente de los costados en fotos grupales
        ancho, alto = imagen.size
        margen_x, margen_y = int(ancho * 0.08), int(alto * 0.08)
        return imagen.crop((margen_x, margen_y, ancho - margen_x, alto - margen_y))

    def _evaluar(self, fotos):
        """Probabilidad por atributo, tomando la mejor foto de cada uno (si se ve en una, cuenta).
        None si no bajó ninguna."""
        self.ultimo_error = None
        vectores, indices, modelo = self._vectores_texto()
        torch = _modelo[3]
        preproceso = _modelo[1]
        mejor = {nombre: 0.0 for nombre in ATRIBUTOS}
        usadas = 0
        for url in fotos:
            try:
                imagen = self._bajar(url)
            except Exception as exc:
                self.ultimo_error = self.ultimo_error or f"{type(exc).__name__}: {exc}"
                continue
            with torch.no_grad():
                tensor = preproceso(imagen).unsqueeze(0)
                vector = modelo.encode_image(tensor)
                vector /= vector.norm(dim=-1, keepdim=True)
                logits = (modelo.logit_scale.exp() * vector @ vectores.T)[0]
            # softmax POR atributo: cada uno reparte su propia masa entre su positivo y su negativo
            inicio = 0
            for nombre, total, positivas in indices:
                tramo = logits[inicio:inicio + total]
                p = float(tramo.softmax(dim=-1)[:positivas].sum())
                mejor[nombre] = max(mejor[nombre], p)
                inicio += total
            usadas += 1
        if not usadas:
            return None
        return {nombre: round(valor, 3) for nombre, valor in mejor.items()}

    def _veredicto(self, probabilidades):
        corte = self.cfg["corte"]
        quiero, evitar = self.cfg["obligatorio"], self.cfg["excluir"]
        # si ninguno de los rasgos elegidos se aparta de 0.5, las fotos no dicen nada: no decide
        if max(abs(probabilidades.get(a, 0.5) - 0.5) for a in quiero + evitar) < self.cfg["corte_incierto"]:
            return None

        faltan = [a for a in quiero if probabilidades.get(a, 0) < corte]
        sobran = [a for a in evitar if probabilidades.get(a, 0) >= corte]
        # solo informativo (para mirar el registro): qué tanto se ven los rasgos que quiero
        score = round(100 * sum(probabilidades.get(a, 0) for a in quiero) / len(quiero)) if quiero else 100
        return {"score": score, "pasa": not (faltan or sobran), "rasgos": probabilidades,
                "faltan": faltan, "sobran": sobran}

    # --- decisión ---

    @property
    def agotado(self):
        return self.vistos >= self.cfg["max_vistos"]

    def decidir(self):
        """True likea, False descarta, None no decide (sombra, sin fotos, error, desincronizado)."""
        if self.agotado:
            return None
        if not (self.cfg["obligatorio"] or self.cfg["excluir"]):
            return None  # no elegiste ningún rasgo: no hay nada que filtrar
        try:
            visibles = self.fotos()
            if len(visibles) < max(1, self.cfg["min_fotos"]):
                return self._fallback("sin fotos")
            fotos = self._perfil_completo(visibles)
            clave = _clave(fotos)

            # se cachean las probabilidades, no el veredicto: si cambiás umbral o pesos,
            # las fotos ya vistas se vuelven a juzgar con la configuración nueva
            probabilidades = self.cache.get(clave)
            if probabilidades and "rasgos" in probabilidades:  # formato viejo: veredicto entero
                probabilidades = probabilidades["rasgos"]
            # si se agregó un rasgo después de cachear la foto, se vuelve a evaluar
            if probabilidades is None or any(a not in probabilidades for a in ATRIBUTOS):
                probabilidades = self._evaluar(fotos)
                if probabilidades is None:
                    return self._fallback(f"no se pudo bajar la foto — {self.ultimo_error}")
                self._guardar_cache(clave, probabilidades)
            veredicto = self._veredicto(probabilidades)
            if veredicto is None:
                return self._fallback("foto que no dice nada")

            self.vistos += 1
            # la tarjeta pudo cambiar mientras se evaluaba: si cambió, no se aplica el veredicto
            if self.fotos()[:1] != visibles[:1]:
                self.inciertos += 1
                return self._fallback("tarjeta cambiada")

            self._anotar(clave, fotos, veredicto, sombra=self.cfg["modo"] == "sombra")
            if veredicto["pasa"]:
                self.likes += 1
            else:
                self.rechazos += 1

            if self.cfg["modo"] == "sombra":
                return None
            return veredicto["pasa"]
        except Exception as exc:
            return self._fallback(f"error: {exc}")

    def _fallback(self, motivo):
        self.inciertos += 1
        if self.cfg["modo"] == "sombra":
            return None  # en sombra nunca decide, tampoco cuando falla: sigue el ratio de siempre
        if self.cfg["fallback"] == "like":
            self.likes += 1
            return True
        self.rechazos += 1
        return False

    def resumen(self):
        return (f"Físico: {self.vistos} evaluadas, {self.likes} pasan, {self.rechazos} descartes, "
                f"{self.inciertos} sin veredicto (modo {self.cfg['modo']}).")

    # --- persistencia ---

    def _anotar(self, clave, fotos, veredicto, sombra):
        """Una línea por tarjeta, para calibrar el umbral después con datos reales."""
        self.root.mkdir(exist_ok=True)
        linea = json.dumps({"clave": clave, "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "foto": fotos[0], "n_fotos": len(fotos), "sombra": sombra, **veredicto}, ensure_ascii=False)
        with self.swipes_path.open("a", encoding="utf-8") as f:
            f.write(linea + "\n")

    def _cargar_cache(self):
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _guardar_cache(self, clave, veredicto):
        self.cache[clave] = veredicto
        if len(self.cache) > _CACHE_MAX:
            # se van los más viejos: el dict conserva el orden de inserción
            for vieja in list(self.cache)[: len(self.cache) - _CACHE_MAX]:
                self.cache.pop(vieja, None)
        self.root.mkdir(exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")


# --- CLI: probar una foto suelta y calibrar con lo anotado ---

def _probar(fuente, opciones):
    """fuente: una URL http(s) o la ruta a un archivo local."""
    filtro = Filtro(driver=None, root=".", opciones=opciones)
    if not fuente.startswith("http"):
        ruta = Path(fuente).resolve()
        if not ruta.exists():
            print(f"No existe: {ruta}")
            return
        crudo = ruta.read_bytes()
        print(f"{ruta.name}: {len(crudo)} bytes, empieza con {crudo[:4].hex(' ')}")
        if not crudo:
            print("Archivo vacío.")
            return
        filtro._bajar = lambda _: Image.open(io.BytesIO(crudo)).convert("RGB")

    probabilidades = filtro._evaluar([fuente])
    if probabilidades is None:
        print(f"No se pudo evaluar: {filtro.ultimo_error}")
        return
    print(json.dumps(probabilidades, indent=2, ensure_ascii=False))
    veredicto = filtro._veredicto(probabilidades)
    print(json.dumps(veredicto, indent=2, ensure_ascii=False) if veredicto
          else "Incierto: ningún atributo se aparta de 0.5.")


def _calibrar():
    """Acuerdo entre el veredicto y lo que swipeaste a mano, por umbral."""
    ruta = Path("data/fisico_swipes.jsonl")
    if not ruta.exists():
        print("No hay data/fisico_swipes.jsonl. Corré primero en modo sombra.")
        return
    filas = [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]
    reales = [f for f in filas if f.get("swipe") in (True, False)]
    if not reales:
        print(f"{len(filas)} tarjetas anotadas, ninguna con tu swipe real todavía.")
        return
    print(f"{len(reales)} tarjetas con tu decisión real.\n")
    print(" umbral  likes  aciertos  falsos positivos")
    for umbral in range(40, 91, 5):
        elige = [f for f in reales if f["score"] >= umbral]
        bien = sum(1 for f in elige if f["swipe"])
        print(f"  {umbral:>5}  {len(elige):>5}  {bien / max(1, len(elige)):>8.0%}  "
              f"{len(elige) - bien:>16}")


if __name__ == "__main__":
    import sys

    if "--calibrar" in sys.argv:
        _calibrar()
    elif "--probar" in sys.argv:
        _probar(sys.argv[sys.argv.index("--probar") + 1], None)
    else:
        print("Uso:  python -m loveworm.helpers.fisico --probar <url | ruta a un jpg>")
        print("      python -m loveworm.helpers.fisico --calibrar")