"""
Gửi email thông báo qua SMTP (Outlook/Office 365, Gmail, mail server nội bộ...).

- Lỗi: gửi ngay khi một bước thất bại (với Airflow: sau lần thử lại cuối cùng),
  ghi rõ bước nào lỗi, thông báo lỗi và lệnh để chạy lại từ bước đó.
- Thành công: gửi bản tóm tắt (có thể tắt bằng NOTIFY_ON_SUCCESS=false). Nếu có
  cảnh báo, tiêu đề email ghi [CẢNH BÁO] để dễ lọc.
Chưa cấu hình SMTP_HOST / EMAIL_TO thì chỉ in ra màn hình, không làm lỗi luồng.
"""

import html
import smtplib
import ssl
import sys
from email.message import EmailMessage

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

from core import settings
from pipeline.run_log import STEP_LABEL, STEP_ORDER

SUBJECT_PREFIX = "Dữ liệu khách hàng"


def send(subject, text, html_body=None):
    if not settings.SMTP_HOST or not settings.EMAIL_TO:
        print(f"[email] Chưa cấu hình SMTP_HOST/EMAIL_TO, bỏ qua email: {subject}")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM or settings.SMTP_USER
    msg["To"] = ", ".join(settings.EMAIL_TO)
    msg.set_content(text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    try:
        ctx = ssl.create_default_context()
        if settings.SMTP_SSL:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30, context=ctx)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30)
            if settings.SMTP_STARTTLS:
                server.starttls(context=ctx)
        with server:
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        print(f"[email] Đã gửi: {subject}")
        return True
    except Exception as e:  # noqa: BLE001  (lỗi email không được làm hỏng luồng dữ liệu)
        print(f"[email] Gửi thất bại ({type(e).__name__}: {e}): {subject}")
        return False


def _steps_rows(run):
    rows = []
    for name in STEP_ORDER:
        s = run.get("steps", {}).get(name)
        if not s:
            rows.append((STEP_LABEL[name], "chưa chạy", "", ""))
            continue
        m = s.get("metrics") or {}
        brief = {"extract": lambda: (f"{m.get('rows_total', 0):,} dòng, từ {m.get('data_first_day')} "
                                     f"đến {m.get('data_last_day')} ({m.get('days_with_data', 0):,} ngày có "
                                     f"giao dịch); lần này lấy {m.get('rows_this_run', 0):,} dòng"),
                 "validate": lambda: f"{m.get('errors', 0)} lỗi, {m.get('warnings', 0)} cảnh báo",
                 "clean": lambda: f"{m.get('rows_in', 0):,} → {m.get('rows_out', 0):,} dòng",
                 "profiles": lambda: f"{m.get('pairs', 0):,} cặp, {m.get('customers', 0):,} khách",
                 "publish": lambda: f"bản ngày {m.get('published', '')}"}[name]
        try:
            info = brief() if s["status"] == "success" else (s.get("error") or "")
        except Exception:  # noqa: BLE001
            info = ""
        status_vn = {"success": "thành công", "failed": "LỖI", "running": "đang chạy"}.get(
            s["status"], s["status"])
        rows.append((s["label"], status_vn, f"{s.get('duration_s') or 0:.0f}s", info))
    return rows


def _table_html(rows):
    tr = "".join(f"<tr><td>{html.escape(a)}</td><td>{html.escape(b)}</td>"
                 f"<td>{html.escape(c)}</td><td>{html.escape(str(d))}</td></tr>" for a, b, c, d in rows)
    return ("<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'>"
            "<tr><th>Bước</th><th>Trạng thái</th><th>Thời gian</th><th>Kết quả</th></tr>"
            f"{tr}</table>")


