"""
tests/test_exposicion.py -- core/exposicion.py (v10.2). Sin red.
"""

import pandas as pd
import pytest

from core.exposicion import exposicion_bitcoin, exposicion_look_through


def test_look_through_suma_directo_y_via_etfs_y_unifica_clases():
    pesos = pd.Series({"SPY": 40.0, "QQQ": 20.0, "MSFT": 10.0, "MELI": 30.0})
    holdings = {
        "SPY": pd.Series({"MSFT": 0.06, "GOOGL": 0.03, "GOOG": 0.02}),
        "QQQ": pd.Series({"MSFT": 0.08}),
    }
    df = exposicion_look_through(pesos, holdings).set_index("Empresa")
    # MSFT: 10 directo + 40 x 6% + 20 x 8% = 10 + 2.4 + 1.6
    assert df.loc["MSFT", "Total %"] == pytest.approx(14.0)
    assert df.loc["MSFT", "Via ETFs %"] == pytest.approx(4.0)
    # GOOG y GOOGL son la misma empresa
    assert df.loc["GOOGL", "Total %"] == pytest.approx(40 * 0.05)
    assert "GOOG" not in df.index
    # los ETFs no aparecen como empresa; lo que no esta en ningun ETF queda solo directo
    assert "SPY" not in df.index and "QQQ" not in df.index
    assert df.loc["MELI", "Via ETFs %"] == pytest.approx(0.0)
    assert df.index[0] == "MELI"  # ordenado por exposicion total


def test_exposicion_bitcoin_detecta_ligados():
    pesos = pd.Series({"IBIT": 4.6, "MSTR": 6.1, "SPY": 20.0})
    riesgo = pd.Series({"IBIT": 6.0, "MSTR": 15.0})
    df = exposicion_bitcoin(pesos, riesgo).set_index("Ticker")
    assert set(df.index) == {"IBIT", "MSTR"}
    assert df["Peso %"].sum() == pytest.approx(10.7)
    assert df["Riesgo %"].sum() == pytest.approx(21.0)
