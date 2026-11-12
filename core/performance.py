"""
core/performance.py

Analitica de rendimiento, atribucion, riesgo de la cartera REAL, aportes,
dividendos y proyeccion (v10.0). Implementa las mejoras elegidas del plan:

  A1  TWR y TIR (XIRR)                    -> resumen_rendimiento, xirr
  A2  Rendimiento en USD y real (IPC)     -> resumen_rendimiento(factor=...)
  A4  Heatmap de rendimientos mensuales   -> rendimientos_mensuales
  B1  Contribucion por activo             -> contribucion_por_activo
  B2  Core vs. Satelite en el tiempo      -> rendimiento_por_categoria
  C1  Drawdown en el tiempo               -> serie_drawdown, estadisticas_drawdown
  C2  Sharpe, Sortino, beta, vol movil    -> metricas_riesgo
  C3  Concentracion                       -> concentracion, exposicion_por
  C4  Contribucion al riesgo              -> contribucion_al_riesgo
  D1  Historial de aportes                -> historial_aportes
  D3  Dividendos                          -> historial_dividendos
  D4  Compras sobre el grafico            -> operaciones_de_ticker, analisis_timing
  E2  Proyeccion (Monte Carlo)            -> proyeccion_montecarlo

Todo es funcional y agnostico de Streamlit (igual que el resto de core/):
recibe DataFrames/Series ya calculados (curva historica, movimientos,
tenencia, CCL, IPC) y devuelve DataFrames/dataclasses. Cacheo y graficos
viven en app.py / ui/.

=========================================================================
QUE UNIVERSO MIDE EL RENDIMIENTO (importante para leer los numeros)
=========================================================================
TWR, TIR, heatmap, contribucion, categorias, drawdown y ratios se calculan
sobre la curva historica de core/historical_curve.py: las acciones/CEDEARs
operadas en Cocos Capital que tienen precio historico en yfinance (el
"Universo Cerrado"), mas el cash de dividendos. NO incluye: cash sin
invertir, FCI, cauciones, bonos sin precio ni tenencias
manuales -- no hay forma de reconstruir su valor dia a dia desde el CSV.
La UI lo aclara.

=========================================================================
TWR vs. TIR -- por que se muestran las dos
=========================================================================
- Flujo del dia F_t = variacion del Capital Invertido (compras netas de
  ventas, con comisiones -- columna 'total' del CSV). Positivo = pusiste
  plata en la cartera.
- TWR (time-weighted return): encadena el rendimiento de cada dia
  neutralizando los aportes:  r_t = (V_t - V_{t-1} - F_t) / (V_{t-1} + F_t)
  (convencion "flujo al inicio del dia": lo que compras hoy ya participa
  del movimiento de hoy). Mide la calidad de las DECISIONES DE INVERSION,
  sin importar cuando o cuanto aportaste. Es el que se usa para comparar
  contra un indice.
- TIR / XIRR (money-weighted): la tasa anual que hace cero el valor
  presente de todos tus flujos (aportes negativos, valor final positivo).
  Mide lo que realmente gano TU PLATA, incluido el efecto del timing de
  los aportes (si aportaste mucho justo antes de una suba, la TIR queda
  por encima del TWR, y viceversa).
- El "P&L %" que ya mostraba el panel (valor / capital - 1) no es
  ninguno de los dos: no tiene en cuenta cuanto tiempo estuvo invertido
  cada peso, por eso con DCA puede enganar.

Moneda (A2): cualquier resumen se puede expresar en otra "unidad"
dividiendo valor y flujos de cada dia por un factor de ese dia:
  - USD:   factor = CCL del dia.
  - Real:  factor = IPC del dia / IPC de hoy (pesos de hoy).
Asi TWR y TIR en USD/reales salen de la MISMA formula, no de una
aproximacion (1+r)/(1+inflacion).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

DIAS_ANIO = 365.25
RUEDAS_ANIO = 252
BASE_MINIMA = 1.0  # $ -- por debajo de esto no hay cartera sobre la cual medir un rendimiento diario
MIN_RUEDAS_RIESGO = 20  # ruedas minimas de historia para que un activo entre a la contribucion al riesgo

MESES_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


class PerformanceError(Exception):
    """No hay datos suficientes para calcular una metrica."""


def valores_en_fechas(serie: pd.Series, fechas) -> np.ndarray:
    """Valor de `serie` vigente en cada fecha (ultimo dato en o antes de
    la fecha; si la fecha es anterior al primer dato, el primer dato).
    Tolera fechas repetidas (a diferencia de reindex)."""
    s = serie.dropna().sort_index()
    f = pd.DatetimeIndex(pd.to_datetime(fechas))
    pos = s.index.searchsorted(f, side="right") - 1
    pos = np.clip(pos, 0, len(s) - 1)
    return s.values[pos].astype(float)


# ===========================================================================
# A1 / A2 -- Flujos, TWR, XIRR
# ===========================================================================
def flujos_diarios(capital_acumulado: pd.Series) -> pd.Series:
    """Flujo diario a partir del capital acumulado. El primer dia toma
    el valor completo (todo lo aportado hasta ese dia entra ahi)."""
    if capital_acumulado.empty:
        return capital_acumulado.copy()
    flujos = capital_acumulado.diff()
    flujos.iloc[0] = capital_acumulado.iloc[0]
    return flujos.fillna(0.0)


def rendimientos_diarios_twr(valor: pd.Series, flujos: pd.Series) -> pd.Series:
    """r_t = (V_t - V_{t-1} - F_t) / (V_{t-1} + F_t). Dias sin cartera
    (base <= BASE_MINIMA, ej. antes de la primera compra o despues de
    venderlo todo) rinden 0 en vez de dividir por ~0."""
    previo = valor.shift(1).fillna(0.0)
    base = previo + flujos
    r = (valor - previo - flujos) / base
    r = r.where(base > BASE_MINIMA, 0.0)
    return r.replace([np.inf, -np.inf], 0.0).fillna(0.0)


def indice_desde_rendimientos(rendimientos: pd.Series) -> pd.Series:
    """Indice de riqueza (arranca en 1 + r del primer dia)."""
    return (1.0 + rendimientos).cumprod()


def anualizar(rendimiento_total: float, dias: int) -> Optional[float]:
    if dias <= 0 or rendimiento_total <= -1:
        return None
    return (1.0 + rendimiento_total) ** (DIAS_ANIO / dias) - 1.0


def xirr(fechas: pd.DatetimeIndex, montos: np.ndarray) -> Optional[float]:
    """
    TIR anual para flujos irregulares (convencion: negativo = sale de tu
    bolsillo, positivo = vuelve a vos). Biseccion sobre (-99.99%, +10000%)
    -- robusto (no diverge como Newton) y suficiente precision para una UI.
    Devuelve None si no hay cambio de signo (no existe TIR).
    """
    montos = np.asarray(montos, dtype=float)
    mask = np.abs(montos) > 1e-9
    if mask.sum() < 2:
        return None
    fechas = pd.DatetimeIndex(fechas)[mask]
    montos = montos[mask]
    if not (np.any(montos > 0) and np.any(montos < 0)):
        return None
    t = np.asarray((fechas - fechas[0]).days, dtype=float) / DIAS_ANIO

    def vpn(tasa: float) -> float:
        return float(np.sum(montos / np.power(1.0 + tasa, t)))

    lo, hi = -0.9999, 100.0
    f_lo, f_hi = vpn(lo), vpn(hi)
    if np.isnan(f_lo) or np.isnan(f_hi) or f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = vpn(mid)
        if abs(f_mid) < 1e-7 or (hi - lo) < 1e-10:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


@dataclass
class ResumenRendimiento:
    unidad: str  # "ARS", "USD", "ARS reales"
    fecha_inicio: pd.Timestamp
    fecha_fin: pd.Timestamp
    dias: int
    valor_final: float
    aportado_neto: float  # suma de flujos (en la unidad)
    ganancia: float  # valor_final - aportado_neto
    twr_total: float
    twr_anual: Optional[float]
    tir_anual: Optional[float]
    anual_es_extrapolacion: bool  # True si el periodo es < 1 anio
    rendimientos: pd.Series = field(repr=False)  # diarios (TWR)
    indice: pd.Series = field(repr=False)  # indice de riqueza TWR
    valor: pd.Series = field(repr=False)  # valor diario en la unidad
    flujos: pd.Series = field(repr=False)  # flujos diarios en la unidad


def resumen_rendimiento(
    valor_ars: pd.Series,
    capital_ars: pd.Series,
    factor: Optional[pd.Series] = None,
    unidad: str = "ARS",
) -> ResumenRendimiento:
    """TWR + TIR + ganancia. `factor` (mismo indice) convierte cada dia a
    otra unidad dividiendo: CCL -> USD; IPC_t/IPC_hoy -> pesos reales."""
    if valor_ars.empty:
        raise PerformanceError("La curva historica esta vacia.")
    flujos_ars = flujos_diarios(capital_ars)
    if factor is not None:
        factor = factor.reindex(valor_ars.index).ffill().bfill()
        if factor.isna().any() or (factor <= 0).any():
            raise PerformanceError(f"Faltan datos para convertir a {unidad}.")
        valor = valor_ars / factor
        flujos = flujos_ars / factor
    else:
        valor, flujos = valor_ars.astype(float), flujos_ars.astype(float)

    r = rendimientos_diarios_twr(valor, flujos)
    indice = indice_desde_rendimientos(r)
    dias = int((valor.index[-1] - valor.index[0]).days)
    twr_total = float(indice.iloc[-1] - 1.0)

    montos = -flujos.values.copy()
    montos[-1] += float(valor.iloc[-1])
    tir = xirr(valor.index, montos)

    aportado = float(flujos.sum())
    return ResumenRendimiento(
        unidad=unidad,
        fecha_inicio=valor.index[0],
        fecha_fin=valor.index[-1],
        dias=dias,
        valor_final=float(valor.iloc[-1]),
        aportado_neto=aportado,
        ganancia=float(valor.iloc[-1]) - aportado,
        twr_total=twr_total,
        twr_anual=anualizar(twr_total, dias),
        tir_anual=tir,
        anual_es_extrapolacion=dias < 365,
        rendimientos=r,
        indice=indice,
        valor=valor,
        flujos=flujos,
    )


def factor_real(indice_ipc: pd.Series) -> pd.Series:
    """Factor para expresar pesos de cada dia en pesos de HOY."""
    return indice_ipc / indice_ipc.iloc[-1]


# ===========================================================================
# v10.2 -- ¿Le ganas al indice? (comparacion movil contra un benchmark)
# ===========================================================================
@dataclass
class ComparacionBenchmark:
    label: str
    exceso_total: float  # rendimiento cartera - benchmark, todo el periodo (fraccion)
    exceso_6m: Optional[float]  # ultimos ~6 meses (None si no hay historia)
    exceso_12m: Optional[float]  # ultimos ~12 meses
    pct_ventanas_ganadas: Optional[float]  # % de ventanas moviles de 6 meses en que la cartera rindio mas
    serie_exceso_6m: pd.Series = field(repr=False)  # exceso movil de 6 meses, dia a dia


def _retorno_movil(indice: pd.Series, dias: int) -> pd.Series:
    """Rendimiento de los ultimos `dias` dias calendario, para cada fecha
    que tenga esa historia detras."""
    s = indice.dropna()
    if s.empty or (s.index[-1] - s.index[0]).days < dias:
        return pd.Series(dtype=float)
    fechas = s.index[s.index >= s.index[0] + pd.Timedelta(days=dias)]
    previo = valores_en_fechas(s, fechas - pd.Timedelta(days=dias))
    return pd.Series(s.reindex(fechas).values / previo - 1.0, index=fechas)


def comparacion_vs_benchmark(
    indice_cartera: pd.Series, indice_benchmark: pd.Series, label: str, dias_corto: int = 182, dias_largo: int = 365
) -> ComparacionBenchmark:
    """
    Compara dos indices TWR (cartera y benchmark con tus mismos flujos):
    exceso de rendimiento en las ultimas ventanas de ~6 y ~12 meses, en
    todo el periodo, y en que % de las ventanas moviles de 6 meses la
    cartera le gano. Un solo numero "desde el inicio" puede depender de
    un unico evento; las ventanas moviles muestran si le ganas de forma
    CONSISTENTE.
    """
    c = indice_cartera.dropna()
    b = indice_benchmark.reindex(c.index).ffill().bfill()
    if c.empty or b.isna().all():
        raise PerformanceError(f"No hay datos para comparar contra {label}.")
    exc_total = float(c.iloc[-1] / c.iloc[0] - b.iloc[-1] / b.iloc[0])
    exc_6 = (_retorno_movil(c, dias_corto) - _retorno_movil(b, dias_corto)).dropna()
    exc_12 = (_retorno_movil(c, dias_largo) - _retorno_movil(b, dias_largo)).dropna()
    return ComparacionBenchmark(
        label=label,
        exceso_total=exc_total,
        exceso_6m=float(exc_6.iloc[-1]) if not exc_6.empty else None,
        exceso_12m=float(exc_12.iloc[-1]) if not exc_12.empty else None,
        pct_ventanas_ganadas=float((exc_6 > 0).mean() * 100) if not exc_6.empty else None,
        serie_exceso_6m=exc_6,
    )


# ===========================================================================
# v10.2 -- TIR de TODA la cuenta (depositos/retiros vs. valor total)
# ===========================================================================
TIPOS_EXTERNOS_USD = {"Orden De Pago Usd", "Recibo De Cobro Usd"}


def flujos_cuenta(movimientos: pd.DataFrame, ccl: Optional[pd.Series] = None) -> pd.DataFrame:
    """
    Plata que entro (+) o salio (-) de la cuenta DESDE AFUERA, en ARS:
    depositos y retiros en pesos ("Recibo De Cobro" / "Orden De Pago") y
    en dolares ("... Usd", convertidos al CCL de su dia). Las operaciones
    internas (compras, ventas, FCI, MEP, dividendos) no son flujos: son
    lo que la cuenta hizo con esa plata.
    """
    m = movimientos[movimientos["fechaEjecucion"].notna()].copy()
    m["monto"] = m["total"].fillna(m["montoBruto"]).astype(float)
    tipo = m["tipoOperacion"].fillna("").str.strip().str.title()
    moneda = m["moneda"].fillna("ARS").str.upper()
    externo = m["tipo_operacion_norm"].isin(["INGRESO_CASH", "EGRESO_CASH"]) | tipo.isin(TIPOS_EXTERNOS_USD)
    es_usd = externo & ((moneda == "USD") | tipo.isin(TIPOS_EXTERNOS_USD))
    filas = m[externo & ~es_usd][["fechaEjecucion", "monto"]].assign(moneda="ARS")
    usd = m[es_usd]
    if not usd.empty:
        if ccl is None:
            raise PerformanceError("Hay depositos o retiros en dolares y falta el CCL historico para convertirlos.")
        usd = usd.assign(monto=usd["monto"].values * valores_en_fechas(ccl, usd["fechaEjecucion"]), moneda="USD")
        filas = pd.concat([filas, usd[["fechaEjecucion", "monto", "moneda"]]])
    filas = filas.rename(columns={"fechaEjecucion": "fecha", "monto": "monto_ars"})
    filas = filas[filas["monto_ars"].abs() > 1e-9]
    return filas.sort_values("fecha").reset_index(drop=True)


@dataclass
class ResultadoTirCuenta:
    tir_anual_ars: Optional[float]
    tir_anual_usd: Optional[float]
    aportado_neto_ars: float
    aportado_neto_usd: Optional[float]
    valor_total_ars: float
    ganancia_usd: Optional[float]
    flujos: pd.DataFrame = field(repr=False)


def tir_cuenta(
    movimientos: pd.DataFrame,
    valor_total_ars: float,
    ccl: Optional[pd.Series] = None,
    fecha_valor: Optional[pd.Timestamp] = None,
) -> ResultadoTirCuenta:
    """TIR (XIRR) de toda la cuenta: tus depositos/retiros contra lo que
    vale HOY la cuenta completa (acciones + efectivo + FCI + lo que haya).
    Es la respuesta a "¿cuanto rindio la plata que mande a Cocos?",
    incluida la que estuvo quieta. En USD si hay CCL."""
    fl = flujos_cuenta(movimientos, ccl)
    if fl.empty:
        raise PerformanceError("El CSV no tiene depositos ni retiros.")
    fecha_valor = pd.Timestamp(fecha_valor or pd.Timestamp.today().normalize())
    fechas = pd.DatetimeIndex(list(fl["fecha"]) + [fecha_valor])
    montos = np.append(-fl["monto_ars"].values, float(valor_total_ars))
    tir_ars = xirr(fechas, montos)
    tir_usd = aportado_usd = ganancia_usd = None
    if ccl is not None:
        ccl_f = valores_en_fechas(ccl, fechas)
        montos_usd = montos / ccl_f
        tir_usd = xirr(fechas, montos_usd)
        aportado_usd = float(-montos_usd[:-1].sum())
        ganancia_usd = float(montos_usd[-1] - aportado_usd)
    return ResultadoTirCuenta(
        tir_anual_ars=tir_ars,
        tir_anual_usd=tir_usd,
        aportado_neto_ars=float(fl["monto_ars"].sum()),
        aportado_neto_usd=aportado_usd,
        valor_total_ars=float(valor_total_ars),
        ganancia_usd=ganancia_usd,
        flujos=fl,
    )


# ===========================================================================
# A4 -- Rendimientos mensuales
# ===========================================================================
def rendimientos_mensuales(indice: pd.Series) -> pd.DataFrame:
    """Tabla anio x mes (columnas 'Ene'..'Dic' + 'Anio') con el
    rendimiento TWR de cada mes en %. El primer mes (parcial) se mide
    desde el inicio de la serie. NaN = mes sin datos."""
    if indice.empty:
        return pd.DataFrame()
    # Cada mes se mide contra el cierre del mes anterior; el PRIMER mes, contra
    # la base 1.0 (valor antes del primer dia). Antes la base se fechaba el dia
    # previo al inicio y, si la serie arrancaba a mitad de mes, caia en el mismo
    # mes que el primer dato: resample() la pisaba y el primer mes desaparecia.
    cierre_mes = indice.resample("ME").last()
    previo = cierre_mes.shift(1)
    previo.iloc[0] = 1.0
    mensual = ((cierre_mes / previo - 1) * 100).dropna()
    tabla = pd.DataFrame({"anio": mensual.index.year, "mes": mensual.index.month, "r": mensual.values})
    pivot = tabla.pivot(index="anio", columns="mes", values="r").reindex(columns=range(1, 13))
    pivot.columns = MESES_ES
    anual = tabla.groupby("anio")["r"].apply(lambda x: (np.prod(1 + x / 100) - 1) * 100)
    pivot["Anio"] = anual
    pivot.index.name = None
    return pivot


# ===========================================================================
# B1 -- Contribucion por activo
# ===========================================================================
def _valor_por_ticker(inventario: pd.DataFrame, precios: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in inventario.columns if c in precios.columns]
    return (inventario[cols] * precios[cols]).fillna(0.0)


def contribucion_por_activo(
    inventario: pd.DataFrame,
    precios: pd.DataFrame,
    capital_por_ticker: pd.DataFrame,
    cash_dividendos: Optional[pd.Series] = None,
    desde: Optional[pd.Timestamp] = None,
    factor: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    Cuanto aporto cada activo al resultado de la cartera en el periodo
    [desde, hoy]:
        contribucion_i = (V_i,fin - V_i,ini) - (flujos netos del activo en el periodo)
    Si desde es None se mide desde el inicio (V_i,ini = 0 y todo el
    capital puesto cuenta como flujo). Con `factor` (CCL o IPC) cada
    flujo se convierte al tipo de cambio/indice DE SU DIA.

    Los dividendos en efectivo no traen ticker en el CSV de Cocos, asi
    que aparecen como una fila propia ("Dividendos").
    """
    valores = _valor_por_ticker(inventario, precios)
    capital = capital_por_ticker.reindex(columns=valores.columns, fill_value=0.0)
    idx = valores.index
    if factor is not None:
        factor = factor.reindex(idx).ffill().bfill()
    else:
        factor = pd.Series(1.0, index=idx)

    flujos = capital.diff()
    flujos.iloc[0] = capital.iloc[0]
    flujos_u = flujos.div(factor, axis=0)
    valores_u = valores.div(factor, axis=0)

    if desde is not None and desde > idx[0]:
        pos = idx.searchsorted(desde)
        ini_label = idx[pos - 1]  # cierre del dia anterior al periodo
        v_ini = valores_u.loc[ini_label]
        flujo_periodo = flujos_u.iloc[pos:].sum()
    else:
        v_ini = pd.Series(0.0, index=valores_u.columns)
        flujo_periodo = flujos_u.sum()
    v_fin = valores_u.iloc[-1]

    df = pd.DataFrame(
        {
            "Valor inicial": v_ini,
            "Flujo neto": flujo_periodo,
            "Valor final": v_fin,
        }
    )
    df["Contribucion"] = df["Valor final"] - df["Valor inicial"] - df["Flujo neto"]
    df["Estado"] = np.where(df["Valor final"].abs() > 1e-6, "En cartera", "Vendido")
    df = df[(df[["Valor inicial", "Flujo neto", "Valor final"]].abs().sum(axis=1)) > 1e-6]

    if cash_dividendos is not None and not cash_dividendos.empty:
        cd = cash_dividendos.reindex(idx).ffill().fillna(0.0)
        # dividendos: flujo que entra en la cartera por rendimiento -> se
        # convierte cada ingreso al factor de SU dia
        ingresos = cd.diff()
        ingresos.iloc[0] = cd.iloc[0]
        ingresos_u = ingresos / factor
        if desde is not None and desde > idx[0]:
            div = float(ingresos_u.iloc[idx.searchsorted(desde):].sum())
        else:
            div = float(ingresos_u.sum())
        if abs(div) > 1e-6:
            df.loc["Dividendos"] = [0.0, 0.0, div, div, "Cash"]

    total = df["Contribucion"].sum()
    df["% del resultado"] = (df["Contribucion"] / abs(total) * 100) if abs(total) > 1e-9 else np.nan
    df.index.name = "Ticker"
    return df.sort_values("Contribucion", ascending=False).reset_index()


