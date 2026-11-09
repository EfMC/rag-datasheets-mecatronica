"""Agrega un documento a la base de conocimiento en un solo paso.

Qué hace:
  1. Copia el PDF a datasheets/<Familia>/ (acepta una ruta local o una URL).
  2. Verifica que tenga texto (los PDF escaneados o "impresos" como imagen no sirven).
  3. Propone qué páginas indexar con las mismas reglas del manifiesto original y te
     deja aceptar la propuesta o escribir otro rango.
  4. Agrega la fila al manifiesto.
  5. Extrae solo ese documento y actualiza el índice calculando solo los fragmentos
     nuevos.
  6. Opcionalmente hace commit y push del repositorio de conocimiento (--git).

Uso:
  python agregar_documento.py RUTA_O_URL --familia Sensores --nombre "Sensor de humedad DHT22"
  python agregar_documento.py https://.../dht22.pdf --familia Sensores --nombre "DHT22" --git
  python agregar_documento.py datos.pdf --familia PLC --nombre "..." --paginas 3-40 --si

Opciones útiles:
  --doc-id ID       identificador corto (por defecto, el nombre del archivo)
  --fabricante X    fabricante (aparece en el manifiesto)
  --paginas R       rango a indexar ("1,3-13"); si no se da, se propone uno
  --si              acepta la propuesta sin preguntar
  --git             hace commit y push de la base de conocimiento al terminar
"""
import argparse
import csv
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import pymupdf

from rag import config
from rag.extraccion import actualizar_extraccion
from rag.manifiesto import ErrorManifiesto, cargar_manifiesto, parsear_rango
from rag.sugerencia_paginas import (a_rangos, analizar_pdf, detectar_idioma,
                                    detectar_revision, resumen_exclusiones)


def error(mensaje: str) -> int:
    print(f"\n✗ {mensaje}", file=sys.stderr)
    return 1


def descargar(url: str) -> Path:
    print(f"Descargando {url} ...")
    destino = Path(tempfile.mkdtemp()) / (Path(url.split("?")[0]).name or "documento.pdf")
    if destino.suffix.lower() != ".pdf":
        destino = destino.with_suffix(".pdf")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(destino, "wb") as fh:
        shutil.copyfileobj(r, fh)
    if destino.read_bytes()[:4] != b"%PDF":
        raise ValueError("La URL no devolvió un PDF (quizás pide iniciar sesión o es una página web).")
    return destino


def slug(texto: str) -> str:
    texto = re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")
    return texto[:40] or "documento"


def leer_filas() -> tuple[list[str], list[dict]]:
    with open(config.RUTA_MANIFIESTO, encoding="utf-8-sig", newline="") as fh:
        lector = csv.DictReader(fh)
        return list(lector.fieldnames), list(lector)


