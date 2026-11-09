# Registro de decisiones de diseño

Cada decisión indica qué se eligió, por qué y qué alternativa se descartó.
Sirve como base para justificar la arquitectura en el informe (criterio C2).

---

## D1. Corpus definido por un manifiesto, no por la carpeta
**Fecha:** 2026-11-08

- **Decisión:** `manifiesto.csv` lista cada PDF con `doc_id`, familia, idioma,
  páginas a indexar y si se incluye. Los PDF nunca se editan.
- **Por qué:** el recorte de páginas queda documentado y es reproducible, y agregar
  un documento no exige cambiar código.
- **Descartado:** recortar los PDF a mano (no deja rastro de qué se quitó).

## D2. Se indexa solo el contenido técnico útil
**Fecha:** 2026-11-08

- **Decisión:** se excluyen gráficas de *Typical Characteristics*, encapsulados,
  *tape & reel*, índices, historiales de revisión, avisos legales y el texto
  genérico de los manuales Siemens. Quedan 577 de 959 páginas (60 %).
- **Por qué:** esas páginas no responden preguntas de diseño y generan fragmentos
  ruidosos o casi duplicados entre documentos. Las gráficas son imágenes y al
  extraerlas solo quedan etiquetas sueltas de ejes.
- **Limitación:** se pierde la información de las curvas (trabajo futuro: RAG multimodal).

## D3. PyMuPDF para la extracción
**Fecha:** 2026-11-08

- **Decisión:** PyMuPDF para texto y para detección de tablas.
- **Por qué:** una sola dependencia hace ambas cosas, es rápida y liviana (el equipo
  tiene 8 GB de RAM y no tiene GPU).
- **Descartado:** OCR. Los PDF que eran imágenes se reemplazan por versiones
  oficiales con texto o se excluyen.

## D4. Dos modos de extracción: `simple` y `tablas`
**Fecha:** 2026-11-08

- **Decisión:** `simple` extrae texto plano por bloques. `tablas` convierte cada tabla
  detectada en Markdown (filas y columnas explícitas) y el resto como texto.
- **Por qué:** en texto plano las tablas pierden la relación fila/columna (por
  ejemplo, a qué dispositivo pertenece un valor en el LM324). Ambos modos se
  comparan como experimento (criterio C3).
- **Costo:** `tablas` tarda unas 200 veces más (~5 min frente a ~2 s), pero solo se
  ejecuta una vez.

## D5. Tablas sin relleno de celdas combinadas
**Fecha:** 2026-11-08

- **Decisión:** se usa `to_markdown(fill_empty=False)` y se limpia la salida
  (entidades HTML, `<br>`, negritas y cursivas).
- **Por qué:** con relleno, PyMuPDF copia el valor de una celda combinada hacia los
  lados y genera valores falsos (en el LM324, "3 5" aparecía en MIN, TYP y MAX; en
  el IRFZ44N, la columna de unidades quedaba con "14"). Una celda vacía es
  preferible a un valor inventado.
- **Descartado:** construir el Markdown desde `tabla.extract()`, porque desordena los
  caracteres de cada celda (`45.00` salía como `4500 .`).
- **Limitaciones conocidas:**
  - Las celdas combinadas verticalmente quedan vacías (encapsulados J y W del LM124).
  - En algunas tablas TYP y MAX quedan en una sola celda ("3 5").

  Ambos son candidatos para el análisis de errores.

## D6. Limpieza de encabezados y pies de página
**Fecha:** 2026-11-08

- **Decisión:** se elimina una línea si está en el 8 % superior o inferior de la
  página, contiene letras y se repite en al menos el 50 % de las páginas del documento.
- **Por qué:** quita texto como "Submit Document Feedback…" o "www.vishay.com" sin
  tocar el contenido.
- **Error corregido:** la primera versión comparaba líneas en toda la página y
  reemplazaba los dígitos por `#`. Las filas numéricas de las tablas de termocuplas
  se veían iguales a un número de página y se borraban (el documento pasó de
  24 289 a 10 892 palabras). Ahora solo se mira el margen y nunca se eliminan líneas
  formadas solo por números.

## D7. Etapas separadas con archivos intermedios
**Fecha:** 2026-11-08

- **Decisión:** la extracción guarda `paginas_<modo>.jsonl`. El chunking, los
  embeddings y la evaluación serán etapas independientes que leen ese archivo.
- **Por qué:** los experimentos (tamaño de chunk, modo de extracción, tipo de
  búsqueda) se pueden repetir sin volver a procesar los PDF.