# ===========================================================================
# B2 -- Rendimiento por categoria (Core / Satelite / otros)
# ===========================================================================
CATEGORIA_OTROS = "Fuera de objetivo"


def rendimiento_por_categoria(
    inventario: pd.DataFrame,
    precios: pd.DataFrame,
    capital_por_ticker: pd.DataFrame,
    mapa_categoria: Dict[str, str],
    factor: Optional[pd.Series] = None,
) -> Dict[str, ResumenRendimiento]:
    """TWR/TIR de cada categoria como si fuera una sub-cartera. Los
    tickers que no estan en la config van a CATEGORIA_OTROS. La
    categoria es la de HOY aplicada a todo el historial (la config no
    guarda historia) -- la UI lo aclara."""
    valores = _valor_por_ticker(inventario, precios)
    capital = capital_por_ticker.reindex(columns=valores.columns, fill_value=0.0)
    grupos: Dict[str, List[str]] = {}
    for t in valores.columns:
        grupos.setdefault(mapa_categoria.get(t, CATEGORIA_OTROS), []).append(t)
    resultado: Dict[str, ResumenRendimiento] = {}
    for cat, tickers in grupos.items():
        v = valores[tickers].sum(axis=1)
        c = capital[tickers].sum(axis=1)
        if v.abs().sum() < 1e-6:
            continue
        try:
            resultado[cat] = resumen_rendimiento(v, c, factor=factor, unidad=cat)
        except PerformanceError:
            continue
    return resultado


