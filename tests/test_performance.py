"""
tests/test_performance.py

Fija la matematica de core/performance.py (v10.0) con casos armados a
mano cuyo resultado se puede verificar "con lapiz y papel". Sin red.
"""

import math

import numpy as np
import pandas as pd
import pytest

from core.performance import (
    PerformanceError,
    analisis_timing,
    concentracion,
    contribucion_al_riesgo,
    contribucion_por_activo,
    estadisticas_drawdown,
    historial_aportes,
    historial_dividendos,
    indice_desde_rendimientos,
    metricas_riesgo,
    operaciones_de_ticker,
    proyeccion_montecarlo,
    rendimiento_por_categoria,
    rendimientos_mensuales,
    resumen_rendimiento,
    serie_drawdown,
    xirr,
)


def _rango(n, inicio="2024-01-01"):
    return pd.date_range(inicio, periods=n, freq="D")


# ---------------------------------------------------------------- TWR / TIR
def test_twr_neutraliza_aportes():
    # Dia 0: aporto 100, vale 100. Dia 1: sube 10% -> 110.
    # Dia 2: aporto 890 (total 1000 antes de mercado), sube 10% -> 1100.
    # TWR = 1.1 * 1.1 - 1 = 21% aunque la mayoria de la plata solo vio una suba.
    idx = _rango(3)
    valor = pd.Series([100.0, 110.0, 1100.0], index=idx)
    capital = pd.Series([100.0, 100.0, 990.0], index=idx)
    r = resumen_rendimiento(valor, capital)
    assert r.twr_total == pytest.approx(0.21, abs=1e-9)
    assert r.ganancia == pytest.approx(1100 - 990)
    assert r.aportado_neto == pytest.approx(990)


def test_xirr_un_anio_exacto():
    fechas = pd.DatetimeIndex(["2023-01-01", "2024-01-01"])
    tasa = xirr(fechas, np.array([-100.0, 110.0]))
    # 365 dias / 365.25 -> casi exactamente 10%
    assert tasa == pytest.approx(0.10, abs=2e-4)


def test_xirr_sin_cambio_de_signo_devuelve_none():
    assert xirr(pd.DatetimeIndex(["2023-01-01", "2024-01-01"]), np.array([-100.0, -5.0])) is None


def test_resumen_en_otra_unidad_usa_el_factor_de_cada_dia():
    # En USD: el activo no se mueve en dolares; el peso se devalua 2x.
    idx = _rango(2)
    ccl = pd.Series([100.0, 200.0], index=idx)
    valor_ars = pd.Series([1000.0, 2000.0], index=idx)  # 10 USD -> 10 USD
    capital = pd.Series([1000.0, 1000.0], index=idx)
    ars = resumen_rendimiento(valor_ars, capital)
    usd = resumen_rendimiento(valor_ars, capital, factor=ccl, unidad="USD")
    assert ars.twr_total == pytest.approx(1.0)
    assert usd.twr_total == pytest.approx(0.0)
    assert usd.ganancia == pytest.approx(0.0)


def test_dias_sin_cartera_rinden_cero():
    idx = _rango(3)
    valor = pd.Series([0.0, 0.0, 100.0], index=idx)
    capital = pd.Series([0.0, 0.0, 100.0], index=idx)
    r = resumen_rendimiento(valor, capital)
    assert r.twr_total == pytest.approx(0.0)


# ---------------------------------------------------------------- Mensual
def test_rendimientos_mensuales_compone_dentro_del_mes_y_del_anio():
    idx = pd.date_range("2024-01-01", "2024-02-29", freq="D")
    r = pd.Series(0.0, index=idx)
    r.loc["2024-01-15"] = 0.10
    r.loc["2024-02-10"] = -0.10
    tabla = rendimientos_mensuales(indice_desde_rendimientos(r))
    assert tabla.loc[2024, "Ene"] == pytest.approx(10.0)
    assert tabla.loc[2024, "Feb"] == pytest.approx(-10.0)
    assert tabla.loc[2024, "Anio"] == pytest.approx((1.1 * 0.9 - 1) * 100)


