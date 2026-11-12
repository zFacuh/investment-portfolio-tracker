"""
app.py

Panel de Control de Portafolio - UI de Streamlit (v2.0).

Integra los modulos de core/:
  - config_manager: pesos objetivo por activo/categoria (ahora tambien
    editable en vivo desde la Pestana 2).
  - csv_parser:      movimientos historicos de Cocos Capital.
  - market_data:     cotizaciones en vivo (yfinance + dolar CCL).
  - holdings:        cruce -> tenencia actual valuada en ARS.
  - rebalancer:       algoritmo de DCA -> ordenes de compra sugeridas.

Estructura (v2.0 - por pestanas, sin expanders):
  Pestana 1 "Panel DCA & Rebalanceo": metricas, donas Actual vs Objetivo,
    tabla de tenencia, calculadora DCA y ordenes de ejecucion, todo a la vista.
  Pestana 2 "Configurador de Portafolio": grillas editables (st.data_editor)
    para los % objetivo de categorias y activos, con validacion en vivo y
    guardado a portfolio_config.json.

Correr con:  streamlit run app.py
"""

import html as html_lib
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from core.config_manager import (
    TIPOS_ACTIVO,
    TOLERANCIA_PCT,
    ConfigError,
    get_benchmark_tickers,
    get_target_by_ticker,
    guardar_desde_editor,
    load_config,
    validar_dataframes_editor,
)
from core.analytics import AnalyticsError, calcular_analitica_riesgo
from core.csv_parser import CsvParserError, parsear_movimientos, usando_demo
from core.rutas import MOVIMIENTOS_DIR
from core.historical_curve import HistoricalCurveError, calcular_curva_historica
from core.holdings import calcular_tenencia_actual
from core.manual_holdings import (
    CATEGORIA_FUERA_DE_OBJETIVO,
    ManualHoldingsError,
    cargar_tenencias_manuales,
    guardar_tenencias_manuales,
)
from core.market_data import MarketDataError, get_dolar_ccl, obtener_cotizaciones
from core.rebalancer import (
    BANDA_TOLERANCIA_PCT_DEFAULT,
    COMISION_PCT_APROX,
    RebalancerError,
    calcular_rebalanceo,
    calcular_rebalanceo_banda,
)
from core.macro_data import MacroDataError, get_ccl_historico, get_inflacion_mensual
from core.market_extras import obtener_perfiles, obtener_variacion_diaria, simbolos_para_variacion
from ui import tab_aportes, tab_decisiones, tab_metas, tab_rendimiento, tab_riesgo_real
from ui.componentes import Contexto
from ui.themes import (
    aplicar_tema,
    clase_badge_categoria,
    color_por_ticker,
    estilo_celda_categoria,
    estilo_deficit,
    estilo_estado_banda,
    get_tema_activo,
    header_html,
    plotly_base,
    rgba,
    seccion,
    selector_de_tema,
)

st.set_page_config(
    page_title="Investment Portfolio Tracker",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="expanded",
)

if usando_demo():
    st.info(f"Estás viendo datos de demostración. Para ver tu cartera, poné los CSV de movimientos de tu broker en {MOVIMIENTOS_DIR} (ver README).")

# ---------------------------------------------------------------------------
# v9.0 -- Temas visuales intercambiables (ver ui/themes.py).
# El CSS "Cyberpunk Minimalista" (v8.0) que vivia aca se reemplazo por un
# motor de temas: cada tema es un set de tokens (colores, fuentes, radios)
# y el CSS, el tema nativo de Streamlit (el UNICO que llega al interior de
# las tablas st.dataframe, dibujadas en <canvas> por glide-data-grid), los
# colores de Plotly y los estilos de celda de pandas Styler se generan a
# partir de esos tokens. app.py ya no tiene colores hardcodeados: todo sale
# de TEMA. El tema se elige desde la sidebar y se recuerda en
# config/ui_prefs.json. Copia del diseno anterior: _backup_ui_v8/.
# ---------------------------------------------------------------------------
TEMA = get_tema_activo()
aplicar_tema(TEMA)
with st.sidebar:
    selector_de_tema()



def _badge_categoria_html(categoria: str) -> str:
    """HTML de un badge (pill) coloreado para una Categoria, usado en las
    tarjetas de Ordenes de Ejecucion. Solo "Core"/"Satelite" tienen color
    propio reconocido por nombre; cualquier otra categoria cae en un tercer
    color ("otra"), y "(Fuera de Objetivo)" siempre va atenuado. Los colores
    salen del tema activo (ui/themes.py)."""
    nombre = (categoria or "").strip()
    clase = clase_badge_categoria(nombre, CATEGORIA_FUERA_DE_OBJETIVO)
    # escape: Categoria puede venir de texto tipeado a mano (Tenencias
    # Manuales) -- nunca se interpola texto de usuario en HTML sin escapar.
    return f'<span class="badge {clase}">{html_lib.escape(nombre) or "N/D"}</span>'


# v9.0: colores de graficos derivados del tema activo (antes: paleta neon
# fija). El orden sigue siendo FIJO por ticker -> un activo tiene siempre
# el mismo color en las tres donas.
COLOR_SURFACE = TEMA.surface  # borde entre porciones de torta = fondo de la tarjeta que las contiene
COLOR_TEXT = TEMA.text
# Par divergente de la matriz de correlacion (-1 / 0 / +1).
COLOR_DIVERGENTE_NEG, COLOR_DIVERGENTE_MID, COLOR_DIVERGENTE_POS = TEMA.divergente
# TOLERANCIA_PCT ahora vive en core/config_manager.py (la usan tanto la UI
# como El Guardian que corre antes de guardar), se importa arriba.


def _color_por_ticker(tickers: list[str]) -> dict[str, str]:
    return color_por_ticker(TEMA, tickers)


def _fmt_usd(v) -> str:
    """N/D en vez de 'None': Streamlit 1.61 muestra el texto literal "None"
    para NaN en columnas con NumberColumn(format=...) en vez de dejarlo en
    blanco, asi que estas columnas se formatean como texto a mano."""
    return "N/D" if pd.isna(v) else f"US$ {v:,.2f}"


def _fmt_num(v, prefijo: str = "", sufijo: str = "", decimales: int = 2) -> str:
    """
    Version generica de _fmt_usd para cualquier columna numerica que
    pueda tener NaN (v6.0: ahora es comun, ej. el Precio de un activo
    manual huerfano que no se pudo cotizar). Mismo motivo: NumberColumn
    muestra el texto literal "None" para NaN en vez de dejarlo en
    blanco, asi que se formatea como texto a mano antes de mostrarlo.
    """
    return "N/D" if pd.isna(v) else f"{prefijo}{v:,.{decimales}f}{sufijo}"


def _fmt_cantidad(v) -> str:
    """Cantidad de nominales: hasta 8 decimales SIN ceros de relleno (asi
    un CEDEAR entero se ve '50' y no '50.00000000', pero BTC conserva la
    precision de satoshi cuando hace falta). N/D si falta el dato."""
    return "N/D" if pd.isna(v) else f"{v:.8g}"


def _color_fondo_categoria(categoria) -> str:
    """
    CSS de fondo+texto para pintar la celda de Categoria en las tablas
    st.dataframe (via pandas Styler -- ver la nota tecnica grande sobre
    canvas/glide-data-grid arriba, cerca del CSS: esto es lo UNICO que
    Streamlit deja pintar dentro de una tabla). Misma paleta que
    _badge_categoria_html, para que una categoria se vea consistente sea
    que aparezca en un badge (lista de Ordenes) o en una celda de tabla
    (Tenencia Actual / detalle del calculo). Colores del tema activo.
    """
    return estilo_celda_categoria(TEMA, categoria, CATEGORIA_FUERA_DE_OBJETIVO)


# ---------------------------------------------------------------------------
# Carga de datos (cacheada para no golpear las APIs en cada interaccion)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner="Leyendo movimientos del broker...")
def _cargar_movimientos():
    return parsear_movimientos()


@st.cache_data(ttl=60, show_spinner="Consultando cotizaciones en vivo...")
def _cargar_cotizaciones(config: dict):
    return obtener_cotizaciones(config)


@st.cache_data(ttl=60)
def _cargar_ccl():
    return get_dolar_ccl()


# TTL largo (1 hora): esto descarga un anio de historico diario de TODOS
# los activos, es mucho mas pesado que una cotizacion en vivo y no
# necesita refrescarse a cada rato (los datos de ayer no cambian).
@st.cache_data(ttl=3600, show_spinner="Descargando historico de precios (ultimo año) y calculando riesgo...")
def _cargar_analitica(config: dict):
    return calcular_analitica_riesgo(config)


# v6.0: mismo criterio de TTL largo que _cargar_analitica de arriba --
# reconstruir la Equity Curve cruza el inventario diario (liviano, sale
# del CSV que ya esta en memoria) contra el precio de cierre historico de
# CADA ticker que alguna vez se opero (puede ser mas de un anio de datos
# diarios de 10+ activos), asi que no queremos volver a pegarle a
# yfinance en cada rerun de Streamlit (cada click de un boton, cambio de
# pestana, etc.). show_spinner= ya le pide a Streamlit que muestre un
# spinner mientras la funcion corre de verdad (cache miss) -- es el
# mismo mecanismo que un `with st.spinner(...):` manual, pero integrado
# al decorador en vez de envolver una llamada que de por si ya esta
# cacheada.
@st.cache_data(ttl=3600, show_spinner="Reconstruyendo la curva historica de valor del portafolio...")
def _cargar_curva_historica(movimientos: pd.DataFrame, benchmarks_key: "tuple[tuple[str, str], ...]"):
    # v7.x: `benchmarks_key` (tupla de (ticker, label), hasheable) es
    # parte de la firma -- no un default interno fijo -- para que
    # @st.cache_data invalide el cache solo cuando cambia: si editas
    # "benchmark_tickers" en portfolio_config.json, la proxima corrida
    # recalcula la curva con la lista nueva en vez de servir la version
    # cacheada de la anterior. Se recibe como tupla (no como lista de
    # dicts) porque los argumentos de una funcion @st.cache_data tienen
    # que ser hasheables.
    benchmarks = [{"ticker": t, "label": l} for t, l in benchmarks_key]
    return calcular_curva_historica(movimientos, benchmarks=benchmarks)


# v10.0 -- datos para las pestanas nuevas (Rendimiento, Aportes y
# dividendos, Riesgo real, Metas). TTL largo para lo macro (CCL historico e
# IPC cambian una vez por dia/mes), corto para la variacion del dia.
@st.cache_data(ttl=6 * 3600, show_spinner="Descargando dolar CCL historico e inflacion...")
def _cargar_macro():
    avisos: list[str] = []
    ccl_hist = ipc = None
    try:
        r = get_ccl_historico()
        ccl_hist, avisos = r.serie, avisos + r.advertencias
    except MacroDataError as e:
        avisos.append(f"{e} Las vistas en dolares no van a estar disponibles.")
    try:
        r = get_inflacion_mensual()
        ipc, avisos = r.serie, avisos + r.advertencias
    except MacroDataError as e:
        avisos.append(f"{e} Las vistas ajustadas por inflacion no van a estar disponibles.")
    return ccl_hist, ipc, avisos


@st.cache_data(ttl=300, show_spinner=False)
def _cargar_variacion(simbolos_key: "tuple[tuple[str, str], ...]"):
    return obtener_variacion_diaria(dict(simbolos_key))


@st.cache_data(ttl=24 * 3600, show_spinner="Consultando sector y pais de cada activo (solo la primera vez)...")
def _cargar_perfiles(tickers: tuple, config: dict):
    return obtener_perfiles(list(tickers), config)


