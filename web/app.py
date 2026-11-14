"""App web del asistente (Streamlit). Cada persona usa su propia clave de Gemini (D25).

Uso local:
    pip install -r web/requirements.txt
    streamlit run web/app.py          # abre http://localhost:8501

Publicación en Streamlit Community Cloud: ver despliegue/README.md.

Secretos (Streamlit Cloud: Settings → Secrets; en local, variables de entorno):
    GH_TOKEN_DATOS   token de GitHub de solo lectura sobre el repo privado de datos.
    CODIGO_ACCESO    opcional: si existe, la app lo pide antes de responder.
    REPO_DATOS       opcional: por defecto EfMC/rag-datasheets-datos.
    REFRESCO_MIN     opcional: cada cuántos minutos busca documentos nuevos (30).
"""
from __future__ import annotations

import os
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=SyntaxWarning)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # paquete rag/

import streamlit as st  # noqa: E402

import servicio  # noqa: E402  (web/ ya está en sys.path: es la carpeta del script)

st.set_page_config(page_title="Asistente de datasheets", page_icon="🔧", layout="wide")


def secreto(nombre: str, defecto: str = "") -> str:
    try:
        valor = st.secrets.get(nombre)
    except Exception:  # no hay archivo de secretos (uso local)
        valor = None
    return str(valor if valor is not None else os.environ.get(nombre, defecto)).strip()


TOKEN = secreto("GH_TOKEN_DATOS")
CODIGO_ACCESO = secreto("CODIGO_ACCESO")
REINTENTOS_WEB = 3  # en la web es mejor avisar pronto que esperar minutos

EJEMPLOS = [
    "¿Qué pines GPIO del ESP32 son solo de entrada?",
    "¿Qué fuerza electromotriz genera un termopar tipo K a 125 °C?",
    "¿Qué MOSFET se puede manejar directamente con los 5 V de un microcontrolador?",
    "¿Cómo se calculan los tiempos en alto y en bajo del NE555 en modo astable?",
]


@st.cache_resource(show_spinner="Preparando la base de conocimiento y los modelos "
                                "(la primera vez tarda 1–2 minutos)…")
def obtener_base():
    error = servicio.preparar_conocimiento(TOKEN, secreto("REPO_DATOS", servicio.REPO_DATOS_DEFECTO))
    if error:
        return None, error
    base = servicio.Base(TOKEN, float(secreto("REFRESCO_MIN", "30") or 30))
    base.cargar()
    base.iniciar_actualizacion_periodica()
    return base, ""


base, error_base = obtener_base()
if error_base:
    st.error(error_base)
    st.stop()

from rag import config  # noqa: E402  (después de preparar la base: fija las rutas)
from rag.asistente import responder  # noqa: E402
from rag.llm import ClaveInvalida, CuotaAgotada  # noqa: E402

# --- Barra lateral ---------------------------------------------------------------
with st.sidebar:
    with st.expander("Documentos disponibles"):
        st.markdown(servicio.documentos_md(base))
    with st.expander("Cómo funciona"):
        st.markdown(
            "1. Tu pregunta se compara con unos 1700 fragmentos de los datasheets "
            "(búsqueda semántica multilingüe).\n"
            "2. Un segundo modelo reordena los 30 mejores y se quedan 5.\n"
            f"3. **{config.MODELO_LLM}** redacta la respuesta usando solo esos 5 fragmentos "
            "y cita cada dato.\n\n"
            "En la evaluación con 66 preguntas acertó el 83 % (sin documentos, el mismo "
            "modelo acierta el 58 % e inventa datos en el 21 %).")
    if st.button("Borrar conversación", use_container_width=True):
        st.session_state.mensajes = []
        st.rerun()

# --- Conversación ----------------------------------------------------------------
st.title("Asistente de datasheets de mecatrónica")
st.caption("Responde preguntas técnicas citando el documento y la página. Si el dato no "
           "está en la documentación, lo dice en lugar de inventarlo.")

