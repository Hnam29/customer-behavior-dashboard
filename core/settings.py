"""
Cấu hình chung, đọc từ biến môi trường hoặc file .env ở thư mục gốc dự án.

Cùng một file .env được dùng cho:
  - chạy pipeline bằng tay trên Windows (python -m pipeline.run)
  - Airflow trong Docker (docker-compose đọc .env qua env_file)
  - dashboard Streamlit (chỉ cần DATA_DIR)
Không ghi mật khẩu vào code. Xem .env.example để biết các biến cần khai báo.
"""

import os
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

try:  # python-dotenv là tùy chọn; không có thì chỉ đọc biến môi trường
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass


def _get(name, default=None):
    v = os.environ.get(name)
    return default if v is None or v.strip() == "" else v.strip()


def _bool(name, default):
    return str(_get(name, str(default))).lower() in ("1", "true", "yes", "y", "on")


def _int(name, default):
    return int(_get(name, default))


def _float(name, default):
    return float(_get(name, default))


def _path(name, default):
    p = Path(_get(name, default))
    return p if p.is_absolute() else (PROJECT_ROOT / p)


# ---------------- Nguồn dữ liệu: SQL Server ----------------
MSSQL_SERVER = _get("MSSQL_SERVER", "")
MSSQL_PORT = _int("MSSQL_PORT", 1433)
MSSQL_DATABASE = _get("MSSQL_DATABASE", "")
MSSQL_USER = _get("MSSQL_USER", "")
MSSQL_PASSWORD = _get("MSSQL_PASSWORD", "")
MSSQL_DRIVER = _get("MSSQL_DRIVER", "ODBC Driver 18 for SQL Server")
MSSQL_ENCRYPT = _get("MSSQL_ENCRYPT", "yes")
MSSQL_TRUST_SERVER_CERTIFICATE = _get("MSSQL_TRUST_SERVER_CERTIFICATE", "yes")
MSSQL_LOGIN_TIMEOUT = _int("MSSQL_LOGIN_TIMEOUT", 30)
MSSQL_QUERY_TIMEOUT = _int("MSSQL_QUERY_TIMEOUT", 1800)

# Chỉ dùng để kiểm thử: đọc từ file SQLite thay cho SQL Server
TEST_SQLITE_SOURCE = _get("TEST_SQLITE_SOURCE", "")

SQL_FILE = _path("SQL_FILE", "pipeline/sql/extract_transactions.sql")

# ---------------- Trích xuất ----------------
HISTORY_START = date.fromisoformat(_get("HISTORY_START", "2023-01-01"))
EXTRACT_CHUNK_DAYS = _int("EXTRACT_CHUNK_DAYS", 31)      # lần đầu tải lịch sử theo từng khúc
REEXTRACT_DAYS = _int("REEXTRACT_DAYS", 2)               # mỗi lần chạy lấy lại N ngày gần nhất
TIMEZONE = _get("TIMEZONE", "Asia/Ho_Chi_Minh")

# ---------------- Lưu trữ ----------------
DATA_DIR = _path("DATA_DIR", "data")
SNAPSHOT_KEEP = _int("SNAPSHOT_KEEP", 14)                # số bản chụp đầy đủ giữ lại

# ---------------- Làm sạch & phân tích (bản chính thức) ----------------
DATE_FORMAT = _get("DATE_FORMAT", "auto")                # auto | mdy | dmy
DROP_DUPLICATES = _bool("DROP_DUPLICATES", True)
MIN_ORDERS = _int("MIN_ORDERS", 5)
TIMING_CV = _float("TIMING_CV", 0.5)
QTY_CV = _float("QTY_CV", 0.5)
DUE_K = _float("DUE_K", 1.0)
CHURN_DAYS = _int("CHURN_DAYS", 365)
CHURN_MULT = _float("CHURN_MULT", 5.0)

# ---------------- Kiểm tra dữ liệu thô ----------------
MAX_NULL_RATE = _float("MAX_NULL_RATE", 0.05)            # tỷ lệ ô trống tối đa ở cột bắt buộc
MAX_BAD_DATE_RATE = _float("MAX_BAD_DATE_RATE", 0.05)
VOLUME_LOW_RATIO = _float("VOLUME_LOW_RATIO", 0.3)       # số dòng T-1 < 30% mức thường lệ -> cảnh báo
VOLUME_HIGH_RATIO = _float("VOLUME_HIGH_RATIO", 3.0)

# ---------------- Email ----------------
SMTP_HOST = _get("SMTP_HOST", "")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USER = _get("SMTP_USER", "")
SMTP_PASSWORD = _get("SMTP_PASSWORD", "")
SMTP_STARTTLS = _bool("SMTP_STARTTLS", True)
SMTP_SSL = _bool("SMTP_SSL", False)
EMAIL_FROM = _get("EMAIL_FROM", SMTP_USER)
EMAIL_TO = [e.strip() for e in _get("EMAIL_TO", "").split(",") if e.strip()]
NOTIFY_ON_SUCCESS = _bool("NOTIFY_ON_SUCCESS", True)
DASHBOARD_URL = _get("DASHBOARD_URL", "http://localhost:8501")
AIRFLOW_URL = _get("AIRFLOW_URL", "http://localhost:8080")
