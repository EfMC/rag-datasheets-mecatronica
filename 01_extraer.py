"""Etapa 1: extrae el texto de los PDF indicados en el manifiesto.

Es incremental: cada documento se extrae una sola vez y se guarda en
datos/procesados/por_documento/<modo>/. Solo se vuelve a procesar si cambian el PDF,
sus páginas a indexar o la versión del código de extracción.

Uso:
    python 01_extraer.py                 # ambos modos (simple y tablas)
    python 01_extraer.py --modo tablas   # un solo modo
    python 01_extraer.py --forzar        # vuelve a extraer todo

Salidas:
    datos/procesados/paginas_<modo>.jsonl   una línea JSON por página (todo el corpus)
    reportes/extraccion_<modo>.csv          estadísticas por documento
"""
import argparse
import csv
import sys

from rag import config
from rag.extraccion import actualizar_extraccion
from rag.manifiesto import ErrorManifiesto, cargar_manifiesto


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--modo", choices=config.MODOS_EXTRACCION,
                        help="Modo de extracción (por defecto, ambos)")
    parser.add_argument("--forzar", action="store_true", help="Ignora la caché y extrae todo")
    args = parser.parse_args()

    try:
        documentos = cargar_manifiesto()
    except ErrorManifiesto as exc:
        print(exc, file=sys.stderr)
        return 1

    config.DIR_REPORTES.mkdir(parents=True, exist_ok=True)
    for modo in ([args.modo] if args.modo else config.MODOS_EXTRACCION):
        print(f"\n== Extracción en modo '{modo}' ==")
        estadisticas = actualizar_extraccion(modo, documentos, forzar=args.forzar)
        with open(config.DIR_REPORTES / f"extraccion_{modo}.csv", "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(estadisticas[0]))
            w.writeheader()
            w.writerows(estadisticas)
    return 0


if __name__ == "__main__":
    sys.exit(main())
