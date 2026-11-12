"""
core/macro_data.py

Series macro de Argentina necesarias para medir el rendimiento REAL de la
cartera (v10.0 -- mejora A2 del plan):

  - Dolar CCL historico, diario (ARS por USD, punta "venta").
  - Inflacion mensual (IPC INDEC, % mensual).

Por que hacen falta: la cartera se valua en pesos, y en Argentina un
rendimiento nominal en ARS puede ser una perdida real. Con el CCL
historico se convierte la curva a USD (lo que ganaste "en dolares"), y con
el IPC se deflacta a pesos constantes (lo que ganaste por encima de la
inflacion).

Fuente: api.argentinadatos.com (publica, gratuita, sin API key):
  - /v1/cotizaciones/dolares/contadoconliqui -> [{fecha, compra, venta}]
  - /v1/finanzas/indices/inflacion            -> [{fecha (fin de mes), valor (% mensual)}]

Robustez:
  - Cada descarga exitosa se guarda en data/cache/*.json. Si la API no
    responde (sin internet, caida), se usa la ultima copia guardada, con
    una advertencia. Si no hay ni API ni copia, se lanza MacroDataError y
    la UI desactiva solo las vistas en USD/reales (el resto de la app
    sigue funcionando).
  - A proposito NO hay un fallback que estime el CCL con un ratio de
    CEDEAR hardcodeado (mismo criterio que core/market_data.py: un ratio
    viejo da un numero incorrecto en silencio).

Supuestos documentados:
  - El IPC del mes en curso todavia no se publico: para los dias
    posteriores al ultimo dato se extrapola con la inflacion del ultimo
    mes publicado (`indice_ipc_diario` devuelve tambien la fecha desde la
    que el valor es estimado, para mostrarlo en la UI).
  - Dentro de un mes el indice se interpola geometricamente (inflacion
    "pareja" dia a dia), el estandar para llevar un IPC mensual a diario.

Agnostico de Streamlit (el cacheo en memoria vive en app.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from core.market_data import HTTP_TIMEOUT

URL_CCL_HISTORICO = "https://api.argentinadatos.com/v1/cotizaciones/dolares/contadoconliqui"
URL_INFLACION = "https://api.argentinadatos.com/v1/finanzas/indices/inflacion"

from core.rutas import CACHE_DIR  # noqa: E402
CACHE_CCL = CACHE_DIR / "ccl_historico.json"
CACHE_IPC = CACHE_DIR / "inflacion_mensual.json"


class MacroDataError(Exception):
    """No hay datos macro disponibles (ni API ni copia local)."""


@dataclass
class SerieMacro:
    serie: pd.Series
    advertencias: List[str]


# ---------------------------------------------------------------------------
# Descarga con cache en disco
# ---------------------------------------------------------------------------
def _descargar_json_con_cache(url: str, cache_path: Path, nombre: str) -> Tuple[list, List[str]]:
    advertencias: List[str] = []
    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT * 2)
        resp.raise_for_status()
        datos = resp.json()
        if not isinstance(datos, list) or not datos:
            raise ValueError("respuesta vacia o con formato inesperado")
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(datos), encoding="utf-8")
        except OSError:
            pass  # no poder guardar la copia no impide usar el dato
        return datos, advertencias
    except Exception as e:
        if cache_path.exists():
            try:
                datos = json.loads(cache_path.read_text(encoding="utf-8"))
                advertencias.append(
                    f"No se pudo actualizar {nombre} ({e}); se usa la ultima copia guardada localmente."
                )
                return datos, advertencias
            except (OSError, json.JSONDecodeError):
                pass
        raise MacroDataError(f"No hay datos de {nombre}: la API no respondio ({e}) y no hay copia local.")


def get_ccl_historico() -> SerieMacro:
    """Serie diaria (index = fecha naive, incluye fines de semana si la
    fuente los trae) del CCL "venta" en ARS por USD."""
    datos, advertencias = _descargar_json_con_cache(URL_CCL_HISTORICO, CACHE_CCL, "el dolar CCL historico")
    df = pd.DataFrame(datos)
    if "fecha" not in df.columns or "venta" not in df.columns:
        raise MacroDataError("El CCL historico vino con un formato inesperado.")
    serie = pd.Series(pd.to_numeric(df["venta"], errors="coerce").values, index=pd.to_datetime(df["fecha"]))
    serie = serie[~serie.index.duplicated(keep="last")].dropna().sort_index()
    serie = serie[serie > 0]
    if serie.empty:
        raise MacroDataError("El CCL historico vino vacio.")
    return SerieMacro(serie=serie, advertencias=advertencias)


def get_inflacion_mensual() -> SerieMacro:
    """Serie mensual (index = ultimo dia del mes) de inflacion en %."""
    datos, advertencias = _descargar_json_con_cache(URL_INFLACION, CACHE_IPC, "la inflacion (IPC)")
    df = pd.DataFrame(datos)
    if "fecha" not in df.columns or "valor" not in df.columns:
        raise MacroDataError("La inflacion vino con un formato inesperado.")
    serie = pd.Series(pd.to_numeric(df["valor"], errors="coerce").values, index=pd.to_datetime(df["fecha"]))
    serie = serie[~serie.index.duplicated(keep="last")].dropna().sort_index()
    if serie.empty:
        raise MacroDataError("La serie de inflacion vino vacia.")
    return SerieMacro(serie=serie, advertencias=advertencias)


# ---------------------------------------------------------------------------
# Alineacion a un rango diario
# ---------------------------------------------------------------------------
def ccl_diario(ccl: pd.Series, rango: pd.DatetimeIndex) -> pd.Series:
    """CCL alineado a `rango` (dia calendario): forward-fill para fines de
    semana/feriados y backward-fill acotado para el primer dia si la
    serie arrancara despues."""
    base = ccl.sort_index()
    union = base.index.union(rango)
    return base.reindex(union).ffill().bfill().reindex(rango)


def indice_ipc_diario(inflacion_mensual: pd.Series, rango: pd.DatetimeIndex) -> Tuple[pd.Series, Optional[pd.Timestamp]]:
    """
    Indice de precios diario (base arbitraria) para `rango`, a partir de
    la inflacion mensual en %.

    Construccion: cada dato mensual (fecha = fin del mes) se convierte en
    un nivel de indice acumulado (cumprod de 1 + i). Entre fines de mes
    se interpola geometricamente. Para fechas posteriores al ultimo dato
    publicado se extrapola con la ultima inflacion mensual conocida.

    Devuelve (indice, fecha_desde_estimado). fecha_desde_estimado es None
    si todo el rango esta cubierto con datos publicados.
    """
    infl = inflacion_mensual.sort_index()
    niveles = (1 + infl / 100.0).cumprod()
    # Nivel en el fin del mes anterior al primer dato = 1.0
    primer_fin = infl.index[0]
    inicio = (primer_fin - pd.offsets.MonthEnd(1))
    niveles = pd.concat([pd.Series([1.0], index=[inicio]), niveles])

    ultimo_fin = niveles.index[-1]
    fecha_estimado: Optional[pd.Timestamp] = None
    fin_rango = rango.max()
    if fin_rango > ultimo_fin:
        fecha_estimado = ultimo_fin + pd.Timedelta(days=1)
        tasa_diaria = (1 + infl.iloc[-1] / 100.0) ** (1 / 30.4375)
        dias_extra = (fin_rango - ultimo_fin).days
        niveles = pd.concat(
            [niveles, pd.Series([niveles.iloc[-1] * tasa_diaria**dias_extra], index=[fin_rango])]
        )

    # Interpolacion geometrica = lineal en log
    log_niv = pd.Series(np.log(niveles.values), index=niveles.index)
    union = log_niv.index.union(rango)
    interp = log_niv.reindex(union).interpolate(method="time").ffill().bfill()
    indice = pd.Series(np.exp(interp.reindex(rango).values), index=rango)
    return indice, fecha_estimado
