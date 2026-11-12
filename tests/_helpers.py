"""
tests/_helpers.py

Builders minimos para armar, sin tocar disco ni red, los dos insumos que
necesita core.rebalancer.calcular_rebalanceo: un `config` (misma forma
que portfolio_config.json) y un `holdings_df` (misma forma que devuelve
core.holdings.calcular_tenencia_actual). Compartido por los tests de
core/rebalancer.py -- no es un modulo de tests en si mismo (no tiene
funciones test_*), asi que pytest no lo colecciona.
"""

from typing import Dict, Tuple

import pandas as pd


def build_config(
    categorias: Dict[str, float],
    activos: Dict[str, Tuple[str, float]],
) -> dict:
    """
    `categorias`: {nombre_categoria: objetivo_pct} (debe sumar 100).
    `activos`: {ticker: (categoria, objetivo_pct_categoria)}.

    Arma un config valido minimo (mismas claves que portfolio_config.json)
    con todos los activos como CEDEAR/yfinance -- suficiente para
    core.rebalancer, que no valida el config con validate_config.
    """
    return {
        "meta": {"moneda_base": "ARS"},
        "categorias": {
            nombre: {"objetivo_pct": pct, "descripcion": ""} for nombre, pct in categorias.items()
        },
        "activos": {
            ticker: {
                "nombre": ticker,
                "categoria": categoria,
                "tipo": "CEDEAR",
                "objetivo_pct_categoria": pct_categoria,
                "fuente_datos": "yfinance",
                "ticker_yfinance": f"{ticker}.BA",
            }
            for ticker, (categoria, pct_categoria) in activos.items()
        },
    }


def build_holdings(valores: Dict[str, Tuple[str, float, float]]) -> pd.DataFrame:
    """
    `valores`: {ticker: (categoria, precio_ars, valor_ars_actual)}.

    Arma un holdings_df minimo (mismas columnas que usa
    core.rebalancer.calcular_rebalanceo de core.holdings.calcular_tenencia_actual).
    """
    filas = []
    for ticker, (categoria, precio_ars, valor_ars) in valores.items():
        filas.append(
            {
                "Ticker": ticker,
                "Categoria": categoria,
                "Cantidad": (valor_ars / precio_ars) if precio_ars else 0.0,
                "Precio Actual": precio_ars,
                "Moneda": "ARS",
                "Precio ARS": precio_ars,
                "Valor ARS": valor_ars,
            }
        )
    return pd.DataFrame(filas)
