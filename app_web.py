"""App web del asistente (Gradio). Cada persona usa su propia clave de Gemini (D25).

Uso local:
    pip install -r requirements-web.txt
    python app_web.py                 # abre http://localhost:7860

En Hugging Face Spaces se arranca con despliegue/arrancar.sh (ver despliegue/README.md).

Variables de entorno opcionales:
    CODIGO_ACCESO      si existe, la app pide este código antes de responder.
    GH_TOKEN_DATOS     token de solo lectura del repo privado; con él la app trae
                       periódicamente los documentos nuevos (git pull).
    REFRESCO_MIN       cada cuántos minutos busca documentos nuevos (30 por defecto).
"""
from __future__ import annotations

import base64
import html
import os
import re
import subprocess
import threading
import time
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore", category=SyntaxWarning)
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr  # noqa: E402

from rag import config  # noqa: E402
from rag.asistente import responder  # noqa: E402
from rag.busqueda import Indice  # noqa: E402
from rag.llm import ClaveInvalida, CuotaAgotada  # noqa: E402
from rag.manifiesto import cargar_manifiesto  # noqa: E402

CODIGO_ACCESO = os.environ.get("CODIGO_ACCESO", "").strip()
REFRESCO_MIN = float(os.environ.get("REFRESCO_MIN", "30"))
REINTENTOS_WEB = 3  # en la web es mejor avisar pronto que esperar minutos

EJEMPLOS = [
    "¿Qué pines GPIO del ESP32 son solo de entrada?",
    "¿Qué fuerza electromotriz genera un termopar tipo K a 125 °C?",
    "¿Qué MOSFET se puede manejar directamente con los 5 V de un microcontrolador?",
    "¿Cómo se calculan los tiempos en alto y en bajo del NE555 en modo astable?",
    "¿Qué tipos de termopar admite el módulo AI 8xU/I/RTD/TC ST?",
]


# --- Base de conocimiento ------------------------------------------------------

