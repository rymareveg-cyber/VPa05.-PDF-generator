import os
import sys
import json
import platform
import argparse
import webbrowser
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

# Optional pandas import for CSV parsing; fallback to csv module if not available
try:
    import pandas as pd  # type: ignore
except Exception:
    pd = None  # type: ignore

import csv

from jinja2 import Template


PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
OUTPUT_DIR = PROJECT_ROOT / "output"
ASSETS_FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"


def ensure_directories() -> None:
    for d in [DATA_DIR, TEMPLATES_DIR, OUTPUT_DIR, ASSETS_FONTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def list_data_files() -> List[Path]:
    if not DATA_DIR.exists():
        return []
    return sorted([p for p in DATA_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".csv", ".json"}])


def list_template_files() -> List[Path]:
    if not TEMPLATES_DIR.exists():
        return []
    return sorted([p for p in TEMPLATES_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".html", ".htm"}])


def detect_template_candidates(data_path: Path, records: List[Dict[str, Any]], all_templates: List[Path]) -> List[Path]:
    name = data_path.name.lower()
    tnames = {p.name.lower(): p for p in all_templates}

    # Rules by filename first
    if "invoice" in name and "invoice_simple.html" in tnames:
        return [tnames["invoice_simple.html"]]
    if "order" in name and "order_detailed.html" in tnames:
        return [tnames["order_detailed.html"]]
    if "product" in name and "product_catalog.html" in tnames:
        return [tnames["product_catalog.html"]]

    # Heuristic by data shape
    keys: set[str] = set()
    for r in records:
        if isinstance(r, dict):
            keys.update(r.keys())
    candidates: List[Path] = []
    if {"item_name", "qty", "price"}.issubset(keys) and "invoice_simple.html" in tnames:
        candidates.append(tnames["invoice_simple.html"])
    if {"product_id", "name", "unit"}.issubset(keys) and "product_catalog.html" in tnames:
        candidates.append(tnames["product_catalog.html"])
    # orders style: record has items list
    if any(isinstance(r.get("items"), list) for r in records) and "order_detailed.html" in tnames:
        candidates.append(tnames["order_detailed.html"])
    return candidates or all_templates


def template_requires_invoice_id(template_name: str) -> bool:
    ln = template_name.lower()
    if ln == "product_catalog.html":
        return False
    return True


def print_numbered(title: str, items: List[str]) -> None:
    print(f"\n{title}")
    for idx, item in enumerate(items, start=1):
        print(f"  {idx}. {item}")


def choose_index(prompt_text: str, total: int) -> int:
    while True:
        choice = input(f"{prompt_text} (1-{total}): ").strip()
        if not choice.isdigit():
            print("Введите номер из списка.")
            continue
        idx = int(choice)
        if 1 <= idx <= total:
            return idx - 1
        print("Неверный номер. Попробуйте снова.")


def load_csv(path: Path) -> List[Dict[str, Any]]:
    # Use pandas if available; else fallback to csv module
    if pd is not None:
        df = pd.read_csv(path)
        return df.to_dict(orient="records")
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(dict(row))
    return records


