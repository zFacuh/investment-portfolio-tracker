"""
core/historical_curve.py

Modulo de Curva Historica de Valor de Portafolio ("Equity Curve") -- v6.2.

El CSV de movimientos de Cocos Capital (ver core/csv_parser.py) solo trae
el PRECIO DE EJECUCION de cada operacion, en el dia exacto que se hizo esa
compra/venta -- no una cotizacion diaria continua. Para poder graficar
"cuanto valia mi portafolio" en CUALQUIER dia (no solo los dias que
operaste), este modulo cruza dos series independientes:

  1. Inventario diario (CUANTOS nominales de cada ticker tenias, dia por
     dia): se reconstruye 100% a partir del CSV, acumulando (cumsum) la
     'cantidad' neta de cada operacion de Compra/Venta a lo largo del
     tiempo. Entre dos operaciones (fines de semana, feriados, o
     simplemente dias sin trading) el inventario se mantiene constante
     (Forward Fill).

  2. Precio diario de cierre de cada ticker (CUANTO valia cada nominal
     ese dia), descargado de yfinance ('Close', sufijo ".BA" -- misma
     convencion CEDEAR/BYMA que core.market_data.get_precio_generico).
     yfinance no publica precio los fines de semana/feriados: tambien se
     completa con Forward Fill para que ambas matrices (inventario y
     precio) tengan exactamente las mismas fechas.

Valor Total ARS de un dia = suma, para cada ticker, de (nominales ese
dia x precio de cierre ese dia).

v6.1 agrego una TERCERA serie, "Capital Invertido" -- cuanta plata "de tu
bolsillo" llevas puesta, acumulada, neto de lo que recuperaste en
ventas. A diferencia de las dos de arriba, esta NO necesita yfinance: sale
100% del CSV, acumulando (cumsum) el 'total' (negativo en Compra, salida
de caja; positivo en Venta, entrada de caja -- 'total' ya incluye
comision/iva/otros, ver csv_parser.py) de cada operacion de Compra/Venta,
con el signo dado vuelta (una Compra SUMA al capital invertido, una Venta
RESTA). La diferencia dia a dia entre "Valor Total" y "Capital Invertido"
es la ganancia/perdida NO realizada de la cartera.

v6.2 -- FILTRO DE CONSISTENCIA ("Universo Cerrado"), IMPORTANTE:
  En v6.1 el Capital Invertido sumaba el gasto de TODAS las operaciones
  de Compra/Venta, incluidas las de tickers que despues quedaban afuera
  de "Valor de Mercado" por no tener precio en yfinance (tipicamente
  bonos como AL30/GD38). Eso comparaba peras con manzanas: se cobraba el
  costo de un activo pero se lo valuaba en $0 (porque no esta en el
  inventario valuado), inflando artificialmente una "perdida" que no es
  real -- es un agujero de datos, no una perdida de mercado.

  Ahora el Capital Invertido se calcula EXCLUSIVAMENTE sobre
  `tickers_incluidos` (los que SI devolvieron precio historico de
  yfinance) -- ver `calcular_curva_historica`, que primero descarga los
  precios y recien DESPUES filtra `operaciones` a ese mismo universo
  antes de llamar a `_serie_capital_invertido_diario`. Un ticker sin
  precio (ej. un bono) queda TOTALMENTE afuera de las dos curvas, no
  solo de una: ni suma a Valor de Mercado ni a Capital Invertido. La
  comparacion entre las dos lineas del grafico queda matematicamente
  justa -- ambas describen exactamente la misma canasta de activos.

Que operaciones/instrumentos NO entran en esta curva (a proposito):
  - Depositos y retiros de efectivo ("Recibo De Cobro", "Orden De Pago"):
    no tienen 'ticker' resuelto en el CSV (columna 'instrumento' vacia),
    asi que el filtro de tipo_operacion_norm + ticker.notna() ya los deja
    afuera solos.
  - FCI ("Liquidacion Suscripcion/Rescate Fci", ej. "FCI COCOS
    RENDIMIENTO"): tienen su propio tipo_operacion_norm
    (FCI_SUSCRIPCION/FCI_RESCATE, ver core.csv_parser.MAPA_TIPO_OPERACION),
    DISTINTO de COMPRA/VENTA -- tambien quedan afuera solos, sin logica
    extra.
  - Bonos (renta fija, ej. AL30, GD38) y CUALQUIER otro ticker sin
    precio en yfinance: a diferencia de los dos casos de arriba, un bono
    SI opera via 'Compra'/'Venta' igual que un CEDEAR (ver la nota en
    core/csv_parser.py), asi que el filtro de tipo de operacion NO lo
    excluye por si solo. Se descarta explicitamente de AMBAS curvas (ver
    v6.2 arriba) porque yfinance no publica precio para tickers de renta
    fija de BYMA bajo la convencion "<ticker>.BA" (la descarga devuelve
    vacio) -- exactamente el mismo mecanismo de "tickers_sin_datos" que
    ya usa core/analytics.py para activos sin historico, no una lista de
    bonos hardcodeada a mano. Se informan en
    `ResultadoCurvaHistorica.tickers_sin_datos` para que la UI avise
    cuales quedaron afuera y por que.

Este modulo es agnostico de Streamlit a proposito (como el resto de
core/): no cachea nada el mismo -- el cacheo (@st.cache_data, con un TTL
largo porque esto descarga potencialmente mas de un anio de historico
diario de varios activos) vive en app.py, igual que
_cargar_analitica()/calcular_analitica_riesgo().

v6.4 -- Dividendos y cash de cuenta en la curva. Antes de esta version
el inventario diario y el Capital Invertido solo se calculaban sobre
COMPRA/VENTA, exactamente como en core/holdings.py (ver el docstring de
ese modulo para el detalle de por que el broker registra dividendos en
efectivo y en especie bajo tipos de operacion distintos). Mismo
criterio se aplica aca, sobre las TRES series de este modulo:

  - Inventario diario: ahora TAMBIEN acumula Dividendo En Especie
    cuando resuelve un ticker real (ej. GD38) -- ver
    `OPERACIONES_QUE_MUEVEN_POSICION`, que paso a incluir
    "DIVIDENDO_ESPECIE" ademas de "COMPRA"/"VENTA". Nominales "gratis"
    recibidos como dividendo pasan a valuarse en Valor de Mercado igual
    que los comprados, desde el dia que se recibieron.
  - Capital Invertido: a proposito NO cambia -- sigue calculandose
    exclusivamente sobre COMPRA/VENTA (`OPERACIONES_CAPITAL_INVERTIDO`).
    Sumarle el 'total' de un Dividendo En Especie inflaria Capital
    Invertido con plata que nunca saliste de tu bolsillo (ademas, ese
    'total' es la comision retenida, no el valor del dividendo -- ver
    core/holdings.py).
  - Cash de dividendos (serie nueva): Dividendo + Ajuste Dividendo
    (siempre cash, sin ticker) y Dividendo En Especie SIN ticker
    resuelto (pagado en moneda, no en nominales -- mismo caso que en
    core/holdings.py) se acumulan dia a dia y se SUMAN a Valor Total,
    otra vez sin tocar Capital Invertido -- ver
    `_serie_cash_dividendos_diario`. El resultado: recibir un dividendo
    sube la Equity Curve el dia que se cobra (como deberia, es
    retorno), sin ensuciar la linea de "cuanto plata propia puse".

v7.x -- CUARTA serie OPCIONAL, "Valor Benchmark" (comparacion contra uno
o varios indices, ej. SPY/QQQ/EEM/BTC via IBIT): responde la pregunta
"que hubiera pasado si, en vez de mi cartera real, hubiera puesto
exactamente la misma plata -- mismos montos, mismos dias -- en
`benchmark`". Se activa pasando `benchmarks` (lista) a
`calcular_curva_historica` (por default None/vacia: sin esta cuarta
serie, no cambia el comportamiento de nadie que no lo pida
explicitamente). Cada entrada de la lista es un dict
{"ticker": simbolo_yfinance, "label": nombre_a_mostrar} -- `label` deja
mostrar un nombre distinto del simbolo que realmente cotiza (ej. BTC no
tiene un ".BA" propio, se compara via el CEDEAR "IBIT").

  Como se simula (`_serie_benchmark_diario`, UNA vez por benchmark): el
  flujo de caja DIARIO real (mismo que ya arma `capital_invertido_ars`
  -- se REUTILIZA esa misma serie via .diff(), no se recalcula aparte)
  se "reinvierte" ese mismo dia al precio de cierre de CADA benchmark
  ESE dia: un dia de Compra (flujo positivo) simula comprar nominales
  del benchmark; un dia de Venta (flujo negativo, entra plata) simula
  vender ese mismo MONTO en pesos del benchmark (no la misma
  proporcion de la posicion). Los nominales simulados se acumulan
  (cumsum) y se valuan al precio de cierre de cada dia, exacto mismo
  mecanismo que Valor de Mercado con el inventario real -- y como el
  flujo de caja de ORIGEN es el mismo para todos los benchmarks (el
  mismo `capital_invertido_ars`), las N lineas de benchmark son
  directamente comparables entre si ademas de contra la cartera real.

  UNIVERSO CERRADO aplicado a los benchmarks (lo que pide reusar el
  mismo criterio de v6.2, para las FECHAS): el flujo de caja que se
  reinvierte es el de `operaciones_capital_incluidas` -- el MISMO
  conjunto ya restringido a `tickers_incluidos` que genera
  `capital_invertido_ars` -- no el total bruto de todas las
  operaciones. Asi "Capital Invertido" y cada "Valor Benchmark" arrancan
  de EXACTAMENTE los mismos pesos, en las mismas fechas. Ademas, TODOS
  los benchmarks se descargan en el MISMO batch de yfinance que el
  resto de los tickers de la cartera (misma funcion
  `_descargar_precios_ba`, misma convencion ".BA", una sola llamada de
  red para todo), asi que un benchmark sin historico disponible (ticker
  mal escrito, o que no cotiza como CEDEAR en BYMA) queda AFUERA de la
  curva -- simplemente no aparece en `ResultadoCurvaHistorica.valores_benchmark`,
  con una advertencia propia, en vez de inventar un valor o de bloquear
  a los DEMAS benchmarks o a la cartera real. Mismo principio de "si no
  hay dato, se excluye" que ya rige `tickers_sin_datos`.

  LIMITACION documentada: si un benchmark tiene precio a partir de una
  fecha POSTERIOR al primer aporte real (dato parcial, no ausente del
  todo), los aportes anteriores a esa fecha se valuan al precio mas
  VIEJO disponible (backward-fill acotado al arranque de la serie) --
  es la unica aproximacion posible sin inventar un precio que no existe;
  en la practica, con benchmarks liquidos como SPY/QQQ (cotizan desde
  hace decadas), esto casi nunca aplica -- puede importar mas para un
  ETF mas nuevo (ej. IBIT, que recien empezo a cotizar en 2024).

  Los benchmarks default (si no se pasa nada a esta funcion) se
  resuelven en la UI/config, no aca -- ver
  `core.config_manager.get_benchmark_tickers` y
  `meta.benchmark_tickers` en portfolio_config.json (default solo SPY
  si no esta configurado). Este modulo sigue siendo agnostico de
  Streamlit/config: recibe la lista ya resuelta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

# Timeout de red explicito (mismo criterio que core/market_data.py, ver
# su docstring "Timeouts de red"): sin esto, una conexion de yfinance
# colgada podia bloquear la sesion de Streamlit indefinidamente al
# reconstruir la curva historica. Idem el circuit breaker de rate
# limiting (ver "Rate limiting de Yahoo Finance -- CIRCUIT BREAKER" en
# ese mismo docstring) -- se comparte el mismo estado de cooldown que
# market_data.py y analytics.py, no uno propio: un rate limit detectado
# en CUALQUIERA de los tres modulos pausa a los tres por igual.
from core.market_data import (
    HTTP_TIMEOUT,
    RATE_LIMIT_COOLDOWN_SEG,
    activar_cooldown_rate_limit,
    con_reintento_rate_limit,
    en_cooldown_rate_limit,
    get_yf_session,
)

# Mismo criterio que core.holdings.OPERACIONES_QUE_MUEVEN_POSICION:
# Compra/Venta, mas Dividendo En Especie cuando resuelve un ticker real
# (ver docstring de ambos modulos), cambian la cantidad de nominales en
# cartera -- y por lo tanto el inventario diario de este modulo.
OPERACIONES_QUE_MUEVEN_POSICION = {"COMPRA", "VENTA", "DIVIDENDO_ESPECIE"}

# Subconjunto usado SOLO para Capital Invertido (plata puesta "de tu
# bolsillo"): a diferencia del inventario, un Dividendo En Especie NO
# suma aca -- ver v6.4 en el docstring del modulo.
OPERACIONES_CAPITAL_INVERTIDO = {"COMPRA", "VENTA"}

# Dividendos en efectivo (o equivalente): DIVIDENDO/AJUSTE_DIVIDENDO
# nunca tienen ticker, y DIVIDENDO_ESPECIE sin ticker resuelto es en la
# practica lo mismo (pagado en moneda, no en nominales de un activo) --
# ver core/holdings.py. Se acumulan como cash, no como posicion.
OPERACIONES_DIVIDENDO_CASH = {"DIVIDENDO", "AJUSTE_DIVIDENDO", "DIVIDENDO_ESPECIE"}


class HistoricalCurveError(Exception):
    """Error al reconstruir la curva historica de valor del portafolio."""


@dataclass
class ResultadoCurvaHistorica:
    valor_ars: pd.Series  # index: fecha (diaria, incluye fines de semana); valores: Valor Total ARS
    capital_invertido_ars: pd.Series  # MISMO indice que valor_ars (ver _rango_diario)
    tickers_incluidos: List[str]
    tickers_sin_datos: List[str] = field(default_factory=list)
    advertencias: List[str] = field(default_factory=list)
    # v7.x -- cuarta serie opcional, MULTIPLE (ver docstring del modulo):
    # {label -> serie ARS, MISMO indice que valor_ars}. Solo incluye los
    # benchmarks pedidos que SI tuvieron precio disponible -- uno sin
    # datos simplemente no aparece aca (ver advertencias). Vacio si no
    # se pidio ningun benchmark.
    valores_benchmark: Dict[str, pd.Series] = field(default_factory=dict)
    # v10.0 -- series intermedias expuestas para core/performance.py
    # (rendimiento por activo/categoria, compras sobre el grafico, etc.).
    # Todas recortadas al MISMO indice que valor_ars. Opcionales (None)
    # para no romper a quien construya este resultado a mano (tests).
    inventario: Optional[pd.DataFrame] = None  # fecha x ticker incluido: nominales en cartera
    precios_diarios: Optional[pd.DataFrame] = None  # fecha x ticker (incluidos + benchmarks): cierre ARS, ffill
    capital_por_ticker: Optional[pd.DataFrame] = None  # fecha x ticker incluido: capital neto acumulado (-total)
    cash_dividendos: Optional[pd.Series] = None  # cash acumulado por dividendos (ya sumado a valor_ars)


# ---------------------------------------------------------------------------
# 0. Base compartida: operaciones de Compra/Venta + rango de fechas comun
# ---------------------------------------------------------------------------
def _operaciones_por_tipos(movimientos: pd.DataFrame, tipos: set) -> pd.DataFrame:
    """
    Sub-DataFrame de movimientos limitado a los `tipos` de operacion
    normalizada dados, con 'ticker' y 'fechaEjecucion' resueltos --
    base compartida por el inventario diario, el Capital Invertido y el
    filtro cruzado de "Universo Cerrado" (v6.2), para que todas las
    series salgan de universos consistentes entre si y compartan
    exactamente el mismo rango de fechas (ver _rango_diario).
    """
    return movimientos[
        movimientos["tipo_operacion_norm"].isin(tipos)
        & movimientos["ticker"].notna()
        & movimientos["fechaEjecucion"].notna()
    ]


def _rango_diario(operaciones: pd.DataFrame) -> pd.DatetimeIndex:
    """pd.date_range diario (incluye fines de semana) desde la primera
    operacion de `operaciones` hasta hoy -- el eje X comun de TODAS las
    series de este modulo (inventario, precios, Capital Invertido)."""
    return pd.date_range(
        start=operaciones["fechaEjecucion"].dt.normalize().min(),
        end=pd.Timestamp.today().normalize(),
        freq="D",
    )


# ---------------------------------------------------------------------------
# 1. Inventario diario (a partir del CSV, sin tocar yfinance)
# ---------------------------------------------------------------------------
def _matriz_inventario_diario(operaciones: pd.DataFrame, rango_completo: pd.DatetimeIndex) -> pd.DataFrame:
    """
    A partir de `operaciones` (ver _operaciones_por_tipos, llamada con
    OPERACIONES_QUE_MUEVEN_POSICION), devuelve una matriz fecha x ticker
    (indice = `rango_completo`, UNA fila por dia calendario, incluyendo
    fines de semana) con la cantidad de nominales EN CARTERA ese dia --
    inventario acumulado, no el movimiento de ese dia puntual.

    Solo usa 'fechaEjecucion', 'ticker' y 'cantidad' -- 'cantidad' ya
    viene firmada (positiva en Compra y en Dividendo En Especie,
    negativa en Venta, ver core.holdings.calcular_posiciones_byma /
    calcular_posiciones_dividendo_especie), asi que un cumsum directo
    alcanza para el neto.
    """
    if operaciones.empty:
        return pd.DataFrame(index=rango_completo)

    # Si hubo mas de una operacion del mismo ticker el mismo dia, se
    # suman antes de armar la matriz (groupby ya lo hace).
    movimiento_diario = (
        operaciones.groupby([operaciones["fechaEjecucion"].dt.normalize(), "ticker"])["cantidad"]
        .sum()
        .unstack("ticker")
    )

    # reindex a TODOS los dias calendario (rellena con 0 los dias sin
    # movimiento) y despues cumsum: cada celda pasa de "cuanto se
    # movio ESE dia" a "cuanto tenia acumulado hasta ESE dia".
    inventario = movimiento_diario.reindex(rango_completo).fillna(0.0).cumsum()
    return inventario


# ---------------------------------------------------------------------------
# 1b. Capital Invertido diario (idem, tampoco toca yfinance)
# ---------------------------------------------------------------------------
def _serie_capital_invertido_diario(operaciones: pd.DataFrame, rango_completo: pd.DatetimeIndex) -> pd.Series:
    """
    Capital Invertido acumulado (ARS): cuanta plata "de tu bolsillo"
    llevas puesta en compras de instrumentos, dia por dia, neta de lo
    que recuperaste en ventas.

    Usa la columna 'total' del CSV (mismo criterio que
    core.holdings.calcular_costo_neto_byma para el costo neto por
    ticker): 'total' viene NEGATIVO en una Compra (salida de caja) y
    POSITIVO en una Venta (entrada de caja) -- ya incluye
    comision/iva/otros, no solo cantidad*precio. El delta diario de
    Capital Invertido es -total: una Compra de $10.000 (total=-10000)
    suma +10000 al capital invertido puesto; una Venta que recupera
    $4.000 (total=+4000) resta 4000.

    IMPORTANTE (v6.2, "Universo Cerrado"): `operaciones` que reciba esta
    funcion tiene que venir YA FILTRADO por `calcular_curva_historica` a
    solo los tickers que tienen precio de yfinance (`tickers_incluidos`)
    -- esta funcion en si misma no sabe nada de yfinance ni filtra por
    su cuenta, simplemente suma lo que le pasen. Si se le pasara el
    universo completo de operaciones (incluyendo tickers sin precio,
    tipicamente bonos), el Capital Invertido quedaria sumando el gasto
    de activos que "Valor de Mercado" valua en $0 por no poder
    cotizarlos -- una distorsion de perdida artificial, no real.
    """
    if operaciones.empty:
        return pd.Series(0.0, index=rango_completo)

    gasto_diario = -operaciones.groupby(operaciones["fechaEjecucion"].dt.normalize())["total"].sum()
    capital_invertido = gasto_diario.reindex(rango_completo).fillna(0.0).cumsum()
    return capital_invertido


# ---------------------------------------------------------------------------
# 1c. Cash de dividendos diario (v6.4, tampoco toca yfinance)
# ---------------------------------------------------------------------------
def _es_instrumento_dolar(instrumento: pd.Series) -> pd.Series:
    """True si el 'instrumento' es una moneda dolar (ej. "Dolar Especie CV
    7000", "Dolar estadounidense"). Mismo criterio que
    core.performance.historial_dividendos."""
    return instrumento.fillna("").str.lower().str.contains("dólar|dolar", regex=True)


def _serie_cash_dividendos_diario(
    movimientos: pd.DataFrame,
    rango_completo: pd.DatetimeIndex,
    ccl_diario_serie: Optional[pd.Series] = None,
) -> pd.Series:
    """
    Cash acumulado (ARS) proveniente de dividendos en efectivo:
    DIVIDENDO + AJUSTE_DIVIDENDO (nunca tienen ticker) y
    DIVIDENDO_ESPECIE cuando NO resuelve un ticker real (pagado en
    moneda, no en nominales de un activo -- ver core/holdings.py y el
    docstring de este modulo, v6.4). Suma directo 'total' (ya neto de
    comision/IVA) y acumula (cumsum) dia a dia.

    A proposito NO se resta de Capital Invertido: es plata que entro
    por rendimiento de la cartera, no plata puesta de tu bolsillo. Se
    recibe `movimientos` COMPLETO (no el DataFrame ya filtrado a
    Compra/Venta de las otras funciones de esta seccion) porque estas
    filas no tienen 'ticker', asi que no participan del filtro de
    "Universo Cerrado" (v6.2) ni de ningun otro filtro por ticker.

    v10.1 -- DIVIDENDOS EN DOLARES (fix): en el CSV de Cocos, un
    Dividendo En Especie con instrumento "Dolar..." trae los USD
    cobrados en 'cantidad', y en 'total' solo la retencion/comision en
    ARS (centavos negativos). Antes se sumaba solo 'total', asi que los
    dividendos de CEDEARs (que se pagan en dolares) entraban a la curva
    como una pequena PERDIDA en vez de como ingreso. Ahora su valor es
    total + cantidad x CCL del dia de cobro (mismo criterio que
    core.performance.historial_dividendos). El cash queda fijo en ARS
    desde ese dia (no se revalua con el CCL posterior). Si no hay CCL
    (`ccl_diario_serie` None), se mantiene el comportamiento anterior y
    el caller avisa.
    """
    candidatos = movimientos[
        movimientos["tipo_operacion_norm"].isin(OPERACIONES_DIVIDENDO_CASH)
        & movimientos["fechaEjecucion"].notna()
    ]
    cash_directo = candidatos[candidatos["tipo_operacion_norm"] != "DIVIDENDO_ESPECIE"]
    especie_sin_ticker = candidatos[
        (candidatos["tipo_operacion_norm"] == "DIVIDENDO_ESPECIE") & candidatos["ticker"].isna()
    ]
    combinado = pd.concat([cash_directo, especie_sin_ticker])
    if combinado.empty:
        return pd.Series(0.0, index=rango_completo)

    fechas = combinado["fechaEjecucion"].dt.normalize()
    monto = combinado["total"].fillna(0.0).astype(float)
    if ccl_diario_serie is not None and "instrumento" in combinado.columns:
        es_usd = (combinado["tipo_operacion_norm"] == "DIVIDENDO_ESPECIE") & _es_instrumento_dolar(
            combinado["instrumento"]
        )
        if es_usd.any():
            ccl = ccl_diario_serie.dropna().sort_index()
            pos = ccl.index.searchsorted(fechas[es_usd].values, side="right") - 1
            pos = pos.clip(0, len(ccl) - 1)
            usd = combinado.loc[es_usd, "cantidad"].fillna(0.0).astype(float)
            monto.loc[es_usd] = monto.loc[es_usd] + usd.values * ccl.values[pos]

    ingreso_diario = monto.groupby(fechas).sum()
    return ingreso_diario.reindex(rango_completo).fillna(0.0).cumsum()


# ---------------------------------------------------------------------------
# 1d. Valor Benchmark diario (v7.x -- comparacion contra un indice)
# ---------------------------------------------------------------------------
def _serie_benchmark_diario(
    capital_invertido_ars: pd.Series,
    precios_benchmark: pd.Series,
    rango_completo: pd.DatetimeIndex,
) -> pd.Series:
    """
    Simula reinvertir, dia por dia, el MISMO flujo de caja real que ya
    generó `capital_invertido_ars` -- pero comprando/vendiendo
    `benchmark_ticker` al precio de ese dia en vez de la cartera real.
    Ver "CUARTA serie OPCIONAL" en el docstring del modulo para el
    detalle completo (por que se reutiliza exactamente ese flujo de
    caja, no uno recalculado aparte -- es lo que garantiza el mismo
    "Universo Cerrado" que ya aplica `capital_invertido_ars`).

    `capital_invertido_ars` es la serie CUMULATIVA ya calculada (mismo
    `rango_completo`, sin truncar todavia); se recupera el flujo DIARIO
    con .diff() (el primer dia no tiene "diferencia" previa, se usa su
    propio valor). `precios_benchmark` ya viene alineada a
    `rango_completo` con forward-fill + backward-fill (ver el caller,
    `calcular_curva_historica`, para el porque del backward-fill).
    """
    flujo_diario = capital_invertido_ars.diff()
    flujo_diario.iloc[0] = capital_invertido_ars.iloc[0]

    # Si algun dia el precio del benchmark sigue sin dato (NaN, solo
    # deberia pasar si TODA la serie de precios es NaN -- caso ya
    # cubierto aparte por `benchmark_sin_datos` en el caller), ese dia
    # no aporta nominales simulados en vez de reventar con una division
    # por NaN silenciosa.
    nominales_dia = (flujo_diario / precios_benchmark).where(precios_benchmark.notna(), 0.0)
    nominales_acumulados = nominales_dia.cumsum()
    return nominales_acumulados * precios_benchmark


# ---------------------------------------------------------------------------
# 2. Precios historicos de cierre (yfinance, convencion ".BA" de BYMA)
# ---------------------------------------------------------------------------
def _descargar_uno(simbolo: str, fecha_inicio) -> Optional[pd.Series]:
    """Descarga UN ticker (fallback si el batch entero falla)."""
    try:
        hist = con_reintento_rate_limit(
            yf.Ticker(simbolo, session=get_yf_session()).history,
            start=fecha_inicio,
            auto_adjust=False,
            timeout=HTTP_TIMEOUT,
        )
        if hist.empty or "Close" not in hist.columns:
            return None
        serie = hist["Close"].dropna()
        if serie.empty:
            return None
        # yf.Ticker(...).history() devuelve el indice con tz -- se lo
        # sacamos para poder alinearlo mas adelante con el indice
        # "naive" (sin tz) de la matriz de inventario.
        serie.index = serie.index.tz_localize(None)
        return serie
    except YFRateLimitError:
        # Silencioso a proposito: con_reintento_rate_limit ya avisa UNA
        # vez cuando se activa el cooldown global (ver core/market_data.py)
        # -- repetirlo por cada simbolo que cae en ese mismo cooldown
        # solo ensucia la consola.
        return None
    except Exception as e:
        # Incluye timeout (HTTP_TIMEOUT): se trata igual que cualquier
        # otro ticker sin historico descargable -- se excluye con este
        # aviso, no cuelga la curva.
        print(f"[historical_curve] Error descargando historico de {simbolo}: {e}")
        return None


def _descargar_precios_ba(tickers: List[str], fecha_inicio) -> Tuple[pd.DataFrame, List[str]]:
    """
    Descarga el cierre diario ('Close') de "<ticker>.BA" para cada
    ticker en `tickers`, desde `fecha_inicio` hasta hoy.

    Devuelve (precios, tickers_sin_datos):
      - precios: DataFrame fecha x ticker INTERNO (sin el sufijo .BA).
      - tickers_sin_datos: tickers sin historico descargable (tipico de
        bonos como AL30/GD38, que no cotizan en Yahoo Finance bajo la
        convencion ".BA" -- ver el modulo docstring).

    Mismo patron de robustez que
    core.analytics.descargar_precios_historicos: primero un unico
    batch (mas eficiente); si el batch entero revienta, reintenta
    ticker por ticker para que UN simbolo roto no tire abajo a los
    demas.

    Rate limiting (v7.x, circuit breaker -- ver "Rate limiting de Yahoo
    Finance -- CIRCUIT BREAKER" en core/market_data.py): yf.download()
    no relanza YFRateLimitError al caller -- lo atrapa por ticker
    adentro del pool de threads y deja esa columna vacia, sin que el
    batch "reviente" (no cae en el except de mas abajo) aunque TODOS
    los simbolos hayan sido rate-limitados. Si eso pasa (0 columnas
    descargadas sobre 2+ simbolos pedidos, senal fuerte de rate limit
    sistemico), se activa el cooldown global a mano ANTES de caer al
    fallback ticker por ticker -- ese fallback, gracias al cooldown ya
    activo (estado COMPARTIDO con core/market_data.py y
    core/analytics.py), corta cada simbolo al instante en vez de
    intentar contra la red de nuevo.
    """
    simbolos_por_ticker = {ticker: f"{ticker}.BA" for ticker in tickers}
    simbolos = list(simbolos_por_ticker.values())

    data_batch = None
    if en_cooldown_rate_limit():
        # Ni siquiera se intenta el batch -- ya sabemos que va a fallar
        # (cooldown activado por este modulo, por market_data.py, o por
        # analytics.py, da igual quien lo detecto primero).
        pass
    else:
        try:
            data_batch = yf.download(
                simbolos,
                start=fecha_inicio,
                progress=False,
                group_by="ticker",
                threads=True,
                auto_adjust=False,
                timeout=HTTP_TIMEOUT,
                session=get_yf_session(),
            )
        except Exception as e:
            # Incluye timeout del batch entero (HTTP_TIMEOUT): se
            # reintenta ticker por ticker mas abajo (cada uno con su
            # propio timeout), mismo tratamiento que un batch roto por
            # cualquier otra razon.
            print(f"[historical_curve] Error descargando precios en batch ({e}); reintento ticker por ticker.")
            data_batch = None

        if len(simbolos) >= 2 and data_batch is not None and data_batch.empty:
            ya_estaba_en_cooldown = en_cooldown_rate_limit()
            activar_cooldown_rate_limit()
            if not ya_estaba_en_cooldown:
                print(
                    f"[historical_curve] Los {len(simbolos)} simbolos pedidos volvieron vacios del "
                    f"batch (probable rate limit de yfinance) -- se pausan las consultas a "
                    f"yfinance por {RATE_LIMIT_COOLDOWN_SEG}s."
                )

    columnas: Dict[str, pd.Series] = {}
    tickers_sin_datos: List[str] = []
    for ticker, simbolo in simbolos_por_ticker.items():
        serie = None
        if data_batch is not None:
            try:
                sub = data_batch[simbolo] if len(simbolos) > 1 else data_batch
                if "Close" in sub.columns:
                    serie = sub["Close"].dropna()
                    if serie.empty:
                        serie = None
                    else:
                        serie.index = pd.DatetimeIndex(serie.index).tz_localize(None)
            except Exception:
                serie = None
        if serie is None:
            serie = _descargar_uno(simbolo, fecha_inicio)
        if serie is None:
            tickers_sin_datos.append(ticker)
        else:
            columnas[ticker] = serie

    if not columnas:
        return pd.DataFrame(), tickers_sin_datos

    precios = pd.DataFrame(columnas).sort_index()
    return precios, tickers_sin_datos


# ---------------------------------------------------------------------------
# 2b. Saneamiento de precios de yfinance (v10.0)
# ---------------------------------------------------------------------------
# Simbolo del subyacente en EE.UU. cuando no coincide con el ticker del CEDEAR.
SUBYACENTE_US = {"BRKB": "BRK-B", "BRKA": "BRK-A"}


def _precio_en_fechas(serie: pd.Series, fechas: pd.Series, max_dias: int = 5) -> pd.Series:
    """Ultimo precio valido de `serie` en o antes de cada fecha (hasta
    `max_dias` de antiguedad; si no, NaN)."""
    s = serie.dropna().sort_index()
    if s.empty:
        return pd.Series(float("nan"), index=fechas.index)
    pos = s.index.searchsorted(fechas.values, side="right") - 1
    out = []
    for p, f in zip(pos, fechas.values):
        if p < 0:
            out.append(float("nan"))
            continue
        fecha_px = s.index[p]
        out.append(float(s.iloc[p]) if (pd.Timestamp(f) - fecha_px).days <= max_dias else float("nan"))
    return pd.Series(out, index=fechas.index)


UMBRAL_PICO = 0.20  # salto de un dia que se considera sospechoso
TOLERANCIA_REGRESO = 0.05  # si al dia siguiente vuelve a +-5% del precio previo, era un error de datos


def _quitar_picos_aislados(
    precios: pd.DataFrame,
    advertencias: List[str],
    umbral: float = UMBRAL_PICO,
    tolerancia: float = TOLERANCIA_REGRESO,
) -> pd.DataFrame:
    """
    v10.2 -- Robustez de datos: yfinance a veces trae para BYMA un cierre
    absurdo de UN dia (un trade suelto a mal precio, un error de carga)
    que al dia siguiente desaparece. Ese pico inventa volatilidad, puede
    crear un drawdown falso y distorsiona el TWR de ese tramo.

    Regla (conservadora a proposito): un cierre se reemplaza por el del
    dia anterior SOLO si salta mas de `umbral` respecto del dia anterior
    Y al dia siguiente el precio vuelve a menos de `tolerancia` del
    anterior. Un movimiento real grande (ej. el rally post-elecciones de
    octubre 2025) no vuelve al dia siguiente, asi que no se toca. Cierres
    en 0 o negativos se descartan (quedan como sin dato y se completan
    con el ultimo precio valido). Todo cambio queda en `advertencias`.

    Por que no usar el subyacente en EE.UU. x CCL como fuente principal:
    los ratios de los CEDEARs cambian en el tiempo (ej. SPY paso de 20:1
    a 60:1) y sin el historial de ratios esa fuente meteria saltos falsos
    peores que los que corrige. Se sigue usando solo para completar huecos
    (ver _precio_sintetico_desde_subyacente), calibrado contra tus precios.
    """
    precios = precios.copy()
    corregidos: Dict[str, int] = {}
    for t in precios.columns:
        serie = precios[t].where(precios[t] > 0)
        validos = serie.dropna()
        if len(validos) >= 3:
            v = validos.values.astype(float).copy()
            n = 0
            for i in range(1, len(v) - 1):
                previo, actual, siguiente = v[i - 1], v[i], v[i + 1]
                if abs(actual / previo - 1) > umbral and abs(siguiente / previo - 1) < tolerancia:
                    v[i] = previo
                    n += 1
            if n:
                corregidos[t] = n
                serie.loc[validos.index] = v
        precios[t] = serie
    if corregidos:
        detalle = ", ".join(f"{t} ({n})" for t, n in sorted(corregidos.items()))
        advertencias.append(
            f"Se corrigieron picos aislados de un dia en los precios de yfinance (saltos de mas de "
            f"{umbral * 100:.0f}% que se revierten al dia siguiente, tipicos errores de datos): {detalle}."
        )
    return precios


def _sanear_precios(
    precios: pd.DataFrame,
    operaciones_capital: pd.DataFrame,
    inventario: pd.DataFrame,
    rango_completo: pd.DatetimeIndex,
    advertencias: List[str],
) -> pd.DataFrame:
    """
    Corrige dos problemas reales de los datos de yfinance para BYMA,
    usando tus propias operaciones del CSV como "verdad" (son precios
    reales a los que operaste):

    1. ESCALA: algunos tickers vienen en otra escala (ej. YPFD.BA viene
       dividido por 10). Si TODAS tus operaciones de un ticker estan a
       ~10^k veces el cierre de yfinance de ese dia (k != 0, con poca
       dispersion), se multiplica la serie por 10^k.

    2. HISTORIA INCOMPLETA: si yfinance recien tiene precio DESPUES de
       que ya tenias el activo (ej. META.BA solo desde 25/09/2026), esos
       dias se valuaban en $0 -- una caida falsa y despues una suba falsa.
       Se completan con un precio SINTETICO: cierre del subyacente en
       EE.UU. x CCL / ratio, con el ratio calibrado contra tus precios de
       compra (y el primer precio real de yfinance). Si eso no es posible
       (sin subyacente en EE.UU. o sin CCL), se interpola en escala
       logaritmica entre tus precios de operacion.

    Todo cambio queda informado en `advertencias`.
    """
    if "precio" not in operaciones_capital.columns:
        return precios  # sin precios de operacion no hay contra que validar
    precios = precios.copy()
    ops = operaciones_capital[operaciones_capital["precio"].fillna(0) > 0]

    # --- 1. Escala ---
    for t in precios.columns:
        o = ops[ops["ticker"] == t]
        if o.empty:
            continue
        px = _precio_en_fechas(precios[t], o["fechaEjecucion"].dt.normalize())
        ratios = (o["precio"] / px).replace([float("inf")], float("nan")).dropna()
        ratios = ratios[ratios > 0]
        if ratios.empty:
            continue
        import numpy as np

        logs = np.log10(ratios.values)
        k = int(round(float(np.median(logs))))
        if k != 0 and np.all(np.abs(logs - k) < 0.15):
            precios[t] = precios[t] * (10.0**k)
            advertencias.append(
                f"{t}: yfinance publica el precio en otra escala (x{10.0**k:g} respecto de tus "
                "operaciones reales); se corrigio en la curva historica."
            )

    # --- 2. Historia incompleta ---
    diaria = precios.reindex(precios.index.union(rango_completo)).sort_index()
    faltantes: List[str] = []
    for t in inventario.columns:
        if t not in precios.columns:
            continue
        tenencia = inventario[t].reindex(rango_completo).fillna(0.0) > 1e-12
        px_ff = diaria[t].ffill().reindex(rango_completo)
        hueco = tenencia & px_ff.isna()
        if not hueco.any():
            continue
        faltantes.append(t)
        primer_valido = precios[t].first_valid_index()
        o = ops[ops["ticker"] == t]
        relleno = _precio_sintetico_desde_subyacente(t, o, precios[t], rango_completo)
        metodo = "subyacente en EE.UU. x CCL"
        if relleno is None:
            relleno = _interpolar_precios_operaciones(o, precios[t], rango_completo)
            metodo = "interpolacion entre tus precios de operacion"
        if relleno is None:
            continue
        fechas_hueco = rango_completo[rango_completo < primer_valido] if primer_valido is not None else rango_completo
        diaria.loc[fechas_hueco, t] = relleno.reindex(fechas_hueco).values
        advertencias.append(
            f"{t}: yfinance no tiene precio antes del {primer_valido:%d/%m/%Y} y ya tenias el activo; "
            f"ese tramo se completo con {metodo}."
        )
    return diaria


# ---------------------------------------------------------------------------
# 2c. Benchmarks con dividendos (v10.1)
# ---------------------------------------------------------------------------
def _factor_retorno_total_us(ticker: str, fecha_inicio) -> Optional[pd.Series]:
    """
    Factor de "retorno total" (dividendos reinvertidos) de un benchmark,
    tomado del subyacente en EE.UU.: Adj Close / Close, normalizado a 1
    en el ultimo dato. Multiplicar el cierre del CEDEAR por este factor
    convierte una serie de solo-precio en una de retorno total.

    Por que del subyacente y no del ".BA": yfinance casi no registra los
    dividendos de los CEDEARs (medido: SPY.BA ajusta ~0,17% en un ano
    contra ~1,3% del SPY en EE.UU.). Devuelve None si no se puede
    descargar (el caller avisa y usa solo precio).
    """
    if en_cooldown_rate_limit():
        return None
    simbolo = SUBYACENTE_US.get(ticker, ticker)
    try:
        hist = con_reintento_rate_limit(
            yf.Ticker(simbolo, session=get_yf_session()).history,
            start=fecha_inicio,
            auto_adjust=False,
            timeout=HTTP_TIMEOUT,
        )
    except Exception as e:
        print(f"[historical_curve] No se pudo descargar el ajuste por dividendos de {simbolo}: {e}")
        return None
    if hist is None or hist.empty or "Adj Close" not in hist.columns or "Close" not in hist.columns:
        return None
    factor = (hist["Adj Close"] / hist["Close"]).dropna()
    factor = factor[factor > 0]
    if factor.empty:
        return None
    factor.index = pd.DatetimeIndex(factor.index).tz_localize(None).normalize()
    factor = factor[~factor.index.duplicated(keep="last")]
    return factor / factor.iloc[-1]


def _precio_retorno_total(precio: pd.Series, factor: pd.Series) -> pd.Series:
    """Aplica un factor de retorno total (ver _factor_retorno_total_us)
    a una serie de precios, alineando fechas (ffill/bfill)."""
    f = factor.reindex(factor.index.union(precio.index)).sort_index().ffill().bfill().reindex(precio.index)
    return precio * f.fillna(1.0)


def _precio_sintetico_desde_subyacente(
    ticker: str, ops: pd.DataFrame, serie_ba: pd.Series, rango: pd.DatetimeIndex
) -> Optional[pd.Series]:
    import numpy as np

    try:
        from core.macro_data import ccl_diario, get_ccl_historico

        ccl = ccl_diario(get_ccl_historico().serie, rango)
    except Exception:
        return None
    us = _descargar_uno(SUBYACENTE_US.get(ticker, ticker), rango.min() - pd.Timedelta(days=7))
    if us is None or us.empty:
        return None
    us_diario = us.reindex(us.index.union(rango)).sort_index().ffill().reindex(rango)
    sintetico_sin_ratio = us_diario * ccl  # ARS por accion del subyacente
    puntos = []
    for _, f in ops.iterrows():
        d = f["fechaEjecucion"].normalize()
        if d in sintetico_sin_ratio.index and pd.notna(sintetico_sin_ratio.loc[d]):
            puntos.append(sintetico_sin_ratio.loc[d] / f["precio"])
    primer = serie_ba.first_valid_index()
    if primer is not None and primer in sintetico_sin_ratio.index and pd.notna(sintetico_sin_ratio.loc[primer]):
        puntos.append(sintetico_sin_ratio.loc[primer] / float(serie_ba.loc[primer]))
    puntos = [p for p in puntos if p and np.isfinite(p) and p > 0]
    if not puntos:
        return None
    ratio = float(np.median(puntos))
    return sintetico_sin_ratio / ratio


def _interpolar_precios_operaciones(ops: pd.DataFrame, serie_ba: pd.Series, rango: pd.DatetimeIndex) -> Optional[pd.Series]:
    import numpy as np

    puntos = ops.groupby(ops["fechaEjecucion"].dt.normalize())["precio"].mean()
    primer = serie_ba.first_valid_index()
    if primer is not None:
        puntos.loc[primer] = float(serie_ba.loc[primer])
    puntos = puntos[puntos > 0].sort_index()
    if puntos.empty:
        return None
    log_p = pd.Series(np.log(puntos.values), index=puntos.index)
    union = log_p.index.union(rango)
    interp = log_p.reindex(union).interpolate(method="time").ffill().bfill().reindex(rango)
    return pd.Series(np.exp(interp.values), index=rango)


# ---------------------------------------------------------------------------
# 3. Cruce inventario x precio -> Valor Total ARS por dia
# ---------------------------------------------------------------------------
def calcular_curva_historica(
    movimientos: pd.DataFrame, benchmarks: Optional[List[Dict[str, str]]] = None
) -> ResultadoCurvaHistorica:
    """
    Punto de entrada principal: reconstruye, a partir del DataFrame
    crudo de csv_parser.parsear_movimientos(), la curva diaria de:
      - Valor Total ARS del portafolio (inventario x precio de mercado,
        MAS el cash acumulado por dividendos en efectivo -- ver v6.4 en
        el docstring del modulo), y
      - Capital Invertido ARS (plata neta puesta de tu bolsillo -- NO
        incluye dividendos, en efectivo ni en especie), y
      - (opcional) una linea de Valor Benchmark ARS por cada entrada de
        `benchmarks` -- lista de {"ticker": ..., "label": ...} (ver
        "CUARTA serie OPCIONAL, multiple" en el docstring del modulo).

    Todas las series que se devuelven comparten EXACTAMENTE el mismo
    indice de fechas (ver _rango_diario) para poder graficarse juntas
    sin desalinear el eje X.

    v6.2 -- Universo Cerrado: el Capital Invertido se calcula DESPUES de
    saber que tickers devolvieron precio de yfinance, y solo sobre esos
    (`tickers_incluidos`). Un ticker sin precio (ej. un bono) queda
    afuera de LAS DOS curvas, no solo de Valor de Mercado -- ver el
    filtro cruzado mas abajo, entre la descarga de precios y el calculo
    de capital invertido. Cada benchmark pedido (si tuvo precio)
    reutiliza este mismo flujo de caja ya filtrado -- ver
    `_serie_benchmark_diario`.

    Lanza HistoricalCurveError si no hay operaciones de Compra/Venta en
    el CSV, o si NINGUN ticker DE LA CARTERA pudo cotizarse via yfinance
    (ej. sin conexion a internet) -- en este ultimo caso tampoco hay
    universo valido sobre el que calcular Capital Invertido (quedaria
    vacio, ya que ya no se admite ningun ticker sin precio). Que uno o
    varios benchmarks no tengan precio NO lanza este error: esos
    simplemente no aparecen en `valores_benchmark` (ver advertencias).
    """
    operaciones_capital = _operaciones_por_tipos(movimientos, OPERACIONES_CAPITAL_INVERTIDO)
    if operaciones_capital.empty:
        raise HistoricalCurveError(
            "El CSV no tiene ninguna operacion de Compra/Venta de la que reconstruir una curva historica."
        )
    operaciones_posicion = _operaciones_por_tipos(movimientos, OPERACIONES_QUE_MUEVEN_POSICION)

    rango_completo = _rango_diario(operaciones_capital)
    inventario = _matriz_inventario_diario(operaciones_posicion, rango_completo)

    tickers = [str(t) for t in inventario.columns if isinstance(t, str) and t.strip()]
    fecha_inicio = rango_completo.min()

    # v7.x: los benchmarks (si se piden) se suman al MISMO batch de
    # descarga que los tickers de la cartera -- una sola llamada a
    # yfinance para TODO (cartera + benchmarks), mismo codigo de
    # robustez (batch -> fallback ticker por ticker), en vez de una
    # consulta aparte por cada benchmark. Se normaliza y dedupea por
    # ticker (dos benchmarks con el mismo simbolo, o un benchmark que
    # ya es de casualidad un ticker de la cartera, no se piden dos veces).
    benchmarks_norm: List[Dict[str, str]] = []
    tickers_benchmark_vistos = set()
    for b in benchmarks or []:
        ticker = str(b.get("ticker") or "").strip().upper()
        if not ticker or ticker in tickers_benchmark_vistos:
            continue
        tickers_benchmark_vistos.add(ticker)
        label = str(b.get("label") or ticker).strip()
        benchmarks_norm.append({"ticker": ticker, "label": label})

    tickers_a_descargar = sorted(set(tickers) | tickers_benchmark_vistos)

    precios, tickers_sin_datos_todos = _descargar_precios_ba(tickers_a_descargar, fecha_inicio)

    # Separa "sin datos de la cartera" (bonos, etc. -- advertencia ya
    # existente) de "sin datos de benchmarks" (advertencia propia, mas
    # abajo): son problemas distintos, no tiene sentido conflandirlos en
    # un solo mensaje.
    benchmarks_sin_datos = [b for b in benchmarks_norm if b["ticker"] not in precios.columns]
    tickers_sin_datos = [t for t in tickers_sin_datos_todos if t not in tickers_benchmark_vistos]

    advertencias: List[str] = []
    if tickers_sin_datos:
        advertencias.append(
            f"Sin precio historico en yfinance para: {', '.join(sorted(tickers_sin_datos))} "
            "(tipico de bonos/renta fija -- ej. AL30, GD38 -- que no cotizan en Yahoo Finance "
            "bajo el sufijo .BA). Se excluyen de AMBAS curvas (Valor de Mercado y Capital "
            "Invertido) para que la comparacion entre las dos sea justa -- si se contara su "
            "costo en Capital Invertido pero se los valuara en $0 en Valor de Mercado, se "
            "veria una perdida artificial que no es real."
        )
    if benchmarks_sin_datos:
        etiquetas = ", ".join(f"{b['label']} ({b['ticker']}.BA)" for b in benchmarks_sin_datos)
        advertencias.append(
            f"Sin precio historico en yfinance para el/los benchmark(s): {etiquetas} (misma "
            "convencion CEDEAR/BYMA que el resto de la app) -- se omiten esas lineas de "
            "comparacion del grafico. Revisa 'benchmark_tickers' en portfolio_config.json "
            "(seccion 'meta')."
        )

    if precios.empty:
        raise HistoricalCurveError(
            "No se pudo descargar el historico de precios de NINGUN activo via yfinance "
            "(revisa tu conexion a internet)."
        )

    # v10.0: corrige escala y huecos de historia de yfinance usando tus
    # operaciones reales como referencia (ver _sanear_precios).
    precios = _quitar_picos_aislados(precios, advertencias)
    precios = _sanear_precios(precios, operaciones_capital, inventario, rango_completo, advertencias)

    tickers_incluidos = [t for t in precios.columns if t in inventario.columns]
    if not tickers_incluidos:
        raise HistoricalCurveError(
            "No se pudo descargar el historico de precios de NINGUN activo DE LA CARTERA via "
            "yfinance (revisa tu conexion a internet) -- los benchmarks, si tuvieron precio, no "
            "alcanzan por si solos para reconstruir Valor de Mercado ni Capital Invertido."
        )

    # --- Filtro de Consistencia ("Universo Cerrado", v6.2) ---
    # El Capital Invertido NO se calcula sobre `operaciones_capital`
    # completo: se filtra primero a solo los tickers que SI estan en
    # `tickers_incluidos` (los que devolvieron precio de yfinance mas
    # arriba). Asi, un activo sin cotizacion (tipicamente un bono) queda
    # totalmente afuera de las dos curvas -- ni aporta a Valor de
    # Mercado (ya quedaba afuera antes) NI a Capital Invertido (esto es
    # lo nuevo). Sin este filtro cruzado, se estaria cobrando el costo
    # de compra de un activo que despues se valua en $0 por falta de
    # precio, inflando una "perdida" que es un agujero de datos, no una
    # perdida de mercado real.
    operaciones_capital_incluidas = operaciones_capital[operaciones_capital["ticker"].isin(tickers_incluidos)]
    capital_invertido = _serie_capital_invertido_diario(operaciones_capital_incluidas, rango_completo)
    # v10.0: mismo capital, pero desagregado por ticker (misma fuente,
    # misma convencion de signo) -- lo usa core/performance.py para
    # contribucion por activo y rendimiento por categoria.
    capital_por_ticker = (
        (-operaciones_capital_incluidas.groupby(
            [operaciones_capital_incluidas["fechaEjecucion"].dt.normalize(), "ticker"]
        )["total"].sum())
        .unstack("ticker")
        .reindex(rango_completo)
        .fillna(0.0)
        .cumsum()
        .reindex(columns=tickers_incluidos, fill_value=0.0)
    )

    # Cash de dividendos (v6.4): serie independiente del filtro de
    # Universo Cerrado de arriba -- estas filas no tienen ticker, asi
    # que no hay nada que "cotizar" ni excluir por falta de precio. Se
    # suma a Valor Total mas abajo, nunca a Capital Invertido.
    # v10.1: los dividendos en dolares se valuan al CCL de su dia (ver
    # _serie_cash_dividendos_diario); si el CCL no esta disponible se
    # cae al criterio viejo y se avisa.
    ccl_para_dividendos: Optional[pd.Series] = None
    hay_div_usd = bool(
        (
            (movimientos["tipo_operacion_norm"] == "DIVIDENDO_ESPECIE")
            & movimientos["ticker"].isna()
            & _es_instrumento_dolar(movimientos["instrumento"])
        ).any()
    ) if "instrumento" in movimientos.columns else False
    if hay_div_usd:
        try:
            from core.macro_data import ccl_diario, get_ccl_historico

            ccl_para_dividendos = ccl_diario(get_ccl_historico().serie, rango_completo)
        except Exception as e:
            advertencias.append(
                f"No se pudo obtener el CCL historico ({e}): los dividendos en dolares no se suman "
                "a la curva (quedan subestimados)."
            )
    cash_dividendos = _serie_cash_dividendos_diario(movimientos, rango_completo, ccl_para_dividendos)

    # Alinea la matriz de precios al MISMO rango_completo (fechas
    # identicas a inventario y a capital_invertido) y completa hacia
    # adelante (fines de semana/feriados no tienen cotizacion nueva, se
    # mantiene la ultima conocida) -- mismo criterio que el inventario.
    precios_diarios = precios.reindex(rango_completo).ffill()

    inventario_incluido = inventario[tickers_incluidos]
    precios_incluidos = precios_diarios[tickers_incluidos]

    valor_ars = (inventario_incluido * precios_incluidos).sum(axis=1) + cash_dividendos
    # Antes de que CUALQUIER ticker incluido tenga su primer precio
    # (ej. la ventana pedida a yfinance arranca un poco antes de que el
    # activo empezara a cotizar) esa fila entera de precios_incluidos
    # es NaN -- sum(skipna=True) la convierte en 0 en vez de NaN, lo
    # cual es correcto solo si de verdad no se tenia nada ese dia. Se
    # recorta el arranque de AMBAS series (Valor Total y Capital
    # Invertido) hasta el primer dia con al menos un precio real, para
    # que sigan compartiendo el mismo tramo de fechas visibles en el
    # grafico y no se muestre un arranque de "$0" enganoso en ninguna
    # de las dos.
    primer_precio_valido = precios_incluidos.notna().any(axis=1)

    # --- Valores Benchmark (v7.x, opcional, MULTIPLE) ----------------------
    # Se calculan ANTES del recorte por fecha de abajo (usan el
    # `capital_invertido` todavia completo) para despues recortarlos con
    # el MISMO `fecha_recorte` que las otras series, si aplica.
    benchmarks_con_datos = [b for b in benchmarks_norm if b["ticker"] in precios.columns]
    valores_benchmark: Dict[str, pd.Series] = {}
    benchmarks_solo_precio: List[str] = []
    for b in benchmarks_con_datos:
        # Forward-fill (fines de semana/feriados) MAS backward-fill
        # acotado al arranque (ver "LIMITACION documentada" en el
        # docstring del modulo): un aporte anterior al primer precio
        # disponible de ESTE benchmark se valua al precio mas viejo que
        # exista, en vez de quedar sin simular ese tramo.
        precios_benchmark = precios[b["ticker"]].reindex(rango_completo).ffill().bfill()
        # v10.1: retorno total (con dividendos), igual que tu cartera,
        # que suma los dividendos cobrados. Sin esto la comparacion te
        # favorecia en el dividend yield del indice (~1-2% anual).
        factor_rt = _factor_retorno_total_us(b["ticker"], fecha_inicio)
        if factor_rt is not None:
            precios_benchmark = _precio_retorno_total(precios_benchmark, factor_rt)
        else:
            benchmarks_solo_precio.append(b["label"])
        valores_benchmark[b["label"]] = _serie_benchmark_diario(capital_invertido, precios_benchmark, rango_completo)
    if benchmarks_solo_precio:
        advertencias.append(
            f"Sin datos de dividendos para {', '.join(benchmarks_solo_precio)}: esa(s) linea(s) de comparacion "
            "usan solo precio (sin dividendos), lo que favorece levemente a tu cartera en la comparacion."
        )

    # Antes de que CUALQUIER ticker incluido tenga su primer precio
    # (ej. la ventana pedida a yfinance arranca un poco antes de que el
    # activo empezara a cotizar) esa fila entera de precios_incluidos
    # es NaN -- sum(skipna=True) la convierte en 0 en vez de NaN, lo
    # cual es correcto solo si de verdad no se tenia nada ese dia. Se
    # recorta el arranque de TODAS las series (Valor Total, Capital
    # Invertido y Benchmark si aplica) hasta el primer dia con al menos
    # un precio real de CARTERA, para que sigan compartiendo el mismo
    # tramo de fechas visibles en el grafico y no se muestre un arranque
    # de "$0" enganoso en ninguna de ellas.
    if primer_precio_valido.any():
        fecha_recorte = primer_precio_valido.idxmax()
        valor_ars = valor_ars[fecha_recorte:]
        capital_invertido = capital_invertido[fecha_recorte:]
        valores_benchmark = {label: serie[fecha_recorte:] for label, serie in valores_benchmark.items()}
    else:
        fecha_recorte = rango_completo.min()

    return ResultadoCurvaHistorica(
        valor_ars=valor_ars,
        capital_invertido_ars=capital_invertido,
        tickers_incluidos=tickers_incluidos,
        tickers_sin_datos=sorted(tickers_sin_datos),
        advertencias=advertencias,
        valores_benchmark=valores_benchmark,
        inventario=inventario_incluido[fecha_recorte:],
        precios_diarios=precios_diarios[fecha_recorte:],
        capital_por_ticker=capital_por_ticker[fecha_recorte:],
        cash_dividendos=cash_dividendos[fecha_recorte:],
    )


if __name__ == "__main__":
    from core.config_manager import get_benchmark_tickers, load_config
    from core.csv_parser import parsear_movimientos

    movimientos = parsear_movimientos()
    benchmarks = get_benchmark_tickers(load_config())
    try:
        resultado = calcular_curva_historica(movimientos, benchmarks=benchmarks)
    except HistoricalCurveError as e:
        print(f"No se pudo calcular la curva historica: {e}")
    else:
        for aviso in resultado.advertencias:
            print(f"[aviso] {aviso}")
        print(f"Tickers incluidos: {resultado.tickers_incluidos}")
        assert resultado.valor_ars.index.equals(resultado.capital_invertido_ars.index), (
            "BUG: valor_ars y capital_invertido_ars deberian compartir el mismo indice de fechas."
        )
        comparacion = pd.DataFrame(
            {
                "Valor Total ARS": resultado.valor_ars,
                "Capital Invertido ARS": resultado.capital_invertido_ars,
            }
        )
        comparacion["Ganancia No Realizada ARS"] = (
            comparacion["Valor Total ARS"] - comparacion["Capital Invertido ARS"]
        )
        for label, serie in resultado.valores_benchmark.items():
            assert resultado.valor_ars.index.equals(serie.index), (
                f"BUG: valores_benchmark['{label}'] deberia compartir el mismo indice que valor_ars."
            )
            comparacion[f"Valor Benchmark ({label}) ARS"] = serie
        print(comparacion.tail(10))
