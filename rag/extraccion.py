"""Extracción de texto de los PDF del corpus.

Para cada documento del manifiesto se extraen solo las páginas indicadas en
`paginas_indexar`. Hay dos modos:

- "simple": texto plano por bloques, en orden de lectura (similar a copiar y pegar).
- "tablas": las tablas detectadas se convierten a Markdown (filas y columnas
  explícitas) y el resto de la página se extrae como texto normal.

En ambos modos se eliminan los encabezados y pies de página que se repiten en
los márgenes de la mayoría de las páginas del documento.
"""
from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import asdict, dataclass, field

import pymupdf

from . import config
from .manifiesto import Documento


@dataclass
class Bloque:
    y0: float
    y1: float
    texto: str
    es_tabla: bool = False
    en_margen: bool = False


@dataclass
class Pagina:
    doc_id: str
    nombre: str
    archivo: str
    familia: str
    fabricante: str
    idioma: str
    pagina: int
    modo: str
    texto: str
    n_palabras: int
    n_tablas: int
    alertas: list[str] = field(default_factory=list)

    def a_dict(self) -> dict:
        return asdict(self)


# --- Utilidades de texto ----------------------------------------------------

_ESPACIOS = re.compile(r"[ \t ]+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f�]")
# Guion de corte de línea entre minúsculas: "configu-\nration" -> "configuration".
# No toca nombres de parte como "LM324-N" ni rangos "0-55".
_GUION_CORTE = re.compile(r"([a-záéíóúñ])-\n([a-záéíóúñ])")


def limpiar_texto(texto: str) -> str:
    texto = _CONTROL.sub("", texto)
    texto = _GUION_CORTE.sub(r"\1\2", texto)
    lineas = [_ESPACIOS.sub(" ", l).strip() for l in texto.splitlines()]
    texto = "\n".join(lineas)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def _firma(linea: str) -> str | None:
    """Forma normalizada de una línea para detectar repeticiones.

    Los dígitos se reemplazan por '#' para que "Página 12" y "Página 13"
    cuenten como la misma línea. Las líneas sin letras (números sueltos, filas
    de tablas numéricas) devuelven None: nunca se tratan como encabezados.
    """
    linea = linea.strip().lower()
    if not re.search(r"[a-záéíóúñ]", linea):
        return None
    return re.sub(r"\d+", "#", linea)


def _solapa(a: tuple, b: tuple, minimo: float = 0.5) -> bool:
    """True si el rectángulo `a` queda cubierto al menos `minimo` por `b`."""
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return False
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    return area_a > 0 and (x1 - x0) * (y1 - y0) / area_a >= minimo


def contar_palabras(texto: str) -> int:
    """Cuenta palabras tratando los separadores de tabla '|' como espacios,
    para que ambos modos de extracción sean comparables."""
    return len(texto.replace("|", " ").split())


_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_COLN = re.compile(r"(?<=\|)\s*Col\d+\s*(?=\|)")
# Guiones bajos de cursiva Markdown (_R_), sin tocar nombres como TIM2_CH1.
_CURSIVA = re.compile(r"(?<![A-Za-z0-9])_(?=\S)|(?<=\S)_(?![A-Za-z0-9])")


def tabla_a_markdown(tabla) -> str:
    """Convierte una tabla detectada por PyMuPDF en Markdown limpio.

    Se usa el formateador de PyMuPDF porque conserva bien el orden de los
    caracteres (números decimales y signos negativos). Después se quita el
    formato que no aporta: entidades HTML, <br>, negritas, cursivas y los
    encabezados automáticos "Col2", "Col3"...
    """
    md = tabla.to_markdown(clean=False, fill_empty=False)
    md = html.unescape(html.unescape(md))   # algunas entidades vienen escapadas dos veces
    md = _BR.sub(" ", md).replace("**", "").replace("~~", "")
    md = _CURSIVA.sub("", md)
    md = _COLN.sub(" ", md)
    lineas = [_ESPACIOS.sub(" ", l).strip() for l in md.splitlines()]
    return "\n".join(l for l in lineas if l)


# --- Extracción por página ------------------------------------------------------

_TOKEN = re.compile(r"[a-záéíóúñ0-9µΩ°±.,/+-]+")


def _tokens(texto: str) -> set[str]:
    return set(_TOKEN.findall(texto.lower()))


