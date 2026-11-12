# Packaged Python engine

`python desktop/scripts/build_engine.py` puts the standalone engine
(`ipt-engine.exe` + `_internal/`) in this folder, and `npm run tauri build`
includes it in the installer so users don't need Python.

If this folder only has this file, the app runs the engine from source with
Python instead (that's always the case in `npm run tauri dev`).