# ---------------------------------------------------------------------------
# Estado de sesion: se inicializa ANTES de crear los widgets para que el
# monto de la Calculadora DCA (y el resultado del ultimo rebalanceo) no se
# pierdan al cambiar de pestana ni al guardar la configuracion.
# ---------------------------------------------------------------------------
st.session_state.setdefault("monto_dca", 100_000)
st.session_state.setdefault("resultado_rebalanceo", None)
st.session_state.setdefault("mostrar_detalle_calculo", False)
# Rebalanceo por Banda de Tolerancia (v7.x, con venta -- ver
# core/rebalancer.py::calcular_rebalanceo_banda): estado propio,
# separado del de la Calculadora DCA de arriba.
st.session_state.setdefault("banda_tolerancia_pct", BANDA_TOLERANCIA_PCT_DEFAULT)
st.session_state.setdefault("monto_nuevo_banda", 0)
st.session_state.setdefault("resultado_rebalanceo_banda", None)
# "benchmarks_equity_seleccionados" (Equity Curve, v7.x -- ver
# core/historical_curve.py, "CUARTA serie OPCIONAL, multiple") se
# inicializa mas abajo, en la seccion de la Equity Curve, recien cuando
# se conoce la lista de benchmarks disponibles (curva.valores_benchmark).

# ---------------------------------------------------------------------------
# Header + carga de datos base (compartida por las dos pestanas)
# ---------------------------------------------------------------------------
# v9.0: encabezado propio (HTML, ver ui.themes.header_html) en vez de
# st.title con emoji. Se reserva el lugar ACA ARRIBA con st.empty() y se
# completa mas abajo, cuando ya se conocen el dolar CCL y la hora de la
# cotizacion (el header muestra esos datos a la derecha).
_header_slot = st.empty()

try:
    config = load_config()
except ConfigError as e:
    st.error(f"Error de configuracion: {e}")
    st.stop()

try:
    movimientos = _cargar_movimientos()
except CsvParserError as e:
    st.error(f"Error leyendo los CSV de movimientos: {e}")
    st.stop()

cotizaciones = _cargar_cotizaciones(config)

# v7.0: los avisos de esta seccion ya NO se muestran como st.warning()
# apilados (cada uno ocupa una caja entera de ancho completo y, con dos o
# tres a la vez, empujaban todo el panel para abajo). Se juntan en una
# lista y se muestran en UN solo bloque compacto y colapsable justo
# despues -- mismo contenido, pero no rompe la estructura visual.
avisos_generales: list[str] = []

try:
    dolar_ccl = _cargar_ccl()
except MarketDataError as e:
    dolar_ccl = None
    avisos_generales.append(
        f"**Dolar CCL no disponible** ({e}). Los montos en USD no van a estar disponibles."
    )

try:
    tenencias_manuales = cargar_tenencias_manuales()
except ManualHoldingsError as e:
    tenencias_manuales = []
    avisos_generales.append(f"**Tenencias Manuales no disponibles** ({e}); se ignoran por esta corrida.")

holdings_df = calcular_tenencia_actual(
    config=config,
    movimientos=movimientos,
    cotizaciones=cotizaciones,
    tenencias_manuales=tenencias_manuales,
)

tickers_sin_precio = holdings_df[holdings_df["Precio Actual"].isna()]["Ticker"].tolist()
if tickers_sin_precio:
    avisos_generales.append(
        f"**Sin cotizacion en vivo:** {', '.join(tickers_sin_precio)}. "
        "Revisa tu conexion (Yahoo Finance) o volve a intentar en unos segundos. "
        "Mientras tanto, los totales y la Calculadora DCA no van a poder incluir estos activos."
    )

# v6.3: Ticker Alias vinculado (ej. BTC -> IBIT) configurado pero sin
# poder cotizarse -- distinto de "sin saldo real": aca directamente no
# se sabe el precio del alias, asi que si tenes posicion ahi (CSV o
# manual) esa parte queda AFUERA del Valor Total sin aviso si no
# chequeamos esto explicitamente.
filas_alias_sin_cotizar = holdings_df[
    holdings_df["Alias Ticker"].notna() & holdings_df["Alias Precio ARS"].isna()
]
if not filas_alias_sin_cotizar.empty:
    detalle_alias = ", ".join(
        f"{fila['Ticker']} (via {fila['Alias Ticker']})" for _, fila in filas_alias_sin_cotizar.iterrows()
    )
    avisos_generales.append(
        f"**Ticker Alias vinculado sin cotizar:** {detalle_alias}. No se pudo obtener el precio "
        "del ticker vinculado, asi que esa parte de la posicion (si la hay) no se esta sumando "
        "al Valor Total, y la Calculadora DCA no va a poder sugerir ordenes para ese activo."
    )

_header_slot.markdown(
    header_html(
        titulo="Investment Portfolio Tracker",
        subtitulo="Cocos Capital (BYMA) — asignacion objetivo y rebalanceo por DCA",
        meta=[
            ("Dolar CCL", f"$ {dolar_ccl:,.2f}" if dolar_ccl else "N/D"),
            ("Actualizado", datetime.now().strftime("%d/%m/%Y %H:%M")),
        ],
    ),
    unsafe_allow_html=True,
)

if avisos_generales:
    with st.expander(
        f"{len(avisos_generales)} aviso(s) sobre los datos de esta corrida",
        expanded=False,
        icon=":material/warning:",
    ):
        for aviso in avisos_generales:
            st.markdown(f"- {aviso}")

# v10.0: la curva historica se carga ACA (antes vivia adentro de la
# pestana Panel) porque ahora la usan cuatro pestanas. Es @st.cache_data:
# cargarla una vez sirve para todas.
benchmarks_config = get_benchmark_tickers(config)
benchmarks_config_key = tuple((b["ticker"], b["label"]) for b in benchmarks_config)
try:
    curva = _cargar_curva_historica(movimientos, benchmarks_config_key)
    curva_error = None
except HistoricalCurveError as e:
    curva = None
    curva_error = str(e)

ccl_historico, inflacion_mensual, avisos_macro = _cargar_macro()
CTX = Contexto(
    tema=TEMA,
    config=config,
    movimientos=movimientos,
    holdings=holdings_df,
    curva=curva,
    curva_error=curva_error,
    dolar_ccl=dolar_ccl,
    ccl_historico=ccl_historico,
    inflacion_mensual=inflacion_mensual,
    avisos_macro=avisos_macro,
)

# F3 -- variacion de la ultima rueda por activo (Panel: tarjeta + columna
# de la tabla de Tenencia Actual).
_simbolos_var = simbolos_para_variacion(holdings_df["Ticker"].dropna().astype(str).tolist(), config)
variacion_dia = _cargar_variacion(tuple(sorted(_simbolos_var.items())))

tab_panel, tab_rend, tab_aportes_ui, tab_riesgo, tab_metas_ui, tab_decisiones_ui, tab_config = st.tabs(
    [
        ":material/dashboard: Panel y rebalanceo",
        ":material/trending_up: Rendimiento",
        ":material/savings: Aportes y dividendos",
        ":material/query_stats: Riesgo",
        ":material/flag: Metas",
        ":material/swap_horiz: Transicion y diario",
        ":material/tune: Configuracion",
    ]
)