def _daily_stats(as_of):
    """
    Trả về dict chứa:
      - today_rows      : số giao dịch ngày as_of
      - revenue_today   : tổng doanh thu/số lượng ngày as_of (None nếu không có)
      - revenue_yesterday: tổng doanh thu/số lượng ngày liền trước
      - revenue_pct     : % thay đổi so với ngày trước
      - buyers_df       : DataFrame khách mua ngày liền trước (customer, n_orders, revenue, last_date)
      - has_amount      : bool (True nếu có cột amount)
      - prev_label      : nhãn ngày liền trước (ví dụ 'hôm qua' hoặc 'ngày GD liền trước (2026-10-02)')
      - prev_date_str   : chuỗi YYYY-MM-DD của ngày so sánh
    """
    import pandas as pd
    from core import storage

    as_of_ts  = pd.Timestamp(as_of).normalize()
    yesterday = as_of_ts - pd.Timedelta(days=1)

    df_today = storage.read_raw(since=as_of_ts,  until=as_of_ts)
    df_prev  = storage.read_raw(since=yesterday, until=yesterday)

    prev_date_str = str(yesterday.date())
    prev_label = "hôm qua"

    # Nếu hôm qua không có dữ liệu (cuối tuần / nghỉ lễ), tìm ngày gần nhất có giao dịch trong vòng 7 ngày
    if df_prev.empty:
        df_lookback = storage.read_raw(since=as_of_ts - pd.Timedelta(days=7), until=yesterday)
        if not df_lookback.empty:
            last_date = df_lookback["date"].max()
            df_prev = df_lookback[df_lookback["date"] == last_date].copy()
            prev_date_str = str(pd.Timestamp(last_date).date())
            prev_label = f"ngày GD liền trước ({prev_date_str})"

    has_amount = ("amount" in df_today.columns if not df_today.empty else False) or (
                  "amount" in df_prev.columns if not df_prev.empty else False)

    def _total(df):
        if df.empty:
            return None
        col = "amount" if "amount" in df.columns else ("quantity" if "quantity" in df.columns else None)
        if col is None:
            return None
        s = pd.to_numeric(df[col], errors="coerce").sum()
        return float(s) if not pd.isna(s) else None

    rev_today = _total(df_today)
    rev_prev  = _total(df_prev)
    if rev_today is not None and rev_prev:
        rev_pct = (rev_today - rev_prev) / rev_prev * 100
    else:
        rev_pct = None

    buyers_df = None
    if not df_prev.empty and "customer" in df_prev.columns:
        df_prev = df_prev.copy()
        df_prev["_date"] = pd.to_datetime(df_prev.get("date", prev_date_str), errors="coerce")
        val_col = "amount" if "amount" in df_prev.columns else (
                  "quantity" if "quantity" in df_prev.columns else None)
        if val_col:
            df_prev[val_col] = pd.to_numeric(df_prev[val_col], errors="coerce")
        agg = {"n_orders": ("customer", "count")}
        if val_col:
            agg["revenue"] = (val_col, "sum")
        agg["last_date"] = ("_date", "max")
        buyers_df = df_prev.groupby("customer", as_index=False).agg(**agg)
        sort_col  = "revenue" if "revenue" in buyers_df.columns else "n_orders"
        buyers_df = buyers_df.sort_values(sort_col, ascending=False)

    return {
        "today_rows":        len(df_today),
        "revenue_today":     rev_today,
        "revenue_yesterday": rev_prev,
        "revenue_pct":       rev_pct,
        "buyers_df":         buyers_df,
        "has_amount":        has_amount,
        "prev_label":        prev_label,
        "prev_date_str":     prev_date_str,
    }


def _buyers_table_html(buyers_df, has_amount):
    val_header = "Doanh thu (đ)" if has_amount else "Số lượng"
    rows_html = ""
    for _, r in buyers_df.iterrows():
        cust = html.escape(str(r["customer"]))
        n    = int(r.get("n_orders", 0))
        val  = r.get("revenue")
        try:
            val_str = f"{float(val):,.0f}" if val is not None else "—"
        except Exception:  # noqa: BLE001
            val_str = "—"
        last = str(r.get("last_date", ""))[:10]
        rows_html += (f"<tr><td>{cust}</td>"
                      f"<td style='text-align:center'>{n}</td>"
                      f"<td style='text-align:right'>{val_str}</td>"
                      f"<td style='text-align:center'>{last}</td></tr>")
    return (
        f"<table border='1' cellpadding='6' cellspacing='0' "
        f"style='border-collapse:collapse;width:100%;max-width:680px'>"
        f"<tr style='background:#f0f4f8'>"
        f"<th>Khách hàng</th><th>Số đơn</th><th>{html.escape(val_header)}</th>"
        f"<th>Lần mua gần nhất</th></tr>"
        f"{rows_html}</table>"
    )


