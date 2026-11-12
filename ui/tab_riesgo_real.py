"""
ui/tab_riesgo_real.py -- Riesgo de tu cartera REAL (v10.0)

C1 drawdown en el tiempo · C2 Sharpe, Sortino, beta, volatilidad movil
C3 concentracion (activo, sector, pais, moneda) · C4 contribucion al riesgo
v10.2: stress test historico · exposicion real (look-through de ETFs y bitcoin)
Va arriba de la analitica de la cartera OBJETIVO que ya existia.
"""

from __future__ import annotations

from typing import Callable, Dict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.config_manager import get_target_by_ticker
from core.macro_data import ccl_diario
from core.market_extras import exposicion_cambiaria, traducir_pais, traducir_sector
from core.performance import (
    PerformanceError,
    concentracion,
    contribucion_al_riesgo,
    estadisticas_drawdown,
    exposicion_por,
    metricas_riesgo,
    resumen_rendimiento,
    serie_drawdown,
)
from core.exposicion import exposicion_bitcoin, exposicion_look_through, top_holdings_etfs
from core.stress import correr_escenarios
from ui.componentes import UNIDAD_ARS, UNIDAD_USD, Contexto, aviso_universo, fmt_pct, layout, tabla_stress_html
from ui.themes import rgba, seccion


