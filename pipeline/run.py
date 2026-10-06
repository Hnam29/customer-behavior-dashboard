"""
Chạy luồng dữ liệu bằng tay (không cần Airflow). Airflow cũng gọi các hàm ở đây.

  python -m pipeline.run                              # toàn bộ các bước cho ngày hôm qua (T-1)
  python -m pipeline.run --as-of 2026-09-28           # cho một ngày cụ thể
  python -m pipeline.run --steps clean,profiles,publish   # chạy lại từ bước clean
  python -m pipeline.run --full-reload                # xóa dữ liệu thô, tải lại toàn bộ lịch sử
  python -m pipeline.run --no-email                   # không gửi email
"""

import argparse
import sys
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from core import settings
from pipeline import notify
from pipeline.run_log import STEP_ORDER, RunLog


def default_as_of(reference=None):
    """T-1 theo giờ Việt Nam. reference: thời điểm chạy (mặc định là bây giờ)."""
    tz = ZoneInfo(settings.TIMEZONE)
    ref = pd.Timestamp(reference) if reference is not None else pd.Timestamp.now(tz)
    ref = ref.tz_localize(tz) if ref.tzinfo is None else ref.tz_convert(tz)
    return (ref.normalize() - timedelta(days=1)).date()


def new_run_id(as_of, trigger="manual"):
    return f"{trigger}_{as_of}_{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"


def run_step(name, as_of, run_id, trigger="manual", **kw):
    """Chạy 1 bước và ghi nhật ký. Lỗi được ghi vào nhật ký rồi ném tiếp ra ngoài."""
    from pipeline.steps import STEPS              # import muộn: DAG Airflow nạp nhanh hơn
    log = RunLog(run_id, as_of, trigger)
    with log.step(name) as rec:
        STEPS[name](as_of, rec, run_id=run_id, **kw)
    return log


def finish_run(run_id, send_email=True):
    log = RunLog(run_id, None)
    log.finish("success")
    if send_email and (settings.NOTIFY_ON_SUCCESS or log.warnings):
        notify.success(log.data, log.warnings)
    return log.data


def fail_run(run_id, send_email=True):
    from core import storage
    data = storage.read_json(storage.run_path(run_id)) or {"run_id": run_id}
    if send_email:
        notify.failure(data)
    return data


def run_pipeline(as_of=None, steps=None, full_reload=False, send_email=True, trigger="manual"):
    as_of = pd.Timestamp(as_of).date() if as_of else default_as_of()
    steps = steps or STEP_ORDER
    run_id = new_run_id(as_of, trigger)
    print(f"== Lần chạy {run_id}: ngày đánh giá {as_of}, các bước: {', '.join(steps)}")
    for name in steps:
        print(f"-> {name} ...", flush=True)
        try:
            log = run_step(name, as_of, run_id, trigger, full_reload=full_reload)
        except Exception as e:  # noqa: BLE001
            print(f"!! Lỗi ở bước {name}: {type(e).__name__}: {e}")
            fail_run(run_id, send_email)
            return 1
        rec = log.data["steps"][name]
        print(f"   xong sau {rec['duration_s']}s | {rec['metrics']}")
        for w in rec["warnings"]:
            print(f"   cảnh báo: {w}")
    finish_run(run_id, send_email)
    print(f"== Thành công. Nhật ký: data/runs/{run_id}.json")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Luồng cập nhật dữ liệu hành vi khách hàng")
    p.add_argument("--as-of", help="Ngày đánh giá YYYY-MM-DD (mặc định: hôm qua)")
    p.add_argument("--steps", help=f"Các bước cần chạy, cách nhau dấu phẩy: {','.join(STEP_ORDER)}")
    p.add_argument("--full-reload", action="store_true", help="Tải lại toàn bộ lịch sử")
    p.add_argument("--no-email", action="store_true", help="Không gửi email")
    a = p.parse_args(argv)
    steps = [s.strip() for s in a.steps.split(",")] if a.steps else None
    bad = [s for s in (steps or []) if s not in STEP_ORDER]
    if bad:
        p.error(f"Bước không hợp lệ: {', '.join(bad)}")
    return run_pipeline(a.as_of, steps, a.full_reload, not a.no_email)


if __name__ == "__main__":
    sys.exit(main())
