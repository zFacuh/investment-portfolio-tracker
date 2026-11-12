"""
core/rutas.py

Donde vive cada archivo. Hay dos raices:

- CODE_ROOT: la carpeta del codigo. De ahi se leen los archivos que vienen
  con la app y no se modifican (la cartera de ejemplo y los datos de demo).
- DATA_ROOT: la carpeta de los datos del usuario (sus CSV, su configuracion,
  su diario). Corriendo desde el repositorio es la misma carpeta del codigo;
  la app instalada la apunta a Documentos\\Investment Portfolio Tracker con la
  variable de entorno IPT_DATA_ROOT.

La cache de datos de mercado va en data/cache/ salvo que IPT_CACHE_DIR diga
otra cosa (la app instalada la deja fuera de Documentos).
"""

from __future__ import annotations

import os
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ["IPT_DATA_ROOT"]) if os.environ.get("IPT_DATA_ROOT") else CODE_ROOT
CACHE_DIR = Path(os.environ["IPT_CACHE_DIR"]) if os.environ.get("IPT_CACHE_DIR") else DATA_ROOT / "data" / "cache"

# Datos del usuario
CONFIG_DIR = DATA_ROOT / "config"
DATA_DIR = DATA_ROOT / "data"
MOVIMIENTOS_DIR = DATA_DIR / "movimientos"

# Archivos que vienen con la app
EJEMPLO_CONFIG = CODE_ROOT / "config" / "portfolio_config.example.json"
DEMO_DIR = CODE_ROOT / "data" / "demo"