def render(ctx: Contexto, cargar_perfiles: Callable[[tuple], Dict[str, dict]]) -> None:
    t = ctx.tema
    if ctx.curva is None:
        st.info(f"No se pudo reconstruir la curva historica: {ctx.curva_error}")
        return
    curva = ctx.curva
    usd = ctx.ccl_historico is not None
    unidad = UNIDAD_USD if usd else UNIDAD_ARS
    factor = ccl_diario(ctx.ccl_historico, curva.valor_ars.index) if usd else None
    try:
        r = resumen_rendimiento(curva.valor_ars, curva.capital_invertido_ars, factor=factor, unidad=unidad)
    except PerformanceError as e:
        st.caption(str(e))
        return

    # ------------------------------------------------------------------ C2
    with st.container(border=True, key="fp-card-ratios"):
        seccion("Riesgo y retorno de tu cartera real", f"Medido en {unidad.lower()} · TWR")
        col_rf, _ = st.columns([1, 3])
        rf = col_rf.number_input(
            "Tasa libre de riesgo anual (%)", min_value=0.0, max_value=50.0, step=0.5,
            value=4.0 if usd else 0.0, key="riesgo_rf",
            help="Rendimiento que obtendrias sin riesgo, en la misma moneda. En dolares, una letra del Tesoro de EE.UU. (~4%).",
        ) / 100
        bench = None
        if curva.precios_diarios is not None and "SPY" in curva.precios_diarios.columns:
            bench = curva.precios_diarios["SPY"]
            if factor is not None:
                bench = bench / factor
        try:
            m = metricas_riesgo(r.indice, bench, rf)
        except PerformanceError as e:
            st.caption(str(e))
            m = None
        if m is not None:
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Volatilidad anual", fmt_pct(m.volatilidad_anual, signo=False),
                      help="Cuanto oscila tu cartera en un año tipico (desvio estandar anualizado de los rendimientos diarios).")
            c2.metric("Sharpe", f"{m.sharpe:.2f}" if m.sharpe is not None else "N/D",
                      help="Rendimiento extra sobre la tasa libre de riesgo por cada unidad de volatilidad. >1 es bueno, >2 muy bueno.")
            c3.metric("Sortino", f"{m.sortino:.2f}" if m.sortino is not None else "N/D",
                      help="Como Sharpe, pero solo penaliza la volatilidad de las caidas.")
            c4.metric("Beta vs. S&P 500", f"{m.beta:.2f}" if m.beta is not None else "N/D",
                      help="Cuanto se mueve tu cartera cuando el S&P 500 se mueve 1%. 1 = igual que el mercado.")
            c5.metric("Correlacion S&P", f"{m.correlacion:.2f}" if m.correlacion is not None else "N/D",
                      help="1 = se mueven igual; 0 = sin relacion.")
            if m.retorno_anual is not None:
                st.caption(
                    f"Retorno anualizado del periodo: {fmt_pct(m.retorno_anual)} · {m.ruedas} ruedas analizadas. "
                    "Beta y correlacion contra SPY (el S&P 500) en la misma moneda."
                )
            fig_v = go.Figure()
            fig_v.add_trace(go.Scatter(x=m.vol_movil_1m.index, y=m.vol_movil_1m.values, name="Ultimo mes (21 ruedas)",
                                       mode="lines", line=dict(color=t.text_muted, width=1.2),
                                       hovertemplate="1 mes: %{y:.1f}%<extra></extra>"))
            fig_v.add_trace(go.Scatter(x=m.vol_movil_3m.index, y=m.vol_movil_3m.values, name="Ultimos 3 meses (63 ruedas)",
                                       mode="lines", line=dict(color=t.accent, width=2),
                                       hovertemplate="3 meses: %{y:.1f}%<extra></extra>"))
            fig_v.update_layout(**layout(t, 240, yaxis=dict(ticksuffix="%", showgrid=True, gridcolor=t.chart_grid,
                                                            color=t.text_muted, zeroline=False)))
            st.markdown("**Volatilidad movil (anualizada)**")
            st.plotly_chart(fig_v, use_container_width=True)
        aviso_universo()

    st.write("")
    # ------------------------------------------------------------------ C1
    with st.container(border=True, key="fp-card-drawdown"):
        seccion("Caidas desde el maximo", "Drawdown de tu cartera real")
        dd = serie_drawdown(r.indice)
        est = estadisticas_drawdown(r.indice)
        c1, c2, c3, c4 = st.columns(4)
        with c1.container(key="metric-drawdown-real"):
            st.metric("Peor caida", f"{est.max_drawdown:.1f}%",
                      help=f"Del {est.fecha_pico:%d/%m/%Y} al {est.fecha_valle:%d/%m/%Y}.")
        c2.metric("Duracion de la caida", f"{est.dias_caida} dias")
        c3.metric("Recuperacion",
                  f"{est.dias_recuperacion} dias" if est.dias_recuperacion is not None else "En curso",
                  help=(f"Volvio al maximo el {est.fecha_recuperacion:%d/%m/%Y}." if est.fecha_recuperacion is not None
                        else "Todavia no volvio al maximo previo."))
        c4.metric("Caida actual", f"{est.drawdown_actual:.1f}%",
                  help="0% = hoy estas en maximos.")
        fig = go.Figure(go.Scatter(
            x=dd.index, y=dd.values, mode="lines", fill="tozeroy",
            line=dict(color=t.negative, width=1.4), fillcolor=rgba(t.negative, 0.18),
            hovertemplate="%{x|%d/%m/%Y}: %{y:.1f}%<extra></extra>", name="Drawdown",
        ))
        fig.update_layout(**layout(t, 260, showlegend=False,
                                   yaxis=dict(ticksuffix="%", showgrid=True, gridcolor=t.chart_grid,
                                              color=t.text_muted, zeroline=False)))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Cuanto estaba tu cartera por debajo de su maximo anterior, dia a dia (sobre el TWR, asi que los "
            "aportes no lo \"tapan\"). Es la medida de riesgo que mas se siente: cuanto podes llegar a ver en rojo."
        )

    st.write("")
    # ------------------------------------------------------------------ v10.2 Stress test
    with st.container(border=True, key="fp-card-stress"):
        seccion("Stress test", "Tu cartera de hoy en crisis pasadas, en dolares")
        _render_stress(ctx)

    st.write("")
    # ------------------------------------------------------------------ C3
    valores = ctx.holdings.set_index("Ticker")["Valor ARS"].fillna(0.0)
    valores = valores[valores > 0]
    with st.container(border=True, key="fp-card-concentracion"):
        seccion("Concentracion", "Tenencia actual completa")
        try:
            conc = concentracion(valores)
        except PerformanceError as e:
            st.caption(str(e))
            conc = None
        if conc is not None:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Mayor posicion", f"{conc.top1_pct:.1f}%", delta=conc.top1_ticker, delta_color="off")
            c2.metric("Top 3", f"{conc.top3_pct:.1f}%")
            c3.metric("Top 5", f"{conc.top5_pct:.1f}%")
            c4.metric("Activos efectivos", f"{conc.n_efectivo:.1f}", delta=f"de {len(valores)} posiciones", delta_color="off",
                      help="A cuantos activos de igual peso equivale tu diversificacion real (1 / suma de pesos al cuadrado).")
            perfiles = cargar_perfiles(tuple(sorted(valores.index)))
            mapa_sector = {tk: traducir_sector(p.get("sector")) for tk, p in perfiles.items()}
            mapa_pais = {tk: traducir_pais(p.get("pais")) for tk, p in perfiles.items()}
            mapa_moneda = {tk: exposicion_cambiaria(p) for tk, p in perfiles.items()}
            g1, g2, g3 = st.columns(3)
            for col, titulo, mapa in ((g1, "Por sector", mapa_sector), (g2, "Por pais", mapa_pais),
                                      (g3, "Por moneda", mapa_moneda)):
                with col:
                    st.markdown(f"**{titulo}**")
                    _barras_exposicion(t, exposicion_por(valores, mapa))
            st.caption(
                "Los ETF se agrupan por su categoria (ej. Large Blend = S&P 500) porque no tienen un unico sector. "
                "\"Por moneda\" es la exposicion real: un CEDEAR cotiza en pesos pero sigue al dolar CCL. Sector y pais "
                "salen de Yahoo Finance y se guardan 30 dias en data/cache/."
            )

    st.write("")
    # ------------------------------------------------------------------ C4
    with st.container(border=True, key="fp-card-riesgo-contrib"):
        seccion("De donde viene el riesgo", "Peso vs. contribucion a la volatilidad · ultimo año")
        precios = curva.precios_diarios if curva.precios_diarios is not None else pd.DataFrame()
        columnas = {}
        for tk in valores.index:
            if tk in precios.columns:
                columnas[tk] = precios[tk]
            else:
                alias = str(ctx.config.get("activos", {}).get(tk, {}).get("alias_ticker") or "").upper()
                if alias and alias in precios.columns:
                    columnas[tk] = precios[alias]
        sin_datos = [tk for tk in valores.index if tk not in columnas and tk != "CASH"]
        try:
            rc = contribucion_al_riesgo(pd.DataFrame(columnas), valores.reindex(list(columnas)))
        except PerformanceError as e:
            st.caption(str(e))
            rc = None
        if rc is not None:
            df = rc.iloc[::-1]
            fig = go.Figure()
            fig.add_trace(go.Bar(y=df["Ticker"], x=df["Peso %"], name="Peso en la cartera", orientation="h",
                                 marker_color=rgba(t.text_muted, 0.55),
                                 hovertemplate="%{y} peso: %{x:.1f}%<extra></extra>"))
            fig.add_trace(go.Bar(y=df["Ticker"], x=df["Contribucion al riesgo %"], name="Aporte al riesgo",
                                 orientation="h", marker_color=t.accent,
                                 hovertemplate="%{y} riesgo: %{x:.1f}%<extra></extra>"))
            fig.update_layout(**layout(t, 30 * len(df) + 80, barmode="group", hovermode="closest",
                                       xaxis=dict(ticksuffix="%", showgrid=True, gridcolor=t.chart_grid, color=t.text_muted),
                                       yaxis=dict(showgrid=False, color=t.text)))
            st.plotly_chart(fig, use_container_width=True)
            top = rc.iloc[0]
            mas = rc[rc["Riesgo / peso"] > 1.3]["Ticker"].tolist()
            texto = (
                f"{top['Ticker']} aporta el {top['Contribucion al riesgo %']:.0f}% de la volatilidad con el "
                f"{top['Peso %']:.0f}% del capital. "
            )
            if mas:
                texto += f"Aportan mas riesgo que su peso: {', '.join(mas)}. "
            texto += "Se calcula con los rendimientos diarios en pesos del ultimo año y tus pesos de hoy (suma 100%)."
            if sin_datos:
                texto += f" Sin precio historico (fuera del calculo): {', '.join(sin_datos)}."
            excluidos = rc.attrs.get("excluidos_poca_historia") or []
            if excluidos:
                texto += (
                    f" Con menos de un mes de historia (fuera del calculo, los pesos se reparten entre el resto): "
                    f"{', '.join(excluidos)}."
                )
            st.caption(texto)

    st.write("")
    # ------------------------------------------------------------------ v10.2 Exposicion real
    with st.container(border=True, key="fp-card-exposicion"):
        seccion("Exposicion real", "Lo que tenes directo + lo que tenes adentro de tus ETFs")
        _render_exposicion(ctx, cargar_perfiles, valores)


