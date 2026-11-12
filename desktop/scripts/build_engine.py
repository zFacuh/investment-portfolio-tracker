"""
Empaqueta el motor en Python (desktop/backend/server.py + core/) como un
programa independiente con PyInstaller, para que el instalador de la app de
escritorio no necesite Python en la PC de quien lo usa.

Uso (con un Python que tenga los requisitos del motor y pyinstaller):
    python desktop/scripts/build_engine.py

Deja el resultado en desktop/app/src-tauri/engine-dist/ipt-engine/, que
`npm run tauri build` incluye en el instalador (ver tauri.conf.json).
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BACKEND = RAIZ / "desktop" / "backend"
SALIDA = RAIZ / "desktop" / "app" / "src-tauri" / "engine-dist"
TRABAJO = Path(tempfile.gettempdir()) / "ipt-pyinstaller"
SEP = os.pathsep  # ";" en Windows

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--clean", "--onedir",
    "--name", "ipt-engine",
    "--paths", str(RAIZ),
    "--paths", str(BACKEND),
    # Archivos que vienen con la app (se leen desde CODE_ROOT, ver core/rutas.py)
    "--add-data", f"{RAIZ / 'config' / 'portfolio_config.example.json'}{SEP}config",
    "--add-data", f"{RAIZ / 'data' / 'demo'}{SEP}data/demo",
    # Modulos que se cargan de forma dinamica
    "--collect-submodules", "uvicorn",
    "--collect-all", "curl_cffi",
    "--collect-submodules", "core",
    "--hidden-import", "rendimiento",
    "--hidden-import", "riesgo",
    "--hidden-import", "aportes",
    "--hidden-import", "metas_diario",
    # Lo que no usa el motor (achica el paquete)
    "--exclude-module", "streamlit",
    "--exclude-module", "plotly",
    "--exclude-module", "matplotlib",
    "--exclude-module", "tkinter",
    "--exclude-module", "pytest",
    "--distpath", str(SALIDA),
    "--workpath", str(TRABAJO / "work"),
    "--specpath", str(TRABAJO),
    str(BACKEND / "server.py"),
]
print(" ".join(cmd))
sys.exit(subprocess.call(cmd, cwd=RAIZ))
