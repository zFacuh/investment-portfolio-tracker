"""
tests/test_rebalancer.py

Fija el comportamiento matematico de core.rebalancer.calcular_rebalanceo
-- el modulo mas sensible a romperse en silencio con un cambio futuro
(ver ANALISIS_REVISION.md, item 6 de la hoja de ruta). No pega a la red
ni a disco: `config` y `holdings_df` se arman a mano con tests/_helpers.py,
exactamente con las columnas/claves que produce el resto de la app.
"""

import pytest

from core.rebalancer import RebalancerError, calcular_rebalanceo, calcular_rebalanceo_banda
from tests._helpers import build_config, build_holdings

TOLERANCIA = 1e-6


def test_asignacion_nunca_excede_el_monto_y_ningun_activo_supera_su_meta():
    """
    Demostracion del docstring del modulo: con un activo sobreponderado
    (BBB, deficit negativo -> se recorta a 0 y no recibe nada), la suma
    de TODOS los deficits positivos queda > monto_x, asi que:
      1. La suma de "Asignacion ARS" da EXACTAMENTE monto_x (nunca mas).
      2. Ningun activo recibe mas de lo que le faltaba para su Meta
         (Valor Actual + Asignacion <= Meta ARS, con margen de tolerancia
         de punto flotante).
      3. El costo real que se va a pagar (nominales x precio + comision
         estimada) tampoco excede lo asignado a cada activo.
    """
    config = build_config(
        categorias={"Core": 50.0, "Satelite": 50.0},
        activos={
            "AAA": ("Core", 100.0),       # 50% del total
            "BBB": ("Satelite", 50.0),    # 25% del total
            "CCC": ("Satelite", 50.0),    # 25% del total
        },
    )
    holdings = build_holdings(
        {
            "AAA": ("Core", 100.0, 0.0),        # muy por debajo de su meta
            "BBB": ("Satelite", 100.0, 5000.0),  # muy por ENCIMA de su meta (25% de 6000 = 1500)
            "CCC": ("Satelite", 100.0, 0.0),     # por debajo de su meta
        }
    )
    monto_x = 1000.0

    resultado = calcular_rebalanceo(holdings, config, monto_x=monto_x)
    tabla = resultado.ordenes.set_index("Ticker")

    # 1. La suma asignada es EXACTAMENTE el monto ingresado (prueba
    # algebraica del docstring: sum(deficits positivos) >= monto_x).
    assert tabla["Asignacion ARS"].sum() == pytest.approx(monto_x, abs=0.01)

    # BBB YA estaba por encima de su Meta ANTES de este calculo (a
    # proposito, para probar el caso sobreponderado): el algoritmo nunca
    # vende, asi que sigue por encima despues tambien -- lo que importa
    # es que no reciba NADA de la compra nueva, no que dejar de estar
    # sobreponderado (eso esta fuera de alcance de un DCA puro, ver
    # docstring del modulo).
    assert tabla.loc["BBB", "Asignacion ARS"] == 0.0
    assert tabla.loc["BBB", "Nominales a Comprar"] == 0.0
    assert tabla.loc["BBB", "Valor Actual ARS"] > tabla.loc["BBB", "Meta ARS"]

    # 2. y 3.: NINGUN activo recibe mas de lo que le faltaba para su Meta
    # (Asignacion <= Deficit, la propiedad que evita el "overshoot"
    # demostrada en el docstring del modulo), ni gasta mas de lo
    # asignado una vez descontada la comision y el redondeo hacia abajo.
    for ticker in tabla.index:
        fila = tabla.loc[ticker]
        assert fila["Asignacion ARS"] <= max(fila["Deficit ARS"], 0.0) + TOLERANCIA
        assert fila["Costo Total Estimado ARS"] <= fila["Asignacion ARS"] + TOLERANCIA

    # El costo total real (con comision) tampoco excede el monto pedido.
    assert resultado.costo_total_estimado <= monto_x + TOLERANCIA


def test_cartera_vacia_reparte_exactamente_segun_pct_objetivo():
    """
    Con Valor ARS = 0 en todos los activos (cartera recien arrancada,
    sin ninguna compra todavia), el Deficit de cada uno es igual a su
    Meta completa -- la Asignacion tiene que repartirse en las mismas
    proporciones que el % Objetivo de cada activo, sin excepciones ni
    division por cero.
    """
    config = build_config(
        categorias={"Core": 70.0, "Satelite": 30.0},
        activos={
            "AAA": ("Core", 100.0),      # 70% del total
            "BBB": ("Satelite", 60.0),   # 18% del total
            "CCC": ("Satelite", 40.0),   # 12% del total
        },
    )
    holdings = build_holdings(
        {
            "AAA": ("Core", 10.0, 0.0),
            "BBB": ("Satelite", 10.0, 0.0),
            "CCC": ("Satelite", 10.0, 0.0),
        }
    )
    monto_x = 50_000.0

    resultado = calcular_rebalanceo(holdings, config, monto_x=monto_x)
    tabla = resultado.ordenes.set_index("Ticker")

    assert resultado.valor_cartera_actual == 0.0
    assert tabla["Asignacion ARS"].sum() == pytest.approx(monto_x, abs=0.01)

    for ticker, pct_objetivo in (("AAA", 70.0), ("BBB", 18.0), ("CCC", 12.0)):
        esperado = monto_x * pct_objetivo / 100
        assert tabla.loc[ticker, "Asignacion ARS"] == pytest.approx(esperado, abs=0.01)
        assert tabla.loc[ticker, "% Actual"] == 0.0


