"""
tests/test_analytics.py

Fija el fix de MIN_DIAS_HISTORICO_ANALITICA en
core.analytics.descargar_precios_historicos: un ticker con MUY POCO
historico (ej. un CEDEAR recien listado en BYMA, con apenas 1 dia de
datos en yfinance) tiene que quedar excluido de la Analitica de Riesgo
-- si no, arrastra la ventana de fechas COMUN de TODOS los demas
activos a ese unico dia al intersectar (`.dropna(how="any")`), dejando
la matriz de correlacion entera en NaN aunque el resto tenga un anio
completo de datos buenos (bug real, reportado en la pestana Analitica
de Riesgo de la UI).

No pega a la red: se fuerza el fallback ticker-por-ticker (monkeypatch
de `yf.download` para que falle) y se monkeypatchea `_descargar_uno`
para devolver series deterministas.
"""

import numpy as np
import pandas as pd

import core.analytics as analytics


def _serie_con_variacion(fechas: pd.DatetimeIndex, semilla: int) -> pd.Series:
    """Serie con variacion real dia a dia -- necesaria para que la
    correlacion de Pearson no de NaN por varianza cero."""
    rng = np.random.default_rng(semilla)
    valores = 100 + np.cumsum(rng.normal(0, 1, size=len(fechas)))
    return pd.Series(valores, index=fechas)


def test_ticker_con_historico_insuficiente_no_recorta_la_ventana_de_los_demas(monkeypatch):
    """Si NI el CEDEAR (.BA) NI su subyacente tienen historico
    suficiente, el activo queda excluido -- pero sin arrastrar a los
    demas a esa misma ventana corta."""
    fechas_largas = pd.date_range("2025-01-01", periods=60, freq="D")

    def fake_descargar_uno(simbolo, periodo):
        if simbolo in ("NUEVO.BA", "NUEVO"):
            # Recien listado: un solo dia de historico (NI el CEDEAR NI
            # el subyacente alcanzan), muy por debajo de
            # MIN_DIAS_HISTORICO_ANALITICA.
            return pd.Series([100.0], index=[fechas_largas[-1]])
        semilla = hash(simbolo) % 1000
        return _serie_con_variacion(fechas_largas, semilla)

    # Fuerza el fallback ticker-por-ticker (mismo mecanismo que un batch
    # roto en produccion) en vez de pegarle a yfinance de verdad.
    def batch_roto(*args, **kwargs):
        raise Exception("batch forzado a fallar para el test")

    monkeypatch.setattr(analytics.yf, "download", batch_roto)
    monkeypatch.setattr(analytics, "_descargar_uno", fake_descargar_uno)

    config = {
        "activos": {
            "AAA": {"fuente_datos": "yfinance", "ticker_yfinance": "AAA.BA"},
            "BBB": {"fuente_datos": "yfinance", "ticker_yfinance": "BBB.BA"},
            "NUEVO": {"fuente_datos": "yfinance", "ticker_yfinance": "NUEVO.BA"},
        }
    }

    precios, _mapa_yf, tickers_sin_datos = analytics.descargar_precios_historicos(config)

    # NUEVO queda afuera (no arrastra la ventana comun a 1 dia).
    assert "NUEVO" not in precios.columns
    assert "NUEVO" in tickers_sin_datos

    # AAA y BBB conservan su ventana completa de 60 dias -- el bug
    # original la hubiera recortado a 1.
    assert "AAA" in precios.columns and "BBB" in precios.columns
    assert len(precios) >= analytics.MIN_DIAS_HISTORICO_ANALITICA

    # Con datos suficientes y variacion real, la correlacion tiene que
    # ser un numero valido, no NaN (el sintoma original del bug).
    rendimientos = analytics.calcular_rendimientos_diarios(precios)
    matriz = analytics.calcular_matriz_correlacion(rendimientos)
    assert matriz.loc["AAA", "BBB"] == matriz.loc["AAA", "BBB"]  # no es NaN


def test_proxy_al_subyacente_incluye_cedear_recien_listado(monkeypatch):
    """
    Un CEDEAR recien listado en BYMA (".BA" con 1 solo dia de historico,
    ej. XLV.BA en la vida real) NO debe desaparecer de la Analitica de
    Riesgo si su ACTIVO SUBYACENTE (mismo ticker sin ".BA", en su
    mercado de origen) SI tiene historico suficiente -- se usa ese como
    proxy en vez de excluir el activo, y queda registrado en `mapa_yf`
    para que calcular_analitica_riesgo pueda avisarlo aparte.
    """
    fechas_largas = pd.date_range("2025-01-01", periods=60, freq="D")

    def fake_descargar_uno(simbolo, periodo):
        if simbolo == "NUEVO.BA":
            return pd.Series([100.0], index=[fechas_largas[-1]])  # CEDEAR: 1 solo dia
        if simbolo == "NUEVO":
            return _serie_con_variacion(fechas_largas, semilla=7)  # subyacente: historico completo
        return _serie_con_variacion(fechas_largas, semilla=hash(simbolo) % 1000)

    def batch_roto(*args, **kwargs):
        raise Exception("batch forzado a fallar para el test")

    monkeypatch.setattr(analytics.yf, "download", batch_roto)
    monkeypatch.setattr(analytics, "_descargar_uno", fake_descargar_uno)

    config = {
        "activos": {
            "AAA": {"fuente_datos": "yfinance", "ticker_yfinance": "AAA.BA"},
            "NUEVO": {"fuente_datos": "yfinance", "ticker_yfinance": "NUEVO.BA"},
        }
    }

    precios, mapa_yf, tickers_sin_datos = analytics.descargar_precios_historicos(config)

    assert "NUEVO" in precios.columns
    assert "NUEVO" not in tickers_sin_datos
    assert mapa_yf["NUEVO"] == "NUEVO"  # ya NO es "NUEVO.BA" -- se sustituyo por el subyacente
    assert len(precios) >= analytics.MIN_DIAS_HISTORICO_ANALITICA
