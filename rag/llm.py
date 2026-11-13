"""Cliente de Gemini con caché en disco y reintentos.

- Cada llamada se identifica por un hash de (modelo, instrucción de sistema,
  prompt, parámetros). Si ya existe en datos/cache_llm/, se devuelve sin gastar
  cuota; así un experimento interrumpido continúa donde quedó.
- Ante errores de cuota (429) o del servidor (5xx) se reintenta con espera
  exponencial. Si la cuota diaria se agota, se lanza CuotaAgotada.
- La clave de la API sale de .env (uso local) o se pasa en cada llamada (app web,
  D25: cada usuario usa la suya). Hay un cliente y un límite de ritmo por clave, y la
  clave nunca se escribe en disco ni en los mensajes.
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


class ClaveInvalida(RuntimeError):
    """La API rechazó la clave (inválida, revocada o sin permiso)."""


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
        raise RuntimeError(f"Falta GEMINI_API_KEY en {config.RAIZ_CODIGO / '.env'} "
                           "(escribe ahí: GEMINI_API_KEY=tu_clave)")
    return clave


_clientes: dict[str, object] = {}
_candado_cliente = threading.Lock()


def _id_clave(clave: str) -> str:
    """Identificador no reversible de una clave (para indexar clientes y ritmo)."""
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()[:16]


def _cliente_gemini(clave: str):
    ident = _id_clave(clave)
    with _candado_cliente:
        if ident not in _clientes:
            if len(_clientes) >= 64:  # app web: no acumular clientes indefinidamente
                _clientes.clear()
            _clientes[ident] = _crear_cliente(clave)
        return _clientes[ident]


def _crear_cliente(clave: str):
    from google import genai
    from google.genai import types
    return genai.Client(api_key=clave,
                        http_options=types.HttpOptions(timeout=config.TIMEOUT_LLM_MS))


def _es_clave_invalida(exc) -> bool:
    msg = (getattr(exc, "message", "") or str(exc)).lower()
    return exc.code in (401, 403) or (exc.code == 400 and ("api key" in msg or "api_key" in msg))


def _sin_clave(texto: str, clave: str) -> str:
    return texto.replace(clave, "***") if clave else texto


def _clave_cache(modelo: str, sistema: str, prompt: str, temperatura: float, json_salida: bool) -> str:
    base = json.dumps([modelo, sistema, prompt, temperatura, json_salida], ensure_ascii=False)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def generar(prompt: str, sistema: str = "", modelo: str = config.MODELO_LLM,
            temperatura: float = 0.0, json_salida: bool = False,
            max_reintentos: int = config.MAX_REINTENTOS,
            espera_inicial: float = config.ESPERA_INICIAL_S,
            api_key: str | None = None) -> RespuestaLLM:
    """Llama al modelo (o devuelve la respuesta guardada en caché).

    `api_key=None` usa la clave de .env; la app web pasa la del usuario."""
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

    api_key = (api_key or "").strip() or _cargar_api_key()
    ritmo = f"{_id_clave(api_key)}:{modelo}"
    espera = espera_inicial
    for intento in range(1, max_reintentos + 1):
        _respetar_ritmo(ritmo)
        inicio = time.perf_counter()
        try:
            r = _cliente_gemini(api_key).models.generate_content(model=modelo, contents=prompt, config=cfg)
        except errors.APIError as exc:
            if _es_clave_invalida(exc):
                raise ClaveInvalida(_sin_clave(f"La API rechazó la clave ({exc.code}): {exc.message}",
                                               api_key)) from None
            reintentable = exc.code == 429 or (exc.code or 0) >= 500
            if not reintentable or intento == max_reintentos:
                if exc.code == 429:
                    raise CuotaAgotada(_sin_clave(f"Cuota agotada para {modelo}: {exc.message}",
                                                  api_key)) from None
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
    """Espera lo necesario para no superar LLAMADAS_POR_MINUTO por modelo (y por
    clave: `modelo` llega como "<id de la clave>:<modelo>").

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