def test_rendimientos_mensuales_incluye_el_primer_mes_parcial():
    # La serie arranca a mitad de mes: ese primer mes (parcial) tiene que
    # aparecer, y el producto de todos los meses = rendimiento total.
    idx = pd.date_range("2024-07-07", "2024-09-30", freq="D")
    r = pd.Series(0.0, index=idx)
    r.loc["2024-07-07"] = 0.05  # el primer dia ya rinde
    r.loc["2024-07-20"] = 0.02
    r.loc["2024-08-15"] = -0.10
    r.loc["2024-09-03"] = 0.04
    indice = indice_desde_rendimientos(r)
    tabla = rendimientos_mensuales(indice)
    assert tabla.loc[2024, "Jul"] == pytest.approx((1.05 * 1.02 - 1) * 100)
    assert tabla.loc[2024, "Ago"] == pytest.approx(-10.0)
    assert tabla.loc[2024, "Anio"] == pytest.approx((indice.iloc[-1] - 1) * 100)


# ---------------------------------------------------------------- Contribucion
def _cartera_dos_activos():
    idx = _rango(3)
    inventario = pd.DataFrame({"A": [1.0, 1.0, 1.0], "B": [2.0, 2.0, 0.0]}, index=idx)
    precios = pd.DataFrame({"A": [100.0, 120.0, 150.0], "B": [50.0, 40.0, 45.0]}, index=idx)
    # A: compro a 100. B: compro 2 a 50, vendo 2 a 45 el ultimo dia.
    capital = pd.DataFrame({"A": [100.0, 100.0, 100.0], "B": [100.0, 100.0, 10.0]}, index=idx)
    return inventario, precios, capital


def test_contribucion_suma_la_ganancia_total():
    inv, px, cap = _cartera_dos_activos()
    cash = pd.Series([0.0, 0.0, 5.0], index=inv.index)
    df = contribucion_por_activo(inv, px, cap, cash).set_index("Ticker")
    assert df.loc["A", "Contribucion"] == pytest.approx(50.0)
    assert df.loc["B", "Contribucion"] == pytest.approx(-10.0)
    assert df.loc["B", "Estado"] == "Vendido"
    assert df.loc["Dividendos", "Contribucion"] == pytest.approx(5.0)
    valor_total = (inv * px).sum(axis=1) + cash
    assert df["Contribucion"].sum() == pytest.approx(valor_total.iloc[-1] - cap.sum(axis=1).iloc[-1])


def test_contribucion_desde_una_fecha():
    inv, px, cap = _cartera_dos_activos()
    df = contribucion_por_activo(inv, px, cap, desde=inv.index[2]).set_index("Ticker")
    # A del dia 1 al 2: 120 -> 150
    assert df.loc["A", "Contribucion"] == pytest.approx(30.0)


def test_rendimiento_por_categoria_separa_subcarteras():
    inv, px, cap = _cartera_dos_activos()
    res = rendimiento_por_categoria(inv, px, cap, {"A": "Core"})
    assert set(res) == {"Core", "Fuera de objetivo"}
    assert res["Core"].twr_total == pytest.approx(0.5)


# ---------------------------------------------------------------- Drawdown
def test_drawdown_y_recuperacion():
    idx = _rango(5)
    indice = pd.Series([1.0, 1.2, 0.9, 1.1, 1.3], index=idx)
    dd = serie_drawdown(indice)
    assert dd.min() == pytest.approx(-25.0)
    est = estadisticas_drawdown(indice)
    assert est.fecha_pico == idx[1] and est.fecha_valle == idx[2]
    assert est.fecha_recuperacion == idx[4]
    assert est.drawdown_actual == pytest.approx(0.0)


def test_drawdown_sin_recuperar():
    indice = pd.Series([1.0, 0.8, 0.9], index=_rango(3))
    assert estadisticas_drawdown(indice).fecha_recuperacion is None


