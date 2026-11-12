"""
desktop/backend/server.py

API local (FastAPI) para la app de escritorio. Reutiliza TAL CUAL la logica
de core/ (la misma que usa la app Streamlit): aca no hay calculo de negocio
nuevo, solo carga de datos con cache en memoria y conversion a JSON.

Correr a mano (para desarrollo):
    py -3.10 desktop/backend/server.py
La app Tauri lo lanza sola al abrirse y lo cierra al salir.
"""

from __future__ import annotations

import json
import math
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from core.config_manager import (  # noqa: E402
    TIPOS_ACTIVO,
    TOLERANCIA_PCT,
    ConfigError,
    get_benchmark_tickers,
    get_target_by_ticker,
    guardar_desde_editor,
    load_config,
    validar_dataframes_editor,
)
from core.csv_parser import CsvParserError, parsear_movimientos, usando_demo  # noqa: E402
from core.historical_curve import HistoricalCurveError, calcular_curva_historica  # noqa: E402
from core.holdings import TICKER_CASH, calcular_tenencia_actual  # noqa: E402
from core.manual_holdings import (  # noqa: E402
    CATEGORIA_FUERA_DE_OBJETIVO,
    ManualHoldingsError,
    cargar_tenencias_manuales,
    guardar_tenencias_manuales,
)
from core.market_data import MarketDataError, get_dolar_ccl, obtener_cotizaciones  # noqa: E402
from core.market_extras import obtener_variacion_diaria, simbolos_para_variacion  # noqa: E402
from core.metas import cargar_metas, guardar_metas  # noqa: E402
from core.macro_data import MacroDataError, get_ccl_historico, get_inflacion_mensual  # noqa: E402
from core.performance import PerformanceError  # noqa: E402

import rendimiento as rend  # noqa: E402
import riesgo  # noqa: E402
import aportes as aportes_mod  # noqa: E402
import metas_diario as md  # noqa: E402
from core.diario import ACCIONES, REFERENCIA, DiarioError, cargar_diario, eliminar_entrada, guardar_diario, nueva_entrada  # noqa: E402
from core.metas import ESCENARIOS  # noqa: E402
from core.rutas import CONFIG_DIR, DATA_ROOT, MOVIMIENTOS_DIR  # noqa: E402
from core.analytics import AnalyticsError, calcular_analitica_riesgo  # noqa: E402
from core.market_extras import obtener_perfiles  # noqa: E402
from core.rebalancer import (  # noqa: E402
    BANDA_TOLERANCIA_PCT_DEFAULT,
    COMISION_PCT_APROX,
    RebalancerError,
    calcular_rebalanceo,
    calcular_rebalanceo_banda,
)

PUERTO = 8765

# ---------------------------------------------------------------------------
# Cache en memoria con TTL (equivalente a los @st.cache_data de app.py, pero
# vive mientras la app esta abierta: cambiar de pantalla no recalcula nada).
# ---------------------------------------------------------------------------
_cache: Dict[str, tuple[float, Any]] = {}
_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def cacheado(clave: str, ttl: float, fn: Callable[[], Any]) -> Any:
    ahora = time.time()
    hit = _cache.get(clave)
    if hit and ahora - hit[0] < ttl:
        return hit[1]
    with _locks_guard:
        lock = _locks.setdefault(clave, threading.Lock())
    with lock:  # dos pedidos simultaneos no descargan lo mismo dos veces
        hit = _cache.get(clave)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        valor = fn()
        _cache[clave] = (time.time(), valor)
        return valor


