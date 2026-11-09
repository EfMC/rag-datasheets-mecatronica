"""Índices y búsqueda: BM25 (palabras clave), semántica (embeddings) e híbrida.

- Semántica: embeddings de un modelo multilingüe local, normalizados, con
  similitud coseno por fuerza bruta (producto punto con NumPy). Con unos pocos
  miles de chunks es exacta e instantánea, así que no hace falta una base de
  datos vectorial.
- BM25: sobre el mismo texto indexado, con un tokenizador que conserva nombres
  de parte (irlz44n, 6es7521-1bh00, 3.3).
- Híbrida: Reciprocal Rank Fusion (RRF) de ambas listas.

Los embeddings se guardan en disco (datos/indices/<nombre>/) y se reutilizan.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from . import config
from .chunking import Chunk, fragmentar

_TOKEN = re.compile(r"[a-z0-9áéíóúüñµωΩ°]+(?:[.\-/][a-z0-9]+)*")


def tokenizar(texto: str) -> list[str]:
    return _TOKEN.findall(texto.lower())


@lru_cache(maxsize=2)
def cargar_modelo(nombre: str):
    from sentence_transformers import SentenceTransformer  # import lento: solo si se usa
    return SentenceTransformer(nombre, device="cpu")


@lru_cache(maxsize=2)
def cargar_reranker(nombre: str):
    from sentence_transformers import CrossEncoder
    return CrossEncoder(nombre, device="cpu", max_length=512)


def _prefijos(modelo: str) -> tuple[str, str]:
    """Los modelos E5 se entrenaron con prefijos para consulta y pasaje."""
    return ("query: ", "passage: ") if "e5" in modelo.lower() else ("", "")


@dataclass
class Resultado:
    chunk: Chunk
    puntaje: float
    rango: int


class Indice:
    def __init__(self, modo: str, tamano: int, modelo: str = config.MODELO_EMBEDDINGS,
                 modelo_rerank: str = config.MODELO_RERANK,
                 contexto_tablas: bool = config.CONTEXTO_TABLAS):
        self.modo, self.tamano, self.modelo = modo, tamano, modelo
        # Las tablas en Markdown solo existen en modo "tablas"; en modo "simple" la
        # opción no aplica (y una línea que empiece con "|" no debe tratarse como tabla).
        self.contexto_tablas = contexto_tablas and modo == "tablas"
        self.modelo_rerank = modelo_rerank
        # Los modelos locales se usan de a una consulta a la vez (seguro con varios hilos).
        self._candado = threading.RLock()
        self.nombre = config.nombre_indice(modo, tamano, modelo, self.contexto_tablas or modo != "tablas")
        self.dir = config.DIR_INDICES / self.nombre
        self.chunks: list[Chunk] = []
        self.embeddings: np.ndarray | None = None
        self.bm25: BM25Okapi | None = None
        self.segundos_embeddings = 0.0
        self.calculados = 0

    # --- construcción y carga ---------------------------------------------------
    def construir(self, forzar: bool = False) -> "Indice":
        ruta_emb = self.dir / "embeddings.npy"
        ruta_chunks = self.dir / "chunks.jsonl"
        self.chunks = fragmentar(self.modo, self.tamano, self.contexto_tablas)

        # Incremental (D24): cada embedding se identifica por el texto exacto que se
        # codificó (encabezado + contenido). Solo se calculan los fragmentos nuevos o
        # modificados; los demás se reutilizan del índice guardado.
        previos = {} if forzar else self._embeddings_guardados(ruta_chunks, ruta_emb)
        claves = [c.texto_indexado for c in self.chunks]
        faltantes = [i for i, k in enumerate(claves) if k not in previos]
        mismo_orden = (not faltantes and ruta_chunks.exists()
                       and self._claves_guardadas(ruta_chunks) == claves)

        if mismo_orden:
            self.embeddings = np.load(ruta_emb)
            meta = json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
            self.segundos_embeddings = meta.get("segundos_embeddings", 0.0)
            self.calculados = 0
        else:
            self.dir.mkdir(parents=True, exist_ok=True)
            _, pref_pasaje = _prefijos(self.modelo)
            modelo = cargar_modelo(self.modelo)
            inicio = time.perf_counter()
            nuevos = {}
            if faltantes:
                vectores = modelo.encode(
                    [pref_pasaje + claves[i] for i in faltantes],
                    batch_size=32, normalize_embeddings=True,
                    show_progress_bar=len(faltantes) > 64, convert_to_numpy=True,
                ).astype(np.float32)
                nuevos = {claves[i]: v for i, v in zip(faltantes, vectores)}
            self.segundos_embeddings = time.perf_counter() - inicio
            self.calculados = len(faltantes)
            self.embeddings = np.vstack([nuevos.get(k, previos.get(k)) for k in claves]).astype(np.float32)
            np.save(ruta_emb, self.embeddings)
            with open(ruta_chunks, "w", encoding="utf-8") as fh:
                for c in self.chunks:
                    fh.write(json.dumps(c.a_dict(), ensure_ascii=False) + "\n")
            (self.dir / "meta.json").write_text(json.dumps({
                "modo": self.modo, "tamano": self.tamano, "modelo": self.modelo,
                "contexto_tablas": self.contexto_tablas, "n_chunks": len(self.chunks),
                "dimension": int(self.embeddings.shape[1]),
                "calculados_en_la_ultima_actualizacion": self.calculados,
                "segundos_embeddings": round(self.segundos_embeddings, 1),
                "truncados": self._contar_truncados(modelo),
            }, indent=2, ensure_ascii=False), encoding="utf-8")

        self.bm25 = BM25Okapi([tokenizar(c.texto_indexado) for c in self.chunks])
        return self

    @staticmethod
    def _claves_guardadas(ruta_chunks: Path) -> list[str]:
        with open(ruta_chunks, encoding="utf-8") as fh:
            return [Chunk(**json.loads(l)).texto_indexado for l in fh]

    def _embeddings_guardados(self, ruta_chunks: Path, ruta_emb: Path) -> dict[str, np.ndarray]:
        """{texto indexado: vector} del índice guardado (vacío si no hay o no coincide)."""
        if not (ruta_chunks.exists() and ruta_emb.exists()):
            return {}
        claves = self._claves_guardadas(ruta_chunks)
        matriz = np.load(ruta_emb)
        if len(claves) != len(matriz):
            return {}
        return dict(zip(claves, matriz))

    def _contar_truncados(self, modelo) -> int:
        """Chunks que superan la longitud máxima del modelo (se truncan al codificar)."""
        limite = modelo.max_seq_length
        tok = modelo.tokenizer
        _, pref = _prefijos(self.modelo)
        return sum(len(tok(pref + c.texto_indexado)["input_ids"]) > limite for c in self.chunks)

    # --- búsqueda -------------------------------------------------------------------
    def _rank_semantica(self, consulta: str) -> np.ndarray:
        pref_consulta, _ = _prefijos(self.modelo)
        q = cargar_modelo(self.modelo).encode(
            [pref_consulta + consulta], normalize_embeddings=True, convert_to_numpy=True)[0]
        return self.embeddings @ q

    def _rank_bm25(self, consulta: str) -> np.ndarray:
        return self.bm25.get_scores(tokenizar(consulta))

    def buscar(self, consulta: str, k: int = 5, metodo: str = "hibrida") -> list[Resultado]:
        with self._candado:
            return self._buscar(consulta, k, metodo)

    def _buscar(self, consulta: str, k: int, metodo: str) -> list[Resultado]:
        if metodo.endswith("_rerank"):
            return self._reordenar(consulta, metodo.removesuffix("_rerank"), k)
        if metodo == "semantica":
            puntajes = self._rank_semantica(consulta)
        elif metodo == "bm25":
            puntajes = self._rank_bm25(consulta)
        elif metodo == "hibrida":
            puntajes = self._rrf(consulta)
        else:
            raise ValueError(f"Método desconocido '{metodo}'. Opciones: {config.METODOS_BUSQUEDA}")
        orden = np.argsort(-puntajes)[:k]
        return [Resultado(self.chunks[i], float(puntajes[i]), r + 1) for r, i in enumerate(orden)]

    def _reordenar(self, consulta: str, base: str, k: int) -> list[Resultado]:
        """Toma CANDIDATOS_RERANK de la búsqueda base y los reordena con un cross-encoder,
        que lee cada par (pregunta, fragmento) completo."""
        candidatos = self._buscar(consulta, config.CANDIDATOS_RERANK, base)
        modelo = cargar_reranker(self.modelo_rerank)
        puntajes = modelo.predict([(consulta, r.chunk.texto_indexado) for r in candidatos],
                                  batch_size=16, show_progress_bar=False)
        orden = np.argsort(-np.asarray(puntajes))[:k]
        return [Resultado(candidatos[i].chunk, float(puntajes[i]), r + 1) for r, i in enumerate(orden)]

    def _rrf(self, consulta: str) -> np.ndarray:
        """Reciprocal Rank Fusion: suma 1/(k + rango) de cada lista."""
        total = np.zeros(len(self.chunks), dtype=np.float64)
        for puntajes in (self._rank_semantica(consulta), self._rank_bm25(consulta)):
            mejores = np.argsort(-puntajes)[:config.CANDIDATOS_HIBRIDA]
            for rango, i in enumerate(mejores, start=1):
                total[i] += 1.0 / (config.K_RRF + rango)
        return total