class Base:
    """Índice en memoria y su actualización periódica desde el repo privado."""

    def __init__(self) -> None:
        self.candado = threading.Lock()
        self.indice: Indice | None = None
        self.documentos: list = []
        self.version = ""
        self.cargada_en = ""

    def cargar(self) -> None:
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
        nada (las respuestas en caché son las mismas para la misma clave de caché)."""
        antes = _git("rev-parse", "HEAD")
        if not antes:
            return False
        _git("fetch", "--quiet", autenticado=True)
        remoto = _git("rev-parse", "@{u}")
        if not remoto or remoto == antes:
            return False
        _git("reset", "--hard", "--quiet", remoto)
        self.cargar()
        return True

    def ciclo_actualizacion(self) -> None:
        while True:
            time.sleep(REFRESCO_MIN * 60)
            try:
                if self.actualizar():
                    print("Base de conocimiento actualizada.")
            except Exception as exc:  # nunca tumbar la app por una actualización
                print(f"No se pudo actualizar la base: {type(exc).__name__}")


def _git(*args: str, autenticado: bool = False) -> str:
    """Ejecuta git en la carpeta de conocimiento. El token va en una cabecera
    temporal: no queda escrito en .git/config ni en la URL del remoto."""
    if not (config.DIR_CONOCIMIENTO / ".git").exists():
        return ""
    cmd = ["git", "-C", str(config.DIR_CONOCIMIENTO)]
    token = os.environ.get("GH_TOKEN_DATOS", "").strip()
    if autenticado and token:
        cred = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        cmd += ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {cred}"]
    try:
        r = subprocess.run(cmd + list(args), capture_output=True, text=True, timeout=120)
    except Exception:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


BASE = Base()


# --- Presentación --------------------------------------------------------------

_CITA = re.compile(r"\[([a-z0-9_.\-]+),\s*p[áa]g(?:ina|s)?\.?\s*([\d\s,y\-–]+)\]", re.IGNORECASE)


def _resaltar_citas(texto: str) -> str:
    return _CITA.sub(lambda m: f"<span class='cita'>{m.group(1)} · pág. {m.group(2).strip()}</span>", texto)


def _fuentes(r) -> str:
    """Lista de documentos citados, con sus páginas agrupadas."""
    nombres = {f.chunk.doc_id: f.chunk.nombre for f in r.fragmentos}
    paginas: dict[str, list[int]] = {}
    for doc, pag in r.citas:
        if pag not in paginas.setdefault(doc, []):
            paginas[doc].append(pag)
    filas = []
    for doc, pags in paginas.items():
        pags = sorted(pags)
        etiqueta = "pág." if len(pags) == 1 else "págs."
        filas.append(f"- **{html.escape(nombres.get(doc, doc))}** ({doc}), {etiqueta} "
                     + ", ".join(map(str, pags)))
    return "\n\n**Fuentes**\n" + "\n".join(filas) if filas else ""


def _fragmentos_md(r) -> str:
    if not r.fragmentos:
        return ""
    partes = [f"Estos son los {len(r.fragmentos)} fragmentos que recibió el modelo, en el orden "
              "que les dio el reordenador:\n"]
    for f in r.fragmentos:
        c = f.chunk
        partes.append(f"#### {f.rango}. {html.escape(c.nombre)} — pág. {c.pagina}\n"
                      f"<small>`{c.doc_id}` · puntaje {f.puntaje:.3f}</small>\n\n{c.texto}\n\n---")
    return "\n".join(partes)


def _lista_documentos() -> str:
    with BASE.candado:
        docs, version, fecha = list(BASE.documentos), BASE.version, BASE.cargada_en
        n_frag = len(BASE.indice.chunks) if BASE.indice else 0
    familias: dict[str, list] = {}
    for d in docs:
        familias.setdefault(d.familia, []).append(d)
    lineas = [f"**{len(docs)} documentos · {n_frag} fragmentos** · versión `{version}` · cargada {fecha}\n"]
    for fam in sorted(familias):
        lineas.append(f"\n**{fam}**")
        for d in sorted(familias[fam], key=lambda x: x.nombre):
            lineas.append(f"- {html.escape(d.nombre)} <small>({d.fabricante})</small>")
    return "\n".join(lineas)


# --- Lógica de la app ------------------------------------------------------------

def preguntar(pregunta: str, historial: list, clave: str, codigo: str):
    pregunta = (pregunta or "").strip()
    historial = list(historial or [])
    if not pregunta:
        yield historial, gr.update(), gr.update()
        return
    clave = (clave or "").strip()
    if CODIGO_ACCESO and (codigo or "").strip() != CODIGO_ACCESO:
        gr.Warning("El código de acceso no es correcto.", title="Atención")
        yield historial, gr.update(), gr.update(value=pregunta)
        return
    if not clave:
        gr.Warning("Primero escribe tu clave de la API de Gemini (panel de la izquierda).",
                   title="Falta tu clave")
        yield historial, gr.update(), gr.update(value=pregunta)
        return

    historial += [{"role": "user", "content": pregunta},
                  {"role": "assistant", "content": "_Buscando en los datasheets y redactando… (suele tardar entre 15 s y 1 min)_"}]
    yield historial, gr.update(), ""

    with BASE.candado:
        indice = BASE.indice
    inicio = time.perf_counter()
    try:
        r = responder(pregunta, indice, respaldos=config.MODELOS_RESPALDO, api_key=clave,
                      reintentos_final=REINTENTOS_WEB)
    except ClaveInvalida:
        historial[-1]["content"] = ("⚠️ Google rechazó la clave. Revisa que esté bien copiada "
                                    "(empieza por `AIza`) y que siga activa en "
                                    "[AI Studio](https://aistudio.google.com/apikey).")
        yield historial, gr.update(), gr.update(value=pregunta)
        return
    except CuotaAgotada:
        historial[-1]["content"] = ("⚠️ Tu clave agotó la cuota gratuita de todos los modelos "
                                    "por ahora. Intenta en unos minutos o mañana.")
        yield historial, gr.update(), gr.update(value=pregunta)
        return
    except Exception as exc:
        historial[-1]["content"] = (f"⚠️ Los servidores de Google no respondieron "
                                    f"({type(exc).__name__}). Intenta de nuevo en un momento.")
        yield historial, gr.update(), gr.update(value=pregunta)
        return

    pie = f"\n\n<small>{r.llm.modelo} · {time.perf_counter() - inicio:.0f} s"
    if r.llm.desde_cache:
        pie += " · respuesta guardada (no gastó cuota)"
    if r.modelo_respaldo:
        pie += f" · respondió el modelo de respaldo porque {config.MODELO_LLM} no estaba disponible"
    pie += "</small>"
    historial[-1]["content"] = _resaltar_citas(r.texto) + _fuentes(r) + pie
    yield historial, gr.update(value=_fragmentos_md(r)), ""


def recordar_clave(clave: str, recordar: bool):
    return (clave or "").strip() if recordar else ""


def al_cargar(guardada: str):
    guardada = guardada or ""
    return gr.update(value=guardada), gr.update(value=bool(guardada)), _lista_documentos()


# --- Interfaz ------------------------------------------------------------------

CSS = """
.cita { background: var(--color-accent-soft); color: var(--body-text-color);
        border-radius: 4px; padding: 0 4px; font-size: .88em; white-space: nowrap; }
