"""
DAG Airflow: cập nhật dữ liệu hành vi khách hàng mỗi đêm, dữ liệu đến ngày T-1.

prepare -> extract -> validate -> clean -> profiles -> publish -> report

- Mỗi task chỉ gọi đúng 1 bước trong pipeline/steps.py (logic không nằm trong Airflow),
  nên có thể chạy thử từng bước bằng tay: python -m pipeline.run --steps <bước>
- Task lỗi được thử lại 2 lần, cách 10 phút. Sau lần thử cuối vẫn lỗi thì gửi email.
- Muốn chạy cho một ngày cụ thể: Trigger DAG w/ config, điền as_of = "YYYY-MM-DD".
- Muốn chạy lại từ bước lỗi: bấm vào task lỗi -> Clear (chọn Downstream).
"""

import sys
from datetime import timedelta

import pendulum
from airflow.sdk import Param, dag, get_current_context, task

sys.path.insert(0, "/opt/airflow/project")      # thư mục chứa core/ và pipeline/

TZ = pendulum.timezone("Asia/Ho_Chi_Minh")


def _info_from_context(ctx):
    """Ngày đánh giá T-1 và mã lần chạy, tính từ ngữ cảnh của lần chạy Airflow."""
    from pipeline.run import default_as_of
    as_of = (ctx["params"] or {}).get("as_of")
    if not as_of:
        ref = ctx.get("data_interval_end") or ctx.get("logical_date") or pendulum.now(TZ)
        as_of = str(default_as_of(ref))
    return {"as_of": str(as_of), "run_id": f"airflow_{ctx['run_id']}"}


def _on_failure(context):
    """Gửi email lỗi (chỉ chạy sau lần thử lại cuối cùng)."""
    from core import storage
    from pipeline import notify
    info = _info_from_context(context)
    run = storage.read_json(storage.run_path(info["run_id"]))
    if not run or run.get("status") != "failed":
        # lỗi xảy ra ngoài các bước (vd không import được): tự dựng nội dung email
        ti = context.get("task_instance")
        run = {"run_id": info["run_id"], "as_of": info["as_of"], "status": "failed",
               "failed_step": getattr(ti, "task_id", "?"),
               "error": repr(context.get("exception")), "steps": (run or {}).get("steps", {})}
    notify.failure(run)


@dag(
    dag_id="customer_behavior_daily",
    description="Trích xuất SQL Server -> kiểm tra -> làm sạch -> hồ sơ khách -> công bố",
    schedule="30 1 * * *",                       # 01:30 sáng mỗi ngày, giờ Việt Nam
    start_date=pendulum.datetime(2026, 9, 1, tz=TZ),
    catchup=False,                               # bước extract tự lấy bù ngày bị lỡ
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10),
                  "on_failure_callback": _on_failure},
    params={
        "as_of": Param(None, type=["null", "string"],
                       description="Ngày đánh giá YYYY-MM-DD. Để trống = hôm qua."),
        "full_reload": Param(False, type="boolean",
                             description="Xóa dữ liệu thô và tải lại toàn bộ lịch sử."),
    },
    tags=["customer-behavior"],
)
def customer_behavior_daily():

    @task
    def prepare():
        return _info_from_context(get_current_context())

    def _make_step(name):
        @task(task_id=name)
        def _run(info):
            from pipeline.run import run_step
            ctx = get_current_context()
            full = bool((ctx["params"] or {}).get("full_reload")) if name == "extract" else False
            log = run_step(name, info["as_of"], info["run_id"], trigger="airflow", full_reload=full)
            rec = log.data["steps"][name]
            print(f"{name}: {rec['metrics']}")
            for w in rec["warnings"]:
                print(f"CẢNH BÁO: {w}")
            return info
        return _run

    @task
    def report(info):
        from pipeline.run import finish_run
        finish_run(info["run_id"], send_email=True)

    info = prepare()
    for name in ["extract", "validate", "clean", "profiles", "publish"]:
        info = _make_step(name)(info)
    report(info)


customer_behavior_daily()
