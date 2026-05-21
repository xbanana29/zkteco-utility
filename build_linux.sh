#!/bin/bash
echo "============================================"
echo " ZKTeco Utility — Linux Build"
echo "============================================"

pip install pyzk openpyxl pyinstaller --quiet

pyinstaller --onefile --windowed \
  --name "ZKTeco_Utility_Linux" \
  --add-data "app_icon.png:." \
  --add-data "i18n.py:." \
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

echo "Done: dist/ZKTeco_Utility_Linux"
echo "Run: chmod +x dist/ZKTeco_Utility_Linux && ./dist/ZKTeco_Utility_Linux"