def test_drawdown_cuenta_la_caida_desde_el_capital_inicial():
    # v10.1: el indice arranca en 1 + r del primer dia; si ya cae ese dia,
    # la caida se mide desde 1.0 (lo que pusiste), no desde 0.9.
    idx = _rango(3)
    indice = pd.Series([0.9, 0.8, 1.05], index=idx)
    assert serie_drawdown(indice).min() == pytest.approx(-20.0)
    est = estadisticas_drawdown(indice)
    assert est.max_drawdown == pytest.approx(-20.0)
    assert est.fecha_recuperacion == idx[2]


def test_volatilidad_se_anualiza_con_la_frecuencia_real():
    # Serie de lunes a viernes (~261 ruedas/anio): la vol anual tiene que
    # usar esa frecuencia, no 252.
    idx = pd.bdate_range("2024-01-01", periods=300)
    rng = np.random.default_rng(3)
    r = rng.normal(0, 0.01, len(idx))
    indice = pd.Series(np.cumprod(1 + r), index=idx)
    m = metricas_riesgo(indice)
    rd = indice.pct_change().dropna()
    ppa = (len(idx) - 1) / ((idx[-1] - idx[0]).days / 365.25)
    assert 255 < ppa < 265
    assert m.volatilidad_anual == pytest.approx(rd.std(ddof=1) * math.sqrt(ppa))


# ---------------------------------------------------------------- Riesgo
def test_beta_de_una_cartera_apalancada_2x():
    idx = pd.bdate_range("2024-01-01", periods=120)
    rng = np.random.default_rng(0)
    rb = rng.normal(0, 0.01, len(idx))
    bench = pd.Series(np.cumprod(1 + rb), index=idx)
    cartera = pd.Series(np.cumprod(1 + 2 * rb), index=idx)
    m = metricas_riesgo(cartera, bench, 0.0)
    assert m.beta == pytest.approx(2.0, rel=1e-6)
    assert m.correlacion == pytest.approx(1.0, rel=1e-6)
    assert m.volatilidad_anual > 0


def test_riesgo_requiere_historia_minima():
    with pytest.raises(PerformanceError):
        metricas_riesgo(pd.Series([1.0, 1.01, 1.02], index=pd.bdate_range("2024-01-01", periods=3)))


def test_concentracion():
    c = concentracion(pd.Series({"A": 50.0, "B": 50.0, "C": 0.0}))
    assert c.n_efectivo == pytest.approx(2.0)
    assert c.hhi == pytest.approx(5000.0)
    assert c.top1_pct == pytest.approx(50.0)


def test_contribucion_al_riesgo_suma_100_y_activo_sin_vol_aporta_cero():
    idx = pd.bdate_range("2024-01-01", periods=80)
    rng = np.random.default_rng(1)
    precios = pd.DataFrame(
        {
            "VOL": np.cumprod(1 + rng.normal(0, 0.02, len(idx))),
            "QUIETO": np.ones(len(idx)),
            "MEDIO": np.cumprod(1 + rng.normal(0, 0.01, len(idx))),
        },
        index=idx,
    )
    df = contribucion_al_riesgo(precios, pd.Series({"VOL": 1, "QUIETO": 1, "MEDIO": 1})).set_index("Ticker")
    assert df["Contribucion al riesgo %"].sum() == pytest.approx(100.0)
    assert df.loc["QUIETO", "Contribucion al riesgo %"] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------- Aportes / dividendos
def _movs(filas):
    base = {
        "tipoOperacion": "",
        "instrumento": "",
        "ticker": None,
        "moneda": "ARS",
        "cantidad": np.nan,
        "precio": np.nan,
        "montoBruto": np.nan,
        "total": np.nan,
    }
    return pd.DataFrame([{**base, **f} for f in filas])


