"""
desktop/backend/metas_diario.py

Datos de las pestanas "Metas" y "Transicion y diario". Misma logica que
ui/tab_metas.py y ui/tab_decisiones.py (Streamlit), devolviendo JSON. Todo
el calculo sale de core/ (performance, rebalancer, stress, diario, metas).
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from core.config_manager import get_target_by_ticker
from core.diario import REFERENCIA, evaluar_diario
from core.macro_data import ccl_diario
from core.market_data import get_precio_generico
from core.metas import ESCENARIOS
from core.performance import PerformanceError, historial_aportes, metricas_riesgo, proyeccion_montecarlo, resumen_rendimiento
from core.rebalancer import calcular_transicion
from core.stress import correr_escenarios

CATEGORIA_FUERA = "Fuera de objetivo"


def _n(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def valor_total_usd(holdings: pd.DataFrame, ccl: Optional[float]) -> Optional[float]:
    total = float(holdings["Valor ARS"].sum(skipna=True))
    return total / ccl if ccl else None


# --------------------------------------------------------------------- Metas
def defaults_proyeccion(movimientos: pd.DataFrame, curva, ccl_hist: Optional[pd.Series]) -> dict:
    """Valores por defecto a partir de tus datos reales (igual que tab_metas)."""
    out: Dict[str, Optional[float]] = {"aporte_real": None, "vol_real": None, "vol_hist": None, "twr_real": None}
    if ccl_hist is None:
        return out
    try:
        out["aporte_real"] = _n(historial_aportes(movimientos, ccl=ccl_hist).promedio_mensual_6m_usd)
    except PerformanceError:
        pass
    if curva is not None:
        try:
            f = ccl_diario(ccl_hist, curva.valor_ars.index)
            r = resumen_rendimiento(curva.valor_ars, curva.capital_invertido_ars, factor=f, unidad="USD")
            out["vol_hist"] = _n(metricas_riesgo(r.indice).volatilidad_anual)
            out["twr_real"] = _n(r.twr_anual)
            # Por defecto la volatilidad de los ULTIMOS 12 meses (la de tu cartera actual).
            desde = r.indice.index[-1] - pd.DateOffset(months=12)
            try:
                out["vol_real"] = _n(metricas_riesgo(r.indice[r.indice.index >= desde]).volatilidad_anual)
            except PerformanceError:
                out["vol_real"] = out["vol_hist"]
        except PerformanceError:
            pass
    return out


def proyeccion(valor_usd: float, aporte: float, escenario: str, vol: float, anios: int, meta: Optional[float], fecha_objetivo: Optional[str]) -> dict:
    fecha = pd.Timestamp(fecha_objetivo) if fecha_objetivo else None
    p = proyeccion_montecarlo(valor_usd, aporte, ESCENARIOS[escenario], vol, anios, meta=meta, fecha_objetivo=fecha)
    pc = p.percentiles
    fechas = [d.strftime("%Y-%m-%d") for d in pc.index]
    return {
        "fechas": fechas,
        "p10": [_n(v) for v in pc["p10"]],
        "p25": [_n(v) for v in pc["p25"]],
        "p50": [_n(v) for v in pc["p50"]],
        "p75": [_n(v) for v in pc["p75"]],
        "p90": [_n(v) for v in pc["p90"]],
        "aportado": {"fechas": [d.strftime("%Y-%m-%d") for d in p.aportado.index], "valores": [_n(v) for v in p.aportado.values]},
        "final_p50": _n(pc["p50"].iloc[-1]),
        "final_p10": _n(pc["p10"].iloc[-1]),
        "final_p90": _n(pc["p90"].iloc[-1]),
        "aportado_extra": _n(p.aportado.iloc[-1] - valor_usd),
        "prob_meta": _n(p.prob_meta),
        "mes_meta": p.mes_meta_mediana.strftime("%Y-%m") if p.mes_meta_mediana is not None else None,
        "prob_meta_en_fecha": _n(p.prob_meta_en_fecha),
    }


# --------------------------------------------------------------------- Transicion
def _categoria_de(config: dict, ticker: str) -> str:
    if ticker == "Efectivo":
        return "Efectivo"
    if ticker == "CASH":
        return "Cash (dividendos)"
    return config.get("activos", {}).get(ticker, {}).get("categoria") or CATEGORIA_FUERA


def opciones_transicion(holdings: pd.DataFrame, config: dict) -> dict:
    objetivos = get_target_by_ticker(config)
    valuados = holdings[(holdings["Valor ARS"].fillna(0) > 0) & (holdings["Ticker"] != "CASH") & holdings["Precio ARS"].notna()]
    tickers = [str(t) for t in valuados["Ticker"]]
    return {"tickers": tickers, "fuera": [t for t in tickers if t not in objetivos]}


def transicion(holdings: pd.DataFrame, config: dict, ccl: Optional[float], vender: List[str], monto: float, sobre: bool) -> dict:
    r = calcular_transicion(holdings, config, vender=vender, monto_nuevo=float(monto), vender_sobreponderados=sobre, dolar_ccl=ccl)
    neto_ventas = float(r.ventas["Monto Neto ARS"].sum()) if not r.ventas.empty else 0.0
    compras = r.compras.ordenes if r.compras is not None else pd.DataFrame()
    if not compras.empty:
        compras = compras[compras["Nominales a Comprar"] > 0]

    cats: Dict[str, Dict[str, float]] = {}
    for col, serie in (("antes", r.pesos_antes), ("despues", r.pesos_despues), ("objetivo", r.pesos_objetivo)):
        for tk, v in serie.items():
            cats.setdefault(_categoria_de(config, tk), {"antes": 0.0, "despues": 0.0, "objetivo": 0.0})[col] += float(v)
    orden = sorted(cats, key=lambda c: -cats[c]["objetivo"] - cats[c]["antes"] / 1000)

    stress = None
    try:
        cols = {
            "hoy": correr_escenarios(r.pesos_antes, config),
            "despues": correr_escenarios(r.pesos_despues, config),
            "objetivo": correr_escenarios(r.pesos_objetivo, config),
        }
        nombres = [x.escenario for x in cols["hoy"]]
        stress = [
            {
                "nombre": n,
                **{k: _n(next((x.retorno_cartera for x in v if x.escenario == n), None)) for k, v in cols.items()},
            }
            for n in nombres
        ]
    except Exception as e:  # red caida, etc.: no tumbar el plan
        stress = {"error": f"No se pudo correr el stress test: {e}"}

    return {
        "ventas_neto": neto_ventas,
        "ventas_neto_usd": neto_ventas / ccl if ccl else None,
        "para_reinvertir": _n(r.efectivo_disponible),
        "comisiones": _n(r.comision_total),
        "comisiones_usd": _n(r.comision_total / ccl) if ccl else None,
        "vuelto": _n(r.vuelto),
        "ventas": [
            {
                "ticker": str(f["Ticker"]),
                "motivo": str(f["Motivo"]),
                "nominales": _n(f["Nominales a Vender"]),
                "precio": _n(f["Precio ARS"]),
                "neto": _n(f["Monto Neto ARS"]),
                "usd": _n(f["Equivalente USD"]),
            }
            for _, f in r.ventas.iterrows()
        ],
        "compras": [
            {
                "ticker": str(f.get("Ticker Ejecucion") or f["Ticker"]),
                "nominales": _n(f["Nominales a Comprar"]),
                "precio": _n(f["Precio Actual"]),
                "costo": _n(f["Costo Total Estimado ARS"]),
                "usd": _n(f["Equivalente USD"]),
            }
            for _, f in compras.iterrows()
        ],
        "categorias": [{"nombre": c, **{k: _n(v) for k, v in cats[c].items()}} for c in orden],
        "stress": stress,
        "advertencias": list(r.advertencias),
    }


# --------------------------------------------------------------------- Diario
def precios_hoy(holdings: pd.DataFrame, ccl: Optional[float], tickers: Iterable[str], cache: Dict[str, Optional[float]]) -> Dict[str, float]:
    """Precio ARS de hoy: de la tenencia si lo tenes, si no se cotiza suelto (cacheado)."""
    h = holdings.set_index("Ticker")["Precio ARS"]
    out: Dict[str, float] = {}
    for tk in {str(x).strip().upper() for x in tickers}:
        if tk in h.index and pd.notna(h[tk]) and float(h[tk]) > 0:
            out[tk] = float(h[tk])
            continue
        if tk not in cache:
            try:
                cache[tk] = float(get_precio_generico(tk, ccl).precio_ars)
            except Exception:
                cache[tk] = None
        if cache[tk]:
            out[tk] = cache[tk]
    return out


def diario(entradas: List[dict], precios: Dict[str, float], ccl: Optional[float]) -> dict:
    if not entradas:
        return {"entradas": [], "total": 0, "evaluables": 0, "aciertos": None, "revisar": 0}
    df = evaluar_diario(entradas, precios, precios.get(REFERENCIA), ccl or 0.0)
    evaluadas = df[df["Resultado"].isin(["Acierto", "Error"])]
    return {
        "referencia": REFERENCIA,
        "entradas": [
            {
                "id": str(f["id"]),
                "fecha": str(f["Fecha"]),
                "ticker": str(f["Ticker"]),
                "accion": str(f["Accion"]),
                "motivo": str(f["Motivo"]),
                "dias": int(f["Dias"]),
                "activo_usd": _n(f["Activo USD %"]),
                "ref_usd": _n(f[f"{REFERENCIA} USD %"]),
                "diferencia": _n(f["Diferencia pp"]),
                "resultado": str(f["Resultado"]),
                "revisar": bool(f["Revisar"]),
            }
            for _, f in df.iterrows()
        ],
        "total": int(len(df)),
        "evaluables": int(len(evaluadas)),
        "aciertos": _n((evaluadas["Resultado"] == "Acierto").mean() * 100) if len(evaluadas) else None,
        "revisar": int(df["Revisar"].sum()),
    }
