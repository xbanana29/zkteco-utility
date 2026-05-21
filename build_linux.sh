#!/bin/bash
# build_linux.sh — Build Linux binary
echo "============================================"
echo " ZKTeco Utility — Linux Build Script"
echo "============================================"

echo "[1/3] Install dependencies..."
pip install pyzk openpyxl pyinstaller --quiet

echo "[2/3] Build binary..."
pyinstaller --onefile --windowed \
  --name "ZKTeco_Utility_Linux" \
  --collect-all openpyxl \
  --collect-all zk \
  --hidden-import openpyxl \
  --hidden-import openpyxl.styles \
  --hidden-import openpyxl.utils \
  --hidden-import openpyxl.worksheet \
  --hidden-import openpyxl.formatting \
  --hidden-import zk \
  --exclude-module pandas \
  --exclude-module numpy \
  --exclude-module matplotlib \
  --exclude-module PIL \
  --exclude-module pytest \
  --exclude-module unittest \
  zkteco_app.py

echo "[3/3] Done!"
echo ""
echo "Binary: dist/ZKTeco_Utility_Linux"
echo "Jalankan: chmod +x dist/ZKTeco_Utility_Linux && ./dist/ZKTeco_Utility_Linux"