# ===========================================================================
# C1 -- Drawdown
# ===========================================================================
def serie_drawdown(indice: pd.Series) -> pd.Series:
    """Caida % desde el maximo previo del indice (<= 0).

    v10.1: el maximo arranca en 1.0 (el capital inicial, antes del primer
    dia): si la cartera ya cae el primer dia, eso tambien es drawdown."""
    pico = indice.cummax().clip(lower=1.0)
    return (indice / pico - 1.0) * 100


@dataclass
class EstadisticasDrawdown:
    max_drawdown: float  # % (<= 0)
    fecha_pico: pd.Timestamp
    fecha_valle: pd.Timestamp
    fecha_recuperacion: Optional[pd.Timestamp]  # None = todavia no recupero
    dias_caida: int
    dias_recuperacion: Optional[int]
    drawdown_actual: float


def estadisticas_drawdown(indice: pd.Series) -> EstadisticasDrawdown:
    dd = serie_drawdown(indice)
    fecha_valle = dd.idxmin()
    previo = indice[:fecha_valle]
    if float(previo.max()) >= 1.0:
        fecha_pico = previo.idxmax()
        pico = float(indice.loc[fecha_pico])
    else:
        # la caida arranca desde el capital inicial (base 1.0, ver serie_drawdown)
        fecha_pico = indice.index[0]
        pico = 1.0
    post = indice[fecha_valle:]
    recuperado = post[post >= pico]
    fecha_rec = recuperado.index[0] if not recuperado.empty and dd.min() < 0 else None
    return EstadisticasDrawdown(
        max_drawdown=float(dd.min()),
        fecha_pico=fecha_pico,
        fecha_valle=fecha_valle,
        fecha_recuperacion=fecha_rec,
        dias_caida=int((fecha_valle - fecha_pico).days),
        dias_recuperacion=int((fecha_rec - fecha_valle).days) if fecha_rec is not None else None,
        drawdown_actual=float(dd.iloc[-1]),
    )