def _num(v: Any) -> Optional[float]:
    """NaN/inf/None -> None (JSON no tiene NaN)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _registros(df: pd.DataFrame) -> list[dict]:
    salida = []
    for fila in df.to_dict(orient="records"):
        limpio = {}
        for k, v in fila.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                limpio[k] = _num(v)
            elif v is None or (not isinstance(v, str) and pd.isna(v)):
                limpio[k] = None
            else:
                limpio[k] = str(v) if not isinstance(v, (str, bool)) else v
        salida.append(limpio)
    return salida


# ---------------------------------------------------------------------------
# Carga de datos (mismos TTL que app.py)
# ---------------------------------------------------------------------------
def _config() -> dict:
    return cacheado("config", 5, load_config)


def _movimientos() -> pd.DataFrame:
    return cacheado("movimientos", 300, parsear_movimientos)


def _base() -> dict:
    """Tenencia valuada + CCL + avisos: lo que necesitan Panel y Calculadora."""

    def calcular() -> dict:
        config = _config()
        movimientos = _movimientos()
        # La clave incluye los tickers configurados: si agregas un activo, se cotiza.
        firma = str(sorted((t, d.get("ticker_yfinance"), d.get("alias_ticker")) for t, d in config["activos"].items()))
        cotizaciones = cacheado("cotizaciones:" + firma, 60, lambda: obtener_cotizaciones(config))
        avisos: list[str] = []
        if usando_demo():
            avisos.append(f"Estás viendo datos de demostración. Para ver tu cartera, poné los CSV de movimientos de tu broker en {MOVIMIENTOS_DIR} (Configuración → Tus datos).")
        try:
            ccl = cacheado("ccl", 60, get_dolar_ccl)
        except MarketDataError as e:
            ccl = None
            avisos.append(f"Dolar CCL no disponible ({e}). Los montos en USD no van a estar disponibles.")
        try:
            manuales = cargar_tenencias_manuales()
        except ManualHoldingsError as e:
            manuales = []
            avisos.append(f"Tenencias manuales no disponibles ({e}).")
        holdings = calcular_tenencia_actual(
            config=config, movimientos=movimientos, cotizaciones=cotizaciones, tenencias_manuales=manuales
        )
        # CASH (dividendos) no tiene cotizacion por diseno: no es un aviso.
        sin_precio = holdings[holdings["Precio Actual"].isna() & (holdings["Ticker"] != TICKER_CASH)]["Ticker"].tolist()
        if sin_precio:
            avisos.append(f"Sin cotizacion en vivo: {', '.join(sin_precio)}.")
        return {"config": config, "holdings": holdings, "ccl": ccl, "avisos": avisos, "hora": datetime.now()}

    return cacheado("base", 60, calcular)


def _curva():
    config = _config()
    benchmarks = get_benchmark_tickers(config)
    clave = "curva:" + "|".join(f"{b['ticker']}={b['label']}" for b in benchmarks)
    return cacheado(clave, 3600, lambda: calcular_curva_historica(_movimientos(), benchmarks=benchmarks))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
app = FastAPI(title="Investment Portfolio Tracker API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # solo escucha en 127.0.0.1; el origen es la ventana Tauri o Vite
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/datos")
def datos_usuario() -> dict:
    """Donde estan los datos del usuario (para mostrarlo en Configuracion)."""
    MOVIMIENTOS_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "raiz": str(DATA_ROOT),
        "movimientos": str(MOVIMIENTOS_DIR),
        "csv": len(list(MOVIMIENTOS_DIR.rglob("*.csv"))),
        "demo": usando_demo(),
    }


@app.post("/api/abrir-carpeta")
def abrir_carpeta() -> dict:
    """Abre la carpeta de movimientos en el Explorador de Windows."""
    import os

    MOVIMIENTOS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(MOVIMIENTOS_DIR)  # type: ignore[attr-defined]
    except (AttributeError, OSError) as e:
        raise HTTPException(500, f"No se pudo abrir la carpeta: {e}")
    return {"ok": True}


@app.post("/api/refresh")
def refresh() -> dict:
    _cache.clear()
    return {"ok": True}


@app.get("/api/panel")
def panel() -> dict:
    try:
        base = _base()
    except ConfigError as e:
        raise HTTPException(500, f"Error de configuracion: {e}")
    except CsvParserError as e:
        raise HTTPException(500, f"Error leyendo los CSV de movimientos: {e}")

    config, holdings, ccl = base["config"], base["holdings"], base["ccl"]
    avisos = list(base["avisos"])
    valor_ars = float(holdings["Valor ARS"].sum(skipna=True))
    valor_usd = valor_ars / ccl if ccl else None

    # P&L acumulado y peor brecha (misma logica que la pestana Panel de app.py)
    pnl_pct = brecha_pct = None
    brecha_fecha = None
    try:
        curva = _curva()
    except HistoricalCurveError as e:
        curva = None
        avisos.append(f"Curva historica no disponible: {e}")
    if curva is not None and len(curva.valor_ars):
        ultimo_cap = curva.capital_invertido_ars.iloc[-1]
        if ultimo_cap:
            pnl_pct = (curva.valor_ars.iloc[-1] / ultimo_cap - 1) * 100
        valido = curva.capital_invertido_ars > 0
        if valido.any():
            b = (curva.valor_ars[valido] - curva.capital_invertido_ars[valido]) / curva.capital_invertido_ars[valido] * 100
            brecha_pct, brecha_fecha = float(b.min()), b.idxmin().strftime("%Y-%m-%d")

    # Variacion de la ultima rueda
    var = {"ars": None, "pct": None, "fecha": None, "suben": [], "bajan": []}
    simbolos = simbolos_para_variacion(holdings["Ticker"].dropna().astype(str).tolist(), config)
    variacion = cacheado(
        "var:" + ",".join(sorted(simbolos)), 300, lambda: obtener_variacion_diaria(simbolos)
    )
    if not variacion.empty:
        v = holdings[["Ticker", "Valor ARS"]].merge(variacion, on="Ticker", how="inner")
        v = v[v["Valor ARS"].fillna(0) > 0]
        if not v.empty:
            mov = v["Valor ARS"] * (v["Var %"] / 100) / (1 + v["Var %"] / 100)
            var_ars = float(mov.sum())
            base_ayer = float(v["Valor ARS"].sum()) - var_ars
            v = v.sort_values("Var %")
            var = {
                "ars": var_ars,
                "pct": var_ars / base_ayer * 100 if base_ayer else None,
                "fecha": pd.to_datetime(v["Fecha"]).max().strftime("%Y-%m-%d"),
                "suben": [{"ticker": t, "pct": _num(p)} for t, p in zip(v["Ticker"].iloc[::-1].head(3), v["Var %"].iloc[::-1].head(3))],
                "bajan": [{"ticker": t, "pct": _num(p)} for t, p in zip(v["Ticker"].head(3), v["Var %"].head(3))],
            }

    # Meta patrimonial
    metas = cargar_metas()
    meta = None
    if metas.get("meta_usd") and valor_usd is not None:
        m = float(metas["meta_usd"])
        meta = {"usd": m, "fecha": metas.get("fecha_objetivo"), "pct": valor_usd / m * 100, "falta": max(m - valor_usd, 0)}

    objetivos = get_target_by_ticker(config)
    tickers_obj = list(config["activos"].keys())
    return {
        "ccl": ccl,
        "actualizado": base["hora"].isoformat(timespec="seconds"),
        "avisos": avisos,
        "kpis": {
            "valor_ars": valor_ars,
            "valor_usd": valor_usd,
            "pnl_pct": _num(pnl_pct),
            "brecha_pct": _num(brecha_pct),
            "brecha_fecha": brecha_fecha,
            "variacion": var,
        },
        "meta": meta,
        "orden_tickers": tickers_obj + [t for t in holdings["Ticker"].tolist() if t not in tickers_obj],
        "objetivo": [{"ticker": t, "pct": _num(objetivos.get(t))} for t in tickers_obj],
        "tenencia": _registros(holdings),
        "comision_pct": COMISION_PCT_APROX,
        "banda_default": BANDA_TOLERANCIA_PCT_DEFAULT,
    }


@app.get("/api/curva")
def curva() -> dict:
    try:
        c = _curva()
    except HistoricalCurveError as e:
        raise HTTPException(500, str(e))
    fechas = [d.strftime("%Y-%m-%d") for d in c.valor_ars.index]
    return {
        "fechas": fechas,
        "valor": [_num(x) for x in c.valor_ars.values],
        "capital": [_num(x) for x in c.capital_invertido_ars.values],
        "benchmarks": {lbl: [_num(x) for x in s.values] for lbl, s in c.valores_benchmark.items()},
        "advertencias": c.advertencias,
    }


class PedidoRebalanceo(BaseModel):
    monto: float = Field(ge=0)


@app.post("/api/rebalanceo")
def rebalanceo(pedido: PedidoRebalanceo) -> dict:
    base = _base()
    try:
        r = calcular_rebalanceo(base["holdings"], base["config"], monto_x=pedido.monto, dolar_ccl=base["ccl"])
    except RebalancerError as e:
        raise HTTPException(400, str(e))
    ordenes = r.ordenes[r.ordenes["Monto a Invertir ARS"] > 0]
    return {
        "monto": r.monto_a_invertir,
        "asignado": r.monto_total_asignado,
        "comision": r.comision_total_estimada,
        "costo_total": r.costo_total_estimado,
        "vuelto": r.vuelto_total,
        "advertencias": r.advertencias,
        "ordenes": _registros(ordenes),
        "proyeccion": {
            str(t): _num(m) for t, m in r.ordenes.set_index("Ticker")["Monto a Invertir ARS"].items()
        },
    }


class PedidoBanda(BaseModel):
    banda: float = Field(default=BANDA_TOLERANCIA_PCT_DEFAULT, gt=0, le=50)
    monto_nuevo: float = Field(default=0, ge=0)


@app.post("/api/banda")
def banda(pedido: PedidoBanda) -> dict:
    base = _base()
    try:
        r = calcular_rebalanceo_banda(
            base["holdings"],
            base["config"],
            banda_tolerancia_pct=pedido.banda,
            monto_nuevo=pedido.monto_nuevo,
            dolar_ccl=base["ccl"],
        )
    except RebalancerError as e:
        raise HTTPException(400, str(e))
    return {
        "banda": r.banda_tolerancia_pct,
        "monto_nuevo": r.monto_nuevo,
        "venta_bruta": r.venta_bruta_total,
        "comision_venta": r.comision_venta_total,
        "venta_neta": r.venta_neta_total,
        "efectivo_disponible": r.efectivo_disponible_total,
        "compra_neta": r.compra_neta_total,
        "comision_compra": r.comision_compra_total,
        "costo_compra": r.costo_compra_total,
        "efectivo_sobrante": r.efectivo_sobrante,
        "advertencias": r.advertencias,
        "desviaciones": _registros(r.desviaciones),
        "ventas": _registros(r.ordenes_venta),
        "compras": _registros(r.ordenes_compra),
    }


# ---------------------------------------------------------------------------
# Configuracion (mismos archivos y mismas validaciones que la pestana
# Configuracion de app.py: core.config_manager / core.manual_holdings)
# ---------------------------------------------------------------------------
class CategoriaIn(BaseModel):
    nombre: str = ""
    objetivo: Optional[float] = None
    descripcion: str = ""


class ActivoIn(BaseModel):
    ticker: str = ""
    nombre: str = ""
    categoria: str = ""
    tipo: str = "CEDEAR"
    objetivo_cat: Optional[float] = None
    ticker_mercado: str = ""
    alias: str = ""


class ConfigIn(BaseModel):
    categorias: list[CategoriaIn]
    activos: list[ActivoIn]


def _dataframes(c: ConfigIn) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Arma las grillas con las MISMAS columnas que el editor de app.py,
    asi validar_dataframes_editor / guardar_desde_editor se usan tal cual."""
    df_cat = pd.DataFrame(
        [{"Categoria": x.nombre, "% Objetivo Total": x.objetivo, "Descripcion": x.descripcion} for x in c.categorias],
        columns=["Categoria", "% Objetivo Total", "Descripcion"],
    )
    df_act = pd.DataFrame(
        [
            {
                "Ticker": x.ticker,
                "Nombre": x.nombre,
                "Categoria": x.categoria,
                "Tipo": x.tipo,
                "% Objetivo en Categoria": x.objetivo_cat,
                "Ticker de Mercado": x.ticker_mercado,
                "Ticker Alias (opcional)": x.alias,
            }
            for x in c.activos
        ],
        columns=["Ticker", "Nombre", "Categoria", "Tipo", "% Objetivo en Categoria", "Ticker de Mercado", "Ticker Alias (opcional)"],
    )
    return df_cat, df_act


