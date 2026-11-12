"""
core/exposicion.py -- Exposicion REAL de la cartera (v10.2)

1. Look-through de ETFs: tu exposicion a cada empresa sumando lo que
   tenes directo y lo que tenes adentro de tus ETFs (ej. MSFT suelta +
   la parte de MSFT dentro de SPY y QQQ).
2. Exposicion a bitcoin: suma de todo lo que se mueve con BTC (el ETF
   IBIT y acciones cuyo negocio depende de bitcoin, como MSTR).

LIMITE: yfinance publica solo las ~10 mayores posiciones de cada ETF
(en SPY/QQQ son ~35-55% del fondo), asi que la exposicion "via ETFs" a
empresas mas chicas queda subestimada. Para las grandes (las que mas
importan para detectar superposiciones) es buena aproximacion.
"""

from __future__ import annotations

import io
import contextlib
import json
import time
from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd
import yfinance as yf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
from core.rutas import CACHE_DIR  # noqa: E402

CACHE_PATH = CACHE_DIR / "etf_holdings.json"
TTL_SEG = 30 * 24 * 3600

# Clases de acciones / simbolos que son la MISMA empresa que un ticker interno
ALIAS_EMPRESA = {"GOOG": "GOOGL", "BRK-B": "BRKB", "BRK.B": "BRKB", "BRK-A": "BRKB"}

# Activos que se mueven con bitcoin: ticker -> descripcion
LIGADOS_BITCOIN: Dict[str, str] = {
    "IBIT": "ETF de bitcoin (sigue al precio 1 a 1)",
    "FBTC": "ETF de bitcoin",
    "GBTC": "ETF de bitcoin",
    "BITO": "ETF de futuros de bitcoin",
    "MSTR": "Strategy: compra bitcoin con deuda y acciones (exposicion apalancada)",
    "COIN": "Coinbase: exchange cripto (sus ingresos dependen del mercado cripto)",
    "MARA": "Minera de bitcoin",
    "RIOT": "Minera de bitcoin",
    "CLSK": "Minera de bitcoin",
    "HUT": "Minera de bitcoin",
    "BITF": "Minera de bitcoin",
}


def _leer_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def top_holdings_etfs(etfs: Iterable[str], cache_path: Path = CACHE_PATH) -> Dict[str, pd.Series]:
    """ETF -> Serie (simbolo -> peso en fraccion) con sus mayores
    posiciones segun yfinance. Cache de 30 dias. Un ETF sin datos (ej.
    IBIT, que tiene bitcoin y no acciones) simplemente no aparece."""
    from core.market_data import en_cooldown_rate_limit, get_yf_session

    cache = _leer_cache(cache_path)
    ahora = time.time()
    resultado: Dict[str, pd.Series] = {}
    cambios = False
    for etf in sorted(set(etfs)):
        en_cache = cache.get(etf)
        if en_cache and ahora - en_cache.get("_ts", 0) < TTL_SEG:
            if en_cache.get("holdings"):
                resultado[etf] = pd.Series(en_cache["holdings"], dtype=float)
            continue
        if en_cooldown_rate_limit():
            continue
        holdings: Dict[str, float] = {}
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                th = yf.Ticker(etf, session=get_yf_session()).funds_data.top_holdings
            if th is not None and not th.empty and "Holding Percent" in th.columns:
                holdings = {str(k): float(v) for k, v in th["Holding Percent"].items() if pd.notna(v)}
        except Exception:
            holdings = {}
        cache[etf] = {"_ts": ahora, "holdings": holdings}
        cambios = True
        if holdings:
            resultado[etf] = pd.Series(holdings, dtype=float)
    if cambios:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        except OSError as e:
            print(f"[exposicion] No se pudo guardar la cache de ETFs: {e}")
    return resultado


def exposicion_look_through(pesos: pd.Series, holdings_etf: Dict[str, pd.Series]) -> pd.DataFrame:
    """
    `pesos`: ticker -> % de tu cartera (directo). `holdings_etf`: ETF ->
    (simbolo -> fraccion del ETF). Devuelve una fila por EMPRESA (no por
    ETF) con: Directo %, Via ETFs %, Total %, Detalle (de donde sale).
    Los ETFs en si no aparecen como empresa.
    """
    directo = pesos.astype(float)
    via: Dict[str, float] = {}
    detalle: Dict[str, list] = {}
    for etf, comp in holdings_etf.items():
        peso_etf = float(directo.get(etf, 0.0))
        if peso_etf <= 0:
            continue
        for sym, w in comp.items():
            empresa = ALIAS_EMPRESA.get(sym, sym)
            aporte = peso_etf * float(w)
            via[empresa] = via.get(empresa, 0.0) + aporte
            detalle.setdefault(empresa, []).append((etf, aporte))
    empresas = (set(directo.index) | set(via)) - set(holdings_etf)
    filas = []
    for e in empresas:
        d, v = float(directo.get(e, 0.0)), via.get(e, 0.0)
        partes = ([f"directo {d:.1f}%"] if d > 0 else []) + [f"{etf} {a:.1f}%" for etf, a in detalle.get(e, [])]
        filas.append({"Empresa": e, "Directo %": d, "Via ETFs %": v, "Total %": d + v, "Detalle": " + ".join(partes)})
    df = pd.DataFrame(filas, columns=["Empresa", "Directo %", "Via ETFs %", "Total %", "Detalle"])
    return df.sort_values("Total %", ascending=False).reset_index(drop=True)


def exposicion_bitcoin(pesos: pd.Series, riesgo: Optional[pd.Series] = None) -> pd.DataFrame:
    """Activos ligados a bitcoin presentes en `pesos` (ticker -> %), con
    su descripcion y, si se pasa `riesgo` (ticker -> % de contribucion al
    riesgo), cuanto riesgo aportan."""
    filas = []
    for t, desc in LIGADOS_BITCOIN.items():
        p = float(pesos.get(t, 0.0))
        if p > 0:
            filas.append({"Ticker": t, "Que es": desc, "Peso %": p,
                          "Riesgo %": float(riesgo.get(t, float("nan"))) if riesgo is not None else float("nan")})
    return pd.DataFrame(filas, columns=["Ticker", "Que es", "Peso %", "Riesgo %"])
