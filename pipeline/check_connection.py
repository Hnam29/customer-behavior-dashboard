"""
Kiểm tra nhanh trước khi chạy luồng: kết nối được SQL Server chưa, câu SQL có chạy
được không, trả về đủ cột chưa. Không ghi gì ra ổ đĩa.

  python -m pipeline.check_connection                  # thử với ngày hôm qua
  python -m pipeline.check_connection --date 2026-09-28
"""

import argparse
import sys
from datetime import timedelta

import pandas as pd

from core import settings
from pipeline import db
from pipeline.run import default_as_of
from pipeline.steps import OPTIONAL, REQUIRED


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="Ngày thử (YYYY-MM-DD), mặc định hôm qua")
    a = p.parse_args(argv)
    d = pd.Timestamp(a.date).date() if a.date else default_as_of()

    print(f"1) Kết nối: {db.connection_string(hide_password=True)}")
    try:
        db.connect().close()
        print("   OK")
    except db.SourceError as e:
        print(f"   LỖI: {e}")
        return 1

    print(f"2) Đọc câu SQL: {settings.SQL_FILE}")
    try:
        sql = db.load_sql()
        print("   OK")
    except db.SourceError as e:
        print(f"   LỖI: {e}")
        return 1

    print(f"3) Chạy câu SQL cho ngày {d}")
    try:
        df = db.query_range(d, d + timedelta(days=1), sql)
    except db.SourceError as e:
        print(f"   LỖI: {e}")
        return 1
    print(f"   OK: {len(df):,} dòng, cột: {', '.join(map(str, df.columns))}")
    lack = [c for c in REQUIRED if c not in df.columns]
    opt = [c for c in OPTIONAL if c not in df.columns]
    if lack:
        print(f"   THIẾU cột bắt buộc: {', '.join(lack)} -> sửa tên cột bằng AS trong file SQL")
        return 1
    if opt:
        print(f"   (không có cột tùy chọn: {', '.join(opt)})")
    if len(df):
        print(df.head(5).to_string())
    print("Tất cả đều ổn. Có thể chạy: python -m pipeline.run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
