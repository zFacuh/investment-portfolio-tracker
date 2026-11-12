"""
desktop/backend/rendimiento.py

Datos de la pestana Rendimiento. Misma logica que ui/tab_rendimiento.py
(Streamlit), pero devolviendo JSON en vez de dibujar: todos los calculos
salen de core/performance.py y core/macro_data.py.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import pandas as pd

from core.macro_data import ccl_diario, indice_ipc_diario
from core.performance import (
    CATEGORIA_OTROS,
    PerformanceError,
    ResumenRendimiento,
    comparacion_vs_benchmark,
    contribucion_por_activo,
    factor_real,
    rendimiento_por_categoria,
    rendimientos_mensuales,
    resumen_rendimiento,
    tir_cuenta,
)

# Mismos nombres que ui/componentes.py
UNIDADES = {"usd": "Dolares (CCL)", "ars": "Pesos", "real": "Pesos reales"}
ORDEN_UNIDADES = ["usd", "ars", "real"]
NOTA_UNIDAD = {
    "usd": "Cada peso convertido al dólar CCL del día en que se movió.",
    "ars": "Pesos corrientes, sin ajustar por inflación ni por dólar.",
    "real": "Pesos ajustados por inflación (IPC), expresados en pesos de hoy.",
}


def _n(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _serie(s: pd.Series, escala: float = 1.0) -> Dict[str, list]:
    return {"fechas": [d.strftime("%Y-%m-%d") for d in s.index], "valores": [_n(x * escala) for x in s.values]}


def factores(ccl_hist: Optional[pd.Series], ipc: Optional[pd.Series], indice: pd.DatetimeIndex) -> Dict[str, Optional[pd.Series]]:
    """Factor diario por el que se divide cada peso para llevarlo a la unidad."""
    out: Dict[str, Optional[pd.Series]] = {"ars": None}
    if ccl_hist is not None:
        out["usd"] = ccl_diario(ccl_hist, indice)
    if ipc is not None:
        idx_ipc, _ = indice_ipc_diario(ipc, indice)
        out["real"] = factor_real(idx_ipc)
    return out


def resumenes(curva, fac: Dict[str, Optional[pd.Series]]) -> Dict[str, ResumenRendimiento]:
    out: Dict[str, ResumenRendimiento] = {}
    for u in ORDEN_UNIDADES:
        if u not in fac:
            continue
        try:
            out[u] = resumen_rendimiento(curva.valor_ars, curva.capital_invertido_ars, factor=fac[u], unidad=u)
        except PerformanceError:
            continue
    return out


def _resumen_json(u: str, r: ResumenRendimiento) -> dict:
    return {
        "unidad": u,
        "nombre": UNIDADES[u],
        "ganancia": _n(r.ganancia),
        "aportado": _n(r.aportado_neto),
        "ganancia_pct": _n(r.ganancia / r.aportado_neto) if r.aportado_neto else None,
        "twr_total": _n(r.twr_total),
        "twr_anual": _n(r.twr_anual),
        "tir_anual": _n(r.tir_anual),
        "extrapolacion": bool(r.anual_es_extrapolacion),
        "fecha_inicio": r.fecha_inicio.strftime("%Y-%m-%d"),
        "dias": int(r.dias),
    }


def indices_benchmark(curva, factor: Optional[pd.Series]) -> Dict[str, pd.Series]:
    """TWR de cada benchmark simulado con tus mismos flujos (incluye dividendos)."""
    out: Dict[str, pd.Series] = {}
    for label, serie in (curva.valores_benchmark or {}).items():
        try:
            out[label] = resumen_rendimiento(serie, curva.capital_invertido_ars, factor=factor).indice
        except PerformanceError:
            continue
    return out


def mapa_categorias(config: dict) -> Dict[str, str]:
    mapa = {tk: d.get("categoria") for tk, d in config.get("activos", {}).items() if d.get("categoria")}
    for tk, d in config.get("activos", {}).items():  # un alias hereda la categoria
        if d.get("alias_ticker"):
            mapa[str(d["alias_ticker"]).upper()] = d.get("categoria")
    return mapa


def armar(curva, config: dict, unidad: str, ccl_hist, ipc, avisos_macro: List[str]) -> dict:
    fac = factores(ccl_hist, ipc, curva.valor_ars.index)
    res = resumenes(curva, fac)
    if not res:
        raise PerformanceError("No se pudo calcular el rendimiento con los datos disponibles.")
    if unidad not in res:
        unidad = next(u for u in ORDEN_UNIDADES if u in res)
    r = res[unidad]
    f = fac.get(unidad)

    # --- acumulado base 100
    bench = indices_benchmark(curva, f)
    referencias: Dict[str, dict] = {}
    if unidad == "ars":
        if fac.get("real") is not None:
            ipc_d = 1 / fac["real"]
            referencias["Inflación (IPC)"] = _serie(100 * ipc_d / ipc_d.iloc[0])
        if fac.get("usd") is not None:
            ccl_d = fac["usd"]
            referencias["Dólar CCL"] = _serie(100 * ccl_d / ccl_d.iloc[0])

    # --- vs indice (QQQ y SPY primero, como en Streamlit)
    orden = sorted(bench, key=lambda l: (l not in ("QQQ", "SPY"), l != "QQQ", l))
    vs = []
    for label in orden:
        try:
            c = comparacion_vs_benchmark(r.indice, bench[label], label)
        except PerformanceError:
            continue
        vs.append(
            {
                "label": c.label,
                "exceso_6m": _n(c.exceso_6m),
                "exceso_12m": _n(c.exceso_12m),
                "exceso_total": _n(c.exceso_total),
                "pct_ventanas": _n(c.pct_ventanas_ganadas),
                "serie_6m": _serie(c.serie_exceso_6m.dropna(), 100) if c.label in ("QQQ", "SPY") else None,
            }
        )

    # --- mensual
    tabla = rendimientos_mensuales(r.indice)
    mensual = None
    if not tabla.empty:
        meses = [c for c in tabla.columns if c != "Anio"]
        mensual = {
            "anios": [int(a) for a in tabla.index],
            "meses": meses,
            "valores": [[_n(v) for v in fila] for fila in tabla[meses].values],
            "anual": [_n(v) for v in tabla["Anio"].values],
        }

    # --- categorias
    cats = rendimiento_por_categoria(curva.inventario, curva.precios_diarios, curva.capital_por_ticker, mapa_categorias(config), factor=f)
    categorias = []
    orden_cat = sorted(cats, key=lambda c: (c == CATEGORIA_OTROS, c))
    valores_hoy = {c: float(cats[c].valor.iloc[-1]) for c in orden_cat}
    total_hoy = sum(v for v in valores_hoy.values() if v > 0) or 1.0
    for cat in orden_cat:
        x = cats[cat]
        activo = x.valor[x.valor > 1.0]
        if activo.empty:
            continue
        desde = activo.index[0]
        idx = x.indice[desde:]
        base = 100 * idx / idx.iloc[0] * (1 + x.rendimientos.loc[desde])
        twr = float(idx.iloc[-1] / idx.iloc[0] * (1 + x.rendimientos.loc[desde]) - 1)
        dias = (x.fecha_fin - desde).days
        categorias.append(
            {
                "nombre": cat,
                "otros": cat == CATEGORIA_OTROS,
                "desde": desde.strftime("%Y-%m-%d"),
                "twr": _n(twr),
                "twr_anual": _n((1 + twr) ** (365.25 / dias) - 1) if dias >= 365 else None,
                "ganancia": _n(x.ganancia),
                "peso": _n(max(valores_hoy[cat], 0) / total_hoy * 100),
                "serie": _serie(base),
            }
        )

    return {
        "unidad": unidad,
        "unidades": [{"id": u, "nombre": UNIDADES[u]} for u in ORDEN_UNIDADES if u in res],
        "nota_unidad": NOTA_UNIDAD[unidad],
        "avisos": avisos_macro + list(curva.advertencias or []),
        "resumen": _resumen_json(unidad, r),
        "resumenes": [_resumen_json(u, res[u]) for u in ORDEN_UNIDADES if u in res],
        "acumulado": {
            "cartera": _serie(100 * r.indice),
            "benchmarks": {l: _serie(100 * s) for l, s in bench.items()},
            "referencias": referencias,
        },
        "vs_indice": vs,
        "mensual": mensual,
        "categorias": categorias,
    }


PERIODOS = {"inicio": "Desde el inicio", "anio": "Este año", "12m": "Últimos 12 meses", "3m": "Últimos 3 meses"}


def contribucion(curva, unidad: str, periodo: str, ccl_hist, ipc) -> dict:
    fac = factores(ccl_hist, ipc, curva.valor_ars.index)
    f = fac.get(unidad)
    hoy = curva.valor_ars.index[-1]
    desde = {
        "inicio": None,
        "anio": pd.Timestamp(year=hoy.year, month=1, day=1),
        "12m": hoy - pd.DateOffset(months=12),
        "3m": hoy - pd.DateOffset(months=3),
    }.get(periodo)
    df = contribucion_por_activo(curva.inventario, curva.precios_diarios, curva.capital_por_ticker, curva.cash_dividendos, desde=desde, factor=f)
    filas = []
    for _, x in df.iterrows():
        filas.append(
            {
                "ticker": str(x["Ticker"]),
                "valor_inicial": _n(x["Valor inicial"]),
                "flujo": _n(x["Flujo neto"]),
                "valor_final": _n(x["Valor final"]),
                "contribucion": _n(x["Contribucion"]),
                "estado": str(x["Estado"]),
                "pct_resultado": _n(x["% del resultado"]),
            }
        )
    return {"periodo": periodo, "unidad": unidad, "filas": filas, "total": _n(df["Contribucion"].sum()) if not df.empty else 0.0}


def tir_de_cuenta(movimientos: pd.DataFrame, holdings: pd.DataFrame, otros: float, ccl_hist, fac_res: Dict[str, ResumenRendimiento]) -> dict:
    """TIR de TODA la cuenta (depositos/retiros vs. valor total), vs. la TIR solo de acciones."""
    acciones = float(holdings.loc[holdings["Ticker"] != "CASH", "Valor ARS"].fillna(0).sum())
    rc = tir_cuenta(movimientos, acciones + otros, ccl=ccl_hist)
    usd = rc.tir_anual_usd is not None
    tir_c = rc.tir_anual_usd if usd else rc.tir_anual_ars
    r_acc = fac_res.get("usd" if usd else "ars")
    tir_a = r_acc.tir_anual if r_acc is not None else None
    return {
        "en_usd": usd,
        "tir_cuenta": _n(tir_c),
        "tir_acciones": _n(tir_a),
        "diferencia": _n(tir_c - tir_a) if tir_c is not None and tir_a is not None else None,
        "ganancia": _n(rc.ganancia_usd) if usd else _n(rc.valor_total_ars - rc.aportado_neto_ars),
        "acciones_ars": acciones,
        "otros_ars": otros,
        "flujos": int(len(rc.flujos)),
    }
