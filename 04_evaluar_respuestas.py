"""Etapa 4: genera respuestas con Gemini y las califica con el juez.

Configuraciones (todas sobre el mismo set de 66 preguntas):
    sin_rag           el modelo responde solo con su conocimiento (línea base)
    rag_final         configuración final: extracción tablas, chunks de 150,
                      búsqueda semántica + reranking
    rag_sin_rerank    igual, sin reranking (ablación)
    rag_bm25          igual, con búsqueda por palabras clave (ablación)
    rag_final_simple  igual que rag_final con extracción simple (ablación)
    rag_final_v1      rag_final con el chunking de tablas anterior a D22

Uso:
    python 04_evaluar_respuestas.py                         # todas
    python 04_evaluar_respuestas.py --config sin_rag rag_hibrida
    python 04_evaluar_respuestas.py --limite 5              # prueba rápida

Todas las llamadas quedan en caché: si se agota la cuota, se vuelve a ejecutar
más tarde y continúa donde quedó.

Salidas en reportes/:
    respuestas_detalle.csv   una fila por (configuración, pregunta)
    respuestas_resumen.csv   métricas por configuración
    respuestas_por_tipo.csv  métricas por configuración y tipo de pregunta
"""
import argparse
import csv
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from rag import config
from rag.asistente import armar_contexto, responder
from rag.busqueda import Indice
from rag.juez import juzgar
from rag.llm import CuotaAgotada
from rag.metricas import cargar_preguntas

CONFIGS = {
    "sin_rag":             dict(modo=None, metodo=None),
    "rag_final":           dict(modo=config.MODO_DEFECTO, metodo=config.METODO_DEFECTO),
    "rag_sin_rerank":      dict(modo=config.MODO_DEFECTO, metodo="semantica"),
    "rag_bm25":            dict(modo=config.MODO_DEFECTO, metodo="bm25"),
    "rag_final_simple":    dict(modo="simple", metodo=config.METODO_DEFECTO),
    # Chunking anterior a D22 (sin título ni encabezado completo en las tablas).
    "rag_final_v1":        dict(modo=config.MODO_DEFECTO, metodo=config.METODO_DEFECTO,
                                contexto_tablas=False),
}


def media(valores):
    valores = [v for v in valores if v is not None]
    return round(sum(valores) / len(valores), 3) if valores else None


def resumir(filas: list[dict]) -> dict:
    responder_ = [f for f in filas if f["comportamiento"] == "responder"]
    no_sabe = [f for f in filas if f["comportamiento"] == "no_sabe"]
    return {
        "n": len(filas),
        "correccion": media([f["correccion"] for f in filas]),
        "correccion_responder": media([f["correccion"] for f in responder_]),
        "comportamiento_ok": media([float(f["comportamiento_ok"]) for f in filas]),
        "fidelidad": media([f["fidelidad"] for f in filas]),
        "tasa_alucinacion": media([float(f["alucinacion"]) for f in filas]),
        "contexto_suficiente": media([f["contexto_suficiente"] for f in filas]),
        "abstencion_correcta": media([float(f["se_abstiene"]) for f in no_sabe]),
        "abstencion_indebida": media([float(f["se_abstiene"]) for f in responder_]),
        "cita_correcta": media([f["cita_correcta"] for f in filas if f["cita_correcta"] is not None]),
        "citas_fuera_de_contexto": media([f["citas_fuera_contexto"] for f in filas
                                         if f["citas_fuera_contexto"] is not None]),
        "tokens_entrada_medio": media([f["tokens_entrada"] for f in filas]),
        "segundos_medio": media([f["segundos"] for f in filas if not f["desde_cache"]]),
    }


def aplicar_reglas_abstencion(j: dict, comportamiento: str, se_abstiene: bool) -> dict:
    """La abstención se detecta sin ambigüedad (frase fija), así que se califica con
    reglas en vez de confiar en el juez, que en la auditoría premió abstenciones en
    preguntas que sí tenían respuesta.

    - Pregunta con respuesta (responder / pedir_aclaracion) y se abstiene: corrección 0.
    - Pregunta sin respuesta (no_sabe) y se abstiene: corrección 1.
    - Pregunta sin respuesta y NO se abstiene: decide el juez (puede ser una negativa
      redactada de otra forma), pero nunca más de lo que diga el juez.
    """
    j = dict(j, juez_correccion_original=j["correccion"])
    if se_abstiene and comportamiento != "no_sabe":
        j.update(correccion=0.0, comportamiento_ok=False)
    elif se_abstiene and comportamiento == "no_sabe":
        j.update(correccion=1.0, comportamiento_ok=True, alucinacion=False)
    return j


