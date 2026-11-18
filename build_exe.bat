@echo off
rem Builds dist\offconv.exe, a single file that needs no Python installed.
rem Run this on Windows from the project folder.

python -m pip install --upgrade pip
python -m pip install -e ".[heic,dev]"
python -m PyInstaller --onefile --console --name offconv --paths src ^
    --collect-all pillow_heif --clean --noconfirm run.py

echo.
echo Done. Your file is dist\offconv.exe
