@echo off
rem Abre la version web (Streamlit) en el navegador.
rem Para usar un Python en particular, cambia "py -3" por la ruta a tu python.exe.
cd /d "%~dp0"
py -3 -m streamlit run app.py
