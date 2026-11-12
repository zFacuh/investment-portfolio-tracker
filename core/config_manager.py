"""
core/config_manager.py

Modulo de Configuracion Dinamica.

Maneja la carga, validacion y actualizacion de la configuracion del
portafolio (porcentajes objetivo por categoria, tickers, categoria de
cada activo, etc.) persistida en un archivo JSON editable a mano o,
mas adelante, desde la UI de Streamlit.

Diseno:
- La "fuente de verdad" es config/portfolio_config.json.
- El resto de la app (parser, market data, rebalanceador, UI) lee la
  configuracion a traves de las funciones de este modulo, nunca accede
  al JSON directamente. Si el dia de manana migramos a SQLite u otro
  storage, solo hay que tocar este archivo.
- Las rutas se resuelven en forma relativa a la ubicacion de este
  script (no se hardcodean rutas absolutas de Windows), para que el
  proyecto funcione igual sin importar desde donde se lo clone/copie.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
from core.rutas import CONFIG_DIR, EJEMPLO_CONFIG  # noqa: E402

CONFIG_PATH = CONFIG_DIR / "portfolio_config.json"
# Cartera de ejemplo que se copia a CONFIG_PATH la primera vez (el archivo
# real es personal y no se versiona; ver .gitignore).
EXAMPLE_CONFIG_PATH = EJEMPLO_CONFIG

PathLike = Union[str, Path]

# Tolerancia para considerar que una suma de % "cierra" en 100. Vive aca
# (no en app.py) porque ahora la usan tanto la UI como El Guardian
# (validar_dataframes_editor), y no queremos dos numeros que se puedan
# desincronizar.
TOLERANCIA_PCT = 0.01

# Tipos de activo soportados por el Configurador Interactivo. Determinan
# que fuente de datos se arma en construir_config_desde_editor. v10.2: solo
# CEDEAR/yfinance (se elimino Cripto/Binance; BTC se sigue via el CEDEAR IBIT).
TIPOS_ACTIVO = ["CEDEAR"]

# Benchmarks DEFAULT para la comparacion de la Equity Curve (ver
# core/historical_curve.py, "CUARTA serie OPCIONAL, multiple") si no se
# configuro nada en portfolio_config.json ("meta.benchmark_tickers") --
# solo SPY (S&P 500) via el CEDEAR "SPY.BA" de BYMA, misma convencion
# que el resto de la app. Ver get_benchmark_tickers() para el formato
# completo (soporta varios, y un "label" de display distinto del ticker
# que realmente cotiza -- ej. BTC comparado via el CEDEAR IBIT).
DEFAULT_BENCHMARK_TICKERS = [{"ticker": "SPY", "label": "SPY"}]


class ConfigError(Exception):
    """Error de validacion o de lectura/escritura de la configuracion."""


# ---------------------------------------------------------------------------
# Carga / guardado
# ---------------------------------------------------------------------------
def load_config(path: PathLike = CONFIG_PATH) -> Dict[str, Any]:
    """
    Lee el JSON de configuracion y lo valida antes de devolverlo.

    Un JSON corrupto (ej. una coma de mas si se edito a mano) o un
    problema de lectura de disco (permisos, archivo bloqueado) se
    relanzan como ConfigError con un mensaje entendible, en vez de dejar
    pasar el traceback crudo de json.JSONDecodeError/OSError -- mismo
    patron que ya usa core.manual_holdings.cargar_tenencias_manuales
    para este mismo caso.
    """
    path = Path(path)
    if not path.exists() and path == CONFIG_PATH and EXAMPLE_CONFIG_PATH.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    if not path.exists():
        raise ConfigError(f"No se encontro el archivo de configuracion: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ConfigError(f"No se pudo leer '{path}': {e}") from e
    validate_config(config)
    return config


def save_config(config: Dict[str, Any], path: PathLike = CONFIG_PATH) -> None:
    """Valida y persiste la configuracion en disco (formato legible)."""
    validate_config(config)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Validacion
# ---------------------------------------------------------------------------
def validate_config(config: Dict[str, Any]) -> None:
    """
    Reglas de integridad del archivo de configuracion:
      1. Deben existir las claves 'categorias' y 'activos'.
      2. Los 'objetivo_pct' de todas las categorias deben sumar 100%.
      3. Cada activo debe referenciar una categoria existente.
      4. Dentro de cada categoria, los 'objetivo_pct_categoria' de sus
         activos deben sumar 100% (si la categoria tiene activos).
    """
    if "categorias" not in config or "activos" not in config:
        raise ConfigError("El JSON debe tener las claves 'categorias' y 'activos'.")

    categorias = config["categorias"]
    activos = config["activos"]

    total_pct = sum(c["objetivo_pct"] for c in categorias.values())
    if abs(total_pct - 100) > 0.01:
        raise ConfigError(
            f"Los 'objetivo_pct' de 'categorias' deben sumar 100%. Suman {total_pct}%."
        )

    for ticker, datos in activos.items():
        categoria = datos.get("categoria")
        if categoria not in categorias:
            raise ConfigError(
                f"El activo '{ticker}' referencia la categoria '{categoria}', "
                f"que no existe en 'categorias'."
            )

        # v6.3 (vinculo BTC<->IBIT): "alias_ticker" es opcional -- marca que
        # este activo tambien se puede/debe operar bajo OTRO ticker (ej.
        # BTC via el CEDEAR IBIT en Cocos Capital, porque el broker no
        # opera cripto directamente). Ver core/holdings.py y
        # core/rebalancer.py para el detalle de como se usa. Aca solo se
        # valida que, si esta presente, no venga vacio ni apunte al mismo
        # ticker (auto-alias sin sentido) ni a otro activo ya definido
        # (ambiguedad: no puede ser "su propia posicion" Y "el alias de
        # otro" a la vez).
        alias_ticker = datos.get("alias_ticker")
        if alias_ticker is not None:
            alias_ticker = str(alias_ticker).strip().upper()
            if not alias_ticker:
                raise ConfigError(
                    f"El activo '{ticker}' tiene 'alias_ticker' vacio; omite el campo "
                    f"si no aplica, o completa el ticker vinculado (ej. 'IBIT')."
                )
            if alias_ticker == ticker:
                raise ConfigError(f"El activo '{ticker}' no puede tener a si mismo como 'alias_ticker'.")
            if alias_ticker in activos:
                raise ConfigError(
                    f"El 'alias_ticker' de '{ticker}' ('{alias_ticker}') ya es un activo propio "
                    f"de la configuracion -- no puede ser ambas cosas a la vez."
                )

        fuente = datos.get("fuente_datos")
        if fuente == "yfinance":
            if not datos.get("ticker_yfinance"):
                raise ConfigError(
                    f"El activo '{ticker}' tiene fuente_datos='yfinance' pero le "
                    f"falta 'ticker_yfinance' (ej. 'SPY.BA')."
                )
        else:
            raise ConfigError(
                f"El activo '{ticker}' tiene fuente_datos='{fuente}' invalida. "
                f"Debe ser 'yfinance'."
            )

    for nombre_categoria in categorias:
        activos_de_categoria = [
            a for a in activos.values() if a["categoria"] == nombre_categoria
        ]
        if not activos_de_categoria:
            continue
        suma_interna = sum(
            a.get("objetivo_pct_categoria", 0) for a in activos_de_categoria
        )
        if abs(suma_interna - 100) > 0.01:
            raise ConfigError(
                f"Los 'objetivo_pct_categoria' de la categoria '{nombre_categoria}' "
                f"deben sumar 100%. Suman {suma_interna}%."
            )


# ---------------------------------------------------------------------------
# "El Guardian": validacion + transformacion de las grillas editables de la
# Pestana 2 (Configurador Interactivo, v3.0). Separado a proposito de
# validate_config(): esa funcion valida el JSON ya armado (usa claves como
# 'objetivo_pct'); estas funciones validan y transforman DataFrames crudos
# que vienen directo de st.data_editor (columnas en castellano, con
# num_rows="dynamic" -> el usuario puede agregar/borrar filas a mano, asi
# que puede haber filas vacias, tickers repetidos, categorias borradas que
# activos viejos todavia referencian, etc.). validate_config() sigue
# corriendo dentro de save_config() como ultima red de seguridad.
# ---------------------------------------------------------------------------
def validar_dataframes_editor(
    df_categorias: pd.DataFrame, df_activos: pd.DataFrame
) -> List[str]:
    """
    Corre el pipeline COMPLETO de validaciones sobre las grillas editadas
    en la Pestana 2, en este orden:
      1. Matematica: Categorias suman 100%; activos de cada categoria
         suman 100% entre si.
      2. Integridad referencial (FK): ningun activo puede apuntar a una
         categoria que no exista en la tabla de Categorias.
      3. Campos nulos/duplicados: ni Categoria ni Ticker pueden estar
         vacios ni repetidos; a todo activo le tiene que faltar su
         "Ticker de Mercado" (simbolo de yfinance) para poder cotizarlo.

    Devuelve la lista COMPLETA de errores encontrados (no corta en el
    primero) para que la UI los pueda mostrar todos juntos en un solo
    st.error. Lista vacia = todo OK, se puede guardar. No muta nada ni
    toca el disco: es un chequeo puro.
    """
    errores: List[str] = []

    if df_categorias is None or df_categorias.empty:
        return ["No puede haber cero categorias: agrega al menos una fila en la tabla de Categorias."]

    # --- Categorias: nombres vacios ---
    nombres_cat_raw = df_categorias["Categoria"].astype(str).str.strip()
    if (nombres_cat_raw == "").any() or df_categorias["Categoria"].isna().any():
        errores.append(
            "Hay una fila en 'Categorias' con el nombre vacio. Completala o borra la fila "
            "(icono de papelera al pasar el mouse por la fila)."
        )

    # --- Categorias: nombres duplicados ---
    nombres_cat = [n for n in nombres_cat_raw.tolist() if n]
    duplicadas_cat = sorted({n for n in nombres_cat if nombres_cat.count(n) > 1})
    if duplicadas_cat:
        errores.append(f"Hay categorias duplicadas: {', '.join(duplicadas_cat)}. Cada nombre debe ser unico.")

    # --- Categorias: suma de % Objetivo Total ---
    suma_categorias = float(pd.to_numeric(df_categorias["% Objetivo Total"], errors="coerce").fillna(0).sum())
    if abs(suma_categorias - 100) > TOLERANCIA_PCT:
        errores.append(
            f"Los '% Objetivo Total' de Categorias suman {suma_categorias:.1f}% (tienen que sumar 100%)."
        )

    categorias_validas = set(nombres_cat)

    if df_activos is None or df_activos.empty:
        errores.append("No hay ningun activo cargado: agrega al menos una fila en la tabla de Activos.")
        return errores

    # --- Activos: tickers vacios ---
    tickers_raw = df_activos["Ticker"].astype(str).str.strip().str.upper()
    if (tickers_raw == "").any() or df_activos["Ticker"].isna().any():
        errores.append(
            "Hay una fila en 'Activos' con el Ticker vacio. Completala (ej. 'TSLA') o borra la fila."
        )

    # --- Activos: tickers duplicados ---
    tickers = [t for t in tickers_raw.tolist() if t]
    tickers_dup = sorted({t for t in tickers if tickers.count(t) > 1})
    if tickers_dup:
        errores.append(f"Hay tickers duplicados en Activos: {', '.join(tickers_dup)}. Cada Ticker debe ser unico.")

    # --- Activos: integridad referencial (FK a Categorias) ---
    for _, fila in df_activos.iterrows():
        ticker = str(fila.get("Ticker", "")).strip().upper() or "(sin ticker)"
        categoria = str(fila.get("Categoria", "")).strip()
        if categoria not in categorias_validas:
            errores.append(
                f"El activo '{ticker}' tiene la categoria '{categoria or '(vacia)'}', que no existe "
                f"en la tabla de Categorias (¿la borraste o la escribiste distinto?)."
            )

    # --- Activos: Tipo valido ---
    if "Tipo" in df_activos.columns:
        for _, fila in df_activos.iterrows():
            ticker = str(fila.get("Ticker", "")).strip().upper() or "(sin ticker)"
            tipo = str(fila.get("Tipo", "")).strip()
            if tipo not in TIPOS_ACTIVO:
                errores.append(
                    f"El activo '{ticker}' tiene un Tipo invalido ('{tipo}'). Debe ser uno de: "
                    f"{', '.join(TIPOS_ACTIVO)}."
                )

    # --- Activos: Ticker de Mercado vacio (necesario para poder cotizar) ---
    if "Ticker de Mercado" in df_activos.columns:
        for _, fila in df_activos.iterrows():
            ticker = str(fila.get("Ticker", "")).strip().upper() or "(sin ticker)"
            ticker_mercado = str(fila.get("Ticker de Mercado", "")).strip()
            if not ticker_mercado:
                errores.append(
                    f"Al activo '{ticker}' le falta el 'Ticker de Mercado' (ej. 'TSLA.BA')."
                )

    # --- Activos: Ticker Alias (opcional, v6.3 -- ver validate_config para
    # el detalle de por que existe) -- no puede ser el mismo ticker de la
    # fila, ni coincidir con el Ticker propio de OTRA fila de esta misma
    # tabla (ambiguedad: no puede ser a la vez "su propia posicion" y "el
    # alias vinculado de otro activo").
    if "Ticker Alias (opcional)" in df_activos.columns:
        tickers_propios = set(tickers)
        for _, fila in df_activos.iterrows():
            ticker = str(fila.get("Ticker", "")).strip().upper() or "(sin ticker)"
            alias = str(fila.get("Ticker Alias (opcional)", "") or "").strip().upper()
            if not alias:
                continue
            if alias == ticker:
                errores.append(f"El activo '{ticker}' no puede tener a si mismo como Ticker Alias.")
            elif alias in tickers_propios:
                errores.append(
                    f"El Ticker Alias '{alias}' del activo '{ticker}' ya es el Ticker propio de otro "
                    f"activo en esta tabla -- no puede ser ambas cosas a la vez."
                )

    # --- Activos: dentro de cada categoria, los % suman 100% ---
    if "Categoria" in df_activos.columns and "% Objetivo en Categoria" in df_activos.columns:
        tmp = df_activos.copy()
        tmp["% Objetivo en Categoria"] = pd.to_numeric(
            tmp["% Objetivo en Categoria"], errors="coerce"
        ).fillna(0)
        for categoria in nombres_cat:
            en_categoria = tmp[tmp["Categoria"].astype(str).str.strip() == categoria]
            if en_categoria.empty:
                errores.append(
                    f"La categoria '{categoria}' no tiene ningun activo asignado. "
                    "Agregale al menos uno o borra la categoria."
                )
                continue
            suma = float(en_categoria["% Objetivo en Categoria"].sum())
            if abs(suma - 100) > TOLERANCIA_PCT:
                errores.append(
                    f"Los activos de la categoria '{categoria}' suman {suma:.1f}% (tienen que sumar 100%)."
                )

    return errores


def construir_config_desde_editor(
    df_categorias: pd.DataFrame,
    df_activos: pd.DataFrame,
    meta_original: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Transforma las grillas ya validadas (ver validar_dataframes_editor) a
    la estructura anidada de portfolio_config.json. Asume que la
    validacion ya paso: esta funcion no vuelve a chequear reglas de
    negocio, solo arma el dict (save_config() corre validate_config()
    igual, como ultima red de seguridad antes de escribir a disco).

    Para activos nuevos (agregados a mano en la grilla, sin entrada
    previa en el config original): el Tipo elegido determina la fuente
    de datos ("CEDEAR" -> yfinance, con el 'Ticker de Mercado' como
    ticker_yfinance).
    """
    nuevas_categorias: Dict[str, Any] = {}
    for _, fila in df_categorias.iterrows():
        nombre = str(fila["Categoria"]).strip()
        if not nombre:
            continue
        nuevas_categorias[nombre] = {
            "objetivo_pct": float(fila["% Objetivo Total"]),
            "descripcion": str(fila.get("Descripcion", "") or ""),
        }

    nuevos_activos: Dict[str, Any] = {}
    for _, fila in df_activos.iterrows():
        ticker = str(fila["Ticker"]).strip().upper()
        if not ticker:
            continue

        tipo = str(fila.get("Tipo", "CEDEAR")).strip() or "CEDEAR"
        ticker_mercado = str(fila.get("Ticker de Mercado", "")).strip()
        nombre_activo = str(fila.get("Nombre", "") or ticker).strip()

        nuevo_activo: Dict[str, Any] = {
            "nombre": nombre_activo,
            "categoria": str(fila["Categoria"]).strip(),
            "tipo": tipo,
            "objetivo_pct_categoria": float(fila["% Objetivo en Categoria"]),
        }

        nuevo_activo["fuente_datos"] = "yfinance"
        nuevo_activo["ticker_yfinance"] = ticker_mercado

        # v6.3: "Ticker Alias (opcional)" -- ver validate_config/
        # validar_dataframes_editor para el detalle. Solo se agrega la
        # clave si la celda vino completa, para no ensuciar el JSON de
        # todos los demas activos con "alias_ticker": null.
        alias_ticker = str(fila.get("Ticker Alias (opcional)", "") or "").strip().upper()
        if alias_ticker:
            nuevo_activo["alias_ticker"] = alias_ticker

        nuevos_activos[ticker] = nuevo_activo

    nuevo_meta = dict(meta_original or {})
    nuevo_meta["version"] = int(nuevo_meta.get("version", 1)) + 1
    nuevo_meta["ultima_actualizacion"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {"meta": nuevo_meta, "categorias": nuevas_categorias, "activos": nuevos_activos}


def guardar_desde_editor(
    df_categorias: pd.DataFrame,
    df_activos: pd.DataFrame,
    meta_original: Optional[Dict[str, Any]] = None,
    path: PathLike = CONFIG_PATH,
) -> Dict[str, Any]:
    """
    Punto de entrada UNICO que usa la UI (Pestana 2, boton "Guardar y
    Recalcular"): corre El Guardian (validar_dataframes_editor) y, si no
    hay errores, arma el nuevo config (construir_config_desde_editor) y lo
    persiste con save_config (que vuelve a correr validate_config como
    ultima red de seguridad antes de escribir el archivo). Devuelve el
    config nuevo si todo salio bien.

    Lanza ConfigError con TODOS los errores encontrados (uno por linea)
    si algo no cierra matematica o referencialmente. No escribe nada en
    disco en ese caso.
    """
    errores = validar_dataframes_editor(df_categorias, df_activos)
    if errores:
        raise ConfigError("\n".join(f"- {e}" for e in errores))

    nuevo_config = construir_config_desde_editor(df_categorias, df_activos, meta_original)
    save_config(nuevo_config, path=path)
    return nuevo_config


# ---------------------------------------------------------------------------
# Helpers de consulta (usados por Mercado / Rebalanceador / UI)
# ---------------------------------------------------------------------------
def get_target_by_ticker(config: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """
    Devuelve el % objetivo de cada ticker sobre el TOTAL del portafolio,
    combinando el peso de su categoria con su peso dentro de la categoria.

    Ej: Core=70%, GGAL=20% dentro de Core -> GGAL pesa 14% del total.
    """
    config = config or load_config()
    resultado: Dict[str, float] = {}
    for ticker, datos in config["activos"].items():
        pct_categoria = config["categorias"][datos["categoria"]]["objetivo_pct"]
        pct_dentro_categoria = datos.get("objetivo_pct_categoria", 0)
        resultado[ticker] = round(pct_categoria * pct_dentro_categoria / 100, 4)
    return resultado


def get_benchmark_tickers(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """
    Lista de benchmarks configurados para comparar contra la Equity
    Curve (ver "CUARTA serie OPCIONAL, multiple" en
    core/historical_curve.py). Se lee de
    `config["meta"]["benchmark_tickers"]`; si no esta configurado (o
    esta vacio), cae a DEFAULT_BENCHMARK_TICKERS (solo SPY).

    Cada entrada de la lista puede ser:
      - un string simple, ej. "QQQ" -- el ticker que se pide a yfinance
        (con sufijo ".BA", misma convencion que el resto de la app) ES
        el nombre a mostrar.
      - un dict {"ticker": ..., "label": ...} -- para cuando el nombre a
        mostrar difiere del simbolo que realmente cotiza. Ej. BTC no
        tiene un CEDEAR ".BA" propio en yfinance bajo ese ticker, pero
        SI se puede comparar via el CEDEAR "IBIT" (el ETF de Bitcoin) -- {"ticker": "IBIT", "label": "BTC"} pide
        IBIT.BA pero la Equity Curve lo etiqueta "BTC".

    Devuelve siempre la forma normalizada [{"ticker": ..., "label": ...}, ...],
    en mayusculas/sin espacios (ticker) y sin espacios de mas (label).
    Entradas sin ticker resoluble se descartan en silencio.
    """
    config = config or load_config()
    crudo = config.get("meta", {}).get("benchmark_tickers")
    if not crudo:
        return [dict(b) for b in DEFAULT_BENCHMARK_TICKERS]

    resultado: List[Dict[str, str]] = []
    for item in crudo:
        if isinstance(item, dict):
            ticker = str(item.get("ticker") or "").strip().upper()
            label = str(item.get("label") or ticker).strip()
        else:
            ticker = str(item or "").strip().upper()
            label = ticker
        if ticker:
            resultado.append({"ticker": ticker, "label": label})

    return resultado or [dict(b) for b in DEFAULT_BENCHMARK_TICKERS]


def get_yfinance_map(config: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Mapea ticker interno -> simbolo de yfinance (ej. GGAL -> GGAL.BA)."""
    config = config or load_config()
    return {t: d["ticker_yfinance"] for t, d in config["activos"].items()}


def get_tickers_por_categoria(
    categoria: str, config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    config = config or load_config()
    return {
        t: d for t, d in config["activos"].items() if d["categoria"] == categoria
    }


# ---------------------------------------------------------------------------
# Mutaciones (para la futura UI de Streamlit / uso interactivo)
# ---------------------------------------------------------------------------
def agregar_o_actualizar_activo(
    ticker: str,
    nombre: str,
    categoria: str,
    objetivo_pct_categoria: float,
    tipo: str,
    ticker_yfinance: str,
    config: Optional[Dict[str, Any]] = None,
    guardar: bool = True,
) -> Dict[str, Any]:
    """Agrega un activo nuevo o pisa uno existente. No valida sumas: usar
    `validate_config` (o `save_config`, que valida internamente) despues
    de terminar de ajustar los `objetivo_pct_categoria` de la categoria."""
    config = config or load_config()
    if categoria not in config["categorias"]:
        raise ConfigError(f"La categoria '{categoria}' no existe.")

    config["activos"][ticker.upper()] = {
        "nombre": nombre,
        "categoria": categoria,
        "tipo": tipo,
        "objetivo_pct_categoria": objetivo_pct_categoria,
        "ticker_yfinance": ticker_yfinance,
    }
    if guardar:
        save_config(config)
    return config


def eliminar_activo(
    ticker: str, config: Optional[Dict[str, Any]] = None, guardar: bool = True
) -> Dict[str, Any]:
    config = config or load_config()
    config["activos"].pop(ticker.upper(), None)
    if guardar:
        save_config(config)
    return config


def actualizar_objetivo_categoria(
    categoria: str,
    nuevo_pct: float,
    config: Optional[Dict[str, Any]] = None,
    guardar: bool = True,
) -> Dict[str, Any]:
    config = config or load_config()
    if categoria not in config["categorias"]:
        raise ConfigError(f"La categoria '{categoria}' no existe.")
    config["categorias"][categoria]["objetivo_pct"] = nuevo_pct
    if guardar:
        save_config(config)
    return config


if __name__ == "__main__":
    cfg = load_config()
    print("Configuracion cargada y valida.")
    print(f"Categorias: { {k: v['objetivo_pct'] for k, v in cfg['categorias'].items()} }")
    print("Peso objetivo por ticker (sobre el total del portafolio):")
    for ticker, pct in sorted(get_target_by_ticker(cfg).items(), key=lambda x: -x[1]):
        print(f"  {ticker:<8} {pct:>6.2f}%")
