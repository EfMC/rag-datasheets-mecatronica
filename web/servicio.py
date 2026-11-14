"""Lógica de la app web, independiente de la interfaz (D25).

- `preparar_conocimiento`: en el servidor, clona el repo privado con un token de solo
  lectura. Hay que llamarla ANTES de importar `rag`, porque `rag.config` fija las rutas
  al importarse.
- `Base`: el índice en memoria y su actualización periódica desde el repo privado.
- Funciones de presentación: citas resaltadas, lista de fuentes y fragmentos.
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ_CODIGO = Path(__file__).resolve().parent.parent
REPO_DATOS_DEFECTO = "EfMC/rag-datasheets-datos"


def _cabecera(token: str) -> list[str]:
    """El token viaja en una cabecera temporal: no queda en .git/config ni en la URL."""
    if not token:
        return []
    cred = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {cred}"]


def preparar_conocimiento(token: str, repo: str = REPO_DATOS_DEFECTO) -> str:
    """Deja la base de conocimiento lista y devuelve un mensaje de error ('' si todo va bien).

    Si ya hay una (RAG_CONOCIMIENTO, conocimiento/ junto al código o el diseño de OneDrive),
    no hace nada. Si no, clona el repo privado en conocimiento/."""
    if os.environ.get("RAG_CONOCIMIENTO") or (RAIZ_CODIGO / "conocimiento" / "manifiesto.csv").exists():
        return ""
    if (RAIZ_CODIGO / "manifiesto.csv").exists():  # diseño original en OneDrive
        return ""
    if not token:
        return ("Falta el secreto GH_TOKEN_DATOS: sin él la app no puede descargar la base de "
                "conocimiento privada.")
    destino = RAIZ_CODIGO / "conocimiento"
    try:
        r = subprocess.run(["git", *_cabecera(token), "clone", "--quiet",
                            f"https://github.com/{repo}.git", str(destino)],
                           capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        return "El servidor no tiene git instalado (packages.txt debe incluir 'git')."
    if r.returncode != 0:
        return (f"No se pudo descargar {repo}. Revisa que GH_TOKEN_DATOS tenga permiso de "
                "lectura (Contents: Read-only) sobre ese repositorio y que no haya vencido.")
    return ""


def _git(*args: str, token: str = "") -> str:
    from rag import config
    if not (config.DIR_CONOCIMIENTO / ".git").exists():
        return ""
    try:
        r = subprocess.run(["git", "-C", str(config.DIR_CONOCIMIENTO), *_cabecera(token), *args],
                           capture_output=True, text=True, timeout=120)
    except Exception:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


class Base:
    """Índice en memoria compartido por todas las sesiones."""

    def __init__(self, token: str = "", refresco_min: float = 30) -> None:
        self.token, self.refresco_min = token, refresco_min
        self.candado = threading.Lock()
        self.indice = None
        self.documentos: list = []
        self.version = ""
        self.cargada_en = ""

    def cargar(self) -> None:
        from rag import config
        from rag.busqueda import Indice
        from rag.manifiesto import cargar_manifiesto
        inicio = time.perf_counter()
        indice = Indice(config.MODO_DEFECTO, config.TAMANO_CHUNK).construir()
        indice.buscar("calentamiento", k=1, metodo=config.METODO_DEFECTO)  # carga los modelos ya
        docs = cargar_manifiesto(solo_incluidos=True)
        with self.candado:
            self.indice, self.documentos = indice, docs
            self.version = _git("rev-parse", "--short", "HEAD") or "local"
            self.cargada_en = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        print(f"Base cargada: {len(docs)} documentos, {len(indice.chunks)} fragmentos, "
              f"versión {self.version} ({time.perf_counter() - inicio:.0f} s)")

    def actualizar(self) -> bool:
        """Trae el repo privado y recarga el índice si llegó algo nuevo.

        Usa fetch + reset --hard en lugar de pull: la app escribe respuestas nuevas en la
        caché de esa carpeta, y un archivo que también llegue del remoto haría fallar el
        pull para siempre. La copia del servidor nunca hace commits, así que no se pierde
        nada (una misma clave de caché corresponde a la misma respuesta)."""
        antes = _git("rev-parse", "HEAD")
        if not antes:
            return False
        _git("fetch", "--quiet", token=self.token)
        remoto = _git("rev-parse", "@{u}")
        if not remoto or remoto == antes:
            return False
        _git("reset", "--hard", "--quiet", remoto)
        self.cargar()
        return True

    def iniciar_actualizacion_periodica(self) -> None:
        if not self.token or self.refresco_min <= 0:
            return

        def ciclo() -> None:
            while True:
                time.sleep(self.refresco_min * 60)
                try:
                    if self.actualizar():
                        print("Base de conocimiento actualizada.")
                except Exception as exc:  # nunca tumbar la app por una actualización
                    print(f"No se pudo actualizar la base: {type(exc).__name__}")

        threading.Thread(target=ciclo, daemon=True, name="actualizar-base").start()


# --- Presentación --------------------------------------------------------------

_CITA = re.compile(r"\[([a-z0-9_.\-]+),\s*p[áa]g(?:ina|s)?\.?\s*([\d\s,y\-–]+)\]", re.IGNORECASE)


def resaltar_citas(texto: str) -> str:
    """[doc, pág. N] → etiqueta resaltada de Streamlit."""
    return _CITA.sub(lambda m: f":blue-background[{m.group(1)} · pág. {m.group(2).strip()}]", texto)


def fuentes_md(r) -> str:
    """Documentos citados, con sus páginas agrupadas."""
    nombres = {f.chunk.doc_id: f.chunk.nombre for f in r.fragmentos}
    paginas: dict[str, list[int]] = {}
    for doc, pag in r.citas:
        if pag not in paginas.setdefault(doc, []):
            paginas[doc].append(pag)
    filas = []
    for doc, pags in paginas.items():
        pags = sorted(pags)
        etiqueta = "pág." if len(pags) == 1 else "págs."
        filas.append(f"- **{nombres.get(doc, doc)}** ({doc}), {etiqueta} " + ", ".join(map(str, pags)))
    return "**Fuentes**\n" + "\n".join(filas) if filas else ""


def fragmentos_md(r) -> str:
    partes = []
    for f in r.fragmentos:
        c = f.chunk
        partes.append(f"**{f.rango}. {c.nombre} — pág. {c.pagina}** · `{c.doc_id}` · "
                      f"puntaje {f.puntaje:.2f}\n\n{c.texto}")
    return "\n\n---\n\n".join(partes)


def documentos_md(base: Base) -> str:
    with base.candado:
        docs, version, fecha = list(base.documentos), base.version, base.cargada_en
        n_frag = len(base.indice.chunks) if base.indice else 0
    familias: dict[str, list] = {}
    for d in docs:
        familias.setdefault(d.familia, []).append(d)
    lineas = [f"**{len(docs)} documentos · {n_frag} fragmentos**  \nversión `{version}` · {fecha}"]
    for fam in sorted(familias):
        lineas.append(f"\n**{fam}**")
        lineas += [f"- {d.nombre} ({d.fabricante})" for d in sorted(familias[fam], key=lambda x: x.nombre)]
    return "\n".join(lineas)