# ===========================================================================
# PESTANA 1 - Panel DCA & Rebalanceo
# ===========================================================================
with tab_panel:
    # v6.2 (HUD): Fila Superior -- ahora 4 cards (Valor Total ARS, Valor
    # Total USD CCL, Peor Brecha vs. Capital Invertido y Monto a
    # Invertir), cada una con su "delta" cargado con datos reales en vez
    # de ser solo el numero pelado. Para poder calcular el P&L%
    # acumulado (Tarjeta 1) y la Peor Brecha (Tarjeta 3) necesitamos la
    # curva historica (valor_ars vs capital_invertido_ars) ANTES de
    # dibujar esta fila -- se movio aca arriba el
    # _cargar_curva_historica(movimientos) que antes solo se llamaba mas
    # abajo, en la seccion del Equity Curve. Es un @st.cache_data, asi
    # que reutilizarlo mas abajo (para el grafico) no vuelve a golpear
    # yfinance ni recalcula nada.
    valor_total_ars = float(holdings_df["Valor ARS"].sum(skipna=True))
    valor_total_usd = (valor_total_ars / dolar_ccl) if dolar_ccl else None

    # (curva ya cargada arriba, antes de las pestanas -- v10.0)

    # Tarjeta 1: P&L% acumulado = ultimo Valor de Mercado vs ultimo Capital
    # Inyectado (misma logica de "Universo Cerrado" que ya trae la curva).
    pnl_delta = None
    if curva is not None and len(curva.valor_ars) and len(curva.capital_invertido_ars):
        ultimo_valor = curva.valor_ars.iloc[-1]
        ultimo_capital = curva.capital_invertido_ars.iloc[-1]
        if ultimo_capital:
            pnl_delta = f"{(ultimo_valor / ultimo_capital - 1) * 100:+.1f}%"

    # Tarjeta 3: "Peor Brecha vs. Capital Invertido" = el dia en que la
    # brecha porcentual (Valor de Mercado - Capital Inyectado) / Capital
    # Inyectado fue mas negativa. Se descartan dias con
    # capital_invertido_ars == 0 (division por cero, tipicamente el
    # arranque de la serie).
    #
    # OJO -- esto NO es un Max Drawdown pico-a-valle (no mide la caida
    # desde el maximo historico del VALOR del portafolio, que es lo que
    # normalmente se entiende por "drawdown" y es lo que si calcula
    # core.analytics.calcular_max_drawdown / calcular_max_drawdown_portafolio,
    # mostrado en la pestana Analitica de Riesgo). Son dos metricas
    # distintas a proposito: esta compara contra tu propio capital
    # puesto (util en fase de DCA, cuando "cuanto perdi respecto a lo
    # que meti" importa mas que el pico historico del activo), la otra
    # compara contra el maximo historico del portafolio (la definicion
    # estandar de riesgo de mercado). Antes ambas se llamaban "Max
    # Drawdown" en pestanas distintas -- ver ANALISIS_REVISION.md,
    # seccion 2 -- de ahi el nombre explicito aca.
    brecha_valor = "N/D"
    brecha_help = (
        "Peor brecha porcentual entre el Valor de Mercado y el Capital Invertido (DCA) "
        "hasta hoy -- NO es un drawdown pico-a-valle. Para la caida real desde el maximo "
        "historico del portafolio, ver 'Max Drawdown del Portafolio' en la pestana "
        "Analitica de Riesgo."
    )
    brecha_disponible = False
    if curva is not None:
        capital_valido = curva.capital_invertido_ars > 0
        if capital_valido.any():
            brecha_pct = (
                (curva.valor_ars[capital_valido] - curva.capital_invertido_ars[capital_valido])
                / curva.capital_invertido_ars[capital_valido]
                * 100
            )
            peor_pct = brecha_pct.min()
            peor_fecha = brecha_pct.idxmin()
            brecha_valor = f"{peor_pct:.1f}%"
            brecha_help = f"Peor momento: {peor_fecha:%d-%m-%Y}. {brecha_help}"
            brecha_disponible = True

    # F3 (v10.0): variacion de la ultima rueda, en pesos y %, sobre la
    # tenencia actual. Cada activo aporta Valor ARS x var/(1+var) (su
    # movimiento en pesos desde el cierre anterior).
    var_total_ars = var_total_pct = None
    var_fecha = None
    if not variacion_dia.empty:
        _v = holdings_df[["Ticker", "Valor ARS"]].merge(variacion_dia, on="Ticker", how="inner")
        _v = _v[_v["Valor ARS"].fillna(0) > 0]
        if not _v.empty:
            _mov = _v["Valor ARS"] * (_v["Var %"] / 100) / (1 + _v["Var %"] / 100)
            var_total_ars = float(_mov.sum())
            base_ayer = float(_v["Valor ARS"].sum()) - var_total_ars
            var_total_pct = var_total_ars / base_ayer * 100 if base_ayer else None
            var_fecha = pd.to_datetime(_v["Fecha"]).max()
            _v = _v.assign(Mov=_mov).sort_values("Var %")
            var_help = (
                f"Ultima rueda ({var_fecha:%d/%m}). Mas subieron: "
                + ", ".join(f"{tk} {v:+.1f}%" for tk, v in zip(_v["Ticker"].iloc[::-1].head(3), _v["Var %"].iloc[::-1].head(3)))
                + ". Mas bajaron: "
                + ", ".join(f"{tk} {v:+.1f}%" for tk, v in zip(_v["Ticker"].head(3), _v["Var %"].head(3)))
                + ". Cubre los activos con cotizacion diaria (no el cash)."
            )

    # v10.0: "Monto a invertir" ya no va en esta fila (repetia el input de
    # la Calculadora DCA de abajo) -- su lugar lo ocupa la variacion del dia.
    col1, col2, col_hoy, col3 = st.columns([1.15, 1.1, 1, 1])
    col1.metric(
        "Valor total (ARS)",
        f"${valor_total_ars:,.0f}" if valor_total_ars else "N/D",
        delta=pnl_delta,
        help="Ganancia/perdida acumulada vs. el capital inyectado (DCA) hasta hoy.",
    )
    col2.metric(
        "Valor total (USD, dolar CCL)",
        f"US$ {valor_total_usd:,.0f}" if valor_total_usd else "N/D",
        delta=f"CCL: ${dolar_ccl:,.2f}" if dolar_ccl else None,
        delta_color="off",
    )
    with col3:
        # Ver nota de CSS mas arriba ("st-key-metric-drawdown"): es el unico
        # gancho para pintar el VALOR de un st.metric en rojo, ya que
        # st.metric solo permite colorear el "delta" via Python. Solo se
        # aplica el contenedor (y por lo tanto el rojo) cuando hay una
        # brecha real calculada -- si "N/D" (curva no disponible) se deja
        # en el color neutro de siempre, para no insinuar una perdida que
        # no se pudo calcular.
        if brecha_disponible:
            with st.container(key="metric-drawdown"):
                st.metric("Peor brecha vs. capital", brecha_valor, help=brecha_help)
        else:
            st.metric("Peor brecha vs. capital", brecha_valor, help=brecha_help)
    if var_total_ars is not None:
        col_hoy.metric(
            "Hoy" if var_fecha is not None and var_fecha.normalize() == pd.Timestamp.today().normalize() else "Ultima rueda",
            f"{'+' if var_total_ars >= 0 else '-'}${abs(var_total_ars):,.0f}",
            delta=f"{var_total_pct:+.2f}%" if var_total_pct is not None else None,
            help=var_help,
        )
    else:
        col_hoy.metric("Hoy", "N/D", help="No se pudo obtener la variacion diaria (Yahoo Finance no respondio).")

    # E1 (v10.0): progreso hacia la meta patrimonial, si esta definida.
    tab_metas.render_progreso_panel(CTX)

    st.write("")

    # v7.0: cuadricula modular -- Bloque Izquierdo (donas Actual vs
    # Objetivo) y Bloque Derecho (Calculadora DCA + resumen directo de
    # Ordenes de Ejecucion), lado a lado en vez de todo apilado en una
    # sola columna vertical.
    col_izq, col_der = st.columns([1.15, 1], gap="large")

    # --- Donuts: distribucion actual vs objetivo ---
    # OJO (v6.1): "Distribucion Actual" tiene que mostrar TODO lo que
    # hay en holdings_df -- incluye activos huerfanos (del CSV o
    # cargados a mano) que no estan en portfolio_config.json. Antes solo
    # se graficaban los tickers de la config, asi que un huerfano
    # aparecia en la tabla de Tenencia Actual pero desaparecia del
    # grafico. "Distribucion Objetivo" en cambio SI sigue siendo
    # unicamente los tickers de la config (un huerfano por definicion
    # tiene 0% Objetivo, no aporta nada visible a esa dona).
    objetivos = get_target_by_ticker(config)
    tickers_objetivo = list(config["activos"].keys())
    tickers_actual = holdings_df["Ticker"].tolist()
    # Union para que el color de un ticker sea siempre el mismo en las
    # dos donas (este en una, en la otra, o en ambas), preservando el
    # orden fijo existente para los tickers de config.
    tickers_para_colores = tickers_objetivo + [t for t in tickers_actual if t not in tickers_objetivo]
    colores = _color_por_ticker(tickers_para_colores)

    valores_actuales = holdings_df.set_index("Ticker")["Valor ARS"].reindex(tickers_actual)
    valores_objetivo = pd.Series(objetivos).reindex(tickers_objetivo)

    def _etiquetas_selectivas(tickers_: list[str], valores) -> list[str]:
        """Etiqueta directa solo las porciones >= 3% del total; las mas
        chicas quedan sin texto (siguen identificables por color y por el
        tooltip) para evitar que las etiquetas se superpongan."""
        total = float(sum(valores)) or 1.0
        etiquetas = []
        for ticker, valor in zip(tickers_, valores):
            pct = (valor / total) * 100
            etiquetas.append(f"{ticker}<br>{pct:.1f}%" if pct >= 4 else "")
        return etiquetas

    # --- Bloque Izquierdo: donas Distribucion Actual vs Objetivo ---
    # v7.0: showlegend=False -- la leyenda horizontal de abajo obligaba a
    # hacer scroll con muchos activos. Cada porcion >=3% ya trae su
    # propia etiqueta ticker+% adentro (via _etiquetas_selectivas), y el
    # detalle exacto de cualquier porcion (chica o grande) sigue
    # disponible al pasar el mouse (hovertemplate), asi que la leyenda
    # aparte no hace falta y las dos donas quedan grandes y limpias.
    with col_izq.container(border=True, key="fp-card-distribucion"):
        seccion("Distribucion actual vs. objetivo", "Por valor de mercado en ARS")
        if valores_actuales.notna().any() and valores_actuales.fillna(0).sum() > 0:
            valores_actuales_plot = valores_actuales.fillna(0).values
            fig = make_subplots(
                rows=1,
                cols=2,
                specs=[[{"type": "domain"}, {"type": "domain"}]],
                subplot_titles=("Actual", "Objetivo"),
            )
            fig.add_trace(
                go.Pie(
                    labels=tickers_actual,
                    values=valores_actuales_plot,
                    marker=dict(
                        colors=[colores[t] for t in tickers_actual], line=dict(color=COLOR_SURFACE, width=2)
                    ),
                    hole=0.55,
                    sort=False,
                    text=_etiquetas_selectivas(tickers_actual, valores_actuales_plot),
                    textinfo="text",
                    textposition="inside",
                    insidetextorientation="horizontal",
                    hovertemplate="%{label}<br>$%{value:,.0f} ARS<br>%{percent}<extra></extra>",
                ),
                row=1,
                col=1,
            )
            fig.add_trace(
                go.Pie(
                    labels=tickers_objetivo,
                    values=valores_objetivo.values,
                    marker=dict(
                        colors=[colores[t] for t in tickers_objetivo], line=dict(color=COLOR_SURFACE, width=2)
                    ),
                    hole=0.55,
                    sort=False,
                    text=_etiquetas_selectivas(tickers_objetivo, valores_objetivo.values),
                    textinfo="text",
                    textposition="inside",
                    insidetextorientation="horizontal",
                    hovertemplate="%{label}<br>%{value:.1f}% objetivo<extra></extra>",
                ),
                row=1,
                col=2,
            )
            fig.update_layout(
                **plotly_base(
                    TEMA,
                    showlegend=False,
                    margin=dict(t=36, b=10, l=10, r=10),
                    height=380,
                    # etiquetas que no entran legibles se ocultan (siguen en el tooltip)
                    uniformtext=dict(minsize=10, mode="hide"),
                )
            )
            fig.update_annotations(font=dict(color=TEMA.text_muted, size=13))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Todavia no hay cotizaciones disponibles para graficar la distribucion actual.")

        # --- Tercer donut: Distribucion Proyectada (Actual + Rebalanceo) ---
        # v7.1: se lee el ULTIMO resultado calculado desde session_state
        # (misma fuente que usa el Bloque Derecho para las Ordenes de
        # Ejecucion, cero calculo nuevo de negocio aca) -- no hace falta
        # llamar a calcular_rebalanceo() de nuevo, la tabla de ordenes ya
        # tiene, por ticker, cuanto se le asigna comprar. La proyeccion
        # es simplemente Valor ARS actual + Monto a Invertir ARS de esa
        # orden, sumado ticker por ticker.
        #
        # OJO con el orden de ejecucion del script: esta columna
        # izquierda se dibuja ANTES que el boton "Calcular Rebalanceo"
        # (que esta en la columna derecha, mas abajo). Para que esta
        # dona no quede mostrando el rebalanceo del click ANTERIOR en
        # vez del que se acaba de calcular, el handler del boton (ver
        # mas abajo) fuerza un st.rerun() apenas termina de guardar el
        # resultado nuevo en session_state -- eso dispara una segunda
        # pasada completa del script donde, esta vez si, esta dona ya
        # lee el resultado fresco antes de dibujarse.
        resultado_para_dona = st.session_state.get("resultado_rebalanceo")
        seccion("Distribucion proyectada", "Actual + ordenes sugeridas")
        if resultado_para_dona is None:
            st.caption(
                "Calcula un rebalanceo (Calculadora DCA, a la derecha) para ver como "
                "quedaria tu tenencia despues de ejecutar las ordenes sugeridas."
            )
        else:
            montos_asignados = resultado_para_dona.ordenes.set_index("Ticker")["Monto a Invertir ARS"]
            valores_proyectados = valores_actuales.reindex(tickers_para_colores).fillna(0) + montos_asignados.reindex(
                tickers_para_colores
            ).fillna(0)
            valores_proyectados = valores_proyectados[valores_proyectados > 0]
            if valores_proyectados.empty:
                st.caption("El rebalanceo calculado no asigna compras a ningun activo.")
            else:
                tickers_proy = valores_proyectados.index.tolist()
                fig_proy = go.Figure(
                    data=[
                        go.Pie(
                            labels=tickers_proy,
                            values=valores_proyectados.values,
                            marker=dict(
                                colors=[colores[t] for t in tickers_proy], line=dict(color=COLOR_SURFACE, width=2)
                            ),
                            hole=0.55,
                            sort=False,
                            text=_etiquetas_selectivas(tickers_proy, valores_proyectados.values),
                            textinfo="text",
                            textposition="inside",
                            insidetextorientation="horizontal",
                            hovertemplate="%{label}<br>$%{value:,.0f} ARS<br>%{percent}<extra></extra>",
                        )
                    ]
                )
                fig_proy.update_layout(
                    **plotly_base(
                        TEMA,
                        showlegend=False,
                        margin=dict(t=10, b=10, l=10, r=10),
                        height=340,
                        uniformtext=dict(minsize=10, mode="hide"),
                    )
                )
                st.plotly_chart(fig_proy, use_container_width=True)

    # --- Bloque Derecho: Calculadora DCA + resumen de Ordenes de Ejecucion ---
    with col_der.container(border=True, key="fp-card-dca"):
        seccion("Calculadora DCA", "Aporte nuevo, sin vender")

        st.number_input(
            "Monto a invertir este mes (ARS)",
            min_value=0,
            step=10_000,
            format="%d",
            key="monto_dca",
        )
        calcular = st.button(
            "Calcular rebalanceo", type="primary", icon=":material/calculate:", use_container_width=True
        )

        if calcular:
            try:
                st.session_state["resultado_rebalanceo"] = calcular_rebalanceo(
                    holdings_df, config, monto_x=st.session_state["monto_dca"], dolar_ccl=dolar_ccl
                )
            except RebalancerError as e:
                st.session_state["resultado_rebalanceo"] = None
                st.error(str(e))
            else:
                # v7.1: la dona "Distribucion Proyectada" de la columna
                # IZQUIERDA ya se dibujo en este mismo paso del script
                # (col_izq va primero) usando el resultado VIEJO -- se
                # fuerza un rerun inmediato para que, en la proxima
                # pasada, esa dona ya lea este resultado recien
                # calculado antes de dibujarse. No es un calculo nuevo,
                # solo hace que la UI se entere en la misma interaccion.
                st.rerun()

        resultado = st.session_state.get("resultado_rebalanceo")
        ordenes_con_compra = None

        if resultado is not None:
            st.markdown("**Ordenes de ejecucion**")

            for advertencia in resultado.advertencias:
                st.warning(advertencia)

            # v7.x: "Asignado" ahora muestra el monto NETO (nominales sin
            # comision, igual que antes) y se agregan dos tarjetas nuevas
            # -- "Comisión Est." y "Costo Total Est." -- para que quede
            # claro cuanto de mas te va a debitar el broker. Ver el
            # docstring de core/rebalancer.py ("Comision/IVA de la orden
            # nueva") para de donde sale el % estimado.
            with st.container(key="metrics-dca-compactas"):
                # v9.0: 2x2 en vez de 4 en fila -- en la columna derecha
                # (mitad de pantalla) cuatro tarjetas en fila truncaban los
                # montos ("$100,...").
                m1, m2 = st.columns(2)
                m3, m4 = st.columns(2)
                m1.metric("Invertir", f"${resultado.monto_a_invertir:,.0f}")
                m2.metric(
                    "Asignado (neto)",
                    f"${resultado.monto_total_asignado:,.0f}",
                    help="Suma de nominales x precio de todas las ordenes, SIN comision/IVA.",
                )
                m3.metric(
                    "Comisión Est.",
                    f"${resultado.comision_total_estimada:,.0f}",
                    help=(
                        f"Comision + IVA estimada ({COMISION_PCT_APROX:.1f}% aprox., solo sobre lo "
                        "operado en Cocos Capital) -- ver core/rebalancer.py."
                    ),
                )
                m4.metric(
                    "Costo Total Est.",
                    f"${resultado.costo_total_estimado:,.0f}",
                    help="Asignado (neto) + Comisión Estimada -- lo que realmente te va a debitar el broker.",
                )
            st.caption(f"Vuelto: ${resultado.vuelto_total:,.0f}")

            ordenes_con_compra = resultado.ordenes[resultado.ordenes["Monto a Invertir ARS"] > 0].copy()

            if ordenes_con_compra.empty:
                st.info(
                    "Con este monto no alcanza para comprar ni un nominal de ningun activo "
                    "(el monto entero queda como vuelto). Probá con un monto mayor."
                )
            else:
                # v7.0: lista de tarjetas HTML en vez de un st.dataframe --
                # las celdas de un st.dataframe se dibujan en un <canvas>
                # via glide-data-grid (ver la nota tecnica grande al
                # principio del archivo, cerca del CSS), asi que no se
                # puede pintar un badge de color ahi adentro. Una tarjeta
                # HTML propia por orden si permite el badge de Categoria.
                tarjetas_html = []
                for _, fila in ordenes_con_compra.iterrows():
                    # v6.3: si esta orden tiene un Ticker Alias vinculado
                    # (ej. BTC -> IBIT), el simbolo a mostrar como titulo
                    # es el EJECUTABLE (lo que hay que tipear en Cocos
                    # Capital) -- con una anotacion chica de a que objetivo
                    # pertenece, para no perder el contexto de "esto es tu
                    # asignacion de BTC".
                    ticker_ejecucion = fila.get("Ticker Ejecucion", fila["Ticker"])
                    if pd.notna(ticker_ejecucion) and str(ticker_ejecucion) != str(fila["Ticker"]):
                        ticker_txt = (
                            f'{html_lib.escape(str(ticker_ejecucion))} '
                            f'<span style="opacity:0.6;font-weight:400;font-size:0.82em;">'
                            f'(obj. {html_lib.escape(str(fila["Ticker"]))})</span>'
                        )
                    else:
                        ticker_txt = html_lib.escape(str(fila["Ticker"]))
                    badge_html = _badge_categoria_html(fila["Categoria"])
                    nominales_txt = _fmt_cantidad(fila["Nominales a Comprar"])
                    precio_txt = _fmt_num(fila["Precio Actual"])
                    moneda_txt = html_lib.escape(str(fila["Moneda"])) if pd.notna(fila["Moneda"]) else "N/D"
                    monto_ars = float(fila["Monto a Invertir ARS"])
                    comision_ars = float(fila.get("Comision Estimada ARS", 0.0) or 0.0)
                    costo_total_ars = float(fila.get("Costo Total Estimado ARS", monto_ars) or monto_ars)
                    usd_txt = _fmt_usd(fila["Equivalente USD"])
                    usd_linea = f"≈ {usd_txt}" if usd_txt != "N/D" else ""
                    # v7.x: el monto grande de la tarjeta pasa a ser el
                    # COSTO TOTAL estimado (neto + comision/IVA) -- es lo
                    # que realmente te va a debitar el broker, no solo el
                    # bruto de los nominales. Cuando hay comision estimada
                    # (>0), se agrega una linea chica con el desglose neto
                    # + comision para que quede trazable de donde sale el
                    # numero grande.
                    desglose_html = ""
                    if comision_ars > 1e-9:
                        desglose_html = (
                            f'<div class="order-meta">neto ${monto_ars:,.2f} '
                            f"+ comisión est. ${comision_ars:,.2f} ARS "
                            f"({COMISION_PCT_APROX:.1f}%)</div>"
                        )
                    tarjetas_html.append(
                        f'<div class="order-card">'
                        f'<div class="order-row1">'
                        f'<span class="order-ticker">{ticker_txt} {badge_html}</span>'
                        f'<span class="order-amount">${costo_total_ars:,.2f} ARS</span>'
                        f"</div>"
                        f'<div class="order-meta">{nominales_txt} nominales &middot; precio est. '
                        f"{precio_txt} {moneda_txt}</div>"
                        f"{desglose_html}"
                        f'<div class="order-usd">{usd_linea}</div>'
                        f"</div>"
                    )
                st.markdown("\n".join(tarjetas_html), unsafe_allow_html=True)

        else:
            st.caption("Ingresa un monto y toca **Calcular Rebalanceo** para ver las ordenes sugeridas.")

    st.write("")  # v9.0: espacio en vez de linea -- las tarjetas ya separan las secciones

    # ===========================================================================
    # Rebalanceo por Banda de Tolerancia (v7.x, CON venta) -- seccion NUEVA,
    # separada a proposito de la Calculadora DCA de arriba (que por diseno
    # NUNCA vende, ver el docstring de core/rebalancer.py). Detecta que
    # activos se desviaron mas de `banda_tolerancia_pct` puntos porcentuales
    # de su % Objetivo y sugiere vender el excedente de los sobreponderados
    # para financiar a los subponderados, opcionalmente sumando tambien un
    # Monto Nuevo -- ver core.rebalancer.calcular_rebalanceo_banda.
    # ===========================================================================
    with st.container(border=True, key="fp-card-banda"):
        seccion("Rebalanceo por banda de tolerancia", "Incluye ventas")
        st.warning(
            "A diferencia de la Calculadora DCA de arriba, esta seccion sugiere **vender** "
            "posicion existente. Vender implica un posible impacto impositivo (Bienes "
            "Personales/Ganancias segun tu situacion) que esta calculadora NO estima -- solo "
            "descuenta la comision/IVA del broker, igual que las compras. Revisa el impacto "
            "fiscal de cada venta antes de ejecutarla."
        )

        col_banda1, col_banda2, col_banda3 = st.columns([1.3, 1.3, 1])
        col_banda1.slider(
            "Banda de tolerancia (puntos porcentuales)",
            min_value=1.0,
            max_value=20.0,
            step=0.5,
            key="banda_tolerancia_pct",
            help=(
                "Solo se sugiere operar activos cuya diferencia entre % Actual y % Objetivo "
                "supere esta banda -- los que estan adentro se dejan quietos a proposito, para "
                f"no rebalancear por ruido de mercado de un dia. Default: "
                f"{BANDA_TOLERANCIA_PCT_DEFAULT:.1f} puntos porcentuales."
            ),
        )
        col_banda2.number_input(
            "Monto nuevo a sumar (opcional, ARS)",
            min_value=0,
            step=10_000,
            format="%d",
            key="monto_nuevo_banda",
            help=(
                "Plata nueva a inyectar ADEMAS de lo que se recupera vendiendo. 0 = "
                "redistribucion pura entre lo que ya tenes, sin aportar nada."
            ),
        )
        with col_banda3:
            st.write("")
            st.write("")
            calcular_banda = st.button(
                "Calcular por banda", icon=":material/balance:", use_container_width=True, key="btn_calcular_banda"
            )

        if calcular_banda:
            try:
                st.session_state["resultado_rebalanceo_banda"] = calcular_rebalanceo_banda(
                    holdings_df,
                    config,
                    banda_tolerancia_pct=st.session_state["banda_tolerancia_pct"],
                    monto_nuevo=st.session_state["monto_nuevo_banda"],
                    dolar_ccl=dolar_ccl,
                )
            except RebalancerError as e:
                st.session_state["resultado_rebalanceo_banda"] = None
                st.error(str(e))

        resultado_banda = st.session_state.get("resultado_rebalanceo_banda")

        if resultado_banda is None:
            st.caption(
                "Ajusta la banda (y opcionalmente un Monto Nuevo) y toca **Calcular Rebalanceo "
                "por Banda** para ver que activos estan desviados de su objetivo y que ordenes "
                "de venta/compra sugiere."
            )
        else:
            for advertencia in resultado_banda.advertencias:
                st.warning(advertencia)

            # --- Tabla de desviaciones: TODOS los activos, dentro y fuera de banda ---
            st.markdown("**Desviaciones vs. Objetivo**")
            tabla_desv = resultado_banda.desviaciones.copy()
            if tabla_desv.empty:
                st.info("No hay activos con Valor Actual sobre los que calcular desviaciones.")
            else:
                def _color_estado_banda(estado):
                    return estilo_estado_banda(TEMA, estado)

                tabla_desv_estilada = tabla_desv.style.map(_color_estado_banda, subset=["Estado"]).map(
                    _color_fondo_categoria, subset=["Categoria"]
                )
                st.dataframe(
                    tabla_desv_estilada,
                    use_container_width=True,
                    hide_index=True,
                    row_height=34,
                    column_config={
                        "Ticker": st.column_config.Column(pinned=True),
                        "% Objetivo": st.column_config.NumberColumn(format="%.2f%%", alignment="center"),
                        "% Actual": st.column_config.NumberColumn(format="%.2f%%", alignment="center"),
                        "Desviacion pp": st.column_config.NumberColumn(format="%+.2f pp", alignment="center"),
                        "Valor Actual ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                        "Meta ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                        "Estado": st.column_config.Column(alignment="center"),
                        "Categoria": st.column_config.Column(alignment="center"),
                    },
                )
                st.caption(
                    f"Banda actual: ±{resultado_banda.banda_tolerancia_pct:.1f} puntos porcentuales. "
                    "Sobreponderado (rojo) = candidato a vender · Subponderado (verde) = "
                    "candidato a comprar · gris = dentro de banda, no se toca."
                )

            # --- Resumen de efectivo ---
            b1, b2, b3, b4 = st.columns(4)
            b1.metric(
                "Venta Neta",
                f"${resultado_banda.venta_neta_total:,.0f}",
                help=(
                    f"Bruto ${resultado_banda.venta_bruta_total:,.0f} - comision estimada "
                    f"${resultado_banda.comision_venta_total:,.0f}."
                ),
            )
            b2.metric(
                "Efectivo Disponible",
                f"${resultado_banda.efectivo_disponible_total:,.0f}",
                help="Venta Neta + Monto Nuevo -- lo que se reparte entre los activos subponderados.",
            )
            b3.metric(
                "Costo Compra Total",
                f"${resultado_banda.costo_compra_total:,.0f}",
                help="Nominales comprados x precio + comision estimada. Nunca supera el Efectivo Disponible.",
            )
            b4.metric(
                "Efectivo Sobrante",
                f"${resultado_banda.efectivo_sobrante:,.0f}",
                help=(
                    "Efectivo Disponible que no se pudo asignar (redondeo de nominales hacia "
                    "abajo, o no hay ningun activo subponderado que lo absorba)."
                ),
            )

            # --- Ventas sugeridas ---
            st.markdown("**Ventas Sugeridas**")
            if resultado_banda.ordenes_venta.empty:
                st.caption("Ningun activo esta sobreponderado fuera de la banda -- no hay nada que vender.")
            else:
                tabla_venta = resultado_banda.ordenes_venta.copy()
                tabla_venta["Nominales a Vender"] = tabla_venta["Nominales a Vender"].apply(_fmt_cantidad)
                tabla_venta["Precio Actual"] = tabla_venta["Precio Actual"].apply(lambda v: _fmt_num(v))
                tabla_venta["Equivalente USD"] = tabla_venta["Equivalente USD"].apply(_fmt_usd)
                tabla_venta_estilada = tabla_venta.style.map(_color_fondo_categoria, subset=["Categoria"])
                st.dataframe(
                    tabla_venta_estilada,
                    use_container_width=True,
                    hide_index=True,
                    row_height=34,
                    column_config={
                        "Ticker": st.column_config.Column(pinned=True),
                        "Ticker Ejecucion": st.column_config.TextColumn(
                            alignment="center",
                            help="Simbolo concreto a operar (distinto de 'Ticker' solo si el activo tiene un Ticker Alias vinculado).",
                        ),
                        "Monto Bruto Venta ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                        "Comision Estimada ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                        "Monto Neto Venta ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                        "% Objetivo": st.column_config.NumberColumn(format="%.2f%%", alignment="center"),
                        "% Actual": st.column_config.NumberColumn(format="%.2f%%", alignment="center"),
                        "Desviacion pp": st.column_config.NumberColumn(format="%+.2f pp", alignment="center"),
                        "Valor Actual ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                        "Meta ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                        "Exceso ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                    },
                )

            # --- Compras sugeridas (financiadas por la venta + Monto Nuevo) ---
            st.markdown("**Compras Sugeridas**")
            if resultado_banda.ordenes_compra.empty:
                st.caption("Ningun activo esta subponderado fuera de la banda -- no hay nada que comprar.")
            else:
                tabla_compra_banda = resultado_banda.ordenes_compra.copy()
                tabla_compra_banda["Nominales a Comprar"] = tabla_compra_banda["Nominales a Comprar"].apply(_fmt_cantidad)
                tabla_compra_banda["Precio Actual"] = tabla_compra_banda["Precio Actual"].apply(lambda v: _fmt_num(v))
                tabla_compra_banda["Equivalente USD"] = tabla_compra_banda["Equivalente USD"].apply(_fmt_usd)
                tabla_compra_banda_estilada = tabla_compra_banda.style.map(_color_fondo_categoria, subset=["Categoria"])
                st.dataframe(
                    tabla_compra_banda_estilada,
                    use_container_width=True,
                    hide_index=True,
                    row_height=34,
                    column_config={
                        "Ticker": st.column_config.Column(pinned=True),
                        "Ticker Ejecucion": st.column_config.TextColumn(
                            alignment="center",
                            help="Simbolo concreto a operar (distinto de 'Ticker' solo si el activo tiene un Ticker Alias vinculado).",
                        ),
                        "Monto a Invertir ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                        "Comision Estimada ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                        "Costo Total Estimado ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                        "% Objetivo": st.column_config.NumberColumn(format="%.2f%%", alignment="center"),
                        "% Actual": st.column_config.NumberColumn(format="%.2f%%", alignment="center"),
                        "Desviacion pp": st.column_config.NumberColumn(format="%+.2f pp", alignment="center"),
                        "Valor Actual ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                        "Meta ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                        "Deficit ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                        "Asignacion ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                    },
                )

    st.write("")  # v9.0: espacio en vez de linea -- las tarjetas ya separan las secciones

    # --- Equity Curve: Valor Total vs Capital Invertido en el tiempo ---
    # v6.0: cruza el inventario diario reconstruido del CSV de movimientos
    # (Compra/Venta) contra el precio de cierre historico de yfinance.
    # v6.1: suma una segunda linea, Capital Invertido (cuanta plata "de tu
    # bolsillo" llevas puesta, acumulada) -- la separacion visual entre
    # las dos lineas ES la ganancia/perdida no realizada de la cartera.
    # Ver core/historical_curve.py para el detalle completo del cruce, y
    # que instrumentos quedan afuera a proposito (cash, FCI, bonos) y por
    # que. Contenedor propio de ancho completo, debajo de la seccion de
    # rebalanceo (donas + calculadora) y antes de la tabla de Tenencia
    # Actual.
    with st.container(border=True, key="fp-card-evolucion"):
        seccion("Evolucion del portafolio", "Valor de mercado vs. capital invertido")
        # v6.2 (HUD): "curva" ya se cargo mas arriba (fila de metricas) para
        # poder calcular el P&L% y la Peor Brecha vs. Capital Invertido --
        # se reutiliza aca tal cual en vez de volver a llamar a
        # _cargar_curva_historica. Si arriba fallo (HistoricalCurveError),
        # curva quedo en None.
        if curva is None:
            st.info(f"No se pudo reconstruir la curva historica de valor: {curva_error}")
        else:
            for aviso in curva.advertencias:
                st.caption(f":material/info: {aviso}")

            # v6.1: core.historical_curve.calcular_curva_historica ya
            # garantiza que valor_ars y capital_invertido_ars comparten
            # EXACTAMENTE el mismo indice de fechas (mismo
            # rango_completo, mismo recorte de arranque) -- este assert
            # es barato y deja el desalineamiento en evidencia apenas se
            # rompa, en vez de dejar que Plotly dibuje dos lineas
            # desalineadas en silencio.
            assert curva.valor_ars.index.equals(curva.capital_invertido_ars.index), (
                "valor_ars y capital_invertido_ars deberian compartir el mismo indice de fechas."
            )
            fechas = curva.valor_ars.index

            # v7.x: N lineas OPCIONALES de benchmark (ver portfolio_config.json
            # -> meta.benchmark_tickers). Solo se ofrecen los que
            # efectivamente tienen serie calculada (curva.valores_benchmark
            # ya excluye los que no tuvieron precio -- la advertencia de
            # arriba explica por que). Un multiselect (no un checkbox por
            # cada uno) para no ensuciar el layout si hay varios
            # configurados; por default se muestran TODOS los disponibles.
            labels_disponibles = list(curva.valores_benchmark.keys())
            for label, serie in curva.valores_benchmark.items():
                assert curva.valor_ars.index.equals(serie.index), (
                    f"valores_benchmark['{label}'] deberia compartir el mismo indice que valor_ars."
                )

            labels_seleccionados: list[str] = []
            if labels_disponibles:
                st.session_state.setdefault("benchmarks_equity_seleccionados", labels_disponibles)
                # Un benchmark agregado/quitado en la config despues de la
                # ultima corrida puede dejar el session_state con labels
                # que ya no existen (o sin los nuevos) -- se filtra/completa
                # contra `labels_disponibles` en vez de que el multiselect
                # reviente con un default invalido.
                default_valido = [
                    label for label in st.session_state["benchmarks_equity_seleccionados"] if label in labels_disponibles
                ] or labels_disponibles
                labels_seleccionados = st.multiselect(
                    "Comparar contra benchmark(s)",
                    options=labels_disponibles,
                    default=default_valido,
                    key="benchmarks_equity_seleccionados",
                    help=(
                        "Simula: si cada peso que pusiste realmente en tu cartera lo hubieras "
                        "puesto, esos mismos dias, en este benchmark -- cuanto valdria hoy. "
                        "Reutiliza el mismo flujo de caja y el mismo filtro de Universo Cerrado "
                        "que ya usa Capital Invertido (ver core/historical_curve.py)."
                    ),
                )

            fig_equity = go.Figure()
            fig_equity.add_trace(
                go.Scatter(
                    x=fechas,
                    y=curva.valor_ars.values,
                    name="Valor de Mercado",
                    mode="lines",
                    line=dict(color=TEMA.linea_valor, width=2),
                    fill="tozeroy",
                    fillcolor=rgba(TEMA.linea_valor, 0.10),
                    hovertemplate="%{x|%d-%m-%Y}<br>Valor de Mercado: $%{y:,.0f} ARS<extra></extra>",
                )
            )
            fig_equity.add_trace(
                go.Scatter(
                    x=fechas,
                    y=curva.capital_invertido_ars.values,
                    name="Capital Inyectado",
                    mode="lines",
                    line=dict(color=TEMA.linea_capital, width=1.5, dash="dash"),
                    fill=None,  # sin relleno -- no debe tapar la linea de Valor de Mercado
                    hovertemplate="%{x|%d-%m-%Y}<br>Capital Inyectado: $%{y:,.0f} ARS<extra></extra>",
                )
            )
            # Paleta propia para las lineas de benchmark (distinta de cian
            # -Valor de Mercado- y gris -Capital Inyectado-, ya usados
            # arriba), ciclando si hay mas benchmarks que colores.
            colores_benchmark = list(TEMA.benchmarks)
            for i, label in enumerate(labels_seleccionados):
                color = colores_benchmark[i % len(colores_benchmark)]
                fig_equity.add_trace(
                    go.Scatter(
                        x=fechas,
                        y=curva.valores_benchmark[label].values,
                        name=f"Si hubieras comprado {label}",
                        mode="lines",
                        line=dict(color=color, width=1.5, dash="dot"),
                        fill=None,
                        hovertemplate=(
                            f"%{{x|%d-%m-%Y}}<br>Si hubieras comprado {label}: "
                            "$%{y:,.0f} ARS<extra></extra>"
                        ),
                    )
                )
            fig_equity.update_layout(
                **plotly_base(TEMA),
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                    bgcolor="rgba(0,0,0,0)",
                    font=dict(color=TEMA.text_muted),
                ),
                margin=dict(t=36, b=10, l=10, r=10),
                height=320,
                hovermode="x unified",
                xaxis=dict(title=None, showgrid=False, color=TEMA.text_muted, linecolor=TEMA.border),
                yaxis=dict(
                    title=None,
                    showgrid=True,
                    gridcolor=TEMA.chart_grid,
                    color=TEMA.text_muted,
                    zeroline=False,
                    tickprefix="$ ",
                    tickformat=",.0f",
                ),
            )
            st.plotly_chart(fig_equity, use_container_width=True)

    st.write("")  # v9.0: espacio en vez de linea -- las tarjetas ya separan las secciones

    # --- Tenencia actual (a la vista, sin expander, ahora a todo el ancho) ---
    seccion("Tenencia actual", "Posiciones valuadas a precio de mercado")

    tickers_con_alias = [
        t for t, d in config["activos"].items() if d.get("alias_ticker")
    ]
    if tickers_con_alias:
        detalle_alias_ok = ", ".join(
            f"{t} = {config['activos'][t]['alias_ticker']}" for t in tickers_con_alias
        )
        st.caption(
            f"Activo vinculado: {detalle_alias_ok}. El Valor ARS y la Cantidad de este activo "
            "ya suman su posicion propia mas la del ticker vinculado -- se "
            "muestran como una sola fila."
        )

    # "Alias Ticker"/"Alias Precio Actual"/"Alias Moneda"/"Alias Precio
    # ARS" son columnas internas (las usa core.rebalancer para saber a
    # que precio ejecutar una compra nueva, ver core/holdings.py) -- no
    # aportan nada nuevo en esta tabla (ya estan resumidas en el caption
    # de arriba) asi que se excluyen para no ensuciarla.
    tabla_tenencia = holdings_df.drop(
        columns=["Alias Ticker", "Alias Precio Actual", "Alias Moneda", "Alias Precio ARS"],
        errors="ignore",
    ).copy()
    for columna, sufijo in [
        ("Costo Neto ARS", ""),
        ("Precio Promedio Compra ARS", ""),
        ("P&L ARS", ""),
        ("P&L %", "%"),
    ]:
        tabla_tenencia[columna] = holdings_df[columna].apply(
            lambda v, s=sufijo: "N/D" if pd.isna(v) else (f"${v:,.2f}" if not s else f"{v:+.2f}%")
        )
    # v6.0: un activo manual huerfano (ver Pestana 2 -> Tenencias
    # Manuales) puede no tener cotizacion si el ticker no se resolvio;
    # Cantidad/Precio/Valor tambien pueden faltar para un activo de
    # config sin saldo. Se formatean a mano como las columnas de arriba: Streamlit
    # muestra el texto literal "None" para NaN en columnas con
    # NumberColumn(format=...) en vez de dejarlas en blanco.
    tabla_tenencia["Cantidad"] = holdings_df["Cantidad"].apply(_fmt_cantidad)
    tabla_tenencia["Precio Actual"] = holdings_df["Precio Actual"].apply(lambda v: _fmt_num(v))
    tabla_tenencia["Precio ARS"] = holdings_df["Precio ARS"].apply(lambda v: _fmt_num(v))
    tabla_tenencia["Valor ARS"] = holdings_df["Valor ARS"].apply(lambda v: _fmt_num(v, prefijo="$"))
    tabla_tenencia["% Real"] = holdings_df["% Real"].apply(lambda v: _fmt_num(v, sufijo="%"))
    # "Moneda" es texto (no numerico), pero el mismo problema de fondo
    # aplica: una fila sin cotizacion tiene Moneda=None, y Streamlit lo
    # muestra como el texto literal "None" en vez de dejarlo en blanco.
    tabla_tenencia["Moneda"] = holdings_df["Moneda"].fillna("N/D")
    # F3 (v10.0): variacion de la ultima rueda por activo
    _var_map = variacion_dia.set_index("Ticker")["Var %"] if not variacion_dia.empty else pd.Series(dtype=float)
    _pos_valor = list(tabla_tenencia.columns).index("Valor ARS") + 1
    tabla_tenencia.insert(_pos_valor, "Var. dia", holdings_df["Ticker"].map(_var_map).apply(
        lambda v: "" if pd.isna(v) else f"{v:+.2f}%"
    ))

    # v7.0: la columna Categoria se pinta via pandas Styler -- unica forma
    # de colorear celdas individuales dentro de un st.dataframe (ver nota
    # tecnica grande al principio del archivo). Misma paleta que los
    # badges HTML de las Ordenes de Ejecucion: Core=azul, Satelite=verde,
    # "(Fuera de Objetivo)"=gris atenuado.
    def _color_var_dia(v):
        if not isinstance(v, str) or not v:
            return ""
        return f"color: {TEMA.positive if not v.startswith('-') else TEMA.negative};"

    tabla_tenencia_estilada = tabla_tenencia.style.map(_color_fondo_categoria, subset=["Categoria"]).map(
        _color_var_dia, subset=["Var. dia"]
    )

    st.dataframe(
        tabla_tenencia_estilada,
        use_container_width=True,
        hide_index=True,
        row_height=34,
        column_config={
            "Ticker": st.column_config.Column(pinned=True),
            **{
                col: st.column_config.Column(alignment="center")
                for col in tabla_tenencia.columns
                if col != "Ticker"
            },
        },
    )

    # --- Detalle del calculo (checkbox, a todo el ancho) ---
    if resultado is not None:
        st.checkbox(
            "Mostrar detalle del calculo (Meta, Deficit, % Objetivo, Asignacion)",
            key="mostrar_detalle_calculo",
        )
        if st.session_state["mostrar_detalle_calculo"]:
            # v6.4: columnas elegidas y reordenadas a mano (en vez de
            # mostrar TODO resultado.ordenes tal cual viene) -- agrupa
            # primero las columnas del calculo del reparto (Objetivo vs
            # Actual, Meta, Deficit, Asignacion) y despues el resultado
            # concreto de la orden. Tambien se saco "Vuelto ARS" (ver
            # nota arriba) y se agrego "% Actual" (cuanto pesa HOY el
            # activo en la cartera, para comparar de un vistazo contra
            # "% Objetivo" -- antes solo se veia "Valor Actual ARS" en
            # pesos, sin el % que realmente importa para el rebalanceo).
            columnas_detalle_ui = [
                "Ticker",
                "Ticker Ejecucion",
                "Categoria",
                "% Objetivo",
                "% Actual",
                "Valor Actual ARS",
                "Meta ARS",
                "Deficit ARS",
                "Asignacion ARS",
                "Nominales a Comprar",
                "Precio Actual",
                "Moneda",
                "Monto a Invertir ARS",
                "Comision Estimada ARS",
                "Costo Total Estimado ARS",
                "Equivalente USD",
            ]
            tabla_detalle = resultado.ordenes[columnas_detalle_ui].copy()
            # v6.3: "Ticker Ejecucion" solo difiere de "Ticker" para un
            # activo con alias vinculado (ej. BTC -> IBIT); para el resto
            # son iguales, asi que se muestra "=" en vez de repetir el
            # mismo texto dos veces.
            tabla_detalle["Ticker Ejecucion"] = tabla_detalle.apply(
                lambda r: "=" if r["Ticker Ejecucion"] == r["Ticker"] else r["Ticker Ejecucion"], axis=1
            )
            tabla_detalle["Equivalente USD"] = tabla_detalle["Equivalente USD"].apply(_fmt_usd)
            # v6.0: un huerfano de 0% Objetivo sin cotizacion (ver arriba,
            # calcular_rebalanceo ya no bloquea el calculo por esto) deja
            # "Precio Actual" en NaN a proposito -- se formatea a mano
            # como N/D en vez de dejar que NumberColumn muestre "None".
            tabla_detalle["Precio Actual"] = tabla_detalle["Precio Actual"].apply(lambda v: _fmt_num(v))
            # v7.0 (fix menor): a esta tabla le faltaba el mismo tratamiento
            # que a "Tenencia Actual" -- un huerfano sin cotizar tambien
            # deja "Moneda" en NaN, y sin este fillna Streamlit lo mostraba
            # como el texto literal "None" en vez de "N/D".
            tabla_detalle["Moneda"] = tabla_detalle["Moneda"].fillna("N/D")

            # "Distinguida" (v6.4): el Deficit ARS es la columna que mas
            # importa para entender POR QUE un activo recibe o no parte
            # del Monto X, asi que se resalta con color en vez de dejarla
            # como un numero mas: verde si es positivo (le falta plata,
            # participa del reparto) y un gris neutro si es <= 0 (ya esta
            # en o por encima de su objetivo, no recibe nada este mes).
            def _resaltar_deficit(v):
                return estilo_deficit(TEMA, v)

            # v7.0: se encadena el pintado de Deficit ARS (arriba) con el
            # de Categoria (mismo _color_fondo_categoria de la tabla de
            # Tenencia Actual) sobre el mismo objeto Styler -- ambos
            # .map() se aplican sobre columnas distintas, sin pisarse.
            tabla_detalle_estilada = tabla_detalle.style.map(
                _resaltar_deficit, subset=["Deficit ARS"]
            ).map(_color_fondo_categoria, subset=["Categoria"])

            st.dataframe(
                tabla_detalle_estilada,
                use_container_width=True,
                hide_index=True,
                row_height=34,
                column_config={
                    "Ticker": st.column_config.TextColumn(alignment="center", pinned=True),
                    "Ticker Ejecucion": st.column_config.TextColumn(
                        alignment="center",
                        help="Simbolo concreto a operar. Distinto de 'Ticker' solo si el activo "
                        "tiene un Ticker Alias vinculado (ej. BTC se opera como IBIT en Cocos Capital).",
                    ),
                    "Categoria": st.column_config.TextColumn(alignment="center"),
                    "% Objetivo": st.column_config.NumberColumn(format="%.2f%%", alignment="center"),
                    "% Actual": st.column_config.NumberColumn(format="%.2f%%", alignment="center"),
                    "Valor Actual ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                    "Meta ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                    "Deficit ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                    "Asignacion ARS": st.column_config.NumberColumn(format="$ %.2f", alignment="center"),
                    "Nominales a Comprar": st.column_config.NumberColumn(format="%.8g", alignment="center"),
                    "Precio Actual": st.column_config.TextColumn(alignment="center"),
                    "Moneda": st.column_config.TextColumn(alignment="center"),
                    "Monto a Invertir ARS": st.column_config.NumberColumn(
                        format="$ %.2f", alignment="center", help="Nominales x precio, SIN comision/IVA."
                    ),
                    "Comision Estimada ARS": st.column_config.NumberColumn(
                        format="$ %.2f",
                        alignment="center",
                        help=(
                            f"Comision + IVA estimada ({COMISION_PCT_APROX:.1f}% aprox.). "
                            "Se descuenta del monto asignado a cada orden."
                        ),
                    ),
                    "Costo Total Estimado ARS": st.column_config.NumberColumn(
                        format="$ %.2f",
                        alignment="center",
                        help="Monto a Invertir ARS + Comision Estimada ARS -- lo que realmente te va a debitar el broker.",
                    ),
                    "Equivalente USD": st.column_config.TextColumn(alignment="center"),
                },
            )
            st.caption(
                "Deficit ARS positivo (verde) = le falta plata para llegar a su Meta, participa del "
                "reparto del Monto X este mes. Gris = ya esta en o por encima de su Objetivo. "
                "El color de fondo de Categoria sigue la misma paleta que en Tenencia Actual. "
                f"La comision estimada ({COMISION_PCT_APROX:.1f}%) es aproximada -- se descuenta del "
                "monto disponible antes de calcular nominales para que Costo Total nunca supere la Asignacion."
            )

