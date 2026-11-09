"""Asistente interactivo: haz preguntas sobre los datasheets desde la terminal.

Uso:
    python preguntar.py
    python preguntar.py "¿Qué pines del ESP32 son solo de entrada?"
    python preguntar.py --metodo bm25 --ver-fragmentos "..."
"""
import argparse
import sys

from rag import config
from rag.asistente import responder
from rag.busqueda import Indice


def mostrar(indice, pregunta, metodo, ver, respaldos):
    r = responder(pregunta, indice, metodo=metodo, respaldos=respaldos)
    print("\n" + r.texto + "\n")
    if r.modelo_respaldo:
        print(f"(Respondió el modelo de respaldo {r.llm.modelo}; el principal, "
              f"{config.MODELO_LLM}, no estaba disponible.)\n")
    if ver:
        print("Fragmentos usados:")
        for f in r.fragmentos:
            print(f"  {f.rango}. {f.chunk.doc_id}, pág. {f.chunk.pagina}  ({f.puntaje:.3f})")
        print()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("pregunta", nargs="?")
    p.add_argument("--metodo", choices=config.METODOS_BUSQUEDA, default=config.METODO_DEFECTO)
    p.add_argument("--modo", choices=config.MODOS_EXTRACCION, default=config.MODO_DEFECTO)
    p.add_argument("--tamano", type=int, default=config.TAMANO_CHUNK)
    p.add_argument("--ver-fragmentos", action="store_true")
    p.add_argument("--sin-respaldo", action="store_true",
                   help="Usar solo el modelo principal, sin modelos de respaldo")
    a = p.parse_args()

    respaldos = () if a.sin_respaldo else config.MODELOS_RESPALDO
    print("Cargando índice...")
    indice = Indice(a.modo, a.tamano).construir()
    if a.pregunta:
        mostrar(indice, a.pregunta, a.metodo, a.ver_fragmentos, respaldos)
        return 0
    print("Escribe tu pregunta (Enter vacío para salir).")
    while True:
        try:
            pregunta = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not pregunta:
            break
        mostrar(indice, pregunta, a.metodo, a.ver_fragmentos, respaldos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
