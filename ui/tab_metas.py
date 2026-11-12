"""
ui/tab_metas.py -- Pestana "Metas y proyeccion" (v10.0)

E1 meta patrimonial con progreso · E2 proyeccion Monte Carlo
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.macro_data import ccl_diario
from core.metas import ESCENARIOS, cargar_metas, guardar_metas
from core.performance import PerformanceError, historial_aportes, metricas_riesgo, proyeccion_montecarlo, resumen_rendimiento
from ui.componentes import UNIDAD_USD, Contexto, barra_progreso_html, fmt_dinero, fmt_pct, layout
from ui.themes import rgba, seccion



def valor_total_usd(ctx: Contexto) -> Optional[float]:
    total = float(ctx.holdings["Valor ARS"].sum(skipna=True))
    return total / ctx.dolar_ccl if ctx.dolar_ccl else None


def render_progreso_panel(ctx: Contexto) -> None:
    """Barra compacta para el panel principal (solo si hay meta)."""
    metas = cargar_metas()
    total = valor_total_usd(ctx)
    if not metas.get("meta_usd") or total is None:
        return
    meta = float(metas["meta_usd"])
    pct = total / meta * 100
    der = f"Meta {fmt_dinero(meta, UNIDAD_USD)}"
    if metas.get("fecha_objetivo"):
        der += f" · {pd.Timestamp(metas['fecha_objetivo']):%m/%Y}"
    st.markdown(
        barra_progreso_html(ctx.tema, pct, f"{pct:.1f}% de tu meta · te faltan {fmt_dinero(max(meta - total, 0), UNIDAD_USD)}", der),
        unsafe_allow_html=True,
    )


def render(ctx: Contexto) -> None:
    t = ctx.tema
    metas = cargar_metas()
    total = valor_total_usd(ctx)
    if total is None:
        st.info("Hace falta el dolar CCL para medir la meta en dolares.")
        return

    # ------------------------------------------------------------------ E1
    with st.container(border=True, key="fp-card-meta"):
        seccion("Tu meta patrimonial", "En dolares de hoy (poder de compra actual)")
        c1, c2, c3 = st.columns([1.2, 1.2, 1])
        meta = c1.number_input("Meta (US$)", min_value=0, step=1000,
                               value=int(metas.get("meta_usd") or 0), key="meta_usd_input",
                               help="Patrimonio que queres alcanzar, en dolares de HOY (el dolar tambien tiene "
                                    "inflacion: US$ 100.000 dentro de 20 anios compran bastante menos que hoy). "
                                    "La proyeccion de abajo usa rendimientos reales, asi que se compara bien con esta "
                                    "meta. 0 = sin meta.")
        fecha_def = pd.Timestamp(metas["fecha_objetivo"]).date() if metas.get("fecha_objetivo") else None
        fecha = c2.date_input("Para cuando (opcional)", value=fecha_def, min_value=date.today(), key="meta_fecha_input",
                              format="DD/MM/YYYY")
        c3.write("")
        c3.write("")
        if c3.button("Guardar meta", icon=":material/flag:", use_container_width=True, key="btn_guardar_meta"):
            metas["meta_usd"] = int(meta) if meta else None
            metas["fecha_objetivo"] = fecha.isoformat() if fecha else None
            guardar_metas(metas)
            st.success("Meta guardada.")
            st.rerun()
        if metas.get("meta_usd"):
            m_usd = float(metas["meta_usd"])
            st.markdown(
                barra_progreso_html(t, total / m_usd * 100, f"Hoy: {fmt_dinero(total, UNIDAD_USD)} ({total / m_usd * 100:.1f}%)",
                                    f"Meta: {fmt_dinero(m_usd, UNIDAD_USD)}"),
                unsafe_allow_html=True,
            )
            st.caption(f"Te faltan {fmt_dinero(max(m_usd - total, 0), UNIDAD_USD)}. Valor total de hoy convertido al CCL de hoy.")
        else:
            st.caption("Defini una meta para ver tu progreso aca y en el panel principal.")

    st.write("")
    # ------------------------------------------------------------------ E2
    with st.container(border=True, key="fp-card-proyeccion"):
        seccion("Proyeccion", "Simulacion de 2.000 escenarios posibles")
        # --- valores por defecto a partir de tus datos reales
        aporte_real = None
        vol_real = None
        vol_hist = None
        twr_real = None
        if ctx.ccl_historico is not None:
            try:
                aporte_real = historial_aportes(ctx.movimientos, ccl=ctx.ccl_historico).promedio_mensual_6m_usd
            except PerformanceError:
                pass
            if ctx.curva is not None:
                try:
                    f = ccl_diario(ctx.ccl_historico, ctx.curva.valor_ars.index)
                    r = resumen_rendimiento(ctx.curva.valor_ars, ctx.curva.capital_invertido_ars, factor=f, unidad="USD")
                    vol_hist = metricas_riesgo(r.indice).volatilidad_anual
                    twr_real = r.twr_anual
                    # v10.1: por defecto la volatilidad de los ULTIMOS 12 MESES (la de tu cartera
                    # actual); la de todo el historial puede arrastrar una cartera que ya no tenes
                    # (ej. la etapa con acciones argentinas de 2025).
                    desde_12m = r.indice.index[-1] - pd.DateOffset(months=12)
                    try:
                        vol_real = metricas_riesgo(r.indice[r.indice.index >= desde_12m]).volatilidad_anual
                    except PerformanceError:
                        vol_real = vol_hist
                except PerformanceError:
                    pass

        c1, c2, c3, c4 = st.columns(4)
        aporte = c1.number_input(
            "Aporte mensual (US$)", min_value=0, step=50,
            value=int(metas.get("aporte_mensual_usd") or round(max(aporte_real or 0, 0) / 10) * 10),
            key="proy_aporte",
            help=(f"Por defecto: tu promedio real de los ultimos 6 meses ({fmt_dinero(aporte_real, UNIDAD_USD)})."
                  if aporte_real is not None else None),
        )
        opciones = list(ESCENARIOS)
        escenario = c2.selectbox(
            "Escenario de rendimiento", opciones,
            index=opciones.index(metas.get("escenario")) if metas.get("escenario") in opciones else 1,
            format_func=lambda e: f"{e} ({ESCENARIOS[e] * 100:.0f}% anual real en USD)", key="proy_escenario",
            help=(
                "Rendimiento anual esperado (mediana) en dolares, REAL: ya descontada la inflacion del dolar "
                "(~2-3% anual). Como referencia, el S&P 500 rindio historicamente ~7% anual real en dolares. "
                "Por eso todos los montos de la proyeccion estan en dolares de HOY."
                + (f" Tu TWR anual en dolares (nominal) hasta hoy: {fmt_pct(twr_real)} (un periodo corto no es buen predictor)."
                   if twr_real is not None else "")
            ),
        )
        vol = c3.number_input(
            "Volatilidad anual (%)", min_value=0.0, max_value=80.0, step=1.0,
            value=float(round((vol_real or 0.18) * 100)), key="proy_vol",
            help=(
                "Por defecto, la volatilidad real de tu cartera en dolares en los ultimos 12 meses "
                "(representa mejor tu cartera actual). Mas volatilidad = abanico mas ancho."
                + (f" Volatilidad de todo tu historial: {fmt_pct(vol_hist, signo=False)}." if vol_hist is not None else "")
            ),
        ) / 100
        anios = c4.slider("Horizonte (años)", 1, 40, int(metas.get("horizonte_anios") or 10), key="proy_anios")

        meta_usd = float(metas["meta_usd"]) if metas.get("meta_usd") else None
        fecha_obj = pd.Timestamp(metas["fecha_objetivo"]) if metas.get("fecha_objetivo") else None
        p = proyeccion_montecarlo(total, float(aporte), ESCENARIOS[escenario], vol, anios,
                                  meta=meta_usd, fecha_objetivo=fecha_obj)

        pc = p.percentiles
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=pc.index, y=pc["p90"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=pc.index, y=pc["p10"], mode="lines", line=dict(width=0), fill="tonexty",
                                 fillcolor=rgba(t.accent, 0.12), name="80% de los escenarios",
                                 hovertemplate="Pesimista (p10): US$ %{y:,.0f}<extra></extra>"))
        fig.add_trace(go.Scatter(x=pc.index, y=pc["p75"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=pc.index, y=pc["p25"], mode="lines", line=dict(width=0), fill="tonexty",
                                 fillcolor=rgba(t.accent, 0.22), name="50% de los escenarios",
                                 hovertemplate="p25: US$ %{y:,.0f}<extra></extra>"))
        fig.add_trace(go.Scatter(x=pc.index, y=pc["p50"], mode="lines", line=dict(color=t.accent, width=2.4),
                                 name="Escenario central", hovertemplate="Central: US$ %{y:,.0f}<extra></extra>"))
        fig.add_trace(go.Scatter(x=p.aportado.index, y=p.aportado.values, mode="lines",
                                 line=dict(color=t.text_muted, width=1.4, dash="dash"), name="Solo lo que aportas",
                                 hovertemplate="Aportado: US$ %{y:,.0f}<extra></extra>"))
        if meta_usd:
            fig.add_hline(y=meta_usd, line=dict(color=t.warning, width=1.4, dash="dot"),
                          annotation_text=f"Meta {fmt_dinero(meta_usd, UNIDAD_USD)}", annotation_position="top left",
                          annotation_font=dict(color=t.warning, size=11))
        fig.update_layout(**layout(t, 380, yaxis=dict(tickprefix="US$ ", tickformat=",.0f", showgrid=True,
                                                      gridcolor=t.chart_grid, color=t.text_muted, zeroline=False)))
        st.plotly_chart(fig, use_container_width=True)

        c1, c2, c3 = st.columns(3)
        c1.metric(f"En {anios} años (escenario central)", fmt_dinero(pc["p50"].iloc[-1], UNIDAD_USD),
                  delta=f"aportando {fmt_dinero(p.aportado.iloc[-1] - total, UNIDAD_USD)}", delta_color="off")
        # "\\$": st.metric interpreta dos "$" en el mismo texto como LaTeX
        c2.metric("Rango probable (80%)",
                  f"US\\$ {pc['p10'].iloc[-1] / 1000:,.0f}k – US\\$ {pc['p90'].iloc[-1] / 1000:,.0f}k")
        if meta_usd:
            if p.mes_meta_mediana is not None:
                c3.metric("Llegas a la meta (escenario central)", f"{p.mes_meta_mediana:%m/%Y}",
                          delta=f"{p.prob_meta * 100:.0f}% de probabilidad en {anios} años", delta_color="off")
            else:
                c3.metric("Probabilidad de llegar a la meta", f"{(p.prob_meta or 0) * 100:.0f}%",
                          delta=f"en {anios} años", delta_color="off")
            if fecha_obj is not None and p.prob_meta_en_fecha is not None:
                st.caption(f"Probabilidad de llegar a la meta para el {fecha_obj:%d/%m/%Y}: {p.prob_meta_en_fecha * 100:.0f}%.")
        else:
            c3.metric("Meta", "Sin definir")

        if st.button("Recordar estos parametros", icon=":material/save:", key="btn_guardar_proy"):
            metas.update({"aporte_mensual_usd": int(aporte), "escenario": escenario, "horizonte_anios": int(anios)})
            guardar_metas(metas)
            st.success("Parametros guardados.")
        st.caption(
            "Es una simulacion, no una prediccion: cada escenario sortea rendimientos mensuales con el rendimiento y la "
            "volatilidad elegidos (en dolares, sin impuestos ni comisiones). Sirve para dimensionar el rango de resultados "
            "posibles y cuanto pesa tu aporte mensual. Todos los montos estan en dolares de HOY: el rendimiento es real "
            "(sin la inflacion del dolar) y el aporte se supone constante en poder de compra, o sea que en la practica "
            "tu aporte en dolares nominales tiene que ir subiendo con la inflacion para que esta proyeccion se cumpla."
        )
