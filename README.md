# Phân tích hành vi mua hàng: luồng dữ liệu tự động + dashboard

Mỗi đêm, luồng dữ liệu tự lấy giao dịch đến **ngày hôm qua (T-1)** từ SQL Server, kiểm tra,
làm sạch, tính hồ sơ khách hàng rồi công bố cho dashboard. Mọi kết quả lưu dạng file Parquet
trong thư mục `data/`, **không ghi gì vào SQL Server** (chỉ đọc, tài khoản chỉ cần quyền SELECT).

```
SQL Server ──► 1.Trích xuất ──► 2.Kiểm tra ──► 3.Làm sạch ──► 4.Tính hồ sơ ──► 5.Công bố ──► Dashboard
                                   │ lỗi thì dừng, dashboard giữ bản tốt gần nhất, gửi email
```

## Cấu trúc thư mục

| Thư mục / file | Nội dung |
|---|---|
| `app.py` | Dashboard Streamlit (nguồn mặc định: dữ liệu tự động; vẫn tải file lên được) |
| `core/behavior.py` | Làm sạch và tính hồ sơ khách (dùng chung cho dashboard và luồng dữ liệu) |
| `core/settings.py`, `core/storage.py` | Đọc cấu hình từ `.env`; đọc/ghi file trong `data/` |
| `pipeline/sql/extract_transactions.sql` | **Câu SQL của bạn** |
| `pipeline/steps.py` | 5 bước của luồng dữ liệu |
| `pipeline/run.py` | Chạy luồng bằng tay |
| `pipeline/check_connection.py` | Kiểm tra kết nối và câu SQL |
| `pipeline/notify.py` | Gửi email |
| `dags/customer_behavior_daily.py` | Lịch chạy trên Airflow (chỉ gọi các bước ở trên) |
| `docker-compose.yaml`, `airflow/`, `dashboard/` | Chạy Airflow 3.3.2 và dashboard bằng Docker |
| `tests/test_pipeline.py` | Kiểm thử toàn bộ luồng với nguồn giả, không cần SQL Server |

---

## Phần 1. Cài đặt trên Windows (làm một lần)

**1.1. Cài phần mềm**
- Python 3.11 hoặc 3.12 (khi cài nhớ tích *Add python.exe to PATH*).
- **ODBC Driver 18 for SQL Server** của Microsoft (tìm "Download ODBC Driver for SQL Server").
  DBeaver dùng driver riêng (JDBC) nên máy bạn có thể chưa có driver này. Python cần nó để kết nối.
- Docker Desktop (đã cài). Trong *Settings → General*, bật *Start Docker Desktop when you sign in*
  để Airflow tự chạy lại khi máy khởi động lại.

**1.2. Cài thư viện Python.** Mở PowerShell tại thư mục dự án:
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
Từ đây về sau, mỗi lần mở PowerShell mới, chạy lại `.venv\Scripts\activate` trước.

**1.3. Kiểm tra cài đặt** (không cần SQL Server):
```powershell
python -m tests.test_pipeline
```
Thấy dòng `Tất cả kiểm thử đều qua` là được.

**1.4. Khai báo cấu hình.** Sao chép `.env.example` thành `.env` rồi điền:
- `MSSQL_SERVER`, `MSSQL_PORT`, `MSSQL_DATABASE`, `MSSQL_USER`, `MSSQL_PASSWORD`: lấy trong DBeaver
  (chuột phải vào kết nối → *Edit Connection* → tab *Main*).
- `HISTORY_START`: ngày bắt đầu lấy lịch sử ở lần chạy đầu.
- `SMTP_*`, `EMAIL_TO`: thông tin email (xem mục 1.7).

**1.5. Dán câu SQL** vào `pipeline/sql/extract_transactions.sql` theo hướng dẫn ở đầu file:
đặt tên cột bằng `AS` (`[date]`, `customer`, `product`, `unit`, `quantity`, `unit_price`,
`amount`, `contract_number`) và giữ điều kiện `WHERE <cột ngày> >= :start_date AND <cột ngày> < :end_date`.

**1.6. Thử kết nối:**
```powershell
python -m pipeline.check_connection
```
Lệnh này thử kết nối, chạy câu SQL cho ngày hôm qua và in vài dòng đầu. Không ghi gì ra ổ đĩa.

