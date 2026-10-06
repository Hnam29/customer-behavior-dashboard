"""
Lưu trữ dạng file Parquet/JSON trong DATA_DIR (không ghi gì vào SQL Server).

data/
  raw/transactions/date=YYYY-MM-DD.parquet   dữ liệu thô, mỗi ngày giao dịch một file
  raw/manifest.json                          ngày nào đã trích xuất, bao nhiêu dòng
  snapshots/YYYY-MM-DD/                      kết quả của ngày đánh giá (T-1)
      validation.json                        kết quả kiểm tra dữ liệu thô
      clean.parquet                          dữ liệu sạch
      report.json + report_*.parquet         báo cáo làm sạch (dùng cho tab Làm sạch dữ liệu)
      profiles_pair.parquet                  hồ sơ khách × sản phẩm (bản chính thức)
      profiles_customer.parquet              hồ sơ theo khách
  runs/<run_id>.json                         nhật ký từng lần chạy, từng bước
  latest.json                                bản chụp thành công gần nhất (dashboard đọc file này)

Mọi file đều được ghi ra file tạm rồi đổi tên, nên dashboard không bao giờ đọc phải
một file đang ghi dở.
"""

import json
import os
import shutil
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from core import settings


# ---------------- đường dẫn ----------------
def data_dir():
    d = Path(settings.DATA_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def raw_dir():
    d = data_dir() / "raw" / "transactions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def snapshot_dir(as_of, create=True):
    d = data_dir() / "snapshots" / pd.Timestamp(as_of).strftime("%Y-%m-%d")
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def runs_dir():
    d = data_dir() / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------- ghi an toàn ----------------
def _json_default(o):
    if isinstance(o, (pd.Timestamp, datetime, date)):
        return o.isoformat()
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default),
                   encoding="utf-8")
    os.replace(tmp, path)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def parquet_safe(df):
    """Đưa các cột kiểu object về kiểu Parquet hiểu được (Decimal -> số, còn lại -> chuỗi)."""
    out = df.copy()
    for c in out.columns:
        s = out[c]
        if s.dtype == object:
            non_null = s.dropna()
            if len(non_null) and non_null.map(lambda v: isinstance(v, (int, float, np.number))
                                              or type(v).__name__ == "Decimal").all():
                out[c] = pd.to_numeric(s, errors="coerce")
            elif len(non_null) and non_null.map(lambda v: isinstance(v, (datetime, date,
                                                                         pd.Timestamp))).all():
                out[c] = pd.to_datetime(s, errors="coerce")
            else:
                out[c] = s.map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v))
                               else str(v)).astype(object)
    return out


def write_parquet(path, df):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    parquet_safe(df).to_parquet(tmp, index=False)
    os.replace(tmp, path)


def read_parquet(path):
    return pd.read_parquet(path)


# ---------------- dữ liệu thô ----------------
def raw_path(d):
    return raw_dir() / f"date={pd.Timestamp(d):%Y-%m-%d}.parquet"


def manifest_path():
    return data_dir() / "raw" / "manifest.json"


def load_manifest():
    return read_json(manifest_path(), default={"dates": {}})


def save_manifest(m):
    write_json(manifest_path(), m)


def read_raw(until=None, since=None):
    """Đọc và ghép các file thô theo ngày (đã sắp theo ngày)."""
    files = sorted(raw_dir().glob("date=*.parquet"))
    keep = []
    for f in files:
        d = f.stem.split("=", 1)[1]
        if until is not None and d > pd.Timestamp(until).strftime("%Y-%m-%d"):
            continue
        if since is not None and d < pd.Timestamp(since).strftime("%Y-%m-%d"):
            continue
        keep.append(f)
    if not keep:
        return pd.DataFrame()
    frames = [pd.read_parquet(f) for f in keep]
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------- báo cáo làm sạch ----------------
def save_report(report, folder):
    """DataFrame -> report_<key>.parquet, còn lại -> report.json."""
    folder = Path(folder)
    meta = {}
    for k, v in report.items():
        if isinstance(v, pd.DataFrame):
            name = f"report_{k}.parquet"
            write_parquet(folder / name, v)
            meta[k] = {"__parquet__": name}
        else:
            meta[k] = v
    write_json(folder / "report.json", meta)


def load_report(folder):
    folder = Path(folder)
    meta = read_json(folder / "report.json")
    if meta is None:
        return None
    out = {}
    for k, v in meta.items():
        if isinstance(v, dict) and "__parquet__" in v:
            out[k] = pd.read_parquet(folder / v["__parquet__"])
        else:
            out[k] = v
    return out


# ---------------- bản chính thức & nhật ký ----------------
def latest_path():
    return data_dir() / "latest.json"


def read_latest():
    return read_json(latest_path())


def write_latest(info):
    write_json(latest_path(), info)


def run_path(run_id):
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in run_id)
    return runs_dir() / f"{safe}.json"


def list_runs(limit=30):
    runs = []
    for f in runs_dir().glob("*.json"):
        r = read_json(f)
        if r:
            runs.append(r)
    runs.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    return runs[:limit]


def cleanup_snapshots(keep=None):
    """
    Giữ SNAPSHOT_KEEP bản chụp đầy đủ gần nhất. Với bản cũ hơn chỉ giữ lại hồ sơ
    (profiles_*.parquet, nhỏ) để còn lịch sử trạng thái theo ngày, xóa phần nặng.
    """
    keep = settings.SNAPSHOT_KEEP if keep is None else keep
    root = data_dir() / "snapshots"
    if not root.exists():
        return []
    snaps = sorted([p for p in root.iterdir() if p.is_dir()], reverse=True)
    latest = read_latest() or {}
    removed = []
    for p in snaps[keep:]:
        if p.name == latest.get("as_of"):
            continue
        for f in p.iterdir():
            if not f.name.startswith("profiles_") and f.name != "validation.json":
                if f.is_dir():
                    shutil.rmtree(f)
                else:
                    f.unlink()
        removed.append(p.name)
    return removed
