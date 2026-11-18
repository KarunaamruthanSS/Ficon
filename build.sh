#!/usr/bin/env sh
# Builds dist/offconv, a single file for Linux that needs no Python installed.
set -e

python3 -m pip install -e ".[heic,dev]"
python3 -m PyInstaller --onefile --console --name offconv --paths src \
    --collect-all pillow_heif --clean --noconfirm run.py

echo
echo "Done. Your file is dist/offconv"
