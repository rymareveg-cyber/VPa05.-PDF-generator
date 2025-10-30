VPa05 PDF Generator

Коротко
- Генерация PDF из CSV/JSON через HTML-шаблоны (Jinja2) и WeasyPrint.
- Поддержка кириллицы (рекомендуется TTF в `assets/fonts/`).
- Кроссплатформенно (Windows/macOS/Linux). На Windows нужен GTK Runtime для WeasyPrint.

Требования
- Python 3.10+
- Windows: установлен GTK3 Runtime (`C:\Program Files\GTK3-Runtime Win64\bin` в PATH). См. релизы: https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases

Установка и запуск (быстро)
```powershell
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt

# (опционально для Windows) добавить GTK в PATH текущей сессии
$gtk = 'C:\\Program Files\\GTK3-Runtime Win64\\bin'; if (Test-Path $gtk) { $env:Path = "$gtk;$env:Path" }

./.venv/Scripts/python .\main.py
```

CLI-аргументы (необязательно)
```powershell
./.venv/Scripts/python .\main.py --data invoices.csv --template invoice_simple.html --invoice INV-1001
```

Данные и шаблоны
- `data/invoices.csv` → `templates/invoice_simple.html` (требует выбор invoice id)
- `data/orders.json`  → `templates/order_detailed.html` (требует invoice id)
- `data/products.csv` → `templates/product_catalog.html` (без invoice id)

Вывод
- PDF сохраняются в `output/` и автоматически открываются в браузере.
- Именование:
  - счета/заказы: `invoice_<id>_<YYYYMMDD_HHMMSS>.pdf`
  - каталоги/прочее: `<data>_<template>_<YYYYMMDD_HHMMSS>.pdf`

Шрифты
- Для гарантии кириллицы положите `DejaVuSans.ttf` или `Roboto-Regular.ttf` в `assets/fonts/`.


