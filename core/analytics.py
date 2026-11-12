"""
core/analytics.py

Modulo de Analitica de Riesgo (v4.0).

Descarga el historial de precios (ultimo 1 anio, configurable) de TODOS
los activos de la configuracion OBJETIVO (portfolio_config.json) via
yfinance, y calcula:
  - Matriz de correlacion de Pearson entre los rendimientos diarios.
  - Volatilidad anualizada por activo y del portafolio en su conjunto,
    ponderada por los % objetivo de la config (es analitica de la
    cartera IDEAL/objetivo, no de lo que ya tenes comprado hoy -- para
    eso esta la Pestana 1).
  - Maximum Drawdown (peor caida pico-a-valle) por activo y del
    portafolio.

Nota importante sobre monedas (leer antes de interpretar los numeros):
  - CEDEARs (BYMA, sufijo ".BA"): se usa el MISMO ticker_yfinance que el
    resto de la app (ej. "SPY.BA"), que cotiza en ARS. Esto significa
    que su volatilidad/correlacion incluye el efecto del tipo de cambio
    (CCL) ademas del riesgo del activo subyacente en si -- NO es un
    numero "purificado" de solo riesgo de mercado en USD. Two activos
    100% descorrelacionados en USD pueden aparecer correlacionados aca
    porque ambos se mueven con el CCL. Si mas adelante queres separar
    ambos efectos, habria que traer tambien el precio del subyacente en
    USD y descontar la variacion del CCL.
      EXCEPCION (v7.x, "proxy al subyacente"): si el CEDEAR tiene muy
      poco historico en yfinance -- tipico de un listado reciente en
      BYMA, ver MIN_DIAS_HISTORICO_ANALITICA mas abajo -- se usa el
      simbolo SUBYACENTE (sin ".BA", en su mercado de origen, en USD)
      en su lugar, para que el activo no desaparezca de la Analitica de
      Riesgo. Ver `descargar_precios_historicos` para el detalle; estos
      activos SI quedan "purificados" del efecto CCL (al reves que el
      resto), y se avisan aparte en `ResultadoAnalitica.advertencias`.

Como en market_data.py: un ticker que yfinance no encuentra (delistado,
mal escrito, o -en el caso de activos como acciones privadas- que
directamente no cotiza en ningun mercado publico) NO tira abajo el
calculo de los demas: se omite con un aviso, y el resultado deja
constancia de cuales quedaron afuera para que la UI lo muestre. Un
timeout de red (HTTP_TIMEOUT, ver core/market_data.py) se trata exacto
igual que cualquier otro ticker sin datos -- no cuelga la sesion de
Streamlit. Un ticker con MUY POCO historico (ej. un CEDEAR recien
listado en BYMA) recibe el mismo tratamiento aunque SI tenga datos --
ver MIN_DIAS_HISTORICO_ANALITICA mas abajo -- PERO antes de excluirlo
se intenta el proxy al subyacente (arriba); solo se descarta del todo
si ni el CEDEAR ni el subyacente alcanzan el minimo. Sin esto, esos
pocos dias recortarian la ventana comun de TODOS los demas activos al
intersectar fechas, dejando la matriz de correlacion entera en NaN.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from core.config_manager import get_target_by_ticker, load_config
# Timeout de red explicito (mismo criterio que core/market_data.py, ver
# su docstring "Timeouts de red"): sin esto, una conexion de yfinance
# colgada podia bloquear la sesion de Streamlit indefinidamente al
# descargar el historico para la Analitica de Riesgo. Idem el circuit
# breaker de rate limiting (ver "Rate limiting de Yahoo Finance --
# CIRCUIT BREAKER" en ese mismo docstring) -- se comparte el mismo
# estado de cooldown que market_data.py y historical_curve.py.
from core.market_data import (
    HTTP_TIMEOUT,
    RATE_LIMIT_COOLDOWN_SEG,
    activar_cooldown_rate_limit,
    con_reintento_rate_limit,
    en_cooldown_rate_limit,
    get_yf_session,
)

PERIODO_DEFAULT = "1y"
DIAS_TRADING_ANIO = 252  # estandar de mercado para anualizar una vol diaria

# BUG CORREGIDO (v7.x): antes, `descargar_precios_historicos` intersectaba
# las fechas de TODOS los tickers via `.dropna(how="any")` sin ningun piso
# minimo de cobertura -- un solo CEDEAR recien listado en BYMA (ej. con
# apenas 1 dia de historico en yfinance) recortaba la ventana COMUN de
# TODA la matriz de correlacion a ese unico dia, dejando practicamente
# todo en NaN (con 1-3 filas, casi todos los precios quedan "planos" tras
# el ffill de fin de semana -> varianza 0 -> correlacion de Pearson
# indefinida) aunque el resto de los activos tuvieran un anio entero de
# datos buenos. Ahora un ticker con menos de `MIN_DIAS_HISTORICO_ANALITICA`
# dias de cotizacion se excluye ANTES de intersectar fechas -- mismo
# tratamiento que "sin datos" (ver tickers_sin_datos), documentado aparte
# porque la causa es distinta (datos insuficientes, no ausentes).
MIN_DIAS_HISTORICO_ANALITICA = 20


class AnalyticsError(Exception):
    """Error al descargar precios historicos o calcular la analitica de riesgo."""


@dataclass
class ResultadoAnalitica:
    precios: pd.DataFrame                      # fecha x ticker interno, Adj Close
    rendimientos: pd.DataFrame                  # fecha x ticker interno, rendimiento diario
    matriz_correlacion: pd.DataFrame            # ticker x ticker, Pearson
    volatilidad_anualizada: pd.Series           # ticker -> % anual, ordenado desc (mayor riesgo primero)
    max_drawdown: pd.Series                     # ticker -> % (<= 0), ordenado asc (peor primero)
    volatilidad_portafolio: Optional[float]     # % anual del portafolio ponderado por objetivo
    max_drawdown_portafolio: Optional[float]    # % del portafolio ponderado por objetivo
    tickers_incluidos: List[str]
    tickers_sin_datos: List[str] = field(default_factory=list)
    advertencias: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Resolucion de simbolos: que ticker de yfinance corresponde a cada activo
# interno segun su fuente de datos.
# ---------------------------------------------------------------------------
def _ticker_yfinance_para_analitica(datos: dict) -> Optional[str]:
    fuente = datos.get("fuente_datos")
    if fuente == "yfinance":
        return datos.get("ticker_yfinance")
    return None


# ---------------------------------------------------------------------------
# Descarga de precios historicos
# ---------------------------------------------------------------------------
def _descargar_uno(simbolo: str, periodo: str) -> Optional[pd.Series]:
    """Descarga UN ticker (usado como fallback si el batch entero falla)."""
    try:
        hist = con_reintento_rate_limit(
            yf.Ticker(simbolo, session=get_yf_session()).history,
            period=periodo,
            auto_adjust=False,
            timeout=HTTP_TIMEOUT,
        )
        columna = "Adj Close" if "Adj Close" in hist.columns else "Close"
        serie = hist[columna].dropna()
        if serie.empty:
            return None
        # Ticker(...).history() devuelve el indice con tz (la del
        # mercado de origen -- ej. NYSEArca para un simbolo subyacente
        # en USD, ver "PROXY AL SUBYACENTE" en el docstring del modulo).
        # Se saca para poder combinar esta serie con las del batch (tz-
        # naive) en un mismo DataFrame -- pandas no deja mezclar indices
        # tz-aware y tz-naive al armar columnas.
        serie.index = serie.index.tz_localize(None)
        return serie
    except YFRateLimitError:
        # Silencioso a proposito: con_reintento_rate_limit ya avisa UNA
        # vez cuando se activa el cooldown global (ver core/market_data.py).
        return None
    except Exception as e:
        # Incluye timeout (HTTP_TIMEOUT): mismo tratamiento que
        # cualquier otro ticker sin historico disponible -- se omite con
        # este aviso, no cuelga el resto de la analitica.
        print(f"[analytics] Error descargando historico de {simbolo}: {e}")
        return None


def descargar_precios_historicos(
    config: Optional[dict] = None, periodo: str = PERIODO_DEFAULT
) -> Tuple[pd.DataFrame, Dict[str, str], List[str]]:
    """
    Descarga el 'Adj Close' diario de TODOS los activos de la config
    durante `periodo` (formato yfinance, ej. "1y", "6mo").

    Devuelve (precios, mapa_yf, tickers_sin_datos):
      - precios: DataFrame fecha x ticker INTERNO (ej. "SPY", "BTC"),
        recortado a las fechas donde TODOS los activos incluidos tienen
        dato (necesario para que .corr()/.std() no arrastren NaN).
      - mapa_yf: dict ticker interno -> simbolo de yfinance REALMENTE
        usado (puede diferir del "ticker_yfinance" de la config si se
        uso el proxy subyacente, ver mas abajo).
      - tickers_sin_datos: tickers de la config que no se pudieron
        descargar (sin fuente_datos valida, o yfinance no tiene datos
        ni siquiera via el proxy subyacente).

    PROXY AL SUBYACENTE (v7.x): si el CEDEAR (".BA") de un activo tiene
    menos de MIN_DIAS_HISTORICO_ANALITICA dias de historico en yfinance
    (tipico de un CEDEAR recien listado en BYMA, aunque el activo en si
    sea viejo -- ej. "XLV.BA" con 1 dia vs. "XLV" en NYSEArca con mas de
    un anio), se reintenta con el simbolo SUBYACENTE (sin ".BA") antes
    de descartar el activo. Si el subyacente SI alcanza el minimo, se
    usa esa serie -- en USD, sin el efecto del dolar CCL que tienen el
    resto de los CEDEARs (ver la nota de monedas en el docstring del
    modulo) -- para que el activo no desaparezca de la Analitica de
    Riesgo solo por ser una posicion nueva en el mercado local.
    `calcular_analitica_riesgo` compara `mapa_yf` contra
    `ticker_yfinance` de la config para saber cuales usaron este proxy y
    avisarlo aparte.

    Robustez (mismo patron que market_data._ultimos_cierres_yfinance_batch):
    la descarga se intenta primero en UN solo batch (mas eficiente); si
    el batch entero revienta (yfinance a veces lanza una excepcion
    global si algun simbolo del lote es invalido), se reintenta ticker
    por ticker para que UN simbolo roto no tire abajo a los demas.

    Rate limiting (v7.x, circuit breaker -- ver "Rate limiting de Yahoo
    Finance -- CIRCUIT BREAKER" en core/market_data.py): yf.download()
    no relanza YFRateLimitError al caller -- lo atrapa por ticker
    adentro del pool de threads y deja esa columna vacia, sin que el
    batch "reviente", aunque TODOS los simbolos hayan sido
    rate-limitados. Si eso pasa (0 columnas sobre 2+ simbolos pedidos),
    se activa el cooldown global a mano ANTES de caer al fallback
    ticker por ticker -- ese fallback corta cada simbolo al instante
    gracias al cooldown ya activo (estado COMPARTIDO con
    core/market_data.py y core/historical_curve.py).
    """
    config = config or load_config()

    mapa_yf: Dict[str, str] = {}
    tickers_sin_datos: List[str] = []
    for ticker, datos in config["activos"].items():
        simbolo = _ticker_yfinance_para_analitica(datos)
        if simbolo:
            mapa_yf[ticker] = simbolo
        else:
            tickers_sin_datos.append(ticker)

    if not mapa_yf:
        raise AnalyticsError("La configuracion no tiene ningun activo con un simbolo de yfinance resoluble.")

    simbolos = list(mapa_yf.values())

    data_batch = None
    if not en_cooldown_rate_limit():
        try:
            data_batch = yf.download(
                simbolos, period=periodo, progress=False, group_by="ticker",
                threads=True, auto_adjust=False,
                timeout=HTTP_TIMEOUT, session=get_yf_session(),
            )
        except Exception as e:
            # Incluye timeout del batch entero (HTTP_TIMEOUT): se
            # reintenta ticker por ticker mas abajo (cada uno con su
            # propio timeout), mismo tratamiento que un batch roto por
            # cualquier otra razon.
            print(f"[analytics] Error descargando historico en batch ({e}); reintento ticker por ticker.")
            data_batch = None

        if len(simbolos) >= 2 and data_batch is not None and data_batch.empty:
            ya_estaba_en_cooldown = en_cooldown_rate_limit()
            activar_cooldown_rate_limit()
            if not ya_estaba_en_cooldown:
                print(
                    f"[analytics] Los {len(simbolos)} simbolos pedidos volvieron vacios del batch "
                    f"(probable rate limit de yfinance) -- se pausan las consultas a yfinance por "
                    f"{RATE_LIMIT_COOLDOWN_SEG}s."
                )

    columnas: Dict[str, pd.Series] = {}
    for ticker, simbolo in mapa_yf.items():
        serie = None
        if data_batch is not None:
            try:
                sub = data_batch[simbolo] if len(simbolos) > 1 else data_batch
                columna = "Adj Close" if "Adj Close" in sub.columns else "Close"
                serie = sub[columna].dropna()
                if serie.empty:
                    serie = None
            except Exception:
                serie = None
        if serie is None:
            serie = _descargar_uno(simbolo, periodo)

        # v7.x -- PROXY AL SUBYACENTE: un CEDEAR de BYMA (sufijo ".BA")
        # puede tener MUY poco historico en yfinance aunque el ETF/accion
        # SUBYACENTE (el mismo simbolo, sin ".BA", cotizando en su
        # mercado de origen en USD) tenga decadas de datos -- tipico
        # cuando el CEDEAR se listo en BYMA hace poco pero el activo en
        # si es viejo (ej. "XLV.BA" con 1 solo dia de historico via
        # yfinance, vs. "XLV" en NYSEArca con >250). Sin este fallback,
        # ese activo quedaba afuera de la Analitica de Riesgo aunque
        # estuviera en la config objetivo -- se prueba el subyacente
        # ANTES de descartarlo del todo.
        if (
            simbolo.upper().endswith(".BA")
            and (serie is None or len(serie) < MIN_DIAS_HISTORICO_ANALITICA)
        ):
            simbolo_subyacente = simbolo[: -len(".BA")]
            serie_subyacente = _descargar_uno(simbolo_subyacente, periodo)
            if serie_subyacente is not None and len(serie_subyacente) >= MIN_DIAS_HISTORICO_ANALITICA:
                print(
                    f"[analytics] '{ticker}' ({simbolo}) sin historico suficiente en BYMA -- se usa "
                    f"el subyacente '{simbolo_subyacente}' (USD) como proxy para la Analitica de "
                    "Riesgo. Volatilidad/correlacion de este activo NO incluyen el efecto del dolar "
                    "CCL, a diferencia del resto de los CEDEARs -- ver docstring del modulo."
                )
                serie = serie_subyacente
                simbolo = simbolo_subyacente
                mapa_yf[ticker] = simbolo_subyacente

        if serie is None:
            print(f"[analytics] '{ticker}' ({simbolo}) sin historico disponible en yfinance; se omite.")
            tickers_sin_datos.append(ticker)
        elif len(serie) < MIN_DIAS_HISTORICO_ANALITICA:
            # Ver MIN_DIAS_HISTORICO_ANALITICA arriba: un ticker con
            # pocos dias de historico (y cuyo proxy subyacente, si se
            # probo arriba, TAMPOCO alcanzo) NO se descarta por "sin
            # datos" -- SI tiene datos, son insuficientes para no
            # arrastrar a todos los demas activos a esa misma ventana
            # corta al intersectar fechas mas abajo.
            print(
                f"[analytics] '{ticker}' ({simbolo}) tiene solo {len(serie)} dia(s) de historico "
                f"(< {MIN_DIAS_HISTORICO_ANALITICA}, ¿listado reciente en BYMA?); se omite de la "
                "Analitica de Riesgo para no recortar la ventana comun de los demas activos."
            )
            tickers_sin_datos.append(ticker)
        else:
            columnas[ticker] = serie

    if not columnas:
        raise AnalyticsError(
            "No se pudo descargar el historico de NINGUN activo. Revisa tu conexion a internet."
        )

    precios = pd.DataFrame(columnas).sort_index()
    # Un ticker "joven" (empezo a cotizar despues que los demas) va a
    # tener NaN al principio de la serie combinada: se completa hacia
    # adelante (ffill) y se descartan las filas que sigan incompletas,
    # para no romper .corr()/.std() con NaN sueltos.
    precios = precios.ffill().dropna(how="any")

    if precios.empty:
        raise AnalyticsError(
            "Los activos descargados no tienen NINGUNA fecha en comun (revisa el periodo elegido)."
        )

    return precios, mapa_yf, tickers_sin_datos


# ---------------------------------------------------------------------------
# Metricas de riesgo
# ---------------------------------------------------------------------------
def calcular_rendimientos_diarios(precios: pd.DataFrame) -> pd.DataFrame:
    """Rendimiento porcentual diario (precio_hoy / precio_ayer - 1) por ticker.

    fill_method=None explicito: `precios` ya viene sin NaN (descargar_precios_historicos
    hace ffill + dropna), asi que no hay nada que rellenar; esto tambien evita el
    FutureWarning de pandas por el default de pct_change que va a cambiar.
    """
    return precios.pct_change(fill_method=None).dropna(how="all")


def calcular_matriz_correlacion(rendimientos: pd.DataFrame) -> pd.DataFrame:
    """Correlacion de Pearson entre los rendimientos diarios de cada par de activos."""
    return rendimientos.corr(method="pearson")


def calcular_volatilidad_anualizada(rendimientos: pd.DataFrame) -> pd.Series:
    """
    Desvio estandar de los rendimientos diarios, anualizado con la raiz
    de 252 (dias habiles de mercado por anio) y expresado en %. Ordenado
    de mayor a menor (el activo mas riesgoso primero).
    """
    vol = rendimientos.std(ddof=1) * np.sqrt(DIAS_TRADING_ANIO) * 100
    return vol.sort_values(ascending=False)


def calcular_max_drawdown(precios: pd.DataFrame) -> pd.Series:
    """
    Peor caida pico-a-valle de cada activo dentro del periodo descargado,
    en %. Siempre <= 0 (0% = nunca bajo de su propio maximo del periodo).
    Ordenado de peor a mejor (la caida mas fuerte primero).
    """
    maximos_acumulados = precios.cummax()
    drawdown = (precios / maximos_acumulados - 1.0) * 100
    peor = drawdown.min()
    return peor.sort_values(ascending=True)


def calcular_metricas_portafolio(
    rendimientos: pd.DataFrame, pesos: Dict[str, float]
) -> Tuple[Optional[float], Optional[float], List[str]]:
    """
    Combina los rendimientos diarios de cada activo segun `pesos` (% de
    cada ticker sobre el total, de config_manager.get_target_by_ticker)
    para construir la serie de rendimiento del PORTAFOLIO OBJETIVO
    completo, y devuelve (volatilidad_anualizada_%, max_drawdown_%,
    advertencias).

    Si faltan datos historicos de algunos activos, renormaliza los pesos
    de los que SI tienen datos para que sigan sumando 100% entre si (en
    vez de tratarlos como 0%, lo que subestimaria el riesgo real de la
    cartera) y deja constancia en advertencias.

    El indice de precio del portafolio se arma componiendo los
    rendimientos ponderados dia a dia (no promediando precios en niveles
    crudos, que estarian en escalas/monedas distintas entre CEDEARs y
    cripto): indice_t = indice_(t-1) * (1 + rendimiento_ponderado_t).
    """
    advertencias: List[str] = []
    tickers_disponibles = [t for t in rendimientos.columns if t in pesos]
    if not tickers_disponibles:
        return None, None, ["No hay ningun activo con datos historicos que tambien este en la configuracion."]

    pesos_disponibles = pd.Series({t: pesos[t] for t in tickers_disponibles})
    suma_pesos = float(pesos_disponibles.sum())

    faltantes = [t for t in pesos if t not in tickers_disponibles]
    if faltantes:
        advertencias.append(
            f"El riesgo del PORTAFOLIO se calculo renormalizando los pesos sin "
            f"{', '.join(faltantes)} (sin historico disponible): no representa el "
            f"100% de tu cartera objetivo, solo la porcion con datos."
        )

    if suma_pesos <= 0:
        return None, None, advertencias

    pesos_normalizados = pesos_disponibles / suma_pesos

    rendimiento_portafolio = (rendimientos[tickers_disponibles] * pesos_normalizados).sum(axis=1)
    volatilidad = float(rendimiento_portafolio.std(ddof=1) * np.sqrt(DIAS_TRADING_ANIO) * 100)

    indice_portafolio = (1 + rendimiento_portafolio).cumprod()
    max_acumulado = indice_portafolio.cummax()
    drawdown_serie = (indice_portafolio / max_acumulado - 1.0) * 100
    max_drawdown = float(drawdown_serie.min())

    return volatilidad, max_drawdown, advertencias


# ---------------------------------------------------------------------------
# Punto de entrada: corre todo el pipeline
# ---------------------------------------------------------------------------
def calcular_analitica_riesgo(
    config: Optional[dict] = None, periodo: str = PERIODO_DEFAULT
) -> ResultadoAnalitica:
    config = config or load_config()

    precios, mapa_yf, tickers_sin_datos = descargar_precios_historicos(config, periodo)
    rendimientos = calcular_rendimientos_diarios(precios)

    matriz_correlacion = calcular_matriz_correlacion(rendimientos)
    volatilidad = calcular_volatilidad_anualizada(rendimientos)
    drawdown = calcular_max_drawdown(precios)

    pesos = get_target_by_ticker(config)
    vol_portafolio, dd_portafolio, advertencias = calcular_metricas_portafolio(rendimientos, pesos)

    if tickers_sin_datos:
        advertencias.append(
            f"Sin historico suficiente en yfinance para: {', '.join(sorted(tickers_sin_datos))} "
            f"(sin datos, o menos de {MIN_DIAS_HISTORICO_ANALITICA} dias, ni siquiera via el proxy "
            "subyacente -- tipico de un CEDEAR recien listado en BYMA). Quedan afuera de la matriz "
            "de correlacion y de las metricas de riesgo para no recortar la ventana comun de "
            "analisis de los demas activos."
        )

    # v7.x -- Proxy al subyacente (ver descargar_precios_historicos): si
    # el simbolo REALMENTE usado (mapa_yf) no coincide con el
    # "ticker_yfinance" configurado (siempre con sufijo ".BA" para un
    # CEDEAR), es porque el CEDEAR no tenia historico suficiente y se
    # sustituyo por el subyacente en USD -- se avisa aparte porque
    # cambia la base de calculo (sin el efecto del dolar CCL) respecto
    # al resto de los CEDEARs.
    tickers_con_proxy_subyacente = sorted(
        ticker
        for ticker, simbolo_usado in mapa_yf.items()
        if config["activos"].get(ticker, {}).get("fuente_datos") == "yfinance"
        and simbolo_usado != config["activos"][ticker].get("ticker_yfinance")
    )
    if tickers_con_proxy_subyacente:
        advertencias.append(
            f"{', '.join(tickers_con_proxy_subyacente)}: el CEDEAR (.BA) tiene muy poco historico "
            "en yfinance (tipico de un listado reciente en BYMA) -- se uso el ticker subyacente en "
            "USD como proxy. A diferencia del resto de los CEDEARs, la volatilidad/correlacion de "
            "estos activos NO incluye el efecto del dolar CCL."
        )

    return ResultadoAnalitica(
        precios=precios,
        rendimientos=rendimientos,
        matriz_correlacion=matriz_correlacion,
        volatilidad_anualizada=volatilidad,
        max_drawdown=drawdown,
        volatilidad_portafolio=vol_portafolio,
        max_drawdown_portafolio=dd_portafolio,
        tickers_incluidos=list(precios.columns),
        tickers_sin_datos=sorted(set(tickers_sin_datos)),
        advertencias=advertencias,
    )


if __name__ == "__main__":
    cfg = load_config()
    try:
        resultado = calcular_analitica_riesgo(cfg)
    except AnalyticsError as e:
        print(f"Error: {e}")
    else:
        print(f"Activos incluidos: {resultado.tickers_incluidos}")
        if resultado.tickers_sin_datos:
            print(f"Sin datos: {resultado.tickers_sin_datos}")
        print()
        print("Volatilidad anualizada (%):")
        print(resultado.volatilidad_anualizada.round(2).to_string())
        print()
        print("Max Drawdown (%):")
        print(resultado.max_drawdown.round(2).to_string())
        print()
        if resultado.volatilidad_portafolio is not None:
            print(f"Volatilidad del portafolio: {resultado.volatilidad_portafolio:.2f}%")
            print(f"Max Drawdown del portafolio: {resultado.max_drawdown_portafolio:.2f}%")
        print()
        print("Matriz de correlacion:")
        print(resultado.matriz_correlacion.round(2).to_string())
        for a in resultado.advertencias:
            print(f"ADVERTENCIA: {a}")
