"""
core/rebalancer.py

Algoritmo de Rebalanceo por DCA (Dollar-Cost Averaging).

Dado (a) la tenencia actual (core.holdings.calcular_tenencia_actual),
(b) la configuracion de pesos objetivo (config/portfolio_config.json) y
(c) un monto en ARS a inyectar este mes, calcula cuanto comprar de cada
activo para acercar la cartera a los pesos objetivo. Es DCA puro: solo
distribuye COMPRAS, nunca sugiere vender.

Logica (en este orden):

  1. Valor Total Futuro = Valor actual de la cartera + Monto X.
  2. Meta ARS de cada activo = Valor Total Futuro * % objetivo total
     (el % objetivo total = objetivo_pct de su categoria x
     objetivo_pct_categoria del activo, ya resuelto por
     config_manager.get_target_by_ticker).
  3. Deficit ARS = Meta - Valor Actual. Si Deficit < 0 (el activo esta
     sobreponderado), se le asigna 0 ARS de la nueva compra.
  4. El Monto X se reparte proporcionalmente SOLO entre los activos con
     deficit positivo, en proporcion a su deficit:
       asignacion_i = Monto_X * deficit_i / suma(deficits_positivos)
  5. Nominales a comprar:
       - CEDEARs: math.floor(asignacion_i / precio_i) -> no se compran
         fracciones de CEDEAR.
  6. Vuelto_i = asignacion_i - (nominales_i * precio_i): lo que queda
     sin poder invertirse por el redondeo hacia abajo (siempre >= 0).

Ticker Alias vinculado (v6.3, ej. BTC -> IBIT): si el activo tiene
"alias_ticker" configurado (ver core/holdings.py y
config/portfolio_config.json) y ese alias se pudo cotizar, la ORDEN se
arma con el precio del ALIAS y se redondea como CEDEAR (nominales
enteros), sin importar que el "tipo" del activo principal sea "Cripto"
-- es lo unico que en la practica se puede operar en el broker (Cocos
Capital no opera cripto directo). "Ticker" en el resultado sigue siendo
el activo principal (asi Meta/Deficit/las donas de la UI lo siguen
reconociendo como el mismo "balde" objetivo de siempre); una columna
nueva, "Ticker Ejecucion", lleva el simbolo concreto a comprar.

Por que este algoritmo nunca "overshootea" un objetivo (propiedad
matematica, no un caso que haya que forzar a mano): como la Meta de
cada activo se calcula sobre el Valor Total Futuro (que ya incluye el
Monto X), la suma de TODOS los deficits sin recortar es exactamente
igual al Monto X:

    sum(Meta_i) - sum(Valor_actual_i)
      = ValorTotalFuturo * sum(%objetivo_i) - ValorCarteraActual
      = ValorTotalFuturo * 100% - ValorCarteraActual
      = (ValorCarteraActual + Monto_X) - ValorCarteraActual
      = Monto_X

Si algun activo esta sobreponderado (deficit negativo, se recorta a
0), la suma de los deficits POSITIVOS queda, por construccion, siempre
>= Monto_X (nunca menor). Por lo tanto la asignacion de cada activo
(Monto_X * deficit_i / suma_deficits_positivos) nunca puede superar su
propio deficit_i, y ningun activo termina por encima de su meta en un
solo calculo, sin importar cuan grande sea Monto_X. Con monto_x > 0 y
una config valida (validate_config exige que los % sumen 100), la
suma de deficits positivos jamas puede ser 0 ni menor a Monto_X: los
chequeos de division por cero mas abajo son una red de seguridad ante
configuraciones invalidas/corruptas, no un escenario esperado en uso
normal.

Comision/IVA de la orden nueva (v7.x): antes de esta version, la
"Asignacion ARS" de cada activo se convertia directo a nominales
(Asignacion / Precio), sin descontar nada -- el resultado ignoraba que
Cocos Capital cobra comision + IVA sobre cada Compra/Venta, igual que
ya se ve en el costo historico real (`core.holdings.calcular_costo_neto_byma`,
que usa 'total', ya neto de esos cargos). Eso hacia que el monto que
esta calculadora "sugeria" invertir fuera SIEMPRE menor a lo que en
realidad te iba a debitar el broker.

Como todavia no existe la orden (no hay 'total' real que leer, como si
lo hay para el historico), se usa una comision/IVA ESTIMADA constante,
`COMISION_PCT_APROX` = 0.6% del monto bruto operado -- calibrada contra
el promedio real observado en las Compras de este mismo CSV historico
(~0.55%, entre comision del broker + IVA sobre esa comision; ver
`calcular_costo_neto_byma`), redondeado un poco para arriba a proposito
(mejor sugerir de menos que de mas). Solo se aplica a instrumentos que
se operan EN Cocos Capital (v10.2: todos los activos de la config son
CEDEARs/acciones operados en BYMA).

Efecto en el calculo de nominales: la "Asignacion ARS" de un activo ES
el monto TOTAL que vas a pagar (nominales + comision + IVA), no solo el
bruto de los nominales -- por eso antes de dividir por el precio se
descuenta la comision estimada (Asignacion / (1 + COMISION_PCT_APROX/100))
para obtener el monto NETO disponible para nominales, y asi
"Costo Total Estimado ARS" (neto + comision) nunca supere la
Asignacion ARS que le tocaba a ese activo. `ResultadoRebalanceo` expone
tanto el monto neto ("Monto a Invertir ARS", igual que antes: nominales
x precio) como el costo total con comision ("Costo Total Estimado ARS")
para que la UI pueda mostrar los dos.

Rebalanceo por Banda de Tolerancia, CON venta (v7.x, `calcular_rebalanceo_banda`):
modo OPCIONAL y separado de `calcular_rebalanceo` -- el DCA puro de
arriba sigue siendo el default, sin ningun cambio de comportamiento ni
de firma, y `calcular_rebalanceo_banda` es una funcion nueva que hay que
llamar explicitamente (ver tambien la seccion propia que arma app.py,
separada de la Calculadora DCA). Resuelve la limitacion mas grande
frente a una herramienta de gestion de cartera "real" (ver
ANALISIS_REVISION.md, item 7): el DCA de arriba, por diseno, NUNCA
sugiere vender -- razonable mientras estas en fase de aportes puros,
pero inutil el dia que un activo se dispara muy por encima de su peso y
no estas metiendo plata nueva (o no alcanza) para diluirlo comprando.

Logica:
  1. % Actual de cada activo = Valor Actual ARS / Valor Cartera Actual
     (la cartera de HOY, sin sumarle ningun Monto Nuevo todavia).
  2. Desviacion (puntos porcentuales) = % Actual - % Objetivo. Positiva
     = sobreponderado (le sobra), negativa = subponderado (le falta).
  3. Solo participan del rebalanceo los activos con
     |Desviacion| > `banda_tolerancia_pct` -- los que estan DENTRO de la
     banda se dejan quietos a proposito (el enfoque estandar de gestion
     de carteras: rebalancear por banda de tolerancia evita operar por
     ruido de mercado de un dia, a diferencia de rebalancear a un
     porcentaje exacto en cada corrida).
  4. Meta ARS de cada activo = Valor Total Futuro * % Objetivo, donde
     Valor Total Futuro = Valor Cartera Actual + Monto Nuevo (opcional,
     default 0 -- si no se aporta plata nueva, Valor Total Futuro =
     Valor Cartera Actual, y este modo es una redistribucion PURA entre
     los activos existentes). Mismo Monto Nuevo mas grande implica Metas
     mas altas para TODOS los activos (incluidos los sobreponderados),
     asi que hace falta vender MENOS del que esta arriba de su peso --
     es el comportamiento financieramente correcto: la plata nueva ya
     diluye el sobrepeso por su cuenta.
  5. Para cada SOBREPONDERADO fuera de banda: Exceso ARS = Valor Actual
     - Meta ARS (siempre > 0 en este grupo). Nominales a Vender =
     math.floor(Exceso ARS / Precio) -- redondeo hacia ABAJO, mismo
     criterio que las compras: nunca vender de mas (vender de mas
     empujaria al activo por DEBAJO de su Meta, "overshooting" para el
     otro lado). Se estima la MISMA comision/IVA (`COMISION_PCT_APROX`,
     y misma restriccion de que solo aplica a lo operado en Cocos
     Capital) sobre el monto BRUTO de la venta -- Monto Neto de Venta =
     Monto Bruto - Comision, la plata que efectivamente queda
     disponible para reinvertir.
  6. Para cada SUBPONDERADO fuera de banda: Deficit ARS = Meta ARS -
     Valor Actual (siempre > 0 en este grupo).
  7. Efectivo Disponible = suma de TODOS los Montos Netos de Venta +
     Monto Nuevo. Se reparte entre los subponderados con la MISMA formula
     proporcional-y-nunca-overshootea que el DCA de arriba (ver la
     demostracion matematica mas arriba en este docstring): si el
     Efectivo Disponible alcanza para cubrir la suma de TODOS los
     Deficits, cada uno recibe exactamente su Deficit (mejor caso: la
     cartera queda perfectamente en su Objetivo); si no alcanza, se
     reparte proporcionalmente y ningun activo recibe mas de lo que le
     faltaba.

LIMITACION IMPORTANTE (documentada a proposito, ver tambien la UI):
vender implica un evento fiscal real (Bienes Personales/Ganancias segun
tu situacion) que esta funcion NO calcula ni descuenta -- solo estima la
comision/IVA del broker, igual que ya hace el DCA con las compras. El
"Monto Neto de Venta" de esta funcion es neto de comision, NO neto de
impuestos. Revisa el impacto impositivo de cada venta antes de
ejecutarla; `ResultadoRebalanceoBanda.advertencias` siempre incluye un
recordatorio de esto cuando hay al menos una venta sugerida.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from core.config_manager import get_target_by_ticker

# Comision + IVA ESTIMADA de una orden nueva en Cocos Capital, como % del
# monto bruto operado -- ver el docstring del modulo ("Comision/IVA de
# la orden nueva") para de donde sale el numero y por que solo se aplica
# a instrumentos operados EN Cocos Capital.
COMISION_PCT_APROX = 0.6

# Banda de tolerancia DEFAULT para calcular_rebalanceo_banda, en puntos
# porcentuales de desviacion respecto al % Objetivo de cada activo.
#
# OJO -- esto NO es lo mismo que `core.config_manager.TOLERANCIA_PCT`
# (0.01): ese numero es la tolerancia de REDONDEO para validar que los %
# de la config sumen 100 (una config con 99.99% o 100.01% por error de
# punto flotante sigue siendo valida), no un umbral de rebalanceo -- si
# se usara 0.01 puntos porcentuales como banda, CUALQUIER movimiento de
# mercado activaria una sugerencia de venta en cada corrida, lo que
# contradice el proposito mismo de rebalancear "por banda" (evitar
# operar por ruido). BANDA_TOLERANCIA_PCT_DEFAULT vive en este modulo,
# separado a proposito, con un valor bien distinto (5 puntos
# porcentuales, un default razonable y comun en gestion de carteras --
# ver p.ej. la regla informal "5/25"): la UI lo expone como un control
# ajustable, este valor es solo el punto de partida.
BANDA_TOLERANCIA_PCT_DEFAULT = 5.0


class RebalancerError(Exception):
    """Error de datos de entrada: precios faltantes, montos invalidos, etc."""


@dataclass
class ResultadoRebalanceo:
    ordenes: pd.DataFrame
    monto_a_invertir: float
    valor_cartera_actual: float
    valor_total_futuro: float
    monto_total_asignado: float  # suma de "Monto a Invertir ARS" (neto, sin comision)
    comision_total_estimada: float  # suma de "Comision Estimada ARS" de todas las ordenes
    costo_total_estimado: float  # monto_total_asignado + comision_total_estimada
    vuelto_total: float
    dolar_ccl: Optional[float] = None
    advertencias: List[str] = field(default_factory=list)


# Columnas "limpias" pensadas para mostrar en la UI (Seccion 3). El
# detalle de Meta/Deficit/% Objetivo tambien queda en el DataFrame por
# si se quiere auditar el calculo, pero no son las primeras que se
# muestran.
COLUMNAS_ORDENES = [
    "Ticker",
    "Ticker Ejecucion",
    "Categoria",
    "Nominales a Comprar",
    "Precio Actual",
    "Moneda",
    "Monto a Invertir ARS",
    "Comision Estimada ARS",
    "Costo Total Estimado ARS",
    "Equivalente USD",
    "Vuelto ARS",
    "% Objetivo",
    "% Actual",
    "Valor Actual ARS",
    "Meta ARS",
    "Deficit ARS",
    "Asignacion ARS",
]


@dataclass
class ResultadoRebalanceoBanda:
    desviaciones: pd.DataFrame  # TODOS los activos (dentro y fuera de banda) -- foto completa
    ordenes_venta: pd.DataFrame  # solo sobreponderados fuera de banda
    ordenes_compra: pd.DataFrame  # solo subponderados fuera de banda
    banda_tolerancia_pct: float
    monto_nuevo: float
    valor_cartera_actual: float
    valor_total_futuro: float
    venta_bruta_total: float
    comision_venta_total: float
    venta_neta_total: float  # venta_bruta_total - comision_venta_total (efectivo que deja la venta)
    efectivo_disponible_total: float  # venta_neta_total + monto_nuevo
    compra_neta_total: float  # suma de "Monto a Invertir ARS" (sin comision)
    comision_compra_total: float
    costo_compra_total: float  # compra_neta_total + comision_compra_total
    efectivo_sobrante: float  # efectivo_disponible_total no asignado (sin subponderados que lo absorban, o redondeo)
    dolar_ccl: Optional[float] = None
    advertencias: List[str] = field(default_factory=list)


# Mismas columnas de "ejecucion" (Ticker/Precio/Moneda/etc.) que
# COLUMNAS_ORDENES, mas las especificas de una VENTA. "Ticker" sigue
# siendo el activo principal (ver Ticker Alias vinculado en el docstring
# del modulo); "Ticker Ejecucion" el simbolo concreto a operar.
COLUMNAS_ORDENES_VENTA = [
    "Ticker",
    "Ticker Ejecucion",
    "Categoria",
    "Nominales a Vender",
    "Precio Actual",
    "Moneda",
    "Monto Bruto Venta ARS",
    "Comision Estimada ARS",
    "Monto Neto Venta ARS",
    "Equivalente USD",
    "% Objetivo",
    "% Actual",
    "Desviacion pp",
    "Valor Actual ARS",
    "Meta ARS",
    "Exceso ARS",
]

COLUMNAS_ORDENES_COMPRA_BANDA = [
    "Ticker",
    "Ticker Ejecucion",
    "Categoria",
    "Nominales a Comprar",
    "Precio Actual",
    "Moneda",
    "Monto a Invertir ARS",
    "Comision Estimada ARS",
    "Costo Total Estimado ARS",
    "Equivalente USD",
    "% Objetivo",
    "% Actual",
    "Desviacion pp",
    "Valor Actual ARS",
    "Meta ARS",
    "Deficit ARS",
    "Asignacion ARS",
]

COLUMNAS_DESVIACIONES = [
    "Ticker",
    "Categoria",
    "Estado",
    "% Objetivo",
    "% Actual",
    "Desviacion pp",
    "Valor Actual ARS",
    "Meta ARS",
]


# ---------------------------------------------------------------------------
# Helpers compartidos entre calcular_rebalanceo (DCA) y
# calcular_rebalanceo_banda (banda de tolerancia, con venta)
# ---------------------------------------------------------------------------
def _float_seguro(v) -> Optional[float]:
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v)


def _tipo_activo(ticker: str, config: dict) -> str:
    datos = config["activos"].get(ticker, {})
    if datos.get("alias_ticker"):
        # v6.3: se opera como CEDEAR (nominales enteros, redondeo hacia
        # abajo) a traves del alias vinculado -- ej. IBIT para BTC --
        # sin importar que el "tipo" del activo principal sea "Cripto".
        # "Precio ARS" de la fila de ejecucion ya es el del alias (ver
        # _resolver_ejecucion), asi que el redondeo tiene que ser el de
        # un instrumento que se compra/vende en nominales enteros.
        return "CEDEAR"
    return datos.get("tipo", "")


def _aplica_comision_cocos(ticker: str, config: dict) -> bool:
    # Ver "Comision/IVA de la orden nueva" en el docstring del modulo:
    # solo se estima comision para lo que se opera EN Cocos Capital
    # (CEDEARs, incluidos los activos con alias_ticker -- _tipo_activo
    # devuelve "CEDEAR" en ese caso).
    return _tipo_activo(ticker, config) == "CEDEAR"


def _preparar_objetivos_y_precios(
    holdings_df: pd.DataFrame, config: dict
) -> "tuple[pd.DataFrame, dict, List[str]]":
    """
    Paso de arranque compartido por las dos funciones de rebalanceo:
    resuelve el % Objetivo de cada ticker (incluidos huerfanos a 0%,
    ver docstring del modulo) y valida que todo activo con Objetivo > 0
    tenga precio disponible (directo o via alias_ticker vinculado).

    Devuelve (holdings indexado por Ticker, objetivos, advertencias).
    Lanza RebalancerError si a un activo BLOQUEANTE (Objetivo > 0) le
    falta el precio.
    """
    holdings = holdings_df.set_index("Ticker")
    objetivos = get_target_by_ticker(config)  # ticker -> % del total del portafolio

    # Activos "huerfanos" (v6.0): estan en holdings_df (ej. una tenencia
    # manual, ver core/manual_holdings.py) pero no en portfolio_config.json,
    # asi que get_target_by_ticker no sabe nada de ellos. Se les asigna
    # 0% Objetivo EXPLICITO en vez de omitirlos: asi entran al calculo
    # con Meta ARS = 0 (siempre "sobreponderados" respecto a un objetivo
    # de 0%) y quedan visibles en el resultado -- en vez de desaparecer
    # sin explicacion -- pero nunca reciben parte de una compra nueva.
    for ticker in holdings.index:
        if ticker not in objetivos:
            objetivos[ticker] = 0.0

    advertencias: List[str] = []

    con_precio_faltante = holdings_df[
        holdings_df["Precio Actual"].isna() | holdings_df["Precio ARS"].isna()
    ]["Ticker"].tolist()

    # v6.3 (Ticker Alias vinculado, ej. BTC -> IBIT): a un activo le
    # puede faltar SU propio precio y aun asi
    # ser perfectamente operable a traves del alias vinculado (IBIT via
    # yfinance) -- no tiene sentido bloquear todo el rebalanceo por eso
    # si el precio que realmente se va a usar para la orden SI esta
    # disponible (ver _resolver_ejecucion).
    def _resuelto_via_alias(ticker: str) -> bool:
        alias_ticker = config["activos"].get(ticker, {}).get("alias_ticker")
        if not alias_ticker or ticker not in holdings.index:
            return False
        return pd.notna(holdings.loc[ticker].get("Alias Precio ARS"))

    con_precio_faltante = [t for t in con_precio_faltante if not _resuelto_via_alias(t)]
    bloqueantes = [t for t in con_precio_faltante if objetivos.get(t, 0) > 0]
    if bloqueantes:
        raise RebalancerError(
            "No se puede calcular el rebalanceo: falta el precio de "
            f"{bloqueantes}. Esto casi siempre es Yahoo Finance rate-limitando temporalmente las "
            "consultas (no un problema de configuracion -- los tickers de CEDEARs ya se piden "
            "con el sufijo '.BA' correctamente, ver core/market_data.py); la app ya reintenta "
            "sola un par de veces antes de mostrar este error. Esperá un minuto y volvé a tocar "
            "'Calcular Rebalanceo', o revisa tu conexion si el problema persiste."
        )
    no_bloqueantes = [t for t in con_precio_faltante if t not in bloqueantes]
    if no_bloqueantes:
        advertencias.append(
            f"No se pudo cotizar {no_bloqueantes} (0% Objetivo, ej. una tenencia manual "
            "huerfana con un ticker que no se resolvio). No afecta el reparto porque nunca "
            "iban a recibir compras, pero quedan afuera del Valor Total mientras no tengan precio."
        )

    return holdings, objetivos, advertencias


def _resolver_ejecucion(ticker: str, fila: pd.Series, config: dict) -> dict:
    """
    Resuelve el precio/moneda/simbolo con el que se va a EJECUTAR una
    orden (compra O venta) de este activo -- ver "Ticker Alias
    vinculado" en el docstring del modulo: si el activo tiene
    "alias_ticker" configurado y ese alias se pudo cotizar, se opera con
    el precio del ALIAS (ej. IBIT para BTC) en vez del activo principal.
    """
    alias_ticker = config["activos"].get(ticker, {}).get("alias_ticker")
    precio_actual = _float_seguro(fila["Precio Actual"])
    moneda = fila["Moneda"]
    precio_ars = _float_seguro(fila["Precio ARS"])
    ticker_ejecucion = ticker
    if alias_ticker:
        alias_precio_ars = _float_seguro(fila.get("Alias Precio ARS"))
        if alias_precio_ars is not None:
            precio_actual = _float_seguro(fila.get("Alias Precio Actual"))
            moneda = fila.get("Alias Moneda")
            precio_ars = alias_precio_ars
            ticker_ejecucion = alias_ticker
    return {
        "Ticker Ejecucion": ticker_ejecucion,
        "Precio Actual": precio_actual,
        "Moneda": moneda,
        "Precio ARS": precio_ars,
    }


def calcular_rebalanceo(
    holdings_df: pd.DataFrame,
    config: dict,
    monto_x: float,
    dolar_ccl: Optional[float] = None,
) -> ResultadoRebalanceo:
    """
    Calcula las ordenes de compra de DCA para distribuir `monto_x`
    (ARS) entre los activos de `holdings_df` segun los objetivos de
    `config`.

    `holdings_df` debe tener, como minimo, las columnas que produce
    core.holdings.calcular_tenencia_actual: Ticker, Categoria, Precio
    Actual, Moneda, Precio ARS, Valor ARS. Si a un activo con % Objetivo
    > 0 le falta el precio (tipicamente porque el Modulo de Mercado no
    pudo cotizarlo), se corta con RebalancerError en vez de calcular
    sobre datos incompletos -- para ESE activo si importa el precio,
    porque puede recibir parte del Monto X.

    Un activo con 0% Objetivo (huerfano, ver mas abajo) que ademas no
    se pudo cotizar NO bloquea el calculo: nunca iba a recibir compras
    de todas formas, asi que solo se lo excluye del Valor Total (con una
    advertencia) en vez de frenar todo el rebalanceo por un dato que no
    afecta el resultado de nadie mas.

    `dolar_ccl` es opcional: si se pasa, se usa para mostrar a cuantos
    USD equivale la asignacion de cada activo (como referencia).
    """
    if monto_x is None or monto_x <= 0:
        raise RebalancerError("El monto a invertir debe ser mayor a 0.")

    holdings, objetivos, advertencias = _preparar_objetivos_y_precios(holdings_df, config)

    valor_cartera_actual = float(holdings["Valor ARS"].fillna(0).sum())
    valor_total_futuro = valor_cartera_actual + monto_x

    filas = []
    for ticker, pct_objetivo in objetivos.items():
        if ticker not in holdings.index:
            continue  # no deberia pasar: config y holdings_df vienen del mismo config
        fila = holdings.loc[ticker]

        # pd.isna(), no "fila['Valor ARS'] or 0": bool(float('nan')) es
        # TRUE en Python, asi que ese patron NO detecta un Valor ARS
        # faltante (NaN) y lo dejaria pasar tal cual -> deficit_ars
        # terminaria en NaN y arrastraria NaN por el resto del calculo.
        valor_actual_raw = fila["Valor ARS"]
        valor_actual = 0.0 if pd.isna(valor_actual_raw) else float(valor_actual_raw)
        meta_ars = valor_total_futuro * pct_objetivo / 100
        deficit_ars = meta_ars - valor_actual
        # % que este activo pesa HOY en la cartera (antes de sumarle el
        # Monto X) -- distinto de "% Objetivo", que es la meta. Con
        # cartera vacia (valor_cartera_actual == 0, ej. todavia no
        # cargaste ninguna tenencia) queda en 0 en vez de dividir por 0.
        pct_actual = (valor_actual / valor_cartera_actual * 100) if valor_cartera_actual else 0.0

        # v6.3 (Ticker Alias vinculado, ej. BTC -> IBIT): si el activo
        # tiene un alias configurado y su precio se pudo resolver, la
        # ORDEN se arma con el precio/moneda del ALIAS -- es lo unico que
        # en la practica se puede operar en Cocos Capital -- en vez del
        # precio del activo principal. "Ticker" se deja
        # igual al activo principal (para que Meta/Deficit/las donas de
        # la UI lo sigan reconociendo como el mismo "balde" de siempre);
        # "Ticker Ejecucion" lleva el simbolo concreto a comprar.
        ejecucion = _resolver_ejecucion(ticker, fila, config)

        filas.append(
            {
                "Ticker": ticker,
                "Ticker Ejecucion": ejecucion["Ticker Ejecucion"],
                "Categoria": fila["Categoria"],
                "Precio Actual": ejecucion["Precio Actual"],
                "Moneda": ejecucion["Moneda"],
                "Precio ARS": ejecucion["Precio ARS"],
                "% Objetivo": round(pct_objetivo, 2),
                "% Actual": round(pct_actual, 2),
                "Valor Actual ARS": round(valor_actual, 2),
                "Meta ARS": round(meta_ars, 2),
                "Deficit ARS": round(deficit_ars, 2),
            }
        )

    tabla = pd.DataFrame(filas)

    deficits_positivos = tabla["Deficit ARS"].clip(lower=0)
    suma_deficits = float(deficits_positivos.sum())

    # Red de seguridad: con monto_x > 0 (ya validado arriba) y una config
    # valida, suma_deficits siempre es >= monto_x > 0 (ver demostracion en
    # el docstring del modulo). Esta rama solo se activaria ante una config
    # corrupta que sortee validate_config (ej. % que no suman 100).
    if suma_deficits <= 0:
        advertencias.append(
            "No se pudo distribuir el monto por deficit (suma de deficits "
            "positivos <= 0), lo cual solo deberia ocurrir con una configuracion "
            "invalida. Se repartio segun el % objetivo de cada activo como "
            "resguardo, pero conviene revisar portfolio_config.json."
        )
        tabla["Asignacion ARS"] = monto_x * tabla["% Objetivo"] / 100
    else:
        tabla["Asignacion ARS"] = monto_x * deficits_positivos / suma_deficits

    tabla["Asignacion ARS"] = tabla["Asignacion ARS"].round(2)

    # --- Nominales a comprar ---
    def _nominales(row) -> float:
        precio_ars = row["Precio ARS"]
        # pd.isna() (no "not precio_ars"/"falsy"): un DataFrame con None
        # mezclado con floats los convierte a NaN, y bool(float('nan')) es
        # TRUE en Python -- un chequeo "not precio_ars" NO detecta ese
        # caso (v6.0: ahora es un caso real, un huerfano de 0% Objetivo
        # sin cotizacion), y math.floor(NaN) revienta mas abajo.
        if pd.isna(precio_ars) or precio_ars <= 0:
            return 0.0
        # La Asignacion ARS es el monto TOTAL a pagar (nominales +
        # comision estimada), asi que primero se descuenta la comision
        # para saber cuanto queda disponible para nominales -- ver
        # "Efecto en el calculo de nominales" en el docstring del modulo.
        monto_neto_disponible = row["Asignacion ARS"]
        if _aplica_comision_cocos(row["Ticker"], config):
            monto_neto_disponible = monto_neto_disponible / (1 + COMISION_PCT_APROX / 100)
        cantidad_exacta = monto_neto_disponible / precio_ars
        return float(math.floor(cantidad_exacta))

    tabla["Nominales a Comprar"] = tabla.apply(_nominales, axis=1)
    tabla["Monto a Invertir ARS"] = (tabla["Nominales a Comprar"] * tabla["Precio ARS"]).round(2)
    tabla["Comision Estimada ARS"] = tabla.apply(
        lambda row: round(row["Monto a Invertir ARS"] * COMISION_PCT_APROX / 100, 2)
        if _aplica_comision_cocos(row["Ticker"], config)
        else 0.0,
        axis=1,
    )
    tabla["Costo Total Estimado ARS"] = (tabla["Monto a Invertir ARS"] + tabla["Comision Estimada ARS"]).round(2)
    # Para cripto, "Nominales a Comprar" ya viene redondeado a 8 decimales
    # (ver _nominales), lo que puede dejar un Vuelto negativo de centavos
    # por puro error de punto flotante (nunca se "gasta" mas de lo
    # asignado). Se recorta a 0 para no mostrar un vuelto negativo enganoso.
    # El Vuelto se calcula contra el COSTO TOTAL (neto + comision), no
    # solo contra el monto neto -- es lo que realmente sobra de la
    # Asignacion ARS de ese activo despues de pagar nominales y comision.
    tabla["Vuelto ARS"] = (tabla["Asignacion ARS"] - tabla["Costo Total Estimado ARS"]).round(2).clip(lower=0)

    # Un huerfano de 0% Objetivo sin precio (ver mas arriba: no bloquea el
    # calculo) deja "Precio ARS" en NaN, lo que arrastra NaN a Monto a
    # Invertir/Vuelto por la multiplicacion. Como su Asignacion ARS
    # siempre es 0 (nunca recibe parte del Monto X), esos NaN son
    # conceptualmente "$0", no "dato desconocido": se rellenan para que
    # la UI no tenga que lidiar con NaN en una columna de plata.
    tabla[
        ["Nominales a Comprar", "Monto a Invertir ARS", "Comision Estimada ARS", "Costo Total Estimado ARS", "Vuelto ARS"]
    ] = tabla[
        ["Nominales a Comprar", "Monto a Invertir ARS", "Comision Estimada ARS", "Costo Total Estimado ARS", "Vuelto ARS"]
    ].fillna(0.0)

    # --- Equivalente en USD (referencia) ---
    if dolar_ccl:
        tabla["Equivalente USD"] = (tabla["Monto a Invertir ARS"] / dolar_ccl).round(2)
    else:
        tabla["Equivalente USD"] = None

    tabla = tabla.sort_values("Asignacion ARS", ascending=False).reset_index(drop=True)
    tabla = tabla[COLUMNAS_ORDENES]

    monto_total_asignado = float(tabla["Monto a Invertir ARS"].sum())
    comision_total_estimada = round(float(tabla["Comision Estimada ARS"].sum()), 2)
    costo_total_estimado = round(monto_total_asignado + comision_total_estimada, 2)
    vuelto_total = round(float(tabla["Vuelto ARS"].sum()), 2)

    return ResultadoRebalanceo(
        ordenes=tabla,
        monto_a_invertir=monto_x,
        valor_cartera_actual=valor_cartera_actual,
        valor_total_futuro=valor_total_futuro,
        monto_total_asignado=monto_total_asignado,
        comision_total_estimada=comision_total_estimada,
        costo_total_estimado=costo_total_estimado,
        vuelto_total=vuelto_total,
        dolar_ccl=dolar_ccl,
        advertencias=advertencias,
    )


def calcular_rebalanceo_banda(
    holdings_df: pd.DataFrame,
    config: dict,
    banda_tolerancia_pct: float = BANDA_TOLERANCIA_PCT_DEFAULT,
    monto_nuevo: float = 0.0,
    dolar_ccl: Optional[float] = None,
) -> ResultadoRebalanceoBanda:
    """
    Modo OPCIONAL de rebalanceo -- ver "Rebalanceo por Banda de
    Tolerancia, CON venta" en el docstring del modulo para la logica
    completa y la demostracion matematica de por que ningun activo
    recibe mas de lo que necesita. A diferencia de `calcular_rebalanceo`
    (DCA puro, nunca vende), esta funcion SI sugiere vender el excedente
    de los activos que se desviaron mas de `banda_tolerancia_pct` puntos
    porcentuales por ENCIMA de su objetivo, para reinvertirlo en los que
    se desviaron por DEBAJO -- opcionalmente sumando tambien plata nueva
    (`monto_nuevo`, default 0 = redistribucion pura entre lo que ya
    tenes, sin aportar nada).

    `holdings_df` y las reglas de precio faltante/bloqueante son
    identicas a `calcular_rebalanceo` (ver ese docstring). A diferencia
    del DCA, esta funcion NO lanza RebalancerError si `valor_cartera_actual`
    es 0: simplemente no hay nada que rebalancear por banda (no hay
    desviaciones posibles sin cartera), pero no es un error de datos.

    `dolar_ccl` es opcional, igual que en `calcular_rebalanceo`: si se
    pasa, se agrega el equivalente en USD tanto a las ventas como a las
    compras sugeridas.

    LIMITACION IMPORTANTE: vender implica un evento fiscal real que esta
    funcion NO calcula (ver el docstring del modulo) -- `advertencias`
    siempre incluye un recordatorio de esto si hay al menos una venta.
    """
    if banda_tolerancia_pct is None or banda_tolerancia_pct <= 0:
        raise RebalancerError("La banda de tolerancia debe ser mayor a 0 puntos porcentuales.")
    if monto_nuevo is None or monto_nuevo < 0:
        raise RebalancerError("El monto nuevo (opcional) no puede ser negativo.")

    holdings, objetivos, advertencias = _preparar_objetivos_y_precios(holdings_df, config)

    valor_cartera_actual = float(holdings["Valor ARS"].fillna(0).sum())
    valor_total_futuro = valor_cartera_actual + monto_nuevo

    if valor_cartera_actual <= 0:
        # Sin cartera valuada no hay "% Actual" que comparar contra el
        # objetivo -- a diferencia del DCA (que si tiene sentido con
        # cartera vacia, ver test_cartera_vacia), rebalancear por banda
        # sin ninguna posicion existente no es un caso real: se devuelve
        # un resultado vacio en vez de forzar numeros sin sentido.
        vacio = pd.DataFrame(columns=COLUMNAS_DESVIACIONES)
        return ResultadoRebalanceoBanda(
            desviaciones=vacio,
            ordenes_venta=pd.DataFrame(columns=COLUMNAS_ORDENES_VENTA),
            ordenes_compra=pd.DataFrame(columns=COLUMNAS_ORDENES_COMPRA_BANDA),
            banda_tolerancia_pct=banda_tolerancia_pct,
            monto_nuevo=monto_nuevo,
            valor_cartera_actual=0.0,
            valor_total_futuro=valor_total_futuro,
            venta_bruta_total=0.0,
            comision_venta_total=0.0,
            venta_neta_total=0.0,
            efectivo_disponible_total=monto_nuevo,
            compra_neta_total=0.0,
            comision_compra_total=0.0,
            costo_compra_total=0.0,
            efectivo_sobrante=monto_nuevo,
            dolar_ccl=dolar_ccl,
            advertencias=advertencias + ["La cartera no tiene valor actual: no hay desviaciones que calcular."],
        )

    # --- Paso 1: desviacion de CADA activo (dentro y fuera de banda) ---
    filas_desviacion = []
    for ticker, pct_objetivo in objetivos.items():
        if ticker not in holdings.index:
            continue
        fila = holdings.loc[ticker]
        valor_actual_raw = fila["Valor ARS"]
        valor_actual = 0.0 if pd.isna(valor_actual_raw) else float(valor_actual_raw)
        pct_actual = valor_actual / valor_cartera_actual * 100
        desviacion_pp = pct_actual - pct_objetivo
        meta_ars = valor_total_futuro * pct_objetivo / 100

        if desviacion_pp > banda_tolerancia_pct:
            estado = "Sobreponderado"
        elif desviacion_pp < -banda_tolerancia_pct:
            estado = "Subponderado"
        else:
            estado = "Dentro de banda"

        filas_desviacion.append(
            {
                "Ticker": ticker,
                "Categoria": fila["Categoria"],
                "Estado": estado,
                "% Objetivo": round(pct_objetivo, 2),
                "% Actual": round(pct_actual, 2),
                "Desviacion pp": round(desviacion_pp, 2),
                "Valor Actual ARS": round(valor_actual, 2),
                "Meta ARS": round(meta_ars, 2),
                "_valor_actual_raw": valor_actual,  # uso interno, no va en COLUMNAS_DESVIACIONES
                "_meta_ars_raw": meta_ars,
            }
        )

    desviaciones_completas = pd.DataFrame(filas_desviacion)

    tickers_huerfanos_sobreponderados = [
        f["Ticker"] for f in filas_desviacion if f["Estado"] == "Sobreponderado" and f["% Objetivo"] == 0.0
    ]
    if tickers_huerfanos_sobreponderados:
        advertencias.append(
            f"{tickers_huerfanos_sobreponderados} tienen 0% Objetivo (huerfanos, ver "
            "core/holdings.py) y por lo tanto aparecen como 'Sobreponderados' con una venta "
            "sugerida por el TOTAL de su posicion -- no es un error, es la misma logica de "
            "'0% Objetivo = nunca recibe compras' aplicada del otro lado."
        )

    # --- Paso 2: ordenes de VENTA (sobreponderados fuera de banda) ---
    filas_venta = []
    for f in filas_desviacion:
        if f["Estado"] != "Sobreponderado":
            continue
        ticker = f["Ticker"]
        exceso_ars = f["_valor_actual_raw"] - f["_meta_ars_raw"]
        if exceso_ars <= 0:
            # Puede pasar de verdad (no es solo una red de seguridad)
            # cuando `monto_nuevo` es grande: la Meta de este activo se
            # calcula sobre Valor Total Futuro (incluye monto_nuevo, ver
            # docstring del modulo), asi que un aporte grande puede subir
            # la Meta en ARS por encima del Valor Actual aunque el % de
            # HOY siga fuera de banda -- la plata nueva ya diluye el
            # sobrepeso sin necesidad de vender nada de este activo.
            advertencias.append(
                f"'{ticker}' esta fuera de banda por su % actual, pero el Monto Nuevo alcanza "
                "para diluir su sobrepeso sin vender nada (su Meta en ARS, ya con el aporte "
                "sumado, quedo por encima de su Valor Actual) -- no se sugiere ninguna venta "
                "para este activo."
            )
            continue

        fila_holdings = holdings.loc[ticker]
        ejecucion = _resolver_ejecucion(ticker, fila_holdings, config)
        precio_ars = ejecucion["Precio ARS"]

        if pd.isna(precio_ars) or precio_ars is None or precio_ars <= 0:
            advertencias.append(
                f"'{ticker}' esta sobreponderado fuera de banda pero no tiene precio disponible "
                "para calcular cuantos nominales vender -- se omite de las ordenes de venta."
            )
            continue

        # Redondeo hacia ABAJO, mismo criterio que las compras: vender de
        # mas empujaria al activo por DEBAJO de su Meta ("overshoot" para
        # el otro lado) -- ver docstring del modulo.
        nominales_vender = float(math.floor(exceso_ars / precio_ars))
        if nominales_vender <= 0:
            continue

        monto_bruto = round(nominales_vender * precio_ars, 2)
        comision = (
            round(monto_bruto * COMISION_PCT_APROX / 100, 2) if _aplica_comision_cocos(ticker, config) else 0.0
        )
        monto_neto = round(monto_bruto - comision, 2)

        filas_venta.append(
            {
                "Ticker": ticker,
                "Ticker Ejecucion": ejecucion["Ticker Ejecucion"],
                "Categoria": f["Categoria"],
                "Nominales a Vender": nominales_vender,
                "Precio Actual": ejecucion["Precio Actual"],
                "Moneda": ejecucion["Moneda"],
                "Monto Bruto Venta ARS": monto_bruto,
                "Comision Estimada ARS": comision,
                "Monto Neto Venta ARS": monto_neto,
                "Equivalente USD": round(monto_neto / dolar_ccl, 2) if dolar_ccl else None,
                "% Objetivo": f["% Objetivo"],
                "% Actual": f["% Actual"],
                "Desviacion pp": f["Desviacion pp"],
                "Valor Actual ARS": f["Valor Actual ARS"],
                "Meta ARS": f["Meta ARS"],
                "Exceso ARS": round(exceso_ars, 2),
            }
        )

    ordenes_venta = pd.DataFrame(filas_venta, columns=COLUMNAS_ORDENES_VENTA)
    if not ordenes_venta.empty:
        ordenes_venta = ordenes_venta.sort_values("Monto Neto Venta ARS", ascending=False).reset_index(drop=True)

    venta_bruta_total = round(float(ordenes_venta["Monto Bruto Venta ARS"].sum()), 2) if not ordenes_venta.empty else 0.0
    comision_venta_total = round(float(ordenes_venta["Comision Estimada ARS"].sum()), 2) if not ordenes_venta.empty else 0.0
    venta_neta_total = round(venta_bruta_total - comision_venta_total, 2)
    efectivo_disponible_total = round(venta_neta_total + monto_nuevo, 2)

    if ordenes_venta.empty and monto_nuevo <= 0:
        advertencias.append(
            "Ningun activo esta desviado mas de "
            f"{banda_tolerancia_pct:.1f} puntos porcentuales por ENCIMA de su objetivo, y no "
            "se ingreso Monto Nuevo: no hay efectivo disponible para comprar nada."
        )
    elif not ordenes_venta.empty:
        advertencias.append(
            "Vender implica un posible impacto impositivo (Bienes Personales/Ganancias segun tu "
            "situacion) que este calculo NO estima -- 'Monto Neto Venta ARS' es neto de la "
            "comision del broker unicamente, no de impuestos. Revisa el impacto fiscal de cada "
            "venta antes de ejecutarla."
        )

    # --- Paso 3: ordenes de COMPRA (subponderados fuera de banda), ---
    # financiadas por `efectivo_disponible_total` -- MISMA formula
    # proporcional-y-nunca-overshootea que calcular_rebalanceo (DCA).
    filas_compra_base = []
    for f in filas_desviacion:
        if f["Estado"] != "Subponderado":
            continue
        ticker = f["Ticker"]
        deficit_ars = f["_meta_ars_raw"] - f["_valor_actual_raw"]
        if deficit_ars <= 0:
            continue  # red de seguridad: no deberia pasar si Estado == "Subponderado"

        fila_holdings = holdings.loc[ticker]
        ejecucion = _resolver_ejecucion(ticker, fila_holdings, config)
        filas_compra_base.append(
            {
                "Ticker": ticker,
                "Ticker Ejecucion": ejecucion["Ticker Ejecucion"],
                "Categoria": f["Categoria"],
                "Precio Actual": ejecucion["Precio Actual"],
                "Moneda": ejecucion["Moneda"],
                "Precio ARS": ejecucion["Precio ARS"],
                "% Objetivo": f["% Objetivo"],
                "% Actual": f["% Actual"],
                "Desviacion pp": f["Desviacion pp"],
                "Valor Actual ARS": f["Valor Actual ARS"],
                "Meta ARS": f["Meta ARS"],
                "Deficit ARS": round(deficit_ars, 2),
            }
        )

    tabla_compra = pd.DataFrame(filas_compra_base)

    if tabla_compra.empty:
        if efectivo_disponible_total > 0:
            advertencias.append(
                "No hay ningun activo desviado mas de "
                f"{banda_tolerancia_pct:.1f} puntos porcentuales por DEBAJO de su objetivo para "
                f"reinvertir el efectivo disponible (${efectivo_disponible_total:,.2f} ARS) -- "
                "queda como remanente sin asignar."
            )
        ordenes_compra = pd.DataFrame(columns=COLUMNAS_ORDENES_COMPRA_BANDA)
        compra_neta_total = comision_compra_total = costo_compra_total = 0.0
        efectivo_sobrante = round(efectivo_disponible_total, 2)
    else:
        suma_deficits = float(tabla_compra["Deficit ARS"].sum())
        if efectivo_disponible_total <= 0:
            tabla_compra["Asignacion ARS"] = 0.0
        elif efectivo_disponible_total >= suma_deficits:
            # Alcanza para cubrir el Deficit COMPLETO de todos: mejor
            # caso, la cartera queda exactamente en su Objetivo.
            tabla_compra["Asignacion ARS"] = tabla_compra["Deficit ARS"]
        else:
            tabla_compra["Asignacion ARS"] = efectivo_disponible_total * tabla_compra["Deficit ARS"] / suma_deficits
        tabla_compra["Asignacion ARS"] = tabla_compra["Asignacion ARS"].round(2)

        def _nominales_banda(row) -> float:
            precio_ars = row["Precio ARS"]
            if pd.isna(precio_ars) or precio_ars <= 0:
                return 0.0
            monto_neto_disponible = row["Asignacion ARS"]
            if _aplica_comision_cocos(row["Ticker"], config):
                monto_neto_disponible = monto_neto_disponible / (1 + COMISION_PCT_APROX / 100)
            cantidad_exacta = monto_neto_disponible / precio_ars
            return float(math.floor(cantidad_exacta))

        tabla_compra["Nominales a Comprar"] = tabla_compra.apply(_nominales_banda, axis=1)
        tabla_compra["Monto a Invertir ARS"] = (tabla_compra["Nominales a Comprar"] * tabla_compra["Precio ARS"]).round(2)
        tabla_compra["Comision Estimada ARS"] = tabla_compra.apply(
            lambda row: round(row["Monto a Invertir ARS"] * COMISION_PCT_APROX / 100, 2)
            if _aplica_comision_cocos(row["Ticker"], config)
            else 0.0,
            axis=1,
        )
        tabla_compra["Costo Total Estimado ARS"] = (
            tabla_compra["Monto a Invertir ARS"] + tabla_compra["Comision Estimada ARS"]
        ).round(2)
        tabla_compra[["Nominales a Comprar", "Monto a Invertir ARS", "Comision Estimada ARS", "Costo Total Estimado ARS"]] = (
            tabla_compra[
                ["Nominales a Comprar", "Monto a Invertir ARS", "Comision Estimada ARS", "Costo Total Estimado ARS"]
            ].fillna(0.0)
        )

        if dolar_ccl:
            tabla_compra["Equivalente USD"] = (tabla_compra["Monto a Invertir ARS"] / dolar_ccl).round(2)
        else:
            tabla_compra["Equivalente USD"] = None

        tabla_compra = tabla_compra.sort_values("Asignacion ARS", ascending=False).reset_index(drop=True)
        ordenes_compra = tabla_compra[COLUMNAS_ORDENES_COMPRA_BANDA]

        compra_neta_total = float(ordenes_compra["Monto a Invertir ARS"].sum())
        comision_compra_total = round(float(ordenes_compra["Comision Estimada ARS"].sum()), 2)
        costo_compra_total = round(compra_neta_total + comision_compra_total, 2)
        # Efectivo que sobra: por no alcanzar a cubrir ningun Deficit
        # completo (imposible si efectivo >= suma_deficits, ver arriba),
        # o -el caso normal- por el redondeo hacia abajo de nominales.
        efectivo_sobrante = round(efectivo_disponible_total - costo_compra_total, 2)

    resultado_desviaciones = desviaciones_completas[COLUMNAS_DESVIACIONES] if not desviaciones_completas.empty else pd.DataFrame(columns=COLUMNAS_DESVIACIONES)

    return ResultadoRebalanceoBanda(
        desviaciones=resultado_desviaciones,
        ordenes_venta=ordenes_venta,
        ordenes_compra=ordenes_compra,
        banda_tolerancia_pct=banda_tolerancia_pct,
        monto_nuevo=monto_nuevo,
        valor_cartera_actual=valor_cartera_actual,
        valor_total_futuro=valor_total_futuro,
        venta_bruta_total=venta_bruta_total,
        comision_venta_total=comision_venta_total,
        venta_neta_total=venta_neta_total,
        efectivo_disponible_total=efectivo_disponible_total,
        compra_neta_total=round(compra_neta_total, 2),
        comision_compra_total=comision_compra_total,
        costo_compra_total=costo_compra_total,
        efectivo_sobrante=max(efectivo_sobrante, 0.0),
        dolar_ccl=dolar_ccl,
        advertencias=advertencias,
    )


# ===========================================================================
# v10.2 -- Modo TRANSICION: vender lo que esta fuera de tu objetivo y
# reinvertir para quedar en tu asignacion objetivo
# ===========================================================================
@dataclass
class ResultadoTransicion:
    ventas: pd.DataFrame  # una fila por venta sugerida (ver COLUMNAS_VENTA_TRANSICION)
    compras: Optional[ResultadoRebalanceo]  # None si no hay efectivo para reinvertir
    efectivo_disponible: float  # neto de las ventas + monto_nuevo (ARS)
    comision_ventas: float
    comision_compras: float
    vuelto: float  # efectivo que queda sin invertir por el redondeo de nominales
    pesos_antes: pd.Series  # ticker -> % de la cartera valuada, hoy
    pesos_despues: pd.Series  # ticker -> % despues de ejecutar el plan ("Efectivo" = vuelto)
    pesos_objetivo: pd.Series  # ticker -> % objetivo de la config
    advertencias: List[str] = field(default_factory=list)

    @property
    def comision_total(self) -> float:
        return round(self.comision_ventas + self.comision_compras, 2)


COLUMNAS_VENTA_TRANSICION = [
    "Ticker", "Motivo", "Nominales a Vender", "Precio ARS", "Monto Bruto ARS",
    "Comision Estimada ARS", "Monto Neto ARS", "Equivalente USD",
]


def calcular_transicion(
    holdings_df: pd.DataFrame,
    config: dict,
    vender: Optional[List[str]] = None,
    monto_nuevo: float = 0.0,
    vender_sobreponderados: bool = False,
    dolar_ccl: Optional[float] = None,
) -> ResultadoTransicion:
    """
    Plan de TRANSICION hacia la cartera objetivo, en dos pasos:

    1. VENTAS: se vende la posicion COMPLETA de cada ticker de `vender`
       (por defecto: todo lo que tiene 0% objetivo, o sea lo que esta
       fuera de la config). Con `vender_sobreponderados=True` tambien se
       vende el EXCEDENTE (redondeado hacia abajo) de los activos de la
       config que estan por encima de su objetivo, calculado sobre el
       valor total despues de la transicion.
    2. COMPRAS: el efectivo neto de esas ventas (menos la comision
       estimada) mas `monto_nuevo` se reinvierte con `calcular_rebalanceo`
       (el mismo algoritmo del DCA, ya testeado): va a los activos con
       deficit, en proporcion a su deficit, con nominales enteros y
       comision descontada.

    A diferencia de `calcular_rebalanceo_banda`, no hay umbral: todo lo
    elegido se vende entero, por chico que sea. Se aplica la comision
    estimada de Cocos Capital a TODAS las ventas (si parte de una posicion
    es una tenencia manual en otro broker, esa parte se vende alla, con
    sus propios costos). Vender puede tener impacto impositivo, que esta
    funcion no calcula.
    """
    if monto_nuevo is None or monto_nuevo < 0:
        raise RebalancerError("El monto nuevo no puede ser negativo.")
    objetivos = get_target_by_ticker(config)
    h = holdings_df.copy()
    h["Valor ARS"] = pd.to_numeric(h["Valor ARS"], errors="coerce")
    h["Precio ARS"] = pd.to_numeric(h["Precio ARS"], errors="coerce")
    valuados = h[h["Valor ARS"].fillna(0) > 0]
    advertencias: List[str] = []

    if vender is None:
        vender = [
            t for t in valuados["Ticker"]
            if t not in objetivos and t != "CASH" and pd.notna(valuados.set_index("Ticker").at[t, "Precio ARS"])
        ]
    vender = [str(t).strip().upper() for t in vender]
    no_validos = [t for t in vender if t not in set(valuados["Ticker"])]
    if no_validos:
        raise RebalancerError(f"No hay posicion valuada para vender: {', '.join(no_validos)}.")
    en_objetivo = [t for t in vender if t in objetivos]
    if en_objetivo:
        advertencias.append(
            f"Vas a vender entero {', '.join(en_objetivo)}, que SI estan en tu objetivo: el plan los va a "
            "recomprar en parte si quedan por debajo de su %. Si solo queres recortar el excedente, sacalos de "
            "la lista y usa 'vender sobreponderados'."
        )

    def _fila_venta(ticker: str, motivo: str, nominales: float, precio: float) -> dict:
        bruto = round(nominales * precio, 2)
        comision = round(bruto * COMISION_PCT_APROX / 100, 2)
        neto = round(bruto - comision, 2)
        return {
            "Ticker": ticker, "Motivo": motivo, "Nominales a Vender": nominales, "Precio ARS": precio,
            "Monto Bruto ARS": bruto, "Comision Estimada ARS": comision, "Monto Neto ARS": neto,
            "Equivalente USD": round(neto / dolar_ccl, 2) if dolar_ccl else None,
        }

    filas_venta = []
    for t in vender:
        fila = valuados[valuados["Ticker"] == t].iloc[0]
        motivo = "Fuera de objetivo" if t not in objetivos else "Venta total elegida"
        filas_venta.append(_fila_venta(t, motivo, float(fila["Cantidad"]), float(fila["Precio ARS"])))
    h_post = h[~h["Ticker"].isin(vender)].copy()

    if vender_sobreponderados:
        comision_parcial = sum(f["Comision Estimada ARS"] for f in filas_venta)
        valor_total_post = float(h["Valor ARS"].fillna(0).sum()) - comision_parcial + monto_nuevo
        for i, fila in h_post.iterrows():
            t = fila["Ticker"]
            precio = fila["Precio ARS"]
            if t not in objetivos or pd.isna(precio) or precio <= 0 or pd.isna(fila["Valor ARS"]):
                continue
            exceso = float(fila["Valor ARS"]) - objetivos[t] / 100 * valor_total_post
            nominales = float(math.floor(exceso / precio)) if exceso > 0 else 0.0
            if nominales <= 0:
                continue
            filas_venta.append(_fila_venta(t, "Sobreponderado", nominales, float(precio)))
            h_post.at[i, "Cantidad"] = float(fila["Cantidad"]) - nominales
            h_post.at[i, "Valor ARS"] = round(float(fila["Valor ARS"]) - nominales * precio, 2)

    ventas = pd.DataFrame(filas_venta, columns=COLUMNAS_VENTA_TRANSICION)
    comision_ventas = round(float(ventas["Comision Estimada ARS"].sum()), 2) if not ventas.empty else 0.0
    efectivo = round(float(ventas["Monto Neto ARS"].sum()) + monto_nuevo, 2) if not ventas.empty else float(monto_nuevo)

    compras: Optional[ResultadoRebalanceo] = None
    if efectivo > 0:
        compras = calcular_rebalanceo(h_post, config, efectivo, dolar_ccl=dolar_ccl)
        advertencias.extend(a for a in compras.advertencias if a not in advertencias)
    if not ventas.empty:
        advertencias.append(
            "Vender puede tener impacto impositivo (segun tu situacion fiscal y el tipo de activo) que este "
            "plan NO calcula: confirmalo antes de ejecutar. Las comisiones son estimadas "
            f"({COMISION_PCT_APROX:.1f}% por operacion)."
        )

    # --- pesos antes / despues / objetivo
    def _pct(serie: pd.Series) -> pd.Series:
        serie = serie[serie > 0]
        return (serie / serie.sum() * 100).sort_values(ascending=False) if serie.sum() > 0 else serie

    antes = valuados.groupby("Ticker")["Valor ARS"].sum()
    despues = h_post[h_post["Valor ARS"].fillna(0) > 0].groupby("Ticker")["Valor ARS"].sum()
    vuelto = 0.0
    comision_compras = 0.0
    if compras is not None:
        invertido = compras.ordenes.groupby("Ticker")["Monto a Invertir ARS"].sum()
        despues = despues.add(invertido, fill_value=0.0)
        vuelto = round(efectivo - compras.costo_total_estimado, 2)
        comision_compras = compras.comision_total_estimada
    else:
        vuelto = efectivo
    if vuelto > 0.005:
        despues.loc["Efectivo"] = vuelto

    return ResultadoTransicion(
        ventas=ventas,
        compras=compras,
        efectivo_disponible=efectivo,
        comision_ventas=comision_ventas,
        comision_compras=comision_compras,
        vuelto=vuelto,
        pesos_antes=_pct(antes),
        pesos_despues=_pct(despues),
        pesos_objetivo=pd.Series(objetivos, dtype=float).sort_values(ascending=False),
        advertencias=advertencias,
    )


if __name__ == "__main__":
    from core.config_manager import load_config
    from core.holdings import calcular_tenencia_actual
    from core.market_data import get_dolar_ccl

    cfg = load_config()
    holdings_df = calcular_tenencia_actual(config=cfg)

    try:
        ccl = get_dolar_ccl()
    except Exception:
        ccl = None

    resultado = calcular_rebalanceo(holdings_df, cfg, monto_x=100_000, dolar_ccl=ccl)

    print(f"Valor cartera actual: {resultado.valor_cartera_actual:,.2f} ARS")
    print(f"Valor total futuro:   {resultado.valor_total_futuro:,.2f} ARS")
    print()
    with pd.option_context("display.float_format", lambda x: f"{x:,.4f}"):
        print(resultado.ordenes.to_string(index=False))
    print()
    print(f"Monto total asignado (neto):  {resultado.monto_total_asignado:,.2f} ARS")
    print(f"Comision total estimada:      {resultado.comision_total_estimada:,.2f} ARS")
    print(f"Costo total estimado:         {resultado.costo_total_estimado:,.2f} ARS")
    print(f"Vuelto total:                 {resultado.vuelto_total:,.2f} ARS")
    for a in resultado.advertencias:
        print(f"ADVERTENCIA: {a}")
