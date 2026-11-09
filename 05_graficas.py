"""Etapa 5: genera las gráficas del informe a partir de los reportes CSV.

Uso:
    python 05_graficas.py

Lee reportes/recuperacion_*.csv y reportes/respuestas_*.csv y guarda PNG en
reportes/graficas/. Si un reporte no existe todavía, esa gráfica se omite.
"""
import csv
import sys
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from rag import config  # noqa: E402

# Paleta categórica validada (orden fijo; contraste suficiente con etiquetas visibles).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
SUPERFICIE, TINTA, TINTA_2, REJILLA = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
DIR_GRAFICAS = config.DIR_REPORTES / "graficas"


def leer(nombre: str) -> list[dict]:
    ruta = config.DIR_REPORTES / nombre
    if not ruta.exists():
        print(f"  (se omite: falta {nombre})")
        return []
    with open(ruta, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def estilo(ax, titulo: str, ylabel: str):
    ax.set_facecolor(SUPERFICIE)
    ax.figure.set_facecolor(SUPERFICIE)
    ax.set_title(textwrap.fill(titulo, 95), loc="left", fontsize=13, color=TINTA, pad=30)
    ax.set_ylabel(ylabel, color=TINTA_2)
    ax.set_ylim(0, 1.18)
    ax.grid(axis="y", color=REJILLA, linewidth=0.8)
    ax.set_axisbelow(True)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(TINTA_2)
    ax.tick_params(colors=TINTA_2, length=0)


def barras(categorias, series: dict[str, list[float]], titulo, ylabel, archivo, rot=0):
    """Barras agrupadas: una serie por color, con el valor escrito sobre cada barra."""
    n = len(series)
    ancho = 0.8 / n
    fig, ax = plt.subplots(figsize=(max(9, 1.3 * len(categorias) * n / 2 + 3), 4.8), dpi=150)
    for i, (nombre, valores) in enumerate(series.items()):
        xs = [x + (i - (n - 1) / 2) * ancho for x in range(len(categorias))]
        b = ax.bar(xs, valores, width=ancho * 0.92, color=SERIES[i], label=nombre,
                   edgecolor=SUPERFICIE, linewidth=1.5)
        for rect, v in zip(b, valores):
            ax.text(rect.get_x() + rect.get_width() / 2, v + 0.015, f"{v:.2f}",
                    ha="center", va="bottom", fontsize=8, color=TINTA)
    ax.set_xticks(range(len(categorias)))
    ax.set_xticklabels(categorias, rotation=rot, ha="right" if rot else "center", color=TINTA)
    estilo(ax, titulo, ylabel)
    if n > 1:
        ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=n,
                  fontsize=9, labelcolor=TINTA)
    fig.tight_layout()
    DIR_GRAFICAS.mkdir(parents=True, exist_ok=True)
    fig.savefig(DIR_GRAFICAS / archivo, facecolor=SUPERFICIE)
    plt.close(fig)
    print(f"  {archivo}")


def main() -> int:
    print("Generando gráficas:")
    base = leer("recuperacion_resumen.csv")
    rerank = leer("recuperacion_resumen_rerank.csv")

    # 1. Métodos de búsqueda sobre la configuración final (tablas, 150 palabras).
    filas = [r for r in base if r["modo"] == "tablas" and r["tamano"] == str(config.TAMANO_CHUNK)]
    filas += [r for r in rerank if r["metodo"].endswith("_rerank")]
    if filas:
        etiquetas = {"bm25": "BM25", "semantica": "Semántica", "hibrida": "Híbrida (RRF)",
                     "semantica_rerank": "Semántica\n+ reranking", "hibrida_rerank": "Híbrida\n+ reranking"}
        barras([etiquetas[r["metodo"]] for r in filas],
               {"hit@1": [float(r["hit@1"]) for r in filas],
                "hit@5": [float(r["hit@5"]) for r in filas],
                "MRR": [float(r["mrr"]) for r in filas]},
               "Recuperación de la página correcta según el método de búsqueda",
               "Proporción de preguntas (n = 60)", "01_metodos_busqueda.png")

    # 2. Tamaño de fragmento y modo de extracción (búsqueda semántica).
    sem = [r for r in base if r["metodo"] == "semantica"]
    if sem:
        tamanos = sorted({int(r["tamano"]) for r in sem})
        serie = {}
        for modo in config.MODOS_EXTRACCION:
            serie[f"extracción {modo}"] = [float(next(r["hit@5"] for r in sem
                                           if r["modo"] == modo and int(r["tamano"]) == t)) for t in tamanos]
        barras([f"{t} palabras" for t in tamanos], serie,
               "hit@5 de la búsqueda semántica según tamaño de fragmento y extracción",
               "hit@5 (n = 60)", "02_tamano_y_extraccion.png")

    # 3. Calidad de las respuestas por configuración.
    resp = leer("respuestas_resumen.csv")
    if resp:
        def v(r, k):
            return float(r[k]) if r[k] not in ("", "None") else 0.0
        barras([r["config"] for r in resp],
               {"Corrección": [v(r, "correccion") for r in resp],
                "Comportamiento esperado": [v(r, "comportamiento_ok") for r in resp],
                "Tasa de alucinación": [v(r, "tasa_alucinacion") for r in resp]},
               "Calidad de las respuestas por configuración (juez: gemini-3.5-flash-lite)",
               "Promedio (n = 66)", "03_respuestas_por_config.png", rot=20)

    # 4. Corrección por tipo de pregunta: sin RAG frente a RAG final.
    tipos = leer("respuestas_por_tipo.csv")
    if tipos:
        orden = sorted({r["tipo"] for r in tipos})
        n_tipo = {r["tipo"]: r["n"] for r in tipos}
        series = {}
        for cfg in ("sin_rag", "rag_final"):
            por = {r["tipo"]: float(r["correccion"] or 0) for r in tipos if r["config"] == cfg}
            if por:
                series[cfg] = [por.get(t, 0.0) for t in orden]
        if series:
            barras([f"{t}\n(n={n_tipo[t]})" for t in orden], series,
                   "Corrección por tipo de pregunta: sin RAG frente a RAG final", "Corrección media",
                   "04_correccion_por_tipo.png", rot=25)
    return 0


if __name__ == "__main__":
    sys.exit(main())