def evaluar_pregunta(q, nombre: str, indice, cfg: dict) -> dict:
    """Genera la respuesta de una pregunta, la califica y arma su fila de resultados."""
    r = responder(q.pregunta, indice, metodo=cfg["metodo"] or config.METODO_DEFECTO)
    contexto = armar_contexto(r.fragmentos) if r.fragmentos else ""
    j = juzgar(q.pregunta, q.respuesta_referencia, q.comportamiento, contexto, r.texto)
    j = aplicar_reglas_abstencion(j, q.comportamiento, r.se_abstiene)

    recuperados = {(f.chunk.doc_id, f.chunk.pagina) for f in r.fragmentos}
    cita_ok = float(any(c in q.evidencia for c in r.citas)) if r.citas and q.evidencia else None
    fuera = (sum(c not in recuperados for c in r.citas) / len(r.citas)
             if r.citas and recuperados else None)
    return {
        "config": nombre, "id": q.id, "tipo": q.tipo, "familia": q.familia,
        "comportamiento": q.comportamiento, "pregunta": q.pregunta,
        "respuesta": r.texto, "referencia": q.respuesta_referencia,
        "se_abstiene": r.se_abstiene,
        "hit_contexto": (float(bool(recuperados & q.evidencia)) if q.evidencia and recuperados
                         else None),
        "citas": " ; ".join(f"{d}:{pg}" for d, pg in r.citas),
        "cita_correcta": cita_ok, "citas_fuera_contexto": fuera,
        **j,
        "tokens_entrada": r.llm.tokens_entrada if r.llm else 0,
        "segundos": r.llm.segundos if r.llm else 0,
        "desde_cache": bool(r.llm and r.llm.desde_cache),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", nargs="+", choices=list(CONFIGS), default=list(CONFIGS))
    p.add_argument("--tamano", type=int, default=config.TAMANO_CHUNK)
    p.add_argument("--limite", type=int, help="Evaluar solo las primeras N preguntas")
    p.add_argument("--sufijo", default="", help="Sufijo para los archivos de salida")
    p.add_argument("--hilos", type=int, default=4,
                   help="Preguntas en paralelo (la latencia del modelo es el cuello de botella)")
    a = p.parse_args()

    preguntas = cargar_preguntas()[: a.limite]
    indices: dict[str, Indice] = {}
    filas: list[dict] = []
    fallidas: list[tuple[str, str]] = []
    interrumpido = False

    for nombre in a.config:
        cfg = CONFIGS[nombre]
        indice = None
        if cfg["modo"]:
            clave = (cfg["modo"], cfg.get("contexto_tablas", True))
            if clave not in indices:
                indices[clave] = Indice(cfg["modo"], a.tamano, contexto_tablas=clave[1]).construir()
            indice = indices[clave]
        print(f"\n== {nombre} ({len(preguntas)} preguntas) ==")
        inicio = time.perf_counter()

        completadas = 0
        with ThreadPoolExecutor(max_workers=a.hilos) as pool:
            futuros = {pool.submit(evaluar_pregunta, q, nombre, indice, cfg): q for q in preguntas}
            resultados = {}
            for fut in as_completed(futuros):
                q = futuros[fut]
                try:
                    resultados[q.id] = fut.result()
                except CuotaAgotada as exc:
                    if not interrumpido:
                        print(f"\n⚠ {exc}\nVuelve a ejecutar más tarde: lo ya calculado está en caché.")
                    interrumpido = True
                    for f in futuros:
                        f.cancel()
                    continue
                except Exception as exc:  # error persistente del servidor: se salta la pregunta
                    fallidas.append((nombre, q.id))
                    print(f"\n    ✗ {q.id} falló ({type(exc).__name__}: {str(exc)[:80]}); se omite", flush=True)
                    continue
                completadas += 1
                c = resultados[q.id]["correccion"]
                marca = "✓" if c == 1 else ("~" if c == 0.5 else "✗")
                print(f"  {completadas:>2}/{len(preguntas)} {q.id:<6} {marca}",
                      end="\n" if completadas % 6 == 0 else "  ", flush=True)
        filas.extend(resultados[q.id] for q in preguntas if q.id in resultados)
        print(f"\n  ({time.perf_counter() - inicio:.0f} s)")
        if interrumpido:
            break

    if not filas:
        return 1
    config.DIR_REPORTES.mkdir(parents=True, exist_ok=True)
    with open(config.DIR_REPORTES / f"respuestas_detalle{a.sufijo}.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)

    por_config, por_tipo = defaultdict(list), defaultdict(list)
    for f in filas:
        por_config[f["config"]].append(f)
        por_tipo[(f["config"], f["tipo"])].append(f)
    resumen = [{"config": c, **resumir(fs)} for c, fs in por_config.items()]
    tipos = [{"config": c, "tipo": t, **resumir(fs)} for (c, t), fs in sorted(por_tipo.items())]
    for nombre, datos in (("resumen", resumen), ("por_tipo", tipos)):
        with open(config.DIR_REPORTES / f"respuestas_{nombre}{a.sufijo}.csv", "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(datos[0]))
            w.writeheader()
            w.writerows(datos)

    print("\nconfig                 corrección  comport.  fidelidad  alucin.  abst.ok  cita ok")
    for r in resumen:
        fmt = lambda v: "  -  " if v is None else f"{v:5.2f}"
        print(f"{r['config']:<22} {fmt(r['correccion'])}       {fmt(r['comportamiento_ok'])}     "
              f"{fmt(r['fidelidad'])}      {fmt(r['tasa_alucinacion'])}    {fmt(r['abstencion_correcta'])}    "
              f"{fmt(r['cita_correcta'])}")
    if fallidas:
        print(f"\n⚠ {len(fallidas)} preguntas fallaron por errores del servidor y no entran en las "
              f"métricas: {fallidas}\nVuelve a ejecutar el script para completarlas.")
    return 2 if interrumpido or fallidas else 0


if __name__ == "__main__":
    sys.exit(main())