# Datos de mercado que NO dependen de la config ni de las tenencias manuales:
# sobreviven a un guardado (re-descargarlos tarda ~20 s y no cambia nada).
_SOBREVIVEN_AL_GUARDAR = ("movimientos", "ccl", "macro", "curva:", "cotizaciones:", "perfiles:", "var:")


def _invalidar_datos() -> None:
    """Despues de guardar, se recalcula todo lo que depende de la config o de las
    tenencias (tenencia valuada, rendimientos por categoria, stress, etc.)."""
    for clave in list(_cache):
        if not clave.startswith(_SOBREVIVEN_AL_GUARDAR):
            _cache.pop(clave, None)


@app.get("/api/config")
def config_get() -> dict:
    try:
        config = load_config()
    except ConfigError as e:
        raise HTTPException(500, f"Error de configuracion: {e}")
    try:
        manuales = cargar_tenencias_manuales()
        error_manuales = None
    except ManualHoldingsError as e:
        manuales, error_manuales = [], str(e)
    return {
        "categorias": [
            {"nombre": n, "objetivo": _num(d.get("objetivo_pct")), "descripcion": d.get("descripcion", "") or ""}
            for n, d in config["categorias"].items()
        ],
        "activos": [
            {
                "ticker": t,
                "nombre": d.get("nombre", "") or "",
                "categoria": d.get("categoria", "") or "",
                "tipo": d.get("tipo", "CEDEAR") or "CEDEAR",
                "objetivo_cat": _num(d.get("objetivo_pct_categoria", 0)),
                "ticker_mercado": d.get("ticker_yfinance") or "",
                "alias": d.get("alias_ticker", "") or "",
            }
            for t, d in config["activos"].items()
        ],
        "tipos": TIPOS_ACTIVO,
        "tolerancia": TOLERANCIA_PCT,
        "ultima_actualizacion": config.get("meta", {}).get("ultima_actualizacion"),
        "manuales": [
            {"ticker": str(m.get("ticker", "")), "cantidad": _num(m.get("cantidad")), "categoria": m.get("categoria") or CATEGORIA_FUERA_DE_OBJETIVO}
            for m in manuales
        ],
        "error_manuales": error_manuales,
        "categoria_fuera": CATEGORIA_FUERA_DE_OBJETIVO,
    }


