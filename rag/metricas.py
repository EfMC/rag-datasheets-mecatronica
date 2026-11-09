"""Carga del set de evaluación y métricas de recuperación."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from . import config

RUTA_PREGUNTAS = config.RAIZ_CODIGO / "evaluacion" / "preguntas.csv"


@dataclass(frozen=True)
class Pregunta:
    id: str
    pregunta: str
    respuesta_referencia: str
    evidencia: frozenset[tuple[str, int]]   # {(doc_id, página)}
    tipo: str
    familia: str
    comportamiento: str                     # responder | pedir_aclaracion | no_sabe

    @property
    def docs_evidencia(self) -> frozenset[str]:
        return frozenset(d for d, _ in self.evidencia)


def cargar_preguntas(ruta: Path = RUTA_PREGUNTAS) -> list[Pregunta]:
    with open(ruta, encoding="utf-8-sig", newline="") as fh:
        filas = list(csv.DictReader(fh))
    preguntas = []
    for f in filas:
        evid = set()
        for item in filter(None, f["evidencia"].split(";")):
            doc, pag = item.rsplit(":", 1)
            evid.add((doc.strip(), int(pag)))
        preguntas.append(Pregunta(f["id"], f["pregunta"], f["respuesta_referencia"],
                                  frozenset(evid), f["tipo"], f["familia"], f["comportamiento"]))
    return preguntas


def metricas_recuperacion(pregunta: Pregunta, recuperados: list[tuple[str, int]],
                          ks: tuple[int, ...] = (1, 3, 5, 10)) -> dict:
    """Métricas para una pregunta dada la lista ordenada de (doc_id, página) recuperados.

    - hit@k: alguna de las k primeras páginas recuperadas es página de evidencia.
    - doc@k: alguno de los k primeros fragmentos es del documento correcto.
    - cobertura@k: fracción de los documentos de evidencia presentes en el top-k
      (importa en preguntas multidocumento y ambiguas).
    - rr: rango recíproco del primer acierto de página (0 si no aparece).
    """
    m: dict[str, float] = {}
    for k in ks:
        top = recuperados[:k]
        m[f"hit@{k}"] = float(any(r in pregunta.evidencia for r in top))
        m[f"doc@{k}"] = float(any(d in pregunta.docs_evidencia for d, _ in top))
        docs_top = {d for d, _ in top}
        m[f"cobertura@{k}"] = len(pregunta.docs_evidencia & docs_top) / len(pregunta.docs_evidencia)
    m["rr"] = next((1.0 / i for i, r in enumerate(recuperados, start=1) if r in pregunta.evidencia), 0.0)
    return m
