"""
ui/componentes.py

Piezas reutilizables de las pestanas nuevas (v10.0): contexto compartido,
formato de numeros, KPIs y layouts base de Plotly segun el tema activo.
"""

from __future__ import annotations

import html as html_lib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

from ui.themes import Theme, plotly_base, rgba

# Unidades de medida del rendimiento
UNIDAD_ARS = "Pesos"
UNIDAD_USD = "Dolares (CCL)"
UNIDAD_REAL = "Pesos reales"
UNIDADES = [UNIDAD_USD, UNIDAD_ARS, UNIDAD_REAL]


@dataclass
class Contexto:
    """Todo lo que las pestanas nuevas necesitan, calculado una vez en app.py."""

    tema: Theme
    config: dict
    movimientos: pd.DataFrame
    holdings: pd.DataFrame
    curva: object  # core.historical_curve.ResultadoCurvaHistorica | None
    curva_error: Optional[str]
    dolar_ccl: Optional[float]
    ccl_historico: Optional[pd.Series]
    inflacion_mensual: Optional[pd.Series]
    avisos_macro: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Formato
# ---------------------------------------------------------------------------
def fmt_dinero(v: Optional[float], unidad: str = UNIDAD_ARS, decimales: int = 0, signo: bool = False) -> str:
    if v is None or pd.isna(v):
        return "N/D"
    if abs(v) < 0.5 * 10 ** (-decimales):
        v = 0.0
    s = f"{v:+,.{decimales}f}" if signo else f"{v:,.{decimales}f}"
    if s.startswith("+") or s.startswith("-"):
        signo_txt, s = s[0], s[1:]
    else:
        signo_txt = ""
    prefijo = "US$ " if unidad == UNIDAD_USD else "$"
    return f"{signo_txt}{prefijo}{s}"


def fmt_pct(v: Optional[float], decimales: int = 1, signo: bool = True, es_fraccion: bool = True) -> str:
    if v is None or pd.isna(v):
        return "N/D"
    x = v * 100 if es_fraccion else v
    return f"{x:+.{decimales}f}%" if signo else f"{x:.{decimales}f}%"


def nota_unidad(unidad: str) -> str:
    if unidad == UNIDAD_USD:
        return "Cada peso convertido al dolar CCL del dia en que se movio."
    if unidad == UNIDAD_REAL:
        return "Pesos ajustados por inflacion (IPC), expresados en pesos de hoy."
    return "Pesos corrientes, sin ajustar por inflacion ni por dolar."


# ---------------------------------------------------------------------------
# Graficos
# ---------------------------------------------------------------------------
def layout(t: Theme, height: int = 320, **kw) -> dict:
    base = plotly_base(
        t,
        height=height,
        margin=dict(t=30, b=10, l=10, r=10),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, bgcolor="rgba(0,0,0,0)",
                    font=dict(color=t.text_muted)),
        xaxis=dict(showgrid=False, color=t.text_muted, linecolor=t.border, title=None),
        yaxis=dict(showgrid=True, gridcolor=t.chart_grid, color=t.text_muted, zeroline=False, title=None),
    )
    base.update(kw)
    return base


def color_signo(t: Theme, v: float) -> str:
    return t.positive if v >= 0 else t.negative


def tabla_html(t: Theme, columnas: Sequence[str], filas: Sequence[Sequence[Tuple[str, Optional[str]]]], alinear_primera: str = "left") -> str:
    """Tabla HTML compacta y sobria. Cada celda es (texto, color|None).
    El texto se escapa."""
    th = "".join(
        f'<th style="text-align:{"left" if i == 0 else "right"};padding:8px 12px;color:{t.text_muted};'
        f'font-weight:500;font-size:0.78rem;border-bottom:1px solid {t.border};">{html_lib.escape(c)}</th>'
        for i, c in enumerate(columnas)
    )
    cuerpo = ""
    for fila in filas:
        tds = ""
        for i, (texto, color) in enumerate(fila):
            estilo_color = f"color:{color};" if color else f"color:{t.text};"
            peso = "font-weight:500;" if i == 0 else ""
            tds += (
                f'<td style="text-align:{alinear_primera if i == 0 else "right"};padding:8px 12px;{estilo_color}{peso}'
                f'font-variant-numeric:tabular-nums;border-bottom:1px solid {t.border};font-size:0.9rem;">'
                f"{html_lib.escape(texto)}</td>"
            )
        cuerpo += f"<tr>{tds}</tr>"
    return (
        f'<div style="overflow-x:auto;border:1px solid {t.border};border-radius:{t.radius}px;background:{t.surface};">'
        f'<table style="width:100%;border-collapse:collapse;"><thead><tr>{th}</tr></thead><tbody>{cuerpo}</tbody></table></div>'
    )


def barra_progreso_html(t: Theme, pct: float, etiqueta_izq: str, etiqueta_der: str) -> str:
    p = max(0.0, min(100.0, pct))
    return (
        f'<div style="margin:4px 0 2px 0;">'
        f'<div style="display:flex;justify-content:space-between;font-size:0.82rem;color:{t.text_muted};margin-bottom:6px;">'
        f"<span>{html_lib.escape(etiqueta_izq)}</span><span>{html_lib.escape(etiqueta_der)}</span></div>"
        f'<div style="height:8px;background:{t.surface_2};border:1px solid {t.border};border-radius:999px;overflow:hidden;">'
        f'<div style="width:{p:.2f}%;height:100%;background:{t.accent};"></div></div></div>'
    )


def tabla_stress_html(t: Theme, columnas: Dict[str, list], valor_usd: Optional[float] = None) -> str:
    """Tabla de escenarios de stress (v10.2). `columnas`: nombre -> lista de
    core.stress.ResultadoStress (mismos escenarios). Si se pasa `valor_usd`,
    agrega la perdida en dolares de la PRIMERA columna. '*' = mas del 10%
    del peso uso el proxy (escenario menos confiable)."""
    nombres = list(columnas)
    if not nombres or not columnas[nombres[0]]:
        return ""
    escenarios = [r.escenario for r in columnas[nombres[0]]]
    encabezado = ["Escenario"] + nombres + ([f"{nombres[0]} en US$"] if valor_usd else [])
    filas = []
    for esc in escenarios:
        fila: list = [(esc, None)]
        primero = None
        for n in nombres:
            r = next((x for x in columnas[n] if x.escenario == esc), None)
            if r is None:
                fila.append(("N/D", None))
                continue
            primero = primero if primero is not None else r
            marca = " *" if r.peso_con_supuesto > 10 else ""
            fila.append((f"{r.retorno_cartera * 100:+.1f}%{marca}", color_signo(t, r.retorno_cartera)))
        if valor_usd:
            fila.append((fmt_dinero(valor_usd * primero.retorno_cartera, UNIDAD_USD, signo=True) if primero else "N/D",
                         t.negative))
        filas.append(fila)
    return tabla_html(t, encabezado, filas)


def aviso_universo() -> None:
    st.caption(
        "Se mide sobre tu cartera de acciones y CEDEARs operada en Cocos Capital (la misma que la curva "
        "historica del panel), incluidos los dividendos cobrados. No incluye cash sin invertir, FCI, "
        "cauciones, bonos sin precio historico ni tenencias manuales."
    )
