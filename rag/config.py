"""Rutas y parámetros globales del proyecto.

El código y la base de conocimiento están separados (D24):

- Código (repo público): este directorio, con rag/, los scripts, evaluacion/ y reportes/.
- Base de conocimiento (repo privado): los PDF, el manifiesto, el texto extraído, los
  índices y la caché de respuestas del LLM. Tiene esta estructura:

      <conocimiento>/
      ├── manifiesto.csv
      ├── datasheets/<Familia>/<archivo>.pdf
      └── datos/{procesados, indices, cache_llm}/

La carpeta de conocimiento se busca en este orden:
  1. la variable de entorno RAG_CONOCIMIENTO;
  2. la carpeta conocimiento/ junto al código (así queda en Codespaces);
  3. el diseño original en OneDrive: Proyecto 3. RAG/datasheets con el manifiesto y
     datos/ dentro de Códigos/.
"""
import os
from pathlib import Path

# Carpeta del código
RAIZ_CODIGO = Path(__file__).resolve().parent.parent


def _ubicar_conocimiento() -> tuple[Path, Path, Path]:
    """Devuelve (carpeta de PDF, ruta del manifiesto, carpeta datos/)."""
    explicita = os.environ.get("RAG_CONOCIMIENTO", "").strip()
    if explicita:
        base = Path(explicita).expanduser().resolve()
        return base / "datasheets", base / "manifiesto.csv", base / "datos"
    junto = RAIZ_CODIGO / "conocimiento"
    if (junto / "manifiesto.csv").exists():
        return junto / "datasheets", junto / "manifiesto.csv", junto / "datos"
    # Diseño original (OneDrive): Proyecto 3. RAG/{datasheets, Códigos/{manifiesto.csv, datos}}
    return RAIZ_CODIGO.parent / "datasheets", RAIZ_CODIGO / "manifiesto.csv", RAIZ_CODIGO / "datos"


DIR_DATASHEETS, RUTA_MANIFIESTO, DIR_DATOS = _ubicar_conocimiento()
DIR_CONOCIMIENTO = RUTA_MANIFIESTO.parent
DIR_PROCESADOS = DIR_DATOS / "procesados"
# Los reportes y gráficas son resultados del proyecto: van con el código (repo público).
DIR_REPORTES = RAIZ_CODIGO / "reportes"

# --- Extracción -------------------------------------------------------------
MODOS_EXTRACCION = ("simple", "tablas")

# Fracción de la altura de la página considerada margen superior/inferior,
# donde se buscan encabezados y pies de página repetidos.
MARGEN_ENCABEZADO = 0.08

# Una línea del margen se considera encabezado/pie repetido si aparece en al
# menos esta fracción de las páginas indexadas del documento...
UMBRAL_REPETICION = 0.5
# ...y el documento tiene al menos este número de páginas indexadas.
MIN_PAGINAS_PARA_LIMPIEZA = 3

# Un bloque de texto que cae dentro de una tabla solo se descarta si al menos
# esta fracción de sus palabras ya aparece en la tabla (si no, la tabla no
# capturó ese contenido y el bloque se conserva).
UMBRAL_COBERTURA_TABLA = 0.8

# Páginas con menos palabras que esto se marcan con alerta "pocas_palabras".
MIN_PALABRAS_PAGINA = 20


def ruta_paginas(modo: str) -> Path:
    return DIR_PROCESADOS / f"paginas_{modo}.jsonl"