## D8. Texto dentro de tablas: se conserva si la tabla no lo capturó
**Fecha:** 2026-11-08

- **Decisión:** un bloque de texto que cae dentro de una tabla solo se descarta si al
  menos el 80 % de sus palabras ya están en la tabla (`UMBRAL_COBERTURA_TABLA`).
- **Por qué:** la validación del set de evaluación mostró que PyMuPDF a veces detecta la
  tabla pero deja celdas vacías o recorta caracteres en el borde. Antes se perdían los
  umbrales de señal del módulo DI ("+11 a +30 V") y las etiquetas del recuadro principal
  de los MOSFET. Las claves de evidencia perdidas en modo `tablas` bajaron de 4 a 1.
- **Limitación conocida:** en el NTC, "B25/85" queda como "25/85" (carácter recortado),
  aunque el valor numérico se conserva.

## D9. Set de evaluación verificado contra los PDF originales
**Fecha:** 2026-11-08

- **Decisión:** 66 preguntas en `evaluacion/preguntas.csv`, verificadas contra el texto
  de los PDF originales y no contra la salida del pipeline. Cada una trae respuesta de
  referencia, páginas de evidencia (`doc_id:página`), un texto clave de control, tipo y
  comportamiento esperado.
- **Composición:** 26 dato puntual, 15 tabla, 6 multidispositivo, 4 confusor,
  4 multidocumento, 2 procedimiento, 2 ambiguas (se espera que pida aclaración),
  1 contradicción del documento y 6 sin respuesta en el corpus (se espera que diga que no sabe).
- **Control automático:** `evaluacion/validar_preguntas.py` comprueba que cada evidencia
  esté indexada y que la clave aparezca en el PDF. También informa qué claves se pierden
  en cada modo de extracción.
- **Riesgo de sesgo:** el set lo redactó la misma persona (asistente) que diseñó el
  pipeline. Para mitigarlo, cada respuesta se tomó directamente del PDF.

## D10. Fragmentación (chunking) por página, con encabezado del documento
**Fecha:** 2026-11-08

- **Decisión:** los fragmentos nunca cruzan de una página a otra. El texto de cada
  página se divide en unidades (párrafos y tablas) que se agrupan hasta el tamaño
  objetivo, con un 15 % de solapamiento. Una tabla demasiado grande se parte por filas
  y cada parte repite el encabezado de la tabla.
- **Encabezado:** cada fragmento se indexa con
  `[Nombre del documento — doc_id, pág. N]` (columna `nombre` del manifiesto).
- **Por qué:**
  - la citación de página queda exacta;
  - el nombre del componente en cada fragmento ayuda a distinguir pares confusores y a
    emparejar preguntas en español con documentos en inglés;
  - repetir el encabezado de la tabla evita fragmentos con números sin columnas.
- **Experimento:** tamaños de 150, 300 y 600 palabras. Como no se cruzan páginas,
  600 equivale casi a "una página por fragmento" (promedio real de ~250 palabras).

## D11. Embeddings locales con multilingual-e5-small
**Fecha:** 2026-11-08

- **Decisión:** `intfloat/multilingual-e5-small`: 118 M de parámetros, 384 dimensiones,
  corre en CPU. Como comparación de costo frente a desempeño se usa
  `multilingual-e5-base` (278 M, 768 dimensiones).
- **Por qué:**
  - el corpus mezcla inglés y español y las preguntas están en español, así que el
    modelo tiene que ser multilingüe;
  - corre en un PC sin GPU con 8 GB de RAM;
  - al ser local, la indexación es reproducible y no gasta cuota de API.
- **Descartado:** embeddings por API. Dependen de la cuota gratuita y cambian si el
  proveedor actualiza el modelo.

## D12. Búsqueda exacta con NumPy, BM25 e híbrida con RRF
**Fecha:** 2026-11-08

- **Decisión:**
  - la búsqueda semántica usa similitud coseno por fuerza bruta, sin base de datos
    vectorial;
  - BM25 usa un tokenizador que conserva nombres de parte (`irlz44n`, `6es7521-1bh00`);
  - la búsqueda híbrida combina ambas con Reciprocal Rank Fusion (k = 60, 50 candidatos
    por método).
- **Por qué:**
  - con menos de 2000 fragmentos, la búsqueda exacta tarda milisegundos, así que un
    índice aproximado (FAISS, Chroma) solo agregaría dependencias;
  - RRF no necesita normalizar puntajes de escalas distintas.
