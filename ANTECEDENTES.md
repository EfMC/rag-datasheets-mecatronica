# Búsqueda sistemática de antecedentes

Revisión de literatura del asistente RAG de datasheets de mecatrónica: qué se sabe sobre
cada componente del sistema, qué trabajos resuelven problemas parecidos y en qué se
diferencia este proyecto.

**Alcance y momento.** La búsqueda se hizo el 16 de noviembre de 2026, con el sistema ya
construido y evaluado. Sirve para contrastar las decisiones de `DECISIONES.md` con el
estado del arte, no las originó: las decisiones se tomaron midiendo (`RESULTADOS.md`).
Donde un trabajo coincide o contradice lo que medimos, se dice.

## 1. Preguntas de búsqueda

| Código | Pregunta |
|---|---|
| PB1 | ¿Qué es RAG y por qué reduce las alucinaciones frente a un modelo sin recuperación? |
| PB2 | ¿Qué trabajos aplican RAG a documentación técnica, datasheets o manuales de producto, y cómo tratan las tablas? |
| PB3 | ¿Qué modelos de recuperación sirven para preguntas en español sobre documentos en inglés, y qué aporta un reordenador (cross-encoder)? |
| PB4 | ¿Cómo influyen el tamaño de los fragmentos y la cantidad de contexto en la respuesta? |
| PB5 | ¿Cómo se evalúa un sistema RAG, y qué tan confiable es usar un LLM como juez? |

## 2. Protocolo

- **Fuentes:** arXiv, actas de ACM SIGIR y NeurIPS, revistas MDPI (*AI*, *Electronics*) y
  Google Research. La búsqueda se hizo con un buscador web.
- **Cadenas de búsqueda:**
  - `retrieval-augmented generation technical documents datasheets engineering question answering`
  - `RAG tables PDF chunking evaluation table question answering retrieval study`
  - `retrieval-augmented generation survey large language models`
  - `multilingual E5 text embeddings`
  - `mMARCO multilingual passage ranking cross-encoder`
  - `passage re-ranking with BERT`
  - `reciprocal rank fusion`
  - `lost in the middle language models long contexts`
  - `RAGAS automated evaluation retrieval augmented generation`
  - `judging LLM-as-a-judge`
- **Criterios de inclusión:**
  - Publicado entre 2009 y 2026.
  - Artículo revisado por pares, o preprint ampliamente citado.
  - Responde a alguna de las preguntas PB1 a PB5.
  - Se pudo leer al menos el resumen en la página original.
- **Criterios de exclusión:**
  - Blogs, páginas comerciales y repositorios de código sin evaluación.
  - Trabajos que no se pudieron abrir para verificarlos. Por ejemplo, un artículo de 2026
    sobre validación de respuestas con RAG agéntico para datasheets de IoT apareció en la
    búsqueda, pero su página no se pudo consultar.
- **Resultado:** 14 trabajos incluidos.

## 3. Trabajos incluidos