@app.post("/api/config/validar")
def config_validar(c: ConfigIn) -> dict:
    return {"errores": validar_dataframes_editor(*_dataframes(c))}


@app.put("/api/config")
def config_guardar(c: ConfigIn) -> dict:
    df_cat, df_act = _dataframes(c)
    try:
        meta = load_config().get("meta")
        guardar_desde_editor(df_cat, df_act, meta_original=meta)
    except ConfigError as e:
        raise HTTPException(400, str(e))
    _invalidar_datos()
    return {"ok": True}


class ManualIn(BaseModel):
    ticker: str
    cantidad: float
    categoria: str = ""


@app.put("/api/manuales")
def manuales_guardar(lista: list[ManualIn]) -> dict:
    df = pd.DataFrame(
        [{"Ticker": m.ticker.strip().upper(), "Cantidad": m.cantidad, "Categoria": m.categoria} for m in lista],
        columns=["Ticker", "Cantidad", "Categoria"],
    )
    try:
        guardar_tenencias_manuales(df)
    except ManualHoldingsError as e:
        raise HTTPException(400, str(e))
    _invalidar_datos()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Rendimiento (ver rendimiento.py)
# ---------------------------------------------------------------------------
def _macro() -> tuple:
    """CCL historico + inflacion mensual (TTL 6 h, como _cargar_macro de app.py)."""

    def calcular():
        avisos: list[str] = []
        ccl_hist = ipc = None
        try:
            r = get_ccl_historico()
            ccl_hist, avisos = r.serie, avisos + r.advertencias
        except MacroDataError as e:
            avisos.append(f"{e} Las vistas en dólares no van a estar disponibles.")
        try:
            r = get_inflacion_mensual()
            ipc, avisos = r.serie, avisos + r.advertencias
        except MacroDataError as e:
            avisos.append(f"{e} Las vistas ajustadas por inflación no van a estar disponibles.")
        return ccl_hist, ipc, avisos

    return cacheado("macro", 6 * 3600, calcular)