# ===========================================================================
# C2 -- Metricas de riesgo/retorno
# ===========================================================================
def _solo_ruedas(serie: pd.Series) -> pd.Series:
    """Deja solo lunes a viernes: la curva es diaria calendario (fines de
    semana con precio repetido); incluirlos subestimaria la volatilidad."""
    return serie[serie.index.dayofweek < 5]


def _periodos_por_anio(fechas: pd.DatetimeIndex) -> float:
    """Observaciones por anio de una serie (para anualizar). Con menos de
    ~2 meses de historia la estimacion es inestable: se usa RUEDAS_ANIO."""
    dias = (fechas[-1] - fechas[0]).days if len(fechas) > 1 else 0
    if dias < 60:
        return float(RUEDAS_ANIO)
    return (len(fechas) - 1) / (dias / DIAS_ANIO)


@dataclass
class MetricasRiesgo:
    retorno_anual: Optional[float]  # CAGR del indice, fraccion
    volatilidad_anual: float  # fraccion
    sharpe: Optional[float]
    sortino: Optional[float]
    beta: Optional[float]
    correlacion: Optional[float]
    tasa_libre_riesgo: float
    vol_movil_1m: pd.Series = field(repr=False)
    vol_movil_3m: pd.Series = field(repr=False)
    ruedas: int = 0


