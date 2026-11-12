"""
desktop/backend/aportes.py

Datos de la pestana "Aportes y dividendos". Misma logica que ui/tab_aportes.py
(Streamlit), devolviendo JSON. Todo el calculo sale de core/performance.py.
"""

from __future__ import annotations

import math
from typing import Any, Optional

import pandas as pd

from core.macro_data import ccl_diario
from core.performance import (
    TIPO_RENTA,
    PerformanceError,
    analisis_timing,
    historial_aportes,
    historial_dividendos,
    operaciones_de_ticker,
    valores_en_fechas,
)


def _n(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def aportes(movimientos: pd.DataFrame, ccl_hist: Optional[pd.Series]) -> dict:
    h = historial_aportes(movimientos, ccl=ccl_hist)
    m = h.mensual
    tiene_usd = "Neto USD" in m.columns and ccl_hist is not None
    return {
        "en_usd": tiene_usd,
        "neto": _n(h.neto),
        "neto_usd": _n(h.neto_usd),
        "depositado": _n(h.total_depositado),
        "retirado": _n(h.total_retirado),
        "promedio_6m": _n(h.promedio_mensual_6m),
        "promedio_6m_usd": _n(h.promedio_mensual_6m_usd),
        "racha": int(h.racha_actual),
        "meses_con_aporte": int(h.meses_con_aporte),
        "meses_totales": int(h.meses_totales),
        "mensual": [
            {
                "mes": d.strftime("%Y-%m"),
                "depositos": _n(f.get("Depositos")),
                "retiros": _n(f.get("Retiros")),
                "neto": _n(f.get("Neto")),
                "neto_usd": _n(f.get("Neto USD")) if tiene_usd else None,
                "acumulado": _n(f.get("Acumulado")),
                "acumulado_usd": _n(f.get("Acumulado USD")) if tiene_usd else None,
            }
            for d, f in m.iterrows()
        ],
    }


def dividendos(movimientos: pd.DataFrame, ccl_hist: Optional[pd.Series], capital: Optional[float]) -> dict:
    if ccl_hist is None:
        return {"error": "Hace falta el dólar CCL histórico para valuar los dividendos en dólares."}
    d = historial_dividendos(movimientos, ccl_hist)
    especie = [
        {"ticker": str(r["Ticker"]), "nominales": _n(r["Nominales recibidos"])} for _, r in d.en_especie.iterrows()
    ] if not d.en_especie.empty else []
    return {
        "ultimos_12m_ars": _n(d.ultimos_12m_ars),
        "ultimos_12m_usd": _n(d.ultimos_12m_usd),
        "total_ars": _n(d.total_ars),
        "total_usd": _n(d.total_usd),
        "rendimiento": _n(d.ultimos_12m_ars / capital) if capital else None,
        "meses": [x.strftime("%Y-%m") for x in d.mensual_ars.index],
        "por_tipo": {str(t): [_n(v) for v in d.mensual_ars[t].values] for t in d.mensual_ars.columns},
        "tiene_renta": TIPO_RENTA in d.mensual_ars.columns,
        "en_especie": especie,
    }


def tickers_operados(movimientos: pd.DataFrame, curva) -> list:
    """Activos con operaciones y precio historico, los de mayor monto operado primero."""
    if curva is None or curva.precios_diarios is None:
        return []
    ops = movimientos[movimientos["tipo_operacion_norm"].isin(["COMPRA", "VENTA"])]
    monto = ops.groupby("ticker")["total"].apply(lambda s: s.abs().sum())
    return [str(tk) for tk in monto.sort_values(ascending=False).index if tk in curva.precios_diarios.columns]


def compras(movimientos: pd.DataFrame, curva, ccl_hist: Optional[pd.Series], ticker: str, unidad: str) -> dict:
    precios = curva.precios_diarios
    usd = unidad == "usd" and ccl_hist is not None
    ops = operaciones_de_ticker(movimientos, ticker)
    serie = precios[ticker].dropna()
    serie = serie[ops["Fecha"].min() - pd.Timedelta(days=20):]
    if usd:
        serie = serie / ccl_diario(ccl_hist, serie.index)
        ops = ops.copy()
        ops["Precio"] = ops["Precio"].values / valores_en_fechas(ccl_hist, ops["Fecha"])
    try:
        t = analisis_timing(precios[ticker], operaciones_de_ticker(movimientos, ticker), factor=ccl_hist if usd else None)
        timing = {
            "promedio_compra": _n(t.precio_promedio_compra),
            "promedio_periodo": _n(t.precio_promedio_periodo),
            "referencia_dca": _n(t.precio_referencia_dca),
            "ventaja_pct": _n(t.ventaja_pct),
            "bajo_precio_actual": _n(t.pct_compras_bajo_precio_actual),
            "precio_actual": _n(t.precio_actual),
            "n_compras": int(t.n_compras),
            "n_ventas": int(t.n_ventas),
        }
    except PerformanceError:
        timing = None
    return {
        "ticker": ticker,
        "unidad": "usd" if usd else "ars",
        "precio": {"fechas": [d.strftime("%Y-%m-%d") for d in serie.index], "valores": [_n(v) for v in serie.values]},
        "operaciones": [
            {"fecha": f["Fecha"].strftime("%Y-%m-%d"), "tipo": str(f["Tipo"]), "cantidad": _n(f["Cantidad"]), "precio": _n(f["Precio"])}
            for _, f in ops.iterrows()
        ],
        "timing": timing,
    }
