"""Sugerencia automática de qué páginas de un PDF indexar (D24).

Aplica las mismas reglas que se usaron a mano para el manifiesto (D2): se excluyen
páginas sin texto útil, encapsulados y empaque, avisos legales, índices, historiales
de revisión, texto genérico de los manuales y páginas de gráficas. La regla mira los
encabezados de cada página (sus primeras líneas), no las menciones en el cuerpo.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pymupdf

# (expresión regular sobre los títulos de la página, motivo de exclusión). Los patrones
# se escriben sin tildes: los títulos se comparan normalizados (sin tildes, minúsculas).
REGLAS = [
    (r"^(package option addendum|orderable information|ordering information|informacion de pedido)", "información de pedido"),
    (r"tape and reel|reel specifications|packaging information|package materials information|^packaging$|tape specifications", "empaque"),
    (r"package outline|example board layout|example stencil|mechanical data|land pattern", "plano mecánico"),
    (r"important notice|legal disclaimer|notas juridicas|disclaimer and copyright", "aviso legal"),
    (r"^revision history|^historial de revisiones", "historial de revisiones"),
    (r"^(table of )?contents$|^indice$|^list of (tables|figures)$|^indice alfabetico$", "índice"),
    (r"guia de (la )?documentacion|^prologo$|documentation support|receiving notification of documentation", "texto genérico"),
    (r"related documentation and resources", "texto genérico"),
    (r"documentacion tecnica de simatic|industry online support|^mysupport", "texto genérico"),
]
_PIE_FIGURA = re.compile(r"^(figure|fig\.?|figura)\s*\d")
MIN_FIGURAS_PAGINA_GRAFICAS = 2   # una página con 2+ figuras y poco texto es de gráficas
_REGLA_GRAFICAS = re.compile(r"typical characteristics|caracteristicas tipicas")
MIN_PALABRAS = 40            # menos que esto: figura o página casi vacía
MAX_PALABRAS_GRAFICAS = 250  # una página de "Typical Characteristics" con pocas palabras son gráficas
MAX_PALABRAS_TITULO = 6      # solo las líneas cortas se tratan como títulos


@dataclass
class DecisionPagina:
    pagina: int
    palabras: int
    incluir: bool
    motivo: str = ""


def _normalizar(linea: str) -> str:
    """Minúsculas y sin tildes (algunos PDF guardan 'í' como 'ı' + tilde combinada)."""
    linea = unicodedata.normalize("NFKD", linea.replace("ı", "i"))
    return "".join(c for c in linea if not unicodedata.combining(c)).lower().strip()


def _titulos(texto: str) -> list[str]:
    """Líneas cortas de la página: así se ven los títulos y encabezados de sección."""
    lineas = (_normalizar(l) for l in texto.splitlines())
    return [l for l in lineas if l and len(l.split()) <= MAX_PALABRAS_TITULO]


def _contar_palabras(texto: str) -> int:
    """Palabras con al menos una letra o dígito (ignora líneas de '____' o '....')."""
    return sum(1 for t in texto.split() if any(c.isalnum() for c in t))


def analizar_pdf(ruta: Path) -> list[DecisionPagina]:
    decisiones = []
    with pymupdf.open(ruta) as pdf:
        for n, pag in enumerate(pdf, start=1):
            texto = pag.get_text()
            palabras = _contar_palabras(texto)
            if palabras < MIN_PALABRAS:
                decisiones.append(DecisionPagina(n, palabras, False, "figura o casi vacía"))
                continue
            titulos = _titulos(texto)
            motivo = next((m for patron, m in REGLAS
                           if any(re.search(patron, l) for l in titulos)), "")
            if not motivo and palabras <= MAX_PALABRAS_GRAFICAS and (
                    any(_REGLA_GRAFICAS.search(l) for l in titulos)
                    or sum(bool(_PIE_FIGURA.match(l)) for l in titulos) >= MIN_FIGURAS_PAGINA_GRAFICAS):
                motivo = "gráficas"
            decisiones.append(DecisionPagina(n, palabras, not motivo, motivo))
    return decisiones


def a_rangos(paginas: list[int]) -> str:
    """[1, 3, 4, 5, 9] -> '1,3-5,9'"""
    rangos, inicio, previo = [], None, None
    for p in sorted(paginas):
        if inicio is None:
            inicio = previo = p
        elif p == previo + 1:
            previo = p
        else:
            rangos.append(f"{inicio}-{previo}" if previo > inicio else str(inicio))
            inicio = previo = p
    if inicio is not None:
        rangos.append(f"{inicio}-{previo}" if previo > inicio else str(inicio))
    return ",".join(rangos)


def resumen_exclusiones(decisiones: list[DecisionPagina]) -> list[tuple[str, str]]:
    """Agrupa páginas excluidas consecutivas con el mismo motivo: [('29-65', 'plano mecánico'), ...]"""
    grupos: list[tuple[list[int], str]] = []
    for d in decisiones:
        if d.incluir:
            continue
        if grupos and grupos[-1][1] == d.motivo and grupos[-1][0][-1] == d.pagina - 1:
            grupos[-1][0].append(d.pagina)
        else:
            grupos.append(([d.pagina], d.motivo))
    return [(a_rangos(p), m) for p, m in grupos]


def detectar_idioma(ruta: Path, paginas: int = 6) -> str:
    """'es' o 'en' contando palabras funcionales en las primeras páginas."""
    es = {"de", "la", "el", "los", "las", "para", "con", "una", "por", "que", "del", "se", "en"}
    en = {"the", "of", "and", "to", "for", "with", "is", "are", "in", "on", "by", "this"}
    with pymupdf.open(ruta) as pdf:
        texto = " ".join(pdf[i].get_text() for i in range(min(paginas, len(pdf)))).lower()
    tokens = re.findall(r"[a-záéíóúñ]+", texto)
    return "es" if sum(t in es for t in tokens) > sum(t in en for t in tokens) else "en"


def detectar_revision(ruta: Path) -> str:
    with pymupdf.open(ruta) as pdf:
        titulo = (pdf.metadata or {}).get("title", "") or ""
    m = re.search(r"\(Rev\.?\s*([A-Z]{1,2})\)", titulo)
    return m.group(1) if m else ""
