#!/usr/bin/env python3
"""
Сборщик дневных данных доходности.

Источники:
  - Фонд ОПИФ «Матрёшка а-ля Рус» (Альфа-Капитал): стоимость пая и СЧА.
    Данные встроены в страницу как JSON в window.__SERVER_STATE__.navData.
    Публичного API на полную историю нет, поэтому берём встроенное окно
    (последние ~60 дней). При ежедневном запуске это окно перекрывает любые
    пропуски, а апсерт по дате исключает дубли.
  - Индекс МосБиржи полной доходности MCFTR: открытый ISS API (iss.moex.com),
    без ключей, с постраничной историей.

Всё складывается в SQLite. Запуск ежедневно (cron/launchd) — см. README.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import socket
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "matryoshka.db"

FUND_URL = "https://www.alfacapital.ru/disclosure/pifs/opif-matryoshka/cost"
FUND_MIN_DATE = "2025-04-21"  # navMinDate — начало жизни фонда, граница бэкфилла индекса
INDEX_SECID = "MCFTR"         # Индекс МосБиржи полной доходности «брутто»
MOEX_URL = (
    "https://iss.moex.com/iss/history/engines/stock/markets/index/"
    "securities/{secid}.json"
)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) matryoshka-tracker/1.0"

# Ретраи при сетевых сбоях (напр. кратковременный отвал DNS/интернета).
# Настраиваются флагами --retries / --retry-delay в main().
RETRY_ATTEMPTS = 3        # всего попыток
RETRY_DELAY = 300         # пауза между попытками, сек (5 минут)

# Ошибки, которые имеет смысл повторять (сеть/DNS/таймаут).
NET_ERRORS = (urllib.error.URLError, socket.gaierror, socket.timeout,
              TimeoutError, ConnectionError)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def http_get(url: str, timeout: int = 30) -> bytes:
    last = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except NET_ERRORS as e:
            last = e
            if attempt < RETRY_ATTEMPTS:
                mins = RETRY_DELAY // 60
                print(f"[сеть]   попытка {attempt}/{RETRY_ATTEMPTS} не удалась "
                      f"({e}); пауза {mins} мин перед повтором…", file=sys.stderr)
                time.sleep(RETRY_DELAY)
    raise last


# --------------------------------------------------------------------------- #
# База
# --------------------------------------------------------------------------- #
def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS fund (
            date       TEXT PRIMARY KEY,   -- YYYY-MM-DD
            share_cost REAL NOT NULL,      -- стоимость пая, ₽
            nav        REAL                -- СЧА, ₽
        );
        CREATE TABLE IF NOT EXISTS index_value (
            secid TEXT NOT NULL,
            date  TEXT NOT NULL,           -- YYYY-MM-DD
            close REAL NOT NULL,
            PRIMARY KEY (secid, date)
        );
        """
    )
    conn.commit()


def upsert_fund(conn: sqlite3.Connection, rows: list[dict]) -> int:
    cur = conn.executemany(
        """
        INSERT INTO fund (date, share_cost, nav) VALUES (:date, :share_cost, :nav)
        ON CONFLICT(date) DO UPDATE SET
            share_cost = excluded.share_cost,
            nav        = excluded.nav
        """,
        rows,
    )
    conn.commit()
    return cur.rowcount if cur.rowcount != -1 else len(rows)


def upsert_index(conn: sqlite3.Connection, secid: str, rows: list[tuple]) -> int:
    conn.executemany(
        """
        INSERT INTO index_value (secid, date, close) VALUES (?, ?, ?)
        ON CONFLICT(secid, date) DO UPDATE SET close = excluded.close
        """,
        [(secid, d, c) for d, c in rows],
    )
    conn.commit()
    return len(rows)


def max_date(conn: sqlite3.Connection, table: str, where: str = "") -> str | None:
    row = conn.execute(f"SELECT MAX(date) FROM {table} {where}").fetchone()
    return row[0] if row and row[0] else None


# --------------------------------------------------------------------------- #
# Фонд
# --------------------------------------------------------------------------- #
def extract_server_state(html: str) -> dict:
    """Достаёт JSON-объект из `window.__SERVER_STATE__ = {...};`."""
    m = re.search(r"window\.__SERVER_STATE__\s*=\s*(\{)", html)
    if not m:
        raise ValueError("не найден window.__SERVER_STATE__ на странице")
    start = m.start(1)
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(html[start : i + 1])
    raise ValueError("не удалось сбалансировать скобки __SERVER_STATE__")


