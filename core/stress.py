"""
core/stress.py -- Stress test con escenarios historicos (v10.2)

Responde "¿cuanto perderia mi cartera de HOY si se repitiera X?": aplica
el movimiento real (en USD) que tuvo cada activo en una crisis pasada a
tus pesos actuales.

  retorno_cartera = suma_i ( peso_i x retorno_i(escenario) )

Supuestos y limites (la UI los aclara):
  - Pesos fijos durante toda la caida (sin aportes ni rebalanceo en el
    medio). Es la foto de cuanto "duele" tu cartera actual, no una
    simulacion de lo que harias.
  - Precios del SUBYACENTE en EE.UU. (en USD, ajustados por dividendos),
    no del CEDEAR: en una crisis el CCL suele saltar, asi que medido en
    pesos la caida se veria distinta. En dolares es la comparacion limpia.
  - Activos sin historia en ese escenario (ej. PLTR no cotizaba en 2020,
    IBIT no existia en 2022 -> se usa BTC-USD, que si) reciben el
    retorno de un PROXY (QQQ por defecto), marcado como supuesto.
"""

from __future__ import annotations

import io
import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
import yfinance as yf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
from core.rutas import CACHE_DIR as _CACHE  # noqa: E402

CACHE_DIR = _CACHE / "stress"

# nombre -> (fecha de inicio, fecha de fin). Fechas de cierre del pico y del valle.
ESCENARIOS: Dict[str, tuple] = {
    "Bear market 2022 (año completo)": ("2021-12-31", "2022-12-30"),
    "Bear 2021-22 (pico a valle del Nasdaq)": ("2021-11-19", "2022-12-28"),
    "Crash COVID (feb-mar 2020)": ("2020-02-19", "2020-03-23"),
    "Crisis 2008 (pico a valle del S&P 500)": ("2007-10-09", "2009-03-09"),
}
HISTORIA_DESDE = "2007-01-01"
HISTORIA_HASTA = "2023-02-01"  # alcanza para todos los escenarios: la cache no necesita refrescarse
PROXY_DEFAULT = "QQQ"

# CEDEAR / accion local -> simbolo en EE.UU. cuando no es el mismo ticker.
# None = sin equivalente con historia (se usa el proxy).
SIMBOLO_US_ESPECIAL: Dict[str, Optional[str]] = {
    "BRKB": "BRK-B",
    "BRKA": "BRK-A",
    "IBIT": "BTC-USD",  # IBIT nacio en 2024: su historia "real" es la de bitcoin
    "YPFD": "YPF",
    "PAMP": "PAM",
    "GGAL": "GGAL",
    "SPCX": None,
    "CASH": None,
}


def simbolo_us(ticker: str, config: Optional[dict] = None) -> Optional[str]:
    """Simbolo en EE.UU. con historia larga para un ticker interno."""
    t = str(ticker).strip().upper()
    if t in SIMBOLO_US_ESPECIAL:
        return SIMBOLO_US_ESPECIAL[t]
    tyf = str(((config or {}).get("activos", {}).get(t, {}) or {}).get("ticker_yfinance") or "")
    if tyf.upper().endswith(".BA"):
        return tyf[:-3].upper()
    return t


def _ruta_cache(simbolo: str, cache_dir: Path) -> Path:
    return cache_dir / f"{simbolo.replace('/', '_')}.csv"


def cierres_historicos(simbolos: Iterable[str], cache_dir: Path = CACHE_DIR) -> pd.DataFrame:
    """
    Cierres diarios ajustados (USD) de HISTORIA_DESDE a HISTORIA_HASTA.
    Cada simbolo se guarda en su propio CSV en `cache_dir` y no se vuelve
    a pedir (esos precios ya no cambian). Un simbolo sin datos se guarda
    vacio SOLO si la descarga funciono para otros (si fallo todo, puede
    ser la red: se reintenta la proxima vez).
    """
    from core.market_data import HTTP_TIMEOUT, en_cooldown_rate_limit, get_yf_session

    simbolos = sorted({s for s in simbolos if s})
    cache_dir.mkdir(parents=True, exist_ok=True)
    series: Dict[str, pd.Series] = {}
    faltan = []
    for s in simbolos:
        ruta = _ruta_cache(s, cache_dir)
        if ruta.exists():
            df = pd.read_csv(ruta, index_col=0, parse_dates=True)
            if not df.empty:
                series[s] = df.iloc[:, 0]
        else:
            faltan.append(s)

    if faltan and not en_cooldown_rate_limit():
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                data = yf.download(faltan, start=HISTORIA_DESDE, end=HISTORIA_HASTA, progress=False,
                                   auto_adjust=True, group_by="ticker", threads=True,
                                   timeout=HTTP_TIMEOUT, session=get_yf_session())
        except Exception as e:
            print(f"[stress] No se pudo descargar historia para el stress test: {e}")
            data = None
        if data is not None and not data.empty:
            for s in faltan:
                try:
                    # Con group_by="ticker", yfinance devuelve columnas MultiIndex
                    # (simbolo, campo) incluso cuando se pide UN solo simbolo.
                    sub = data[s] if isinstance(data.columns, pd.MultiIndex) else data
                    serie = sub["Close"].dropna()
                    serie.index = pd.DatetimeIndex(serie.index).tz_localize(None)
                except Exception:
                    serie = pd.Series(dtype=float)
                serie.rename(s).to_frame().to_csv(_ruta_cache(s, cache_dir))
                if not serie.empty:
                    series[s] = serie
    return pd.DataFrame(series).sort_index() if series else pd.DataFrame()


