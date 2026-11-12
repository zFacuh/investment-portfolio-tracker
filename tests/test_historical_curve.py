"""
tests/test_historical_curve.py

Fija el filtro de "Universo Cerrado" (v6.2) de
core.historical_curve.calcular_curva_historica: un ticker sin precio
historico en yfinance (tipicamente un bono, ej. AL30/GD38 -- ver el
docstring del modulo) tiene que quedar excluido de LAS DOS series
(Valor de Mercado y Capital Invertido), no solo de una -- si quedara
adentro de Capital Invertido pero afuera de Valor de Mercado, se
inflaria una "perdida" que es un agujero de datos, no una perdida real.
Tambien cubre la CUARTA serie opcional (v7.x, comparacion contra
benchmark): que reutilice el mismo flujo de caja ya filtrado por
Universo Cerrado, y que un benchmark sin precio no bloquee la curva
real.

No pega a la red: se monkeypatchea `_descargar_precios_ba` (el unico
punto del modulo que llama a yfinance) para devolver una respuesta
determinista.
"""

import pandas as pd
import pytest

import core.historical_curve as historical_curve
from core.historical_curve import calcular_curva_historica


def _movimiento(ticker: str, fecha: pd.Timestamp, cantidad: float, total: float) -> dict:
    return {
        "tipo_operacion_norm": "COMPRA",
        "ticker": ticker,
        "fechaEjecucion": fecha,
        "cantidad": cantidad,
        "total": total,
    }


def test_universo_cerrado_excluye_ticker_sin_precio_de_ambas_series(monkeypatch):
    fecha = pd.Timestamp("2024-01-01")
    movimientos = pd.DataFrame(
        [
            # AAA: CEDEAR normal, SI tiene precio en yfinance (mockeado abajo).
            _movimiento("AAA", fecha, cantidad=10.0, total=-1000.0),
            # BBB: simula un bono (ej. AL30/GD38) que NO cotiza en yfinance
            # bajo la convencion ".BA" -- nunca va a aparecer en `precios`.
            _movimiento("BBB", fecha, cantidad=5.0, total=-500.0),
        ]
    )

    def fake_descargar_precios_ba(tickers, fecha_inicio):
        precios = pd.DataFrame({"AAA": [100.0]}, index=[fecha_inicio])
        tickers_sin_datos = [t for t in tickers if t != "AAA"]
        return precios, tickers_sin_datos

    monkeypatch.setattr(historical_curve, "_descargar_precios_ba", fake_descargar_precios_ba)

    resultado = calcular_curva_historica(movimientos)

    assert resultado.tickers_incluidos == ["AAA"]
    assert resultado.tickers_sin_datos == ["BBB"]

    # Valor de Mercado: 10 nominales de AAA a $100 = 1000 ARS, constante
    # (no hay mas operaciones despues del dia de la compra).
    assert resultado.valor_ars.iloc[-1] == pytest.approx(1000.0)

    # Capital Invertido: TIENE que dar 1000 (solo el gasto de AAA), no
    # 1500. Si el filtro de Universo Cerrado no excluyera a BBB de esta
    # serie, el gasto de BBB ($500) quedaria sumado igual, aunque su
    # Valor de Mercado es $0 por no tener precio -- exactamente el bug
    # que corrige v6.2 (ver el docstring del modulo).
    assert resultado.capital_invertido_ars.iloc[-1] == pytest.approx(1000.0)

    # Ambas series comparten siempre el mismo indice de fechas.
    assert resultado.valor_ars.index.equals(resultado.capital_invertido_ars.index)


def test_sin_operaciones_compra_venta_lanza_error(monkeypatch):
    """Un CSV sin ninguna Compra/Venta (ej. solo dividendos o cash) no
    tiene de que reconstruir una curva -- HistoricalCurveError, no un
    DataFrame vacio silencioso."""
    movimientos = pd.DataFrame(
        [
            {
                "tipo_operacion_norm": "DIVIDENDO",
                "ticker": None,
                "fechaEjecucion": pd.Timestamp("2024-01-01"),
                "cantidad": None,
                "total": 100.0,
            }
        ]
    )
    with pytest.raises(historical_curve.HistoricalCurveError):
        calcular_curva_historica(movimientos)


