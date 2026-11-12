"""
core/holdings.py

Tenencia Actual: cruza los movimientos historicos (core.csv_parser) con
las cotizaciones en vivo (core.market_data) para armar la foto actual
del portafolio: cuanto tenes de cada activo, a que precio, cuanto vale
en ARS, y que % real representa sobre el total.

Fuente automatica de "cantidad poseida":

- CEDEARs / acciones operadas en BYMA via Cocos Capital: se suma la
  columna 'cantidad' de todos los movimientos COMPRA/VENTA de ese
  ticker en el DataFrame de csv_parser. Las ventas ya vienen con
  cantidad negativa (asi las exporta el broker), por lo que la suma
  neta agrupada por ticker es directamente la posicion actual.

Tambien expone "Precio ARS" (precio ya convertido, sea cual sea la
moneda de origen) porque el modulo de Rebalanceo lo necesita para
calcular nominales de activos que cotizan en USD, y una
aproximacion de Ganancia/Perdida no realizada por ticker a partir del
flujo de caja neto de Compras/Ventas del CSV (ver
`calcular_costo_neto_byma` para el detalle y las limitaciones de este
calculo).

Tenencias Manuales (v6.0): una SEGUNDA fuente de cantidad, ademas de
Cocos Capital (CSV) -- ver core/manual_holdings.py. La regla
es SIEMPRE sumar, nunca "una fuente pisa a la otra": si el CSV dice 5
GOOGL y cargaste 3 GOOGL a mano (ej. en otro broker), la Cantidad final
es 8. Un ticker que no esta en portfolio_config.json (un "huerfano") se
cotiza igual y se suma al Valor Total, pero queda fuera de la
configuracion objetivo -- ver core/rebalancer.py, que es donde
efectivamente se le asigna 0% Objetivo y por lo tanto nunca recibe
compras nuevas del DCA.

Huerfanos (v6.1): un huerfano puede salir de CUALQUIERA de las dos
fuentes automaticas/manuales, no solo de la carga manual -- si comprate
un ticker por Cocos Capital y todavia no lo agregaste a "Activos" en el
Configurador, esa posicion tambien aparece como huerfano (antes de esta
version quedaba totalmente afuera de la tabla, solo se avisaba por
consola). El set de huerfanos es la union de "tickers con posicion CSV"
y "tickers con tenencia manual", menos los que ya estan en la config; la
Cantidad de cada uno vuelve a ser la suma de ambas fuentes con la misma
regla de nunca pisar.

Dividendos y cash de cuenta (v6.4): antes de esta version,
OPERACIONES_QUE_MUEVEN_POSICION = {"COMPRA", "VENTA"} y este modulo
ignoraba por completo los movimientos de dividendos del CSV (ya
mapeados por core/csv_parser.py como "DIVIDENDO", "DIVIDENDO_ESPECIE" y
"AJUSTE_DIVIDENDO"), subestimando sistematicamente el Valor Total de
cualquier cartera con activos que pagan dividendos. Que se hace con
cada tipo:

  - DIVIDENDO ("Dividendos", cash en ARS) y AJUSTE_DIVIDENDO ("Nota
    Debito/Credito Dividendos ARS"): no tienen ticker (no representan
    nominales de ningun activo), asi que se acumulan como saldo de
    CASH DISPONIBLE (no invertido), sumando la columna 'total' de cada
    movimiento -- ver `calcular_cash_dividendos`. Este saldo aparece
    como una fila propia "CASH" en la tabla de tenencia (Categoria
    "Cash (Dividendos)"), se suma al Valor Total como cualquier otro
    activo, y por lo tanto tambien queda reflejado en la Equity Curve
    (ver core/historical_curve.py).
  - DIVIDENDO_ESPECIE ("Dividendos En Especie"): el export de Cocos
    Capital usa este mismo tipo de operacion para DOS casos distintos,
    diferenciables por si 'instrumento' resuelve un ticker real (via
    `_extraer_ticker`, ver core/csv_parser.py) o no:
      * CON ticker (ej. "BONOS REP. ARG. ... (GD38)"): es un dividendo
        pagado en especie de verdad -- nominales de un activo. Se suma
        'cantidad' a la posicion de ESE ticker, exactamente igual que
        una Compra (ver `calcular_posiciones_dividendo_especie`), sin
        costo de base asociado (no hay 'total' de compra real, es
        dinero "gratis").
      * SIN ticker (ej. instrumento = "Dolar estadounidense" o "Peso
        argentino"): a pesar del nombre, esto es en la practica un
        dividendo en EFECTIVO en moneda extranjera (o local), no una
        entrega de nominales de un activo -- no hay ningun ticker al
        cual sumarle cantidad. Se trata igual que DIVIDENDO/
        AJUSTE_DIVIDENDO: se suma su 'total' al saldo de cash.
    Nota: para estas filas 'total' suele ser un monto chico y NEGATIVO
    (es la comision/IVA retenida sobre el dividendo, no el valor bruto
    del dividendo -- el export de Cocos Capital no trae una columna con
    el valor bruto de estos movimientos). El saldo de cash resultante
    es entonces una aproximacion conservadora (neta de costos) del
    ingreso real por dividendos, no el monto bruto acreditado.

Ticker Alias vinculado (v6.3): un activo de la config puede declarar
"alias_ticker" (ej. BTC -> "IBIT") para el caso de un instrumento que en
la practica NO se puede operar directo en el broker (Cocos Capital no
opera cripto), pero si a traves de otro ticker que SI cotiza ahi (el
ETF/CEDEAR IBIT, que sigue el precio de BTC). Cuando esto pasa:
  - El Valor ARS del activo principal pasa a ser la SUMA de dos
    patas -- la automatica de siempre (CSV de Cocos Capital + manual)
    MAS el valor de la posicion del alias (IBIT: CSV de
    Cocos Capital + tenencia manual, cotizado con get_precio_generico).
    Misma regla de "nunca una fuente pisa a la otra, siempre se suman"
    que ya rige Manual + Automatico.
  - La Cantidad mostrada se re-expresa en la unidad del activo
    PRINCIPAL (equivalente en BTC = Valor ARS combinado / precio ARS de
    BTC), para que "Cantidad x Precio ARS = Valor ARS" se siga
    cumpliendo a simple vista en la tabla aunque la plata real este
    repartida entre dos instrumentos distintos.
  - El ticker del alias (IBIT) se EXCLUYE del set de huerfanos: ya no
    aparece como fila propia, su valor queda plegado dentro de la fila
    de BTC.
  - Costo Neto / P&L de la fila combinada se deja en None a proposito
    -- mezclar en una sola fila el costo de base de dos instrumentos
    distintos daria una ganancia/perdida distorsionada -- el mismo tipo
    de "peras con manzanas" que ya se corrigio en
    core/historical_curve.py (ver Filtro de Consistencia / Universo
    Cerrado).
  - Se agregan columnas "Alias Ticker", "Alias Precio Actual", "Alias
    Moneda" y "Alias Precio ARS" al resultado -- las usa
    core.rebalancer para saber a que precio (y en que instrumento)
    ejecutar una compra nueva de este activo, ver ese modulo.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from core.config_manager import load_config
from core.csv_parser import parsear_movimientos
from core.manual_holdings import (
    CATEGORIA_FUERA_DE_OBJETIVO,
    cargar_tenencias_manuales,
)
from core.market_data import (
    Cotizacion,
    MarketDataError,
    get_dolar_ccl,
    get_precio_generico,
    obtener_cotizaciones,
)

# Tipos de operacion que modifican la cantidad de nominales en cartera
# de un ticker: Compra/Venta de siempre, mas Dividendo En Especie CUANDO
# resuelve un ticker real (ver docstring del modulo, seccion "Dividendos
# y cash de cuenta"). FCI, dividendos en efectivo, cash puro, etc. no
# son "posicion" en ningun ticker.
OPERACIONES_QUE_MUEVEN_POSICION = {"COMPRA", "VENTA"}
OPERACIONES_DIVIDENDO_ESPECIE = {"DIVIDENDO_ESPECIE"}

# Tipos de operacion que representan dividendos en EFECTIVO (o
# equivalente -- ver docstring): se acumulan como saldo de cash
# disponible, nunca como posicion de un ticker.
OPERACIONES_DIVIDENDO_CASH = {"DIVIDENDO", "AJUSTE_DIVIDENDO"}

TICKER_CASH = "CASH"
CATEGORIA_CASH = "Cash (Dividendos)"

COLUMNAS_SALIDA = [
    "Ticker",
    "Categoria",
    "Cantidad",
    "Precio Actual",
    "Moneda",
    "Precio ARS",
    "Valor ARS",
    "% Real",
    "Costo Neto ARS",
    "Precio Promedio Compra ARS",
    "P&L ARS",
    "P&L %",
    # v6.3 (Ticker Alias vinculado, ej. BTC <-> IBIT): None/NaN en
    # cualquier activo que no tenga "alias_ticker" configurado. Ver el
    # docstring del modulo y core.rebalancer para el detalle de uso.
    "Alias Ticker",
    "Alias Precio Actual",
    "Alias Moneda",
    "Alias Precio ARS",
]


def calcular_posiciones_byma(movimientos: pd.DataFrame) -> Dict[str, float]:
    """
    Suma neta de 'cantidad' por ticker a partir de los movimientos de
    Compra/Venta del broker. Devuelve {ticker: cantidad_neta}.
    """
    operaciones = movimientos[
        movimientos["tipo_operacion_norm"].isin(OPERACIONES_QUE_MUEVEN_POSICION)
        & movimientos["ticker"].notna()
    ]
    if operaciones.empty:
        return {}
    return operaciones.groupby("ticker")["cantidad"].sum().to_dict()


def calcular_costo_neto_byma(movimientos: pd.DataFrame) -> Dict[str, float]:
    """
    Aproxima el costo neto invertido (en ARS) por ticker, sumando la
    columna 'total' de todas las Compras/Ventas de ese ticker. 'total'
    ya viene negativo en las compras (salida de caja) y positivo en las
    ventas (entrada de caja), asi que -sum(total) es la caja neta
    puesta en ese activo.

    LIMITACION IMPORTANTE: esto es un costo promedio simplificado, no
    un calculo FIFO/LIFO de lotes. Si hubo ventas PARCIALES de un
    ticker, el costo neto resultante ya no representa fielmente el
    costo de base de lo que queda en cartera (mezcla el costo de lo
    vendido con lo que se mantiene). Para una posicion que solo tuvo
    compras (el caso mas comun en una cartera en armado) es exacto.

    Esta funcion usa el costo REAL (comision/IVA efectivamente cobrados
    por el broker en cada operacion pasada, ya incluidos en 'total').
    Para una orden NUEVA todavia no ejecutada, ese dato real no existe
    -- core.rebalancer.calcular_rebalanceo usa una comision/IVA
    ESTIMADA (`core.rebalancer.COMISION_PCT_APROX`, calibrada contra el
    promedio observado en este mismo historico) para descontarla del
    monto sugerido. Ver el docstring de ese modulo para el detalle.
    """
    operaciones = movimientos[
        movimientos["tipo_operacion_norm"].isin(OPERACIONES_QUE_MUEVEN_POSICION)
        & movimientos["ticker"].notna()
    ]
    if operaciones.empty:
        return {}
    return (-operaciones.groupby("ticker")["total"].sum()).to_dict()


def calcular_posiciones_dividendo_especie(movimientos: pd.DataFrame) -> Dict[str, float]:
    """
    Suma neta de 'cantidad' por ticker a partir de los movimientos de
    Dividendo En Especie que SI resuelven un ticker real (ej. "BONOS
    REP. ARG. ... (GD38)"). Devuelve {ticker: cantidad_nominales}, para
    sumarse a la posicion automatica del activo igual que una Compra
    (ver docstring del modulo). Las filas de Dividendo En Especie SIN
    ticker (pagadas en moneda, no en nominales de un activo) quedan
    afuera a proposito -- esas se tratan como cash, ver
    `calcular_cash_dividendos`.
    """
    operaciones = movimientos[
        movimientos["tipo_operacion_norm"].isin(OPERACIONES_DIVIDENDO_ESPECIE)
        & movimientos["ticker"].notna()
    ]
    if operaciones.empty:
        return {}
    return operaciones.groupby("ticker")["cantidad"].sum().to_dict()


def calcular_cash_dividendos(movimientos: pd.DataFrame) -> float:
    """
    Saldo de cash disponible (no invertido) acumulado por dividendos en
    efectivo: DIVIDENDO + AJUSTE_DIVIDENDO (siempre, no tienen ticker) y
    DIVIDENDO_ESPECIE cuando NO resuelve un ticker real (pagado en
    moneda extranjera/local, no en nominales de un activo -- ver
    docstring del modulo). Suma directo la columna 'total' de cada
    movimiento (ya neta de comision/IVA); ver la nota del docstring
    sobre por que esto es una aproximacion conservadora del ingreso
    bruto real por dividendos.
    """
    cash_directo = movimientos[movimientos["tipo_operacion_norm"].isin(OPERACIONES_DIVIDENDO_CASH)]
    especie_sin_ticker = movimientos[
        (movimientos["tipo_operacion_norm"].isin(OPERACIONES_DIVIDENDO_ESPECIE))
        & movimientos["ticker"].isna()
    ]
    total = cash_directo["total"].sum() + especie_sin_ticker["total"].sum()
    return float(total) if pd.notna(total) else 0.0


def _consolidar_tenencias_manuales(
    tenencias_manuales: List[Dict[str, Any]],
) -> "tuple[Dict[str, float], Dict[str, str]]":
    """
    Reduce la lista cruda de tenencias manuales (puede tener el mismo
    ticker en mas de una fila, ej. dos lotes cargados por separado) a
    dos dicts: cantidad TOTAL por ticker, y la Categoria declarada para
    cada uno (se queda con la primera no vacia que encuentre).
    """
    cantidades: Dict[str, float] = {}
    categorias: Dict[str, str] = {}
    for registro in tenencias_manuales:
        ticker = str(registro.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        cantidad = float(registro.get("cantidad", 0) or 0)
        cantidades[ticker] = cantidades.get(ticker, 0.0) + cantidad

        categoria = str(registro.get("categoria", "") or "").strip()
        if categoria and ticker not in categorias:
            categorias[ticker] = categoria
    return cantidades, categorias


def calcular_tenencia_actual(
    config: Optional[dict] = None,
    movimientos: Optional[pd.DataFrame] = None,
    cotizaciones: Optional[Dict[str, Cotizacion]] = None,
    tenencias_manuales: Optional[List[Dict[str, Any]]] = None,
) -> pd.DataFrame:
    """
    Arma la tabla de tenencia actual consolidando DOS fuentes de
    cantidad -- Cocos Capital (CSV) y Tenencias Manuales -- con Precio Actual, Valor en ARS, % que representa sobre
    el total valuado del portafolio, y una P&L aproximada (solo para
    activos operados via Cocos Capital: las tenencias manuales no
    tienen costo de base conocido).

    Regla de consolidacion (v6.0): para cada ticker de la config, la
    Cantidad final es SIEMPRE (cantidad automatica del CSV)
    + (cantidad manual de manual_holdings.json).
    Nunca una fuente "pisa" a la otra. Ademas, cualquier ticker que
    tenga tenencia manual cargada pero NO este en la config ("huerfano",
    ej. una accion legacy de otro broker) tambien se cotiza y se agrega
    como fila propia, con Cantidad = solo la parte manual (por
    definicion no puede tener parte de CSV si no esta en la
    config objetivo).

    Los cuatro parametros son opcionales (pensados para poder testear
    el cruce sin pegarle a la red): si no se pasan, se cargan con sus
    fuentes por defecto:
      - config             -> config/portfolio_config.json
      - movimientos        -> csv_parser.parsear_movimientos() (data/movimientos)
      - cotizaciones       -> market_data.obtener_cotizaciones(config), en vivo
      - tenencias_manuales -> manual_holdings.cargar_tenencias_manuales()
    """
    config = config or load_config()
    movimientos = movimientos if movimientos is not None else parsear_movimientos()
    cotizaciones = (
        cotizaciones if cotizaciones is not None else obtener_cotizaciones(config)
    )
    tenencias_manuales = (
        tenencias_manuales if tenencias_manuales is not None else cargar_tenencias_manuales()
    )

    posiciones_byma = calcular_posiciones_byma(movimientos)
    posiciones_especie = calcular_posiciones_dividendo_especie(movimientos)
    costos_netos_byma = calcular_costo_neto_byma(movimientos)
    cantidades_manuales, categorias_manuales = _consolidar_tenencias_manuales(tenencias_manuales)

    # Cache perezoso del CCL, compartido entre el alias vinculado (mas
    # abajo, en el loop principal) y el bloque de huerfanos (mas abajo del
    # todo) -- antes solo existia en el bloque de huerfanos; se sube aca
    # para que ambos usos peguen contra la misma consulta en vez de
    # duplicarla.
    dolar_ccl_cache: Optional[float] = None

    filas = []
    tickers_de_config = set()

    for ticker, datos in config["activos"].items():
        tickers_de_config.add(ticker)
        alias_ticker = str(datos.get("alias_ticker") or "").strip().upper() or None
        if alias_ticker:
            # Se excluye del set de huerfanos mas abajo: su valor va
            # plegado dentro de esta misma fila, no como fila propia.
            tickers_de_config.add(alias_ticker)
        fuente = datos.get("fuente_datos", "yfinance")

        # Dividendo En Especie con ticker resuelto (ej. GD38) suma
        # nominales igual que una Compra -- ver docstring del
        # modulo, "Dividendos y cash de cuenta".
        cantidad_automatica = posiciones_byma.get(ticker, 0.0) + posiciones_especie.get(
            ticker, 0.0
        )

        cantidad_manual = cantidades_manuales.get(ticker, 0.0)
        # Suma real solo si hay AL MENOS un dato disponible; si la fuente
        # automatica no respondio (None)
        # y tampoco hay tenencia manual para ese ticker, se mantiene el
        # N/D de siempre en vez de mostrar un 0 enganoso.
        if cantidad_automatica is None and ticker not in cantidades_manuales:
            cantidad = None
        else:
            cantidad = (cantidad_automatica or 0.0) + cantidad_manual

        cotizacion = cotizaciones.get(ticker)
        precio_actual = cotizacion.precio if cotizacion else None
        moneda = cotizacion.moneda if cotizacion else None
        precio_ars = cotizacion.precio_ars if cotizacion else None

        valor_ars = None
        if cantidad is not None and precio_ars is not None:
            valor_ars = round(cantidad * precio_ars, 2)

        # --- Ticker Alias vinculado (v6.3, ej. BTC -> IBIT) -----------
        # Se busca el precio del alias SIEMPRE que este configurado (no
        # solo si ya hay posicion): core.rebalancer lo necesita para
        # poder armar una orden de compra nueva aunque hoy la posicion en
        # el alias sea cero. Si hay posicion (CSV y/o manual, sumadas sin
        # que una pise a la otra), su Valor ARS se suma al del activo
        # principal.
        alias_precio_actual = None
        alias_moneda = None
        alias_precio_ars = None
        if alias_ticker:
            alias_cantidad = posiciones_byma.get(alias_ticker, 0.0) + cantidades_manuales.get(
                alias_ticker, 0.0
            )
            try:
                if dolar_ccl_cache is None:
                    dolar_ccl_cache = get_dolar_ccl()
            except MarketDataError:
                dolar_ccl_cache = None
            try:
                cotiz_alias = get_precio_generico(alias_ticker, dolar_ccl=dolar_ccl_cache)
                alias_precio_actual = cotiz_alias.precio
                alias_moneda = cotiz_alias.moneda
                alias_precio_ars = cotiz_alias.precio_ars
            except MarketDataError as e:
                print(f"[holdings] Alias '{alias_ticker}' de '{ticker}' sin cotizacion: {e}")

            if abs(alias_cantidad) > 1e-9 and alias_precio_ars is not None:
                alias_valor_ars = round(alias_cantidad * alias_precio_ars, 2)
                valor_ars = (valor_ars or 0.0) + alias_valor_ars
                # Cantidad mostrada: se reexpresa el Valor ARS COMBINADO
                # en unidades del activo principal (equivalente en BTC),
                # para que "Cantidad x Precio ARS = Valor ARS" se siga
                # cumpliendo a simple vista aunque la plata real este
                # repartida entre dos instrumentos (el propio + el alias).
                if precio_ars:
                    cantidad = valor_ars / precio_ars

        # Costo neto / P&L: solo tiene sentido para activos operados en
        # Cocos Capital (fuente yfinance) y con posicion abierta. La
        # parte manual (si la hay) no tiene costo de base conocido, asi
        # que el P&L sigue reflejando unicamente el costo de lo comprado
        # por el broker -- no se pretende inventar un costo para lo
        # cargado a mano.
        costo_neto = None
        pnl_ars = None
        pnl_pct = None
        precio_promedio_compra = None
        if fuente == "yfinance" and cantidad and abs(cantidad) > 1e-9:
            costo_neto = costos_netos_byma.get(ticker)
            if costo_neto is not None and valor_ars is not None:
                pnl_ars = round(valor_ars - costo_neto, 2)
                if abs(costo_neto) > 1e-9:
                    pnl_pct = round(pnl_ars / costo_neto * 100, 2)
            # Precio Promedio de Compra = Costo Neto ARS / Cantidad -- misma
            # base (y misma limitacion documentada arriba: costo_neto solo
            # cubre lo comprado via Cocos Capital, no la parte manual si la
            # hay) que ya usa el P&L de esta fila, asi que hereda el mismo
            # caveat: exacto si solo hubo compras, aproximado si hubo
            # ventas parciales o tenencia manual mezclada con el mismo
            # ticker (ver calcular_costo_neto_byma).
            if costo_neto is not None:
                precio_promedio_compra = round(costo_neto / cantidad, 2)

        filas.append(
            {
                "Ticker": ticker,
                "Categoria": datos["categoria"],
                "Cantidad": cantidad,
                "Precio Actual": precio_actual,
                "Moneda": moneda,
                "Precio ARS": precio_ars,
                "Valor ARS": valor_ars,
                "% Real": None,  # se completa abajo, una vez que se conoce el total
                "Costo Neto ARS": round(costo_neto, 2) if costo_neto is not None else None,
                "Precio Promedio Compra ARS": precio_promedio_compra,
                "P&L ARS": pnl_ars,
                "P&L %": pnl_pct,
                "Alias Ticker": alias_ticker,
                "Alias Precio Actual": alias_precio_actual,
                "Alias Moneda": alias_moneda,
                "Alias Precio ARS": alias_precio_ars,
            }
        )

    # --- Activos "huerfanos": tienen posicion real (comprada via Cocos
    # Capital, detectada en el CSV) y/o tenencia manual cargada, pero el
    # ticker NO esta en la configuracion objetivo. Antes (v6.0 original)
    # esto solo contemplaba la parte manual -- un ticker comprado por
    # CSV pero nunca agregado a portfolio_config.json quedaba TOTALMENTE
    # afuera de la tabla (solo se avisaba por consola). v6.1: se unifica
    # el set de huerfanos = (tickers con posicion CSV) U (tickers con
    # tenencia manual), menos los que ya estan en la config, y se suma
    # la cantidad de AMBAS fuentes con la misma regla que los activos de
    # config (nunca una pisa a la otra).
    #
    # Se cotizan con get_precio_generico (no tienen un
    # ticker_yfinance propio en la config) y se suman al
    # Valor Total igual, con Categoria = la declarada en el editor
    # manual (o "(Fuera de Objetivo)" si solo viene del CSV, sin carga
    # manual). El 0% Objetivo se resuelve en core.rebalancer, no aca:
    # esta tabla solo refleja tenencia, no metas.
    tickers_huerfanos = (
        set(posiciones_byma.keys()) | set(posiciones_especie.keys()) | set(cantidades_manuales.keys())
    ) - tickers_de_config

    # dolar_ccl_cache ya viene definido (posiblemente ya resuelto) desde
    # el loop principal de arriba -- se reutiliza tal cual en vez de
    # volver a declararlo, para no duplicar la consulta a dolarapi.com.
    huerfanos_sin_cotizar: List[str] = []
    for ticker in sorted(tickers_huerfanos):
        cantidad_automatica = posiciones_byma.get(ticker, 0.0) + posiciones_especie.get(ticker, 0.0)
        cantidad_manual = cantidades_manuales.get(ticker, 0.0)
        cantidad = cantidad_automatica + cantidad_manual
        if abs(cantidad) <= 1e-9:
            # Posicion neteada a cero (ej. compraste y vendiste todo un
            # ticker que ya no esta en la config, o una carga manual que
            # se cancela contra una venta del CSV): no tiene sentido
            # mostrar una fila con Cantidad 0.
            continue

        try:
            if dolar_ccl_cache is None:
                dolar_ccl_cache = get_dolar_ccl()
        except MarketDataError:
            dolar_ccl_cache = None

        precio_actual = moneda = precio_ars = None
        try:
            cotizacion = get_precio_generico(ticker, dolar_ccl=dolar_ccl_cache)
            precio_actual, moneda, precio_ars = (
                cotizacion.precio,
                cotizacion.moneda,
                cotizacion.precio_ars,
            )
        except MarketDataError as e:
            huerfanos_sin_cotizar.append(ticker)
            print(f"[holdings] Tenencia huerfana '{ticker}' sin cotizacion: {e}")

        valor_ars = round(cantidad * precio_ars, 2) if precio_ars is not None else None

        # Costo neto / P&L: igual que en el loop de config, solo tiene
        # sentido si hubo Compras/Venta reales via Cocos Capital para
        # este ticker (la parte manual no tiene costo de base conocido).
        costo_neto = costos_netos_byma.get(ticker)
        pnl_ars = None
        pnl_pct = None
        precio_promedio_compra = None
        if costo_neto is not None and valor_ars is not None:
            pnl_ars = round(valor_ars - costo_neto, 2)
            if abs(costo_neto) > 1e-9:
                pnl_pct = round(pnl_ars / costo_neto * 100, 2)
        if costo_neto is not None and cantidad and abs(cantidad) > 1e-9:
            precio_promedio_compra = round(costo_neto / cantidad, 2)

        filas.append(
            {
                "Ticker": ticker,
                "Categoria": categorias_manuales.get(ticker) or CATEGORIA_FUERA_DE_OBJETIVO,
                "Cantidad": cantidad,
                "Precio Actual": precio_actual,
                "Moneda": moneda,
                "Precio ARS": precio_ars,
                "Valor ARS": valor_ars,
                "% Real": None,
                "Costo Neto ARS": round(costo_neto, 2) if costo_neto is not None else None,
                "Precio Promedio Compra ARS": precio_promedio_compra,
                "P&L ARS": pnl_ars,
                "P&L %": pnl_pct,
            }
        )

    # --- Cash de dividendos (v6.4) -------------------------------------
    # Saldo NO invertido acumulado por dividendos en efectivo (ver
    # `calcular_cash_dividendos` y el docstring del modulo). Se agrega
    # como una fila propia mas -- igual que un huerfano -- para que
    # sume al Valor Total y a "% Real" sin necesidad de tocar el resto
    # del pipeline (rebalanceo, equity curve, etc. la ven como cualquier
    # otra fila). Se omite si el saldo neteo a ~0 (ninguna cuenta con
    # dividendos, o dividendos + notas de debito que se cancelan).
    cash_dividendos = calcular_cash_dividendos(movimientos)
    if abs(cash_dividendos) > 1e-9:
        filas.append(
            {
                "Ticker": TICKER_CASH,
                "Categoria": CATEGORIA_CASH,
                "Cantidad": None,
                "Precio Actual": None,
                "Moneda": "ARS",
                "Precio ARS": None,
                "Valor ARS": round(cash_dividendos, 2),
                "% Real": None,
                "Costo Neto ARS": None,
                "Precio Promedio Compra ARS": None,
                "P&L ARS": None,
                "P&L %": None,
            }
        )

    tenencia = pd.DataFrame(filas, columns=COLUMNAS_SALIDA)

    total_ars = tenencia["Valor ARS"].sum(skipna=True)
    if total_ars:
        tenencia["% Real"] = (tenencia["Valor ARS"] / total_ars * 100).round(2)

    tenencia = tenencia.sort_values(
        "Valor ARS", ascending=False, na_position="last"
    ).reset_index(drop=True)

    # Nota: antes de v6.1 aca se llamaba a una funcion que solo AVISABA
    # por consola sobre tickers con posicion CSV fuera de la config, sin
    # mostrarlos en la tabla. Ya no hace falta: ahora esos tickers son
    # justamente los "huerfanos" del bloque de arriba, que SI aparecen
    # como fila en `tenencia` con su Valor ARS y % Real.

    return tenencia


if __name__ == "__main__":
    tabla = calcular_tenencia_actual()
    total = tabla["Valor ARS"].sum(skipna=True)

    with pd.option_context("display.float_format", lambda x: f"{x:,.2f}"):
        print(tabla.to_string(index=False))

    print()
    if total:
        print(f"Valor total del portafolio: {total:,.2f} ARS")
    else:
        print("No se pudo valuar el portafolio (sin cotizaciones disponibles).")