def metricas_riesgo(
    indice: pd.Series,
    indice_benchmark: Optional[pd.Series] = None,
    tasa_libre_riesgo_anual: float = 0.0,
) -> MetricasRiesgo:
    """Sharpe y Sortino anualizados (sobre rendimientos diarios en exceso
    de la tasa libre de riesgo), beta y correlacion contra el benchmark,
    y volatilidad movil de ~1 y ~3 meses (21 y 63 ruedas)."""
    idx = _solo_ruedas(indice)
    r = idx.pct_change().dropna()
    if len(r) < 20:
        raise PerformanceError("Hacen falta al menos ~20 ruedas de historia para medir riesgo.")
    # v10.1: anualizar con la frecuencia REAL de la serie. La curva es
    # diaria calendario y _solo_ruedas deja lunes a viernes (~261/anio,
    # feriados incluidos con precio repetido); usar 252 subestimaba
    # levemente la volatilidad y el Sharpe.
    ppa = _periodos_por_anio(idx.index)
    rf_d = (1 + tasa_libre_riesgo_anual) ** (1 / ppa) - 1
    exceso = r - rf_d
    sd = r.std(ddof=1)
    vol = float(sd * math.sqrt(ppa))
    sharpe = float(exceso.mean() / sd * math.sqrt(ppa)) if sd > 0 else None
    abajo = np.sqrt(np.mean(np.minimum(exceso.values, 0.0) ** 2))
    sortino = float(exceso.mean() * ppa / (abajo * math.sqrt(ppa))) if abajo > 0 else None

    dias = int((idx.index[-1] - idx.index[0]).days)
    retorno_anual = anualizar(float(idx.iloc[-1] / idx.iloc[0] - 1), dias)

    beta = correl = None
    if indice_benchmark is not None:
        b = _solo_ruedas(indice_benchmark.reindex(indice.index).ffill())
        rb = b.pct_change()
        juntos = pd.concat([r, rb], axis=1, join="inner").dropna()
        juntos.columns = ["p", "b"]
        if len(juntos) >= 20 and juntos["b"].var() > 0:
            beta = float(juntos["p"].cov(juntos["b"]) / juntos["b"].var())
            correl = float(juntos["p"].corr(juntos["b"]))

    return MetricasRiesgo(
        retorno_anual=retorno_anual,
        volatilidad_anual=vol,
        sharpe=sharpe,
        sortino=sortino,
        beta=beta,
        correlacion=correl,
        tasa_libre_riesgo=tasa_libre_riesgo_anual,
        vol_movil_1m=r.rolling(21).std() * math.sqrt(ppa) * 100,
        vol_movil_3m=r.rolling(63).std() * math.sqrt(ppa) * 100,
        ruedas=len(r),
    )


# ===========================================================================
# C3 -- Concentracion
# ===========================================================================
@dataclass
class Concentracion:
    pesos: pd.Series  # ticker -> % (desc)
    top1_ticker: str
    top1_pct: float
    top3_pct: float
    top5_pct: float
    hhi: float  # 0..10000 (escala usual)
    n_efectivo: float  # 1 / sum(w^2)


def concentracion(valores: pd.Series) -> Concentracion:
    """`valores`: ticker -> valor actual (cualquier moneda). Ignora <= 0."""
    v = valores[valores > 0].astype(float)
    if v.empty:
        raise PerformanceError("No hay posiciones con valor para medir concentracion.")
    w = (v / v.sum()).sort_values(ascending=False)
    hhi = float((w**2).sum())
    return Concentracion(
        pesos=w * 100,
        top1_ticker=str(w.index[0]),
        top1_pct=float(w.iloc[0] * 100),
        top3_pct=float(w.iloc[:3].sum() * 100),
        top5_pct=float(w.iloc[:5].sum() * 100),
        hhi=hhi * 10000,
        n_efectivo=1.0 / hhi,
    )


def exposicion_por(valores: pd.Series, mapa: Dict[str, str], sin_dato: str = "Sin dato") -> pd.Series:
    """Agrupa `valores` (ticker -> valor) segun `mapa` (ticker -> grupo)
    y devuelve % por grupo, ordenado desc."""
    v = valores[valores > 0].astype(float)
    grupos = v.groupby(lambda t: mapa.get(t) or sin_dato).sum()
    return (grupos / grupos.sum() * 100).sort_values(ascending=False)