def _curva_o_error():
    try:
        return _curva()
    except HistoricalCurveError as e:
        raise HTTPException(500, f"No se pudo reconstruir la curva histórica, que es la base de esta pestaña: {e}")


@app.get("/api/rendimiento")
def rendimiento(unidad: str = "usd") -> dict:
    curva_ = _curva_o_error()
    ccl_hist, ipc, avisos = _macro()
    try:
        return cacheado(f"rend:{unidad}:{id(curva_)}", 3600, lambda: rend.armar(curva_, _config(), unidad, ccl_hist, ipc, avisos))
    except PerformanceError as e:
        raise HTTPException(500, str(e))


@app.get("/api/rendimiento/contribucion")
def rendimiento_contribucion(unidad: str = "usd", periodo: str = "inicio") -> dict:
    curva_ = _curva_o_error()
    ccl_hist, ipc, _ = _macro()
    try:
        return rend.contribucion(curva_, unidad, periodo, ccl_hist, ipc)
    except Exception as e:  # datos incompletos: no tumbar la pantalla (igual que Streamlit)
        raise HTTPException(500, f"No se pudo calcular la contribución: {e}")


@app.get("/api/rendimiento/tir_cuenta")
def rendimiento_tir_cuenta(otros: Optional[float] = None) -> dict:
    curva_ = _curva_o_error()
    ccl_hist, ipc, _ = _macro()
    if otros is None:
        otros = float(cargar_metas().get("otros_cuenta_ars") or 0)
    res = rend.resumenes(curva_, rend.factores(ccl_hist, ipc, curva_.valor_ars.index))
    try:
        return rend.tir_de_cuenta(_movimientos(), _base()["holdings"], float(otros), ccl_hist, res)
    except PerformanceError as e:
        raise HTTPException(400, str(e))