def _cubierto_por_tabla(texto: str, tokens_tabla: set[str]) -> bool:
    """True si al menos UMBRAL_COBERTURA_TABLA de las palabras del bloque ya
    están dentro de la tabla. Si la tabla no capturó el contenido (celdas
    vacías o caracteres recortados en el borde), el bloque se conserva."""
    tokens = _tokens(texto)
    if not tokens:
        return True
    return len(tokens & tokens_tabla) / len(tokens) >= config.UMBRAL_COBERTURA_TABLA


def _bloques_pagina(pagina: pymupdf.Page, modo: str) -> list[Bloque]:
    tablas: list[tuple[tuple, set[str]]] = []   # (rectángulo, palabras de la tabla)
    bloques: list[Bloque] = []

    if modo == "tablas":
        for tabla in pagina.find_tables().tables:
            md = tabla_a_markdown(tabla)
            if md:
                tablas.append((tuple(tabla.bbox), _tokens(md)))
                bloques.append(Bloque(tabla.bbox[1], tabla.bbox[3], md, es_tabla=True))

    # get_text("blocks") -> (x0, y0, x1, y1, texto, nro_bloque, tipo); tipo 0 = texto
    for x0, y0, x1, y1, texto, _, tipo in pagina.get_text("blocks", sort=True):
        if tipo != 0 or not texto.strip():
            continue
        rect = (x0, y0, x1, y1)
        if any(_solapa(rect, r) and _cubierto_por_tabla(texto, tok) for r, tok in tablas):
            continue  # su contenido ya está dentro de una tabla
        bloques.append(Bloque(y0, y1, texto))

    limite = pagina.rect.height * config.MARGEN_ENCABEZADO
    for b in bloques:
        b.en_margen = not b.es_tabla and (b.y1 <= limite or b.y0 >= pagina.rect.height - limite)

    bloques.sort(key=lambda b: b.y0)
    return bloques


def _lineas_margen(bloques: list[Bloque]) -> set[str]:
    """Firmas de las líneas que están en el margen superior o inferior."""
    firmas = set()
    for b in bloques:
        if b.en_margen:
            firmas.update(f for l in b.texto.splitlines() if (f := _firma(l)))
    return firmas


def extraer_documento(doc: Documento, modo: str) -> tuple[list[Pagina], dict]:
    """Extrae las páginas indicadas de un documento.

    Devuelve la lista de páginas y un diccionario con estadísticas para el reporte.
    """
    if modo not in config.MODOS_EXTRACCION:
        raise ValueError(f"Modo desconocido '{modo}'. Opciones: {config.MODOS_EXTRACCION}")

    with pymupdf.open(doc.ruta) as pdf:
        crudas = []  # (número de página, bloques, firmas en el margen)
        for n in doc.paginas:
            pag = pdf[n - 1]
            bloques = _bloques_pagina(pag, modo)
            crudas.append((n, bloques, _lineas_margen(bloques)))

    # Encabezados/pies: firmas que aparecen en el margen de muchas páginas.
    repetidas: set[str] = set()
    if len(crudas) >= config.MIN_PAGINAS_PARA_LIMPIEZA:
        conteo = Counter(f for _, _, firmas in crudas for f in firmas)
        minimo = config.UMBRAL_REPETICION * len(crudas)
        repetidas = {f for f, c in conteo.items() if c >= minimo}

    paginas: list[Pagina] = []
    lineas_eliminadas = 0
    for n, bloques, _ in crudas:
        partes = []
        for b in bloques:
            if not b.en_margen:  # solo se limpian los márgenes
                partes.append(b.texto)
                continue
            lineas = [l for l in b.texto.splitlines() if _firma(l) not in repetidas]
            lineas_eliminadas += len(b.texto.splitlines()) - len(lineas)
            if lineas:
                partes.append("\n".join(lineas))

        texto = limpiar_texto("\n\n".join(partes))
        n_palabras = contar_palabras(texto)
        alertas = []
        if n_palabras < config.MIN_PALABRAS_PAGINA:
            alertas.append("pocas_palabras")

        paginas.append(Pagina(
            doc_id=doc.doc_id, nombre=doc.nombre, archivo=doc.archivo, familia=doc.familia,
            fabricante=doc.fabricante, idioma=doc.idioma, pagina=n, modo=modo,
            texto=texto, n_palabras=n_palabras,
            n_tablas=sum(b.es_tabla for b in bloques), alertas=alertas,
        ))

    stats = {
        "doc_id": doc.doc_id,
        "familia": doc.familia,
        "idioma": doc.idioma,
        "paginas_indexadas": len(paginas),
        "palabras": sum(p.n_palabras for p in paginas),
        "tablas": sum(p.n_tablas for p in paginas),
        "paginas_con_alerta": sum(bool(p.alertas) for p in paginas),
        "lineas_encabezado_eliminadas": lineas_eliminadas,
        "firmas_encabezado": " | ".join(sorted(repetidas))[:300],
    }
    return paginas, stats


