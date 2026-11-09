"""Intervalos de confianza (bootstrap) y comparación pareada entre configuraciones.

Uso:  python evaluacion/estadistica.py [config_referencia]

Para cada configuración: corrección media con IC 95 % por bootstrap.
Para cada configuración frente a la de referencia (por defecto rag_final):
diferencia media pareada con IC 95 % y prueba de signos sobre las preguntas
en las que difieren (exacta, binomial).
Guarda reportes/respuestas_estadistica.csv.
"""
import csv
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
B = 10_000
random.seed(2026)


def bootstrap_ic(valores: list[float]) -> tuple[float, float]:
    n = len(valores)
    medias = sorted(sum(random.choices(valores, k=n)) / n for _ in range(B))
    return medias[int(0.025 * B)], medias[int(0.975 * B) - 1]


def prueba_signos(mejor: int, peor: int) -> float:
    """p bilateral exacto de la prueba de signos (binomial con p = 0,5)."""
    n, k = mejor + peor, min(mejor, peor)
    if n == 0:
        return 1.0
    cola = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * cola)


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else "rag_final"
    datos = defaultdict(dict)
    with open(RAIZ / "reportes" / "respuestas_detalle.csv", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            datos[r["config"]][r["id"]] = float(r["correccion"])

    filas = []
    print(f"{'config':<18} {'corrección':>10}  IC 95 %          diferencia vs {ref}   IC 95 %           mejor/peor  p (signos)")
    for cfg, por_id in datos.items():
        valores = list(por_id.values())
        media = sum(valores) / len(valores)
        lo, hi = bootstrap_ic(valores)
        fila = {"config": cfg, "n": len(valores), "correccion": round(media, 3),
                "ic95_inf": round(lo, 3), "ic95_sup": round(hi, 3)}
        linea = f"{cfg:<18} {media:>10.3f}  [{lo:.3f}, {hi:.3f}]"
        if cfg != ref:
            ids = sorted(set(por_id) & set(datos[ref]))
            difs = [por_id[i] - datos[ref][i] for i in ids]
            d = sum(difs) / len(difs)
            dlo, dhi = bootstrap_ic(difs)
            mejor = sum(x > 0 for x in difs)
            peor = sum(x < 0 for x in difs)
            p = prueba_signos(mejor, peor)
            fila.update(dif_vs_ref=round(d, 3), dif_ic95_inf=round(dlo, 3), dif_ic95_sup=round(dhi, 3),
                        mejor_que_ref=mejor, peor_que_ref=peor, p_signos=round(p, 4))
            linea += f"   {d:+.3f}             [{dlo:+.3f}, {dhi:+.3f}]   {mejor:>3}/{peor:<3}     {p:.4f}"
        print(linea)
        filas.append(fila)

    campos = ["config", "n", "correccion", "ic95_inf", "ic95_sup", "dif_vs_ref", "dif_ic95_inf",
              "dif_ic95_sup", "mejor_que_ref", "peor_que_ref", "p_signos"]
    with open(RAIZ / "reportes" / "respuestas_estadistica.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        w.writerows(filas)
    return 0


if __name__ == "__main__":
    sys.exit(main())