def failure(run):
    step = run.get("failed_step") or "?"
    label = STEP_LABEL.get(step, step)
    as_of = run.get("as_of")
    remaining = ",".join(STEP_ORDER[STEP_ORDER.index(step):]) if step in STEP_ORDER else "..."
    rerun = f"python -m pipeline.run --as-of {as_of} --steps {remaining}"
    tb = (run.get("steps", {}).get(step) or {}).get("traceback") or ""
    subject = f"[LỖI] {SUBJECT_PREFIX} ngày {as_of}: lỗi ở bước {label}"
    text = (f"Luồng cập nhật dữ liệu ngày {as_of} bị lỗi ở bước {label}.\n\n"
            f"Lỗi: {run.get('error')}\n\n"
            "Dashboard vẫn hiển thị bản dữ liệu thành công gần nhất, không bị ghi đè.\n\n"
            + "\n".join(f"- {a}: {b} {c} {d}" for a, b, c, d in _steps_rows(run))
            + f"\n\nSau khi sửa, chạy lại từ bước bị lỗi:\n  {rerun}\n"
            f"hoặc bấm Clear task '{step}' trong Airflow: {settings.AIRFLOW_URL}\n\n"
            f"Mã lần chạy: {run.get('run_id')}\n\nChi tiết lỗi:\n{tb[-3000:]}")
    body = (f"<p>Luồng cập nhật dữ liệu ngày <b>{as_of}</b> bị lỗi ở bước <b>{html.escape(label)}</b>.</p>"
            f"<p><b>Lỗi:</b> {html.escape(str(run.get('error')))}</p>"
            "<p>Dashboard vẫn hiển thị bản dữ liệu thành công gần nhất, không bị ghi đè.</p>"
            + _table_html(_steps_rows(run))
            + f"<p>Sau khi sửa, chạy lại từ bước bị lỗi:<br><code>{html.escape(rerun)}</code><br>"
            f"hoặc bấm <i>Clear</i> task <code>{step}</code> trong "
            f"<a href='{settings.AIRFLOW_URL}'>Airflow</a>.</p>"
            f"<p style='color:#666'>Mã lần chạy: {html.escape(str(run.get('run_id')))}</p>"
            f"<pre style='background:#f4f4f4;padding:8px;font-size:12px'>{html.escape(tb[-3000:])}</pre>")
    return send(subject, text, body)


def success(run, warnings=None):
    warnings = warnings or []
    as_of = run.get("as_of")
    tag = "[CẢNH BÁO]" if warnings else "[OK]"
    pub = (run.get("steps", {}).get("profiles") or {}).get("metrics", {})
    st = pub.get("status_pair", {})
    due = ", ".join(f"{k}: {st.get(k, 0)}" for k in ("Quá hạn", "Sắp đến hạn", "Chưa đến hạn"))
    subject = f"{tag} {SUBJECT_PREFIX} đã cập nhật đến ngày {as_of}"

    try:
        stats = _daily_stats(as_of)
    except Exception as e:  # noqa: BLE001
        stats = None
        print(f"[email] Không lấy được số liệu ngày: {e}")

    warn_txt  = "\n".join(f"- {w}" for w in warnings) or "Không có."
    daily_txt = ""
    if stats:
        val_label = "Doanh thu" if stats["has_amount"] else "Sản lượng"
        prev_lbl  = stats.get("prev_label", "hôm qua")
        rev_pct   = stats["revenue_pct"]
        daily_txt = (
            f"\n\n── Số liệu ngày {as_of} ──\n"
            f"- Giao dịch hôm nay ({as_of}): {stats['today_rows']:,} dòng\n"
        )
        if stats["revenue_today"] is not None:
            daily_txt += f"- {val_label} hôm nay: {stats['revenue_today']:,.0f}\n"
        if stats["revenue_yesterday"] is not None:
            daily_txt += f"- {val_label} {prev_lbl}: {stats['revenue_yesterday']:,.0f}\n"
        if rev_pct is not None:
            sign = "+" if rev_pct >= 0 else ""
            daily_txt += f"- Thay đổi so với {prev_lbl}: {sign}{rev_pct:.1f}%\n"
        bd = stats.get("buyers_df")
        if bd is not None and not bd.empty:
            daily_txt += f"\nDanh sách {len(bd)} khách mua {prev_lbl}:\n"
            for _, r in bd.head(20).iterrows():
                val = r.get("revenue")
                try:
                    val_str = f"{float(val):,.0f}" if val is not None else ""
                except Exception:  # noqa: BLE001
                    val_str = ""
                last = str(r.get("last_date", ""))[:10]
                daily_txt += (f"  - {r['customer']}: {int(r.get('n_orders', 0))} đơn"
                              + (f", {val_label.lower()} {val_str}" if val_str else "")
                              + f", lần cuối {last}\n")

    text = (f"Dữ liệu đã được cập nhật đến ngày {as_of}.\n\n"
            + "\n".join(f"- {a}: {b} {c} {d}" for a, b, c, d in _steps_rows(run))
            + daily_txt
            + f"\n\nTrạng thái khách × sản phẩm: {due}\n\nCảnh báo:\n{warn_txt}\n\n"
            f"Dashboard: {settings.DASHBOARD_URL}")

    warn_html = ("<ul>" + "".join(f"<li>{html.escape(w)}</li>" for w in warnings) + "</ul>"
                 if warnings else "<p>Không có.</p>")

    daily_html = ""
    if stats:
        val_label = "Doanh thu" if stats["has_amount"] else "Sản lượng"
        prev_lbl  = stats.get("prev_label", "hôm qua")
        rev_pct   = stats["revenue_pct"]
        pct_color = "#1a7a4a" if (rev_pct or 0) >= 0 else "#b5475b"
        pct_sign  = "+" if (rev_pct or 0) >= 0 else ""
        pct_str   = (f"<b style='color:{pct_color}'>{pct_sign}{rev_pct:.1f}%</b>"
                     if rev_pct is not None else "<i>không đủ dữ liệu</i>")

        daily_html = (
            f"<hr style='border:none;border-top:1px solid #dde3ea;margin:16px 0'>"
            f"<h3 style='margin-bottom:8px'>&#128202; Số liệu ngày {html.escape(str(as_of))}</h3>"
            f"<table cellpadding='8' cellspacing='0' "
            f"style='border-collapse:collapse;margin-bottom:12px;"
            f"border:1px solid #dde3ea'>"
            f"<tr><td style='color:#5b6b7c'>Giao dịch hôm nay ({html.escape(str(as_of))})</td>"
            f"<td><b>{stats['today_rows']:,} dòng</b></td></tr>"
        )
        if stats["revenue_today"] is not None:
            daily_html += (f"<tr><td style='color:#5b6b7c'>{html.escape(val_label)} hôm nay</td>"
                           f"<td><b>{stats['revenue_today']:,.0f} đ</b></td></tr>")
        if stats["revenue_yesterday"] is not None:
            daily_html += (f"<tr><td style='color:#5b6b7c'>{html.escape(val_label)} {html.escape(prev_lbl)}</td>"
                           f"<td>{stats['revenue_yesterday']:,.0f} đ</td></tr>")
        daily_html += (f"<tr><td style='color:#5b6b7c'>Thay đổi so với {html.escape(prev_lbl)}</td>"
                       f"<td>{pct_str}</td></tr></table>")

        bd = stats.get("buyers_df")
        if bd is not None and not bd.empty:
            daily_html += (
                f"<h3 style='margin-bottom:8px'>&#128722; {len(bd)} khách mua {html.escape(prev_lbl)}</h3>"
                + _buyers_table_html(bd, stats["has_amount"])
            )

    body = (f"<p>Dữ liệu đã được cập nhật đến ngày <b>{as_of}</b>.</p>"
            + _table_html(_steps_rows(run))
            + daily_html
            + f"<p><b>Trạng thái khách x sản phẩm:</b> {html.escape(due)}</p>"
            f"<p><b>Cảnh báo:</b></p>{warn_html}"
            f"<p><a href='{settings.DASHBOARD_URL}'>Mở dashboard</a></p>")
    return send(subject, text, body)