| # | Trabajo | Pregunta | Qué aporta | Relación con este proyecto |
|---|---|---|---|---|
| 1 | Lewis et al. (2020), RAG para tareas intensivas en conocimiento | PB1 | Une un generador con un índice vectorial consultado por un recuperador neuronal; produce respuestas más específicas y factuales que un modelo solo paramétrico | Es la arquitectura base. Lo confirmamos: sin RAG el modelo inventó datos en el 21 % de las respuestas, con RAG en el 2 % |
| 2 | Gao et al. (2023), revisión de RAG para LLM | PB1 | Clasifica los sistemas en RAG ingenuo, avanzado (con pre y posrecuperación, p. ej. reordenamiento) y modular | El sistema es un **RAG avanzado**: recuperación densa + reordenamiento + instrucciones de cita y abstención |
| 3 | Curavale et al. (2026), recuperación de datasheets con RAG para selección de componentes (Infineon) | PB2, PB3 | Asistente de datasheets de microcontroladores con fragmentos de 1000 caracteres, embeddings densos y reordenador cross-encoder (ms-marco-MiniLM). BM25 sobre fragmentos alcanza 33 % en k=1; con resúmenes y reordenador, 72 %. Evaluación piloto de 18 consultas | El antecedente más cercano. Coincide en usar datasheets, un cross-encoder y que BM25 es una línea base débil (nuestro hit@5 con BM25: 0,28). Ellos buscan componentes equivalentes; nosotros respondemos preguntas puntuales con cita de página |
| 4 | Lee y Choi (2026), TechDocRAG | PB2 | Los pipelines RAG típicos "aplanan" cláusulas, tablas y figuras en fragmentos independientes y pierden sus relaciones. Modelan el documento como un grafo y suben el acierto de evidencia de 0,51 (híbrida) a 0,94 | Explica nuestro principal error: tablas partidas que pierden su título y encabezado. Nuestra solución (D22, cada parte repite título y encabezado) es una versión simple de preservar esa relación |
| 5 | Sobhan y Haque (2025), RAG consciente de datos estructurados para documentos técnicos | PB2, PB5 | Pipeline para tablas e imágenes con reordenador ajustado (Gemma-2-9b); fidelidad del 94 % con RAGAS | Muestra que las tablas son el punto difícil y que el reordenador es la pieza clave. No ajustamos el reordenador por falta de GPU |
| 6 | El Bachyr et al. (2026), evaluación empírica de extracción de PDF y fragmentación | PB2, PB4 | Compara analizadores de PDF y estrategias de fragmentación (con solapamiento) en preguntas financieras con tablas | Respalda comparar modos de extracción y tamaños de fragmento con experimentos, como hicimos (modos `simple`/`tablas`, 150 frente a 300 palabras) |
| 7 | Soman y Roychowdhury (2024), observaciones al construir RAG para documentos técnicos (Ericsson) | PB2, PB4 | Los embeddings se vuelven poco confiables con fragmentos largos; excluyeron tablas, lo que limita la recuperación | Coincide con nuestra elección de 150 palabras: a 300 palabras el modelo de embeddings truncaba el 39 % de los fragmentos de tabla (D13). Nosotros sí indexamos las tablas |
| 8 | Wang et al. (2024), Multilingual E5 | PB3 | Familia de embeddings multilingües (small, base, large) entrenada con unos 1000 millones de pares de texto y ajuste fino con MS MARCO | Justifica multilingual-e5-small: preguntas en español, 17 de 23 documentos en inglés y CPU sin GPU |
| 9 | Nogueira y Cho (2019), reordenamiento de pasajes con BERT | PB3 | Un cross-encoder que lee pregunta y pasaje juntos mejora un 27 % relativo el MRR@10 en MS MARCO | Fundamento del reordenamiento. En nuestro corpus duplicó hit@1 (0,27 → 0,58) y subió la corrección +0,17 (p = 0,007) |
| 10 | Bonifacio et al. (2021), mMARCO | PB3 | MS MARCO traducido a 13 idiomas; los reordenadores multilingües entrenados con él superan a los entrenados solo en inglés | Es el origen del reordenador usado (mmarco-mMiniLMv2), adecuado para preguntas en español |
| 11 | Cormack et al. (2009), Reciprocal Rank Fusion | PB3 | Método para combinar rankings de varios buscadores | Se probó la búsqueda híbrida con RRF; aquí empeoró a la semántica (hit@5 0,50 frente a 0,60) porque BM25 falla entre idiomas |
| 12 | Liu et al. (2023), *Lost in the Middle* | PB4 | Los modelos usan peor la información situada en medio de contextos largos | Apoya enviar pocos fragmentos bien ordenados (K = 5, ~1950 tokens) en lugar de muchos |
| 13 | Es et al. (2023), RAGAS | PB5 | Evalúa por separado la calidad de la recuperación, el uso fiel del contexto y la calidad de la respuesta | Nuestras métricas siguen esa división: hit@k y MRR para la recuperación; fidelidad, alucinación y contexto suficiente para el uso del contexto; corrección para la respuesta |
| 14 | Zheng et al. (2023), LLM como juez | PB5 | GPT-4 como juez coincide con humanos en más del 80 %; tiene sesgos de posición, verbosidad y autopreferencia | Justifica usar un juez distinto del generador y auditarlo: coincidió 92 % con la revisión manual de 24 respuestas. Encontramos otro sesgo (premiaba abstenciones) y lo corregimos con reglas (D20) |

## 4. Síntesis

1. **Estado del arte.** RAG es la forma establecida de dar a un LLM conocimiento específico
   y verificable sin reentrenarlo (1, 2). En documentación técnica, el problema abierto son
   las tablas y las relaciones entre elementos del documento (4, 5, 6, 7).
2. **Componentes.** Los trabajos más cercanos (3, 5) usan la misma combinación que este
   proyecto: recuperación densa más un reordenador cross-encoder. Los reordenadores
   entrenados con datos multilingües (10) son los adecuados para preguntas en español.
3. **Brecha que cubre el proyecto:**
   - Los trabajos encontrados están en inglés y usan modelos grandes o GPU. Este sistema
     responde en español sobre datasheets en inglés, corre en un PC sin GPU con 8 GB de
     RAM y usa modelos gratuitos.
   - Mide con pruebas estadísticas pareadas cuánto aporta cada componente.