def test_historial_aportes_netea_retiros_y_convierte_a_usd():
    hoy = pd.Timestamp.today().normalize()
    m1 = (hoy - pd.DateOffset(months=2)).normalize()
    movs = _movs(
        [
            {"fechaEjecucion": m1, "tipo_operacion_norm": "INGRESO_CASH", "total": 1000.0},
            {"fechaEjecucion": m1, "tipo_operacion_norm": "EGRESO_CASH", "total": -200.0},
            {"fechaEjecucion": m1 + pd.DateOffset(months=1), "tipo_operacion_norm": "INGRESO_CASH", "total": 500.0},
        ]
    )
    ccl = pd.Series([100.0], index=[m1 - pd.Timedelta(days=10)])
    h = historial_aportes(movs, ccl=ccl)
    assert h.neto == pytest.approx(1300.0)
    assert h.neto_usd == pytest.approx(13.0)
    assert h.racha_actual == 2  # el mes en curso sin aporte no corta la racha


def test_dividendos_en_dolares_usan_la_cantidad_y_descuentan_la_retencion():
    f = pd.Timestamp.today().normalize() - pd.Timedelta(days=5)
    movs = _movs(
        [
            {"fechaEjecucion": f, "tipo_operacion_norm": "DIVIDENDO", "total": 60.0},
            {
                "fechaEjecucion": f,
                "tipo_operacion_norm": "DIVIDENDO_ESPECIE",
                "tipoOperacion": "DIVIDENDOS EN ESPECIE",
                "instrumento": "Dólar estadounidense",
                "cantidad": 2.0,
                "total": -10.0,
            },
        ]
    )
    ccl = pd.Series([1000.0], index=[f - pd.Timedelta(days=30)])
    d = historial_dividendos(movs, ccl)
    assert d.total_ars == pytest.approx(60.0 + 2.0 * 1000.0 - 10.0)
    assert d.ultimos_12m_ars == pytest.approx(d.total_ars)


# ---------------------------------------------------------------- Timing
def test_analisis_timing():
    idx = pd.bdate_range("2024-01-01", periods=10)
    precios = pd.Series([100, 90, 80, 90, 100, 110, 120, 110, 100, 100], index=idx, dtype=float)
    movs = pd.DataFrame(
        {
            "ticker": ["X", "X"],
            "tipo_operacion_norm": ["COMPRA", "COMPRA"],
            "fechaEjecucion": [idx[0], idx[2]],
            "cantidad": [1.0, 1.0],
            "precio": [100.0, 80.0],
            "total": [-100.0, -80.0],
        }
    )
    ops = operaciones_de_ticker(movs, "X")
    t = analisis_timing(precios, ops)
    assert t.precio_promedio_compra == pytest.approx(90.0)
    # v10.1: ventana = de la primera a la ultima compra (100, 90, 80)
    assert t.precio_promedio_periodo == pytest.approx(90.0)
    # DCA de monto fijo en esa ventana paga la media armonica (~89,26)
    armonica = 3 / (1 / 100 + 1 / 90 + 1 / 80)
    assert t.precio_referencia_dca == pytest.approx(armonica)
    # comprar 1 nominal por vez (monto variable) quedo apenas PEOR que el
    # DCA mecanico, aunque este "justo en el promedio simple": antes este
    # caso se mostraba como neutro/favorable
    assert t.ventaja_pct > 0


def test_analisis_timing_dca_puro_no_muestra_ventaja_ficticia():
    # Comprar el MISMO monto en cada rueda de la ventana es exactamente el
    # DCA de referencia: la ventaja tiene que dar 0, no "a tu favor".
    idx = pd.bdate_range("2024-01-01", periods=4)
    precios = pd.Series([100.0, 50.0, 100.0, 50.0], index=idx)
    movs = pd.DataFrame(
        {
            "ticker": ["X"] * 4,
            "tipo_operacion_norm": ["COMPRA"] * 4,
            "fechaEjecucion": list(idx),
            "cantidad": [1000.0 / p for p in precios],
            "precio": list(precios),
            "total": [-1000.0] * 4,
        }
    )
    t = analisis_timing(precios, operaciones_de_ticker(movs, "X"))
    assert t.ventaja_pct == pytest.approx(0.0, abs=1e-9)
    assert t.precio_promedio_compra < t.precio_promedio_periodo  # la "ventaja" vieja era pura matematica


