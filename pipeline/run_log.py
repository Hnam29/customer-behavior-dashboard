"""
Nhật ký chạy: mỗi lần chạy một file runs/<run_id>.json, ghi lại từng bước.

Mỗi bước có: trạng thái (running / success / failed / skipped), thời gian, số liệu
(metrics), cảnh báo và lỗi kèm traceback. Nhờ vậy khi có sự cố, chỉ cần mở nhật ký
là biết lỗi xuất phát từ bước nào. Dùng được cho cả chạy tay và Airflow (mỗi task
Airflow là một tiến trình riêng, nhật ký được đọc lại từ file trước khi ghi tiếp).
"""

import traceback
from contextlib import contextmanager
from datetime import datetime

from core import storage

STEP_ORDER = ["extract", "validate", "clean", "profiles", "publish"]
STEP_LABEL = {"extract": "1. Trích xuất", "validate": "2. Kiểm tra dữ liệu thô",
              "clean": "3. Làm sạch", "profiles": "4. Tính hồ sơ", "publish": "5. Công bố"}


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class RunLog:
    def __init__(self, run_id, as_of, trigger="manual"):
        self.path = storage.run_path(run_id)
        existing = storage.read_json(self.path)
        if existing:
            self.data = existing
        else:
            self.data = {"run_id": run_id, "as_of": str(as_of), "trigger": trigger,
                         "started_at": _now(), "finished_at": None, "status": "running",
                         "failed_step": None, "error": None, "steps": {}}
            self.save()

    def save(self):
        storage.write_json(self.path, self.data)

    @contextmanager
    def step(self, name):
        rec = {"name": name, "label": STEP_LABEL.get(name, name), "status": "running",
               "started_at": _now(), "finished_at": None, "duration_s": None,
               "metrics": {}, "warnings": [], "error": None, "traceback": None}
        self.data["steps"][name] = rec
        self.data["status"] = "running"
        self.save()
        t0 = datetime.now()
        try:
            yield rec
            rec["status"] = "success"
        except Exception as e:
            rec["status"] = "failed"
            rec["error"] = f"{type(e).__name__}: {e}"
            rec["traceback"] = traceback.format_exc()[-6000:]
            self.data["status"] = "failed"
            self.data["failed_step"] = name
            self.data["error"] = rec["error"]
            self.data["finished_at"] = _now()
            raise
        finally:
            rec["finished_at"] = _now()
            rec["duration_s"] = round((datetime.now() - t0).total_seconds(), 1)
            self.save()

    def finish(self, status="success"):
        self.data["status"] = status
        self.data["finished_at"] = _now()
        if status == "success":            # vd Airflow thử lại thành công sau lần lỗi đầu
            self.data["failed_step"] = None
            self.data["error"] = None
        self.save()

    @property
    def warnings(self):
        out = []
        for name in STEP_ORDER:
            s = self.data["steps"].get(name)
            if s:
                out += [f"[{s['label']}] {w}" for w in s.get("warnings", [])]
        return out