- **Experimento:** se comparan los tres métodos con hit@k (página correcta en el top-k),
  doc@k y MRR, sin usar la API.

## D13. Truncamiento del modelo de embeddings (hallazgo)
**Fecha:** 2026-11-08

- **Hallazgo:** multilingual-e5 lee como máximo 512 tokens por fragmento y descarta el
  resto. Con fragmentos de 300 palabras se truncan el 27 % en modo `simple` y el 39 % en
  modo `tablas`, porque en las tablas cada número y cada `|` es un token. Con 150 palabras
  el truncamiento baja al 2 % y al 11 %.
- **Consecuencia:** en fragmentos grandes, la búsqueda semántica no "ve" el final del
  fragmento. Es un argumento para preferir fragmentos más pequeños con este modelo
  (criterio C2: hiperparámetro justificado por una restricción del modelo).

## D14. Generación con gemini-3.5-flash y juez gemini-3.5-flash-lite
**Fecha:** 2026-11-08

- **Prueba de disponibilidad (una llamada mínima por modelo):**
  - `gemini-2.5-flash` ya no está disponible para cuentas nuevas;
  - `gemini-3.8-flash` no respondió en 2 minutos;
  - `gemini-3.5-flash` y `gemini-3.5-flash-lite` respondieron bien.
- **Decisión:** el asistente usa `gemini-3.5-flash` con temperatura 0. El juez usa
  `gemini-3.5-flash-lite`, un modelo distinto, para reducir el autosesgo. Además, la
  cuota gratuita es independiente por modelo.
- **Robustez:** caché en disco por hash de la llamada, reintentos con espera
  exponencial ante 429/5xx y un ritmo máximo de 8 llamadas por minuto por modelo.
  Un experimento interrumpido continúa al volver a ejecutarlo.
- **Prompt:**
  - solo información de los fragmentos;
  - citas `[doc_id, pág. N]`;
  - indicar la variante de cada valor;
  - señalar ambigüedades y contradicciones;
  - frase fija de abstención, para medirla automáticamente.

## D15. Métricas de la respuesta
**Fecha:** 2026-11-08

- **Las asigna el juez**, comparando contra la respuesta de referencia:
  - corrección (1 / 0,5 / 0);
  - comportamiento esperado;
  - fidelidad a los fragmentos;
  - alucinación;
  - contexto suficiente (si los fragmentos traían la respuesta, aunque no fuera la
    página marcada como evidencia).
- **Se calculan con reglas automáticas:**
  - abstención correcta (en preguntas sin respuesta) e indebida (en preguntas con
    respuesta);
  - cita correcta (alguna cita coincide con la página de evidencia);
  - citas fuera de contexto (citas a páginas que no se recuperaron).

## D16. Reranking con cross-encoder: configuración final de búsqueda
**Fecha:** 2026-11-08

- **Hallazgo:** en 22 de los 25 fallos de la búsqueda semántica (tablas, 300 palabras) el
  documento era correcto pero la página no. El problema era el orden dentro del documento.
