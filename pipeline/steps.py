"""
5 bước của luồng dữ liệu. Mỗi bước:
  - chỉ đọc kết quả của bước trước từ DATA_DIR và ghi kết quả của chính nó,
  - chạy lại được nhiều lần cho cùng một ngày mà không nhân đôi dữ liệu,
  - ghi số liệu vào rec["metrics"] và cảnh báo vào rec["warnings"] (xem run_log.py).

Hàm chính của mỗi bước: step_<tên>(as_of, rec, **kw)
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from core import settings, storage
from core.behavior import (STD_COLS, _is_blank, _to_number, clean_transactions,
                           compute_profiles, parse_dates)
from pipeline import db

REQUIRED = ["date", "customer", "product", "quantity"]
OPTIONAL = ["unit", "unit_price", "amount", "contract_number", "category", "ingredient"]


class ValidationError(RuntimeError):
    """Dữ liệu thô không đạt kiểm tra: dừng luồng trước khi số liệu sai lan ra dashboard."""


def _d(x):
    return pd.Timestamp(x).normalize()


def _key(x):
    return _d(x).strftime("%Y-%m-%d")


# =====================================================================
# 1. TRÍCH XUẤT
# =====================================================================
def _chunks(days, max_len):
    """Gom các ngày liên tiếp thành các khúc tối đa max_len ngày."""
    days = sorted(days)
    out, start, prev = [], None, None
    for d in days:
        if start is None:
            start = prev = d
        elif (d - prev).days == 1 and (d - start).days < max_len:
            prev = d
        else:
            out.append((start, prev))
            start = prev = d
    if start is not None:
        out.append((start, prev))
    return out


def step_extract(as_of, rec, full_reload=False, **_):
    as_of = _d(as_of)
    if as_of.date() < settings.HISTORY_START:
        raise ValueError(f"Ngày đánh giá {as_of:%d/%m/%Y} trước HISTORY_START {settings.HISTORY_START}")
    man = storage.load_manifest()
    if full_reload:
        for f in storage.raw_dir().glob("date=*.parquet"):
            f.unlink()
        man = {"dates": {}}

    all_days = pd.date_range(settings.HISTORY_START, as_of, freq="D")
    missing = [d for d in all_days if _key(d) not in man["dates"]]
    # luôn lấy lại vài ngày gần nhất: phòng khi lần chạy trước chạy lúc nguồn chưa nạp đủ
    recent = [d for d in pd.date_range(as_of - timedelta(days=settings.REEXTRACT_DAYS - 1), as_of)
              if d >= pd.Timestamp(settings.HISTORY_START)]
    todo = sorted(set(missing) | set(recent))
    chunks = _chunks(todo, settings.EXTRACT_CHUNK_DAYS)

    sql = db.load_sql()
    total, stray, cols_seen = 0, 0, None
    for a, b in chunks:
        df = db.query_range(a, b + timedelta(days=1), sql)
        if cols_seen is None:
            cols_seen = list(df.columns)
            lack = [c for c in REQUIRED if c not in df.columns]
            if lack:
                raise db.SourceError(
                    f"Câu SQL chưa trả về cột bắt buộc: {', '.join(lack)}. Các cột đang có: "
                    f"{', '.join(map(str, df.columns))}. Hãy đặt tên cột bằng AS (xem file SQL).")
        if len(df):
            key, used, ambiguous = parse_dates(df["date"], settings.DATE_FORMAT)
            if ambiguous and man.get("date_format") in ("mdy", "dmy"):
                # khúc ít ngày (vd chạy hằng đêm) mà mọi ngày đều <= 12: không tự nhận diện
                # được -> dùng định dạng đã nhận diện được ở các lần trước
                key, used, ambiguous = parse_dates(df["date"], man["date_format"])
            elif ambiguous:
                rec["warnings"].append("Cột ngày dạng chữ, không phân biệt được ngày/tháng. "
                                       "Hãy đặt DATE_FORMAT=mdy hoặc dmy trong .env.")
            if used in ("mdy", "dmy") and not ambiguous:
                man["date_format"] = used
            key = pd.to_datetime(key).dt.normalize()
            outside = key.isna() | (key < a) | (key > b)
            stray += int(outside.sum())
            key = key.where(~outside, a)       # dòng ngày lỗi: xếp vào ngày đầu khúc, bước làm sạch sẽ báo
        else:
            key = pd.Series(dtype="datetime64[ns]")
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        for d in pd.date_range(a, b, freq="D"):
            part = df[key.values == d] if len(df) else df
            p = storage.raw_path(d)
            if len(part):
                storage.write_parquet(p, part)
            elif p.exists():
                p.unlink()
            man["dates"][_key(d)] = {"rows": int(len(part)), "extracted_at": now}
        storage.save_manifest(man)                # lưu sau mỗi khúc: lỗi giữa chừng vẫn giữ phần đã xong
        total += len(df)

    # Số liệu để đối chiếu trực tiếp với database (MIN/MAX ngày, số ngày có giao dịch, số dòng)
    have = sorted(k for k, v in man["dates"].items() if v["rows"] > 0 and k <= _key(as_of))
    rec["metrics"] = {
        "range_requested": f"{todo[0]:%Y-%m-%d} → {todo[-1]:%Y-%m-%d}" if todo else "",
        "days_requested": len(todo),              # số ngày trên lịch được truy vấn lần này
        "queries": len(chunks),
        "rows_this_run": int(total),              # số dòng lấy về trong lần chạy này
        "data_first_day": have[0] if have else None,     # = MIN(ngày) trong database
        "data_last_day": have[-1] if have else None,     # = MAX(ngày) trong database
        "days_with_data": len(have),              # = COUNT(DISTINCT ngày) trong database
        "rows_total": int(sum(man["dates"][k]["rows"] for k in have)),   # = COUNT(*)
        "rows_on_as_of": man["dates"].get(_key(as_of), {}).get("rows", 0),
        "columns": cols_seen or []}
    if stray:
        rec["warnings"].append(f"{stray} dòng có ngày không đọc được hoặc nằm ngoài khoảng truy vấn.")
    return rec


# =====================================================================
# 2. KIỂM TRA DỮ LIỆU THÔ
# =====================================================================
def step_validate(as_of, rec, **_):
    as_of = _d(as_of)
    man = storage.load_manifest()
    checks = []

    def check(name, level, ok, detail):
        checks.append({"check": name, "level": level, "passed": bool(ok), "detail": detail})

    raw = storage.read_raw(until=as_of)
    check("Có dữ liệu thô", "error", len(raw) > 0, f"{len(raw):,} dòng")
    if len(raw):
        lack = [c for c in REQUIRED if c not in raw.columns]
        check("Đủ cột bắt buộc", "error", not lack,
              "đủ" if not lack else f"thiếu: {', '.join(lack)}")
        opt = [c for c in OPTIONAL if c in raw.columns]
        check("Cột không bắt buộc", "info", True, ", ".join(opt) or "không có")

        key = _key(as_of)
        check("Đã trích xuất ngày T-1", "error", key in man["dates"], key)
        n_asof = man["dates"].get(key, {}).get("rows", 0)
        check("Ngày T-1 có giao dịch", "warning", n_asof > 0,
              f"{n_asof:,} dòng" + ("" if n_asof else " (có thể là ngày nghỉ)"))

        prev = [man["dates"][_key(as_of - timedelta(days=7 * i))]["rows"] for i in range(1, 9)
                if _key(as_of - timedelta(days=7 * i)) in man["dates"]]
        prev = [p for p in prev if p > 0]
        if n_asof and len(prev) >= 4:
            med = float(np.median(prev))
            ratio = n_asof / med if med else np.nan
            check("Số dòng T-1 so với cùng thứ 8 tuần trước", "warning",
                  settings.VOLUME_LOW_RATIO <= ratio <= settings.VOLUME_HIGH_RATIO,
                  f"{n_asof:,} dòng, thường khoảng {med:,.0f} (bằng {ratio:.0%})")

        if not lack:
            recent = storage.read_raw(since=as_of - timedelta(days=6), until=as_of)
            for c in REQUIRED:
                if len(recent):
                    rate = float(_is_blank(recent[c]).mean())
                    check(f"Ô trống ở cột {c} (7 ngày gần nhất)", "warning",
                          rate <= settings.MAX_NULL_RATE, f"{rate:.1%}")
            parsed, used, _ = parse_dates(raw["date"], settings.DATE_FORMAT)
            bad = float(pd.isna(parsed).mean())
            check("Đọc được cột ngày", "error", bad <= settings.MAX_BAD_DATE_RATE,
                  f"{bad:.2%} dòng không đọc được (định dạng: {used})")
            future = int((pd.to_datetime(parsed) > as_of).sum())
            check("Không có ngày sau T-1", "warning", future == 0, f"{future} dòng")
            q = _to_number(raw["quantity"])
            bad_q = float((q.isna() & ~_is_blank(raw["quantity"])).mean())
            check("Số lượng là số", "error", bad_q <= settings.MAX_BAD_DATE_RATE,
                  f"{bad_q:.2%} dòng không đọc được")

    storage.write_json(storage.snapshot_dir(as_of) / "validation.json",
                       {"as_of": _key(as_of), "checks": checks})
    failed_err = [c for c in checks if c["level"] == "error" and not c["passed"]]
    failed_warn = [c for c in checks if c["level"] == "warning" and not c["passed"]]
    rec["metrics"] = {"checks": len(checks), "errors": len(failed_err), "warnings": len(failed_warn),
                      "raw_rows": int(len(raw))}
    rec["warnings"] += [f"{c['check']}: {c['detail']}" for c in failed_warn]
    if failed_err:
        raise ValidationError("; ".join(f"{c['check']} ({c['detail']})" for c in failed_err))
    return rec


# =====================================================================
# 3. LÀM SẠCH
# =====================================================================
def step_clean(as_of, rec, **_):
    as_of = _d(as_of)
    raw = storage.read_raw(until=as_of)
    if raw.empty:
        raise ValueError("Không có dữ liệu thô để làm sạch. Hãy chạy bước extract trước.")
    mapping = {c: (c if c in raw.columns else None) for c in STD_COLS}
    df, report = clean_transactions(raw, mapping, drop_exact_duplicates=settings.DROP_DUPLICATES,
                                    date_format=settings.DATE_FORMAT)
    if df.empty:
        raise ValueError("Sau khi làm sạch không còn dòng nào.")

    # Dùng [category] làm chiều phân tích sản phẩm chính trên dashboard.
    # [product] gốc (tên thành phẩm cụ thể) giữ lại trong [product_name] để tra cứu.
    if "category" in df.columns:
        if "product" in df.columns:
            df = df.rename(columns={"product": "product_name"})
        df = df.rename(columns={"category": "product"})
        # Fallback: nếu category rỗng thì dùng product_name
        if "product_name" in df.columns:
            mask = df["product"].isna() | (df["product"].astype(str).str.strip() == "")
            df.loc[mask, "product"] = df.loc[mask, "product_name"]

    snap = storage.snapshot_dir(as_of)
    storage.write_parquet(snap / "clean.parquet", df)
    storage.save_report(report, snap)

    steps = report["steps"]
    rec["metrics"] = {"rows_in": int(report["rows_in"]), "rows_out": int(report["rows_out"]),
                      "removed_by_step": {r.step: int(r.removed) for r in steps.itertuples()
                                          if r.removed},
                      "cells_filled": int(len(report["fill_log"])),
                      "amount_mismatch": report["amount_mismatch"]}
    kept = report["rows_out"] / max(report["rows_in"], 1)
    if kept < 0.9:
        rec["warnings"].append(f"Bước làm sạch loại {1 - kept:.1%} số dòng (trên 10%).")
    if report["date_ambiguous"]:
        rec["warnings"].append("Không tự nhận diện được định dạng ngày, hãy đặt DATE_FORMAT trong .env.")
    return rec


# =====================================================================
# 4. TÍNH HỒ SƠ (bản chính thức, theo ngưỡng mặc định trong .env)
# =====================================================================
def official_params(as_of):
    return dict(min_orders=settings.MIN_ORDERS, timing_cv=settings.TIMING_CV, qty_cv=settings.QTY_CV,
                k=settings.DUE_K, churn_days=settings.CHURN_DAYS, churn_mult=settings.CHURN_MULT,
                as_of=_d(as_of))


def step_profiles(as_of, rec, **_):
    snap = storage.snapshot_dir(as_of)
    f = snap / "clean.parquet"
    if not f.exists():
        raise ValueError("Chưa có dữ liệu sạch cho ngày này. Hãy chạy bước clean trước.")
    df = storage.read_parquet(f)
    has_amount = bool(df["amount"].notna().any())
    params = official_params(as_of)
    pair, _ = compute_profiles(df, level="pair", vol_basis="qty", **params)
    cust, _ = compute_profiles(df, level="customer", vol_basis="amount" if has_amount else "qty",
                               **params)
    for p in (pair, cust):
        p.insert(0, "as_of", _d(as_of))
    storage.write_parquet(snap / "profiles_pair.parquet", pair)
    storage.write_parquet(snap / "profiles_customer.parquet", cust)
    rec["metrics"] = {"pairs": int(len(pair)), "customers": int(len(cust)),
                      "status_pair": {str(k): int(v) for k, v in pair["status"].value_counts().items()},
                      "status_customer": {str(k): int(v) for k, v in
                                          cust["status"].value_counts().items()},
                      "params": {k: (str(v) if k == "as_of" else v) for k, v in params.items()}}
    return rec


# =====================================================================
# 5. CÔNG BỐ
# =====================================================================
def step_publish(as_of, rec, run_id=None, **_):
    snap = storage.snapshot_dir(as_of)
    need = ["validation.json", "clean.parquet", "report.json", "profiles_pair.parquet",
            "profiles_customer.parquet"]
    lack = [n for n in need if not (snap / n).exists()]
    if lack:
        raise ValueError(f"Bản chụp ngày {_key(as_of)} còn thiếu: {', '.join(lack)}")
    report = storage.read_json(snap / "report.json")
    pair = storage.read_parquet(snap / "profiles_pair.parquet")
    info = {"as_of": _key(as_of), "run_id": run_id,
            "published_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "snapshot": f"snapshots/{_key(as_of)}",
            "rows_in": report.get("rows_in"), "rows_out": report.get("rows_out"),
            "status_pair": {str(k): int(v) for k, v in pair["status"].value_counts().items()}}
    storage.write_latest(info)
    trimmed = storage.cleanup_snapshots()
    rec["metrics"] = {"published": info["as_of"], "snapshots_trimmed": trimmed,
                      "status_pair": info["status_pair"]}
    return rec


STEPS = {"extract": step_extract, "validate": step_validate, "clean": step_clean,
         "profiles": step_profiles, "publish": step_publish}
