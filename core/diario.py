"""
core/diario.py -- Diario de decisiones (v10.2)

Cada vez que tomas una decision FUERA del DCA (comprar algo nuevo,
vender, mantener contra tu impulso) la anotas con el por que. El diario
guarda el precio del activo, el de SPY y el CCL de ese dia, y despues
mide en dolares como salio la decision CONTRA el indice:

  - Compra / Mantener: acertaste si el activo rindio MAS que SPY desde ese dia.
  - Venta: acertaste si el activo rindio MENOS que SPY desde que lo vendiste
    (vender algo que despues le gano al indice te costo rendimiento).

El objetivo no es el numero en si, sino aprender de tus propios patrones:
con el tiempo ves que tipo de decisiones te salen bien y cuales no.
Se guarda en data/diario.json.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
from core.rutas import DATA_DIR  # noqa: E402

DIARIO_PATH = DATA_DIR / "diario.json"
ACCIONES = ["Compra", "Venta", "Mantener"]
REFERENCIA = "SPY"


class DiarioError(Exception):
    """Entrada invalida o archivo del diario corrupto."""


def cargar_diario(path: Path = DIARIO_PATH) -> List[Dict[str, Any]]:
    if not Path(path).exists():
        return []
    try:
        datos = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise DiarioError(f"No se pudo leer {Path(path).name}: {e}") from e
    if not isinstance(datos, list):
        raise DiarioError(f"{Path(path).name} no tiene el formato esperado (una lista de decisiones).")
    return datos


def guardar_diario(entradas: List[Dict[str, Any]], path: Path = DIARIO_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(entradas, indent=2, ensure_ascii=False), encoding="utf-8")


def nueva_entrada(
    ticker: str,
    accion: str,
    motivo: str,
    precio_ars: float,
    precio_ref_ars: float,
    ccl: float,
    horizonte_meses: int = 12,
    fecha: Optional[date] = None,
) -> Dict[str, Any]:
    """Arma (y valida) una entrada. Los precios son los de HOY, en ARS."""
    ticker = str(ticker or "").strip().upper()
    motivo = str(motivo or "").strip()
    if not ticker:
        raise DiarioError("Falta el ticker.")
    if accion not in ACCIONES:
        raise DiarioError(f"La accion tiene que ser una de: {', '.join(ACCIONES)}.")
    if len(motivo) < 10:
        raise DiarioError("Escribi el motivo con un poco mas de detalle (es lo mas valioso del diario).")
    for nombre, v in (("precio del activo", precio_ars), (f"precio de {REFERENCIA}", precio_ref_ars), ("CCL", ccl)):
        if v is None or pd.isna(v) or float(v) <= 0:
            raise DiarioError(f"Falta el {nombre} de hoy para poder medir la decision mas adelante.")
    if not 1 <= int(horizonte_meses) <= 120:
        raise DiarioError("El horizonte tiene que estar entre 1 y 120 meses.")
    return {
        "id": uuid.uuid4().hex[:8],
        "fecha": (fecha or date.today()).isoformat(),
        "ticker": ticker,
        "accion": accion,
        "motivo": motivo,
        "horizonte_meses": int(horizonte_meses),
        "precio_ars": float(precio_ars),
        "precio_ref_ars": float(precio_ref_ars),
        "ccl": float(ccl),
    }


def eliminar_entrada(entradas: List[Dict[str, Any]], id_entrada: str) -> List[Dict[str, Any]]:
    return [e for e in entradas if e.get("id") != id_entrada]


def evaluar_diario(
    entradas: List[Dict[str, Any]],
    precios_hoy_ars: Dict[str, float],
    precio_ref_hoy_ars: float,
    ccl_hoy: float,
    hoy: Optional[date] = None,
) -> pd.DataFrame:
    """Una fila por decision con su resultado en USD contra SPY.
    `precios_hoy_ars`: ticker -> precio actual en ARS (los que falten
    quedan sin evaluar)."""
    hoy = hoy or date.today()
    filas = []
    for e in entradas:
        p_hoy = precios_hoy_ars.get(e["ticker"])
        dias = (hoy - date.fromisoformat(e["fecha"])).days
        fila = {
            "id": e["id"], "Fecha": e["fecha"], "Ticker": e["ticker"], "Accion": e["accion"], "Motivo": e["motivo"],
            "Dias": dias, "Activo USD %": None, f"{REFERENCIA} USD %": None, "Diferencia pp": None,
            "Resultado": "Sin precio", "Revisar": dias >= e.get("horizonte_meses", 12) * 30,
        }
        if p_hoy and p_hoy > 0 and precio_ref_hoy_ars and ccl_hoy:
            r_act = (p_hoy / ccl_hoy) / (e["precio_ars"] / e["ccl"]) - 1
            r_ref = (precio_ref_hoy_ars / ccl_hoy) / (e["precio_ref_ars"] / e["ccl"]) - 1
            dif = (r_act - r_ref) * 100
            acierto = dif < 0 if e["accion"] == "Venta" else dif > 0
            fila.update({
                "Activo USD %": r_act * 100, f"{REFERENCIA} USD %": r_ref * 100, "Diferencia pp": dif,
                "Resultado": ("Muy pronto" if dias < 30 else ("Acierto" if acierto else "Error")),
            })
        filas.append(fila)
    cols = ["id", "Fecha", "Ticker", "Accion", "Motivo", "Dias", "Activo USD %", f"{REFERENCIA} USD %",
            "Diferencia pp", "Resultado", "Revisar"]
    return pd.DataFrame(filas, columns=cols).sort_values("Fecha", ascending=False).reset_index(drop=True)
