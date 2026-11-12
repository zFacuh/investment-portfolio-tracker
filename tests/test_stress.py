"""
tests/test_stress.py -- core/stress.py (v10.2). Sin red: los cierres se
arman a mano.
"""

import numpy as np
import pandas as pd
import pytest

from core.stress import correr_escenarios, retornos_escenario, simbolo_us, stress_test


def test_simbolo_us_mapea_cedears_y_casos_especiales():
    config = {"activos": {"SPY": {"ticker_yfinance": "SPY.BA"}}}
    assert simbolo_us("SPY", config) == "SPY"
    assert simbolo_us("BRKB") == "BRK-B"
    assert simbolo_us("IBIT") == "BTC-USD"
    assert simbolo_us("YPFD") == "YPF"
    assert simbolo_us("SPCX") is None
    assert simbolo_us("MELI") == "MELI"  # sin config: el mismo ticker


def test_retornos_escenario_y_activo_sin_historia():
    idx = pd.bdate_range("2020-01-01", "2020-12-31")
    cierres = pd.DataFrame(
        {
            "VIEJO": np.linspace(100, 50, len(idx)),
            "NUEVO": [np.nan] * 200 + list(np.linspace(10, 20, len(idx) - 200)),  # empieza a cotizar despues
        },
        index=idx,
    )
    r = retornos_escenario(cierres, "2020-01-02", "2020-12-31")
    assert r["VIEJO"] == pytest.approx(50 / cierres["VIEJO"].loc["2020-01-02"] - 1)
    assert np.isnan(r["NUEVO"])


def test_stress_test_pondera_y_usa_proxy_y_efectivo():
    pesos = pd.Series({"A": 40.0, "B": 40.0, "CASH": 20.0})
    retornos = pd.Series({"A": -0.5, "B": np.nan})
    res = stress_test(pesos, retornos, retorno_proxy=-0.25, escenario="test")
    # 0.4 x -50% + 0.4 x -25% (proxy) + 0.2 x 0% = -30%
    assert res.retorno_cartera == pytest.approx(-0.30)
    assert res.peso_con_supuesto == pytest.approx(40.0)
    det = res.detalle.set_index("Ticker")
    assert det.loc["CASH", "Fuente"] == "efectivo"
    assert det.loc["B", "Fuente"].startswith("supuesto")
    assert det["Aporte pp"].sum() == pytest.approx(-30.0)


def test_correr_escenarios_con_cierres_dados():
    idx = pd.bdate_range("2021-12-01", "2023-01-31")
    cierres = pd.DataFrame({"QQQ": np.linspace(100, 60, len(idx)), "SPY": np.linspace(100, 80, len(idx))}, index=idx)
    esc = {"prueba": ("2021-12-31", "2022-12-30")}
    res = correr_escenarios(pd.Series({"SPY": 50.0, "SPCX": 50.0}), cierres=cierres, escenarios=esc)
    assert len(res) == 1
    det = res[0].detalle.set_index("Ticker")
    assert det.loc["SPCX", "Fuente"] == "supuesto: QQQ"
    r_spy = retornos_escenario(cierres, "2021-12-31", "2022-12-30")
    assert res[0].retorno_cartera == pytest.approx(0.5 * r_spy["SPY"] + 0.5 * r_spy["QQQ"])


def test_cierres_historicos_descarga_de_un_solo_simbolo_multiindex(tmp_path, monkeypatch):
    # Bug real: con group_by="ticker", yfinance devuelve columnas MultiIndex
    # (simbolo, campo) aun para UN solo simbolo; antes se guardaba vacio y el
    # activo quedaba como "sin historia" (usaba el proxy) para siempre.
    import core.market_data as md
    import core.stress as stress

    idx = pd.bdate_range("2020-01-01", periods=5)
    cols = pd.MultiIndex.from_product([["GLD"], ["Open", "Close"]])
    falso = pd.DataFrame(np.ones((5, 2)) * [[100.0, 101.0]], index=idx, columns=cols)
    monkeypatch.setattr(stress.yf, "download", lambda *a, **k: falso)
    monkeypatch.setattr(md, "en_cooldown_rate_limit", lambda: False)
    out = stress.cierres_historicos(["GLD"], cache_dir=tmp_path)
    assert "GLD" in out.columns and out["GLD"].iloc[0] == pytest.approx(101.0)
    assert (tmp_path / "GLD.csv").stat().st_size > 50  # quedo guardado con datos, no vacio
