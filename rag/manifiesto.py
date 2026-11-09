"""Lectura y validación del manifiesto del corpus (manifiesto.csv)."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from . import config


class ErrorManifiesto(Exception):
    """El manifiesto tiene un error que impide continuar."""


@dataclass(frozen=True)
class Documento:
    doc_id: str
    nombre: str           # nombre descriptivo (se usa como encabezado de los fragmentos)
    archivo: str          # ruta relativa a la carpeta datasheets
    familia: str
    fabricante: str
    fuente: str
    idioma: str
    revision: str
    paginas_totales: int
    paginas: tuple[int, ...]   # páginas a indexar, numeradas desde 1
    incluir: bool
    notas: str

    @property
    def ruta(self) -> Path:
        return config.DIR_DATASHEETS / self.archivo


def parsear_rango(rango: str) -> list[int]:
    """Convierte '1,3-13,21-26' en [1, 3, 4, ..., 13, 21, ..., 26]."""
    paginas: list[int] = []
    for parte in filter(None, (p.strip() for p in rango.split(","))):
        inicio, _, fin = parte.partition("-")
        try:
            a, b = int(inicio), int(fin or inicio)
        except ValueError as exc:
            raise ErrorManifiesto(f"Rango de páginas inválido: '{parte}'") from exc
        if a < 1 or b < a:
            raise ErrorManifiesto(f"Rango de páginas inválido: '{parte}'")
        paginas.extend(range(a, b + 1))
    if len(paginas) != len(set(paginas)):
        raise ErrorManifiesto(f"Páginas repetidas en el rango '{rango}'")
    return paginas


def cargar_manifiesto(ruta: Path = config.RUTA_MANIFIESTO,
                      solo_incluidos: bool = True) -> list[Documento]:
    """Lee el manifiesto y valida cada fila. Lanza ErrorManifiesto si algo falla."""
    if not ruta.exists():
        raise ErrorManifiesto(f"No se encontró el manifiesto en {ruta}")

    with open(ruta, encoding="utf-8-sig", newline="") as fh:
        filas = list(csv.DictReader(fh))

    errores: list[str] = []
    documentos: list[Documento] = []
    vistos: set[str] = set()

    for i, fila in enumerate(filas, start=2):  # fila 1 = encabezado
        doc_id = fila["doc_id"].strip()
        incluir = fila["incluir"].strip().lower()
        if incluir not in ("si", "no"):
            errores.append(f"Fila {i}: 'incluir' debe ser si/no, no '{incluir}'")
            continue
        if doc_id in vistos:
            errores.append(f"Fila {i}: doc_id repetido '{doc_id}'")
        vistos.add(doc_id)

        try:
            paginas = parsear_rango(fila["paginas_indexar"])
        except ErrorManifiesto as exc:
            errores.append(f"Fila {i} ({doc_id}): {exc}")
            continue

        doc = Documento(
            doc_id=doc_id,
            nombre=fila["nombre"].strip(),
            archivo=fila["archivo"].strip(),
            familia=fila["familia"].strip(),
            fabricante=fila["fabricante"].strip(),
            fuente=fila["fuente"].strip(),
            idioma=fila["idioma"].strip(),
            revision=fila["revision"].strip(),
            paginas_totales=int(fila["paginas_totales"]),
            paginas=tuple(paginas),
            incluir=incluir == "si",
            notas=fila["notas"].strip(),
        )

        if doc.incluir:
            if not doc.ruta.exists():
                errores.append(f"Fila {i} ({doc_id}): no existe el archivo {doc.ruta}")
            if not paginas:
                errores.append(f"Fila {i} ({doc_id}): incluido pero sin páginas a indexar")
            elif max(paginas) > doc.paginas_totales:
                errores.append(f"Fila {i} ({doc_id}): página {max(paginas)} supera "
                               f"el total ({doc.paginas_totales})")
        documentos.append(doc)

    if errores:
        raise ErrorManifiesto("Errores en el manifiesto:\n  - " + "\n  - ".join(errores))

    return [d for d in documentos if d.incluir] if solo_incluidos else documentos
