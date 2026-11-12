"""
core/market_extras.py

Datos de mercado complementarios (v10.0):

  F3  Variacion del dia por activo      -> obtener_variacion_diaria
  C3  Perfil de cada activo (sector,    -> obtener_perfiles
      pais, tipo) para la exposicion

Reusa la sesion, timeouts y el circuit breaker de rate limit de
core/market_data.py (un rate limit detectado en cualquier modulo pausa a
todos). Agnostico de Streamlit.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from core.market_data import (
    HTTP_TIMEOUT,
    con_reintento_rate_limit,
    en_cooldown_rate_limit,
    get_yf_session,
)

from core.rutas import CACHE_DIR  # noqa: E402
CACHE_PERFILES = CACHE_DIR / "perfil_activos.json"
TTL_PERFIL_SEG = 30 * 24 * 3600  # sector/pais casi no cambian: 30 dias

# Simbolo de yfinance del SUBYACENTE (mercado de origen) cuando no es igual
# al ticker del CEDEAR. Solo afecta sector/pais (no precios).
SUBYACENTE_ESPECIAL = {"BRKB": "BRK-B", "BRKA": "BRK-A"}


# ===========================================================================
# F3 -- Variacion del dia
# ===========================================================================
def simbolos_para_variacion(tickers: List[str], config: dict) -> Dict[str, str]:
    """ticker interno -> simbolo yfinance con cotizacion diaria. CEDEARs y
    acciones locales en BYMA (.BA, en ARS)."""
    activos = config.get("activos", {})
    out: Dict[str, str] = {}
    for t in tickers:
        if not t or t == "CASH":
            continue
        datos = activos.get(t, {})
        if datos.get("ticker_yfinance"):
            out[t] = datos["ticker_yfinance"]
        else:
            out[t] = f"{t}.BA"
    return out


def obtener_variacion_diaria(simbolos: Dict[str, str]) -> pd.DataFrame:
    """
    Para cada ticker: ultimo precio, cierre anterior y variacion % de la
    ultima rueda (si el mercado esta abierto, la barra de hoy de yfinance
    ya trae el precio en vivo). Columnas: Ticker, Ultimo, Anterior,
    Var %, Fecha. Tickers sin datos no aparecen.
    """
    if not simbolos or en_cooldown_rate_limit():
        return pd.DataFrame(columns=["Ticker", "Ultimo", "Anterior", "Var %", "Fecha"])
    lista = sorted(set(simbolos.values()))
    try:
        data = yf.download(
            lista,
            period="10d",
            interval="1d",
            progress=False,
            group_by="ticker",
            threads=True,
            auto_adjust=False,
            timeout=HTTP_TIMEOUT,
            session=get_yf_session(),
        )
    except Exception as e:
        print(f"[market_extras] No se pudo descargar la variacion diaria: {e}")
        return pd.DataFrame(columns=["Ticker", "Ultimo", "Anterior", "Var %", "Fecha"])

    filas = []
    for ticker, simbolo in simbolos.items():
        try:
            sub = data[simbolo] if len(lista) > 1 else data
            cierre = sub["Close"].dropna()
        except Exception:
            continue
        if len(cierre) < 2:
            continue
        ultimo, anterior = float(cierre.iloc[-1]), float(cierre.iloc[-2])
        if anterior <= 0:
            continue
        filas.append(
            {
                "Ticker": ticker,
                "Ultimo": ultimo,
                "Anterior": anterior,
                "Var %": (ultimo / anterior - 1) * 100,
                "Fecha": pd.Timestamp(cierre.index[-1]).tz_localize(None) if cierre.index.tz is not None else pd.Timestamp(cierre.index[-1]),
            }
        )
    return pd.DataFrame(filas, columns=["Ticker", "Ultimo", "Anterior", "Var %", "Fecha"])


# ===========================================================================
# C3 -- Perfil (sector / pais / tipo) con cache en disco
# ===========================================================================
def _leer_cache() -> Dict[str, dict]:
    try:
        return json.loads(CACHE_PERFILES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _guardar_cache(cache: Dict[str, dict]) -> None:
    try:
        CACHE_PERFILES.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PERFILES.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def _info_yf(simbolo: str) -> Optional[dict]:
    try:
        info = con_reintento_rate_limit(lambda: yf.Ticker(simbolo, session=get_yf_session()).info)
    except YFRateLimitError:
        return None
    except Exception:
        return None
    if not isinstance(info, dict) or not (info.get("quoteType") or info.get("sector")):
        return None
    return info


def _perfil_desde_info(info: dict) -> dict:
    tipo = info.get("quoteType") or ""
    if tipo == "ETF":
        categoria = info.get("category") or "Diversificado"
        return {"sector": f"ETF · {categoria}", "pais": info.get("country") or "EE.UU. (ETF)", "tipo": "ETF"}
    return {
        "sector": info.get("sector") or "Sin dato",
        "pais": info.get("country") or "Sin dato",
        "tipo": "Accion" if tipo == "EQUITY" else (tipo.title() or "Sin dato"),
    }


# v10.2: activos cuyo perfil no tiene sentido pedirle a Yahoo (un ETF de
# bitcoin no tiene sector ni pais): se resuelven fijos, sin red.
PERFILES_FIJOS = {
    "IBIT": {"sector": "Cripto (Bitcoin)", "pais": "Global", "tipo": "ETF"},
}


def obtener_perfiles(tickers: List[str], config: dict) -> Dict[str, dict]:
    """
    ticker -> {"sector", "pais", "tipo"}. CASH y PERFILES_FIJOS (ej. IBIT) se
    resuelven sin red. El resto consulta yfinance (primero el subyacente en EE.UU.; si
    no existe, el ticker local .BA) y guarda el resultado 30 dias en
    data/cache/perfil_activos.json, porque .info es lento y sensible a
    rate limit.
    """
    activos = config.get("activos", {})
    cache = _leer_cache()
    ahora = time.time()
    resultado: Dict[str, dict] = {}
    cambios = False
    for t in tickers:
        if t == "CASH":
            resultado[t] = {"sector": "Liquidez", "pais": "Argentina", "tipo": "Cash"}
            continue
        if t in PERFILES_FIJOS:
            resultado[t] = dict(PERFILES_FIJOS[t])
            continue
        en_cache = cache.get(t)
        if en_cache and ahora - en_cache.get("_ts", 0) < TTL_PERFIL_SEG:
            resultado[t] = {k: v for k, v in en_cache.items() if not k.startswith("_")}
            continue
        info = _info_yf(SUBYACENTE_ESPECIAL.get(t, t)) or _info_yf(f"{t}.BA")
        if info is None:
            if en_cache:  # vencido pero mejor que nada
                resultado[t] = {k: v for k, v in en_cache.items() if not k.startswith("_")}
            else:
                resultado[t] = {"sector": "Sin dato", "pais": "Sin dato", "tipo": "Sin dato"}
            continue
        perfil = _perfil_desde_info(info)
        resultado[t] = perfil
        cache[t] = {**perfil, "_ts": ahora}
        cambios = True
    if cambios:
        _guardar_cache(cache)
    return resultado


def exposicion_cambiaria(perfil: dict) -> str:
    """Moneda a la que esta expuesto el valor del activo (no la moneda en
    que cotiza): un CEDEAR cotiza en ARS pero sigue al dolar CCL."""
    if perfil.get("tipo") == "Cash":
        return "Pesos"
    if perfil.get("pais") == "Argentina":
        return "Pesos (acciones locales)"
    return "Dólar (CEDEARs y cripto)"


# Traduccion de los nombres que devuelve Yahoo Finance (en ingles).
_SECTORES_ES = {
    "Technology": "Tecnologia",
    "Communication Services": "Comunicaciones",
    "Consumer Cyclical": "Consumo discrecional",
    "Consumer Defensive": "Consumo basico",
    "Financial Services": "Financiero",
    "Healthcare": "Salud",
    "Industrials": "Industria",
    "Energy": "Energia",
    "Utilities": "Servicios publicos",
    "Basic Materials": "Materiales",
    "Real Estate": "Inmobiliario",
}
_PAISES_ES = {
    "United States": "Estados Unidos",
    "EE.UU. (ETF)": "Estados Unidos",
    "Argentina": "Argentina",
    "Uruguay": "Uruguay",
    "Brazil": "Brasil",
    "China": "China",
    "Netherlands": "Paises Bajos",
    "Taiwan": "Taiwan",
    "Canada": "Canada",
    "United Kingdom": "Reino Unido",
}


def traducir_sector(sector: Optional[str]) -> str:
    if not sector:
        return "Sin dato"
    return _SECTORES_ES.get(sector, sector)


def traducir_pais(pais: Optional[str]) -> str:
    if not pais:
        return "Sin dato"
    return _PAISES_ES.get(pais, pais)
