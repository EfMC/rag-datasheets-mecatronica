"""Fragmentación de las páginas extraídas en chunks para la búsqueda.

Reglas:
- Un chunk nunca cruza de una página a otra: así cada respuesta se puede citar
  con su página exacta.
- El texto se divide en unidades (párrafos y tablas) y se empaquetan hasta
  llegar al tamaño objetivo, repitiendo las últimas unidades como solapamiento.
- Una tabla que excede el tamaño se parte por filas y cada parte repite el
  encabezado de la tabla, para no perder el nombre de las columnas.
- Con CONTEXTO_TABLAS (D22), cada tabla lleva además su título (los párrafos cortos
  que la preceden) y el encabezado incluye las filas de títulos de columna que
  vienen después del separador (|t90/°C|0|1|...|9|, |  |MIN|TYP|MAX|).
- Cada chunk lleva un encabezado con el nombre del documento y la página. Ese
  encabezado entra en la búsqueda: ayuda a distinguir componentes parecidos
  (IRFZ44N frente a IRLZ44N) y a buscar con preguntas en español.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from . import config
from .manifiesto import cargar_manifiesto


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    nombre: str
    familia: str
    idioma: str
    pagina: int
    texto: str            # contenido tal como se le muestra al LLM
    n_palabras: int

    @property
    def encabezado(self) -> str:
        return f"[{self.nombre} — {self.doc_id}, pág. {self.pagina}]"

    @property
    def texto_indexado(self) -> str:
        """Texto que se usa para buscar (encabezado + contenido)."""
        return f"{self.encabezado}\n{self.texto}"

    def a_dict(self) -> dict:
        return asdict(self)


def _palabras(texto: str) -> int:
    return len(texto.replace("|", " ").split())


def _es_tabla(unidad: str) -> bool:
    return unidad.lstrip().startswith("|")


def _unidades(texto: str, tamano: int, contexto_tablas: bool = True,
              repetidos: frozenset[str] = frozenset()) -> list[str]:
    """Divide el texto de una página en párrafos y tablas que quepan en `tamano`.

    Con `contexto_tablas`, los párrafos cortos que van justo antes de una tabla se
    tratan como su título: se pegan a la tabla (y a cada parte si se parte) en vez de
    quedar como un fragmento suelto. Los párrafos de `repetidos` (encabezados de página
    que se repiten en el documento) nunca se usan como título.
    """
    partes = [p.strip() for p in texto.split("\n\n") if p.strip()]
    unidades: list[str] = []
    titulo_pendiente: list[str] = []   # párrafos cortos que podrían titular una tabla

    def volcar_pendientes():
        for t in titulo_pendiente:
            unidades.append(t)
        titulo_pendiente.clear()

    for parte in partes:
        if _es_tabla(parte):
            titulo = "\n".join(titulo_pendiente) if contexto_tablas else ""
            titulo_pendiente.clear()
            if _palabras(parte) + _palabras(titulo) <= tamano:
                unidades.append(f"{titulo}\n\n{parte}" if titulo else parte)
            else:
                unidades.extend(_partir_tabla(parte, tamano, titulo, contexto_tablas))
            continue
        if (contexto_tablas and _palabras(parte) <= config.MAX_PALABRAS_TITULO_TABLA
                and _normalizar(parte) not in repetidos):
            titulo_pendiente.append(parte)
            # Solo los últimos párrafos cortos antes de la tabla cuentan como título.
            while len(titulo_pendiente) > config.MAX_PARRAFOS_TITULO_TABLA:
                unidades.append(titulo_pendiente.pop(0))
            continue
        volcar_pendientes()
        if _palabras(parte) <= tamano:
            unidades.append(parte)
        else:
            unidades.extend(_partir_texto(parte, tamano))
    volcar_pendientes()
    return unidades


def _normalizar(parrafo: str) -> str:
    """Forma comparable de un párrafo: minúsculas, dígitos como '#' y líneas
    ordenadas (algunos encabezados alternan el orden de sus líneas entre páginas
    pares e impares)."""
    lineas = (re.sub(r"\s+", " ", re.sub(r"\d+", "#", l.lower())).strip()
              for l in parrafo.splitlines())
    return " | ".join(sorted(l for l in lineas if l))


def _parrafos_repetidos(paginas: list[dict]) -> dict[str, frozenset[str]]:
    """Por documento, los párrafos cortos que aparecen en al menos
    UMBRAL_TITULO_REPETIDO de sus páginas (encabezados de página, secciones)."""
    por_doc: dict[str, dict[str, set[int]]] = {}
    n_paginas: dict[str, int] = {}
    for pg in paginas:
        n_paginas[pg["doc_id"]] = n_paginas.get(pg["doc_id"], 0) + 1
        conteo = por_doc.setdefault(pg["doc_id"], {})
        for parte in pg["texto"].split("\n\n"):
            if parte.strip() and _palabras(parte) <= config.MAX_PALABRAS_TITULO_TABLA:
                conteo.setdefault(_normalizar(parte), set()).add(pg["pagina"])
    return {doc: frozenset(t for t, pags in conteo.items()
                           if len(pags) >= 3 and len(pags) >= config.UMBRAL_TITULO_REPETIDO * n_paginas[doc])
            for doc, conteo in por_doc.items()}


_NUMERO = re.compile(r"^[-–+]?\d[\d\s.,]*$")


def _celdas(fila: str) -> list[str]:
    return [c.strip() for c in fila.strip().strip("|").split("|")]


def _parece_encabezado(fila: str) -> bool:
    """Fila de encabezado: sin números de 2 o más dígitos y, o empieza vacía
    (|  |MIN|TYP|MAX|) o tiene todas las celdas llenas (|t90/°C|0|1|...|9|)."""
    celdas = _celdas(fila)
    if any(_NUMERO.match(c) and sum(ch.isdigit() for ch in c) >= 2 for c in celdas):
        return False
    return celdas[0] == "" or all(celdas)


def _cabecera_tabla(lineas: list[str], completa: bool) -> int:
    """Número de líneas iniciales que forman el encabezado de la tabla."""
    n = 2                                   # primera fila + separador |---|
    if not completa:
        return n
    while (n < len(lineas) and n < 2 + config.MAX_FILAS_ENCABEZADO_EXTRA
           and _parece_encabezado(lineas[n])):
        n += 1
    return n


def _partir_tabla(tabla: str, tamano: int, titulo: str = "", contexto_tablas: bool = True) -> list[str]:
    """Parte una tabla por filas. Cada parte repite el título y el encabezado."""
    lineas = tabla.splitlines()
    n_cab = _cabecera_tabla(lineas, contexto_tablas)
    cabecera, filas = lineas[:n_cab], lineas[n_cab:]
    prefijo = [titulo, ""] if titulo else []
    partes, actual = [], []
    base = _palabras("\n".join(prefijo + cabecera))
    for fila in filas:
        if actual and base + _palabras("\n".join(actual + [fila])) > tamano:
            partes.append("\n".join(prefijo + cabecera + actual))
            actual = []
        actual.append(fila)
    if actual:
        partes.append("\n".join(prefijo + cabecera + actual))
    return partes


def _partir_texto(texto: str, tamano: int) -> list[str]:
    """Parte un párrafo muy largo por líneas y, si hace falta, por palabras."""
    partes, actual = [], []
    for linea in texto.splitlines():
        palabras = linea.split()
        while len(palabras) > tamano:          # línea gigante: corte por palabras
            if actual:
                partes.append("\n".join(actual)); actual = []
            partes.append(" ".join(palabras[:tamano]))
            palabras = palabras[tamano:]
        linea = " ".join(palabras)
        if actual and _palabras("\n".join(actual + [linea])) > tamano:
            partes.append("\n".join(actual)); actual = []
        if linea:
            actual.append(linea)
    if actual:
        partes.append("\n".join(actual))
    return partes


def _empaquetar(unidades: list[str], tamano: int, solape: int) -> list[str]:
    chunks, actual = [], []
    for u in unidades:
        if actual and _palabras("\n\n".join(actual + [u])) > tamano:
            chunks.append("\n\n".join(actual))
            # Solapamiento: se repiten las últimas unidades que quepan en `solape`.
            cola, n = [], 0
            for prev in reversed(actual):
                n += _palabras(prev)
                if n > solape:
                    break
                cola.insert(0, prev)
            actual = cola
        actual.append(u)
    if actual:
        chunks.append("\n\n".join(actual))
    return chunks


def fragmentar(modo: str, tamano: int, contexto_tablas: bool = config.CONTEXTO_TABLAS) -> list[Chunk]:
    """Lee paginas_<modo>.jsonl y devuelve los chunks de todo el corpus."""
    contexto_tablas = contexto_tablas and modo == "tablas"
    nombres = {d.doc_id: d.nombre for d in cargar_manifiesto()}
    solape = int(tamano * config.SOLAPAMIENTO)
    chunks: list[Chunk] = []
    with open(config.ruta_paginas(modo), encoding="utf-8") as fh:
        paginas = [json.loads(l) for l in fh]
    repetidos = _parrafos_repetidos(paginas) if contexto_tablas else {}
    for pagina in paginas:
        textos = _empaquetar(_unidades(pagina["texto"], tamano, contexto_tablas,
                                       repetidos.get(pagina["doc_id"], frozenset())),
                             tamano, solape)
        for i, texto in enumerate(t for t in textos if _palabras(t) >= config.MIN_PALABRAS_CHUNK):
            chunks.append(Chunk(
                chunk_id=f"{pagina['doc_id']}|p{pagina['pagina']}|{i}",
                doc_id=pagina["doc_id"], nombre=nombres[pagina["doc_id"]],
                familia=pagina["familia"], idioma=pagina["idioma"],
                pagina=pagina["pagina"], texto=texto, n_palabras=_palabras(texto),
            ))
    return chunks