**1.7. Thử email:**
```powershell
python -m pipeline.notify
```
- Office 365: `SMTP_HOST=smtp.office365.com`, `SMTP_PORT=587`, `SMTP_STARTTLS=true`. Tài khoản
  phải được bật *Authenticated SMTP* (hỏi bộ phận IT nếu báo lỗi xác thực).
- Gmail: `smtp.gmail.com`, cổng 587, dùng *App password* thay cho mật khẩu thường.

**1.8. Chạy lần đầu** (tải toàn bộ lịch sử từ `HISTORY_START`, có thể mất vài phút):
```powershell
python -m pipeline.run
```

**1.9. Mở dashboard:**
```powershell
streamlit run app.py
```
Nguồn dữ liệu mặc định là **Tự động từ SQL Server**. Muốn phân tích file riêng thì chọn **Tải file lên**.

---

## Phần 2. Chạy tự động mỗi đêm bằng Airflow (Docker)

**2.1. Điền thêm trong `.env`:** `AIRFLOW_ADMIN_PASSWORD`, `AIRFLOW_JWT_SECRET`, `FERNET_KEY`
(lệnh tạo có ghi ngay trong file). Lệnh tạo `FERNET_KEY` cần gói `cryptography`: chạy
`pip install cryptography` trong môi trường ảo trước.

**2.2. Địa chỉ SQL Server nhìn từ bên trong Docker:**
- SQL Server ở máy khác trong mạng (trường hợp thường gặp): giữ nguyên địa chỉ IP hoặc tên máy như trong DBeaver.
- SQL Server cài **ngay trên máy này**: đổi `MSSQL_SERVER=host.docker.internal`, vì bên trong
  Docker, `localhost` là chính container.
- Kết nối qua VPN: container có thể không đi qua VPN được. Khi đó hỏi IT hoặc chạy bằng Task Scheduler (mục 2.7).

**2.3. Khởi động** (PowerShell, tại thư mục dự án):
```powershell
docker compose build
docker compose up airflow-init
docker compose up -d
```
Lần build đầu mất khoảng 5–10 phút.

**2.4. Kiểm tra kết nối từ bên trong Docker:**
```powershell
docker compose run --rm airflow-cli python -m pipeline.check_connection
```

**2.5. Bật lịch chạy.** Mở http://localhost:8080, đăng nhập bằng `AIRFLOW_ADMIN_USER` /
`AIRFLOW_ADMIN_PASSWORD`, tìm DAG `customer_behavior_daily`, bật công tắc (DAG mới tạo đang tạm dừng).
Bấm *Trigger* để chạy thử một lần. Từ đó DAG tự chạy lúc **01:30 mỗi ngày** (giờ Việt Nam).
Muốn đổi giờ chạy: sửa `schedule="30 1 * * *"` trong file DAG.

**2.6. Dashboard chạy luôn trong Docker.** `docker compose up -d` bật cả dịch vụ `dashboard` tại
http://localhost:8501. Dịch vụ này tự khởi động cùng Docker Desktop và tự bật lại khi bị lỗi, không
cần mở PowerShell. Dashboard đọc thư mục `data\` ở chế độ chỉ đọc: DAG công bố bản mới thì chỉ cần
tải lại trang. Sửa `app.py`, `core\` hay `pipeline\` thì chạy `docker compose restart dashboard`.
Cổng 8501 mở cho cả mạng nội bộ (đồng nghiệp vào bằng `http://<IP máy này>:8501`); chỉ muốn xem
trên máy này thì đổi `"8501:8501"` thành `"127.0.0.1:8501:8501"` trong `docker-compose.yaml`.

**2.7. Không dùng được Docker?** Dùng Windows Task Scheduler chạy lệnh sau mỗi đêm:
```
<thư mục dự án>\.venv\Scripts\python.exe -m pipeline.run
```
Nhớ đặt *Start in* là thư mục dự án. Nhật ký và email vẫn hoạt động như khi dùng Airflow,
chỉ thiếu giao diện theo dõi và phần tự thử lại.

Máy phải bật và Docker Desktop phải đang chạy vào lúc 01:30. Nếu lỡ một đêm, lần chạy kế tiếp
**tự lấy bù** các ngày còn thiếu.