class OtrosIn(BaseModel):
    valor: float = Field(ge=0)


@app.put("/api/metas/otros_cuenta")
def guardar_otros_cuenta(x: OtrosIn) -> dict:
    metas = cargar_metas()
    metas["otros_cuenta_ars"] = int(x.valor)
    guardar_metas(metas)
    return {"ok": True}


def _precalentar() -> None:
    """Descarga todo en segundo plano apenas arranca, asi la primera
    pantalla ya encuentra los datos listos."""
    try:
        _base()
        _curva()
        _macro()
    except Exception as e:  # noqa: BLE001 - el error real se ve al pedir el endpoint
        print(f"[precarga] {e}", flush=True)


# ---------------------------------------------------------------------------
# Riesgo (ver riesgo.py). Cuatro partes independientes: la pantalla muestra
# primero lo que esta en memoria y despues lo que descarga datos.
# ---------------------------------------------------------------------------
@app.get("/api/riesgo/real")
def riesgo_real(rf: Optional[float] = None) -> dict:
    curva_ = _curva_o_error()
    ccl_hist, _, _ = _macro()
    try:
        return riesgo.cartera_real(curva_, ccl_hist, rf)
    except PerformanceError as e:
        raise HTTPException(500, str(e))


@app.get("/api/riesgo/stress")
def riesgo_stress() -> dict:
    base = _base()
    try:
        return cacheado("riesgo:stress", 3600, lambda: riesgo.stress(base["holdings"], base["config"], base["ccl"]))
    except Exception as e:  # red caida en la primera descarga, etc.
        raise HTTPException(500, f"No se pudo correr el stress test: {e}")


@app.get("/api/riesgo/composicion")
def riesgo_composicion() -> dict:
    base = _base()
    valores = riesgo.valores_actuales(base["holdings"])
    tickers = tuple(sorted(valores.index))
    perfiles = cacheado("perfiles:" + ",".join(tickers), 24 * 3600, lambda: obtener_perfiles(list(tickers), base["config"]))
    try:
        curva_ = _curva()
    except HistoricalCurveError:
        curva_ = None
    return riesgo.composicion(base["holdings"], base["config"], curva_, perfiles)


@app.get("/api/riesgo/objetivo")
def riesgo_objetivo() -> dict:
    config = _config()
    try:
        a = cacheado("analitica", 3600, lambda: calcular_analitica_riesgo(config))
    except AnalyticsError as e:
        raise HTTPException(500, f"No se pudo calcular la analítica de riesgo: {e}")
    return riesgo.objetivo(a)