def _barras_exposicion(t, serie: pd.Series, top: int = 7) -> None:
    s = serie.copy()
    if len(s) > top:
        s = pd.concat([s.iloc[:top], pd.Series({f"Otros ({len(s) - top})": s.iloc[top:].sum()})])
    s = s.iloc[::-1]
    fig = go.Figure(go.Bar(
        x=s.values, y=[str(i) for i in s.index], orientation="h", marker_color=t.accent,
        text=[f"{v:.0f}%" for v in s.values], textposition="outside", cliponaxis=False,
        textfont=dict(color=t.text_muted, size=11), hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
    ))
    fig.update_layout(**layout(t, 30 * len(s) + 40, showlegend=False, hovermode="closest",
                               margin=dict(t=6, b=6, l=6, r=40),
                               xaxis=dict(visible=False),
                               yaxis=dict(showgrid=False, color=t.text, automargin=True)))
    st.plotly_chart(fig, use_container_width=True)


def _render_stress(ctx: Contexto) -> None:
    """v10.2: escenarios historicos aplicados a la cartera de hoy y a la objetivo."""
    t = ctx.tema
    pesos_hoy = ctx.holdings.set_index("Ticker")["Valor ARS"].fillna(0.0)
    pesos_hoy = pesos_hoy[pesos_hoy > 0]
    if pesos_hoy.empty:
        st.caption("No hay posiciones valuadas.")
        return
    valor_usd = float(pesos_hoy.sum()) / ctx.dolar_ccl if ctx.dolar_ccl else None
    try:
        res_hoy = correr_escenarios(pesos_hoy, ctx.config)
        res_obj = correr_escenarios(pd.Series(get_target_by_ticker(ctx.config)), ctx.config)
    except Exception as e:  # red caida en la primera descarga, etc.
        st.caption(f"No se pudo correr el stress test: {e}")
        return
    if not res_hoy:
        st.caption("No hay historia descargada para los escenarios (revisa tu conexion; se guarda en data/cache/stress/).")
        return
    st.markdown(tabla_stress_html(t, {"Cartera de hoy": res_hoy, "Cartera objetivo": res_obj}, valor_usd),
                unsafe_allow_html=True)
    elegido = st.selectbox("Detalle por activo", [r.escenario for r in res_hoy], key="stress_escenario")
    det = next(r for r in res_hoy if r.escenario == elegido).detalle
    det = det[det["Aporte pp"].abs() > 0.05].iloc[::-1]
    fig = go.Figure(go.Bar(
        y=det["Ticker"], x=det["Aporte pp"], orientation="h",
        marker_color=[t.negative if v < 0 else t.positive for v in det["Aporte pp"]],
        customdata=det[["Retorno %", "Peso %", "Fuente"]].values,
        hovertemplate="%{y}: %{x:+.1f} pp (cayo %{customdata[0]:+.0f}%, pesa %{customdata[1]:.1f}%, "
                      "%{customdata[2]})<extra></extra>",
    ))
    fig.update_layout(**layout(t, 26 * len(det) + 70, showlegend=False, hovermode="closest",
                               xaxis=dict(ticksuffix=" pp", showgrid=True, gridcolor=t.chart_grid, color=t.text_muted),
                               yaxis=dict(showgrid=False, color=t.text)))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Aplica el movimiento real en dolares que tuvo cada activo (su subyacente en EE.UU., con dividendos) a tus "
        "pesos de hoy, sin aportes ni cambios en el medio. Los activos que no cotizaban en ese escenario usan el "
        "movimiento de QQQ como supuesto (* = mas del 10% de la cartera con supuesto). IBIT usa la historia de "
        "bitcoin. En pesos la caida se veria distinta, porque en las crisis el CCL suele saltar."
    )