# --- Fragmentación (chunking) ---------------------------------------------------
# Tamaño objetivo de cada fragmento, en palabras. El valor por defecto se usa
# en el asistente; la lista completa se usa en los experimentos.
TAMANO_CHUNK = 150
TAMANOS_CHUNK_EXPERIMENTO = (150, 300, 600)
# Fracción del tamaño que se repite entre fragmentos consecutivos.
SOLAPAMIENTO = 0.15
# D22: cada tabla lleva su título y su encabezado completo en todas sus partes.
CONTEXTO_TABLAS = True
MAX_PALABRAS_TITULO_TABLA = 40     # un párrafo más largo no se considera título
MAX_PARRAFOS_TITULO_TABLA = 2
MAX_FILAS_ENCABEZADO_EXTRA = 3     # filas de encabezado después del separador |---|
# Un párrafo corto presente en al menos esta fracción de las páginas de un documento
# es un encabezado de página o de sección, no el título de una tabla.
UMBRAL_TITULO_REPETIDO = 0.2
# Fragmentos con menos palabras que esto se descartan (restos de figuras).
MIN_PALABRAS_CHUNK = 8

# --- Embeddings y búsqueda ------------------------------------------------------
DIR_INDICES = DIR_DATOS / "indices"
# Modelo multilingüe pequeño (118 M parámetros, 384 dimensiones): corre en CPU
# con 8 GB de RAM. Requiere los prefijos "query: " y "passage: ".
MODELO_EMBEDDINGS = "intfloat/multilingual-e5-small"
MODELOS_EMBEDDINGS_EXPERIMENTO = ("intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base")
METODOS_BUSQUEDA = ("bm25", "semantica", "hibrida", "semantica_rerank", "hibrida_rerank")
# Configuración final del asistente (elegida con 03_evaluar_recuperacion.py).
MODO_DEFECTO = "tablas"
METODO_DEFECTO = "semantica_rerank"
# Reordenamiento (reranking) con cross-encoder multilingüe sobre los mejores candidatos.
MODELO_RERANK = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
MODELOS_RERANK_EXPERIMENTO = ("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", "BAAI/bge-reranker-v2-m3")
CANDIDATOS_RERANK = 30
# Constante de Reciprocal Rank Fusion para la búsqueda híbrida.
K_RRF = 60
# Candidatos que aporta cada método antes de fusionarlos.
CANDIDATOS_HIBRIDA = 50


def nombre_indice(modo: str, tamano: int, modelo: str, contexto_tablas: bool = True) -> str:
    corto = modelo.split("/")[-1]
    sufijo = "" if contexto_tablas else "_v1"   # v1: chunking anterior a D22
    return f"{modo}_c{tamano}_{corto}{sufijo}"

# --- Generación (Gemini) --------------------------------------------------------
MODELO_LLM = "gemma-4-31b-it"            # responde las preguntas (modelo de pesos abiertos)
MODELO_JUEZ = "gemini-3.5-flash-lite"    # califica (modelo distinto: menos autosesgo)
K_CONTEXTO = 5                           # fragmentos que se le pasan al modelo
MAX_TOKENS_SALIDA = 4096                 # incluye los tokens de "razonamiento" del modelo
TIMEOUT_LLM_MS = 180_000
LLAMADAS_POR_MINUTO = 15                 # por modelo; con varios hilos la latencia deja de ser el cuello de botella
MAX_REINTENTOS = 8
ESPERA_INICIAL_S = 10
DIR_CACHE_LLM = DIR_DATOS / "cache_llm"
# Uso interactivo (preguntar.py): si el modelo principal falla por errores del servidor
# (500/503, frecuentes con Gemma 31B en el nivel gratuito), se prueba el siguiente.
# Orden por calidad medida: gemini-3.5-flash lee bien tablas pero su cuota gratuita es de
# ~20 solicitudes/día; gemma-4-26b se abstiene en tablas difíciles en vez de inventar.
# gemini-3.5-flash-lite queda excluido: dio un valor equivocado en la tabla de termopares.
MODELOS_RESPALDO = ("gemini-3.5-flash", "gemma-4-26b-a4b-it")
REINTENTOS_INTERACTIVO = 2       # intentos con cada modelo antes de pasar al siguiente
ESPERA_INTERACTIVO_S = 2         # el primer reintento llega rápido: los 500 suelen ser momentáneos
# Frase con la que el modelo debe empezar cuando la respuesta no está en el contexto.
FRASE_NO_SABE = "No encuentro esa información en la documentación disponible."
