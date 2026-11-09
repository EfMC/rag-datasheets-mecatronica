"""Asistente RAG: recupera fragmentos, arma el prompt y genera la respuesta citada."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import config
from .busqueda import Indice, Resultado
from .llm import CuotaAgotada, RespuestaLLM, generar

SISTEMA_RAG = f"""Eres un asistente técnico para estudiantes e ingenieros de mecatrónica.
Respondes preguntas sobre datasheets y manuales usando ÚNICAMENTE los fragmentos de
documentación que se te entregan.

Reglas:
1. Usa solo la información de los fragmentos. No completes con conocimiento propio.
2. Cita cada dato con el formato [doc_id, pág. N], usando el doc_id y la página que
   aparecen en el encabezado del fragmento.
3. Indica siempre a qué dispositivo o variante corresponde cada valor (por ejemplo,
   LM324 frente a LM2902) y conserva las unidades y condiciones de medida.
4. Si la pregunta es ambigua porque puede referirse a varios componentes de los
   fragmentos, dilo explícitamente, da el dato de cada uno y pide que se precise.
5. Si los fragmentos no contienen la respuesta, empieza tu respuesta exactamente con:
   "{config.FRASE_NO_SABE}" y no inventes valores, aunque haya un componente parecido.
6. Si dos fuentes se contradicen, señálalo.
7. Responde en español, de forma breve y directa."""

SISTEMA_SIN_RAG = f"""Eres un asistente técnico para estudiantes e ingenieros de mecatrónica.
Responde preguntas sobre componentes electrónicos, microcontroladores y PLC con tu
propio conocimiento. Indica a qué dispositivo o variante corresponde cada valor.
Si no conoces la respuesta, empieza exactamente con: "{config.FRASE_NO_SABE}"
Responde en español, de forma breve y directa."""

_CITA = re.compile(r"\[([a-z0-9_.\-]+),\s*p[áa]g(?:ina|s)?\.?\s*(\d+(?:\s*[-,y]\s*\d+)*)\]", re.IGNORECASE)


@dataclass
class RespuestaAsistente:
    pregunta: str
    texto: str
    fragmentos: list[Resultado] = field(default_factory=list)
    citas: list[tuple[str, int]] = field(default_factory=list)
    llm: RespuestaLLM | None = None

    @property
    def modelo_respaldo(self) -> bool:
        """True si respondió un modelo de respaldo y no el principal."""
        return bool(self.llm) and self.llm.modelo != config.MODELO_LLM

    @property
    def se_abstiene(self) -> bool:
        return self.texto.strip().lower().startswith(config.FRASE_NO_SABE.lower()[:30])


def extraer_citas(texto: str) -> list[tuple[str, int]]:
    """Encuentra citas [doc_id, pág. N] (también 'pág. 11, 12' o 'pág. 3-4')."""
    citas = []
    for doc, paginas in _CITA.findall(texto):
        for n in re.findall(r"\d+", paginas):
            citas.append((doc.lower(), int(n)))
    return list(dict.fromkeys(citas))


def armar_contexto(resultados: list[Resultado]) -> str:
    partes = []
    for i, r in enumerate(resultados, start=1):
        c = r.chunk
        partes.append(f"--- Fragmento {i} ---\n[{c.nombre} — {c.doc_id}, pág. {c.pagina}]\n{c.texto}")
    return "\n\n".join(partes)


def _generar_con_respaldo(prompt: str, sistema: str, modelo: str,
                          respaldos: tuple[str, ...]) -> RespuestaLLM:
    """Prueba el modelo principal y, si falla por errores del servidor o cuota, los de
    respaldo en orden. Sin respaldos se comporta como `generar` (se usa en la evaluación)."""
    if not respaldos:
        return generar(prompt, sistema=sistema, modelo=modelo)
    candidatos = (modelo, *respaldos)
    for i, m in enumerate(candidatos):
        ultimo = i == len(candidatos) - 1
        try:
            return generar(prompt, sistema=sistema, modelo=m,
                           max_reintentos=config.MAX_REINTENTOS if ultimo else config.REINTENTOS_INTERACTIVO,
                           espera_inicial=config.ESPERA_INTERACTIVO_S)
        except Exception as exc:  # 5xx persistentes, timeouts o CuotaAgotada
            if ultimo:
                raise
            motivo = "cuota agotada" if isinstance(exc, CuotaAgotada) else type(exc).__name__
            print(f"    {m} no respondió ({motivo}); probando {candidatos[i + 1]}...")
    raise RuntimeError("Ningún modelo respondió")


def responder(pregunta: str, indice: Indice | None, metodo: str = config.METODO_DEFECTO,
              k: int = config.K_CONTEXTO, modelo: str = config.MODELO_LLM,
              respaldos: tuple[str, ...] = ()) -> RespuestaAsistente:
    """Responde una pregunta. Con `indice=None` responde sin RAG (línea base).

    `respaldos` solo se usa en modo interactivo: la evaluación usa siempre un único
    modelo para que las comparaciones sean justas."""
    if indice is None:
        llm = _generar_con_respaldo(pregunta, SISTEMA_SIN_RAG, modelo, respaldos)
        return RespuestaAsistente(pregunta, llm.texto, llm=llm)

    resultados = indice.buscar(pregunta, k=k, metodo=metodo)
    prompt = (f"Fragmentos de documentación:\n\n{armar_contexto(resultados)}\n\n"
              f"--- Fin de los fragmentos ---\n\nPregunta: {pregunta}")
    llm = _generar_con_respaldo(prompt, SISTEMA_RAG, modelo, respaldos)
    return RespuestaAsistente(pregunta, llm.texto, resultados, extraer_citas(llm.texto), llm)
