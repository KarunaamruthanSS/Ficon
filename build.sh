#!/usr/bin/env sh
# Builds dist/offconv, a single file for Linux that needs no Python installed.
# The document libraries make this big: expect a few hundred MB.
set -e

python3 -m pip install -e ".[heic,docs,dev]"
python3 -m PyInstaller --onefile --console --name offconv --paths src \
    --collect-all pillow_heif --collect-all pymupdf --collect-all pdf2docx \
    --clean --noconfirm run.py

echo
echo "Done. Your file is dist/offconv"
