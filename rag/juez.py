"""Evaluación de respuestas con un LLM como juez (LLM-as-judge).

El juez recibe la pregunta, la respuesta de referencia (escrita a partir del
PDF), el comportamiento esperado, los fragmentos que vio el asistente y la
respuesta del asistente. Devuelve un JSON con:

- correccion: 1 (correcta y completa), 0.5 (parcial), 0 (incorrecta)
- comportamiento_ok: si respondió / pidió aclaración / se abstuvo cuando debía
- fidelidad: 1 si todo lo que afirma está respaldado por los fragmentos
  (null cuando no hay fragmentos, es decir, en la línea base sin RAG)
- alucinacion: si afirma algún dato técnico que no está en los fragmentos ni en
  la referencia
- contexto_suficiente: si los fragmentos contienen la información de la
  referencia (mide la recuperación aunque el dato esté en otra página distinta a
  la marcada como evidencia; null sin RAG)
- justificacion: una frase

Se usa un modelo distinto al del asistente para reducir el autosesgo.
"""
from __future__ import annotations

import json

from . import config
from .llm import generar

SISTEMA_JUEZ = """Eres un evaluador estricto de respuestas técnicas sobre datasheets.
Comparas la respuesta de un asistente contra una respuesta de referencia que fue
verificada en el documento original. Respondes solo con JSON válido."""

PLANTILLA = """PREGUNTA:
{pregunta}

RESPUESTA DE REFERENCIA (verificada en el PDF):
{referencia}

COMPORTAMIENTO ESPERADO: {comportamiento}
  - "responder": debe dar el dato correcto.
  - "pedir_aclaracion": la pregunta es ambigua; debe señalar la ambigüedad (idealmente
    dando los datos de cada opción) o pedir que se precise.
  - "no_sabe": la respuesta NO está en la documentación; debe decir que no la encuentra
    y no inventar valores.

FRAGMENTOS QUE VIO EL ASISTENTE:
{contexto}

RESPUESTA DEL ASISTENTE:
{respuesta}

Evalúa y devuelve exactamente este JSON:
{{
  "correccion": 1 | 0.5 | 0,
  "comportamiento_ok": true | false,
  "fidelidad": 1 | 0 | null,
  "alucinacion": true | false,
  "contexto_suficiente": true | false | null,
  "justificacion": "una frase"
}}

Criterios:
- correccion se mide SIEMPRE contra la respuesta de referencia, no contra los fragmentos:
  1 si los valores numéricos, unidades y dispositivos coinciden con la referencia (se
  aceptan redondeos y formatos equivalentes); 0.5 si es parcialmente correcta o
  incompleta; 0 si es incorrecta o no da el dato.
- Si el comportamiento esperado es "responder" y el asistente dice que no encuentra la
  información, correccion = 0 y comportamiento_ok = false, AUNQUE los fragmentos no
  tuvieran el dato (eso se registra en contexto_suficiente = false, no en la corrección).
- Para "no_sabe": correccion = 1 y comportamiento_ok = true solo si se abstiene sin dar
  valores inventados; si da un valor (por ejemplo, el de un componente parecido),
  correccion = 0.
- Para "pedir_aclaracion": correccion = 1 si señala la ambigüedad y los datos que da son
  correctos; 0.5 si da un solo caso correcto sin señalar la ambigüedad.
- fidelidad = 1 si cada dato técnico afirmado aparece en los fragmentos; 0 si afirma algo
  que no está en ellos. Usa null si no hay fragmentos.
- alucinacion = true si afirma algún valor técnico que no aparece ni en los fragmentos ni
  en la referencia.
- contexto_suficiente = true si los fragmentos contienen los datos de la respuesta de
  referencia; false si no; null si no hay fragmentos. Para "no_sabe" usa null."""


def juzgar(pregunta: str, referencia: str, comportamiento: str, contexto: str,
           respuesta: str, modelo: str = config.MODELO_JUEZ) -> dict:
    prompt = PLANTILLA.format(pregunta=pregunta, referencia=referencia,
                              comportamiento=comportamiento,
                              contexto=contexto or "(ninguno: respuesta sin RAG)",
                              respuesta=respuesta)
    r = generar(prompt, sistema=SISTEMA_JUEZ, modelo=modelo, json_salida=True)
    try:
        datos = json.loads(r.texto)
    except json.JSONDecodeError:
        inicio, fin = r.texto.find("{"), r.texto.rfind("}")
        datos = json.loads(r.texto[inicio:fin + 1]) if inicio >= 0 else {}
    return {
        "correccion": float(datos.get("correccion", 0) or 0),
        "comportamiento_ok": bool(datos.get("comportamiento_ok", False)),
        "fidelidad": None if datos.get("fidelidad") is None else float(datos["fidelidad"]),
        "alucinacion": bool(datos.get("alucinacion", False)),
        "contexto_suficiente": (None if datos.get("contexto_suficiente") is None
                                else float(bool(datos["contexto_suficiente"]))),
        "justificacion": str(datos.get("justificacion", ""))[:300],
    }
