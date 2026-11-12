"""
core/manual_holdings.py

Persistencia de Tenencias Manuales (v6.0).

Activos que NO pasan por el CSV de Cocos Capital: posiciones en otro broker, cripto guardada en una wallet
propia, tenencias legacy que ya no se operan, o simplemente algo que no
queres cargar via CSV en este momento. Se editan a mano desde la
Pestana 2 (Configurador) en una grilla de 3 columnas (Ticker, Cantidad,
Categoria) y se persisten en `data/manual_holdings.json`.

Estas cantidades se SUMAN a las que ya calculan csv_parser (Cocos
Capital) -- la consolidacion de las dos fuentes vive en core.holdings.calcular_tenencia_actual, este
modulo solo se ocupa de guardar/leer/validar el archivo.

Un ticker manual que NO esta en portfolio_config.json (un "huerfano")
se sigue cotizando y sumando al Valor Total de la cartera, pero con 0%
Objetivo: ver core.rebalancer, que es donde efectivamente nunca le
asigna compras nuevas.

Formato del archivo (lista simple, facil de editar a mano si hiciera
falta):
    [
      {"ticker": "GGAL", "cantidad": 50, "categoria": "Satelite"},
      {"ticker": "ETH", "cantidad": 1.5, "categoria": "(Fuera de Objetivo)"}
    ]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Union

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
from core.rutas import DATA_DIR  # noqa: E402

MANUAL_HOLDINGS_PATH = DATA_DIR / "manual_holdings.json"

PathLike = Union[str, Path]

COLUMNAS_EDITOR = ["Ticker", "Cantidad", "Categoria"]

# Categoria por defecto para un activo manual que el usuario no clasifico
# (o que a proposito dejo "fuera de objetivo"). Nunca es None/"" en la
# tabla de Tenencia Actual, para que siempre se pueda agrupar/mostrar.
CATEGORIA_FUERA_DE_OBJETIVO = "(Fuera de Objetivo)"


class ManualHoldingsError(Exception):
    """Error de validacion o de lectura/escritura de las tenencias manuales."""


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------
def cargar_tenencias_manuales(path: PathLike = MANUAL_HOLDINGS_PATH) -> List[Dict[str, Any]]:
    """
    Devuelve la lista de tenencias manuales guardadas, cada una
    {"ticker": str, "cantidad": float, "categoria": str}.

    Si el archivo todavia no existe (primera vez que se usa esta
    funcionalidad) devuelve una lista vacia en vez de lanzar error: no
    tener tenencias manuales cargadas es un estado normal, no una falla.
    """
    path = Path(path)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ManualHoldingsError(f"No se pudo leer '{path}': {e}") from e
    if not isinstance(data, list):
        raise ManualHoldingsError(f"'{path}' deberia contener una lista de tenencias manuales.")
    return data


def cargar_tenencias_manuales_df(path: PathLike = MANUAL_HOLDINGS_PATH) -> pd.DataFrame:
    """Version DataFrame de cargar_tenencias_manuales, lista para pasarle
    directo a st.data_editor en la Pestana 2."""
    registros = cargar_tenencias_manuales(path)
    if not registros:
        return pd.DataFrame(columns=COLUMNAS_EDITOR)
    return pd.DataFrame(
        [
            {
                "Ticker": str(r.get("ticker", "")),
                "Cantidad": float(r.get("cantidad", 0) or 0),
                "Categoria": str(r.get("categoria", "") or ""),
            }
            for r in registros
        ],
        columns=COLUMNAS_EDITOR,
    )


def sumar_tenencias_manuales_por_ticker(path: PathLike = MANUAL_HOLDINGS_PATH) -> Dict[str, float]:
    """
    Devuelve {ticker: cantidad_total}, sumando por si el mismo ticker
    aparece en mas de una fila (ej. dos lotes cargados por separado).
    Usado por core.holdings para consolidar con Cocos Capital.
    """
    registros = cargar_tenencias_manuales(path)
    totales: Dict[str, float] = {}
    for r in registros:
        ticker = str(r.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        cantidad = float(r.get("cantidad", 0) or 0)
        totales[ticker] = totales.get(ticker, 0.0) + cantidad
    return totales


# ---------------------------------------------------------------------------
# Validacion + guardado
# ---------------------------------------------------------------------------
def validar_tenencias_manuales_df(df: pd.DataFrame) -> List[str]:
    """
    Valida la grilla de la UI ANTES de guardar (mismo espiritu que
    config_manager.validar_dataframes_editor, pero mas simple: aca no
    hay integridad referencial que chequear, un activo manual puede
    apuntar a cualquier Categoria o directamente no tener el ticker en
    portfolio_config.json a proposito).

    Reglas:
      - Ticker no puede estar vacio.
      - Cantidad tiene que ser un numero > 0 (para sacar una tenencia,
        se borra la fila en vez de dejarla en 0 o negativa).

    Una tabla vacia (0 tenencias manuales cargadas) es valida: no
    agrega errores.
    """
    errores: List[str] = []
    if df is None or df.empty:
        return errores

    tickers_raw = df["Ticker"].astype(str).str.strip().str.upper()
    if (tickers_raw == "").any() or df["Ticker"].isna().any():
        errores.append("Hay una fila de Tenencias Manuales con el Ticker vacio. Completala o borra la fila.")

    for _, fila in df.iterrows():
        ticker = str(fila.get("Ticker", "")).strip().upper() or "(sin ticker)"
        cantidad = pd.to_numeric(fila.get("Cantidad"), errors="coerce")
        if pd.isna(cantidad):
            errores.append(f"La Cantidad de '{ticker}' no es un numero valido.")
        elif cantidad <= 0:
            errores.append(
                f"La Cantidad de '{ticker}' tiene que ser mayor a 0 "
                "(para sacar una tenencia, borra la fila en vez de poner 0)."
            )

    return errores


def guardar_tenencias_manuales(
    df: pd.DataFrame, path: PathLike = MANUAL_HOLDINGS_PATH
) -> List[Dict[str, Any]]:
    """
    Valida y sobrescribe data/manual_holdings.json con el contenido de
    `df` (la grilla editada en la Pestana 2). Lanza ManualHoldingsError
    con TODOS los errores encontrados (uno por linea) si algo no es
    valido; en ese caso NO escribe nada en disco.
    """
    errores = validar_tenencias_manuales_df(df)
    if errores:
        raise ManualHoldingsError("\n".join(f"- {e}" for e in errores))

    registros: List[Dict[str, Any]] = []
    if df is not None and not df.empty:
        for _, fila in df.iterrows():
            ticker = str(fila["Ticker"]).strip().upper()
            if not ticker:
                continue
            categoria = str(fila.get("Categoria", "") or "").strip() or CATEGORIA_FUERA_DE_OBJETIVO
            registros.append(
                {
                    "ticker": ticker,
                    "cantidad": float(fila["Cantidad"]),
                    "categoria": categoria,
                }
            )

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(registros, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return registros


if __name__ == "__main__":
    registros = cargar_tenencias_manuales()
    if not registros:
        print("No hay tenencias manuales cargadas todavia.")
    else:
        print(f"{len(registros)} tenencia(s) manual(es):")
        for r in registros:
            print(f"  {r['ticker']:<10} {r['cantidad']:>12}  ({r.get('categoria', '')})")
        print()
        print("Totales por ticker:", sumar_tenencias_manuales_por_ticker())