if __name__ == "__main__":
    # Gửi email mẫu đầy đủ thông tin báo cáo: python -m pipeline.notify
    import glob
    import json
    from core import storage

    latest_info = storage.read_json(storage.latest_path()) or {}
    as_of = latest_info.get("as_of", "2026-10-05")
    run_id = latest_info.get("run_id")

    sample_run = None
    if run_id:
        sample_run = storage.read_json(storage.run_path(run_id))
    if not sample_run:
        # Tìm file run gần nhất trong runs/
        run_files = sorted(glob.glob("data/runs/*.json"))
        if run_files:
            sample_run = storage.read_json(run_files[-1])

    if not sample_run:
        sample_run = {
            "run_id": f"sample_{as_of}",
            "as_of": as_of,
            "status": "success",
            "steps": {
                "extract": {"name": "extract", "label": "1. Trích xuất", "status": "success", "duration_s": 70, "metrics": {"rows_total": 26609, "rows_this_run": 39, "data_first_day": "2017-05-01", "data_last_day": as_of, "days_with_data": 2335}},
                "validate": {"name": "validate", "label": "2. Kiểm tra dữ liệu thô", "status": "success", "duration_s": 12, "metrics": {"errors": 0, "warnings": 0}},
                "clean": {"name": "clean", "label": "3. Làm sạch", "status": "success", "duration_s": 13, "metrics": {"rows_in": 26609, "rows_out": 25938}},
                "profiles": {"name": "profiles", "label": "4. Tính hồ sơ", "status": "success", "duration_s": 1, "metrics": {"pairs": 151, "customers": 101, "status_pair": latest_info.get("status_pair", {})}},
                "publish": {"name": "publish", "label": "5. Công bố", "status": "success", "duration_s": 0, "metrics": {"published": as_of}},
            },
        }

    print(f"[email] Đang gửi email mẫu đầy đủ thông tin ngày {as_of} tới: {settings.EMAIL_TO}...")
    ok = success(sample_run, warnings=["Đây là email mẫu chứa đầy đủ các bảng và chỉ số mới nhất."])
    raise SystemExit(0 if ok else 1)