def test_benchmark_reutiliza_flujo_de_capital_invertido_y_universo_cerrado(monkeypatch):
    """
    Cada benchmark (v7.x) tiene que simular exactamente el mismo flujo
    de caja que ya usa Capital Invertido (post Universo Cerrado -- BBB,
    sin precio, no aporta nada a ningun benchmark), invertido en el
    benchmark en vez de la cartera real. Si el benchmark se duplica de
    precio, la posicion simulada tiene que duplicarse tambien -- aunque
    el Valor de Mercado real (AAA a precio constante) no se mueva un
    peso, probando que son series genuinamente independientes.
    """
    fecha = pd.Timestamp("2024-01-01")
    fecha_duplicado = fecha + pd.Timedelta(days=10)
    movimientos = pd.DataFrame(
        [
            _movimiento("AAA", fecha, cantidad=10.0, total=-1000.0),
            _movimiento("BBB", fecha, cantidad=5.0, total=-500.0),  # bono sin precio (Universo Cerrado)
        ]
    )

    def fake_descargar_precios_ba(tickers, fecha_inicio):
        precios = pd.DataFrame(
            {
                "AAA": [100.0, 100.0],  # precio constante: Valor de Mercado no se mueve
                "BENCH": [50.0, 100.0],  # el benchmark se DUPLICA de precio
            },
            index=[fecha_inicio, fecha_duplicado],
        )
        tickers_sin_datos = [t for t in tickers if t not in ("AAA", "BENCH")]
        return precios, tickers_sin_datos

    monkeypatch.setattr(historical_curve, "_descargar_precios_ba", fake_descargar_precios_ba)

    resultado = calcular_curva_historica(movimientos, benchmarks=[{"ticker": "bench", "label": "Bench"}])

    assert list(resultado.valores_benchmark.keys()) == ["Bench"]
    serie_benchmark = resultado.valores_benchmark["Bench"]
    assert serie_benchmark.index.equals(resultado.valor_ars.index)

    # Capital Invertido = 1000 (solo AAA; BBB excluido por Universo
    # Cerrado, ver el otro test) -- son los mismos $1000 que "se
    # hubieran" puesto en el benchmark en la fecha de la compra real.
    assert resultado.capital_invertido_ars.iloc[-1] == pytest.approx(1000.0)

    # El benchmark se duplico (50 -> 100): la posicion simulada de
    # $1000 tiene que valer $2000 al final.
    assert serie_benchmark.iloc[-1] == pytest.approx(2000.0)

    # El Valor de Mercado REAL no se movio (AAA a precio constante) --
    # confirma que el benchmark es una serie genuinamente independiente,
    # no una copia disfrazada de otra.
    assert resultado.valor_ars.iloc[-1] == pytest.approx(1000.0)


def test_benchmarks_multiples_uno_falla_no_bloquea_a_los_demas(monkeypatch):
    """
    Con varios benchmarks pedidos a la vez (ej. SPY, QQQ, BTC via IBIT),
    uno sin historico disponible NO debe bloquear ni a la curva real ni
    a los DEMAS benchmarks -- cada uno se resuelve independientemente,
    y el que fallo queda afuera de `valores_benchmark` con su propia
    advertencia (distinta de la de tickers de cartera sin dato)."""
    fecha = pd.Timestamp("2024-01-01")
    movimientos = pd.DataFrame([_movimiento("AAA", fecha, cantidad=10.0, total=-1000.0)])

    def fake_descargar_precios_ba(tickers, fecha_inicio):
        # BENCH1 tiene precio, BENCH2 ("NOEXISTE") no.
        precios = pd.DataFrame({"AAA": [100.0], "BENCH1": [10.0]}, index=[fecha_inicio])
        tickers_sin_datos = [t for t in tickers if t not in ("AAA", "BENCH1")]
        return precios, tickers_sin_datos

    monkeypatch.setattr(historical_curve, "_descargar_precios_ba", fake_descargar_precios_ba)

    resultado = calcular_curva_historica(
        movimientos,
        benchmarks=[
            {"ticker": "BENCH1", "label": "BenchOK"},
            {"ticker": "NOEXISTE", "label": "BenchRoto"},
        ],
    )

    assert list(resultado.valores_benchmark.keys()) == ["BenchOK"]
    assert resultado.valor_ars.iloc[-1] == pytest.approx(1000.0)
    assert any("BenchRoto" in a and "NOEXISTE" in a for a in resultado.advertencias)


