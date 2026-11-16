# Resultados y análisis de errores

Asistente RAG sobre 23 datasheets y manuales de mecatrónica (577 páginas indexadas).
Set de evaluación: 66 preguntas verificadas en los PDF originales (60 con respuesta y
6 sin respuesta en el corpus). Las decisiones de diseño están en `DECISIONES.md`.

## 1. Configuración final

| Componente | Elección | Justificación |
|---|---|---|
| Extracción | PyMuPDF, modo `tablas` (Markdown) | Mejor hit@5 en la búsqueda (0,60 frente a 0,53); ver §4 |
| Fragmentos | 150 palabras, por página, con encabezado del documento; cada parte de una tabla repite su título y encabezado (D22) | El modelo de embeddings trunca a 512 tokens: con 300 palabras se truncaba el 39 % de los fragmentos en modo `tablas` |
| Embeddings | multilingual-e5-small (CPU) | Corpus inglés y español; PC sin GPU con 8 GB de RAM |
| Búsqueda | Semántica (top-30) + reranking con mmarco-mMiniLMv2 | Duplica hit@1 (0,27 → 0,58) |
| Generación | gemma-4-31b-it, temperatura 0, 5 fragmentos | La cuota gratuita de gemini-3.5-flash es de ~20 solicitudes/día |
| Juez | gemini-3.5-flash-lite + reglas para las abstenciones | Modelo distinto del generador; auditado a mano (§5) |

## 2. Recuperación (sin LLM, 60 preguntas con respuesta)

| Método (tablas, 150 palabras) | hit@1 | hit@5 | doc@5 | MRR | Tiempo/consulta |
|---|---|---|---|---|---|
| BM25 | 0,12 | 0,28 | 0,47 | 0,19 | 2 ms |
| Semántica | 0,27 | 0,60 | 0,95 | 0,40 | 17 ms |
| Híbrida (RRF) | 0,20 | 0,50 | 0,88 | 0,33 | 17 ms |
| **Semántica + reranking** | **0,58** | **0,82** | **0,95** | **0,69** | ~7 s |
| Híbrida + reranking | 0,55 | 0,78 | 0,95 | 0,64 | ~8 s |

- **hit@k:** la página de evidencia está entre los k primeros fragmentos.
- **doc@k:** lo está el documento correcto.

Gráficas: `reportes/graficas/01_metodos_busqueda.png` y `02_tamano_y_extraccion.png`.

**Lectura de los resultados:**
- La búsqueda semántica casi siempre encuentra el documento (doc@5 = 0,95); el problema
  era el orden de las páginas dentro del documento, y eso es lo que corrige el reranking.
- BM25 falla porque las preguntas están en español y 17 de los 23 documentos en inglés.
  En la búsqueda híbrida ese ruido empeora a la semántica.

## 3. Calidad de las respuestas (66 preguntas)

| Configuración | Corrección (IC 95 %) | Comportamiento esperado | Alucinación | Abstención correcta (n=6) | Abstención indebida | Cita correcta |
|---|---|---|---|---|---|---|
| Sin RAG (línea base) | 0,58 [0,47; 0,68] | 0,74 | **0,21** | **0,00** | 0,07 | — |
| **RAG final** | **0,80 [0,70; 0,89]** | 0,79 | 0,02 | 1,00 | 0,16 | 0,82 |
| RAG sin reranking | 0,63 [0,52; 0,74] | 0,64 | 0,00 | 1,00 | 0,33 | 0,62 |
| RAG con BM25 | 0,36 [0,25; 0,49] | 0,36 | 0,00 | 1,00 | 0,69 | 0,74 |
| RAG final, extracción simple | 0,83 [0,75; 0,92] | 0,80 | 0,00 | 1,00 | 0,16 | 0,84 |

Comparación pareada contra el RAG final (bootstrap de 10 000 remuestreos y prueba de
signos sobre las preguntas en que difieren; `evaluacion/estadistica.py`):

| Frente a RAG final | Diferencia | IC 95 % | Mejor / peor | p |
|---|---|---|---|---|
| Sin RAG | −0,22 | [−0,37; −0,07] | 11 / 27 | 0,014 |
| Sin reranking | −0,17 | [−0,27; −0,07] | 4 / 17 | 0,007 |
| BM25 | −0,43 | [−0,55; −0,31] | 1 / 31 | < 0,001 |
| Extracción simple | +0,04 | [−0,03; +0,11] | 5 / 3 | 0,73 (no significativa) |

**Conclusiones:**
1. **El RAG mejora la corrección de forma significativa** (+0,22, p = 0,014), y sobre todo
   elimina las alucinaciones: 21 % sin RAG frente a 1,5 % con RAG. Sin RAG, el modelo
   respondió con seguridad las 6 preguntas que no tienen respuesta en el corpus. Por
   ejemplo, dio para el MG995 el torque del MG996R y para el ESP32-S3 un consumo que no
   está en la documentación. Con RAG se abstuvo en las 6.
2. **El reranking es el componente que más aporta dentro del RAG** (+0,17, p = 0,007).
3. **La extracción `tablas` no mejora las respuestas finales.** La diferencia con el modo
   `simple` (+0,04 a favor de `simple`) no es significativa. El modo `tablas` sí mejora la
   búsqueda (§2), pero ver el análisis de errores (§4).
4. **Dónde gana el RAG:** preguntas ambiguas (0 → 1), sin respuesta (0 → 1), confusores
   (0,5 → 1), multidispositivo (0,5 → 0,92) y datos puntuales (0,75 → 0,85).
5. **Dónde no gana:** tablas (0,60 frente a 0,57) y multidocumento (0,62 frente a 0,50).
   Son los puntos débiles del sistema.

