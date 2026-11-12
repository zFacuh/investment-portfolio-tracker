"""
tests/test_diario.py -- core/diario.py (v10.2). Sin red.
"""

from datetime import date

import pytest

from core.diario import (
    DiarioError,
    cargar_diario,
    eliminar_entrada,
    evaluar_diario,
    guardar_diario,
    nueva_entrada,
)


def _e(accion, fecha=date(2026, 1, 1)):
    # activo a 1000 ARS, SPY a 2000 ARS, CCL 1000
    return nueva_entrada("tsla", accion, "Motivo suficientemente largo", 1000.0, 2000.0, 1000.0, 6, fecha)


def test_nueva_entrada_valida_y_normaliza():
    e = _e("Compra")
    assert e["ticker"] == "TSLA" and e["fecha"] == "2026-01-01" and len(e["id"]) == 8
    with pytest.raises(DiarioError):
        nueva_entrada("TSLA", "Comprar", "Motivo suficientemente largo", 1, 1, 1)
    with pytest.raises(DiarioError):
        nueva_entrada("TSLA", "Compra", "corto", 1, 1, 1)
    with pytest.raises(DiarioError):
        nueva_entrada("TSLA", "Compra", "Motivo suficientemente largo", 0, 1, 1)


def test_evaluacion_en_dolares_contra_spy_compra_y_venta():
    entradas = [_e("Compra"), _e("Venta")]
    # hoy: el activo vale 1500 ARS y SPY 2400 ARS, con el CCL a 1200
    # activo en USD: 1.0 -> 1.25 (+25%); SPY en USD: 2.0 -> 2.0 (0%)
    df = evaluar_diario(entradas, {"TSLA": 1500.0}, 2400.0, 1200.0, hoy=date(2026, 7, 1))
    compra = df[df["Accion"] == "Compra"].iloc[0]
    venta = df[df["Accion"] == "Venta"].iloc[0]
    assert compra["Activo USD %"] == pytest.approx(25.0)
    assert compra["SPY USD %"] == pytest.approx(0.0)
    assert compra["Diferencia pp"] == pytest.approx(25.0)
    assert compra["Resultado"] == "Acierto"
    assert venta["Resultado"] == "Error"  # vendiste algo que despues le gano al indice
    assert bool(compra["Revisar"])  # 181 dias >= horizonte de 6 meses


def test_evaluacion_muy_pronto_y_sin_precio():
    df = evaluar_diario([_e("Compra", date(2026, 6, 20))], {}, 2000.0, 1000.0, hoy=date(2026, 7, 1))
    assert df.iloc[0]["Resultado"] == "Sin precio"
    df = evaluar_diario([_e("Compra", date(2026, 6, 20))], {"TSLA": 1100.0}, 2000.0, 1000.0, hoy=date(2026, 7, 1))
    assert df.iloc[0]["Resultado"] == "Muy pronto"


def test_guardar_cargar_y_eliminar(tmp_path):
    ruta = tmp_path / "diario.json"
    assert cargar_diario(ruta) == []
    e1, e2 = _e("Compra"), _e("Venta")
    guardar_diario([e1, e2], ruta)
    assert [x["id"] for x in cargar_diario(ruta)] == [e1["id"], e2["id"]]
    assert eliminar_entrada(cargar_diario(ruta), e1["id"]) == [e2]
    ruta.write_text("{roto", encoding="utf-8")
    with pytest.raises(DiarioError):
        cargar_diario(ruta)
