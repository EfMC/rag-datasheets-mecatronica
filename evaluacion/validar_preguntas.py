"""Valida el set de evaluación contra el manifiesto y los PDF.

Comprueba, para cada pregunta con evidencia:
  1. Que el doc_id existe y está incluido en el manifiesto.
  2. Que la página de evidencia está dentro de `paginas_indexar`.
  3. Que la `clave` aparece en el texto del PDF original en alguna página de evidencia.
  4. (Informativo) Si la clave sobrevive a la extracción en cada modo.

Uso:  python evaluacion/validar_preguntas.py
"""
import csv
import json
import re
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag import config  # noqa: E402
from rag.manifiesto import cargar_manifiesto  # noqa: E402

RUTA_PREGUNTAS = Path(__file__).with_name("preguntas.csv")


def normalizar(texto: str) -> str:
    """Minúsculas, sin espacios y con guiones/menos unificados, para comparar."""
    texto = texto.lower().replace("−", "-").replace("–", "-").replace(" ", " ")
    return re.sub(r"[\s|]+", "", texto)  # "|" para comparar también dentro de tablas


def parsear_evidencia(evidencia: str) -> list[tuple[str, int]]:
    pares = []
    for item in filter(None, evidencia.split(";")):
        doc_id, pagina = item.rsplit(":", 1)
        pares.append((doc_id.strip(), int(pagina)))
    return pares


def cargar_extraidas(modo: str) -> dict:
    ruta = config.ruta_paginas(modo)
    if not ruta.exists():
        return {}
    with open(ruta, encoding="utf-8") as fh:
        return {(r["doc_id"], r["pagina"]): normalizar(r["texto"]) for r in map(json.loads, fh)}


def main() -> int:
    docs = {d.doc_id: d for d in cargar_manifiesto()}
    with open(RUTA_PREGUNTAS, encoding="utf-8-sig", newline="") as fh:
        preguntas = list(csv.DictReader(fh))
    extraidas = {m: cargar_extraidas(m) for m in config.MODOS_EXTRACCION}

    errores, perdidas = [], {m: [] for m in config.MODOS_EXTRACCION}
    cache_pdf: dict[str, pymupdf.Document] = {}

    for q in preguntas:
        evid = parsear_evidencia(q["evidencia"])
        if q["comportamiento"] == "no_sabe":
            if evid:
                errores.append(f"{q['id']}: pregunta sin respuesta no debe tener evidencia")
            continue
        if not evid:
            errores.append(f"{q['id']}: falta evidencia")
            continue

        clave = normalizar(q["clave"])
        encontrada = False
        for doc_id, pag in evid:
            doc = docs.get(doc_id)
            if doc is None:
                errores.append(f"{q['id']}: doc_id '{doc_id}' no existe o no está incluido")
                continue
            if pag not in doc.paginas:
                errores.append(f"{q['id']}: página {pag} de {doc_id} no está indexada")
                continue
            if doc_id not in cache_pdf:
                cache_pdf[doc_id] = pymupdf.open(doc.ruta)
            if clave and clave in normalizar(cache_pdf[doc_id][pag - 1].get_text()):
                encontrada = True
        if clave and not encontrada:
            errores.append(f"{q['id']}: la clave '{q['clave']}' no aparece en sus páginas de evidencia")

        for modo, paginas in extraidas.items():
            if paginas and clave and not any(clave in paginas.get(e, "") for e in evid):
                perdidas[modo].append(q["id"])

    total = len(preguntas)
    tipos: dict[str, int] = {}
    for q in preguntas:
        tipos[q["tipo"]] = tipos.get(q["tipo"], 0) + 1
    print(f"{total} preguntas. Por tipo: {dict(sorted(tipos.items()))}")

    for modo, ids in perdidas.items():
        if extraidas[modo]:
            print(f"[{modo}] claves que no sobreviven a la extracción ({len(ids)}): {ids}")

    if errores:
        print("\nERRORES:\n  - " + "\n  - ".join(errores))
        return 1
    print("OK: todas las evidencias están indexadas y las claves aparecen en el PDF.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