# ---------------------------------------------------------------- Proyeccion
def test_proyeccion_sin_volatilidad_es_determinista():
    p = proyeccion_montecarlo(1000, 100, 0.0, 0.0, 1, meta=3000, simulaciones=50)
    assert p.percentiles["p50"].iloc[-1] == pytest.approx(1000 + 12 * 100)
    assert p.prob_meta == pytest.approx(0.0)
    p2 = proyeccion_montecarlo(1000, 100, 0.12, 0.0, 1, simulaciones=10)
    esperado = 1000.0
    for _ in range(12):
        esperado = esperado * math.exp(math.log(1.12) / 12) + 100
    assert p2.sin_volatilidad.iloc[-1] == pytest.approx(esperado)


def test_proyeccion_es_reproducible():
    a = proyeccion_montecarlo(1000, 100, 0.07, 0.2, 5)
    b = proyeccion_montecarlo(1000, 100, 0.07, 0.2, 5)
    pd.testing.assert_frame_equal(a.percentiles, b.percentiles)


# ---------------------------------------------------------------- Saneamiento de precios (historical_curve)
def test_sanear_precios_corrige_escala_y_completa_huecos(monkeypatch):
    import core.historical_curve as hc

    monkeypatch.setattr(hc, "_precio_sintetico_desde_subyacente", lambda *a, **k: None)
    rango = pd.date_range("2024-01-01", periods=10, freq="D")
    precios = pd.DataFrame(
        {
            "ESC": [10.0] * 10,  # yfinance "dividido por 10"
            "HUECO": [np.nan] * 5 + [200.0] * 5,  # yfinance recien desde el dia 5
        },
        index=rango,
    )
    ops = pd.DataFrame(
        {
            "ticker": ["ESC", "HUECO"],
            "fechaEjecucion": [rango[1], rango[0]],
            "precio": [100.0, 100.0],
            "total": [-100.0, -100.0],
        }
    )
    inventario = pd.DataFrame({"ESC": 1.0, "HUECO": 1.0}, index=rango)
    avisos = []
    out = hc._sanear_precios(precios, ops, inventario, rango, avisos)
    assert out["ESC"].iloc[0] == pytest.approx(100.0)
    assert out["HUECO"].iloc[0] == pytest.approx(100.0)  # precio de tu operacion
    assert out["HUECO"].iloc[5] == pytest.approx(200.0)  # dato real de yfinance intacto
    assert 100.0 < out["HUECO"].iloc[3] < 200.0  # interpolado
    assert len(avisos) == 2


# ---------------------------------------------------------------- v10.1: contribucion al riesgo con historia corta
def test_contribucion_al_riesgo_no_diluye_activos_nuevos_con_ceros():
    idx = pd.bdate_range("2024-01-01", periods=120)
    rng = np.random.default_rng(7)
    precios = pd.DataFrame(
        {
            "A": np.cumprod(1 + rng.normal(0, 0.01, len(idx))),
            "B": np.cumprod(1 + rng.normal(0, 0.01, len(idx))),
            # muy volatil, pero recien comprado: solo 40 ruedas de historia
            "NUEVO": [np.nan] * 80 + list(np.cumprod(1 + rng.normal(0, 0.04, 40))),
            # casi sin historia: tiene que quedar afuera e informado
            "RECIEN": [np.nan] * 110 + list(np.cumprod(1 + rng.normal(0, 0.02, 10))),
        },
        index=idx,
    )
    pesos = pd.Series({"A": 1, "B": 1, "NUEVO": 1, "RECIEN": 1})
    df = contribucion_al_riesgo(precios, pesos).set_index("Ticker")
    assert df.attrs["excluidos_poca_historia"] == ["RECIEN"]
    assert "RECIEN" not in df.index
    assert df["Contribucion al riesgo %"].sum() == pytest.approx(100.0)
    # con relleno de ceros su vol anual se veia ~0.6x de la real (40/120 ruedas);
    # ahora refleja la volatilidad diaria real (~4% diario ~ 60%+ anual)
    assert df.loc["NUEVO", "Volatilidad anual %"] > 45


