@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 descargar_datasets.py --basicos
if errorlevel 1 (
    echo.
    echo Si no funciona "py", prueba "python descargar_datasets.py --basicos"
    echo Revisa conexion y errores anteriores.
)
pause
