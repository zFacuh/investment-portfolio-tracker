"""
ui/themes.py

Motor de temas visuales (v9.0) -- reemplaza al CSS "Cyberpunk Minimalista"
(v8.0) que vivia hardcodeado adentro de app.py.

Idea central: cada tema es SOLO un conjunto de tokens (colores, fuentes,
radio de bordes, densidad) -- un `Theme`. El CSS inyectado, el tema nativo
de Streamlit (que es lo unico que puede pintar el interior de las tablas
st.dataframe, dibujadas en <canvas>), los colores de Plotly y los estilos
de celda de pandas Styler se GENERAN a partir de esos tokens. Asi:

  - Agregar/ajustar un tema = tocar un diccionario, no 300 lineas de CSS.
  - Todos los temas comparten exactamente la misma estructura visual
    (mismos componentes, mismas reglas), asi que compararlos es justo:
    cambia la "piel", no el layout.
  - app.py no tiene ni un color hardcodeado: pide todo a este modulo.

Por que el cambio de tema recarga la pagina (ver `aplicar_tema`):
Streamlit manda el tema al navegador al INICIO de cada corrida del script,
y el frontend solo lo aplica la primera vez que lo recibe en esa sesion
(cambios posteriores en la misma sesion se ignoran). Por eso, cuando el
tema pedido difiere del que ya tiene el proceso, se actualiza la config
global y se fuerza UNA recarga del navegador -- la sesion nueva ya nace
con el tema correcto. No hay riesgo de loop: despues de la recarga el tema
del proceso ya coincide y no se vuelve a recargar.

Este modulo NO toca nada de core/: es pura presentacion.
"""

from __future__ import annotations

import html as html_lib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit import config as _st_config

from core.rutas import CONFIG_DIR  # noqa: E402

PREFS_PATH = CONFIG_DIR / "ui_prefs.json"


# ---------------------------------------------------------------------------
# Modelo de tema
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Fuente:
    """Una familia tipografica de Google Fonts (nombre CSS + URL del CSS)."""

    familia: str
    url: str

    def spec_streamlit(self, fallback: str) -> str:
        # Formato que acepta theme.font / theme.headingFont en Streamlit
        # 1.61: "<familia>:<url>, <fallback generico>".
        return f"{self.familia}:{self.url}, {fallback}"

    def stack_css(self, fallback: str) -> str:
        return f"'{self.familia}', {fallback}"


def _gf(familia: str, pesos: str = "400;500;600;700") -> Fuente:
    nombre_url = familia.replace(" ", "+")
    return Fuente(
        familia=familia,
        url=f"https://fonts.googleapis.com/css2?family={nombre_url}:wght@{pesos}&display=swap",
    )


@dataclass(frozen=True)
class Theme:
    key: str
    nombre: str
    descripcion: str
    base: str  # "dark" | "light"

    # Superficies
    bg: str
    surface: str
    surface_2: str
    border: str
    border_strong: str

    # Texto
    text: str
    text_muted: str
    text_faint: str

    # Acento y semanticos
    accent: str
    accent_contrast: str  # texto sobre un relleno de acento
    positive: str
    negative: str
    warning: str

    # Categorias del portafolio (color de texto; el fondo se deriva con alpha)
    cat_core: str
    cat_satelite: str
    cat_otra: str
    cat_muted: str

    # Graficos
    chart_palette: Tuple[str, ...]
    chart_grid: str
    divergente: Tuple[str, str, str]  # (-1, 0, +1) para la matriz de correlacion
    linea_valor: str
    linea_capital: str
    benchmarks: Tuple[str, ...]

    # Tipografia
    font_body: Fuente
    font_heading: Fuente
    font_num: Fuente  # cifras (metricas, montos): siempre con tabular-nums
    heading_weight: int = 600
    heading_tracking: str = "-0.015em"
    label_upper: bool = False  # labels de metricas en versalitas (estilo terminal)

    # Forma y densidad
    radius: int = 8
    metric_value_size: str = "1.75rem"
    card_padding: str = "18px 20px"
    mono_numeros: bool = False  # True si font_num es monoespaciada

    extra_css: str = field(default="", compare=False)


# ---------------------------------------------------------------------------
# Catalogo de temas
# ---------------------------------------------------------------------------
_INTER = _gf("Inter")