def find_key(obj, key):
    """Рекурсивно ищет первое значение по ключу в дереве dict/list."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find_key(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, key)
            if r is not None:
                return r
    return None


def collect_fund(conn: sqlite3.Connection) -> int:
    html = http_get(FUND_URL).decode("utf-8", "replace")
    state = extract_server_state(html)
    nav_data = find_key(state, "navData")
    if not nav_data:
        raise ValueError("navData пуст или не найден")
    rows = [
        {
            "date": r["date"],
            "share_cost": float(r["shareCost"]),
            "nav": float(r["netAssetValue"]) if r.get("netAssetValue") is not None else None,
        }
        for r in nav_data
        if r.get("date") and r.get("shareCost") is not None
    ]
    n = upsert_fund(conn, rows)
    span = f"{min(r['date'] for r in rows)}..{max(r['date'] for r in rows)}"
    print(f"[фонд]   собрано строк: {len(rows)} ({span})")
    return n


# --------------------------------------------------------------------------- #
# Разовый импорт полной истории фонда (выгрузка с investfunds.ru)
# --------------------------------------------------------------------------- #
_XL_EPOCH = datetime(1899, 12, 30)  # база серийных дат Excel (учёт бага 1900 года)


def _excel_serial_to_iso(n: float) -> str:
    return (_XL_EPOCH + timedelta(days=int(round(n)))).date().isoformat()


def _parse_date_cell(raw: str) -> str:
    """Дата из ячейки: Excel-серийник (46224) либо строка ДД.ММ.ГГГГ / ISO."""
    raw = str(raw).strip()
    if re.fullmatch(r"\d+(\.\d+)?", raw):
        return _excel_serial_to_iso(float(raw))
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"не распознал дату: {raw!r}")


def _num(raw) -> float | None:
    if raw is None or str(raw).strip() in ("", "-", "н/д", "n/a"):
        return None
    return float(str(raw).replace("\xa0", "").replace(" ", "").replace(",", "."))


def read_fund_xlsx(path: str) -> list[dict]:
    """Читает выгрузку .xlsx (колонки Дата / Пай / СЧА) стандартной библиотекой."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as z:
        sst: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            sst = ["".join(t.text or "" for t in si.iter(f"{ns}t"))
                   for si in root.findall(f"{ns}si")]
        sheet = min(n for n in z.namelist()
                    if re.match(r"xl/worksheets/sheet\d+\.xml", n))
        root = ET.fromstring(z.read(sheet))

    def col(ref: str) -> str:
        return re.match(r"[A-Z]+", ref).group(0)

    rows: list[dict] = []
    for i, row in enumerate(root.findall(f".//{ns}row")):
        cells: dict[str, str] = {}
        for c in row.findall(f"{ns}c"):
            v = c.find(f"{ns}v")
            if v is None:
                continue
            val = v.text
            if c.get("t") == "s":
                val = sst[int(val)]
            cells[col(c.get("r"))] = val
        if i == 0:  # заголовок
            continue
        if "A" not in cells or "B" not in cells:
            continue
        rows.append({
            "date": _parse_date_cell(cells["A"]),
            "share_cost": _num(cells["B"]),
            "nav": _num(cells.get("C")),
        })
    return [r for r in rows if r["share_cost"] is not None]


def read_fund_csv(path: str) -> list[dict]:
    """CSV-фолбэк: колонки Дата, Пай, СЧА (разделитель ,/;, авто)."""
    text = Path(path).read_text(encoding="utf-8-sig")
    delim = ";" if text.count(";") > text.count(",") else ","
    reader = csv.reader(text.splitlines(), delimiter=delim)
    rows: list[dict] = []
    for i, r in enumerate(reader):
        if i == 0 or len(r) < 2:
            continue
        rows.append({
            "date": _parse_date_cell(r[0]),
            "share_cost": _num(r[1]),
            "nav": _num(r[2]) if len(r) > 2 else None,
        })
    return [r for r in rows if r["share_cost"] is not None]


