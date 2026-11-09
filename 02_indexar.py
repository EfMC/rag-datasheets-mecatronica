"""Etapa 2: fragmenta las páginas extraídas y calcula los embeddings.

Uso:
    python 02_indexar.py                               # índice por defecto
    python 02_indexar.py --modo tablas --tamano 300
    python 02_indexar.py --todos                       # todos los del experimento

Los embeddings se guardan en datos/indices/<modo>_c<tamaño>_<modelo>/ y se
reutilizan mientras los chunks no cambien.
"""
import argparse
import itertools
import json
import sys

from rag import config
from rag.busqueda import Indice


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--modo", choices=config.MODOS_EXTRACCION, default="tablas")
    p.add_argument("--tamano", type=int, default=config.TAMANO_CHUNK)
    p.add_argument("--modelo", default=config.MODELO_EMBEDDINGS)
    p.add_argument("--todos", action="store_true",
                   help="Construye todas las combinaciones modo × tamaño con el modelo indicado")
    p.add_argument("--forzar", action="store_true", help="Recalcula aunque exista el índice")
    a = p.parse_args()

    combinaciones = (itertools.product(config.MODOS_EXTRACCION, config.TAMANOS_CHUNK_EXPERIMENTO)
                     if a.todos else [(a.modo, a.tamano)])
    for modo, tamano in combinaciones:
        indice = Indice(modo, tamano, a.modelo).construir(forzar=a.forzar)
        meta = json.loads((indice.dir / "meta.json").read_text(encoding="utf-8"))
        print(f"{indice.nombre:<40} {meta['n_chunks']:>5} chunks  "
              f"{meta['segundos_embeddings']:>6.1f} s  truncados={meta['truncados']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