def retornos_escenario(cierres: pd.DataFrame, inicio: str, fin: str, tolerancia_dias: int = 7) -> pd.Series:
    """Retorno de cada columna entre `inicio` y `fin` (ultimo cierre en o
    antes de cada fecha). NaN si el activo no cotizaba al inicio o no
    tiene datos cerca del fin."""
    ini, fn = pd.Timestamp(inicio), pd.Timestamp(fin)
    out = {}
    for col in cierres.columns:
        s = cierres[col].dropna()
        a, b = s[:ini], s[:fn]
        ok = (not a.empty and not b.empty and (ini - a.index[-1]).days <= tolerancia_dias
              and (fn - b.index[-1]).days <= tolerancia_dias and s.index[0] <= ini + pd.Timedelta(days=tolerancia_dias))
        out[col] = float(b.iloc[-1] / a.iloc[-1] - 1) if ok else float("nan")
    return pd.Series(out, dtype=float)


@dataclass
class ResultadoStress:
    escenario: str
    retorno_cartera: float  # fraccion (ej. -0.33)
    peso_con_supuesto: float  # % del peso que uso el proxy
    detalle: pd.DataFrame = field(repr=False)  # Ticker, Peso %, Retorno %, Aporte pp, Fuente


def stress_test(pesos: pd.Series, retornos: pd.Series, retorno_proxy: float, escenario: str = "",
                proxy: str = PROXY_DEFAULT) -> ResultadoStress:
    """
    `pesos`: ticker -> peso (cualquier escala, se normaliza). `retornos`:
    ticker -> retorno del escenario (NaN = sin historia). "CASH" y
    "Efectivo" rinden 0. Lo que no tiene retorno usa `retorno_proxy`.
    """
    w = pesos[pesos > 0].astype(float)
    w = w / w.sum()
    filas = []
    for t, peso in w.items():
        if t in ("CASH", "Efectivo"):
            r, fuente = 0.0, "efectivo"
        elif pd.notna(retornos.get(t, float("nan"))):
            r, fuente = float(retornos[t]), "historico"
        else:
            r, fuente = float(retorno_proxy), f"supuesto: {proxy}"
        filas.append({"Ticker": t, "Peso %": peso * 100, "Retorno %": r * 100, "Aporte pp": peso * r * 100,
                      "Fuente": fuente})
    det = pd.DataFrame(filas).sort_values("Aporte pp").reset_index(drop=True)
    return ResultadoStress(
        escenario=escenario,
        retorno_cartera=float(det["Aporte pp"].sum() / 100),
        peso_con_supuesto=float(det.loc[det["Fuente"].str.startswith("supuesto"), "Peso %"].sum()),
        detalle=det,
    )


def correr_escenarios(pesos: pd.Series, config: Optional[dict] = None, cierres: Optional[pd.DataFrame] = None,
                      escenarios: Optional[Dict[str, tuple]] = None, proxy: str = PROXY_DEFAULT) -> List[ResultadoStress]:
    """Corre todos los escenarios para `pesos` (ticker -> peso)."""
    escenarios = escenarios or ESCENARIOS
    mapa = {t: simbolo_us(t, config) for t in pesos.index}
    if cierres is None:
        cierres = cierres_historicos(list(mapa.values()) + [proxy])
    resultados = []
    for nombre, (ini, fin) in escenarios.items():
        r_sym = retornos_escenario(cierres, ini, fin) if not cierres.empty else pd.Series(dtype=float)
        r_tk = pd.Series({t: r_sym.get(s, float("nan")) if s else float("nan") for t, s in mapa.items()}, dtype=float)
        r_proxy = r_sym.get(proxy, float("nan"))
        if pd.isna(r_proxy):
            continue  # sin el proxy no hay escenario confiable
        resultados.append(stress_test(pesos, r_tk, r_proxy, nombre, proxy))
    return resultados