- **Decisión:** se toman los 30 mejores candidatos de la búsqueda semántica y se
  reordenan con `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (multilingüe, 118 M).
  Configuración final: extracción `tablas`, fragmentos de 150 palabras,
  `semantica_rerank`.
- **Resultados (60 preguntas con respuesta, tablas, 150 palabras):**

  | Método | hit@1 | hit@5 | MRR | Tiempo/consulta |
  |---|---|---|---|---|
  | BM25 | 0,12 | 0,28 | 0,19 | 2 ms |
  | Semántica | 0,27 | 0,60 | 0,40 | 17 ms |
  | Híbrida (RRF) | 0,20 | 0,50 | 0,33 | 17 ms |
  | **Semántica + reranking (30 candidatos)** | **0,58** | **0,82** | **0,69** | ~7 s |
  | Semántica + reranking (15 candidatos) | 0,53 | 0,77 | 0,63 | ~4 s |
  | Híbrida + reranking | 0,55 | 0,78 | 0,64 | ~8 s |
  | Reranker bge-reranker-v2-m3 (solo 5 preguntas) | 0,80 | 0,80 | 0,80 | ~78 s |

- **Costo frente a desempeño:** el reranking duplica hit@1 a cambio de ~7 s por consulta
  en CPU. El reranker grande (568 M) es 11 veces más lento y no es viable en un PC de
  8 GB sin GPU.
- **Por qué BM25 y la híbrida quedan atrás:** las preguntas están en español y 18 de los
  23 documentos en inglés. BM25 solo acierta cuando la pregunta trae un nombre de parte, y
  en la fusión RRF ese ruido empeora a la búsqueda semántica.

## D17. Cambio de modelo generador: Gemma 4 31B (cuota diaria de Gemini)
**Fecha:** 2026-11-08

- **Problema:** el nivel gratuito de `gemini-3.5-flash` se agotó con unas 20 solicitudes
  en el día ("requests per day limit exceeded on Free Tier"). El experimento necesita
  ~330 respuestas.
- **Decisión (tomada por el estudiante):** usar `gemma-4-31b-it`, un modelo de pesos
  abiertos de Google, por la misma API y con la misma clave. Ventaja adicional: al ser
  abierto, el mismo modelo se podría ejecutar localmente con el hardware adecuado.
- **Costo:** ~49 s por respuesta (gemini-3.5-flash: ~4 s), así que el experimento completo
  tarda unas 5 horas. Se ejecuta en segundo plano y la caché permite reanudarlo.
- **Juez:** se mantiene `gemini-3.5-flash-lite` (~0,8 s por llamada). Al ser distinto del
  generador, evita el autosesgo.

## D18. Corrección del criterio del juez
**Fecha:** 2026-11-08

- **Problema detectado en el piloto:** cuando el asistente se abstenía en una pregunta
  que sí tiene respuesta, porque la búsqueda no trajo el dato, el juez le daba
  corrección 1 ("hizo bien en abstenerse con ese contexto").
- **Corrección:** la corrección se mide siempre contra la referencia. Abstenerse en una
  pregunta con respuesta vale 0, y la falla de la búsqueda se registra aparte en
  `contexto_suficiente`. Así se separan los errores de recuperación de los de generación.
- **Pendiente:** validar al juez revisando a mano una muestra de sus calificaciones.

## D19. Evaluación en paralelo
**Fecha:** 2026-11-08

- **Problema:** con Gemma 4 31B cada respuesta tarda unos 30 s, y además hay errores
  500/503 intermitentes del servidor. En serie, el experimento completo (330 respuestas
  más el juez) tardaría más de 24 horas.
- **Decisión:** `04_evaluar_respuestas.py --hilos 6` evalúa 6 preguntas a la vez.
  - El limitador de ritmo es seguro con varios hilos: cada llamada reserva su turno.
  - La búsqueda local (embeddings y reranker) se ejecuta de a una consulta a la vez,
    con un candado.
  - Los resultados se ordenan igual que el set de preguntas, así que el resultado no
    depende del orden en que terminen.
- **Efecto:** unas 3 horas en total. La caché garantiza que nada se calcule dos veces.

## D20. Auditoría del juez y calificación de las abstenciones por regla
**Fecha:** 2026-11-08

- **Problema 1 (sesgo sistemático):** aunque el prompt lo prohíbe, el juez
  (`gemini-3.5-flash-lite`) siguió dando corrección 1 cuando el asistente se abstenía en
  preguntas que sí tienen respuesta ("hizo bien, el contexto no lo traía"). En BM25 pasó
  en 18 preguntas, lo que inflaba artificialmente su resultado.
- **Decisión:** como la abstención se detecta sin ambigüedad (frase fija del prompt), se
  califica con una regla determinista (`aplicar_reglas_abstencion`):
  - abstenerse en una pregunta con respuesta vale 0;
  - abstenerse en una pregunta sin respuesta vale 1;
  - el resto lo decide el juez.

  La calificación original del juez se conserva en `juez_correccion_original` por
  transparencia.
- **Problema 2 (confiabilidad del resto):** se auditaron a mano 24 respuestas al azar que
  no son abstenciones (semilla 17), de sin_rag, rag_final y rag_final_simple:
  - coincidencia exacta con el juez en 22 de 24 (92 %);
  - en los 2 desacuerdos el juez fue más indulgente en 0,5:
    - amp03: fórmula del 555 copiada sin paréntesis por un error de extracción; juez 1,
      auditor 0,5;
    - sen09 sin RAG: "≈ 670 Ω" frente a 677,3 Ω; juez 0,5, auditor 0.
- **Conclusión:** con las abstenciones calificadas por regla, el juez es adecuado para
  comparar configuraciones. Sus valores absolutos pueden estar levemente inflados.

## D21. Resultado: el modo `tablas` no mejora las respuestas finales
**Fecha:** 2026-11-08

- **Resultado:** la extracción `tablas` mejora la búsqueda (hit@5 de 0,60 frente a 0,53),
  pero en las respuestas finales queda empatada con `simple`: 0,80 frente a 0,83, con una
  diferencia de +0,04 a favor de `simple` que no es significativa (p = 0,73).
- **Causa encontrada en el análisis de errores:** al partir tablas numéricas grandes, cada
  parte conserva solo las dos primeras líneas del Markdown. El título de la tabla y la
  fila real de encabezados de columna quedan en otro fragmento.
- **Decisión:** se mantiene `tablas` como configuración final, porque la diferencia no es
  significativa y conserva la ventaja en la búsqueda. Se documenta la mejora concreta
  (repetir título y encabezado en cada parte) como el siguiente paso.

## D22. Título y encabezado completo en cada parte de una tabla (configuración final)
**Fecha:** 2026-11-08

- **Motivación:** análisis de errores de D21. Al partir tablas grandes, cada parte perdía
  el título y la fila real de encabezados de columna. En las tablas de termocuplas no se
  podía hacer la búsqueda de doble entrada.
- **Cambios en `rag/chunking.py`** (`CONTEXTO_TABLAS = True`, solo en modo `tablas`):
  1. Los párrafos cortos (≤ 40 palabras, máximo 2) que preceden a una tabla se pegan a
     ella como título y se repiten en cada parte.
  2. El encabezado incluye, además de la primera línea del Markdown, hasta 3 filas que
     parecen encabezado: sin números de 2 o más dígitos y, o empiezan vacías
     (`||MIN|TYP|MAX`), o tienen todas las celdas llenas (`t90/°C|0|1|…|9`).
  3. Un párrafo presente en ≥ 20 % de las páginas del documento (y en ≥ 3 páginas) es un
     encabezado de página, no un título. Se compara con las líneas ordenadas, porque
     algunos encabezados alternan el orden de sus líneas entre páginas pares e impares.
- **Primer intento corregido:** sin la regla 3, "STM32F765xx STM32F767xx…" quedaba como
  título de 104 fragmentos y "Pinouts and pin description" de 82. Ese ruido repetido
  confundía al reranker.
- **Recuperación** (tablas, 150 palabras, 60 preguntas):

  | | hit@1 | hit@5 | MRR |
  |---|---|---|---|
  | Semántica + reranking, v1 | 0,58 | 0,82 | 0,69 |
  | Semántica + reranking, v2 | 0,53 | 0,77 | 0,65 |

  Baja levemente (unas 3 preguntas). Hay más fragmentos truncados (172 → 279), porque
  cada parte repite el título y el encabezado.
- **Respuestas** (66 preguntas, comparación pareada):

  | | v1 | v2 |
  |---|---|---|
  | Corrección global | 0,80 | 0,83 [0,75; 0,92] |
  | Preguntas de tabla (n = 15) | 0,57 | 0,73 |

  - Mejoran sen11, sen12 y sen13 (termocuplas, incluida la búsqueda de doble entrada a
    125 °C) y empeora sen08 (NTC a 0 °C: valor aproximado). Las otras 62 no cambian.
  - Diferencia global +0,04, IC 95 % [−0,01; +0,10], prueba de signos 3/1 (p = 0,63).
    No es significativa en el total; es una mejora focalizada en tablas.
  - La corrida v1 reproduce exactamente los resultados de la corrida principal.
- **Decisión:** se adopta v2 como configuración final. Mejora el tipo de pregunta más
  débil sin empeorar los demás. La caída en hit@5 muestra que la métrica por página no
  captura si llega la parte de la tabla que contiene el dato.
- **Final frente a sin RAG:** +0,26, IC 95 % [0,11; 0,40], 28 mejores y 9 peores,
  p = 0,003.
- **Limitación pendiente:** una tabla que continúa en la página siguiente no hereda el
  título de la página anterior, porque los fragmentos no cruzan páginas.

## D23. Modelos de respaldo y reintentos rápidos en el uso interactivo
**Fecha:** 2026-11-09

- **Problema:** en el nivel gratuito, `gemma-4-31b-it` responde con errores del servidor
  (500/503/504) en ~28 % de los intentos: 148 errores frente a 381 llamadas exitosas
  durante la evaluación. `gemini-3.5-flash-lite` tuvo menos del 1 %: 3 frente a 411. No es
  un problema del código: es capacidad compartida del servidor.
- **Prueba de alternativas** con dos preguntas que el modelo principal responde bien:

  | Modelo | Termopar K a 125 °C | Borrado total de la CPU 1511 | Tiempo |
  |---|---|---|---|
  | gemma-4-31b-it | 5124 µV (correcto) | correcto | ~40 s |
  | gemma-4-26b-a4b-it | se abstiene | correcto | 1–10 s |
  | gemini-3.5-flash-lite | 5043 µV (equivocado: columna 3 en vez de 5) | correcto | ~1 s |

- **Decisión:** se mantiene Gemma 31B como modelo principal, porque los rápidos fallan
  justo en la lectura de tablas. Solo en `preguntar.py`:
  - si el principal falla 2 veces seguidas (primer reintento a los 2 s), se prueba
    `gemini-3.5-flash` (bueno y rápido, ~20 solicitudes/día) y después
    `gemma-4-26b-a4b-it` (que se abstiene en vez de inventar);
  - `gemini-3.5-flash-lite` se excluye porque da números equivocados con seguridad;
  - la respuesta avisa cuando la dio un modelo de respaldo, y `--sin-respaldo` desactiva
    este comportamiento.
- **La evaluación no cambia:** usa siempre un único modelo sin respaldos, para que las
  comparaciones sean justas.
- **Alternativa no adoptada:** activar el nivel de pago en AI Studio eliminaría casi todos
  los errores y permitiría usar gemini-3.5-flash como principal. Es una decisión de costo
  del estudiante.

## D24. Código público, base de conocimiento privada y alimentación continua
**Fecha:** 2026-11-09

- **Requisito del estudiante:** usar el asistente desde cualquier dispositivo y agregar
  documentos a la base de conocimiento de forma continua.
- **Decisión:**
  - **Dos repositorios.** `rag-datasheets-mecatronica` es público: código, evaluación,
    reportes y documentación. `rag-datasheets-datos` es privado: PDF, manifiesto, texto
    extraído, índice y caché del LLM. La visibilidad en GitHub es por repositorio, y tanto
    los PDF como su texto extraído son contenido de los fabricantes.
  - **Ubicación de la base.** `rag/config.py` la busca en este orden: variable
    `RAG_CONOCIMIENTO`, carpeta `conocimiento/` junto al código y, por último, el diseño
    original en OneDrive, que sigue funcionando sin cambios.
  - **GitHub Codespaces.** `.devcontainer/` instala PyTorch solo CPU y las dependencias,
    clona el repositorio privado (permiso declarado en `devcontainer.json`), descarga los
    modelos y en cada inicio hace `git pull` de la base. La API key es un secreto de
    Codespaces.
  - **Extracción incremental.** Cada documento se guarda en
    `datos/procesados/por_documento/<modo>/` con una huella (SHA-256 del PDF, páginas,
    versión del código de extracción). Verificación: la extracción con caché reproduce
    exactamente el texto anterior en las 577 páginas, y la segunda pasada tarda 0,1 s en
    lugar de ~5 min.
  - **Índice incremental.** Cada embedding se identifica por el texto exacto que se
    codificó, así que solo se calculan los fragmentos nuevos o modificados. Verificación:
    reconstruir el índice sin cambios reutiliza los 1690 vectores, idénticos.
  - **`agregar_documento.py`.** Agrega un PDF (ruta o URL) en un paso. Prueba real:
    LM340/LM7805 de TI se descargó, se propusieron 14 de 38 páginas, se extrajo y se
    indexaron sus 38 fragmentos en 36 s en total.
- **Sugerencia automática de páginas** (`rag/sugerencia_paginas.py`):
  - **Reglas.** Las mismas de D2, aplicadas sobre las líneas cortas de cada página (los
    títulos), sin tildes, más las páginas con menos de 40 palabras y las de gráficas
    (dos o más pies de figura y poco texto).
  - **Validación contra el manifiesto manual.** Sobre los 23 documentos, precisión de
    0,81 y recuperación de 0,96. Sin el STM32, donde se excluyeron secciones por tema
    (consumos, interfaces), es 0,94 y 0,95.
  - **Errores corregidos durante la validación.** Una regla de "anexo final" descartaba
    el apéndice de pines del ESP32. Una mención de "ordering information" en el cuerpo de
    una página se tomaba como título. "Notas jurídicas" con la tilde descompuesta del PDF
    no coincidía con el patrón.
  - **Uso.** La propuesta siempre se muestra con su justificación y se puede editar.
- **Consecuencia para el informe:** agregar documentos cambia el corpus. Los resultados
  de RESULTADOS.md corresponden a la etiqueta `corpus-v1` del repositorio de datos.
