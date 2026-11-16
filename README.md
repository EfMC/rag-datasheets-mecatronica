# Asistente RAG para datasheets de mecatrónica

Proyecto final de Inteligencia Artificial (UMNG). Un asistente que responde preguntas
técnicas sobre datasheets y manuales (microcontroladores, PLC, transistores, sensores,
servomotores, amplificadores) citando el documento y la página de donde sale cada dato.

- **Búsqueda:** semántica multilingüe (`multilingual-e5-small`) más reordenamiento con
  un cross-encoder, sobre fragmentos de 150 palabras extraídos con PyMuPDF (las tablas,
  en Markdown).
- **Generación:** Gemma 4 31B por la API de Gemini, con reglas de cita y de abstención.
- **Evidencias E1–E5 (resumen):** [notebooks/Evidencias_E1_E5.ipynb](notebooks/Evidencias_E1_E5.ipynb)
  ([abrir en Colab](https://colab.research.google.com/github/EfMC/rag-datasheets-mecatronica/blob/main/notebooks/Evidencias_E1_E5.ipynb)).
- **Informe ejecutable:** [notebooks/Proyecto_RAG_datasheets.ipynb](notebooks/Proyecto_RAG_datasheets.ipynb)
  ([abrir en Colab](https://colab.research.google.com/github/EfMC/rag-datasheets-mecatronica/blob/main/notebooks/Proyecto_RAG_datasheets.ipynb)):
  problema, antecedentes, datos, implementación, experimentos y análisis en un solo lugar.
- **Resultados** (66 preguntas): corrección de 0,83 con RAG frente a 0,58 sin RAG;
  alucinación de 1,5 % frente a 21 %. Ver [RESULTADOS.md](RESULTADOS.md) y
  [DECISIONES.md](DECISIONES.md).

## Cómo está organizado

El proyecto usa dos repositorios:

| Repositorio | Visibilidad | Contenido |
|---|---|---|
| `rag-datasheets-mecatronica` (este) | Público | Código, set de evaluación, reportes, gráficas y documentación |
| `rag-datasheets-datos` | Privado | Base de conocimiento: PDF, manifiesto, texto extraído, índice y caché del LLM |

Los datasheets y su texto pertenecen a los fabricantes. Por eso viven en un repositorio
privado, y este repositorio no los redistribuye.

```
rag-datasheets-mecatronica/
├── preguntar.py                Asistente interactivo
├── web/                        App web (Streamlit): cada usuario pone su clave de Gemini
├── agregar_documento.py        Agrega un PDF a la base de conocimiento en un paso
├── 01_extraer.py … 05_graficas.py   Pipeline y experimentos
├── rag/                        Módulos (config.py tiene todos los parámetros)
├── evaluacion/                 66 preguntas verificadas, validador y estadística
├── reportes/                   Métricas y gráficas del informe
├── .devcontainer/              Configuración de GitHub Codespaces
├── despliegue/                 Cómo publicar la app web
└── conocimiento/               ← aquí se descarga el repo privado (no se sube)
```

## Página web para que otros lo usen

`web/app.py` es una app web (Streamlit): cada persona abre el enlace desde el PC o el
celular, pega su propia clave gratuita de Gemini y pregunta. Nadie gasta tu cuota y no hay
que compartir archivos. Se publica gratis en Streamlit Community Cloud; el paso a paso
está en [despliegue/README.md](despliegue/README.md).

```bash
pip install -r web/requirements.txt
streamlit run web/app.py          # pruébala en http://localhost:8501
```

## Usarlo desde cualquier dispositivo (GitHub Codespaces)

Codespaces es un computador Linux en la nube que se abre en el navegador. Funciona desde
un PC, una tablet o un celular, sin instalar nada.

**Una sola vez:** en GitHub ve a Settings → Codespaces → Secrets y crea el secreto
`GEMINI_API_KEY` (la clave de aistudio.google.com) con acceso a este repositorio.

**Cada vez que quieras usarlo:**

1. En este repositorio: **Code → Codespaces → Create codespace on main**. La próxima vez
   aparece en la misma lista y abre en segundos.
2. La primera vez GitHub pide autorizar el acceso a `rag-datasheets-datos`: acéptalo.
   Después tarda unos 5 minutos en instalar todo y descargar los modelos.
3. En la terminal de abajo:

   ```bash
   python preguntar.py
   ```

Al abrirlo de nuevo desde otro dispositivo, el Codespace trae automáticamente los
documentos que hayas agregado.

**Cuota gratuita:** 120 horas de núcleo al mes, que equivalen a unas 60 horas de uso en la
máquina de 2 núcleos. Detén el Codespace al terminar (menú ☰ → Codespaces → Stop current
codespace); de lo contrario se detiene solo tras 30 minutos sin uso.

## Agregar documentos a la base de conocimiento

```bash
python agregar_documento.py https://www.ti.com/lit/ds/symlink/lm340.pdf \
    --familia Reguladores --nombre "Regulador de voltaje LM340 / LM7805" \
    --fabricante "Texas Instruments" --git
```

También acepta un PDF local. En Codespaces, arrástralo desde tu computador al panel de
archivos y pasa su ruta. El script:

1. **Verifica el PDF.** Comprueba que tenga texto: los PDF que son imágenes, como los del
   visor de alldatasheet, se rechazan.
2. **Propone páginas.** Sugiere qué páginas indexar y explica qué excluye y por qué
   (encapsulados, avisos legales, índices, gráficas, texto genérico). Puedes aceptar la
   propuesta o escribir otro rango.
3. **Registra el documento.** Lo agrega al manifiesto.
4. **Procesa solo lo nuevo.** Extrae solo ese documento y calcula solo sus fragmentos
   nuevos. Agregar un datasheet tarda menos de un minuto.
5. **Guarda en GitHub.** Con `--git`, hace commit y push al repositorio privado.

La sugerencia de páginas reproduce el 95 % de las decisiones tomadas a mano sobre los 22
datasheets originales sin contar el STM32, que tiene exclusiones por tema (D24). Revisa
la propuesta en los manuales largos.

Si agregas documentos, el corpus deja de ser el del informe. Los resultados de
`RESULTADOS.md` corresponden a la versión `corpus-v1` del repositorio de datos.

## Usarlo en tu PC (Windows)

```powershell
py -3.12 -m venv C:\venvs\rag
C:\venvs\rag\Scripts\activate
git clone https://github.com/EfMC/rag-datasheets-mecatronica
cd rag-datasheets-mecatronica
git clone https://github.com/EfMC/rag-datasheets-datos conocimiento
pip install -r requirements.txt
echo GEMINI_API_KEY=tu_clave > .env
python preguntar.py
```

Crea el entorno virtual y los repositorios fuera de OneDrive, porque la sincronización
bloquea archivos. La carpeta de conocimiento también puede estar en otro lugar si defines
la variable de entorno `RAG_CONOCIMIENTO`.

## El asistente

```bash
python preguntar.py                                     # modo interactivo
python preguntar.py --ver-fragmentos "¿Qué pines del ESP32 son solo de entrada?"
```

Cada consulta tarda unos 7 s de búsqueda más lo que tarde el modelo (~30–50 s con Gemma 4
31B). Los errores `500`/`503` vienen del servidor de Google (capacidad compartida del
nivel gratuito). Si el modelo principal falla dos veces, el asistente prueba los modelos
de respaldo y lo avisa en la respuesta; `--sin-respaldo` desactiva este comportamiento.

## Pipeline y experimentos

```bash
python 01_extraer.py                     # incremental: solo extrae lo nuevo
python 02_indexar.py --todos             # índices del experimento (incremental)
python 03_evaluar_recuperacion.py        # hit@k y MRR, sin usar la API
python 03_evaluar_recuperacion.py --modo tablas --tamano 150 --metodos semantica semantica_rerank --sufijo _rerank
python 04_evaluar_respuestas.py --hilos 6   # respuestas + juez (usa la caché del LLM)
python evaluacion/estadistica.py         # intervalos de confianza y pruebas pareadas
python 05_graficas.py
```

Con la caché `conocimiento/datos/cache_llm/`, `04_evaluar_respuestas.py` reproduce los
resultados del informe sin gastar cuota de la API.

## Formato del manifiesto

`conocimiento/manifiesto.csv` tiene una fila por PDF. Columnas: `doc_id`, `nombre`,
`archivo` (ruta dentro de `datasheets/`), `familia`, `fabricante`, `fuente`, `idioma`,
`revision`, `paginas_totales`, `paginas_indexar` (por ejemplo `1,3-13,21-26`),
`n_paginas_indexar`, `incluir` (`si`/`no`) y `notas`. El pipeline valida el manifiesto
antes de cada ejecución.