Los grupos por tipo de pregunta son pequeños (de 1 a 26 preguntas); las diferencias
dentro de un grupo pequeño son orientativas. Gráficas: `03_respuestas_por_config.png` y
`04_correccion_por_tipo.png`.

## 4. Análisis de errores del RAG final (15 respuestas imperfectas de 66)

| Origen | n | Preguntas | Mecanismo |
|---|---|---|---|
| La búsqueda no trajo la página | 8 | mc04, mc07, mc08, sen09, srv06, tr04, tr05, amp01 | Tablas de características (corriente de GPIO, Absolute Maximum Ratings) que compiten con decenas de tablas parecidas del mismo documento; tr04 exige razonar entre varios documentos |
| La tabla se partió y perdió su contexto | 3 | sen11, sen12, tr03 | La página correcta se recupera, pero el fragmento que llega tiene solo el título ("Type K Thermocouple Table"). Las filas con el valor están en otro fragmento, sin el título ni la fila de encabezado de columnas (0…9), así que no se puede hacer la búsqueda de doble entrada |
| El modelo no usó bien el contexto | 4 | sen13, srv04, amp07, tr01 | Se abstuvo con la tabla de termocuplas en el contexto (sen13); no señaló la contradicción 120°/180° del MG996R (srv04); omitió los encapsulados J y W del LM124, cuyas celdas combinadas verticalmente quedan vacías en la extracción (amp07, limitación prevista en D5); devolvió una respuesta vacía (tr01) |

**Por qué el modo `tablas` no gana en las respuestas:** en las tablas numéricas grandes
(termocuplas), el Markdown se parte en varios fragmentos y cada parte pierde el título y
la fila de encabezado real. En modo `simple`, Gemma sí encontró los valores de los
termopares tipo K y J (sen11, sen13). Es decir, la representación en Markdown ayuda a
encontrar la página, pero el chunking actual de tablas grandes destruye la estructura
que se quería conservar.

**Mejora implementada (D22):** al partir una tabla, cada parte repite el título de la
tabla y la fila de encabezados de columna. Ver §7.

## 5. Validez de la evaluación

- **Abstenciones calificadas por regla.** El juez premiaba abstenciones en preguntas con
  respuesta (18 casos en BM25). Como la frase de abstención es fija, se califican por
  regla (D20). Sin esa corrección, BM25 aparecía con 0,65 en vez de 0,36.
- **Auditoría manual del juez.** En 24 respuestas al azar (semilla 17), coincidencia
  exacta en 22 (92 %). En los 2 desacuerdos el juez fue 0,5 más indulgente, así que las
  cifras absolutas pueden estar levemente infladas. La comparación entre configuraciones
  no se ve afectada.
- **Métrica de página estricta.** Algunos datos aparecen en varias páginas (por ejemplo,
  10 mV/°C del LM35 en las páginas 1, 13 y 14) y solo se marcó una como evidencia.
  `contexto_suficiente` (juez) complementa hit@k: RAG final 0,80, extracción simple 0,82,
  sin reranking 0,70 y BM25 0,28.
- **Sesgo del set.** Las preguntas las redactó el mismo asistente que diseñó el pipeline,
  aunque cada respuesta se tomó del PDF original y no de la salida del sistema.
- **Tamaño.** Con 66 preguntas, solo son concluyentes las diferencias grandes (§3).

## 6. Costo computacional

| Etapa | Costo |
|---|---|
| Extracción `tablas` / `simple` | ~5 min / ~2 s (una sola vez) |
| Embeddings (889–1580 fragmentos, CPU) | 1,5–3 min por índice (una sola vez) |
| Búsqueda semántica / con reranking | 17 ms / ~7 s por consulta |
| Reranker grande bge-reranker-v2-m3 | ~78 s por consulta (descartado) |
| Respuesta gemma-4-31b-it | ~30–50 s por llamada (gemini-3.5-flash: ~4 s) |
| Contexto enviado al modelo | ~1950 tokens por pregunta (sin RAG: ~100) |
| Experimento completo (330 respuestas + juez) | ~1 h con 6 hilos |

## 7. Mejora posterior: contexto de tablas en el chunking (D22)

Las secciones 3 a 5 corresponden al experimento principal, con el chunking v1. A partir
del análisis de errores (§4) se implementó que cada parte de una tabla repita su título y
su encabezado completo, y se comparó pregunta a pregunta contra v1. La configuración
final del asistente es v2.

| RAG final | Corrección (IC 95 %) | Preguntas de tabla (n = 15) | hit@5 (reranking) |
|---|---|---|---|
| v1 (experimento principal) | 0,80 [0,70; 0,89] | 0,57 | 0,82 |
| **v2 (final)** | **0,83 [0,75; 0,92]** | **0,73** | 0,77 |

- **Preguntas que cambian:**
  - mejoran sen11, sen12 y sen13. Son búsquedas en las tablas de termocuplas, incluida la
    de doble entrada: tipo K a 125 °C = 5124 µV, fila 120, columna 5;
  - empeora sen08 (NTC a 0 °C, valor aproximado).
- **Diferencia global:** +0,04 (IC 95 % [−0,01; +0,10], p = 0,63). Es una mejora
  focalizada en tablas, no significativa sobre el total.
- **v2 frente a sin RAG:** +0,26 (IC 95 % [0,11; 0,40]; 28 mejores y 9 peores; p = 0,003).
- **Lección para el informe:** la búsqueda empeoró levemente por página (hit@5 de 0,82 a
  0,77), pero las respuestas mejoraron. La métrica de recuperación por página no basta
  para elegir el chunking; hay que medir la respuesta final.