def load_json(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # Normalize to list[dict]
    if isinstance(data, dict):
        # If dict of id->record, convert to list
        if all(isinstance(v, dict) for v in data.values()):
            out: List[Dict[str, Any]] = []
            for k, v in data.items():
                rec = dict(v)
                if "invoice_id" not in rec:
                    rec["invoice_id"] = k
                out.append(rec)
            return out
        else:
            return [data]
    if isinstance(data, list):
        return [r if isinstance(r, dict) else {"value": r} for r in data]
    return [{"value": data}]


def load_data_file(path: Path) -> List[Dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        return load_csv(path)
    if path.suffix.lower() == ".json":
        return load_json(path)
    return []


def detect_invoice_field(records: List[Dict[str, Any]]) -> Optional[str]:
    if not records:
        return None
    key_counts: Dict[str, int] = {}
    for rec in records:
        for k in rec.keys():
            key_counts[k] = key_counts.get(k, 0) + 1

    keys = list(key_counts.keys())
    normalized = {k: k.lower().replace(" ", "").replace("-", "").replace("_", "") for k in keys}

    candidates_priority = [
        "invoiceid",
        "invoice_id",
        "invoice",
        "inv_id",
        "id",
    ]

    for cand in candidates_priority:
        for k, norm in normalized.items():
            if norm == cand.replace("_", ""):
                return k

    contains_candidates = []
    for k, norm in normalized.items():
        if "invoice" in norm and ("id" in norm or norm.endswith("no") or norm.endswith("number")):
            contains_candidates.append(k)
    if contains_candidates:
        contains_candidates.sort(key=lambda kk: (-key_counts.get(kk, 0), len(kk)))
        return contains_candidates[0]

    for k, norm in normalized.items():
        if norm == "id":
            return k
    return None


def choose_field_from_user(records: List[Dict[str, Any]]) -> Optional[str]:
    keys: List[str] = []
    for rec in records:
        for k in rec.keys():
            if k not in keys:
                keys.append(k)
    if not keys:
        return None
    print_numbered("Выберите поле, которое соответствует invoice id:", keys)
    idx = choose_index("Поле", len(keys))
    return keys[idx]


def get_unique_invoice_ids(records: List[Dict[str, Any]], field: str) -> List[str]:
    values: List[str] = []
    seen = set()
    for rec in records:
        val = rec.get(field, None)
        if val is None:
            continue
        sval = str(val)
        if sval not in seen:
            seen.add(sval)
            values.append(sval)
    return values


def filter_records_by_invoice(records: List[Dict[str, Any]], field: str, invoice_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for rec in records:
        if str(rec.get(field, "")) == str(invoice_id):
            out.append(rec)
    return out


def read_template(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_font_css(font_file: Optional[Path]) -> str:
    if font_file and font_file.exists():
        font_url = font_file.as_uri()
        return (
            """
@font-face {
  font-family: 'AppCyrillic';
  src: url('%s');
  font-weight: normal;
  font-style: normal;
}
html, body { font-family: 'AppCyrillic', 'DejaVu Sans', 'Roboto', 'Arial', 'Segoe UI', sans-serif; }
            """
            % font_url
        )
    return "html, body { font-family: 'DejaVu Sans', 'Roboto', 'Arial', 'Segoe UI', sans-serif; }"


def find_font_file() -> Optional[Path]:
    local_dejavu = ASSETS_FONTS_DIR / "DejaVuSans.ttf"
    if local_dejavu.exists():
        return local_dejavu
    local_roboto = ASSETS_FONTS_DIR / "Roboto-Regular.ttf"
    if local_roboto.exists():
        return local_roboto
    system = platform.system().lower()
    candidates: List[Path] = []
    if system == "windows":
        win_dir = Path(os.environ.get("WINDIR", r"C:\\Windows")) / "Fonts"
        candidates += [
            win_dir / "DejaVuSans.ttf",
            win_dir / "Roboto-Regular.ttf",
            win_dir / "arial.ttf",
            win_dir / "segoeui.ttf",
        ]
    elif system == "darwin":
        candidates += [
            Path("/System/Library/Fonts/Supplemental/DejaVuSans.ttf"),
            Path("/Library/Fonts/DejaVuSans.ttf"),
            Path("/Library/Fonts/Roboto-Regular.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        ]
    else:
        candidates += [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/roboto/hinted/Roboto-Regular.ttf"),
            Path.home() / ".local/share/fonts/DejaVuSans.ttf",
        ]
    for c in candidates:
        if c.exists():
            return c
    return None


def render_html(template_str: str, context: Dict[str, Any]) -> str:
    tmpl = Template(template_str)
    return tmpl.render(**context)


def generate_pdf(html_str: str, css_str: str, out_path: Path) -> None:
    # Lazy import to avoid GLib/GIO messages before user selections
    from weasyprint import HTML, CSS  # type: ignore
    out_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_str, base_url=str(PROJECT_ROOT)).write_pdf(
        target=str(out_path), stylesheets=[CSS(string=css_str)]
    )


def open_pdf_in_browser(path: Path) -> None:
    uri = path.resolve().as_uri()
    try:
        opened = webbrowser.open_new_tab(uri)
        if opened:
            return
        system = platform.system().lower()
        if system == "windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif system == "darwin":
            os.system(f"open '{path}'")
        else:
            os.system(f"xdg-open '{path}'")
    except Exception as e:
        print(f"Не удалось автоматически открыть PDF: {e}")


def main() -> None:
    print("PDF Generator (WeasyPrint) — CSV/JSON -> HTML шаблон -> PDF")
    ensure_directories()

    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--data", dest="data_sel", help="Имя или номер файла данных", default=None)
    parser.add_argument("--template", dest="tmpl_sel", help="Имя или номер шаблона", default=None)
    parser.add_argument("--invoice", dest="invoice_sel", help="Значение invoice id", default=None)
    args, _ = parser.parse_known_args()

    data_files = list_data_files()
    template_files = list_template_files()

    if not data_files:
        print(f"\nНет доступных файлов данных в каталоге: {DATA_DIR}")
        print("Поместите .csv или .json файлы в эту директорию и запустите снова.")
        return

    if not template_files:
        print(f"\nНет доступных HTML-шаблонов в каталоге: {TEMPLATES_DIR}")
        print("Поместите .html файлы в эту директорию и запустите снова.")
        return

    print_numbered("Доступные файлы данных:", [p.name for p in data_files])

    def calc_default_idx(items: List[Path], sel: Optional[str]) -> Optional[int]:
        if not sel:
            return None
        if sel.isdigit():
            idx0 = int(sel) - 1
            if 0 <= idx0 < len(items):
                return idx0
        names = [p.name for p in items]
        if sel in names:
            return names.index(sel)
        for i, n in enumerate(names):
            if sel.lower() in n.lower():
                return i
        return None

    def prompt_selection(items: List[Path], prompt_label: str, default_idx: Optional[int]) -> int:
        while True:
            suffix = ""
            if default_idx is not None:
                suffix = f" [Enter={default_idx+1}:{items[default_idx].name}]"
            ans = input(f"{prompt_label} (1-{len(items)}):{suffix} ").strip()
            if ans == "" and default_idx is not None:
                return default_idx
            if ans.isdigit():
                idx0 = int(ans) - 1
                if 0 <= idx0 < len(items):
                    return idx0
            names = [p.name for p in items]
            if ans in names:
                return names.index(ans)
            print("Введите корректный номер или имя файла.")

    data_default = calc_default_idx(data_files, args.data_sel)
    data_idx = prompt_selection(data_files, "Выберите файл данных", data_default)

    data_path = data_files[data_idx]

    print(f"\nЗагружаю данные из: {data_path.name}")
    records = load_data_file(data_path)
    if not records:
        print("Файл данных не содержит записей.")
        return

    # Now choose template based on selected data
    candidates = detect_template_candidates(data_path, records, template_files)
    tmpl_default = calc_default_idx(candidates, args.tmpl_sel)
    print_numbered("Доступные шаблоны для выбранного файла:", [p.name for p in candidates])
    tmpl_idx = prompt_selection(candidates, "Выберите шаблон", tmpl_default)
    template_path = candidates[tmpl_idx]

    requires_invoice = template_requires_invoice_id(template_path.name)
    chosen_invoice: Optional[str] = None
    field: Optional[str] = None
    if requires_invoice:
        field = detect_invoice_field(records)
        if not field:
            field = choose_field_from_user(records)
            if not field:
                print("Не удалось определить поле invoice id.")
                return
        invoice_ids = get_unique_invoice_ids(records, field)
        if not invoice_ids:
            print(f"Не удалось найти значения по полю '{field}'.")
            return

        print_numbered(f"Доступные счета (по полю '{field}'):", invoice_ids)
        default_inv_idx: Optional[int] = None
        if args.invoice_sel and args.invoice_sel in invoice_ids:
            default_inv_idx = invoice_ids.index(args.invoice_sel)
        prompt = "Выберите invoice id"
        while True:
            suffix = ""
            if default_inv_idx is not None:
                suffix = f" [Enter={default_inv_idx+1}:{invoice_ids[default_inv_idx]}]"
            ans = input(f"{prompt} (1-{len(invoice_ids)}):{suffix} ").strip()
            if ans == "" and default_inv_idx is not None:
                chosen_invoice = invoice_ids[default_inv_idx]
                break
            if ans.isdigit():
                idx0 = int(ans) - 1
                if 0 <= idx0 < len(invoice_ids):
                    chosen_invoice = invoice_ids[idx0]
                    break
            if ans in invoice_ids:
                chosen_invoice = ans
                break
            print("Введите корректный номер или значение invoice id.")

    subset = records if not requires_invoice else filter_records_by_invoice(records, field or "", chosen_invoice or "")

    template_str = read_template(template_path)

    # Build rendering context
    context = {
        "records": subset,
        "record": subset[0] if subset else {},
        "all_records": records,
        "invoice_id": chosen_invoice if chosen_invoice is not None else "",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_file": data_path.name,
        "template_file": template_path.name,
    }

    html_str = render_html(template_str, context)

    font_file = find_font_file()
    css_str = build_font_css(font_file)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if requires_invoice:
        safe_invoice = str(chosen_invoice).strip().replace("/", "-").replace("\\", "-")
        out_name = f"invoice_{safe_invoice}_{ts}.pdf"
    else:
        out_name = f"{data_path.stem}_{template_path.stem}_{ts}.pdf"
    out_path = OUTPUT_DIR / out_name

    print(f"\nГенерация PDF: {out_name}")
    generate_pdf(html_str, css_str, out_path)
    print(f"Готово: {out_path}")

    print("Открываю PDF...")
    open_pdf_in_browser(out_path)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОтменено пользователем.")
        sys.exit(130)
    except Exception as exc:
        print(f"Ошибка: {exc}")
        sys.exit(1)