def test_monto_insuficiente_para_comprar_un_nominal():
    """
    Si el precio del unico activo es mucho mayor que el Monto X, no
    alcanza para comprar ni un nominal: Nominales a Comprar da 0, no se
    gasta nada (Monto a Invertir ARS = 0, sin comision), y el Vuelto ARS
    se queda con TODO el monto asignado -- mismo caso que ya maneja
    app.py mostrando "no alcanza para comprar ni un nominal".
    """
    config = build_config(
        categorias={"Core": 100.0},
        activos={"AAA": ("Core", 100.0)},
    )
    holdings = build_holdings({"AAA": ("Core", 1_000_000.0, 0.0)})
    monto_x = 100.0

    resultado = calcular_rebalanceo(holdings, config, monto_x=monto_x)
    tabla = resultado.ordenes.set_index("Ticker")

    assert tabla.loc["AAA", "Nominales a Comprar"] == 0.0
    assert tabla.loc["AAA", "Monto a Invertir ARS"] == 0.0
    assert tabla.loc["AAA", "Comision Estimada ARS"] == 0.0
    assert tabla.loc["AAA", "Costo Total Estimado ARS"] == 0.0
    assert tabla.loc["AAA", "Vuelto ARS"] == pytest.approx(monto_x, abs=0.01)
    assert resultado.monto_total_asignado == 0.0
    assert resultado.vuelto_total == pytest.approx(monto_x, abs=0.01)


def test_monto_invalido_lanza_rebalancer_error():
    """monto_x <= 0 tiene que cortar con RebalancerError, no calcular
    sobre un dato de entrada sin sentido."""
    config = build_config(categorias={"Core": 100.0}, activos={"AAA": ("Core", 100.0)})
    holdings = build_holdings({"AAA": ("Core", 100.0, 0.0)})

    with pytest.raises(RebalancerError):
        calcular_rebalanceo(holdings, config, monto_x=0)

    with pytest.raises(RebalancerError):
        calcular_rebalanceo(holdings, config, monto_x=-500)


# ---------------------------------------------------------------------------
# calcular_rebalanceo_banda (rebalanceo por banda de tolerancia, con venta)
# ---------------------------------------------------------------------------
def test_banda_vende_sobreponderado_y_financia_al_subponderado():
    """
    Con un activo muy por encima de su objetivo (BBB) y otro muy por
    debajo (AAA), ambos fuera de banda, la venta de BBB tiene que
    financiar la compra de AAA: el costo total de lo comprado (neto +
    comision) nunca puede superar el efectivo neto que dejo la venta
    (neto de SU propia comision) -- misma propiedad de "nunca gastar mas
    de lo disponible" que ya fija calcular_rebalanceo para el DCA.
    """
    config = build_config(
        categorias={"Core": 50.0, "Satelite": 50.0},
        activos={"AAA": ("Core", 100.0), "BBB": ("Satelite", 100.0)},
    )
    holdings = build_holdings(
        {
            "AAA": ("Core", 100.0, 100.0),  # 10% actual vs 50% objetivo
            "BBB": ("Satelite", 100.0, 900.0),  # 90% actual vs 50% objetivo
        }
    )

    resultado = calcular_rebalanceo_banda(holdings, config, banda_tolerancia_pct=5.0)

    assert list(resultado.ordenes_venta["Ticker"]) == ["BBB"]
    assert list(resultado.ordenes_compra["Ticker"]) == ["AAA"]

    assert resultado.venta_bruta_total > 0
    assert resultado.comision_venta_total == pytest.approx(
        resultado.venta_bruta_total * 0.006, abs=0.01
    )
    assert resultado.venta_neta_total == pytest.approx(
        resultado.venta_bruta_total - resultado.comision_venta_total, abs=0.01
    )

    # El efectivo disponible es EXACTAMENTE la venta neta (no se aporto
    # Monto Nuevo), y lo comprado nunca excede ese efectivo.
    assert resultado.efectivo_disponible_total == pytest.approx(resultado.venta_neta_total, abs=0.01)
    assert resultado.costo_compra_total <= resultado.efectivo_disponible_total + 0.01

    # Al menos una advertencia recuerda el impacto impositivo de vender.
    assert any("impositivo" in a for a in resultado.advertencias)


