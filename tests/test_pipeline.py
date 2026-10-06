"""
Kiểm thử toàn bộ luồng với nguồn giả (SQLite) thay cho SQL Server.
Chạy:  python -m tests.test_pipeline
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

TMP = Path(tempfile.mkdtemp(prefix="cb_test_"))
os.environ.update({
    "TEST_SQLITE_SOURCE": str(TMP / "source.db"),
    "DATA_DIR": str(TMP / "data"),
    "SQL_FILE": str(TMP / "extract.sql"),
    "HISTORY_START": "2023-01-01",
    "EXTRACT_CHUNK_DAYS": "92",
    "REEXTRACT_DAYS": "2",
    "SMTP_HOST": "",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from core import storage  # noqa: E402
from core.behavior import make_sample_data  # noqa: E402
from pipeline.run import run_pipeline  # noqa: E402


def build_source():
    raw = make_sample_data()
    d = pd.to_datetime(raw["date"], format="%m/%d/%Y", errors="coerce")
    raw["date"] = d.dt.strftime("%Y-%m-%d 00:00:00").where(d.notna(), None)
    raw = raw.dropna(subset=["date"])          # CSDL thật không chứa ngày sai định dạng
    with sqlite3.connect(TMP / "source.db") as con:
        raw.astype(object).where(raw.notna(), None).to_sql("transactions", con, index=False)
    (TMP / "extract.sql").write_text(
        "SELECT date AS date, customer, product, category, ingredient, unit, quantity,\n"
        "       unit_price, amount, contract_number\n"
        "FROM transactions\n"
        "WHERE date >= :start_date AND date < :end_date\n", encoding="utf-8")

    return len(raw)


def main():
    n = build_source()
    print(f"Nguồn giả: {n} dòng tại {TMP}")

    # 1) lần chạy đầu: tải toàn bộ lịch sử
    assert run_pipeline("2026-05-20", send_email=False) == 0
    latest = storage.read_latest()
    assert latest["as_of"] == "2026-05-20", latest
    man = storage.load_manifest()
    assert len(man["dates"]) == (pd.Timestamp("2026-05-20") - pd.Timestamp("2023-01-01")).days + 1
    snap = storage.snapshot_dir("2026-05-20", create=False)
    for f in ["validation.json", "clean.parquet", "report.json", "profiles_pair.parquet",
              "profiles_customer.parquet"]:
        assert (snap / f).exists(), f
    rep = storage.load_report(snap)
    assert isinstance(rep["steps"], pd.DataFrame) and rep["rows_out"] > 0
    prof = pd.read_parquet(snap / "profiles_pair.parquet")
    print("Trạng thái:", prof["status"].value_counts().to_dict())

    # 2) chạy ngày kế tiếp: chỉ lấy thêm ngày mới + REEXTRACT_DAYS ngày gần nhất
    assert run_pipeline("2026-05-21", send_email=False) == 0
    run = storage.list_runs(1)[0]
    ex = run["steps"]["extract"]["metrics"]
    assert ex["days_requested"] == 2 and ex["queries"] == 1, ex
    print("Lần chạy tăng dần:", ex)

    # 3) bỏ lỡ vài ngày: tự lấy bù các ngày còn thiếu
    assert run_pipeline("2026-05-26", send_email=False) == 0
    ex = storage.list_runs(1)[0]["steps"]["extract"]["metrics"]
    assert ex["days_requested"] == 5, ex
    print("Lấy bù ngày bị lỡ:", ex)

    # 4) ngày sau khi dữ liệu nguồn kết thúc: có cảnh báo, không lỗi
    assert run_pipeline("2026-07-05", send_email=False) == 0
    w = storage.list_runs(1)[0]["steps"]["validate"]["warnings"]
    assert any("T-1 có giao dịch" in x for x in w), w
    print("Cảnh báo ngày không có giao dịch:", w)

    # 5) lỗi ở nguồn: SQL sai -> bước extract lỗi, bản công bố cũ giữ nguyên
    good_sql = (TMP / "extract.sql").read_text(encoding="utf-8")
    (TMP / "extract.sql").write_text(good_sql.replace("FROM transactions", "FROM khong_ton_tai"),
                                     encoding="utf-8")
    assert run_pipeline("2026-07-06", send_email=False) == 1
    run = storage.list_runs(1)[0]
    assert run["status"] == "failed" and run["failed_step"] == "extract", run
    assert storage.read_latest()["as_of"] == "2026-07-05"
    print("Lỗi được ghi đúng bước:", run["failed_step"], "|", run["error"][:90])

    # 6) chạy lại từ bước bị lỗi sau khi sửa
    (TMP / "extract.sql").write_text(good_sql, encoding="utf-8")
    assert run_pipeline("2026-07-06", steps=["extract", "validate", "clean", "profiles", "publish"],
                        send_email=False) == 0
    assert storage.read_latest()["as_of"] == "2026-07-06"

    # 7) SQL thiếu tham số ngày -> báo lỗi rõ ràng
    (TMP / "extract.sql").write_text("SELECT * FROM transactions", encoding="utf-8")
    assert run_pipeline("2026-07-07", send_email=False) == 1
    print("Thiếu tham số:", storage.list_runs(1)[0]["error"][:100])
    (TMP / "extract.sql").write_text(good_sql, encoding="utf-8")

    # 8) email: dựng nội dung (không gửi vì chưa cấu hình SMTP)
    from pipeline import notify
    ok_run = [r for r in storage.list_runs(20) if r["status"] == "success"][0]
    bad_run = [r for r in storage.list_runs(20) if r["status"] == "failed"][0]
    assert notify.success(ok_run, ["ví dụ cảnh báo"]) is False
    assert notify.failure(bad_run) is False
    print("Tất cả kiểm thử đều qua. Dữ liệu thử ở:", TMP / "data")


if __name__ == "__main__":
    main()