def import_fund_file(conn: sqlite3.Connection, path: str) -> int:
    rows = (read_fund_xlsx(path) if path.lower().endswith((".xlsx", ".xlsm"))
            else read_fund_csv(path))
    if not rows:
        raise ValueError("в файле не найдено строк с данными")
    upsert_fund(conn, rows)
    span = f"{min(r['date'] for r in rows)}..{max(r['date'] for r in rows)}"
    print(f"[импорт] из {Path(path).name}: {len(rows)} строк ({span})")
    return len(rows)


# --------------------------------------------------------------------------- #
# Индекс (MOEX ISS)
# --------------------------------------------------------------------------- #
def collect_index(conn: sqlite3.Connection, secid: str, since: str) -> int:
    till = date.today().isoformat()
    total: list[tuple] = []
    start = 0
    while True:
        url = (
            f"{MOEX_URL.format(secid=secid)}"
            f"?from={since}&till={till}&start={start}"
            f"&iss.meta=off&history.columns=TRADEDATE,CLOSE"
        )
        payload = json.loads(http_get(url).decode("utf-8"))
        data = payload["history"]["data"]
        if not data:
            break
        for tradedate, close in data:
            if close is not None:
                total.append((tradedate, float(close)))
        start += len(data)
        if len(data) < 100:  # последняя страница ISS
            break
    if total:
        upsert_index(conn, secid, total)
        span = f"{min(d for d, _ in total)}..{max(d for d, _ in total)}"
        print(f"[индекс] {secid}: собрано строк: {len(total)} ({span})")
    else:
        print(f"[индекс] {secid}: новых строк нет")
    return len(total)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    global RETRY_ATTEMPTS, RETRY_DELAY
    ap = argparse.ArgumentParser(description="Сбор данных доходности фонда и индекса")
    ap.add_argument(
        "--since",
        help="начальная дата для истории индекса (YYYY-MM-DD). "
        "По умолчанию: инкрементально от последней собранной даты, "
        "либо с начала жизни фонда при пустой базе.",
    )
    ap.add_argument("--full", action="store_true",
                    help="полный бэкфилл индекса с даты старта фонда")
    ap.add_argument("--db", default=str(DB_PATH), help="путь к SQLite-базе")
    ap.add_argument("--import-fund", metavar="FILE",
                    help="разовый импорт полной истории фонда из .xlsx/.csv "
                    "(выгрузка с investfunds.ru)")
    ap.add_argument("--skip-fund", action="store_true")
    ap.add_argument("--skip-index", action="store_true")
    ap.add_argument("--retries", type=int, default=RETRY_ATTEMPTS,
                    help=f"число попыток при сетевых сбоях (по умолчанию {RETRY_ATTEMPTS})")
    ap.add_argument("--retry-delay", type=int, default=RETRY_DELAY,
                    help=f"пауза между попытками, сек (по умолчанию {RETRY_DELAY})")
    args = ap.parse_args()

    RETRY_ATTEMPTS = max(1, args.retries)
    RETRY_DELAY = max(0, args.retry_delay)

    conn = sqlite3.connect(args.db)
    init_db(conn)

    ok = True
    if args.import_fund:
        try:
            import_fund_file(conn, args.import_fund)
        except Exception as e:  # noqa: BLE001
            print(f"[импорт] ОШИБКА: {e}", file=sys.stderr)
            ok = False

    if not args.skip_fund:
        try:
            collect_fund(conn)
        except Exception as e:  # noqa: BLE001 — не роняем сбор индекса из-за фонда
            print(f"[фонд]   ОШИБКА: {e}", file=sys.stderr)
            ok = False

    if not args.skip_index:
        if args.since:
            since = args.since
        elif args.full:
            since = FUND_MIN_DATE
        else:
            last = max_date(conn, "index_value", f"WHERE secid='{INDEX_SECID}'")
            if last:
                # перекрываем ~10 дней на случай пересмотра значений
                since = (datetime.fromisoformat(last) - timedelta(days=10)).date().isoformat()
            else:
                since = FUND_MIN_DATE
        try:
            collect_index(conn, INDEX_SECID, since)
        except Exception as e:  # noqa: BLE001
            print(f"[индекс] ОШИБКА: {e}", file=sys.stderr)
            ok = False

    fund_n = conn.execute("SELECT COUNT(*) FROM fund").fetchone()[0]
    idx_n = conn.execute("SELECT COUNT(*) FROM index_value").fetchone()[0]
    print(f"[итого]  в базе: фонд {fund_n} строк, индекс {idx_n} строк -> {args.db}")
    conn.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
