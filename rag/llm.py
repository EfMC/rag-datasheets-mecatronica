"""Cliente de Gemini con caché en disco y reintentos.

- Cada llamada se identifica por un hash de (modelo, instrucción de sistema,
  prompt, parámetros). Si ya existe en datos/cache_llm/, se devuelve sin gastar
  cuota; así un experimento interrumpido continúa donde quedó.
- Ante errores de cuota (429) o del servidor (5xx) se reintenta con espera
  exponencial. Si la cuota diaria se agota, se lanza CuotaAgotada.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
from dataclasses import dataclass

from . import config


class CuotaAgotada(RuntimeError):
    """La cuota de la API se agotó y los reintentos no bastaron."""


@dataclass
class RespuestaLLM:
    texto: str
    modelo: str
    tokens_entrada: int
    tokens_salida: int
    segundos: float
    desde_cache: bool


def _cargar_api_key() -> str:
    from dotenv import load_dotenv
    load_dotenv(config.RAIZ_CODIGO / ".env")
    clave = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    if not clave:
        raise RuntimeError("Falta GEMINI_API_KEY en Códigos/.env")
    return clave


_cliente = None
_candado_cliente = threading.Lock()


def _cliente_gemini():
    global _cliente
    with _candado_cliente:
        if _cliente is None:
            _cliente = _crear_cliente()
    return _cliente


def _crear_cliente():
    from google import genai
    from google.genai import types
    return genai.Client(api_key=_cargar_api_key(),
                        http_options=types.HttpOptions(timeout=config.TIMEOUT_LLM_MS))


def _clave_cache(modelo: str, sistema: str, prompt: str, temperatura: float, json_salida: bool) -> str:
    base = json.dumps([modelo, sistema, prompt, temperatura, json_salida], ensure_ascii=False)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def generar(prompt: str, sistema: str = "", modelo: str = config.MODELO_LLM,
            temperatura: float = 0.0, json_salida: bool = False,
            max_reintentos: int = config.MAX_REINTENTOS,
            espera_inicial: float = config.ESPERA_INICIAL_S) -> RespuestaLLM:
    """Llama al modelo (o devuelve la respuesta guardada en caché)."""
    clave = _clave_cache(modelo, sistema, prompt, temperatura, json_salida)
    ruta = config.DIR_CACHE_LLM / f"{clave}.json"
    if ruta.exists():
        d = json.loads(ruta.read_text(encoding="utf-8"))
        return RespuestaLLM(d["texto"], d["modelo"], d["tokens_entrada"], d["tokens_salida"],
                            d["segundos"], desde_cache=True)

    from google.genai import errors, types
    cfg = types.GenerateContentConfig(
        system_instruction=sistema or None,
        temperature=temperatura,
        max_output_tokens=config.MAX_TOKENS_SALIDA,
        response_mime_type="application/json" if json_salida else None,
    )

    espera = espera_inicial
    for intento in range(1, max_reintentos + 1):
        _respetar_ritmo(modelo)
        inicio = time.perf_counter()
        try:
            r = _cliente_gemini().models.generate_content(model=modelo, contents=prompt, config=cfg)
        except errors.APIError as exc:
            reintentable = exc.code == 429 or (exc.code or 0) >= 500
            if not reintentable or intento == max_reintentos:
                if exc.code == 429:
                    raise CuotaAgotada(f"Cuota agotada para {modelo}: {exc.message}") from exc
                raise
            print(f"    [{modelo}] error {exc.code}; reintento {intento} en {espera:.0f} s")
            time.sleep(espera + random.uniform(0, 2))
            espera = min(espera * 2, 120)
            continue
        except Exception as exc:  # timeouts y cortes de red
            if intento == max_reintentos:
                raise
            print(f"    [{modelo}] {type(exc).__name__}; reintento {intento} en {espera:.0f} s")
            time.sleep(espera)
            espera = min(espera * 2, 120)
            continue

        texto = r.text or ""
        uso = r.usage_metadata
        resp = RespuestaLLM(
            texto=texto.strip(), modelo=modelo,
            tokens_entrada=getattr(uso, "prompt_token_count", 0) or 0,
            tokens_salida=(getattr(uso, "candidates_token_count", 0) or 0)
                          + (getattr(uso, "thoughts_token_count", 0) or 0),
            segundos=round(time.perf_counter() - inicio, 2), desde_cache=False,
        )
        config.DIR_CACHE_LLM.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps({**resp.__dict__, "prompt": prompt, "sistema": sistema},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        return resp
    raise RuntimeError("No se obtuvo respuesta")  # no debería llegar aquí


_proxima_llamada: dict[str, float] = {}
_candado_ritmo = threading.Lock()


def _respetar_ritmo(modelo: str) -> None:
    """Espera lo necesario para no superar LLAMADAS_POR_MINUTO por modelo.

    Es seguro con varios hilos: cada llamada reserva su turno bajo un candado y
    luego espera fuera de él, así las llamadas quedan espaciadas aunque se
    ejecuten en paralelo."""
    intervalo = 60.0 / config.LLAMADAS_POR_MINUTO
    with _candado_ritmo:
        ahora = time.monotonic()
        turno = max(ahora, _proxima_llamada.get(modelo, 0.0))
        _proxima_llamada[modelo] = turno + intervalo
    if turno > ahora:
        time.sleep(turno - ahora)
