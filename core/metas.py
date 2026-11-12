"""
core/metas.py

Meta patrimonial y parametros de la proyeccion (v10.0, mejoras E1/E2).
Se guardan en config/metas.json (separado de portfolio_config.json a
proposito: son objetivos PERSONALES, no la estrategia de asignacion, y no
tienen que pasar por El Guardian de la config).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

# Escenarios de la proyeccion: rendimiento anual REAL en dolares (mediana).
# Lo usan la pestana Metas de Streamlit y la app de escritorio.
ESCENARIOS: Dict[str, float] = {
    "Conservador": 0.04,
    "Moderado": 0.07,
    "Optimista": 0.10,
}

from core.rutas import CONFIG_DIR  # noqa: E402

METAS_PATH = CONFIG_DIR / "metas.json"

DEFAULTS: Dict[str, Any] = {
    "meta_usd": None,  # None = sin meta definida
    "fecha_objetivo": None,  # "YYYY-MM-DD" o None
    "aporte_mensual_usd": None,  # None = usar el promedio real de los ultimos 6 meses
    "escenario": "Moderado",
    "horizonte_anios": 10,
    # Efectivo + FCI + otros fuera de acciones en la cuenta (ARS), para la TIR
    # de toda la cuenta (pestana Rendimiento). Antes faltaba aca y por eso
    # "Recordar este monto" no se guardaba.
    "otros_cuenta_ars": None,
}


def cargar_metas(path: Path = METAS_PATH) -> Dict[str, Any]:
    try:
        datos = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(datos, dict):
            raise ValueError
    except (OSError, ValueError, json.JSONDecodeError):
        datos = {}
    return {**DEFAULTS, **{k: v for k, v in datos.items() if k in DEFAULTS}}


def guardar_metas(metas: Dict[str, Any], path: Path = METAS_PATH) -> None:
    datos = {**DEFAULTS, **{k: v for k, v in metas.items() if k in DEFAULTS}}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