THEMES: Dict[str, Theme] = {
    # 1) Grafito -- estilo producto moderno (Linear / Vercel / Stripe dark):
    #    neutro, un solo acento azul sobrio, cero efectos. El color aparece
    #    casi solo donde significa algo (ganancia, perdida, accion).
    "grafito": Theme(
        key="grafito",
        nombre="Grafito",
        descripcion="Oscuro neutro, un solo acento azul, cero efectos. Estilo producto moderno.",
        base="dark",
        bg="#0B0C0E",
        surface="#131417",
        surface_2="#1A1C20",
        border="#24262B",
        border_strong="#363940",
        text="#EDEEF0",
        text_muted="#9A9EA7",
        text_faint="#62666F",
        accent="#5B8DEF",
        accent_contrast="#FFFFFF",
        positive="#3FB27F",
        negative="#E5484D",
        warning="#E2A336",
        cat_core="#7EA6F4",
        cat_satelite="#5CC49A",
        cat_otra="#B39DFA",
        cat_muted="#8B8F98",
        chart_palette=("#5B8DEF", "#46B3A4", "#D9A441", "#9B8AFB", "#E07A5F", "#6CB85C", "#C77DBA", "#7A8FA6"),
        chart_grid="#1F2126",
        divergente=("#5B8DEF", "#24262B", "#E5484D"),
        linea_valor="#5B8DEF",
        linea_capital="#8B8F98",
        benchmarks=("#D9A441", "#9B8AFB", "#46B3A4", "#E07A5F", "#C77DBA"),
        font_body=_INTER,
        font_heading=_INTER,
        font_num=_INTER,
        heading_weight=600,
        radius=8,
    ),
    # 2) Terminal Institucional -- la estetica de una terminal financiera
    #    profesional (Bloomberg / Refinitiv), pero refinada: negro puro,
    #    ambar como unico acento, cifras en monoespaciada, esquinas rectas,
    #    labels en versalitas. Densa y seria.
    "institucional": Theme(
        key="institucional",
        nombre="Terminal Institucional",
        descripcion="Negro y ambar, cifras en monoespaciada, esquinas rectas. Mesa de trading seria.",
        base="dark",
        bg="#090909",
        surface="#111111",
        surface_2="#181818",
        border="#242424",
        border_strong="#3A3A3A",
        text="#ECE9E4",
        text_muted="#9C978F",
        text_faint="#66625C",
        accent="#F0A202",
        accent_contrast="#111111",
        positive="#2FBF71",
        negative="#F0544F",
        warning="#F0A202",
        cat_core="#F0B840",
        cat_satelite="#5DC8E8",
        cat_otra="#C9A0F5",
        cat_muted="#8F8B85",
        chart_palette=("#F0A202", "#4EA8DE", "#2FBF71", "#C084FC", "#F0544F", "#94A3B8", "#FB923C", "#22D3EE"),
        chart_grid="#1C1C1C",
        divergente=("#4EA8DE", "#242424", "#F0544F"),
        linea_valor="#F0A202",
        linea_capital="#8F8B85",
        benchmarks=("#4EA8DE", "#C084FC", "#2FBF71", "#F0544F", "#22D3EE"),
        font_body=_gf("IBM Plex Sans"),
        font_heading=_gf("IBM Plex Sans"),
        font_num=_gf("IBM Plex Mono", "400;500;600"),
        heading_weight=600,
        heading_tracking="-0.005em",
        label_upper=True,
        radius=2,
        metric_value_size="1.6rem",
        card_padding="14px 16px",
        mono_numeros=True,
    ),
    # 3) Private Banking -- azul marino profundo + dorado, titulos en serif.
    #    Busca transmitir solidez y "patrimonio" (banca privada, family
    #    office) mas que "app tecnologica".
    "private_banking": Theme(
        key="private_banking",
        nombre="Private Banking",
        descripcion="Azul marino y dorado, titulos en serif. Sobrio, transmite patrimonio y solidez.",
        base="dark",
        bg="#0C1220",
        surface="#121A2B",
        surface_2="#182236",
        border="#223049",
        border_strong="#33456A",
        text="#E9ECF2",
        text_muted="#98A3B8",
        text_faint="#5F6B82",
        accent="#C9A54E",
        accent_contrast="#0C1220",
        positive="#4CAF83",
        negative="#D9655B",
        warning="#D8A657",
        cat_core="#D9B96A",
        cat_satelite="#7FB6E8",
        cat_otra="#C5A3D6",
        cat_muted="#8E99AE",
        chart_palette=("#C9A54E", "#6D8BC7", "#4CAF83", "#B07AA1", "#D9655B", "#8EA4B8", "#E0B97A", "#5FA3A3"),
        chart_grid="#1B2436",
        divergente=("#6D8BC7", "#223049", "#D9655B"),
        linea_valor="#C9A54E",
        linea_capital="#8E99AE",
        benchmarks=("#6D8BC7", "#B07AA1", "#4CAF83", "#D9655B", "#5FA3A3"),
        font_body=_gf("Manrope"),
        font_heading=_gf("Source Serif 4", "500;600;700"),
        font_num=_gf("Manrope"),
        heading_weight=600,
        heading_tracking="-0.005em",
        radius=10,
    ),
    # 4) Nordico Suave -- gris calido, acento lavanda, esquinas redondeadas.
    #    El mas "descansado" para la vista: pensado para mirarlo seguido
    #    sin fatiga.
    "nordico": Theme(
        key="nordico",
        nombre="Nordico Suave",
        descripcion="Gris calido, acento lavanda, bordes redondeados. El mas descansado para la vista.",
        base="dark",
        bg="#17181A",
        surface="#1F2023",
        surface_2="#26282B",
        border="#2F3135",
        border_strong="#43464C",
        text="#E6E4DF",
        text_muted="#A29F97",
        text_faint="#6D6B66",
        accent="#8FA8E8",
        accent_contrast="#15161A",
        positive="#7FBF8E",
        negative="#E07B73",
        warning="#E6B87D",
        cat_core="#A5B9EE",
        cat_satelite="#8FCB9D",
        cat_otra="#CDAEDD",
        cat_muted="#9A978F",
        chart_palette=("#8FA8E8", "#7FBF8E", "#E6B87D", "#C39BD3", "#E07B73", "#7CC6C2", "#D4A5A5", "#A3B0C2"),
        chart_grid="#27292C",
        divergente=("#8FA8E8", "#2F3135", "#E07B73"),
        linea_valor="#8FA8E8",
        linea_capital="#9A978F",
        benchmarks=("#E6B87D", "#C39BD3", "#7CC6C2", "#E07B73", "#7FBF8E"),
        font_body=_gf("DM Sans"),
        font_heading=_gf("DM Sans"),
        font_num=_gf("DM Sans"),
        heading_weight=600,
        radius=14,
        card_padding="20px 22px",
    ),
    # 5) Ejecutivo Claro -- el unico claro: fondo papel, texto casi negro,
    #    azul marino institucional. La estetica de un reporte financiero
    #    impreso (FT, informe de gestion de un banco).
    "claro": Theme(
        key="claro",
        nombre="Ejecutivo Claro",
        descripcion="Fondo papel y azul marino. Estetica de informe financiero impreso. Unico tema claro.",
        base="light",
        bg="#F6F5F2",
        surface="#FFFFFF",
        surface_2="#FAF9F7",
        border="#E3E1DB",
        border_strong="#C9C6BE",
        text="#16181D",
        text_muted="#62666E",
        text_faint="#9A9DA3",
        accent="#1F4E8C",
        accent_contrast="#FFFFFF",
        positive="#1E7B4F",
        negative="#C0392B",
        warning="#B7791F",
        cat_core="#1F4E8C",
        cat_satelite="#1E7B4F",
        cat_otra="#6B4FA0",
        cat_muted="#6B6F76",
        chart_palette=("#1F4E8C", "#2E8B74", "#C08A2E", "#7A5CA8", "#C0392B", "#4F7CAC", "#8C6D46", "#5E6B78"),
        chart_grid="#ECEAE5",
        divergente=("#1F4E8C", "#F1EFEA", "#C0392B"),
        linea_valor="#1F4E8C",
        linea_capital="#8A8D93",
        benchmarks=("#C08A2E", "#7A5CA8", "#2E8B74", "#C0392B", "#4F7CAC"),
        font_body=_INTER,
        font_heading=_gf("Source Serif 4", "500;600;700"),
        font_num=_INTER,
        heading_weight=600,
        heading_tracking="-0.01em",
        radius=8,
    ),
}

