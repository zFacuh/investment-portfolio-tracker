"""
desktop/backend/riesgo.py

Datos de la pestana Riesgo. Misma logica que ui/tab_riesgo_real.py y la
seccion "Tu cartera objetivo" de app.py, devolviendo JSON. Todo el calculo
sale de core/ (performance, stress, exposicion, analytics, market_extras).

Se divide en partes independientes para que la pantalla muestre primero lo
rapido (cartera real, en memoria) y despues lo que descarga datos.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

import pandas as pd

from core.config_manager import get_target_by_ticker
from core.exposicion import exposicion_bitcoin, exposicion_look_through, top_holdings_etfs
from core.macro_data import ccl_diario
from core.market_extras import exposicion_cambiaria, traducir_pais, traducir_sector
from core.performance import (
    PerformanceError,
    concentracion,
    contribucion_al_riesgo,
    estadisticas_drawdown,
    exposicion_por,
    metricas_riesgo,
    resumen_rendimiento,
    serie_drawdown,
)
from core.stress import correr_escenarios


def _n(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _serie(s: pd.Series, escala: float = 1.0) -> Dict[str, list]:
    s = s.dropna()
    return {"fechas": [d.strftime("%Y-%m-%d") for d in s.index], "valores": [_n(x * escala) for x in s.values]}


def _f(d) -> Optional[str]:
    return d.strftime("%Y-%m-%d") if d is not None and not pd.isna(d) else None


def valores_actuales(holdings: pd.DataFrame) -> pd.Series:
    v = holdings.set_index("Ticker")["Valor ARS"].fillna(0.0)
    return v[v > 0]


# --------------------------------------------------------------------- C1 + C2
def cartera_real(curva, ccl_hist: Optional[pd.Series], rf_pct: Optional[float]) -> dict:
    usd = ccl_hist is not None
    factor = ccl_diario(ccl_hist, curva.valor_ars.index) if usd else None
    r = resumen_rendimiento(curva.valor_ars, curva.capital_invertido_ars, factor=factor, unidad="usd" if usd else "ars")
    rf = (4.0 if usd else 0.0) if rf_pct is None else rf_pct

    bench = None
    if curva.precios_diarios is not None and "SPY" in curva.precios_diarios.columns:
        bench = curva.precios_diarios["SPY"]
        if factor is not None:
            bench = bench / factor
    metricas = None
    try:
        m = metricas_riesgo(r.indice, bench, rf / 100)
        metricas = {
            "volatilidad": _n(m.volatilidad_anual),
            "sharpe": _n(m.sharpe),
            "sortino": _n(m.sortino),
            "beta": _n(m.beta),
            "correlacion": _n(m.correlacion),
            "retorno_anual": _n(m.retorno_anual),
            "ruedas": int(m.ruedas),
            "vol_1m": _serie(m.vol_movil_1m),
            "vol_3m": _serie(m.vol_movil_3m),
        }
    except PerformanceError as e:
        metricas = {"error": str(e)}

    est = estadisticas_drawdown(r.indice)
    return {
        "en_usd": usd,
        "rf": rf,
        "metricas": metricas,
        "drawdown": {
            "max": _n(est.max_drawdown),
            "fecha_pico": _f(est.fecha_pico),
            "fecha_valle": _f(est.fecha_valle),
            "fecha_recuperacion": _f(est.fecha_recuperacion),
            "dias_caida": int(est.dias_caida),
            "dias_recuperacion": est.dias_recuperacion,
            "actual": _n(est.drawdown_actual),
            "serie": _serie(serie_drawdown(r.indice)),
        },
    }


# --------------------------------------------------------------------- Stress
def stress(holdings: pd.DataFrame, config: dict, ccl: Optional[float]) -> dict:
    pesos_hoy = valores_actuales(holdings)
    if pesos_hoy.empty:
        return {"escenarios": [], "mensaje": "No hay posiciones valuadas."}
    res_hoy = correr_escenarios(pesos_hoy, config)
    res_obj = correr_escenarios(pd.Series(get_target_by_ticker(config)), config)
    if not res_hoy:
        return {"escenarios": [], "mensaje": "No hay historia descargada para los escenarios (revisá tu conexión; se guarda en data/cache/stress/)."}
    valor_usd = float(pesos_hoy.sum()) / ccl if ccl else None
    obj = {r.escenario: r for r in res_obj}
    escenarios = []
    for r in res_hoy:
        o = obj.get(r.escenario)
        det = r.detalle[r.detalle["Aporte pp"].abs() > 0.05]
        escenarios.append(
            {
                "nombre": r.escenario,
                "hoy": _n(r.retorno_cartera),
                "hoy_supuesto": r.peso_con_supuesto > 10,
                "objetivo": _n(o.retorno_cartera) if o else None,
                "objetivo_supuesto": bool(o and o.peso_con_supuesto > 10),
                "perdida_usd": _n(valor_usd * r.retorno_cartera) if valor_usd else None,
                "detalle": [
                    {"ticker": str(f["Ticker"]), "aporte": _n(f["Aporte pp"]), "retorno": _n(f["Retorno %"]), "peso": _n(f["Peso %"]), "fuente": str(f["Fuente"])}
                    for _, f in det.sort_values("Aporte pp").iterrows()
                ],
            }
        )
    return {"escenarios": escenarios, "valor_usd": valor_usd}


# --------------------------------------------------------------------- C3 + C4 + exposicion
def _top(serie: pd.Series, top: int = 7) -> list:
    s = serie.copy()
    if len(s) > top:
        s = pd.concat([s.iloc[:top], pd.Series({f"Otros ({len(s) - top})": s.iloc[top:].sum()})])
    return [{"nombre": str(k), "pct": _n(v)} for k, v in s.items()]


def composicion(holdings: pd.DataFrame, config: dict, curva, perfiles: Dict[str, dict]) -> dict:
    valores = valores_actuales(holdings)
    out: Dict[str, Any] = {}

    # Concentracion por activo / sector / pais / moneda
    try:
        conc = concentracion(valores)
        out["concentracion"] = {
            "top1_ticker": conc.top1_ticker,
            "top1": _n(conc.top1_pct),
            "top3": _n(conc.top3_pct),
            "top5": _n(conc.top5_pct),
            "n_efectivo": _n(conc.n_efectivo),
            "n": int(len(valores)),
            "sector": _top(exposicion_por(valores, {tk: traducir_sector(p.get("sector")) for tk, p in perfiles.items()})),
            "pais": _top(exposicion_por(valores, {tk: traducir_pais(p.get("pais")) for tk, p in perfiles.items()})),
            "moneda": _top(exposicion_por(valores, {tk: exposicion_cambiaria(p) for tk, p in perfiles.items()})),
        }
    except PerformanceError as e:
        out["concentracion"] = {"error": str(e)}

    # De donde viene el riesgo (precio propio o el del alias)
    precios = curva.precios_diarios if curva is not None and curva.precios_diarios is not None else pd.DataFrame()
    columnas = {}
    for tk in valores.index:
        if tk in precios.columns:
            columnas[tk] = precios[tk]
        else:
            alias = str(config.get("activos", {}).get(tk, {}).get("alias_ticker") or "").upper()
            if alias and alias in precios.columns:
                columnas[tk] = precios[alias]
    sin_datos = [tk for tk in valores.index if tk not in columnas and tk != "CASH"]
    riesgo_por_ticker = None
    try:
        rc = contribucion_al_riesgo(pd.DataFrame(columnas), valores.reindex(list(columnas)))
        riesgo_por_ticker = rc.set_index("Ticker")["Contribucion al riesgo %"]
        out["riesgo"] = {
            "filas": [
                {"ticker": str(f["Ticker"]), "peso": _n(f["Peso %"]), "riesgo": _n(f["Contribucion al riesgo %"]), "ratio": _n(f["Riesgo / peso"])}
                for _, f in rc.iterrows()
            ],
            "sin_datos": sin_datos,
            "excluidos": list(rc.attrs.get("excluidos_poca_historia") or []),
        }
    except PerformanceError as e:
        out["riesgo"] = {"error": str(e)}

    # Exposicion real: look-through de ETFs + bitcoin
    if valores.empty:
        out["exposicion"] = None
    else:
        pesos = valores / valores.sum() * 100
        etfs = ({tk for tk, p in perfiles.items() if str(p.get("tipo", "")).lower() == "etf"} | {"SPY", "QQQ"}) & set(pesos.index)
        lt = exposicion_look_through(pesos, top_holdings_etfs(etfs))
        lt = lt[lt["Total %"] >= 0.5].head(15)
        btc = exposicion_bitcoin(pesos, riesgo_por_ticker)
        out["exposicion"] = {
            "empresas": [
                {"empresa": str(f["Empresa"]), "directo": _n(f["Directo %"]), "via_etfs": _n(f["Via ETFs %"]), "total": _n(f["Total %"]), "detalle": str(f["Detalle"])}
                for _, f in lt.iterrows()
            ],
            "superpuestas": lt[(lt["Directo %"] > 0) & (lt["Via ETFs %"] > 0)]["Empresa"].astype(str).tolist(),
            "btc": None
            if btc.empty
            else {
                "capital": _n(btc["Peso %"].sum()),
                "riesgo": _n(btc["Riesgo %"].sum()) if btc["Riesgo %"].notna().any() else None,
                "filas": [{"ticker": str(f["Ticker"]), "peso": _n(f["Peso %"]), "que_es": str(f["Que es"])} for _, f in btc.iterrows()],
            },
        }
    return out


# --------------------------------------------------------------------- cartera objetivo
def objetivo(analitica) -> dict:
    m = analitica.matriz_correlacion
    vol = analitica.volatilidad_anualizada
    dd = analitica.max_drawdown.reindex(vol.index)
    return {
        "volatilidad": _n(analitica.volatilidad_portafolio),
        "max_drawdown": _n(analitica.max_drawdown_portafolio),
        "advertencias": list(analitica.advertencias),
        "sin_datos": list(analitica.tickers_sin_datos),
        "correlacion": {"tickers": [str(t) for t in m.columns], "valores": [[_n(v) for v in fila] for fila in m.values]},
        "por_activo": [{"ticker": str(t), "volatilidad": _n(vol[t]), "max_drawdown": _n(dd[t])} for t in vol.index],
    }