with st.expander("🔑 Tu clave de la API de Gemini", expanded=not st.session_state.get("clave")):
    clave = st.text_input("Clave de la API de Gemini", type="password", placeholder="Pega aquí tu clave",
                          key="clave", label_visibility="collapsed")
    st.caption("¿No tienes una? Créala gratis en [aistudio.google.com/apikey]"
               "(https://aistudio.google.com/apikey) con tu cuenta de Google (1 minuto). "
               "Se usa solo para tus preguntas: no se guarda en el servidor ni se comparte.")
    codigo = (st.text_input("Código de acceso", type="password", key="codigo")
              if CODIGO_ACCESO else "")

if "mensajes" not in st.session_state:
    st.session_state.mensajes = []


def mostrar(m: dict) -> None:
    with st.chat_message(m["rol"]):
        st.markdown(m["texto"])
        if m.get("fuentes"):
            st.markdown(m["fuentes"])
        if m.get("pie"):
            st.caption(m["pie"])
        if m.get("fragmentos"):
            with st.expander("Fragmentos consultados"):
                st.markdown(m["fragmentos"])


for m in st.session_state.mensajes:
    mostrar(m)

pregunta = st.chat_input("Ej.: ¿Cuál es el rango de VDD del STM32F767?")
if not st.session_state.mensajes and not pregunta:
    st.markdown("**Prueba con un ejemplo:**")
    columnas = st.columns(2)
    for i, ej in enumerate(EJEMPLOS):
        if columnas[i % 2].button(ej, key=f"ej{i}", use_container_width=True):
            pregunta = ej


def responder_web(pregunta: str) -> dict:
    with base.candado:
        indice = base.indice
    inicio = time.perf_counter()
    try:
        r = responder(pregunta, indice, respaldos=config.MODELOS_RESPALDO,
                      api_key=clave.strip(), reintentos_final=REINTENTOS_WEB)
    except ClaveInvalida:
        return {"rol": "assistant", "texto": "⚠️ Google rechazó la clave. Revisa que esté completa y bien "
                "copiada, y que siga activa en "
                "[AI Studio](https://aistudio.google.com/apikey)."}
    except CuotaAgotada:
        return {"rol": "assistant", "texto": "⚠️ Tu clave agotó la cuota gratuita de todos los "
                "modelos por ahora. Intenta en unos minutos o mañana."}
    except Exception as exc:
        return {"rol": "assistant", "texto": f"⚠️ Los servidores de Google no respondieron "
                f"({type(exc).__name__}). Intenta de nuevo en un momento."}
    pie = f"{r.llm.modelo} · {time.perf_counter() - inicio:.0f} s"
    if r.llm.desde_cache:
        pie += " · respuesta guardada (no gastó cuota)"
    if r.modelo_respaldo:
        pie += f" · respondió el modelo de respaldo porque {config.MODELO_LLM} no estaba disponible"
    return {"rol": "assistant", "texto": servicio.resaltar_citas(r.texto),
            "fuentes": servicio.fuentes_md(r), "pie": pie,
            "fragmentos": servicio.fragmentos_md(r)}


if pregunta:
    if CODIGO_ACCESO and codigo.strip() != CODIGO_ACCESO:
        st.warning("Escribe el código de acceso (recuadro 🔑 de arriba).")
    elif not clave.strip():
        st.warning("Primero escribe tu clave de la API de Gemini en el recuadro 🔑 de arriba.")
    else:
        usuario = {"rol": "user", "texto": pregunta}
        st.session_state.mensajes.append(usuario)
        mostrar(usuario)
        with st.chat_message("assistant"):
            with st.spinner("Buscando en los datasheets y redactando… (suele tardar entre 15 s y 1 min)"):
                respuesta = responder_web(pregunta)
        st.session_state.mensajes.append(respuesta)
        st.rerun()