# ===========================================================================
# C4 -- Contribucion al riesgo
# ===========================================================================
def contribucion_al_riesgo(precios: pd.DataFrame, pesos: pd.Series, ruedas: int = RUEDAS_ANIO) -> pd.DataFrame:
    """
    Contribucion % de cada activo a la volatilidad total de la cartera
    (descomposicion de Euler):  RC_i = w_i * (Sigma w)_i / (w' Sigma w).
    Suma 100%. Un activo con RC mucho mayor que su peso "mete" mas riesgo
    del que su tamanio sugiere.

    `precios`: fecha x ticker (se usan las ultimas `ruedas` ruedas).
    `pesos`: ticker -> peso (cualquier escala; se renormaliza a los
    tickers que tengan precios).
    """
    cols = [t for t in pesos.index if t in precios.columns]
    if len(cols) < 2:
        raise PerformanceError("Hacen falta al menos 2 activos con historia de precios.")
    p = _solo_ruedas(precios[cols].ffill()).iloc[-(ruedas + 1):]
    r = p.pct_change(fill_method=None).iloc[1:]
    # v10.1: antes los activos con historia corta (comprados hace poco)
    # se completaban con rendimiento 0 donde no habia dato, lo que los
    # hacia parecer mucho mas estables de lo que son (volatilidad y
    # covarianzas diluidas). Ahora la covarianza es POR PARES (cada par
    # usa las ruedas que tienen en comun, sin achicar la ventana de los
    # demas) y los activos con menos de MIN_RUEDAS_RIESGO ruedas se
    # excluyen y se informan en df.attrs["excluidos_poca_historia"].
    r = r.dropna(axis=1, how="all")
    obs = r.notna().sum()
    excluidos = sorted(obs[obs < MIN_RUEDAS_RIESGO].index.tolist())
    r = r.drop(columns=excluidos)
    cols = list(r.columns)
    if len(cols) < 2:
        raise PerformanceError("Hacen falta al menos 2 activos con suficiente historia de precios.")
    w = pesos.reindex(cols).astype(float)
    w = w / w.sum()
    cov_df = r.cov(min_periods=MIN_RUEDAS_RIESGO).fillna(0.0)
    cov = cov_df.values * RUEDAS_ANIO
    wv = w.values
    var_p = float(wv @ cov @ wv)
    if var_p <= 0:
        raise PerformanceError("La varianza de la cartera dio 0.")
    marginal = cov @ wv
    rc = wv * marginal / var_p
    vol_ind = np.sqrt(np.diag(cov))
    df = pd.DataFrame(
        {
            "Ticker": cols,
            "Peso %": wv * 100,
            "Contribucion al riesgo %": rc * 100,
            "Volatilidad anual %": vol_ind * 100,
        }
    )
    df["Riesgo / peso"] = df["Contribucion al riesgo %"] / df["Peso %"]
    df = df.sort_values("Contribucion al riesgo %", ascending=False).reset_index(drop=True)
    df.attrs["excluidos_poca_historia"] = excluidos
    return df


# ===========================================================================
# D1 -- Historial de aportes (depositos/retiros de la cuenta)
# ===========================================================================
@dataclass
class HistorialAportes:
    mensual: pd.DataFrame  # index = mes (Timestamp fin de mes): Depositos, Retiros, Neto, Neto USD, Acumulado, Acumulado USD
    total_depositado: float
    total_retirado: float
    neto: float
    neto_usd: Optional[float]
    promedio_mensual_6m: float
    promedio_mensual_6m_usd: Optional[float]
    meses_con_aporte: int
    meses_totales: int
    racha_actual: int  # meses consecutivos con deposito > 0 (sin contar el mes en curso si todavia no aportaste)


def historial_aportes(movimientos: pd.DataFrame, ccl: Optional[pd.Series] = None) -> HistorialAportes:
    """Depositos ('Recibo De Cobro') y retiros ('Orden De Pago') de la
    cuenta, por mes. Es la plata que ENTRO a la cuenta (despues se reparte
    entre acciones, FCI, caucion, etc.)."""
    ops = movimientos[movimientos["tipo_operacion_norm"].isin(["INGRESO_CASH", "EGRESO_CASH"])].copy()
    ops = ops[ops["fechaEjecucion"].notna() & (ops["moneda"].fillna("ARS") == "ARS")]
    if ops.empty:
        raise PerformanceError("El CSV no tiene depositos ni retiros.")
    ops["monto"] = ops["total"].fillna(ops["montoBruto"]).astype(float)
    if ccl is not None:
        ops["ccl"] = valores_en_fechas(ccl, ops["fechaEjecucion"])
        ops["monto_usd"] = ops["monto"] / ops["ccl"]
    ops["mes"] = ops["fechaEjecucion"].dt.to_period("M")

    desde = ops["mes"].min()
    hasta = pd.Timestamp.today().to_period("M")
    meses = pd.period_range(desde, hasta, freq="M")
    dep = ops[ops["monto"] > 0].groupby("mes")["monto"].sum().reindex(meses, fill_value=0.0)
    ret = -ops[ops["monto"] < 0].groupby("mes")["monto"].sum().reindex(meses, fill_value=0.0)
    mensual = pd.DataFrame({"Depositos": dep, "Retiros": ret})
    mensual["Neto"] = mensual["Depositos"] - mensual["Retiros"]
    mensual["Acumulado"] = mensual["Neto"].cumsum()
    neto_usd = prom_usd = None
    if ccl is not None:
        mensual["Neto USD"] = ops.groupby("mes")["monto_usd"].sum().reindex(meses, fill_value=0.0)
        mensual["Acumulado USD"] = mensual["Neto USD"].cumsum()
        neto_usd = float(mensual["Neto USD"].sum())
    mensual.index = mensual.index.to_timestamp(how="end").normalize()

    # promedio de los ultimos 6 meses COMPLETOS (el mes en curso esta a medias)
    completos = mensual.iloc[:-1] if len(mensual) > 1 else mensual
    ult6 = completos.iloc[-6:]
    prom6 = float(ult6["Neto"].mean()) if not ult6.empty else 0.0
    if ccl is not None and not ult6.empty:
        prom_usd = float(ult6["Neto USD"].mean())

    con_aporte = mensual["Depositos"] > 0
    racha = 0
    serie_racha = list(con_aporte.values)
    if serie_racha and not serie_racha[-1]:
        serie_racha = serie_racha[:-1]  # mes en curso sin aporte todavia: no corta la racha
    for tiene in reversed(serie_racha):
        if tiene:
            racha += 1
        else:
            break

    return HistorialAportes(
        mensual=mensual,
        total_depositado=float(dep.sum()),
        total_retirado=float(ret.sum()),
        neto=float(dep.sum() - ret.sum()),
        neto_usd=neto_usd,
        promedio_mensual_6m=prom6,
        promedio_mensual_6m_usd=prom_usd,
        meses_con_aporte=int(con_aporte.sum()),
        meses_totales=int(len(mensual)),
        racha_actual=racha,
    )