DEFAULT_THEME_KEY = "grafito"


# ---------------------------------------------------------------------------
# Utilidades de color
# ---------------------------------------------------------------------------
def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


# ---------------------------------------------------------------------------
# Persistencia de la eleccion (config/ui_prefs.json)
# ---------------------------------------------------------------------------
def cargar_tema_guardado() -> str:
    try:
        with PREFS_PATH.open("r", encoding="utf-8") as f:
            key = json.load(f).get("tema")
    except (OSError, json.JSONDecodeError, AttributeError):
        return DEFAULT_THEME_KEY
    return key if key in THEMES else DEFAULT_THEME_KEY


def guardar_tema(key: str) -> None:
    try:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PREFS_PATH.open("w", encoding="utf-8") as f:
            json.dump({"tema": key}, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError:
        # No poder recordar la preferencia no debe tumbar la app: el tema
        # igual se aplica en esta corrida.
        pass


def get_tema_activo() -> Theme:
    key = st.session_state.get("_tema_activo") or cargar_tema_guardado()
    return THEMES.get(key, THEMES[DEFAULT_THEME_KEY])


# ---------------------------------------------------------------------------
# Tema nativo de Streamlit (lo unico que llega al interior de las tablas)
# ---------------------------------------------------------------------------
def _opciones_streamlit(t: Theme) -> Dict[str, object]:
    fallback = "sans-serif"
    return {
        "theme.base": t.base,
        "theme.primaryColor": t.accent,
        "theme.backgroundColor": t.bg,
        "theme.secondaryBackgroundColor": t.surface_2,
        "theme.textColor": t.text,
        "theme.font": t.font_body.spec_streamlit(fallback),
        "theme.headingFont": t.font_heading.spec_streamlit("serif" if "Serif" in t.font_heading.familia else fallback),
        "theme.codeFont": t.font_num.spec_streamlit("monospace") if t.mono_numeros else "monospace",
        "theme.baseRadius": f"{t.radius}px",
        "theme.borderColor": t.border,
        "theme.dataframeBorderColor": t.border,
        "theme.dataframeHeaderBackgroundColor": t.surface_2,
        "theme.showWidgetBorder": True,
        "theme.greenColor": t.positive,
        "theme.redColor": t.negative,
        "theme.chartCategoricalColors": list(t.chart_palette),
    }


def aplicar_tema(t: Theme) -> None:
    """Aplica el tema al proceso de Streamlit + inyecta el CSS. Si el tema
    que tenia el proceso era otro, fuerza una recarga del navegador (ver
    el docstring del modulo: es la unica forma de que el frontend lo tome)."""
    cambio = False
    for opcion, valor in _opciones_streamlit(t).items():
        try:
            if _st_config.get_option(opcion) != valor:
                _st_config.set_option(opcion, valor)
                cambio = True
        except Exception:
            # Una opcion que esta version de Streamlit no conozca no debe
            # impedir aplicar el resto.
            continue

    st.session_state["_tema_activo"] = t.key
    st.markdown(f"<style>{construir_css(t)}</style>", unsafe_allow_html=True)

    if cambio:
        # Recarga unica: la sesion nueva ya recibe el tema correcto.
        components.html("<script>window.parent.location.reload();</script>", height=0)


# ---------------------------------------------------------------------------
# CSS generado desde los tokens
# ---------------------------------------------------------------------------
def construir_css(t: Theme) -> str:
    body = t.font_body.stack_css("-apple-system, 'Segoe UI', Roboto, sans-serif")
    head = t.font_heading.stack_css("Georgia, serif" if "Serif" in t.font_heading.familia else "sans-serif")
    num = t.font_num.stack_css("ui-monospace, monospace" if t.mono_numeros else "sans-serif")
    r = t.radius
    label_transform = "uppercase" if t.label_upper else "none"
    label_tracking = "0.07em" if t.label_upper else "0"
    label_size = "0.72rem" if t.label_upper else "0.82rem"
    sombra = "0 1px 2px rgba(16, 24, 40, 0.04)" if t.base == "light" else "none"

    fuentes = {t.font_body.url, t.font_heading.url, t.font_num.url}
    imports = "\n".join(f"@import url('{u}');" for u in sorted(fuentes))

    return f"""
{imports}

:root {{
    --fp-bg: {t.bg};
    --fp-surface: {t.surface};
    --fp-surface-2: {t.surface_2};
    --fp-border: {t.border};
    --fp-border-strong: {t.border_strong};
    --fp-text: {t.text};
    --fp-muted: {t.text_muted};
    --fp-faint: {t.text_faint};
    --fp-accent: {t.accent};
    --fp-on-accent: {t.accent_contrast};
    --fp-pos: {t.positive};
    --fp-neg: {t.negative};
    --fp-radius: {r}px;
    --fp-font-body: {body};
    --fp-font-head: {head};
    --fp-font-num: {num};
}}

/* Lienzo: plano, sin gradientes ni ruido */
[data-testid="stAppViewContainer"], [data-testid="stApp"] {{ background: var(--fp-bg); }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stAppDeployButton"], [data-testid="stDecoration"] {{ display: none !important; }}
.block-container {{ padding-top: 2.2rem !important; padding-bottom: 4rem !important; max-width: 1480px; }}
[data-testid="stSidebar"] {{ background: var(--fp-surface); border-right: 1px solid var(--fp-border); }}

html, body, [data-testid="stApp"] {{ font-family: var(--fp-font-body); -webkit-font-smoothing: antialiased; }}

/* Titulos: sentence case, peso medio, sin mayusculas forzadas */
h1, h2, h3, h4, h5, h6 {{
    font-family: var(--fp-font-head) !important;
    font-weight: {t.heading_weight} !important;
    letter-spacing: {t.heading_tracking} !important;
    color: var(--fp-text) !important;
    text-transform: none !important;
}}
h5, h6 {{ font-size: 1.02rem !important; margin-bottom: 0.2rem !important; }}
[data-testid="stHeadingWithActionElements"] a {{ display: none !important; }}
.stCaption, [data-testid="stCaptionContainer"] {{ color: var(--fp-muted) !important; }}

/* Encabezado propio de la app */
.fp-header {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 24px;
    flex-wrap: wrap; padding-bottom: 18px; margin-bottom: 8px; border-bottom: 1px solid var(--fp-border); }}
.fp-overline {{ font-size: 0.72rem; letter-spacing: 0.12em; text-transform: uppercase; color: var(--fp-muted);
    font-weight: 600; margin-bottom: 6px; }}
.fp-title {{ font-family: var(--fp-font-head); font-size: 2rem; line-height: 1.1; font-weight: {t.heading_weight};
    letter-spacing: {t.heading_tracking}; color: var(--fp-text); margin: 0; }}
.fp-subtitle {{ color: var(--fp-muted); font-size: 0.9rem; margin-top: 6px; }}
.fp-header-meta {{ display: flex; gap: 28px; flex-wrap: wrap; }}
.fp-meta-item {{ text-align: right; }}
.fp-meta-label {{ font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--fp-faint); font-weight: 600; }}
.fp-meta-value {{ font-family: var(--fp-font-num); font-variant-numeric: tabular-nums; color: var(--fp-text);
    font-size: 0.95rem; font-weight: 500; margin-top: 2px; }}

/* Titulo de seccion con linea fina */
.fp-section {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px;
    margin: 6px 0 12px 0; }}
.fp-section-title {{ font-family: var(--fp-font-head); font-size: 1.08rem; font-weight: {t.heading_weight};
    color: var(--fp-text); letter-spacing: {t.heading_tracking}; }}
.fp-section-hint {{ color: var(--fp-faint); font-size: 0.8rem; }}

/* Tarjetas de metricas */
div[data-testid="stMetric"] {{
    background: var(--fp-surface);
    border: 1px solid var(--fp-border);
    border-radius: var(--fp-radius);
    padding: {t.card_padding};
    box-shadow: {sombra};
    transition: border-color 0.15s ease;
}}
div[data-testid="stMetric"]:hover {{ border-color: var(--fp-border-strong); }}
div[data-testid="stMetricLabel"] p {{
    color: var(--fp-muted) !important;
    font-size: {label_size} !important;
    font-weight: 500 !important;
    text-transform: {label_transform};
    letter-spacing: {label_tracking};
}}
div[data-testid="stMetricValue"] {{
    font-family: var(--fp-font-num) !important;
    font-variant-numeric: tabular-nums;
    font-size: {t.metric_value_size} !important;
    font-weight: 600 !important;
    color: var(--fp-text) !important;
    letter-spacing: -0.01em;
}}
div[data-testid="stMetricDelta"] {{ font-family: var(--fp-font-num) !important; font-variant-numeric: tabular-nums; }}
[class*="st-key-metric-drawdown"] div[data-testid="stMetricValue"] {{ color: var(--fp-neg) !important; }}
.st-key-metrics-dca-compactas div[data-testid="stMetric"] {{ padding: 10px 12px; box-shadow: none; }}
.st-key-metrics-dca-compactas div[data-testid="stMetricValue"] {{ font-size: 1.1rem !important; }}
.st-key-metrics-dca-compactas div[data-testid="stMetricLabel"] p {{ font-size: 0.72rem !important; }}

/* Tarjetas de panel: st.container(border=True, key="fp-card-...").
   Se engancha por la clase "st-key-<key>" que Streamlit agrega al
   contenedor (contrato estable) en vez de por clases internas de emotion. */
[class*="st-key-fp-card"] {{
    background: var(--fp-surface) !important;
    border: 1px solid var(--fp-border) !important;
    border-radius: var(--fp-radius) !important;
    padding: 18px 20px 20px 20px !important;
    box-shadow: {sombra};
}}
[class*="st-key-fp-card"] div[data-testid="stMetric"] {{ background: var(--fp-surface-2); box-shadow: none; }}
[class*="st-key-fp-card"] .order-card {{ background: var(--fp-surface-2); box-shadow: none; }}

/* Botones */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {{
    border-radius: var(--fp-radius) !important;
    font-family: var(--fp-font-body) !important;
    font-weight: 500 !important;
    letter-spacing: 0 !important;
    text-transform: none !important;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primaryFormSubmit"] {{
    background: var(--fp-accent) !important;
    color: var(--fp-on-accent) !important;
    border: 1px solid var(--fp-accent) !important;
    box-shadow: none !important;
}}
.stButton > button[kind="primary"]:hover {{ filter: brightness(1.08); }}
.stButton > button[kind="primary"]:active {{ transform: translateY(1px); }}
.stButton > button:not([kind="primary"]), .stFormSubmitButton > button:not([kind="primaryFormSubmit"]) {{
    background: var(--fp-surface) !important;
    border: 1px solid var(--fp-border-strong) !important;
    color: var(--fp-text) !important;
}}
.stButton > button:not([kind="primary"]):hover {{ border-color: var(--fp-accent) !important; color: var(--fp-accent) !important; }}

/* Alertas: en vez del bloque amarillo/azul/rojo lleno de Streamlit, una
   nota sobria (fondo de superficie + filete de color a la izquierda). El
   color sigue indicando el tipo, pero no grita. */
div[data-testid="stAlertContainer"] {{
    background: var(--fp-surface-2) !important;
    border: 1px solid var(--fp-border) !important;
    border-left: 3px solid var(--fp-muted) !important;
    border-radius: var(--fp-radius) !important;
    color: var(--fp-text) !important;
    padding: 10px 14px !important;
}}
div[data-testid="stAlertContainer"] * {{ color: var(--fp-text) !important; }}
div[data-testid="stAlertContainer"] p {{ font-size: 0.87rem !important; line-height: 1.5; }}
div[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {{ border-left-color: {t.warning} !important; }}
div[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {{ border-left-color: {t.negative} !important; }}
div[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {{ border-left-color: {t.positive} !important; }}
div[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {{ border-left-color: {t.accent} !important; }}
div[data-testid="stAlertContainer"] [data-testid="stAlertDynamicIcon"] {{ display: none; }}

/* Expander */
div[data-testid="stExpander"] details {{
    background: var(--fp-surface);
    border: 1px solid var(--fp-border) !important;
    border-radius: var(--fp-radius) !important;
}}

/* Tablas: solo el marco (el interior lo pinta el tema nativo) */
div[data-testid="stDataFrame"], div[data-testid="stDataFrameResizable"] {{ border-radius: var(--fp-radius) !important; }}

/* Tabs */
div[data-testid="stTabs"] [data-baseweb="tab-list"] {{ gap: 6px; border-bottom: 1px solid var(--fp-border); }}
button[data-testid="stTab"] {{ font-weight: 500; font-size: 0.92rem; padding: 10px 14px !important; }}
button[data-testid="stTab"] p {{ font-size: 0.92rem !important; }}
button[data-testid="stTab"][aria-selected="true"] {{ color: var(--fp-text) !important; }}
button[data-testid="stTab"][aria-selected="false"] {{ color: var(--fp-muted) !important; }}
div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ background-color: var(--fp-accent) !important; height: 2px; }}

hr {{ border-color: var(--fp-border) !important; margin: 1.6rem 0 !important; }}

/* Badges de Categoria */
.badge {{
    display: inline-block; padding: 2px 8px; border-radius: 999px;
    font-size: 0.7rem; font-weight: 600; letter-spacing: 0.01em; white-space: nowrap;
    vertical-align: middle; margin-left: 6px;
}}
.badge-core {{ background: {rgba(t.cat_core, 0.14)}; color: {t.cat_core}; border: 1px solid {rgba(t.cat_core, 0.30)}; }}
.badge-satelite {{ background: {rgba(t.cat_satelite, 0.14)}; color: {t.cat_satelite}; border: 1px solid {rgba(t.cat_satelite, 0.30)}; }}
.badge-otra {{ background: {rgba(t.cat_otra, 0.14)}; color: {t.cat_otra}; border: 1px solid {rgba(t.cat_otra, 0.30)}; }}
.badge-muted {{ background: {rgba(t.cat_muted, 0.12)}; color: {t.cat_muted}; border: 1px solid {rgba(t.cat_muted, 0.26)}; }}

/* Tarjetas de orden (Calculadora DCA) */
.order-card {{
    background: var(--fp-surface);
    border: 1px solid var(--fp-border);
    border-radius: var(--fp-radius);
    padding: 12px 14px;
    margin-bottom: 8px;
    box-shadow: {sombra};
    transition: border-color 0.15s ease;
}}
.order-card:hover {{ border-color: var(--fp-border-strong); }}
.order-card .order-row1 {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; }}
.order-card .order-ticker {{ font-weight: 600; font-size: 0.98rem; color: var(--fp-text); }}
.order-card .order-meta {{ color: var(--fp-muted); font-size: 0.8rem; margin-top: 3px;
    font-family: var(--fp-font-num); font-variant-numeric: tabular-nums; }}
.order-card .order-amount {{ color: var(--fp-text); font-family: var(--fp-font-num); font-variant-numeric: tabular-nums;
    font-weight: 600; font-size: 0.98rem; text-align: right; }}
.order-card .order-usd {{ color: var(--fp-faint); font-family: var(--fp-font-num); font-size: 0.76rem; text-align: right; }}

/* Selector de tema (sidebar) */
.fp-swatches {{ display: flex; gap: 5px; margin: 4px 0 2px 0; }}
.fp-swatch {{ width: 18px; height: 18px; border-radius: 4px; border: 1px solid rgba(127,127,127,0.35); }}
{t.extra_css}
"""


# ---------------------------------------------------------------------------
# Helpers de componentes (HTML propio, siempre escapado)
# ---------------------------------------------------------------------------
def header_html(titulo: str, subtitulo: str, meta: List[Tuple[str, str]], overline: str = "Portafolio de inversion") -> str:
    items = "".join(
        f'<div class="fp-meta-item"><div class="fp-meta-label">{html_lib.escape(k)}</div>'
        f'<div class="fp-meta-value">{html_lib.escape(v)}</div></div>'
        for k, v in meta
    )
    return (
        '<div class="fp-header"><div>'
        f'<div class="fp-overline">{html_lib.escape(overline)}</div>'
        f'<h1 class="fp-title">{html_lib.escape(titulo)}</h1>'
        f'<div class="fp-subtitle">{html_lib.escape(subtitulo)}</div>'
        f'</div><div class="fp-header-meta">{items}</div></div>'
    )


def seccion(titulo: str, hint: Optional[str] = None) -> None:
    """Titulo de seccion consistente en todos los temas (reemplaza a los
    '##### emoji Titulo' de markdown)."""
    hint_html = f'<span class="fp-section-hint">{html_lib.escape(hint)}</span>' if hint else ""
    st.markdown(
        f'<div class="fp-section"><span class="fp-section-title">{html_lib.escape(titulo)}</span>{hint_html}</div>',
        unsafe_allow_html=True,
    )


def swatches_html(t: Theme) -> str:
    colores = [t.bg, t.surface_2, t.accent, t.positive, t.negative]
    return '<div class="fp-swatches">' + "".join(
        f'<span class="fp-swatch" style="background:{c}"></span>' for c in colores
    ) + "</div>"


def selector_de_tema() -> None:
    """Selector de tema para la sidebar. Guarda la eleccion en
    config/ui_prefs.json y recarga para aplicarla."""
    actual = get_tema_activo()
    keys = list(THEMES.keys())

    def _on_change() -> None:
        nuevo = st.session_state["_selector_tema"]
        guardar_tema(nuevo)
        st.session_state["_tema_activo"] = nuevo

    st.markdown("**Apariencia**")
    st.radio(
        "Tema",
        options=keys,
        index=keys.index(actual.key),
        format_func=lambda k: THEMES[k].nombre,
        key="_selector_tema",
        on_change=_on_change,
        label_visibility="collapsed",
    )
    elegido = THEMES[st.session_state.get("_selector_tema", actual.key)]
    st.markdown(swatches_html(elegido), unsafe_allow_html=True)
    st.caption(elegido.descripcion)
    st.caption("La eleccion se guarda en config/ui_prefs.json.")


# ---------------------------------------------------------------------------
# Estilos de celda (pandas Styler) y colores para Plotly
# ---------------------------------------------------------------------------
def _es_core(nombre: str) -> bool:
    return nombre.lower() == "core"


def _es_satelite(nombre: str) -> bool:
    return nombre.lower() in ("satelite", "satélite")


def clase_badge_categoria(nombre: str, categoria_huerfana: str) -> str:
    if nombre == categoria_huerfana:
        return "badge-muted"
    if _es_core(nombre):
        return "badge-core"
    if _es_satelite(nombre):
        return "badge-satelite"
    return "badge-otra"


def estilo_celda_categoria(t: Theme, categoria, categoria_huerfana: str) -> str:
    if pd.isna(categoria):
        return ""
    nombre = str(categoria).strip()
    if nombre == categoria_huerfana:
        c, a = t.cat_muted, 0.12
    elif _es_core(nombre):
        c, a = t.cat_core, 0.14
    elif _es_satelite(nombre):
        c, a = t.cat_satelite, 0.14
    else:
        c, a = t.cat_otra, 0.14
    return f"background-color: {rgba(c, a)}; color: {c};"


def estilo_estado_banda(t: Theme, estado) -> str:
    if estado == "Sobreponderado":
        return f"background-color: {rgba(t.negative, 0.14)}; color: {t.negative};"
    if estado == "Subponderado":
        return f"background-color: {rgba(t.positive, 0.14)}; color: {t.positive};"
    return f"background-color: {rgba(t.cat_muted, 0.10)}; color: {t.text_muted};"


def estilo_deficit(t: Theme, v) -> str:
    if pd.isna(v):
        return ""
    if v > 0:
        return f"background-color: {rgba(t.positive, 0.14)}; color: {t.positive};"
    return f"background-color: {rgba(t.cat_muted, 0.10)}; color: {t.text_muted};"


def color_por_ticker(t: Theme, tickers: List[str]) -> Dict[str, str]:
    pal = t.chart_palette
    return {tk: pal[i % len(pal)] for i, tk in enumerate(tickers)}


def plotly_base(t: Theme, **overrides) -> dict:
    """Layout base de Plotly para el tema: fondo transparente (lo pone la
    tarjeta), tipografia y colores de texto/grilla del tema."""
    layout = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=t.text, family=t.font_body.stack_css("sans-serif").replace("'", "")),
        hoverlabel=dict(
            bgcolor=t.surface_2,
            bordercolor=t.border_strong,
            font=dict(color=t.text, family=t.font_num.familia),
        ),
    )
    layout.update(overrides)
    return layout
