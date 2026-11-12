"""
ui/tab_decisiones.py -- Pestana "Transicion y diario" (v10.2)

Plan de transicion hacia la cartera objetivo (vender lo que esta fuera
del objetivo y reinvertir) y diario de decisiones.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional

import pandas as pd
import streamlit as st

from core.config_manager import get_target_by_ticker
from core.diario import (
    ACCIONES,
    REFERENCIA,
    DiarioError,
    cargar_diario,
    eliminar_entrada,
    evaluar_diario,
    guardar_diario,
    nueva_entrada,
)
from core.market_data import get_precio_generico
from core.rebalancer import RebalancerError, calcular_transicion
from core.stress import correr_escenarios
from ui.componentes import UNIDAD_USD, Contexto, fmt_dinero, tabla_html, tabla_stress_html
from ui.themes import seccion

CATEGORIA_FUERA = "Fuera de objetivo"


def render(ctx: Contexto) -> None:
    _render_transicion(ctx)
    st.write("")
    _render_diario(ctx)


# ---------------------------------------------------------------------------
# Plan de transicion
# ---------------------------------------------------------------------------
def _categoria_de(config: dict, ticker: str) -> str:
    if ticker == "Efectivo":
        return "Efectivo"
    if ticker == "CASH":
        return "Cash (dividendos)"
    return config.get("activos", {}).get(ticker, {}).get("categoria") or CATEGORIA_FUERA


def _render_transicion(ctx: Contexto) -> None:
    t = ctx.tema
    with st.container(border=True, key="fp-card-transicion"):
        seccion("Plan de transicion", "Vender lo que esta fuera de tu objetivo y reinvertir en tu cartera objetivo")
        h = ctx.holdings
        objetivos = get_target_by_ticker(ctx.config)
        valuados = h[(h["Valor ARS"].fillna(0) > 0) & (h["Ticker"] != "CASH") & h["Precio ARS"].notna()]
        fuera = [tk for tk in valuados["Ticker"] if tk not in objetivos]

        c1, c2 = st.columns([3, 1])
        vender = c1.multiselect(
            "Que vender (posicion completa)", options=list(valuados["Ticker"]), default=fuera, key="trans_vender",
            help="Por defecto, todo lo que esta fuera de tu config (0% objetivo). Saca de la lista lo que quieras conservar.",
        )
        monto = c2.number_input("Aporte nuevo (ARS)", min_value=0, step=10000, value=0, key="trans_monto",
                                help="Plata nueva para sumar a la reinversion (opcional).")
        sobre = st.toggle(
            "Vender tambien el excedente de los activos que estan por encima de su objetivo", key="trans_sobre",
            help="Recorta (en nominales enteros) lo que sobra de cada activo de tu config respecto de su %. "
                 "Sin esto, los sobreponderados se dejan como estan y el DCA los va equilibrando.",
        )
        try:
            r = calcular_transicion(h, ctx.config, vender=vender, monto_nuevo=float(monto),
                                    vender_sobreponderados=sobre, dolar_ccl=ctx.dolar_ccl)
        except RebalancerError as e:
            st.warning(str(e))
            return

        usd = ctx.dolar_ccl
        neto_ventas = float(r.ventas["Monto Neto ARS"].sum()) if not r.ventas.empty else 0.0
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Ventas (neto)", fmt_dinero(neto_ventas),
                  delta=f"≈ {fmt_dinero(neto_ventas / usd, UNIDAD_USD)}" if usd else None, delta_color="off")
        k2.metric("Para reinvertir", fmt_dinero(r.efectivo_disponible),
                  help="Neto de las ventas mas el aporte nuevo.")
        k3.metric("Comisiones estimadas", fmt_dinero(r.comision_total),
                  delta=f"≈ {fmt_dinero(r.comision_total / usd, UNIDAD_USD, 2)}" if usd else None, delta_color="off",
                  help="Ventas + compras, al % estimado de Cocos Capital.")
        k4.metric("Vuelto", fmt_dinero(r.vuelto), help="Lo que queda sin invertir por comprar nominales enteros.")

        dinero = st.column_config.NumberColumn(format="$ %.0f")
        dolares = st.column_config.NumberColumn(format="US$ %.2f")
        st.markdown("**1. Ventas**")
        if r.ventas.empty:
            st.caption("No hay ventas en este plan.")
        else:
            st.dataframe(
                r.ventas[["Ticker", "Motivo", "Nominales a Vender", "Precio ARS", "Monto Neto ARS", "Equivalente USD"]],
                hide_index=True, use_container_width=True,
                column_config={"Precio ARS": dinero, "Monto Neto ARS": dinero, "Equivalente USD": dolares,
                               "Nominales a Vender": st.column_config.NumberColumn(format="%g")},
            )
        st.markdown("**2. Compras**")
        compras = r.compras.ordenes if r.compras is not None else pd.DataFrame()
        compras = compras[compras["Nominales a Comprar"] > 0] if not compras.empty else compras
        if compras.empty:
            st.caption("No hay compras: sin efectivo para reinvertir, o no alcanza para un nominal.")
        else:
            st.dataframe(
                compras[["Ticker Ejecucion", "Nominales a Comprar", "Precio Actual", "Costo Total Estimado ARS",
                         "Equivalente USD"]].rename(columns={"Ticker Ejecucion": "Ticker", "Precio Actual": "Precio ARS"}),
                hide_index=True, use_container_width=True,
                column_config={"Precio ARS": dinero, "Costo Total Estimado ARS": dinero, "Equivalente USD": dolares,
                               "Nominales a Comprar": st.column_config.NumberColumn(format="%g")},
            )

        st.markdown("**3. Antes y despues**")
        st.markdown(_tabla_antes_despues(ctx, r), unsafe_allow_html=True)

        st.markdown("**4. Cuanto caeria en una crisis, antes y despues**")
        try:
            columnas = {
                "Hoy": correr_escenarios(r.pesos_antes, ctx.config),
                "Despues del plan": correr_escenarios(r.pesos_despues, ctx.config),
                "Objetivo": correr_escenarios(r.pesos_objetivo, ctx.config),
            }
            st.markdown(tabla_stress_html(t, columnas), unsafe_allow_html=True)
            st.caption("Mismos escenarios que en la pestana Riesgo (detalle y supuestos ahi).")
        except Exception as e:
            st.caption(f"No se pudo correr el stress test: {e}")
        for a in r.advertencias:
            st.caption(a)


def _tabla_antes_despues(ctx: Contexto, r) -> str:
    t = ctx.tema
    cats: Dict[str, Dict[str, float]] = {}
    for col, serie in (("antes", r.pesos_antes), ("despues", r.pesos_despues), ("objetivo", r.pesos_objetivo)):
        for tk, v in serie.items():
            cat = _categoria_de(ctx.config, tk)
            cats.setdefault(cat, {"antes": 0.0, "despues": 0.0, "objetivo": 0.0})[col] += float(v)
    orden = sorted(cats, key=lambda c: -cats[c]["objetivo"] - cats[c]["antes"] / 1000)
    filas = []
    for cat in orden:
        d = cats[cat]
        desvio = d["despues"] - d["objetivo"]
        color = t.positive if abs(desvio) <= 2 else (t.warning if abs(desvio) <= 5 else t.negative)
        filas.append([(cat, None), (f"{d['antes']:.1f}%", None), (f"{d['despues']:.1f}%", None),
                      (f"{d['objetivo']:.1f}%", None), (f"{desvio:+.1f} pp", color)])
    return tabla_html(t, ["Categoria", "Hoy", "Despues del plan", "Objetivo", "Desvio final"], filas)


# ---------------------------------------------------------------------------
# Diario de decisiones
# ---------------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def _precio_suelto(ticker: str, dolar_ccl: Optional[float]) -> Optional[float]:
    """Precio en ARS de un ticker que ya no tenes (ej. una decision de venta)."""
    try:
        return float(get_precio_generico(ticker, dolar_ccl).precio_ars)
    except Exception:
        return None


def _precios_hoy(ctx: Contexto, tickers: Iterable[str]) -> Dict[str, float]:
    h = ctx.holdings.set_index("Ticker")["Precio ARS"]
    out: Dict[str, float] = {}
    for tk in {str(x).strip().upper() for x in tickers}:
        if tk in h.index and pd.notna(h[tk]) and float(h[tk]) > 0:
            out[tk] = float(h[tk])
        else:
            p = _precio_suelto(tk, ctx.dolar_ccl)
            if p:
                out[tk] = p
    return out


def _render_diario(ctx: Contexto) -> None:
    with st.container(border=True, key="fp-card-diario"):
        seccion("Diario de decisiones", "Anota el por que de cada decision fuera del DCA y mira como salio")
        try:
            entradas = cargar_diario()
        except DiarioError as e:
            st.error(str(e))
            return
        opciones = sorted((set(ctx.holdings["Ticker"]) - {"CASH"}) | set(ctx.config.get("activos", {})))
        with st.form("form_diario", clear_on_submit=True, border=False):
            c1, c2, c3 = st.columns([1, 1, 1])
            ticker = c1.selectbox("Activo", opciones, accept_new_options=True, key="diario_ticker",
                                  help="Podes escribir un ticker que no tengas (ej. algo que decidiste NO comprar).")
            accion = c2.selectbox("Decision", ACCIONES, key="diario_accion")
            horizonte = c3.number_input("Revisar en (meses)", min_value=1, max_value=120, value=6, key="diario_horizonte")
            motivo = st.text_area(
                "Por que", key="diario_motivo",
                placeholder="Ej: vendo MSTR porque ya tengo bitcoin via IBIT y duplica el riesgo de la cartera.",
            )
            enviar = st.form_submit_button("Guardar decision", icon=":material/edit_note:")
        if enviar:
            tk = str(ticker or "").strip().upper()
            precios = _precios_hoy(ctx, [tk, REFERENCIA])
            try:
                entradas.append(nueva_entrada(tk, accion, motivo, precios.get(tk), precios.get(REFERENCIA),
                                              ctx.dolar_ccl, int(horizonte)))
                guardar_diario(entradas)
                st.success(f"Decision sobre {tk} guardada. Volve a mirarla en {int(horizonte)} meses.")
            except DiarioError as err:
                st.warning(str(err))

        if not entradas:
            st.caption(
                "Todavia no anotaste decisiones. Empeza con las ventas de tu plan de transicion: dentro de unos meses "
                "vas a poder ver, en dolares y contra SPY, si vender cada una fue buena idea."
            )
            return
        precios = _precios_hoy(ctx, {e["ticker"] for e in entradas} | {REFERENCIA})
        df = evaluar_diario(entradas, precios, precios.get(REFERENCIA), ctx.dolar_ccl or 0.0)
        evaluadas = df[df["Resultado"].isin(["Acierto", "Error"])]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Decisiones anotadas", len(df))
        k2.metric("Evaluables", len(evaluadas), help="Con precio y al menos 30 dias de antiguedad.")
        k3.metric("Aciertos", f"{(evaluadas['Resultado'] == 'Acierto').mean() * 100:.0f}%" if len(evaluadas) else "N/D",
                  help="Compra/Mantener: le gano a SPY desde ese dia. Venta: rindio MENOS que SPY despues de vender.")
        k4.metric("Para revisar", int(df["Revisar"].sum()), help="Ya paso el horizonte que te pusiste.")
        pct = st.column_config.NumberColumn(format="%+.1f%%")
        st.dataframe(
            df.drop(columns=["id"]), hide_index=True, use_container_width=True,
            column_config={"Activo USD %": pct, f"{REFERENCIA} USD %": pct,
                           "Diferencia pp": st.column_config.NumberColumn(format="%+.1f pp"),
                           "Motivo": st.column_config.TextColumn(width="large"),
                           "Revisar": st.column_config.CheckboxColumn()},
        )
        c1, c2 = st.columns([3, 1])
        etiquetas = {e["id"]: f"{e['fecha']} · {e['accion']} {e['ticker']}" for e in entradas}
        borrar = c1.selectbox("Borrar una decision", [None] + list(etiquetas), format_func=lambda i: "-" if i is None
                              else etiquetas[i], key="diario_borrar")
        c2.write("")
        c2.write("")
        if c2.button("Borrar", icon=":material/delete:", key="btn_diario_borrar", disabled=borrar is None):
            guardar_diario(eliminar_entrada(entradas, borrar))
            st.rerun()
        st.caption(
            f"Todo se mide en dolares (CCL del dia de la decision y de hoy) contra {REFERENCIA}, que es la alternativa "
            "de no hacer nada especial. Se guarda en data/diario.json."
        )