# ===========================================================================
# D3 -- Dividendos y rentas
# ===========================================================================
TIPO_DIV_ARS = "Dividendos en pesos"
TIPO_DIV_USD = "Dividendos en dolares"
TIPO_RENTA = "Cupones y amortizaciones"


@dataclass
class HistorialDividendos:
    detalle: pd.DataFrame  # una fila por cobro: fecha, tipo, ARS, USD
    mensual_ars: pd.DataFrame  # mes x tipo (ARS)
    mensual_usd: pd.DataFrame  # mes x tipo (USD)
    total_ars: float
    total_usd: float
    ultimos_12m_ars: float
    ultimos_12m_usd: float
    en_especie: pd.DataFrame  # nominales recibidos como dividendo (ticker, cantidad)


def historial_dividendos(movimientos: pd.DataFrame, ccl: pd.Series) -> HistorialDividendos:
    """
    Clasifica todo lo que la cartera PAGO:
      - Dividendos en pesos: DIVIDENDO + AJUSTE_DIVIDENDO ('total', neto).
      - Dividendos en dolares: DIVIDENDO_ESPECIE sin ticker con
        instrumento "Dolar..." -- en el CSV de Cocos la 'cantidad' son los
        USD recibidos y 'total' la retencion/comision en ARS.
      - Cupones y amortizaciones de bonos: RENTA_AMORTIZACION (USD,
        'montoBruto') y "Renta y amortizacion en especie" (cantidad USD).
        OJO: una amortizacion devuelve capital, no es renta pura.
      - DIVIDENDO_ESPECIE CON ticker (nominales de un bono/accion) se
        listan aparte: no tienen valor en efectivo en el CSV.
    """
    m = movimientos[movimientos["fechaEjecucion"].notna()].copy()

    filas = []
    ars = m[m["tipo_operacion_norm"].isin(["DIVIDENDO", "AJUSTE_DIVIDENDO"])]
    for _, f in ars.iterrows():
        filas.append({"fecha": f["fechaEjecucion"], "tipo": TIPO_DIV_ARS, "ars": float(f["total"] or 0.0), "usd": None})

    es_dolar = m["instrumento"].fillna("").str.lower().str.contains("dólar|dolar", regex=True)
    div_usd = m[(m["tipo_operacion_norm"] == "DIVIDENDO_ESPECIE") & m["ticker"].isna() & es_dolar]
    for _, f in div_usd.iterrows():
        filas.append(
            {"fecha": f["fechaEjecucion"], "tipo": TIPO_DIV_USD, "ars": float(f["total"] or 0.0), "usd": float(f["cantidad"] or 0.0)}
        )

    renta_usd = m[m["tipo_operacion_norm"] == "RENTA_AMORTIZACION"]
    for _, f in renta_usd.iterrows():
        filas.append({"fecha": f["fechaEjecucion"], "tipo": TIPO_RENTA, "ars": 0.0, "usd": float(f["montoBruto"] or 0.0)})
    renta_especie = m[
        m["tipoOperacion"].fillna("").str.lower().str.contains("renta y amortizacion en especie") & es_dolar
    ]
    for _, f in renta_especie.iterrows():
        filas.append(
            {"fecha": f["fechaEjecucion"], "tipo": TIPO_RENTA, "ars": float(f["total"] or 0.0), "usd": float(f["cantidad"] or 0.0)}
        )

    especie = m[(m["tipo_operacion_norm"] == "DIVIDENDO_ESPECIE") & m["ticker"].notna()]
    en_especie = especie.groupby("ticker")["cantidad"].sum().reset_index().rename(
        columns={"ticker": "Ticker", "cantidad": "Nominales recibidos"}
    )

    if not filas:
        raise PerformanceError("El CSV no tiene dividendos ni rentas cobradas.")
    det = pd.DataFrame(filas)
    det["ccl"] = valores_en_fechas(ccl, det["fecha"])
    # componente en USD convertido a ARS al CCL del dia + componente ARS (neto de retenciones)
    det["usd"] = det["usd"].astype(float)
    det["total_ars"] = det["ars"] + det["usd"].fillna(0.0) * det["ccl"]
    det["total_usd"] = det["total_ars"] / det["ccl"]
    det = det.sort_values("fecha")
    det["mes"] = det["fecha"].dt.to_period("M")

    meses = pd.period_range(det["mes"].min(), pd.Timestamp.today().to_period("M"), freq="M")
    mensual_ars = det.pivot_table(index="mes", columns="tipo", values="total_ars", aggfunc="sum").reindex(meses).fillna(0.0)
    mensual_usd = det.pivot_table(index="mes", columns="tipo", values="total_usd", aggfunc="sum").reindex(meses).fillna(0.0)
    for tabla in (mensual_ars, mensual_usd):
        tabla.index = tabla.index.to_timestamp(how="end").normalize()
        tabla.columns.name = None

    corte = pd.Timestamp.today().normalize() - pd.DateOffset(months=12)
    ult = det[det["fecha"] > corte]
    return HistorialDividendos(
        detalle=det[["fecha", "tipo", "total_ars", "total_usd"]].reset_index(drop=True),
        mensual_ars=mensual_ars,
        mensual_usd=mensual_usd,
        total_ars=float(det["total_ars"].sum()),
        total_usd=float(det["total_usd"].sum()),
        ultimos_12m_ars=float(ult["total_ars"].sum()),
        ultimos_12m_usd=float(ult["total_usd"].sum()),
        en_especie=en_especie,
    )


# ===========================================================================
# D4 -- Tus compras sobre el grafico
# ===========================================================================
def operaciones_de_ticker(movimientos: pd.DataFrame, ticker: str) -> pd.DataFrame:
    ops = movimientos[
        (movimientos["ticker"] == ticker)
        & movimientos["tipo_operacion_norm"].isin(["COMPRA", "VENTA"])
        & movimientos["fechaEjecucion"].notna()
    ].copy()
    ops["Tipo"] = np.where(ops["tipo_operacion_norm"] == "COMPRA", "Compra", "Venta")
    ops["Cantidad"] = ops["cantidad"].abs()
    ops = ops.rename(columns={"fechaEjecucion": "Fecha", "precio": "Precio", "total": "Total"})
    return ops[["Fecha", "Tipo", "Cantidad", "Precio", "Total"]].sort_values("Fecha").reset_index(drop=True)