# ---------------------------------------------------------------- v10.2: ¿le ganas al indice?
def test_comparacion_vs_benchmark_consistente_y_ventanas():
    from core.performance import comparacion_vs_benchmark

    idx = pd.date_range("2024-01-01", periods=500, freq="D")
    bench = pd.Series(np.linspace(1.0, 1.5, len(idx)), index=idx)
    igual = comparacion_vs_benchmark(bench.copy(), bench, "B")
    assert igual.exceso_total == pytest.approx(0.0)
    assert igual.exceso_6m == pytest.approx(0.0, abs=1e-12)
    assert igual.pct_ventanas_ganadas == pytest.approx(0.0)  # empatar no es ganar

    # cartera que rinde siempre 0,05% diario mas que el benchmark: gana en todas las ventanas
    mejor = bench * np.cumprod(np.full(len(idx), 1.0005))
    c = comparacion_vs_benchmark(mejor, bench, "B")
    assert c.exceso_total > 0 and c.exceso_6m > 0 and c.exceso_12m > 0
    assert c.pct_ventanas_ganadas == pytest.approx(100.0)
    assert c.serie_exceso_6m.index[0] >= idx[0] + pd.Timedelta(days=182)


def test_comparacion_sin_historia_para_12_meses():
    from core.performance import comparacion_vs_benchmark

    idx = pd.date_range("2024-01-01", periods=200, freq="D")
    s = pd.Series(np.linspace(1.0, 1.1, len(idx)), index=idx)
    c = comparacion_vs_benchmark(s, s, "B")
    assert c.exceso_12m is None
    assert c.exceso_6m is not None


# ---------------------------------------------------------------- v10.2: TIR de toda la cuenta
def test_tir_cuenta_con_deposito_retiro_en_dolares_y_ccl():
    from core.performance import flujos_cuenta, tir_cuenta

    d0 = pd.Timestamp("2024-01-01")
    movs = _movs(
        [
            {"fechaEjecucion": d0, "tipo_operacion_norm": "INGRESO_CASH", "tipoOperacion": "Recibo De Cobro",
             "total": 100000.0},
            # compra interna: NO es un flujo de la cuenta
            {"fechaEjecucion": d0, "tipo_operacion_norm": "COMPRA", "tipoOperacion": "Compra", "total": -90000.0},
            # retiro de 10 USD (sale plata de la cuenta)
            {"fechaEjecucion": d0 + pd.Timedelta(days=100), "tipo_operacion_norm": "OTRO",
             "tipoOperacion": "Orden De Pago Usd", "moneda": "USD", "total": -10.0},
        ]
    )
    ccl = pd.Series([1000.0, 1000.0], index=[d0 - pd.Timedelta(days=5), d0 + pd.Timedelta(days=400)])
    fl = flujos_cuenta(movs, ccl)
    assert list(fl["monto_ars"]) == [100000.0, -10000.0]
    assert list(fl["moneda"]) == ["ARS", "USD"]

    r = tir_cuenta(movs, valor_total_ars=99000.0, ccl=ccl, fecha_valor=d0 + pd.Timedelta(days=365))
    assert r.aportado_neto_ars == pytest.approx(90000.0)
    assert r.aportado_neto_usd == pytest.approx(90.0)
    assert r.ganancia_usd == pytest.approx(9.0)
    # con CCL constante, la TIR en pesos y en dolares coinciden
    assert r.tir_anual_usd == pytest.approx(r.tir_anual_ars, abs=1e-6)
    assert 0.09 < r.tir_anual_ars < 0.12


def test_flujos_en_dolares_sin_ccl_avisan():
    from core.performance import flujos_cuenta

    movs = _movs([{"fechaEjecucion": pd.Timestamp("2024-01-01"), "tipo_operacion_norm": "OTRO",
                   "tipoOperacion": "Orden De Pago Usd", "moneda": "USD", "total": -10.0}])
    with pytest.raises(PerformanceError):
        flujos_cuenta(movs, None)
