@echo off
rem Builds dist\offconv.exe, a single file that needs no Python installed.
rem Run this on Windows from the project folder.
rem
rem The document libraries make this big: expect about 165MB, or about
rem 105MB if you install "pymupdf<2" first, which drops the ML layout
rem models offconv does not use. PyMuPDF 1.x does print a deprecation
rem notice of its own on every run, which 2.x does not.

python -m pip install --upgrade pip
python -m pip install -e ".[heic,docs,dev]"
python -m PyInstaller --onefile --console --name offconv --paths src ^
    --collect-all pillow_heif --collect-all pymupdf --collect-all pdf2docx ^
    --clean --noconfirm run.py

echo.
echo Done. Your file is dist\offconv.exe