4. **Diferencia con el antecedente más cercano (3):** aquel elige componentes equivalentes
   con 18 consultas; este proyecto responde preguntas técnicas puntuales citando la página,
   con 66 preguntas verificadas en los PDF y una línea base sin RAG.

## 5. Por qué IA y no programación clásica

| Alternativa clásica | Limitación | Evidencia |
|---|---|---|
| Buscar palabras clave en los PDF (Ctrl+F, BM25) | No relaciona preguntas en español con texto en inglés ni sinónimos ("solo de entrada" frente a *input-only*) | BM25 recupera la página correcta en el 28 % de las preguntas (hit@5), contra 82 % de la búsqueda semántica con reordenador |
| Extracción por reglas a una base de datos de parámetros | Cada fabricante usa un formato distinto de tablas y nombres de parámetros; habría que escribir reglas por documento y mantenerlas | 23 documentos de 6 familias y 8 fabricantes |
| LLM sin recuperación | Inventa valores con seguridad | 21 % de alucinación y 0 de 6 abstenciones correctas sin RAG |
| Ajuste fino del LLM | Requiere GPU y reentrenar con cada documento nuevo; no da citas verificables | El PC no tiene GPU; la base se alimenta de forma continua (D24) |

## 6. Referencias

1. Lewis, P., et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. arXiv:2005.11401. <https://arxiv.org/abs/2005.11401>
2. Gao, Y., et al. (2023). *Retrieval-Augmented Generation for Large Language Models: A Survey*. arXiv:2312.10997. <https://arxiv.org/abs/2312.10997v1>
3. Curavale, D., Nicolae, G., Caranica, A., Cucu, H., Burileanu, C., Davidoiu, V., Buzo, A., y Pelz, G. (2026). Efficient Similarity-Based Datasheet Retrieval and Analysis Using Retrieval-Augmented Generation for Electronic Component Selection. *Electronics*, 15(11), 2301. <https://www.mdpi.com/2079-9292/15/11/2301>
4. Lee, S., y Choi, M. (2026). TechDocRAG: Relation-Preserving Retrieval-Augmented Generation (RAG) for Technical Documents. *AI*, 7(5), 161. <https://doi.org/10.3390/ai7050161>
5. Sobhan, S., y Haque, M. A. (2025). *LLM-Assisted Question-Answering on Technical Documents Using Structured Data-Aware Retrieval Augmented Generation*. arXiv:2506.23136. <https://arxiv.org/pdf/2506.23136>
6. El Bachyr, O., et al. (2026). *Empirical Evaluation of PDF Parsing and Chunking for Financial Question Answering with RAG*. arXiv:2604.12047. <https://arxiv.org/abs/2604.12047>
7. Soman, S., y Roychowdhury, S. (2024). *Observations on Building RAG Systems for Technical Documents*. ICLR 2024 Tiny Papers. arXiv:2404.00657. <https://arxiv.org/pdf/2404.00657>
8. Wang, L., Yang, N., Huang, X., Yang, L., Majumder, R., y Wei, F. (2024). *Multilingual E5 Text Embeddings: A Technical Report*. arXiv:2402.05672. <https://arxiv.org/abs/2402.05672>
9. Nogueira, R., y Cho, K. (2019). *Passage Re-ranking with BERT*. arXiv:1901.04085. <https://arxiv.org/abs/1901.04085v2>
10. Bonifacio, L., et al. (2021). *mMARCO: A Multilingual Version of the MS MARCO Passage Ranking Dataset*. arXiv:2108.13897. <https://arxiv.org/abs/2108.13897v2>
11. Cormack, G. V., Clarke, C. L. A., y Buettcher, S. (2009). Reciprocal rank fusion outperforms Condorcet and individual rank learning methods. *Proc. 32nd ACM SIGIR*, 758–759. <https://research.google/pubs/pub36196/>
12. Liu, N. F., et al. (2023). *Lost in the Middle: How Language Models Use Long Contexts*. arXiv:2307.03172. <https://arxiv.org/abs/2307.03172v3>
13. Es, S., James, J., Espinosa-Anke, L., y Schockaert, S. (2023). *Ragas: Automated Evaluation of Retrieval Augmented Generation*. arXiv:2309.15217. <https://arxiv.org/abs/2309.15217>
14. Zheng, L., et al. (2023). Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. *NeurIPS 2023 Datasets and Benchmarks*. arXiv:2306.05685. <https://arxiv.org/abs/2306.05685>