# ---------------------------------------------------------------------------
# Aportes y dividendos (ver aportes.py)
# ---------------------------------------------------------------------------
@app.get("/api/aportes")
def aportes_y_dividendos() -> dict:
    movimientos = _movimientos()
    ccl_hist, _, _ = _macro()
    try:
        curva_ = _curva()
    except HistoricalCurveError:
        curva_ = None
    out: dict = {}
    try:
        out["aportes"] = aportes_mod.aportes(movimientos, ccl_hist)
    except PerformanceError as e:
        out["aportes"] = {"error": str(e)}
    capital = float(curva_.capital_invertido_ars.iloc[-1]) if curva_ is not None else None
    try:
        out["dividendos"] = aportes_mod.dividendos(movimientos, ccl_hist, capital)
    except PerformanceError as e:
        out["dividendos"] = {"error": str(e)}
    out["tickers_operados"] = aportes_mod.tickers_operados(movimientos, curva_)
    return out


@app.get("/api/aportes/compras")
def aportes_compras(ticker: str, unidad: str = "ars") -> dict:
    curva_ = _curva_o_error()
    if curva_.precios_diarios is None or ticker not in curva_.precios_diarios.columns:
        raise HTTPException(404, f"No hay precio histórico para {ticker}.")
    ccl_hist, _, _ = _macro()
    return aportes_mod.compras(_movimientos(), curva_, ccl_hist, ticker, unidad)


# ---------------------------------------------------------------------------
# Metas (ver metas_diario.py)
# ---------------------------------------------------------------------------
@app.get("/api/metas")
def metas_get() -> dict:
    base = _base()
    ccl_hist, _, _ = _macro()
    try:
        curva_ = _curva()
    except HistoricalCurveError:
        curva_ = None
    m = cargar_metas()
    return {
        "valor_usd": md.valor_total_usd(base["holdings"], base["ccl"]),
        "meta_usd": m.get("meta_usd"),
        "fecha_objetivo": m.get("fecha_objetivo"),
        "aporte_mensual_usd": m.get("aporte_mensual_usd"),
        "escenario": m.get("escenario"),
        "horizonte_anios": m.get("horizonte_anios"),
        "escenarios": ESCENARIOS,
        "defaults": cacheado("metas:defaults", 3600, lambda: md.defaults_proyeccion(_movimientos(), curva_, ccl_hist)),
    }


class MetaIn(BaseModel):
    meta_usd: Optional[float] = Field(default=None, ge=0)
    fecha_objetivo: Optional[str] = None


@app.put("/api/metas/meta")
def metas_guardar_meta(x: MetaIn) -> dict:
    m = cargar_metas()
    m["meta_usd"] = int(x.meta_usd) if x.meta_usd else None
    m["fecha_objetivo"] = x.fecha_objetivo or None
    guardar_metas(m)
    return {"ok": True}


class ProyeccionIn(BaseModel):
    aporte: float = Field(ge=0)
    escenario: str
    volatilidad: float = Field(ge=0, le=0.8)
    anios: int = Field(ge=1, le=40)


@app.post("/api/metas/proyeccion")
def metas_proyeccion(x: ProyeccionIn) -> dict:
    if x.escenario not in ESCENARIOS:
        raise HTTPException(400, f"Escenario desconocido: {x.escenario}")
    base = _base()
    valor = md.valor_total_usd(base["holdings"], base["ccl"])
    if valor is None:
        raise HTTPException(400, "Hace falta el dólar CCL para medir la meta en dólares.")
    m = cargar_metas()
    meta = float(m["meta_usd"]) if m.get("meta_usd") else None
    return md.proyeccion(valor, x.aporte, x.escenario, x.volatilidad, x.anios, meta, m.get("fecha_objetivo"))


@app.put("/api/metas/parametros")
def metas_guardar_parametros(x: ProyeccionIn) -> dict:
    m = cargar_metas()
    m.update({"aporte_mensual_usd": int(x.aporte), "escenario": x.escenario, "horizonte_anios": int(x.anios)})
    guardar_metas(m)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Transicion y diario (ver metas_diario.py)