#encabezado h1 { margin-bottom: 0; }
#encabezado p { margin-top: .25rem; color: var(--body-text-color-subdued); }
"""

TEMA = gr.themes.Soft(primary_hue="teal", neutral_hue="slate")


def construir_app() -> gr.Blocks:
    with gr.Blocks(title="Asistente de datasheets") as app:
        guardada = gr.BrowserState("", storage_key="rag_datasheets_clave")
        with gr.Column(elem_id="encabezado"):
            gr.Markdown("# Asistente de datasheets de mecatrónica\n"
                        "Responde preguntas técnicas citando el documento y la página. "
                        "Si el dato no está en la documentación, lo dice en lugar de inventarlo.")
        with gr.Row(equal_height=False):
            with gr.Column(scale=1, min_width=280):
                clave = gr.Textbox(label="Tu clave de la API de Gemini", type="password",
                                   placeholder="AIza…")
                recordar = gr.Checkbox(label="Recordarla en este navegador", value=False)
                gr.Markdown(
                    "<small>¿No tienes una? Créala gratis en "
                    "[aistudio.google.com/apikey](https://aistudio.google.com/apikey) con tu "
                    "cuenta de Google (1 minuto). La clave se usa solo para tus preguntas: "
                    "no se guarda en el servidor ni se comparte.</small>")
                codigo = gr.Textbox(label="Código de acceso", type="password",
                                    visible=bool(CODIGO_ACCESO))
                with gr.Accordion("Documentos disponibles", open=False):
                    documentos = gr.Markdown()
                with gr.Accordion("Cómo funciona", open=False):
                    gr.Markdown(
                        "1. Tu pregunta se compara con unos 1700 fragmentos de los datasheets "
                        "(búsqueda semántica multilingüe).\n"
                        "2. Un segundo modelo reordena los 30 mejores y se quedan 5.\n"
                        f"3. **{config.MODELO_LLM}** redacta la respuesta usando solo esos 5 "
                        "fragmentos y cita cada dato.\n\n"
                        "En la evaluación con 66 preguntas acertó el 83 % (sin documentos, el "
                        "mismo modelo acierta el 58 % e inventa datos en el 21 %).")
            with gr.Column(scale=3):
                chat = gr.Chatbot(label="Conversación", height=520, show_label=False,
                                  sanitize_html=True, render_markdown=True,
                                  placeholder="Haz una pregunta o elige un ejemplo.")
                with gr.Row():
                    pregunta = gr.Textbox(show_label=False, scale=5, autofocus=True,
                                          placeholder="Ej.: ¿Cuál es el rango de VDD del STM32F767?")
                    enviar = gr.Button("Preguntar", variant="primary", scale=1, min_width=110)
                gr.Examples(EJEMPLOS, inputs=pregunta, label="Ejemplos")
                with gr.Accordion("Fragmentos consultados en la última respuesta", open=False):
                    fragmentos = gr.Markdown("Aún no hay respuesta.")
                limpiar = gr.Button("Borrar conversación", size="sm", variant="secondary")

        entradas = [pregunta, chat, clave, codigo]
        salidas = [chat, fragmentos, pregunta]
        enviar.click(preguntar, entradas, salidas, concurrency_limit=4, api_visibility="private")
        pregunta.submit(preguntar, entradas, salidas, concurrency_limit=4, api_visibility="private")
        limpiar.click(lambda: ([], "Aún no hay respuesta."), None, [chat, fragmentos],
                      api_visibility="private")
        for evento in (clave.change, recordar.change):
            evento(recordar_clave, [clave, recordar], guardada, api_visibility="private")
        app.load(al_cargar, guardada, [clave, recordar, documentos], api_visibility="private")
    return app


def main() -> None:
    print("Cargando índice y modelos de búsqueda...")
    BASE.cargar()
    if os.environ.get("GH_TOKEN_DATOS") and REFRESCO_MIN > 0:
        threading.Thread(target=BASE.ciclo_actualizacion, daemon=True).start()
    app = construir_app()
    app.queue(default_concurrency_limit=4).launch(
        server_name=os.environ.get("HOST", "0.0.0.0"),
        server_port=int(os.environ.get("PORT", "7860")),
        theme=TEMA, css=CSS, footer_links=["settings"],
        blocked_paths=[str(config.DIR_CONOCIMIENTO), str(config.RAIZ_CODIGO / ".env")],
    )


if __name__ == "__main__":
    main()