# ---------------------------------------------------------------- v10.1: dividendos en dolares
def test_cash_dividendos_en_dolares_usa_cantidad_por_ccl():
    import numpy as np

    from core.historical_curve import _serie_cash_dividendos_diario

    rango = pd.date_range("2024-01-01", periods=5, freq="D")
    movs = pd.DataFrame(
        [
            # dividendo en pesos: entra 'total' tal cual
            {"fechaEjecucion": rango[1], "tipo_operacion_norm": "DIVIDENDO", "ticker": None,
             "instrumento": "Peso argentino", "cantidad": np.nan, "total": 60.0},
            # dividendo de CEDEAR en dolares: 2 USD cobrados, 10 ARS de retencion
            {"fechaEjecucion": rango[3], "tipo_operacion_norm": "DIVIDENDO_ESPECIE", "ticker": None,
             "instrumento": "Dolar Especie CV 7000", "cantidad": 2.0, "total": -10.0},
        ]
    )
    ccl = pd.Series([1000.0, 1000.0, 1000.0, 1500.0, 1600.0], index=rango)

    cash = _serie_cash_dividendos_diario(movs, rango, ccl)
    assert cash.iloc[1] == pytest.approx(60.0)
    # 60 + (2 USD x 1500 del dia de cobro - 10 de retencion); despues queda fijo en ARS
    assert cash.iloc[3] == pytest.approx(60.0 + 2.0 * 1500.0 - 10.0)
    assert cash.iloc[4] == pytest.approx(cash.iloc[3])

    # sin CCL: comportamiento anterior (solo 'total')
    sin_ccl = _serie_cash_dividendos_diario(movs, rango, None)
    assert sin_ccl.iloc[-1] == pytest.approx(60.0 - 10.0)


# ---------------------------------------------------------------- v10.1: benchmarks con dividendos
@pytest.fixture(autouse=True)
def _sin_red_para_dividendos_benchmark(monkeypatch):
    """Los tests de este modulo no tocan la red: el factor de dividendos
    del subyacente en EE.UU. se apaga (el benchmark queda solo-precio)."""
    monkeypatch.setattr(historical_curve, "_factor_retorno_total_us", lambda *a, **k: None)


def test_benchmark_con_dividendos_suma_el_dividendo_reinvertido():
    from core.historical_curve import _precio_retorno_total, _serie_benchmark_diario

    rango = pd.date_range("2024-01-01", periods=4, freq="D")
    precio = pd.Series(100.0, index=rango)  # el precio no se mueve
    # dividendo del 2% pagado el dia 2: el factor pasa de 1/1.02 a 1
    factor = pd.Series([1 / 1.02, 1 / 1.02, 1.0, 1.0], index=rango)
    capital = pd.Series(1000.0, index=rango)  # una sola compra de 1000 el dia 0

    solo_precio = _serie_benchmark_diario(capital, precio, rango)
    con_div = _serie_benchmark_diario(capital, _precio_retorno_total(precio, factor), rango)
    assert solo_precio.iloc[-1] == pytest.approx(1000.0)
    assert con_div.iloc[-1] == pytest.approx(1020.0)


# ---------------------------------------------------------------- v10.2: picos aislados
def test_quitar_picos_aislados_corrige_errores_y_respeta_movimientos_reales():
    from core.historical_curve import _quitar_picos_aislados

    idx = pd.bdate_range("2024-01-01", periods=7)
    precios = pd.DataFrame(
        {
            # dia 2: pico de +50% que vuelve al dia siguiente -> error de datos
            "ERROR": [100.0, 101.0, 151.0, 102.0, 103.0, 104.0, 105.0],
            # salto real de +30% que se mantiene -> no se toca
            "REAL": [100.0, 100.0, 130.0, 131.0, 129.0, 132.0, 133.0],
            # cierre en 0 -> dato invalido
            "CERO": [50.0, 51.0, 0.0, 52.0, 53.0, 54.0, 55.0],
        },
        index=idx,
    )
    avisos = []
    out = _quitar_picos_aislados(precios, avisos)
    assert out["ERROR"].iloc[2] == pytest.approx(101.0)
    assert out["ERROR"].drop(idx[2]).equals(precios["ERROR"].drop(idx[2]))
    assert out["REAL"].equals(precios["REAL"])
    assert pd.isna(out["CERO"].iloc[2])
    assert len(avisos) == 1 and "ERROR (1)" in avisos[0] and "REAL" not in avisos[0]
