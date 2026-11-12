"""
ui/tab_aportes.py -- Pestana "Aportes y dividendos" (v10.0)

D1 historial de aportes · D3 dividendos · D4 tus compras sobre el grafico
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.macro_data import ccl_diario
from core.performance import (
    TIPO_DIV_ARS,
    TIPO_DIV_USD,
    TIPO_RENTA,
    PerformanceError,
    analisis_timing,
    historial_aportes,
    historial_dividendos,
    operaciones_de_ticker,
    valores_en_fechas,
)
from ui.componentes import UNIDAD_ARS, UNIDAD_USD, Contexto, fmt_dinero, fmt_pct, layout
from ui.themes import rgba, seccion


def render(ctx: Contexto) -> None:
    _render_aportes(ctx)
    st.write("")
    _render_dividendos(ctx)
    st.write("")
    _render_compras(ctx)


# ---------------------------------------------------------------------------
# D1
# ---------------------------------------------------------------------------
def _render_aportes(ctx: Contexto) -> None:
    t = ctx.tema
    with st.container(border=True, key="fp-card-aportes"):
        seccion("Tus aportes", "Depositos y retiros de la cuenta")
        try:
            h = historial_aportes(ctx.movimientos, ccl=ctx.ccl_historico)
        except PerformanceError as e:
            st.caption(str(e))
            return
        usd = ctx.ccl_historico is not None
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Aportado neto",
            fmt_dinero(h.neto),
            delta=(f"≈ {fmt_dinero(h.neto_usd, UNIDAD_USD)}" if usd else None),
            delta_color="off",
            help=f"Depositado {fmt_dinero(h.total_depositado)} menos retirado {fmt_dinero(h.total_retirado)}.",
        )
        c2.metric(
            "Promedio 6 meses",
            fmt_dinero(h.promedio_mensual_6m),
            delta=(f"≈ {fmt_dinero(h.promedio_mensual_6m_usd, UNIDAD_USD)}" if usd else None),
            delta_color="off",
            help="Aporte neto promedio de los ultimos 6 meses completos (sin contar el mes en curso).",
        )
        c3.metric(
            "Racha de aportes",
            f"{h.racha_actual} {'mes' if h.racha_actual == 1 else 'meses'}",
            help="Meses seguidos con al menos un deposito. El mes en curso no corta la racha si todavia no aportaste.",
        )
        c4.metric("Meses con aporte", f"{h.meses_con_aporte} de {h.meses_totales}")

        ver_usd = usd and (st.segmented_control(
            "Ver en", [UNIDAD_ARS, UNIDAD_USD], default=UNIDAD_ARS, key="aportes_unidad"
        ) == UNIDAD_USD)
        m = h.mensual.copy()
        # etiquetas de mes explicitas (con fechas de fin de mes Plotly
        # dibujaria cada barra bajo el mes SIGUIENTE)
        m.index = [d.strftime("%b %y") for d in m.index]
        fig = go.Figure()
        if ver_usd:
            fig.add_trace(go.Bar(x=m.index, y=m["Neto USD"], name="Aporte neto",
                                 marker_color=[t.accent if v >= 0 else t.negative for v in m["Neto USD"]],
                                 hovertemplate="%{x}: US$ %{y:,.0f}<extra></extra>"))
            fig.add_trace(go.Scatter(x=m.index, y=m["Acumulado USD"], name="Acumulado", mode="lines+markers",
                                     line=dict(color=t.text_muted, width=1.6), yaxis="y2",
                                     hovertemplate="Acumulado: US$ %{y:,.0f}<extra></extra>"))
        else:
            fig.add_trace(go.Bar(x=m.index, y=m["Depositos"], name="Depositos", marker_color=t.accent,
                                 hovertemplate="%{x} depositos: $%{y:,.0f}<extra></extra>"))
            fig.add_trace(go.Bar(x=m.index, y=-m["Retiros"], name="Retiros", marker_color=rgba(t.negative, 0.75),
                                 hovertemplate="Retiros: $%{y:,.0f}<extra></extra>"))
            fig.add_trace(go.Scatter(x=m.index, y=m["Acumulado"], name="Aportado neto acumulado", mode="lines+markers",
                                     line=dict(color=t.text_muted, width=1.6), yaxis="y2",
                                     hovertemplate="Acumulado: $%{y:,.0f}<extra></extra>"))
        fig.update_layout(**layout(
            t, 330, barmode="relative",
            yaxis2=dict(overlaying="y", side="right", showgrid=False, color=t.text_muted, zeroline=False),
            xaxis=dict(showgrid=False, color=t.text_muted, type="category"),
        ))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Es la plata que entro y salio de tu cuenta de Cocos Capital (despues se reparte entre acciones, FCI, "
            "caucion, etc.). En dolares, cada deposito se convierte al CCL de su dia."
        )


# ---------------------------------------------------------------------------
# D3
# ---------------------------------------------------------------------------
def _render_dividendos(ctx: Contexto) -> None:
    t = ctx.tema
    with st.container(border=True, key="fp-card-dividendos"):
        seccion("Dividendos y rentas", "Lo que te pago tu cartera")
        if ctx.ccl_historico is None:
            st.caption("Hace falta el dolar CCL historico para valuar los dividendos en dolares.")
            return
        try:
            d = historial_dividendos(ctx.movimientos, ctx.ccl_historico)
        except PerformanceError as e:
            st.caption(str(e))
            return
        capital = float(ctx.curva.capital_invertido_ars.iloc[-1]) if ctx.curva is not None else None
        c1, c2, c3 = st.columns(3)
        c1.metric("Cobrado (ultimos 12 meses)", fmt_dinero(d.ultimos_12m_ars),
                  delta=f"≈ {fmt_dinero(d.ultimos_12m_usd, UNIDAD_USD, 2)}", delta_color="off")
        c2.metric("Cobrado desde el inicio", fmt_dinero(d.total_ars),
                  delta=f"≈ {fmt_dinero(d.total_usd, UNIDAD_USD, 2)}", delta_color="off")
        c3.metric(
            "Rendimiento por dividendos",
            fmt_pct(d.ultimos_12m_ars / capital if capital else None, 2, signo=False),
            help="Dividendos de los ultimos 12 meses sobre el capital invertido hoy en acciones/CEDEARs.",
        )
        colores = {TIPO_DIV_USD: t.accent, TIPO_DIV_ARS: t.positive, TIPO_RENTA: t.warning}
        fig = go.Figure()
        meses_txt = [x.strftime("%b %y") for x in d.mensual_ars.index]
        for tipo in d.mensual_ars.columns:
            fig.add_trace(go.Bar(x=meses_txt, y=d.mensual_ars[tipo], name=tipo,
                                 marker_color=colores.get(tipo, t.text_muted),
                                 hovertemplate=f"{tipo}: $%{{y:,.0f}}<extra></extra>"))
        fig.update_layout(**layout(t, 280, barmode="stack",
                                   xaxis=dict(showgrid=False, color=t.text_muted, type="category")))
        st.plotly_chart(fig, use_container_width=True)
        nota = (
            "Los dividendos de CEDEARs llegan en dolares (se valuan al CCL del dia, netos de retenciones). "
            "El CSV de Cocos no indica de que activo viene cada dividendo."
        )
        if not d.en_especie.empty:
            nota += " Tambien recibiste en especie: " + ", ".join(
                f"{int(r['Nominales recibidos']) if float(r['Nominales recibidos']).is_integer() else r['Nominales recibidos']} {r['Ticker']}"
                for _, r in d.en_especie.iterrows()
            ) + " (sin valuar: no tienen precio historico)."
        if TIPO_RENTA in d.mensual_ars.columns:
            nota += " Cupones y amortizaciones de bonos se muestran aparte: una amortizacion devuelve capital, no es ganancia."
        st.caption(nota)


# ---------------------------------------------------------------------------
# D4
# ---------------------------------------------------------------------------
def _render_compras(ctx: Contexto) -> None:
    t = ctx.tema
    with st.container(border=True, key="fp-card-compras"):
        seccion("Tus compras sobre el grafico", "¿Compraste barato o caro?")
        curva = ctx.curva
        if curva is None or curva.precios_diarios is None:
            st.caption("Hace falta la curva historica para este grafico.")
            return
        precios = curva.precios_diarios
        ops_todas = ctx.movimientos[ctx.movimientos["tipo_operacion_norm"].isin(["COMPRA", "VENTA"])]
        # tickers con operaciones y precio, ordenados por monto operado (los mas relevantes primero)
        monto = ops_todas.groupby("ticker")["total"].apply(lambda s: s.abs().sum())
        tickers = [tk for tk in monto.sort_values(ascending=False).index if tk in precios.columns]
        if not tickers:
            st.caption("No hay activos con operaciones y precio historico.")
            return
        col1, col2 = st.columns([2, 1])
        ticker = col1.selectbox("Activo", tickers, key="compras_ticker")
        usd_disp = ctx.ccl_historico is not None
        unidad = col2.segmented_control("Precio en", [UNIDAD_ARS, UNIDAD_USD] if usd_disp else [UNIDAD_ARS],
                                        default=UNIDAD_ARS, key="compras_unidad") or UNIDAD_ARS
        ops = operaciones_de_ticker(ctx.movimientos, ticker)
        serie = precios[ticker].dropna()
        desde = ops["Fecha"].min() - pd.Timedelta(days=20)
        serie = serie[desde:]
        factor = ccl_diario(ctx.ccl_historico, serie.index) if unidad == UNIDAD_USD else None
        if factor is not None:
            serie = serie / factor
            ops = ops.copy()
            ops["Precio"] = ops["Precio"].values / valores_en_fechas(ctx.ccl_historico, ops["Fecha"])

        try:
            timing = analisis_timing(precios[ticker], operaciones_de_ticker(ctx.movimientos, ticker),
                                     factor=ctx.ccl_historico if unidad == UNIDAD_USD else None)
        except PerformanceError:
            timing = None

        dec = 2 if unidad == UNIDAD_USD else 0
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=serie.index, y=serie.values, name="Precio", mode="lines",
                                 line=dict(color=t.text_muted, width=1.6),
                                 hovertemplate="%{x|%d/%m/%Y}: %{y:,.2f}<extra></extra>"))
        compras = ops[ops["Tipo"] == "Compra"]
        ventas = ops[ops["Tipo"] == "Venta"]
        tam = lambda q: (8 + 14 * (q / ops["Cantidad"].max()) ** 0.5).tolist()
        if not compras.empty:
            fig.add_trace(go.Scatter(x=compras["Fecha"], y=compras["Precio"], name="Compras", mode="markers",
                                     marker=dict(symbol="triangle-up", color=t.positive, size=tam(compras["Cantidad"]),
                                                 line=dict(color=t.surface, width=1)),
                                     customdata=compras["Cantidad"],
                                     hovertemplate="Compra %{customdata:g} a %{y:,.2f}<extra></extra>"))
        if not ventas.empty:
            fig.add_trace(go.Scatter(x=ventas["Fecha"], y=ventas["Precio"], name="Ventas", mode="markers",
                                     marker=dict(symbol="triangle-down", color=t.negative, size=tam(ventas["Cantidad"]),
                                                 line=dict(color=t.surface, width=1)),
                                     customdata=ventas["Cantidad"],
                                     hovertemplate="Venta %{customdata:g} a %{y:,.2f}<extra></extra>"))
        if timing is not None:
            fig.add_hline(y=timing.precio_promedio_compra, line=dict(color=t.accent, width=1.4, dash="dash"),
                          annotation_text="Tu precio promedio de compra", annotation_position="top left",
                          annotation_font=dict(color=t.accent, size=11))
        fig.update_layout(**layout(t, 360, hovermode="closest"))
        st.plotly_chart(fig, use_container_width=True)

        if timing is not None:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Tu precio promedio", fmt_dinero(timing.precio_promedio_compra, unidad, dec),
                      help="Promedio ponderado por nominales de todas tus compras.")
            c2.metric("DCA de referencia", fmt_dinero(timing.precio_referencia_dca, unidad, dec),
                      help=("Precio promedio que habrias pagado invirtiendo un monto fijo todas las ruedas entre tu "
                            "primera y tu ultima compra. Es la vara justa: cualquier DCA de montos fijos queda por "
                            "debajo del promedio simple del precio solo por matematica (compra mas nominales cuando "
                            f"esta barato). Promedio simple del periodo: {fmt_dinero(timing.precio_promedio_periodo, unidad, dec)}."))
            c3.metric(
                "Timing vs. DCA",
                f"{abs(timing.ventaja_pct):.1f}% {'abajo' if timing.ventaja_pct < 0 else 'arriba'}",
                delta=f"{-timing.ventaja_pct:+.1f}% a tu favor" if timing.ventaja_pct < 0 else f"{-timing.ventaja_pct:+.1f}% en contra",
                help="Tu precio promedio de compra contra el DCA mecanico de referencia. Abajo = tus decisiones de "
                     "cuando y cuanto comprar le ganaron a invertir lo mismo todos los dias.",
            )
            c4.metric("Bajo el precio actual", f"{timing.pct_compras_bajo_precio_actual:.0f}%",
                      help=f"{timing.n_compras} compras, {timing.n_ventas} ventas.")
        st.caption(
            "El tamaño de cada triangulo es proporcional a la cantidad operada. En dolares se saca el efecto del CCL: "
            "para un CEDEAR muestra si elegiste bien el momento del activo en si."
        )