def carpeta_familia(familia: str, filas: list[dict]) -> str:
    """Usa la misma carpeta que los demás documentos de la familia; si es nueva, la crea."""
    for f in filas:
        if f["familia"].lower() == familia.lower():
            return f["archivo"].split("/")[0]
    return re.sub(r"[^A-Za-z0-9]+", "", familia.title()) or "Otros"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("pdf", help="Ruta local o URL del PDF")
    p.add_argument("--familia", required=True, help="Familia (por ejemplo: Sensores, PLC, Transistores)")
    p.add_argument("--nombre", required=True, help="Nombre descriptivo del componente")
    p.add_argument("--doc-id", help="Identificador corto (por defecto, del nombre del archivo)")
    p.add_argument("--fabricante", default="", help="Fabricante")
    p.add_argument("--fuente", default="", help="Sitio de origen (por defecto, la URL o 'local')")
    p.add_argument("--idioma", choices=("es", "en"), help="Idioma (por defecto, se detecta)")
    p.add_argument("--paginas", help="Rango de páginas a indexar (por defecto, se propone)")
    p.add_argument("--notas", default="", help="Notas para el manifiesto")
    p.add_argument("--si", action="store_true", help="Acepta la propuesta de páginas sin preguntar")
    p.add_argument("--git", action="store_true", help="Commit y push de la base de conocimiento al terminar")
    a = p.parse_args()

    # 0. Estado actual del manifiesto
    if not config.RUTA_MANIFIESTO.exists():
        return error(f"No encuentro el manifiesto en {config.RUTA_MANIFIESTO}. "
                     "¿Está descargada la base de conocimiento?")
    try:
        cargar_manifiesto(solo_incluidos=False)
    except ErrorManifiesto as exc:
        return error(f"El manifiesto actual tiene errores; corrígelos antes de agregar:\n{exc}")
    campos, filas = leer_filas()

    # 1. Obtener el PDF
    es_url = a.pdf.startswith(("http://", "https://"))
    try:
        origen = descargar(a.pdf) if es_url else Path(a.pdf).expanduser().resolve()
    except Exception as exc:  # noqa: BLE001 - se informa al usuario
        return error(f"No se pudo descargar: {exc}")
    if not origen.exists():
        return error(f"No existe el archivo {origen}")

    doc_id = a.doc_id or slug(origen.stem)
    if any(f["doc_id"] == doc_id for f in filas):
        return error(f"Ya existe un documento con doc_id '{doc_id}'. Usa --doc-id para darle otro.")

    # 2. Verificar que tenga texto
    with pymupdf.open(origen) as pdf:
        total = len(pdf)
        palabras = sum(len(pg.get_text().split()) for pg in pdf)
    if palabras < 50:
        return error("El PDF no tiene texto seleccionable (es una imagen). Descarga la versión "
                     "oficial del fabricante; las páginas tipo alldatasheet suelen ser imágenes.")

    # 3. Proponer páginas
    decisiones = analizar_pdf(origen)
    if a.paginas:
        rango = a.paginas
    else:
        rango = a_rangos([d.pagina for d in decisiones if d.incluir])
        print(f"\n{origen.name}: {total} páginas, {palabras} palabras")
        print(f"Propuesta de páginas a indexar: {rango or '(ninguna)'}")
        for paginas, motivo in resumen_exclusiones(decisiones):
            print(f"  se excluyen {paginas:<12} {motivo}")
        if not a.si:
            resp = input("\nEnter para aceptar, o escribe otro rango (por ejemplo 1-12,20): ").strip()
            rango = resp or rango
    try:
        lista = parsear_rango(rango)
    except ErrorManifiesto as exc:
        return error(str(exc))
    if not lista or max(lista) > total:
        return error(f"Rango inválido '{rango}' para un documento de {total} páginas.")

    # 4. Copiar el PDF y agregar la fila al manifiesto
    carpeta = carpeta_familia(a.familia, filas)
    destino = config.DIR_DATASHEETS / carpeta / f"{doc_id}.pdf"
    if destino.exists() and destino.resolve() != origen:
        return error(f"Ya existe {destino}. Usa --doc-id para darle otro nombre.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.resolve() != origen:
        shutil.copy2(origen, destino)

    fila = {c: "" for c in campos}
    fila.update({
        "doc_id": doc_id, "nombre": a.nombre, "archivo": f"{carpeta}/{destino.name}",
        "familia": a.familia, "fabricante": a.fabricante,
        "fuente": a.fuente or (a.pdf if es_url else "local"),
        "idioma": a.idioma or detectar_idioma(destino), "revision": detectar_revision(destino),
        "paginas_totales": str(total), "paginas_indexar": a_rangos(lista),
        "n_paginas_indexar": str(len(lista)), "incluir": "si",
        "notas": a.notas or "Agregado con agregar_documento.py",
    })
    with open(config.RUTA_MANIFIESTO, "a", encoding="utf-8", newline="") as fh:
        csv.DictWriter(fh, fieldnames=campos).writerow(fila)
    try:
        documentos = cargar_manifiesto()
    except ErrorManifiesto as exc:
        return error(f"La fila nueva dejó el manifiesto inválido:\n{exc}")
    print(f"\n✓ Agregado al manifiesto: {doc_id} ({len(lista)} de {total} páginas, idioma {fila['idioma']})")

    # 5. Extraer y reindexar solo lo nuevo
    print("\nExtrayendo...")
    for modo in config.MODOS_EXTRACCION:
        actualizar_extraccion(modo, documentos)
    print("\nActualizando el índice...")
    from rag.busqueda import Indice  # import tardío: carga torch
    indice = Indice(config.MODO_DEFECTO, config.TAMANO_CHUNK).construir()
    nuevos = sum(c.doc_id == doc_id for c in indice.chunks)
    print(f"✓ Índice actualizado: {nuevos} fragmentos nuevos de {doc_id}, "
          f"{indice.calculados} embeddings calculados, {len(indice.chunks)} fragmentos en total")

    # 6. Guardar en git (opcional)
    if a.git:
        repo = config.DIR_CONOCIMIENTO
        if not (repo / ".git").exists():
            print(f"\n(No hice commit: {repo} no es un repositorio git.)")
        else:
            try:
                subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
                subprocess.run(["git", "-C", str(repo), "commit", "-m", f"Agrega {doc_id}: {a.nombre}"], check=True)
                subprocess.run(["git", "-C", str(repo), "push"], check=True)
                print("✓ Base de conocimiento guardada en GitHub")
            except subprocess.CalledProcessError as exc:
                print(f"\n⚠ Falló git ({exc}). Los cambios quedaron en disco; haz commit y push a mano.")
    else:
        print(f"\nPara guardarlo en GitHub: cd {config.DIR_CONOCIMIENTO} && git add -A && "
              f"git commit -m \"Agrega {doc_id}\" && git push   (o usa --git)")

    print(f"\nPruébalo: python preguntar.py --ver-fragmentos \"¿...{a.nombre}...?\"")
    print("Recuerda agregar 2 o 3 preguntas de este documento a evaluacion/preguntas.csv "
          "si vas a volver a evaluar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