# ---------------------------------------------------------------------------
@app.get("/api/transicion/opciones")
def transicion_opciones() -> dict:
    base = _base()
    return md.opciones_transicion(base["holdings"], base["config"])


class TransicionIn(BaseModel):
    vender: list[str] = []
    monto: float = Field(default=0, ge=0)
    sobreponderados: bool = False


@app.post("/api/transicion")
def transicion_calcular(x: TransicionIn) -> dict:
    base = _base()
    try:
        return md.transicion(base["holdings"], base["config"], base["ccl"], x.vender, x.monto, x.sobreponderados)
    except RebalancerError as e:
        raise HTTPException(400, str(e))


_precios_sueltos: dict = {}


@app.get("/api/diario")
def diario_get() -> dict:
    base = _base()
    try:
        entradas = cargar_diario()
    except DiarioError as e:
        raise HTTPException(500, str(e))
    precios = md.precios_hoy(base["holdings"], base["ccl"], {e["ticker"] for e in entradas} | {REFERENCIA}, _precios_sueltos)
    out = md.diario(entradas, precios, base["ccl"])
    out["acciones"] = ACCIONES
    out["opciones"] = sorted((set(base["holdings"]["Ticker"]) - {"CASH"}) | set(base["config"].get("activos", {})))
    return out


class DecisionIn(BaseModel):
    ticker: str
    accion: str
    motivo: str = ""
    horizonte_meses: int = Field(default=6, ge=1, le=120)


@app.post("/api/diario")
def diario_agregar(x: DecisionIn) -> dict:
    base = _base()
    tk = x.ticker.strip().upper()
    precios = md.precios_hoy(base["holdings"], base["ccl"], [tk, REFERENCIA], _precios_sueltos)
    try:
        entradas = cargar_diario()
        entradas.append(nueva_entrada(tk, x.accion, x.motivo, precios.get(tk), precios.get(REFERENCIA), base["ccl"], x.horizonte_meses))
        guardar_diario(entradas)
    except DiarioError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.delete("/api/diario/{id_entrada}")
def diario_borrar(id_entrada: str) -> dict:
    try:
        guardar_diario(eliminar_entrada(cargar_diario(), id_entrada))
    except DiarioError as e:
        raise HTTPException(500, str(e))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Diseno de la app de escritorio: tema activo + temas personalizados.
# Se guarda tal cual lo manda la UI (es solo presentacion, no toca core/).
# ---------------------------------------------------------------------------
DISENO_PATH = CONFIG_DIR / "diseno_escritorio.json"


@app.get("/api/diseno")
def diseno_get() -> dict:
    try:
        datos = json.loads(DISENO_PATH.read_text(encoding="utf-8"))
        if isinstance(datos, dict):
            return {"activo": datos.get("activo"), "personalizados": datos.get("personalizados") or []}
    except (OSError, ValueError):
        pass
    return {"activo": None, "personalizados": []}


class DisenoIn(BaseModel):
    activo: Optional[str] = None
    personalizados: list[dict] = []


@app.put("/api/diseno")
def diseno_guardar(x: DisenoIn) -> dict:
    DISENO_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DISENO_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps({"activo": x.activo, "personalizados": x.personalizados}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DISENO_PATH)
    return {"ok": True}


def _vigilar_app(pid: int) -> None:
    """Si la app de escritorio que nos lanzo se cierra por cualquier motivo
    (incluso un cierre forzado o un crash), este proceso termina con ella."""
    if sys.platform != "win32":
        return
    import ctypes
    import os

    SYNCHRONIZE, INFINITE = 0x00100000, 0xFFFFFFFF
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(SYNCHRONIZE, False, pid)
    if not h:
        os._exit(0)  # la app ya no existe
    k32.WaitForSingleObject(h, INFINITE)
    os._exit(0)


if __name__ == "__main__":
    import os

    MOVIMIENTOS_DIR.mkdir(parents=True, exist_ok=True)
    if os.environ.get("FP_PARENT_PID", "").isdigit():
        threading.Thread(target=_vigilar_app, args=(int(os.environ["FP_PARENT_PID"]),), daemon=True).start()
    threading.Thread(target=_precalentar, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PUERTO, log_level="warning")