---

## Phần 3. Khi có sự cố: tìm lỗi ở đâu

1. **Email lỗi** cho biết lỗi ở bước nào, thông báo lỗi, và lệnh để chạy lại từ bước đó.
2. **Dashboard** → tab *Làm sạch dữ liệu* → *Lịch sử cập nhật tự động*: các lần chạy, từng bước,
   số liệu, cảnh báo, traceback; cùng kết quả kiểm tra dữ liệu thô.
3. **Airflow** (http://localhost:8080): bấm vào task màu đỏ → *Logs*.
4. **File nhật ký**: `data/runs/<mã lần chạy>.json`.

Khi một bước lỗi, dashboard **vẫn hiển thị bản thành công gần nhất** và có thông báo đỏ ở thanh bên.

| Lỗi ở bước | Thường do | Cách xử lý |
|---|---|---|
| 1. Trích xuất | Sai thông tin đăng nhập; SQL Server không truy cập được; câu SQL lỗi hoặc thiếu `:start_date`/`:end_date`; thiếu ODBC Driver | Chạy `python -m pipeline.check_connection` để xem lỗi cụ thể |
| 2. Kiểm tra dữ liệu thô | Câu SQL đổi tên cột; ngày không đọc được; dữ liệu T-1 chưa có | Sửa câu SQL, hoặc chờ nguồn nạp xong rồi chạy lại |
| 3. Làm sạch | Dữ liệu bất thường (ví dụ mọi dòng bị loại) | Xem tab *Làm sạch dữ liệu* |
| 4–5 | Hiếm gặp: đầy ổ đĩa, file bị khóa | Kiểm tra dung lượng thư mục `data/` |

**Cảnh báo** (không làm dừng luồng, có ghi trong email): ngày T-1 không có giao dịch (có thể là
ngày nghỉ), số dòng T-1 chênh nhiều so với cùng thứ của 8 tuần trước, tỷ lệ ô trống cao, bước làm
sạch loại trên 10% số dòng.

Một số lỗi kết nối thường gặp:
- `Data source name not found`: chưa cài ODBC Driver 18, hoặc `MSSQL_DRIVER` gõ sai tên.
- `certificate verify failed`: đặt `MSSQL_TRUST_SERVER_CERTIFICATE=yes`.
- `Login timeout expired`: sai địa chỉ hoặc cổng, tường lửa chặn cổng 1433, hoặc (trong Docker)
  cần dùng `host.docker.internal`.

## Chạy lại bằng tay

```powershell
python -m pipeline.run --as-of 2026-09-28                          # chạy lại cả ngày 28/09
python -m pipeline.run --as-of 2026-09-28 --steps clean,profiles,publish   # từ bước làm sạch
python -m pipeline.run --full-reload                                # tải lại toàn bộ lịch sử
python -m pipeline.run --no-email                                   # không gửi email
```
Trên Airflow: bấm vào task lỗi → *Clear* (chọn *Downstream*) để chạy lại từ task đó.
Muốn chạy cho một ngày cụ thể: *Trigger DAG w/ config* và điền `as_of`.

## Dữ liệu được lưu những gì

- `data/raw/`: dữ liệu thô, mỗi ngày giao dịch một file, cùng `manifest.json` ghi ngày nào đã lấy.
  Mỗi lần chạy, luồng lấy các ngày chưa có cộng thêm `REEXTRACT_DAYS` ngày gần nhất, phòng khi lần
  trước chạy lúc nguồn chưa nạp đủ.
- `data/snapshots/<ngày>/`: kết quả kiểm tra, dữ liệu sạch, báo cáo làm sạch, hồ sơ khách.
  Giữ đầy đủ `SNAPSHOT_KEEP` bản gần nhất. Bản cũ hơn chỉ giữ hồ sơ khách (file nhỏ), để sau này
  kiểm chứng xem các cảnh báo "Sắp đến hạn" có đúng không.
- `data/latest.json`: bản đang được dashboard hiển thị.

Hồ sơ "chính thức" trong `snapshots/` dùng các ngưỡng trong `.env`. Trên dashboard, bạn vẫn kéo
thanh trượt để thử các ngưỡng khác; dashboard tính lại từ dữ liệu sạch và không làm thay đổi bản chính thức.
