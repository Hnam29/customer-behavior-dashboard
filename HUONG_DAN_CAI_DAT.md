# 🚀 Hướng dẫn cài đặt nhanh — Customer Behavior Analytics

> Xem [README.md](README.md) để biết đầy đủ chi tiết kỹ thuật.

---

## Yêu cầu phần mềm

| Phần mềm | Phiên bản tối thiểu | Link tải |
|---|---|---|
| **Docker Desktop** | 4.x trở lên | https://www.docker.com/products/docker-desktop |
| **Python** | 3.11 hoặc 3.12 | https://www.python.org/downloads/ (tích "Add to PATH") |
| **ODBC Driver 18 for SQL Server** | 18.x | https://aka.ms/downloadmsodbcsql |

> ⚠️ Sau khi cài Docker Desktop, vào **Settings → General** → bật **"Start Docker Desktop when you sign in"** để Airflow tự chạy khi máy khởi động lại.

---

## Bước 1 — Cấu hình kết nối

Mở file **`.env`** trong thư mục dự án bằng Notepad (hoặc VS Code) và kiểm tra / điền:

```
MSSQL_SERVER=<IP hoặc tên máy chủ SQL Server>
MSSQL_PORT=<cổng, thường 1433>
MSSQL_DATABASE=<tên CSDL>
MSSQL_USER=<tên đăng nhập>
MSSQL_PASSWORD=<mật khẩu>
```

> 💡 Nếu SQL Server cài **ngay trên máy bạn**, đổi `MSSQL_SERVER=host.docker.internal`

---

## Bước 2 — Kiểm tra kết nối (tuỳ chọn, làm trước khi build Docker)

Mở **PowerShell** tại thư mục dự án:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m pipeline.check_connection
```

Thấy vài dòng dữ liệu in ra là kết nối thành công.

---

## Bước 3 — Khởi động toàn bộ hệ thống (Docker)

```powershell
# Build image (lần đầu, mất ~5–10 phút)
docker compose build

# Khởi tạo CSDL nội bộ Airflow (lần đầu)
docker compose up airflow-init

# Chạy tất cả dịch vụ nền
docker compose up -d
```

Sau khi hoàn tất:

| Dịch vụ | Địa chỉ | Tài khoản |
|---|---|---|
| **Dashboard** | http://localhost:8501 | — |
| **Airflow** | http://localhost:8080 | Xem `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD` trong `.env` |

---

## Bước 4 — Bật lịch chạy tự động

1. Mở http://localhost:8080 → đăng nhập
2. Tìm DAG **`customer_behavior_daily`**
3. Bật công tắc sang **ON**
4. Bấm ▶ **Trigger** để chạy thử ngay một lần

Từ đó, pipeline tự chạy lúc **01:30 mỗi đêm** và gửi email tóm tắt.

---

## Các lệnh thường dùng

```powershell
# Dừng tất cả
docker compose down

# Khởi động lại sau khi tắt máy
docker compose up -d

# Xem log dashboard
docker compose logs -f dashboard

# Chạy pipeline thủ công cho một ngày cụ thể
docker compose run --rm airflow-cli python -m pipeline.run --as-of 2026-09-28

# Kiểm tra kết nối từ bên trong Docker
docker compose run --rm airflow-cli python -m pipeline.check_connection
```

---

## Xử lý sự cố nhanh

| Triệu chứng | Kiểm tra |
|---|---|
| Dashboard trắng / báo lỗi | `docker compose logs dashboard` |
| Pipeline không chạy | Vào http://localhost:8080 → xem task màu đỏ → bấm **Logs** |
| Không kết nối được SQL Server | Chạy `python -m pipeline.check_connection`, xem thông báo lỗi |
| Quên mật khẩu Airflow | Xem `AIRFLOW_ADMIN_PASSWORD` trong file `.env` |

---

*Xem thêm hướng dẫn chi tiết trong [README.md](README.md)*
