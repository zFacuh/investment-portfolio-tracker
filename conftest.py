"""
conftest.py (raiz del proyecto)

Asegura que `core/` sea importable como paquete al correr pytest desde
cualquier directorio o forma de invocacion (`pytest`, `python -m pytest`,
desde un IDE, etc.) -- sin este archivo, pytest en modo "prepend" inserta
en sys.path el directorio base de cada archivo de test (tests/), no la
raiz del repo, y `from core.rebalancer import ...` fallaria con
ModuleNotFoundError salvo que se invoque puntualmente como
`python -m pytest` desde la raiz.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