def _render_exposicion(ctx: Contexto, cargar_perfiles: Callable[[tuple], Dict[str, dict]], valores: pd.Series) -> None:
    """v10.2: look-through de ETFs + exposicion agregada a bitcoin."""
    t = ctx.tema
    if valores.empty:
        st.caption("No hay posiciones valuadas.")
        return
    pesos = valores / valores.sum() * 100
    perfiles = cargar_perfiles(tuple(sorted(valores.index)))
    etfs = {tk for tk, p in perfiles.items() if str(p.get("tipo", "")).lower() == "etf"} | {"SPY", "QQQ"}
    etfs &= set(pesos.index)
    holdings_etf = top_holdings_etfs(etfs)
    lt = exposicion_look_through(pesos, holdings_etf)
    lt = lt[lt["Total %"] >= 0.5].head(15)
    superpuestas = lt[(lt["Directo %"] > 0) & (lt["Via ETFs %"] > 0)]
    c1, c2 = st.columns([1.4, 1])
    with c1:
        st.markdown("**Exposicion total por empresa**")
        st.dataframe(
            lt[["Empresa", "Directo %", "Via ETFs %", "Total %"]], hide_index=True, use_container_width=True,
            column_config={c: st.column_config.NumberColumn(format="%.1f%%") for c in ("Directo %", "Via ETFs %", "Total %")},
        )
        if not superpuestas.empty:
            st.caption(
                f"Superpuestas (las tenes sueltas Y adentro de tus ETFs): {', '.join(superpuestas['Empresa'])}. "
                "Comprarlas sueltas es una apuesta extra a esas empresas, no diversificacion."
            )
    with c2:
        st.markdown("**Exposicion a bitcoin**")
        riesgo = None
        try:
            precios = ctx.curva.precios_diarios
            cols = [tk for tk in valores.index if tk in precios.columns]
            rc = contribucion_al_riesgo(precios[cols], valores.reindex(cols))
            riesgo = rc.set_index("Ticker")["Contribucion al riesgo %"]
        except Exception:
            riesgo = None
        btc = exposicion_bitcoin(pesos, riesgo)
        if btc.empty:
            st.caption("No tenes activos ligados a bitcoin.")
        else:
            m1, m2 = st.columns(2)
            m1.metric("Del capital", f"{btc['Peso %'].sum():.1f}%")
            if btc["Riesgo %"].notna().any():
                m2.metric("Del riesgo", f"{btc['Riesgo %'].sum():.1f}%",
                          help="Cuanto de la volatilidad de tu cartera viene de estos activos (ultimo ano).")
            for _, f in btc.iterrows():
                st.caption(f"{f['Ticker']} ({f['Peso %']:.1f}%): {f['Que es']}.")
    st.caption(
        "Fuente: mayores posiciones de cada ETF segun Yahoo Finance (se guardan 30 dias en data/cache/). Solo se "
        "publican las ~10 mayores, asi que la exposicion via ETFs a empresas mas chicas queda subestimada."
    )
