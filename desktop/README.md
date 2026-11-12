# Investment Portfolio Tracker — desktop app

Native Windows app built with **Tauri + React**. It reuses the same Python
engine (`core/`) as the Streamlit version, without duplicating calculations.
Setup, data loading and build instructions are in the main
[README](../README.md) ([español](../README.es.md)).

```
desktop/
  backend/server.py   Local API (FastAPI) on top of core/ — 127.0.0.1:8765
  app/                Interface: React + TypeScript (Vite)
  app/src/i18n/       English / Spanish translations (the Spanish text is the key)
  app/src-tauri/      Native window (Rust). Starts and stops the Python engine
  scripts/            build_engine.py: packages the Python engine for the installer
```

## Development

```bash
cd desktop/app
npm install
npm run tauri dev
```

The window opens, Python starts in the background, and the interface reloads
when you edit `src/`. Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `IPT_PYTHON` | `py -3` | Python interpreter that runs the engine |
| `IPT_REPO` | auto-detected | Path to the project folder |

The engine's log is written to `%TEMP%\investment-portfolio-tracker-backend.log`.

## Release builds

`npm run tauri build` includes the packaged engine from
`app/src-tauri/engine-dist/ipt-engine/` (build it first with
`py -3 desktop/scripts/build_engine.py`). The installed app runs that engine
instead of Python, stores user data in `Documents\Investment Portfolio Tracker`
(override with `IPT_DATA_ROOT`) and market-data cache in its local app data
folder. Without a packaged engine, a release build falls back to running the
engine from source with Python, like `tauri dev` always does.

## Adding a translation

Interface text is written in Spanish in the code and wrapped in `t("...")`.
Add the English version to `app/src/i18n/en.ts` using the Spanish text as the
key. Messages produced by the Python engine (warnings, validation errors) are
matched in `app/src/i18n/mensajes.ts`.