def test_banda_no_toca_activos_dentro_de_la_banda():
    """Un activo cuya desviacion es menor a la banda no debe aparecer ni
    en ordenes de venta ni de compra -- se deja quieto a proposito."""
    config = build_config(
        categorias={"Core": 100.0},
        activos={"AAA": ("Core", 60.0), "BBB": ("Core", 40.0)},
    )
    # AAA: objetivo 60%, actual 62% (desviacion +2pp, dentro de banda 5).
    # BBB: objetivo 40%, actual 38% (desviacion -2pp, dentro de banda 5).
    holdings = build_holdings(
        {
            "AAA": ("Core", 100.0, 620.0),
            "BBB": ("Core", 100.0, 380.0),
        }
    )

    resultado = calcular_rebalanceo_banda(holdings, config, banda_tolerancia_pct=5.0)

    assert resultado.ordenes_venta.empty
    assert resultado.ordenes_compra.empty
    assert set(resultado.desviaciones["Estado"]) == {"Dentro de banda"}


def test_banda_cartera_vacia_no_lanza_error():
    """A diferencia del DCA (que funciona con cartera vacia), la banda
    de tolerancia con cartera vacia no tiene nada que comparar -- debe
    devolver un resultado vacio, no reventar."""
    config = build_config(categorias={"Core": 100.0}, activos={"AAA": ("Core", 100.0)})
    holdings = build_holdings({"AAA": ("Core", 100.0, 0.0)})

    resultado = calcular_rebalanceo_banda(holdings, config, banda_tolerancia_pct=5.0)

    assert resultado.ordenes_venta.empty
    assert resultado.ordenes_compra.empty
    assert resultado.valor_cartera_actual == 0.0


def test_banda_parametros_invalidos_lanzan_rebalancer_error():
    config = build_config(categorias={"Core": 100.0}, activos={"AAA": ("Core", 100.0)})
    holdings = build_holdings({"AAA": ("Core", 100.0, 1000.0)})

    with pytest.raises(RebalancerError):
        calcular_rebalanceo_banda(holdings, config, banda_tolerancia_pct=0)

    with pytest.raises(RebalancerError):
        calcular_rebalanceo_banda(holdings, config, banda_tolerancia_pct=5.0, monto_nuevo=-100)


# ---------------------------------------------------------------- v10.2: modo transicion
from core.rebalancer import calcular_transicion  # noqa: E402


def _cartera_con_fuera_de_objetivo():
    config = build_config({"Core": 100.0}, {"A": ("Core", 50.0), "B": ("Core", 50.0)})
    holdings = build_holdings(
        {
            "A": ("Core", 10.0, 1000.0),
            "B": ("Core", 10.0, 0.0),
            "X": ("(Fuera de Objetivo)", 10.0, 1000.0),  # 100 nominales fuera de la config
        }
    )
    return config, holdings


def test_transicion_vende_todo_lo_fuera_de_objetivo_y_reinvierte():
    config, holdings = _cartera_con_fuera_de_objetivo()
    r = calcular_transicion(holdings, config)
    ventas = r.ventas.set_index("Ticker")
    assert list(ventas.index) == ["X"]
    assert ventas.loc["X", "Nominales a Vender"] == pytest.approx(100.0)
    assert ventas.loc["X", "Monto Neto ARS"] == pytest.approx(1000.0 - r.comision_ventas)
    assert r.efectivo_disponible == pytest.approx(1000.0 - r.comision_ventas)
    compras = r.compras.ordenes.set_index("Ticker")
    # A ya esta en su meta (50% de ~2000): todo el efectivo va a B
    assert compras.loc["B", "Nominales a Comprar"] > 0
    assert compras.loc["A", "Nominales a Comprar"] == pytest.approx(0.0)
    # nunca se gasta mas de lo que dejaron las ventas, y lo que no se invierte queda como vuelto
    assert r.compras.costo_total_estimado <= r.efectivo_disponible + 1e-6
    assert r.vuelto == pytest.approx(r.efectivo_disponible - r.compras.costo_total_estimado)
    assert "X" not in r.pesos_despues.index
    assert r.pesos_despues.sum() == pytest.approx(100.0)
    assert r.comision_total == pytest.approx(r.comision_ventas + r.comision_compras)


def test_transicion_respeta_lo_que_elegis_no_vender():
    config, holdings = _cartera_con_fuera_de_objetivo()
    r = calcular_transicion(holdings, config, vender=[], monto_nuevo=0.0)
    assert r.ventas.empty
    assert r.compras is None
    assert r.efectivo_disponible == pytest.approx(0.0)


def test_transicion_vende_el_excedente_de_sobreponderados():
    config = build_config({"Core": 100.0}, {"A": ("Core", 50.0), "B": ("Core", 50.0)})
    holdings = build_holdings({"A": ("Core", 10.0, 1500.0), "B": ("Core", 10.0, 500.0)})
    r = calcular_transicion(holdings, config, vender_sobreponderados=True)
    ventas = r.ventas.set_index("Ticker")
    assert ventas.loc["A", "Motivo"] == "Sobreponderado"
    # meta de A = 50% de 2000 = 1000 -> sobran 500 -> 50 nominales a 10
    assert ventas.loc["A", "Nominales a Vender"] == pytest.approx(50.0)
    assert r.compras.ordenes.set_index("Ticker").loc["B", "Nominales a Comprar"] > 0


def test_transicion_ticker_inexistente_lanza_error():
    config, holdings = _cartera_con_fuera_de_objetivo()
    with pytest.raises(RebalancerError):
        calcular_transicion(holdings, config, vender=["NOEXISTE"])