# --- Extracción incremental (D24) ---------------------------------------------------
# Cambia este número cuando cambie la lógica de extracción: invalida la caché.
VERSION_EXTRACCION = 3


def _huella(doc: Documento, modo: str) -> dict:
    import hashlib
    h = hashlib.sha256(doc.ruta.read_bytes()).hexdigest()
    return {"sha256": h, "paginas": list(doc.paginas), "modo": modo,
            "version": VERSION_EXTRACCION, "nombre": doc.nombre, "familia": doc.familia,
            "fabricante": doc.fabricante, "idioma": doc.idioma}


def _dir_documentos(modo: str):
    return config.DIR_PROCESADOS / "por_documento" / modo


def extraer_con_cache(doc: Documento, modo: str, forzar: bool = False) -> tuple[list[dict], dict, bool]:
    """Extrae un documento o reutiliza su extracción guardada si nada cambió.

    Devuelve (páginas como dict, estadísticas, se_reutilizo)."""
    import json
    carpeta = _dir_documentos(modo)
    ruta_pag, ruta_meta = carpeta / f"{doc.doc_id}.jsonl", carpeta / f"{doc.doc_id}.meta.json"
    huella = _huella(doc, modo)
    if not forzar and ruta_pag.exists() and ruta_meta.exists():
        meta = json.loads(ruta_meta.read_text(encoding="utf-8"))
        if meta.get("huella") == huella:
            with open(ruta_pag, encoding="utf-8") as fh:
                return [json.loads(l) for l in fh], meta["stats"], True
    paginas, stats = extraer_documento(doc, modo)
    filas = [p.a_dict() for p in paginas]
    carpeta.mkdir(parents=True, exist_ok=True)
    with open(ruta_pag, "w", encoding="utf-8") as fh:
        for f in filas:
            fh.write(json.dumps(f, ensure_ascii=False) + "\n")
    ruta_meta.write_text(json.dumps({"huella": huella, "stats": stats}, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    return filas, stats, False


def actualizar_extraccion(modo: str, documentos: list[Documento], forzar: bool = False,
                          mostrar: bool = True) -> list[dict]:
    """Extrae (o reutiliza) todos los documentos y escribe paginas_<modo>.jsonl.

    Solo se procesan los documentos nuevos o modificados. Devuelve las estadísticas
    por documento para el reporte."""
    import json
    import time
    inicio = time.perf_counter()
    config.DIR_PROCESADOS.mkdir(parents=True, exist_ok=True)
    estadisticas, nuevos, total = [], 0, 0
    with open(config.ruta_paginas(modo), "w", encoding="utf-8") as salida:
        for doc in documentos:
            filas, stats, reutilizado = extraer_con_cache(doc, modo, forzar)
            for f in filas:
                salida.write(json.dumps(f, ensure_ascii=False) + "\n")
            total += len(filas)
            estadisticas.append(stats)
            if not reutilizado:
                nuevos += 1
                if mostrar:
                    aviso = (f"  ⚠ {stats['paginas_con_alerta']} pág. con alerta"
                             if stats["paginas_con_alerta"] else "")
                    print(f"  extraído {doc.doc_id:<20} {stats['paginas_indexadas']:>4} pág. "
                          f"{stats['palabras']:>7} palabras {stats['tablas']:>4} tablas{aviso}")
    if mostrar:
        print(f"[{modo}] {len(documentos)} documentos ({nuevos} extraídos, {len(documentos) - nuevos} "
              f"reutilizados), {total} páginas en {time.perf_counter() - inicio:.1f} s")
    return estadisticas
