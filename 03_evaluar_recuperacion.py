"""Etapa 3: evalúa la recuperación (sin usar la API) sobre el set de preguntas.

Para cada índice y método de búsqueda calcula hit@k (página correcta en el
top-k), doc@k (documento correcto), cobertura@k y MRR. Las preguntas sin
respuesta en el corpus no entran en estas métricas.

Uso:
    python 03_evaluar_recuperacion.py            # todos los índices del experimento
    python 03_evaluar_recuperacion.py --modelo intfloat/multilingual-e5-base --modo tablas --tamano 300

Salidas en reportes/:
    recuperacion_resumen.csv     una fila por (índice, método)
    recuperacion_por_grupo.csv   desglose por tipo, familia e idioma de la pregunta
    recuperacion_detalle.csv     una fila por pregunta (para el análisis de errores)
"""
import argparse
import csv
import itertools
import sys
import time
from collections import defaultdict

from rag import config
from rag.busqueda import Indice
from rag.metricas import cargar_preguntas, metricas_recuperacion

KS = (1, 3, 5, 10)


def promedio(filas: list[dict], clave: str) -> float:
    return sum(f[clave] for f in filas) / len(filas) if filas else 0.0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--modo", choices=config.MODOS_EXTRACCION)
    p.add_argument("--tamano", type=int)
    p.add_argument("--modelo", default=config.MODELO_EMBEDDINGS)
    p.add_argument("--metodos", nargs="+", choices=config.METODOS_BUSQUEDA,
                   default=["bm25", "semantica", "hibrida"],
                   help="Los métodos con reranking tardan ~7 s por consulta en CPU")
    p.add_argument("--sin-contexto-tablas", action="store_true",
                   help="Usa el chunking anterior a D22 (índices *_v1)")
    p.add_argument("--sufijo", default="", help="Sufijo para los archivos de salida")
    a = p.parse_args()

    modos = [a.modo] if a.modo else config.MODOS_EXTRACCION
    tamanos = [a.tamano] if a.tamano else config.TAMANOS_CHUNK_EXPERIMENTO
    preguntas = [q for q in cargar_preguntas() if q.comportamiento != "no_sabe"]
    idioma_doc = {}  # idioma del primer documento de evidencia

    detalle, resumen, grupos = [], [], []
    for modo, tamano in itertools.product(modos, tamanos):
        indice = Indice(modo, tamano, a.modelo, contexto_tablas=not a.sin_contexto_tablas).construir()
        for c in indice.chunks:
            idioma_doc[c.doc_id] = c.idioma
        for metodo in a.metodos:
            inicio = time.perf_counter()
            filas = []
            for q in preguntas:
                res = indice.buscar(q.pregunta, k=max(KS), metodo=metodo)
                recup = [(r.chunk.doc_id, r.chunk.pagina) for r in res]
                m = metricas_recuperacion(q, recup, KS)
                fila = {"indice": indice.nombre, "modo": modo, "tamano": tamano,
                        "modelo": a.modelo.split("/")[-1], "metodo": metodo,
                        "id": q.id, "tipo": q.tipo, "familia": q.familia,
                        "idioma_doc": idioma_doc.get(sorted(q.docs_evidencia)[0], "?"),
                        **m, "top5": " ; ".join(f"{d}:{pg}" for d, pg in recup[:5])}
                filas.append(fila)
            ms = (time.perf_counter() - inicio) / len(preguntas) * 1000
            detalle.extend(filas)

            base = {k: filas[0][k] for k in ("indice", "modo", "tamano", "modelo", "metodo")}
            r = {**base, "n": len(filas), "ms_por_consulta": round(ms, 1),
                 **{f"hit@{k}": round(promedio(filas, f"hit@{k}"), 3) for k in KS},
                 **{f"doc@{k}": round(promedio(filas, f"doc@{k}"), 3) for k in KS},
                 "cobertura@5": round(promedio(filas, "cobertura@5"), 3),
                 "mrr": round(promedio(filas, "rr"), 3)}
            resumen.append(r)
            print(f"{indice.nombre:<36} {metodo:<9} hit@1={r['hit@1']:.2f} hit@5={r['hit@5']:.2f} "
                  f"hit@10={r['hit@10']:.2f} doc@5={r['doc@5']:.2f} MRR={r['mrr']:.2f} ({ms:.0f} ms/consulta)")

            for campo in ("tipo", "familia", "idioma_doc"):
                por = defaultdict(list)
                for f in filas:
                    por[f[campo]].append(f)
                for valor, fs in sorted(por.items()):
                    grupos.append({**base, "agrupado_por": campo, "grupo": valor, "n": len(fs),
                                   "hit@1": round(promedio(fs, "hit@1"), 3),
                                   "hit@5": round(promedio(fs, "hit@5"), 3),
                                   "doc@5": round(promedio(fs, "doc@5"), 3),
                                   "mrr": round(promedio(fs, "rr"), 3)})

    config.DIR_REPORTES.mkdir(parents=True, exist_ok=True)
    for nombre, filas in (("resumen", resumen), ("por_grupo", grupos), ("detalle", detalle)):
        ruta = config.DIR_REPORTES / f"recuperacion_{nombre}{a.sufijo}.csv"
        with open(ruta, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(filas[0]))
            w.writeheader()
            w.writerows(filas)
    print(f"\nReportes en {config.DIR_REPORTES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