# ===========================================================================
# PESTANA 2 - Configurador de Portafolio (v3.0: edicion completa de la
# estructura -> agregar/borrar/modificar categorias y activos, "como un
# Excel", con El Guardian (config_manager.validar_dataframes_editor)
# corriendo antes de habilitar el guardado.)
# ===========================================================================
with tab_config:
    seccion("Categorias", "Bloques de la cartera y su peso objetivo")
    st.caption(
        "Agrega, borra o edita bloques (Core/Satelite/lo que quieras). El % Objetivo "
        "Total tiene que sumar 100% entre todas las filas. Para borrar una fila, "
        "pasa el mouse por ella y toca el icono de papelera; para agregar, usa la "
        "fila '+' al final de la tabla."
    )

    df_categorias = pd.DataFrame(
        [
            {
                "Categoria": nombre,
                "% Objetivo Total": float(datos["objetivo_pct"]),
                "Descripcion": datos.get("descripcion", ""),
            }
            for nombre, datos in config["categorias"].items()
        ]
    )
    df_categorias_editado = st.data_editor(
        df_categorias,
        key="editor_categorias",
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "Categoria": st.column_config.TextColumn(
                required=True, help="Nombre del bloque, ej. 'Core'. Tiene que ser unico."
            ),
            "% Objetivo Total": st.column_config.NumberColumn(
                min_value=0, max_value=100, step=0.5, format="%.1f%%"
            ),
            "Descripcion": st.column_config.TextColumn(),
        },
    )

    seccion("Activos", "Instrumentos, categoria y peso dentro de su bloque")
    st.caption(
        "Agrega o edita activos directamente en la tabla. La Categoria se elige de un "
        "desplegable (se arma automaticamente con lo que hayas cargado arriba, no se "
        "puede escribir libre para no romper la relacion Categoria -> Activo). Para un "
        "activo NUEVO, completa 'Ticker de Mercado' con el simbolo real para cotizarlo: "
        "el de yfinance, ej. 'TSLA.BA' (para BTC, el CEDEAR 'IBIT.BA'). "
        "'Ticker Alias (opcional)' vincula este activo con OTRO ticker que "
        "sea operable en Cocos Capital: la posicion del alias se suma al Valor ARS de este activo, y "
        "las compras nuevas de la Calculadora DCA se calculan con el precio del alias "
        "en vez del propio. **Para BORRAR un activo, usa el selector 'Eliminar un "
        "activo' debajo de la tabla** (no la fila de la tabla): el data_editor de "
        "Streamlit no deja borrar filas mientras haya alguna con 'Tipo' o 'Categoria' "
        "sin completar, y ese selector evita el problema por completo."
    )

    # Las opciones del desplegable de Categoria se recalculan en cada rerun
    # a partir de la tabla de arriba YA editada -> si agregas una categoria
    # nueva, aparece disponible aca apenas Streamlit re-corre el script
    # (que pasa solo con tocar/salir de la celda que acabas de editar).
    nombres_categorias = [
        c for c in df_categorias_editado["Categoria"].dropna().astype(str).str.strip().tolist() if c
    ]

    # v6.4: "Eliminar un activo" (ver el selector + boton despues de la
    # tabla) NO edita la tabla en el momento -- guarda el Ticker en este
    # set de session_state, y ese ticker se EXCLUYE aca abajo antes de
    # construir df_activos (nunca llega a mostrarse en el data_editor).
    # Por que no usar el borrado nativo del data_editor (num_rows="dynamic",
    # seleccionar fila + icono de tacho): ese mecanismo bloquea CUALQUIER
    # cambio -- incluido borrar una fila DISTINTA -- mientras exista una
    # fila en la tabla (tipicamente una fila nueva a medio completar) con
    # una celda "required" vacia (Categoria/Tipo/Ticker de Mercado), que es
    # justo el problema que reporto el usuario. Evitarlo aca es mas
    # confiable que pelear con esa validacion del lado del cliente.
    if "activos_pendientes_borrar" not in st.session_state:
        st.session_state["activos_pendientes_borrar"] = set()

    df_activos = pd.DataFrame(
        [
            {
                "Ticker": ticker,
                "Nombre": datos.get("nombre", ""),
                "Categoria": datos.get("categoria", ""),
                "Tipo": datos.get("tipo", "CEDEAR") or "CEDEAR",
                "% Objetivo en Categoria": float(datos.get("objetivo_pct_categoria", 0)),
                "Ticker de Mercado": datos.get("ticker_yfinance") or "",
                "Ticker Alias (opcional)": datos.get("alias_ticker", "") or "",
            }
            for ticker, datos in config["activos"].items()
            if ticker not in st.session_state["activos_pendientes_borrar"]
        ]
    )
    df_activos_editado = st.data_editor(
        df_activos,
        key="editor_activos",
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "Ticker": st.column_config.TextColumn(
                required=True, help="Ticker interno, ej. 'TSLA'. Tiene que ser unico."
            ),
            "Nombre": st.column_config.TextColumn(),
            "Categoria": st.column_config.SelectboxColumn(options=nombres_categorias, required=True),
            "Tipo": st.column_config.SelectboxColumn(options=TIPOS_ACTIVO, required=True),
            "% Objetivo en Categoria": st.column_config.NumberColumn(
                min_value=0, max_value=100, step=0.5, format="%.1f%%"
            ),
            "Ticker de Mercado": st.column_config.TextColumn(
                required=True,
                help="Simbolo de yfinance para cotizar, ej. 'TSLA.BA' (para BTC: 'IBIT.BA').",
            ),
            "Ticker Alias (opcional)": st.column_config.TextColumn(
                help="Ticker vinculado, operable en Cocos Capital. Dejar "
                "vacio si no aplica. Su posicion se suma al Valor ARS de este activo, y las "
                "compras nuevas se calculan con SU precio en vez del propio.",
            ),
        },
    )

    # --- Eliminar un activo (ver nota arriba de por que no se usa el
    # borrado nativo del data_editor). Solo marca el Ticker como
    # "pendiente de borrar" en session_state y fuerza un rerun: recien se
    # aplica de verdad al disco cuando se toca "Guardar y Recalcular" mas
    # abajo (mismo comportamiento que cualquier otra edicion de esta
    # tabla -- nada se persiste solo).
    tickers_disponibles = df_activos["Ticker"].tolist()
    if tickers_disponibles:
        col_borrar1, col_borrar2 = st.columns([3, 1])
        ticker_a_borrar = col_borrar1.selectbox(
            "Eliminar un activo",
            options=tickers_disponibles,
            key="selector_borrar_activo",
            label_visibility="collapsed",
            help="Elegi el Ticker a sacar de la configuracion y toca 'Eliminar'. Se aplica "
            "recien al tocar 'Guardar y Recalcular'.",
        )
        if col_borrar2.button("Eliminar", icon=":material/delete:", key="btn_borrar_activo", use_container_width=True):
            st.session_state["activos_pendientes_borrar"].add(ticker_a_borrar)
            # Se limpia la key del data_editor: si no, Streamlit sigue
            # mostrando el estado editado VIEJO (con el ticker recien
            # borrado adentro) en vez de releer el df_activos ya filtrado
            # de arriba en el proximo rerun.
            st.session_state.pop("editor_activos", None)
            st.rerun()

    if st.session_state["activos_pendientes_borrar"]:
        col_pend1, col_pend2 = st.columns([4, 1])
        col_pend1.warning(
            "Pendiente de borrar (se aplica al Guardar y Recalcular): "
            + ", ".join(sorted(st.session_state["activos_pendientes_borrar"]))
        )
        if col_pend2.button("Deshacer", icon=":material/undo:", key="btn_deshacer_borrar_activo", use_container_width=True):
            st.session_state["activos_pendientes_borrar"] = set()
            st.session_state.pop("editor_activos", None)
            st.rerun()

    # --- El Guardian: pipeline de validacion (matematica + integridad
    # referencial + nulos/duplicados), corre ANTES de habilitar el boton.
    errores = validar_dataframes_editor(df_categorias_editado, df_activos_editado)

    # --- Resumen visual de las sumas (informativo, no reemplaza a El
    # Guardian: se calcula "a lo bruto" con pd.to_numeric/coerce para no
    # explotar mientras el usuario todavia esta escribiendo una fila a
    # medio completar).
    suma_categorias = float(pd.to_numeric(df_categorias_editado["% Objetivo Total"], errors="coerce").fillna(0).sum())
    tmp_activos = df_activos_editado.copy()
    tmp_activos["% Objetivo en Categoria"] = pd.to_numeric(
        tmp_activos.get("% Objetivo en Categoria"), errors="coerce"
    ).fillna(0)
    sumas_por_categoria = (
        tmp_activos.groupby("Categoria")["% Objetivo en Categoria"].sum() if not tmp_activos.empty else pd.Series(dtype=float)
    )

    st.divider()
    resumen_cols = st.columns(max(len(nombres_categorias), 1) + 1)
    resumen_cols[0].metric("Categorias (total)", f"{suma_categorias:.1f}%")
    for col, categoria in zip(resumen_cols[1:], nombres_categorias):
        col.metric(categoria, f"{float(sumas_por_categoria.get(categoria, 0)):.1f}%")

    if errores:
        st.error(
            "No se puede guardar todavia — corregi lo siguiente:\n\n"
            + "\n".join(f"- {e}" for e in errores)
        )
    else:
        st.success("Validacion matematica y referencial OK (todo suma 100% y todas las categorias existen). Listo para guardar.")

    guardar = st.button(
        "Guardar y recalcular",
        type="primary",
        icon=":material/save:",
        disabled=bool(errores),
        help="Se habilita cuando pasan todas las validaciones (sumas de %, categorias existentes, sin tickers vacios/duplicados)." if errores else None,
    )

    if guardar:
        try:
            guardar_desde_editor(df_categorias_editado, df_activos_editado, meta_original=config.get("meta"))
        except ConfigError as e:
            st.error(f"No se pudo guardar:\n\n{e}")
        except Exception as e:
            st.error(f"Error inesperado al guardar la configuracion: {e}")
        else:
            # El rebalanceo anterior quedo calculado contra los objetivos
            # VIEJOS (y potencialmente contra activos que ya no existen):
            # se descarta para no mostrar ordenes desactualizadas.
            st.session_state["resultado_rebalanceo"] = None
            # Los tickers pendientes de borrar ya quedaron afuera de
            # df_activos_editado (nunca se le mostraron al data_editor),
            # asi que ya se guardaron sin ellos -- se limpia el set para
            # no arrastrarlo a la proxima edicion.
            st.session_state["activos_pendientes_borrar"] = set()
            st.success("Configuracion guardada. Recalculando con los nuevos objetivos...")
            st.rerun()

    if config.get("meta", {}).get("ultima_actualizacion"):
        st.caption(f"Ultima actualizacion: {config['meta']['ultima_actualizacion']}")

    # -----------------------------------------------------------------
    # Tenencias Manuales (v6.0, rediseñado en v6.2) -- seccion
    # independiente: no tiene nada que ver con Categorias/Activos de
    # arriba (esos son objetivos; esto es tenencia real fuera de Cocos
    # Capital).
    #
    # v6.2: se reemplazo el st.data_editor(num_rows="dynamic") por una
    # lista con un boton "eliminar" explicito por fila. El data_editor
    # SI soportaba borrar filas (seleccionando la fila y tocando el
    # tacho que aparece en una mini-barra de herramientas flotante
    # arriba a la derecha de la tabla), pero ese gesto no es nada obvio
    # -- no hay ningun boton visible hasta que seleccionas la fila
    # "a ciegas", y la seccion no explicaba el mecanismo (a diferencia
    # de "Categorias" arriba, que si tiene el tip en su caption). Un
    # boton "🗑️" al lado de cada tenencia es mucho mas directo.
    # -----------------------------------------------------------------
    st.divider()
    seccion("Tenencias manuales", "Posiciones fuera de Cocos Capital")
    st.caption(
        "Activos que NO pasan por el CSV de Cocos Capital: otro "
        "broker, cripto en una wallet propia, tenencias legacy, o simplemente algo que no "
        "queres cargar por CSV ahora. Se SUMAN a lo que ya calcula el CSV (ej. 5 "
        "GOOGL del CSV + 3 acá = 8 en Tenencia Actual). Si el Ticker no existe en 'Activos' de "
        "arriba, igual se cotiza y se suma al Valor Total, pero con 0% Objetivo: nunca se le "
        "asignan compras nuevas en la Calculadora DCA."
    )

    categorias_para_manuales = nombres_categorias + [CATEGORIA_FUERA_DE_OBJETIVO]

    def _guardar_lista_manuales(registros: list) -> None:
        """Sobrescribe manual_holdings.json con `registros` (lista de
        dicts ticker/cantidad/categoria) y fuerza un recalculo limpio.
        Usado tanto por los botones de eliminar como por el form de
        agregar, asi cada accion se guarda sola, en el momento -- no
        hace falta un boton "Guardar" aparte que dependa de acordarse
        de tocarlo."""
        df = pd.DataFrame(
            [
                {
                    "Ticker": str(r.get("ticker", "")),
                    "Cantidad": float(r.get("cantidad", 0) or 0),
                    "Categoria": str(r.get("categoria", "") or ""),
                }
                for r in registros
            ],
            columns=["Ticker", "Cantidad", "Categoria"],
        )
        guardar_tenencias_manuales(df)
        st.session_state["resultado_rebalanceo"] = None

    try:
        tenencias_manuales_actuales = cargar_tenencias_manuales()
    except ManualHoldingsError as e:
        tenencias_manuales_actuales = []
        st.error(f"No se pudieron leer las Tenencias Manuales guardadas ({e}).")

    if not tenencias_manuales_actuales:
        st.caption("Todavia no cargaste ninguna tenencia manual.")
    else:
        col_h1, col_h2, col_h3, col_h4 = st.columns([2.5, 2, 2.5, 1])
        col_h1.markdown("**Ticker**")
        col_h2.markdown("**Cantidad**")
        col_h3.markdown("**Categoria**")

        for i, registro in enumerate(tenencias_manuales_actuales):
            ticker_actual = str(registro.get("ticker", ""))
            # OJO: la key de cada widget se arma con el TICKER, no con el
            # indice `i` de la lista. Si se usara el indice, borrar la
            # fila 0 hace que la fila 1 "se convierta" en la fila 0 en el
            # proximo rerun, y heredaria el valor que habia en el widget
            # de la fila 0 vieja (session_state de Streamlit persiste por
            # key, no se reinicia solo). Con el ticker como key eso no
            # pasa: cada widget sigue atado a SU activo aunque se borren
            # o reordenen filas alrededor.
            widget_id = f"{ticker_actual}_{i}"
            col1, col2, col3, col4 = st.columns([2.5, 2, 2.5, 1])
            col1.write(ticker_actual)

            nueva_cantidad = col2.number_input(
                "Cantidad",
                min_value=0.0,
                value=float(registro.get("cantidad", 0) or 0),
                format="%.8g",
                step=1.0,
                key=f"manual_cantidad_{widget_id}",
                label_visibility="collapsed",
            )
            categoria_actual = str(registro.get("categoria", "") or CATEGORIA_FUERA_DE_OBJETIVO)
            opciones_categoria = categorias_para_manuales if categoria_actual in categorias_para_manuales else [categoria_actual] + categorias_para_manuales
            nueva_categoria = col3.selectbox(
                "Categoria",
                options=opciones_categoria,
                index=opciones_categoria.index(categoria_actual),
                key=f"manual_categoria_{widget_id}",
                label_visibility="collapsed",
            )

            if col4.button("", icon=":material/delete:", key=f"manual_borrar_{widget_id}", help=f"Eliminar {ticker_actual} de las tenencias manuales"):
                restantes = [r for j, r in enumerate(tenencias_manuales_actuales) if j != i]
                try:
                    _guardar_lista_manuales(restantes)
                except ManualHoldingsError as e:
                    st.error(f"No se pudo eliminar '{ticker_actual}':\n\n{e}")
                else:
                    # Limpia el estado de los widgets de ESTA fila para
                    # que, si mas adelante se vuelve a agregar el mismo
                    # ticker, no reaparezca el valor viejo que quedo
                    # dando vueltas en session_state.
                    st.session_state.pop(f"manual_cantidad_{widget_id}", None)
                    st.session_state.pop(f"manual_categoria_{widget_id}", None)
                    st.success(f"Se elimino '{ticker_actual}' de las tenencias manuales.")
                    st.rerun()

            # Si el usuario cambio Cantidad/Categoria con los widgets de
            # arriba (sin tocar el tacho), se guarda aparte con este boton
            # -- separado del de eliminar para que un click en el tacho
            # nunca dependa de si hay o no cambios pendientes sin guardar.
            if nueva_cantidad != float(registro.get("cantidad", 0) or 0) or nueva_categoria != categoria_actual:
                if nueva_cantidad <= 0:
                    st.caption(
                        f"Para sacar '{ticker_actual}', usa el boton de eliminar en vez de poner la Cantidad en 0."
                    )
                elif col1.button("Guardar cambio", icon=":material/save:", key=f"manual_guardar_cambio_{widget_id}"):
                    actualizados = list(tenencias_manuales_actuales)
                    actualizados[i] = {
                        "ticker": ticker_actual,
                        "cantidad": nueva_cantidad,
                        "categoria": nueva_categoria,
                    }
                    try:
                        _guardar_lista_manuales(actualizados)
                    except ManualHoldingsError as e:
                        st.error(f"No se pudo guardar el cambio en '{ticker_actual}':\n\n{e}")
                    else:
                        st.success(f"Se actualizo '{ticker_actual}'.")
                        st.rerun()

    st.markdown("**Agregar una tenencia manual nueva**")
    with st.form("form_agregar_tenencia_manual", clear_on_submit=True):
        fc1, fc2, fc3, fc4 = st.columns([2.5, 2, 2.5, 1])
        nuevo_ticker = fc1.text_input("Ticker", placeholder="Ej. GGAL, ETH", label_visibility="collapsed")
        nueva_cantidad_form = fc2.number_input(
            "Cantidad", min_value=0.0, format="%.8g", step=1.0, label_visibility="collapsed"
        )
        nueva_categoria_form = fc3.selectbox(
            "Categoria", options=categorias_para_manuales, label_visibility="collapsed"
        )
        agregar_manual = fc4.form_submit_button("Agregar", icon=":material/add:")

    if agregar_manual:
        ticker_limpio = nuevo_ticker.strip().upper()
        if not ticker_limpio:
            st.error("El Ticker no puede estar vacio.")
        elif nueva_cantidad_form <= 0:
            st.error("La Cantidad tiene que ser mayor a 0.")
        else:
            nuevos_registros = list(tenencias_manuales_actuales) + [
                {"ticker": ticker_limpio, "cantidad": nueva_cantidad_form, "categoria": nueva_categoria_form}
            ]
            try:
                _guardar_lista_manuales(nuevos_registros)
            except ManualHoldingsError as e:
                st.error(f"No se pudo agregar '{ticker_limpio}':\n\n{e}")
            else:
                st.success(f"Se agrego '{ticker_limpio}'.")
                st.rerun()