@dataclass
class AnalisisTiming:
    precio_promedio_compra: float
    precio_promedio_periodo: float  # promedio simple del precio en la ventana (informativo)
    precio_referencia_dca: float  # lo que pagaria en promedio un DCA de monto fijo en la misma ventana
    ventaja_pct: float  # vs. precio_referencia_dca; < 0 = compraste mas barato que el DCA mecanico
    pct_compras_bajo_precio_actual: float
    precio_actual: float
    n_compras: int
    n_ventas: int


def analisis_timing(precios: pd.Series, ops: pd.DataFrame, factor: Optional[pd.Series] = None) -> AnalisisTiming:
    """
    Compara tu precio promedio de compra (ponderado por nominales) contra
    un DCA MECANICO de referencia: invertir el mismo monto todos los dias
    habiles de tu ventana de compras (de tu primera a tu ultima compra).
    Ese DCA paga la media ARMONICA de los precios, no la media simple.

    v10.1 -- por que no contra el promedio simple: con montos fijos se
    compran mas nominales cuando el precio esta bajo, asi que el precio
    promedio de cualquier DCA queda SIEMPRE por debajo del promedio
    simple (desigualdad media armonica <= media aritmetica), aunque no
    haya ninguna habilidad de timing. La version anterior mostraba esa
    ventaja matematica como si fuera merito. Ademas la ventana ahora
    termina en tu ultima compra (los precios posteriores no los podias
    comprar). Con una sola fecha de compra, la ventana va hasta hoy.

    Con `factor` (CCL) todo se mide en USD, lo que saca el efecto del
    dolar de los CEDEARs.
    """
    compras = ops[ops["Tipo"] == "Compra"].copy()
    if compras.empty:
        raise PerformanceError("No hay compras de este activo.")
    serie = precios.dropna()
    if factor is not None:
        serie = serie / valores_en_fechas(factor, serie.index)
        compras["Precio"] = compras["Precio"].values / valores_en_fechas(factor, compras["Fecha"])
    ppc = float((compras["Precio"] * compras["Cantidad"]).sum() / compras["Cantidad"].sum())
    inicio = compras["Fecha"].min()
    fin = compras["Fecha"].max() if compras["Fecha"].nunique() >= 2 else serie.index[-1]
    periodo = _solo_ruedas(serie[inicio:fin])
    periodo = periodo[periodo > 0]
    prom = float(periodo.mean()) if not periodo.empty else float("nan")
    ref = float(len(periodo) / (1.0 / periodo).sum()) if not periodo.empty else float("nan")
    actual = float(serie.iloc[-1])
    return AnalisisTiming(
        precio_promedio_compra=ppc,
        precio_promedio_periodo=prom,
        precio_referencia_dca=ref,
        ventaja_pct=(ppc / ref - 1) * 100 if ref and not math.isnan(ref) else float("nan"),
        pct_compras_bajo_precio_actual=float((compras["Precio"] < actual).mean() * 100),
        precio_actual=actual,
        n_compras=int(len(compras)),
        n_ventas=int((ops["Tipo"] == "Venta").sum()),
    )


# ===========================================================================
# E2 -- Proyeccion Monte Carlo
# ===========================================================================
@dataclass
class Proyeccion:
    meses: pd.DatetimeIndex
    percentiles: pd.DataFrame  # columnas p10, p25, p50, p75, p90 (valor al final de cada mes)
    sin_volatilidad: pd.Series  # trayectoria determinista (rendimiento esperado exacto)
    aportado: pd.Series  # valor inicial + aportes acumulados (sin rendimiento)
    prob_meta: Optional[float]  # prob. de superar la meta al final del horizonte
    mes_meta_mediana: Optional[pd.Timestamp]  # primer mes en que la mediana supera la meta
    prob_meta_en_fecha: Optional[float]  # prob. de superar la meta en fecha_objetivo


def proyeccion_montecarlo(
    valor_inicial: float,
    aporte_mensual: float,
    rendimiento_anual: float,
    volatilidad_anual: float,
    anios: int,
    meta: Optional[float] = None,
    fecha_objetivo: Optional[pd.Timestamp] = None,
    simulaciones: int = 2000,
    semilla: int = 42,
) -> Proyeccion:
    """
    Simulacion mensual: cada mes la cartera crece por un factor
    log-normal cuya MEDIANA anual es (1 + rendimiento_anual) y cuya
    dispersion es `volatilidad_anual`; el aporte se suma al final de cada
    mes. Semilla fija para que el grafico no "salte" en cada rerun.
    Todo en la moneda que se le pase (la UI usa USD).
    """
    n = max(1, int(anios * 12))
    rng = np.random.default_rng(semilla)
    mu_m = math.log(1 + rendimiento_anual) / 12
    sd_m = volatilidad_anual / math.sqrt(12)
    shocks = rng.standard_normal((simulaciones, n))
    factores = np.exp(mu_m + sd_m * shocks)
    valores = np.empty((simulaciones, n))
    v = np.full(simulaciones, float(valor_inicial))
    for i in range(n):
        v = v * factores[:, i] + aporte_mensual
        valores[:, i] = v

    inicio = pd.Timestamp.today().normalize() + pd.offsets.MonthEnd(0)
    meses = pd.date_range(inicio + pd.offsets.MonthEnd(1), periods=n, freq="ME")
    pct = np.percentile(valores, [10, 25, 50, 75, 90], axis=0)
    percentiles = pd.DataFrame(pct.T, index=meses, columns=["p10", "p25", "p50", "p75", "p90"])

    det = np.empty(n)
    vd = float(valor_inicial)
    for i in range(n):
        vd = vd * math.exp(mu_m) + aporte_mensual
        det[i] = vd
    aportado = pd.Series(valor_inicial + aporte_mensual * np.arange(1, n + 1), index=meses)

    prob = mes_med = prob_fecha = None
    if meta:
        prob = float((valores[:, -1] >= meta).mean())
        cruza = percentiles.index[percentiles["p50"] >= meta]
        mes_med = cruza[0] if len(cruza) else None
        if fecha_objetivo is not None:
            pos = meses.searchsorted(pd.Timestamp(fecha_objetivo))
            if pos < n:
                prob_fecha = float((valores[:, pos] >= meta).mean())
    return Proyeccion(
        meses=meses,
        percentiles=percentiles,
        sin_volatilidad=pd.Series(det, index=meses),
        aportado=aportado,
        prob_meta=prob,
        mes_meta_mediana=mes_med,
        prob_meta_en_fecha=prob_fecha,
    )
