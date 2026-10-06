"""
Kết nối SQL Server (chỉ đọc) và chạy câu SQL trích xuất.

Câu SQL nằm trong file SQL_FILE, dùng 2 tham số :start_date (tính cả ngày này) và
:end_date (KHÔNG tính ngày này). Ví dụ lấy ngày 28/09/2026:
    start_date = 2026-09-28, end_date = 2026-09-29
"""

import re
import sqlite3
from pathlib import Path

import pandas as pd

from core import settings

_PARAM_RE = re.compile(r":(start_date|end_date)\b")
_LITERAL_RE = re.compile(r"('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\[[^\]]*\])")


def _bind(sql):
    """Đổi :start_date/:end_date thành ? (bỏ qua các chữ nằm trong chuỗi '...', [..], "...").
    Trả về (câu SQL đã đổi, danh sách tên tham số theo đúng thứ tự)."""
    names, parts = [], _LITERAL_RE.split(sql)
    for i in range(0, len(parts), 2):            # phần chẵn là câu lệnh, phần lẻ là chuỗi
        names += _PARAM_RE.findall(parts[i])
        parts[i] = _PARAM_RE.sub("?", parts[i])
    return "".join(parts), names


class SourceError(RuntimeError):
    """Lỗi ở phía nguồn dữ liệu: kết nối, đăng nhập, câu SQL."""


def connection_string(hide_password=False):
    pwd = "***" if hide_password else settings.MSSQL_PASSWORD
    return (f"DRIVER={{{settings.MSSQL_DRIVER}}};"
            f"SERVER={settings.MSSQL_SERVER},{settings.MSSQL_PORT};"
            f"DATABASE={settings.MSSQL_DATABASE};UID={settings.MSSQL_USER};PWD={pwd};"
            f"Encrypt={settings.MSSQL_ENCRYPT};"
            f"TrustServerCertificate={settings.MSSQL_TRUST_SERVER_CERTIFICATE};"
            "ApplicationIntent=ReadOnly;")


def connect():
    if settings.TEST_SQLITE_SOURCE:
        return sqlite3.connect(settings.TEST_SQLITE_SOURCE)
    missing = [n for n in ("MSSQL_SERVER", "MSSQL_DATABASE", "MSSQL_USER", "MSSQL_PASSWORD")
               if not getattr(settings, n)]
    if missing:
        raise SourceError(f"Chưa khai báo trong file .env: {', '.join(missing)}")
    try:
        import pyodbc
    except ImportError as e:
        raise SourceError("Chưa cài pyodbc hoặc ODBC Driver cho SQL Server "
                          f"({e}). Xem README, mục Cài đặt.") from e
    try:
        conn = pyodbc.connect(connection_string(), timeout=settings.MSSQL_LOGIN_TIMEOUT)
        conn.timeout = settings.MSSQL_QUERY_TIMEOUT
        return conn
    except pyodbc.Error as e:
        drivers = ", ".join(pyodbc.drivers()) or "không có"
        raise SourceError(f"Không kết nối được SQL Server {settings.MSSQL_SERVER}: {e}. "
                          f"Driver ODBC đang có trên máy: {drivers}") from e


def strip_comments(sql):
    """
    Bỏ ghi chú -- ... và /* ... */ (kể cả lồng nhau) khỏi câu SQL, giữ nguyên chuỗi '...',
    tên [..] và "..." để không cắt nhầm khi trong chuỗi có ký tự -- hoặc /*.
    Cần thiết vì tham số viết trong ghi chú không phải là tham số thật.
    """
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c in ("'", '"'):
            j = i + 1
            while j < n:
                if sql[j] == c and j + 1 < n and sql[j + 1] == c:   # '' hoặc "" là ký tự thoát
                    j += 2
                    continue
                if sql[j] == c:
                    break
                j += 1
            out.append(sql[i:j + 1])
            i = j + 1
        elif c == "[":
            j = sql.find("]", i + 1)
            j = n - 1 if j == -1 else j
            out.append(sql[i:j + 1])
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            if j == -1:
                break
            out.append("\n")
            i = j + 1
        elif sql.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if sql.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif sql.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            out.append(" ")
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def load_sql(path=None):
    path = Path(path or settings.SQL_FILE)
    if not path.exists():
        raise SourceError(f"Không tìm thấy file SQL: {path}")
    sql = strip_comments(path.read_text(encoding="utf-8-sig")).strip()
    if not sql:
        raise SourceError(f"File SQL {path} chưa có câu lệnh nào (chỉ có ghi chú).")
    _, found = _bind(sql)
    missing = [p for p in ("start_date", "end_date") if p not in found]
    if missing:
        raise SourceError(
            "Câu SQL chưa có tham số " + " và ".join(":" + p for p in missing) + " trong phần câu lệnh "
            "(các chỗ nằm trong ghi chú /* */ hoặc -- không được tính). Hãy thêm điều kiện: "
            "WHERE <cột ngày> >= :start_date AND <cột ngày> < :end_date")
    return sql


def query_range(start_date, end_date, sql=None):
    """Chạy câu SQL cho khoảng [start_date, end_date). Trả về DataFrame."""
    sql = sql or load_sql()
    q, names = _bind(sql)
    values = {"start_date": pd.Timestamp(start_date).date(), "end_date": pd.Timestamp(end_date).date()}
    params = [values[n] for n in names]
    conn = connect()
    try:
        cur = conn.cursor()
        if settings.TEST_SQLITE_SOURCE:
            cur.execute(q, [p.isoformat() for p in params])
        else:
            cur.execute("SET NOCOUNT ON;\n" + q, params)
            while cur.description is None and cur.nextset():   # bỏ qua kết quả phụ (bảng tạm...)
                pass
        if cur.description is None:
            raise SourceError("Câu SQL không trả về bảng kết quả nào.")
        cols = [c[0] for c in cur.description]
        rows = []
        while True:
            chunk = cur.fetchmany(50_000)
            if not chunk:
                break
            rows.extend(tuple(r) for r in chunk)
        return pd.DataFrame.from_records(rows, columns=cols)
    except SourceError:
        raise
    except Exception as e:  # noqa: BLE001
        raise SourceError(f"Lỗi khi chạy câu SQL (từ {pd.Timestamp(start_date):%d/%m/%Y} đến trước "
                          f"{pd.Timestamp(end_date):%d/%m/%Y}): {e}") from e
    finally:
        conn.close()