# ===========================================================================
# PESTANA 3 - Analitica de Riesgo (v4.0)
# ===========================================================================
# ===========================================================================
# v10.0 -- Pestanas nuevas (ver ui/tab_*.py y core/performance.py)
# ===========================================================================
with tab_rend:
    tab_rendimiento.render(CTX)

with tab_aportes_ui:
    tab_aportes.render(CTX)

with tab_metas_ui:
    tab_metas.render(CTX)

with tab_decisiones_ui:
    tab_decisiones.render(CTX)

with tab_riesgo:
    tab_riesgo_real.render(CTX, lambda tickers: _cargar_perfiles(tickers, config))
    st.write("")
    seccion("Tu cartera objetivo", "Segun los % de portfolio_config.json · ultimos 12 meses")
    st.caption(
        "Estadistica de tu **cartera OBJETIVO** (la de portfolio_config.json, no lo que ya "
        "tenes comprado hoy): correlacion, volatilidad anualizada y peor caida historica en "
        "el ultimo año, calculadas con precios diarios de yfinance."
    )

    try:
        analitica = _cargar_analitica(config)
    except AnalyticsError as e:
        st.error(f"No se pudo calcular la analitica de riesgo: {e}")
    else:
        for advertencia in analitica.advertencias:
            st.warning(advertencia)

        if analitica.tickers_sin_datos:
            st.warning(
                f"Sin historico disponible para: **{', '.join(analitica.tickers_sin_datos)}** "
                "(ticker delistado, mal escrito, o que no cotiza en ningun mercado publico). "
                "Quedan afuera de todo lo que sigue en esta pestaña."
            )

        # --- Metricas de riesgo del PORTAFOLIO en su conjunto ---
        c1, c2 = st.columns(2)
        c1.metric(
            "Volatilidad Anualizada del Portafolio",
            f"{analitica.volatilidad_portafolio:.1f}%" if analitica.volatilidad_portafolio is not None else "N/D",
        )
        c2.metric(
            "Max Drawdown del Portafolio (12m)",
            f"{analitica.max_drawdown_portafolio:.1f}%" if analitica.max_drawdown_portafolio is not None else "N/D",
            help=(
                "Caida pico-a-valle real: peor retroceso porcentual del VALOR del portafolio "
                "respecto de su propio maximo historico (ultimos 12 meses). Distinto de "
                "'Peor Brecha vs. Capital Invertido' del Panel principal, que compara contra "
                "la plata que fuiste poniendo (DCA), no contra un maximo historico."
            ),
        )
        st.caption(
            "Ponderado por el % Objetivo de cada activo en portfolio_config.json (no por tu tenencia actual)."
        )

        # --- Matriz de correlacion (heatmap divergente: azul = negativa, "
        # gris = sin relacion, rojo = positiva -- par validado para este "
        # fondo oscuro con la skill de dataviz). ---
        seccion("Matriz de correlacion", "Rendimientos diarios, ultimos 12 meses")

        matriz = analitica.matriz_correlacion
        fig_corr = go.Figure(
            data=go.Heatmap(
                z=matriz.values,
                x=matriz.columns.tolist(),
                y=matriz.index.tolist(),
                zmin=-1,
                zmax=1,
                zmid=0,
                colorscale=[
                    [0.0, COLOR_DIVERGENTE_NEG],
                    [0.5, COLOR_DIVERGENTE_MID],
                    [1.0, COLOR_DIVERGENTE_POS],
                ],
                colorbar=dict(title="Correlación", tickfont=dict(color=COLOR_TEXT), title_font=dict(color=COLOR_TEXT)),
                text=matriz.round(2).values,
                texttemplate="%{text}",
                textfont=dict(size=11, color=COLOR_TEXT),
                hovertemplate="%{y} × %{x}<br>Correlación: %{z:.2f}<extra></extra>",
                xgap=2,
                ygap=2,
            )
        )
        fig_corr.update_layout(
            **plotly_base(TEMA),
            margin=dict(t=20, b=20, l=10, r=10),
            xaxis=dict(showgrid=False, side="top"),
            yaxis=dict(showgrid=False, autorange="reversed"),
            height=max(360, 40 * len(matriz)),
        )
        st.plotly_chart(fig_corr, use_container_width=True)
        st.caption(
            "Los CEDEARs (.BA) cotizan en ARS: su correlación/volatilidad incluye el efecto del "
            "dólar CCL, no es solo el riesgo del activo subyacente en USD."
        )

        # --- Volatilidad y Max Drawdown por activo, ordenado de mayor a "
        # menor riesgo (mismo orden en el que ya vienen las Series). ---
        seccion("Volatilidad y drawdown por activo", "Ordenado de mayor a menor riesgo")

        tabla_riesgo = pd.DataFrame(
            {
                "Volatilidad Anualizada": analitica.volatilidad_anualizada,
                "Max Drawdown (12m)": analitica.max_drawdown.reindex(analitica.volatilidad_anualizada.index),
            }
        )
        tabla_riesgo.index.name = "Ticker"
        tabla_riesgo = tabla_riesgo.reset_index().sort_values("Volatilidad Anualizada", ascending=False)

        st.dataframe(
            tabla_riesgo,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Volatilidad Anualizada": st.column_config.NumberColumn(format="%.1f%%"),
                "Max Drawdown (12m)": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
        st.caption(
            "Ordenado de mayor a menor riesgo por Volatilidad Anualizada. Max Drawdown siempre es "
            "≤ 0%: cuanto más negativo, peor fue la caída pico-a-valle en los últimos 12 meses."
        )
