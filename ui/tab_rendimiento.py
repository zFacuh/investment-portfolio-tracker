"""
ui/tab_rendimiento.py -- Pestana "Rendimiento" (v10.0)

A1 TWR y TIR · A2 en pesos, dolares y pesos reales · A4 heatmap mensual
B1 contribucion por activo · B2 Core vs. Satelite
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.macro_data import ccl_diario, indice_ipc_diario
from core.metas import cargar_metas, guardar_metas
from core.performance import (
    CATEGORIA_OTROS,
    PerformanceError,
    ResumenRendimiento,
    comparacion_vs_benchmark,
    contribucion_por_activo,
    factor_real,
    rendimiento_por_categoria,
    rendimientos_mensuales,
    resumen_rendimiento,
    tir_cuenta,
)
from ui.componentes import (
    UNIDAD_ARS,
    UNIDAD_REAL,
    UNIDAD_USD,
    UNIDADES,
    Contexto,
    aviso_universo,
    color_signo,
    fmt_dinero,
    fmt_pct,
    layout,
    nota_unidad,
    tabla_html,
)
from ui.themes import rgba, seccion


def factores_por_unidad(ctx: Contexto, indice: pd.DatetimeIndex) -> Dict[str, Optional[pd.Series]]:
    """Factor diario por el cual se divide cada peso para llevarlo a la
    unidad pedida (None = pesos corrientes)."""
    factores: Dict[str, Optional[pd.Series]] = {UNIDAD_ARS: None}
    if ctx.ccl_historico is not None:
        factores[UNIDAD_USD] = ccl_diario(ctx.ccl_historico, indice)
    if ctx.inflacion_mensual is not None:
        ipc, _ = indice_ipc_diario(ctx.inflacion_mensual, indice)
        factores[UNIDAD_REAL] = factor_real(ipc)
    return factores


def resumenes(ctx: Contexto) -> Dict[str, ResumenRendimiento]:
    curva = ctx.curva
    fac = factores_por_unidad(ctx, curva.valor_ars.index)
    out: Dict[str, ResumenRendimiento] = {}
    for unidad, f in fac.items():
        try:
            out[unidad] = resumen_rendimiento(curva.valor_ars, curva.capital_invertido_ars, factor=f, unidad=unidad)
        except PerformanceError:
            continue
    return out


def indices_benchmark(curva, factor: Optional[pd.Series]) -> Dict[str, pd.Series]:
    """Indice TWR de cada benchmark simulado con tus mismos flujos (ver
    core/historical_curve.py: incluye dividendos), en la unidad de `factor`."""
    out: Dict[str, pd.Series] = {}
    for label, serie in (curva.valores_benchmark or {}).items():
        try:
            out[label] = resumen_rendimiento(serie, curva.capital_invertido_ars, factor=factor).indice
        except PerformanceError:
            continue
    return out


def render(ctx: Contexto) -> None:
    t = ctx.tema
    if ctx.curva is None:
        st.info(f"No se pudo reconstruir la curva historica, que es la base de esta pestaña: {ctx.curva_error}")
        return
    curva = ctx.curva
    for aviso in ctx.avisos_macro:
        st.caption(f":material/info: {aviso}")

    res = resumenes(ctx)
    disponibles = [u for u in UNIDADES if u in res]
    unidad = st.segmented_control(
        "Medir en",
        options=disponibles,
        default=disponibles[0],
        key="rend_unidad",
        help="En Argentina un rendimiento en pesos puede ser una perdida real. Mira el mismo resultado en dolares y ajustado por inflacion.",
    ) or disponibles[0]
    r = res[unidad]
    fac = factores_por_unidad(ctx, curva.valor_ars.index)

    # --- KPIs --------------------------------------------------------------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Ganancia acumulada",
        fmt_dinero(r.ganancia, unidad),
        delta=fmt_pct(r.ganancia / r.aportado_neto if r.aportado_neto else None),
        help="Valor de hoy menos todo lo que pusiste (neto de ventas), en la unidad elegida.",
    )
    c2.metric(
        "Rendimiento (TWR)",
        fmt_pct(r.twr_total),
        help=(
            "Rendimiento ponderado por tiempo: mide tus decisiones de inversion sin el efecto de cuando o "
            "cuanto aportaste. Es el que se compara contra un indice."
        ),
    )
    c3.metric(
        "TWR anualizado",
        fmt_pct(r.twr_anual),
        help="Llevado a tasa anual: es el CAGR de tu estrategia (como si hubieras invertido una sola vez al inicio)."
        + (" Periodo menor a un año: es una extrapolacion." if r.anual_es_extrapolacion else ""),
    )
    c4.metric(
        "TIR anual (acciones)",
        fmt_pct(r.tir_anual),
        help=(
            "Tasa interna de retorno (XIRR) de la plata que pusiste en tu cartera de acciones y CEDEARs: lo que "
            "rindio ese dinero, incluido el efecto del momento en que compraste. No incluye la plata en FCI, "
            "caucion, cash ni bonos, asi que no es el rendimiento de TODA tu cuenta."
        ),
    )
    st.caption(f"Desde el {r.fecha_inicio:%d/%m/%Y} ({r.dias} dias). {nota_unidad(unidad)}")

    # --- Comparacion de las tres unidades ---------------------------------
    filas = []
    for u in UNIDADES:
        if u not in res:
            continue
        x = res[u]
        filas.append(
            [
                (u, None),
                (fmt_dinero(x.ganancia, u), color_signo(t, x.ganancia)),
                (fmt_pct(x.twr_total), color_signo(t, x.twr_total)),
                (fmt_pct(x.twr_anual), color_signo(t, x.twr_anual or 0)),
                (fmt_pct(x.tir_anual), color_signo(t, x.tir_anual or 0)),
            ]
        )
    st.markdown(
        tabla_html(t, ["El mismo resultado medido en", "Ganancia", "TWR", "TWR anual", "TIR anual"], filas),
        unsafe_allow_html=True,
    )
    st.write("")

    # --- Rendimiento acumulado vs referencias ------------------------------
    with st.container(border=True, key="fp-card-rend-acum"):
        seccion("Rendimiento acumulado vs. referencias", "Base 100 al inicio · TWR")
        fig = go.Figure()
        base = 100 * r.indice
        fig.add_trace(
            go.Scatter(x=base.index, y=base.values, name="Tu cartera", mode="lines",
                       line=dict(color=t.linea_valor, width=2.4),
                       hovertemplate="Tu cartera: %{y:.1f}<extra></extra>")
        )
        f = fac.get(unidad)
        paleta = list(t.benchmarks)
        i = 0
        # v10.2: TWR del benchmark simulado con tus mismos flujos (incluye dividendos), en vez del precio crudo
        indices_bench = indices_benchmark(curva, f)
        for label, p in indices_bench.items():
            fig.add_trace(
                go.Scatter(x=p.index, y=100 * p, name=label, mode="lines",
                           line=dict(color=paleta[i % len(paleta)], width=1.4, dash="dot"),
                           hovertemplate=f"{label}: %{{y:.1f}}<extra></extra>")
            )
            i += 1
        if unidad == UNIDAD_ARS:
            if UNIDAD_REAL in fac:
                ipc = 1 / fac[UNIDAD_REAL]
                fig.add_trace(go.Scatter(x=ipc.index, y=100 * ipc / ipc.iloc[0], name="Inflacion (IPC)", mode="lines",
                                         line=dict(color=t.warning, width=1.6, dash="dash"),
                                         hovertemplate="Inflacion: %{y:.1f}<extra></extra>"))
            if UNIDAD_USD in fac:
                ccl = fac[UNIDAD_USD]
                fig.add_trace(go.Scatter(x=ccl.index, y=100 * ccl / ccl.iloc[0], name="Dolar CCL", mode="lines",
                                         line=dict(color=t.text_muted, width=1.6, dash="dash"),
                                         hovertemplate="Dolar CCL: %{y:.1f}<extra></extra>"))
        fig.add_hline(y=100, line=dict(color=t.border_strong, width=1))
        fig.update_layout(**layout(t, 360))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Cada benchmark simula tus mismos aportes, en las mismas fechas, puestos en ese indice (con dividendos), "
            "medido con TWR igual que tu cartera: son comparables. En pesos se suman la inflacion y el dolar CCL como referencia: "
            "si tu linea queda arriba, le ganaste."
        )
        aviso_universo()

    # --- v10.2: ¿Le ganas al indice? ----------------------------------------
    with st.container(border=True, key="fp-card-vs-indice"):
        seccion("¿Le ganas al indice?", f"Tu cartera vs. tus mismos aportes puestos en cada indice, en {unidad.lower()}")
        _render_vs_indice(ctx, r, indices_bench)

    # --- v10.2: TIR de toda la cuenta --------------------------------------
    with st.container(border=True, key="fp-card-tir-cuenta"):
        seccion("Toda tu cuenta", "Lo que rindio la plata que mandaste a Cocos, incluida la que estuvo quieta")
        _render_tir_cuenta(ctx, res)

    # --- Heatmap mensual -----------------------------------------------------
    with st.container(border=True, key="fp-card-heatmap"):
        seccion("Rendimiento mes a mes", f"TWR mensual en {unidad.lower()}")
        tabla = rendimientos_mensuales(r.indice)
        if tabla.empty:
            st.caption("Todavia no hay meses completos.")
        else:
            z = tabla.values.astype(float)
            texto = [[("" if np.isnan(v) else f"{v:+.1f}%") for v in fila] for fila in z]
            lim = float(np.nanmax(np.abs(z))) if np.isfinite(np.nanmax(np.abs(z))) else 1.0
            heat = go.Figure(
                go.Heatmap(
                    z=z,
                    x=[c if c != "Anio" else "Año" for c in tabla.columns],
                    y=[str(a) for a in tabla.index],
                    zmin=-lim, zmax=lim, zmid=0,
                    colorscale=[[0, t.negative], [0.5, t.surface_2], [1, t.positive]],
                    text=texto, texttemplate="%{text}", textfont=dict(size=12, color=t.text),
                    hovertemplate="%{y} %{x}: %{z:+.2f}%<extra></extra>",
                    showscale=False, xgap=3, ygap=3,
                )
            )
            heat.update_layout(**layout(t, 90 + 46 * len(tabla), hovermode="closest",
                                        xaxis=dict(side="top", showgrid=False, color=t.text_muted),
                                        yaxis=dict(autorange="reversed", showgrid=False, color=t.text_muted, type="category")))
            st.plotly_chart(heat, use_container_width=True)
            positivos = int((tabla.drop(columns="Anio") > 0).sum().sum())
            totales = int(tabla.drop(columns="Anio").notna().sum().sum())
            mejor = tabla.drop(columns="Anio").stack().idxmax()
            peor = tabla.drop(columns="Anio").stack().idxmin()
            st.caption(
                f"{positivos} de {totales} meses positivos · mejor mes: {mejor[1]} {mejor[0]} "
                f"({tabla.loc[mejor]:+.1f}%) · peor mes: {peor[1]} {peor[0]} ({tabla.loc[peor]:+.1f}%). "
                "El primer mes es parcial (desde tu primera operacion)."
            )

    # --- Contribucion por activo ---------------------------------------------
    with st.container(border=True, key="fp-card-contribucion"):
        seccion("Que activos explican el resultado", "Contribucion en la unidad elegida")
        hoy = curva.valor_ars.index[-1]
        periodos = {
            "Desde el inicio": None,
            "Este año": pd.Timestamp(year=hoy.year, month=1, day=1),
            "Ultimos 12 meses": hoy - pd.DateOffset(months=12),
            "Ultimos 3 meses": hoy - pd.DateOffset(months=3),
        }
        periodo = st.segmented_control("Periodo", list(periodos), default="Desde el inicio", key="rend_contrib_periodo") or "Desde el inicio"
        try:
            contrib = contribucion_por_activo(
                curva.inventario, curva.precios_diarios, curva.capital_por_ticker, curva.cash_dividendos,
                desde=periodos[periodo], factor=f,
            )
        except Exception as e:  # datos incompletos: no tumbar la pestana
            st.caption(f"No se pudo calcular la contribucion: {e}")
            contrib = None
        if contrib is not None and not contrib.empty:
            _grafico_contribucion(t, contrib, unidad)
            total = contrib["Contribucion"].sum()
            ganadores = contrib[contrib["Contribucion"] > 0]
            st.caption(
                f"Resultado del periodo: {fmt_dinero(total, unidad, signo=True)}. "
                f"{len(ganadores)} de {len(contrib)} posiciones sumaron. Incluye activos que ya vendiste "
                "(su resultado quedo realizado). Los dividendos en efectivo van en una fila aparte porque el CSV de "
                "Cocos no dice de que activo vienen."
            )
            with st.expander("Ver tabla completa"):
                tabla_c = contrib.copy()
                st.dataframe(
                    tabla_c,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Valor inicial": st.column_config.NumberColumn(format="%.0f"),
                        "Flujo neto": st.column_config.NumberColumn(format="%.0f", help="Compras menos ventas en el periodo (con comisiones)."),
                        "Valor final": st.column_config.NumberColumn(format="%.0f"),
                        "Contribucion": st.column_config.NumberColumn(format="%.0f"),
                        "% del resultado": st.column_config.NumberColumn(format="%.1f%%"),
                    },
                )

    # --- Core vs Satelite ------------------------------------------------------
    with st.container(border=True, key="fp-card-categorias"):
        seccion("Core vs. Satelite", "Cada bloque como si fuera una cartera propia")
        mapa = {tk: d.get("categoria") for tk, d in ctx.config.get("activos", {}).items() if d.get("categoria")}
        # un alias (ej. BTC -> IBIT) se opera con otro ticker: hereda la categoria
        for tk, d in ctx.config.get("activos", {}).items():
            if d.get("alias_ticker"):
                mapa[str(d["alias_ticker"]).upper()] = d.get("categoria")
        cats = rendimiento_por_categoria(curva.inventario, curva.precios_diarios, curva.capital_por_ticker, mapa, factor=f)
        if not cats:
            st.caption("No hay datos suficientes por categoria.")
        else:
            fig_c = go.Figure()
            colores = {**{c: col for c, col in zip(sorted(cats), t.chart_palette)}}
            orden = sorted(cats, key=lambda c: (c == CATEGORIA_OTROS, c))
            valores_hoy = {}
            for cat in orden:
                x = cats[cat]
                activo = x.valor[x.valor > 1.0]
                if activo.empty:
                    continue
                inicio = activo.index[0]
                idx = x.indice[inicio:]
                serie = 100 * idx / idx.iloc[0] * (1 + x.rendimientos.loc[inicio])
                valores_hoy[cat] = float(x.valor.iloc[-1])
                fig_c.add_trace(go.Scatter(
                    x=serie.index, y=serie.values, name=cat, mode="lines",
                    line=dict(color=colores[cat], width=2.2 if cat != CATEGORIA_OTROS else 1.6,
                              dash=None if cat != CATEGORIA_OTROS else "dot"),
                    hovertemplate=f"{cat}: %{{y:.1f}}<extra></extra>"))
            fig_c.add_hline(y=100, line=dict(color=t.border_strong, width=1))
            fig_c.update_layout(**layout(t, 320))
            st.plotly_chart(fig_c, use_container_width=True)
            total_hoy = sum(valores_hoy.values()) or 1.0
            filas = []
            for cat in orden:
                x = cats[cat]
                activo = x.valor[x.valor > 1.0]
                if activo.empty:
                    continue
                desde = activo.index[0]
                idx = x.indice[desde:]
                twr = float(idx.iloc[-1] / idx.iloc[0] * (1 + x.rendimientos.loc[desde]) - 1)
                dias = (x.fecha_fin - desde).days
                anual = (1 + twr) ** (365.25 / dias) - 1 if dias >= 365 else None
                filas.append([
                    (cat, None),
                    (f"{desde:%d/%m/%Y}", t.text_muted),
                    (fmt_pct(twr), color_signo(t, twr)),
                    (fmt_pct(anual) if anual is not None else "menos de 1 año", color_signo(t, anual or 0) if anual is not None else t.text_muted),
                    (fmt_dinero(x.ganancia, unidad, signo=True), color_signo(t, x.ganancia)),
                    (f"{valores_hoy.get(cat, 0) / total_hoy * 100:.1f}%", None),
                ])
            st.markdown(tabla_html(t, ["Bloque", "Desde", "TWR", "TWR anual", "Ganancia", "Peso hoy"], filas), unsafe_allow_html=True)
            st.caption(
                "Cada linea arranca en 100 el dia que compraste el primer activo de ese bloque. La categoria es la de "
                f"tu configuracion actual, aplicada a todo el historial. \"{CATEGORIA_OTROS}\" son activos que tenes "
                "(o tuviste) pero que no estan en tu cartera objetivo."
            )


def _ticker_de_benchmark(config: dict, label: str) -> str:
    for b in config.get("meta", {}).get("benchmark_tickers", []) or []:
        if isinstance(b, dict) and (b.get("label") == label):
            return str(b.get("ticker", "")).upper()
        if isinstance(b, str) and b.upper() == label.upper():
            return b.upper()
    return label.upper()


def _grafico_contribucion(t, contrib: pd.DataFrame, unidad: str, top: int = 12) -> None:
    df = contrib.copy()
    if len(df) > top:
        pos = df[df["Contribucion"] >= 0].head(top // 2 + 2)
        neg = df[df["Contribucion"] < 0].tail(top // 2 - 2) if (df["Contribucion"] < 0).any() else df.iloc[0:0]
        resto = df.drop(pos.index).drop(neg.index)
        partes = [pos]
        if not resto.empty:
            partes.append(pd.DataFrame([{"Ticker": f"Resto ({len(resto)})", "Contribucion": resto["Contribucion"].sum()}]))
        partes.append(neg)
        df = pd.concat(partes, ignore_index=True)
    df = df.iloc[::-1]
    colores = [t.positive if v >= 0 else t.negative for v in df["Contribucion"]]
    etiquetas = [fmt_dinero(v, unidad, signo=True) for v in df["Contribucion"]]
    fig = go.Figure(go.Bar(
        x=df["Contribucion"], y=df["Ticker"], orientation="h",
        marker=dict(color=colores), text=etiquetas, textposition="outside",
        textfont=dict(color=t.text_muted, size=11), cliponaxis=False,
        hovertemplate="%{y}: %{text}<extra></extra>",
    ))
    fig.update_layout(**layout(t, 34 * len(df) + 60, hovermode="closest", showlegend=False,
                               margin=dict(t=10, b=10, l=10, r=70),
                               xaxis=dict(showgrid=True, gridcolor=t.chart_grid, color=t.text_muted, zeroline=True,
                                          zerolinecolor=t.border_strong, title=None),
                               yaxis=dict(showgrid=False, color=t.text, title=None)))
    st.plotly_chart(fig, use_container_width=True)


def _render_vs_indice(ctx: Contexto, r: ResumenRendimiento, indices_bench: Dict[str, pd.Series]) -> None:
    """v10.2: exceso de rendimiento contra cada benchmark, en ventanas fijas y moviles."""
    t = ctx.tema
    if not indices_bench:
        st.caption("No hay benchmarks configurados con datos.")
        return
    orden = sorted(indices_bench, key=lambda l: (l not in ("QQQ", "SPY"), l != "QQQ", l))
    comps = []
    for label in orden:
        try:
            comps.append(comparacion_vs_benchmark(r.indice, indices_bench[label], label))
        except PerformanceError:
            continue

    def celda(v, es_pct=False):
        if v is None:
            return ("Sin historia", None)
        if es_pct:
            return (f"{v:.0f}%", t.positive if v >= 50 else t.negative)
        return (f"{v * 100:+.1f} pp", color_signo(t, v))

    filas = [[(f"vs. {c.label}", None), celda(c.exceso_6m), celda(c.exceso_12m), celda(c.exceso_total),
              celda(c.pct_ventanas_ganadas, True)] for c in comps]
    st.markdown(tabla_html(t, ["", "Ultimos 6 meses", "Ultimos 12 meses", "Desde el inicio",
                               "Ventanas de 6m ganadas"], filas), unsafe_allow_html=True)

    fig = go.Figure()
    paleta = list(t.benchmarks)
    for i, c in enumerate(x for x in comps if x.label in ("QQQ", "SPY")):
        s = c.serie_exceso_6m * 100
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=f"vs. {c.label}", mode="lines",
                                 line=dict(color=paleta[i % len(paleta)], width=1.8),
                                 hovertemplate=f"vs. {c.label}: %{{y:+.1f}} pp<extra></extra>"))
    if fig.data:
        fig.add_hline(y=0, line=dict(color=t.border_strong, width=1))
        fig.update_layout(**layout(t, 260, yaxis=dict(ticksuffix=" pp", showgrid=True, gridcolor=t.chart_grid,
                                                      color=t.text_muted, zeroline=False)))
        st.markdown("**Diferencia en ventanas moviles de 6 meses**")
        st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "pp = puntos porcentuales de rendimiento a favor (+) o en contra (-) de tu cartera. \"Desde el inicio\" puede "
        "depender de un solo evento; las ventanas moviles muestran si le ganas de forma consistente. Si despues de "
        "varios anos no le ganas a QQQ de forma sostenida, elegir acciones individuales te esta costando rendimiento "
        "y trabajo."
    )


def _render_tir_cuenta(ctx: Contexto, res: Dict[str, ResumenRendimiento]) -> None:
    """v10.2: TIR de toda la cuenta (depositos/retiros vs. valor total)."""
    metas = cargar_metas()
    acciones = float(ctx.holdings.loc[ctx.holdings["Ticker"] != "CASH", "Valor ARS"].fillna(0).sum())
    c1, c2 = st.columns([1.4, 1])
    otros = c1.number_input(
        "Efectivo + FCI + otros en tu cuenta hoy (ARS)", min_value=0, step=10000,
        value=int(metas.get("otros_cuenta_ars") or 0), key="tir_cuenta_otros",
        help="Lo que tu cuenta de Cocos tiene fuera de acciones y CEDEARs: saldo disponible, FCI, cauciones. "
             "Miralo en Cocos: el CSV no permite saber cuanto vale hoy esa parte.",
    )
    c2.write("")
    c2.write("")
    if c2.button("Recordar este monto", icon=":material/save:", key="btn_tir_cuenta"):
        metas["otros_cuenta_ars"] = int(otros)
        guardar_metas(metas)
        st.success("Guardado.")
    try:
        rc = tir_cuenta(ctx.movimientos, acciones + otros, ccl=ctx.ccl_historico)
    except PerformanceError as e:
        st.caption(str(e))
        return
    usd = rc.tir_anual_usd is not None
    tir_c = rc.tir_anual_usd if usd else rc.tir_anual_ars
    r_acc = res.get(UNIDAD_USD if usd else UNIDAD_ARS)
    tir_a = r_acc.tir_anual if r_acc is not None else None
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("TIR de toda la cuenta", fmt_pct(tir_c), delta="en dolares" if usd else "en pesos", delta_color="off",
              help="XIRR de tus depositos y retiros contra lo que vale hoy la cuenta completa.")
    k2.metric("TIR solo acciones", fmt_pct(tir_a), help="La de arriba en esta pestana: solo la plata puesta en acciones/CEDEARs.")
    k3.metric("Diferencia", f"{(tir_c - tir_a) * 100:+.1f} pp" if tir_c is not None and tir_a is not None else "N/D",
              help="Negativa = la plata que no estaba en acciones (esperando, en FCI, en cash) rindio menos y te bajo "
                   "el resultado total. Es el costo de tener plata quieta.")
    k4.metric("Ganancia total", fmt_dinero(rc.ganancia_usd, UNIDAD_USD, signo=True) if usd else fmt_dinero(
        rc.valor_total_ars - rc.aportado_neto_ars, signo=True))
    if otros == 0:
        st.info("Carga el efectivo + FCI que ves en Cocos: si no, la cuenta parece valer menos de lo que vale y la TIR "
                "da de menos.")
    st.caption(
        f"Valor de la cuenta usado: acciones {fmt_dinero(acciones)} + otros {fmt_dinero(float(otros))}. Flujos: "
        f"{len(rc.flujos)} depositos/retiros (en pesos y en dolares, cada uno a su CCL). Con periodos menores a un ano "
        "la TIR anualizada es una extrapolacion."
    )
