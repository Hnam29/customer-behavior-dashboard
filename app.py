"""
Dashboard: Tính cách mua hàng của từng khách
Chạy:  pip install -r requirements.txt
       streamlit run app.py
"""

import io

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core import storage
from core.behavior import (DATE_FORMATS, DOW_VN, FIELD_LABEL, REQUIRED_COLS, SEG_ORDER,
                           STATUS_ORDER, STD_COLS, classify_category, clean_transactions, compute_profiles,
                           compute_period_growth, describe_profile, due_evidence, fmt_num, make_sample_data,
                           monthly_matrix, period_matrix, split_products_by_unit)
from pipeline.run_log import STEP_LABEL, STEP_ORDER

st.set_page_config(page_title="Tính cách mua hàng", page_icon="🧭", layout="wide")

# ------------------------------------------------------------------
# Giao diện chung
# ------------------------------------------------------------------
INK, MUTED, GRID, PRIMARY = "#1D2A3A", "#5B6B7C", "#E3E9ED", "#0E6E8C"
FONT = "Be Vietnam Pro, system-ui, sans-serif"
SEG_COLOR = dict(zip(SEG_ORDER, ["#1F7A5C", "#2F6FB2", "#C7911C", "#B5475B", "#A3ADB8"]))
STATUS_COLOR = {"Chưa đến hạn": "#1F7A5C", "Sắp đến hạn": "#C7911C", "Quá hạn": "#B5475B",
                "Khó đoán thời điểm": "#7C8A99", "Chưa đủ dữ liệu": "#B8C1CA",
                "Đã ngừng mua": "#3A4654"}

st.markdown("""
<style>
.block-container {padding-top: 2.2rem; max-width: 1440px;}

/* ── Metric cards: background + rounded corners ── */
[data-testid="stMetric"] {
    background: #F4F7FA;
    border: 1px solid #DDE3EA;
    border-radius: 12px;
    padding: 0.85rem 1.1rem 0.75rem 1.1rem;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    transition: box-shadow 0.2s;
}
[data-testid="stMetric"]:hover {
    box-shadow: 0 3px 10px rgba(0,0,0,0.10);
}
[data-testid="stMetricValue"] {font-size: 1.55rem; font-weight: 600; color: #1D2A3A;}
[data-testid="stMetricLabel"] p {color: #5B6B7C;}
[data-testid="stMetricDelta"] {font-size: 0.85rem;}

.sub {color: #5B6B7C; font-size: 0.95rem; margin-top: -0.6rem;}
.badge {display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
        color: #fff; font-size: 0.85rem; font-weight: 500; margin-right: 0.4rem;}
</style>
""", unsafe_allow_html=True)


def style(fig, height=380, legend=True):
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=100 if legend else 52, b=8),
        font=dict(family=FONT, color=INK, size=13), title_font=dict(size=15),
        title_y=0.99, title_yanchor="top",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FFFFFF",
        hoverlabel=dict(font_family=FONT), showlegend=legend,
    )
    if legend:
        fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None))
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    return fig


NC = st.column_config.NumberColumn


def badge(text, color):
    return f"<span class='badge' style='background:{color}'>{text}</span>"


# ------------------------------------------------------------------
# Đọc dữ liệu
# ------------------------------------------------------------------
COL_LABEL = {"date": "Ngày giao dịch", "customer": "Khách hàng", "product": "Nhóm sản phẩm",
             "unit": "Đơn vị tính", "quantity": "Số lượng", "unit_price": "Đơn giá",
             "amount": "Thành tiền", "contract_number": "Số hợp đồng",
             "category": "Nhóm sản phẩm", "product_name": "Sản phẩm cụ thể",
             "ingredient": "Nguyên liệu gốc"}
GUESS = {
    "date": ["date", "ngay", "ngày", "ngay_ct", "ngày ct", "ngày chứng từ", "ngay chung tu"],
    "customer": ["customer", "khach hang", "khách hàng", "ma_kh", "mã kh", "tên kh", "kh", "client"],
    "product": ["category", "nhom san pham", "nhóm sản phẩm", "nhom sp", "nhóm sp", "nhom hang", "nhóm hàng",
                "product", "san pham", "sản phẩm", "mat hang", "mặt hàng", "ten hang",
                "tên hàng", "ma_hang", "mã hàng", "sku", "sp", "item"],
    "unit": ["unit", "uom", "dvt", "đvt", "don vi tinh", "đơn vị tính", "don vi", "đơn vị"],
    "quantity": ["quantity", "qty", "so luong", "số lượng", "sl"],
    "unit_price": ["unit_price", "don gia", "đơn giá", "price", "gia", "giá"],
    "amount": ["amount", "thanh tien", "thành tiền", "doanh thu", "revenue"],
    "contract_number": ["contract_number", "contract_no", "contract", "so hop dong",
                         "số hợp đồng", "so hd", "số hđ", "ma hop dong", "mã hợp đồng",
                         "so_hd", "ma_hd", "hd"],
    "category": ["category", "nhom san pham", "nhóm sản phẩm", "nhom sp", "nhóm sp", "nhom hang", "nhóm hàng"],
    "product_name": ["product_name", "product", "san pham", "sản phẩm", "ten hang", "tên hàng", "sku"],
    "ingredient": ["ingredient", "nguyen lieu", "nguyên liệu", "vat tu", "vật tư", "tenvattu"],
    "paper_type": ["paper_type", "loai giay", "loại giấy", "chat lieu giay", "chất liệu giấy"],
}


def guess_col(cols, std):
    norm = {c: str(c).strip().lower() for c in cols}
    for key in GUESS[std]:
        for c, n in norm.items():
            if n == key:
                return c
    for key in GUESS[std]:
        if len(key) <= 4:          # từ ngắn (vd "unit") chỉ khớp chính xác, tránh nhầm "unit_price"
            continue
        for c, n in norm.items():
            if key in n:
                return c
    return None


@st.cache_data(show_spinner=False)
def list_sheets(data):
    return pd.ExcelFile(io.BytesIO(data)).sheet_names


@st.cache_data(show_spinner="Đang đọc file...")
def read_raw(data, name, sheet):
    if name.lower().endswith(".csv"):
        return pd.read_csv(io.BytesIO(data))
    return pd.read_excel(io.BytesIO(data), sheet_name=sheet)


@st.cache_data(show_spinner=False)
def sample_data():
    return make_sample_data()


@st.cache_data(show_spinner="Đang làm sạch dữ liệu...")
def clean_cached(raw, mapping_items, drop_dup, date_format):
    return clean_transactions(raw, dict(mapping_items), drop_exact_duplicates=drop_dup,
                              date_format=date_format)


@st.cache_data(show_spinner=False)
def split_cached(df):
    return split_products_by_unit(df)


@st.cache_data(show_spinner="Đang đọc dữ liệu tự động...")
def load_snapshot(run_id, snapshot):
    """run_id nằm trong khóa bộ nhớ đệm: có bản công bố mới là tự đọc lại."""
    folder = storage.data_dir() / snapshot
    return pd.read_parquet(folder / "clean.parquet"), storage.load_report(folder)


@st.cache_data(show_spinner="Đang tính hồ sơ mua hàng...")
def profiles_cached(dfw, level, **kw):
    return compute_profiles(dfw, level=level, **kw)


# ------------------------------------------------------------------
# Thanh bên
# ------------------------------------------------------------------
SRC_AUTO, SRC_FILE = "Tự động từ SQL Server", "Tải file lên"
latest = storage.read_latest()
runs_recent = storage.list_runs(30)

with st.sidebar:
    st.header("Dữ liệu")
    src = st.radio("Nguồn dữ liệu", [SRC_AUTO, SRC_FILE], index=0 if latest else 1,
                   help="Tự động: dữ liệu đã được luồng dữ liệu hằng đêm trích xuất và làm sạch "
                        "đến ngày hôm qua. Tải file lên: phân tích một file Excel/CSV bất kỳ.")
auto_mode = src == SRC_AUTO
as_of_limit = None

if auto_mode:
    if not latest:
        st.title("Phân tích hành vi mua hàng của khách hàng")
        st.info("Chưa có dữ liệu tự động. Hãy chạy luồng dữ liệu lần đầu bằng lệnh "
                "`python -m pipeline.run` (xem README), hoặc chọn **Tải file lên** ở thanh bên.")
        st.stop()
    try:
        df, report = load_snapshot(latest["run_id"], latest["snapshot"])
    except Exception as e:  # noqa: BLE001
        st.error(f"Không đọc được bản dữ liệu ngày {latest.get('as_of')}: {e}")
        st.stop()
    as_of_limit = pd.Timestamp(latest["as_of"]).date()
    source = f"SQL Server (dữ liệu đến {as_of_limit:%d/%m/%Y})"
    with st.sidebar:
        pub = pd.Timestamp(latest["published_at"])
        st.caption(f"Dữ liệu đến ngày **{as_of_limit:%d/%m/%Y}**, cập nhật lúc {pub:%H:%M %d/%m/%Y}.")
        last = runs_recent[0] if runs_recent else None
        if last and last.get("status") == "failed" and last.get("run_id") != latest.get("run_id"):
            step = STEP_LABEL.get(last.get("failed_step"), last.get("failed_step"))
            st.error(f"Lần cập nhật gần nhất (ngày {last.get('as_of')}) bị lỗi ở bước {step}. "
                     "Đang hiển thị bản thành công trước đó. Xem tab Làm sạch dữ liệu.")
        elif last and last.get("status") == "running":
            st.info("Đang có một lần cập nhật chạy dở hoặc bị ngắt giữa chừng.")
else:
    with st.sidebar:
        up = st.file_uploader("File giao dịch (Excel hoặc CSV)", type=["xlsx", "csv"])
        if up is None:
            st.caption("Chưa có file nên đang hiển thị dữ liệu mẫu. Tải file của bạn lên để phân tích.")
            raw = sample_data()
            mapping = {c: (c if c in raw.columns else None) for c in STD_COLS}
            source = "Dữ liệu mẫu"
        else:
            data = up.getvalue()
            sheet = None
            if up.name.lower().endswith(".xlsx"):
                sheets = list_sheets(data)
                sheet = st.selectbox("Sheet", sheets,
                                     index=sheets.index("Clean") if "Clean" in sheets else 0)
            raw = read_raw(data, up.name, sheet)
            cols = list(raw.columns)
            with st.expander("Ghép cột trong file", expanded=True):
                st.caption("Cột có dấu * là bắt buộc.")
                mapping = {}
                for c in STD_COLS:
                    opts = ["(không có)"] + cols
                    g = guess_col(cols, c)
                    sel = st.selectbox(COL_LABEL[c] + (" *" if c in REQUIRED_COLS else ""), opts,
                                       index=opts.index(g) if g in opts else 0, key=f"map_{c}")
                    mapping[c] = None if sel == "(không có)" else sel
            source = up.name

        date_format = st.selectbox(
            "Định dạng ngày trong file", list(DATE_FORMATS), format_func=DATE_FORMATS.get,
            help="Chỉ áp dụng khi cột ngày là chữ (vd 03/05/2024). Ô đã là kiểu ngày của Excel "
                 "được giữ nguyên. Nếu chắc chắn file là mm/dd/yyyy, hãy chọn hẳn định dạng đó.")
        drop_dup = st.checkbox(
            "Xóa các dòng trùng lặp hoàn toàn", value=True,
            help="Hai dòng giống nhau ở mọi cột (kể cả số hợp đồng) thường là lỗi xuất dữ liệu. "
                 "Tắt đi nếu file có những dòng giống hệt nhau nhưng hợp lệ. Danh sách dòng trùng "
                 "xem ở tab Làm sạch dữ liệu.")

    missing_req = [COL_LABEL[c] for c in REQUIRED_COLS if mapping.get(c) is None]
    if missing_req:
        st.error(f"Chưa chọn cột cho: {', '.join(missing_req)}. Hãy ghép cột ở thanh bên trái.")
        st.stop()
    chosen = [v for v in mapping.values() if v is not None]
    if len(chosen) != len(set(chosen)):
        st.warning("Có một cột trong file đang được ghép cho nhiều trường. "
                   "Hãy kiểm tra lại phần ghép cột.")
    try:
        df, report = clean_cached(raw, tuple(mapping.items()), drop_dup, date_format)
    except Exception as e:  # noqa: BLE001
        st.error(f"Không đọc được dữ liệu: {e}")
        st.stop()

if df.empty:
    st.error("Sau khi làm sạch không còn dòng nào. Hãy kiểm tra phần ghép cột và định dạng ngày.")
    st.stop()

# Dùng category làm chiều phân tích sản phẩm chính (Nhóm sản phẩm)
# Nếu dữ liệu chưa có category hoặc toàn bộ là 'Khác', tự động phân loại từ tên sản phẩm
if "category" not in df.columns or (df["category"].astype(str).str.strip().isin(["", "Khác", "khác", "nan", "None"])).all():
    df["category"] = classify_category(df["product"])

# Chuẩn hóa cột paper_type (có thể NULL từ SQL hoặc không có khi upload file)
if "paper_type" not in df.columns:
    df["paper_type"] = None

if "product" in df.columns and "product_name" not in df.columns:
    df = df.rename(columns={"product": "product_name"})
df["product"] = df["category"]
if "product_name" in df.columns:
    mask = df["product"].isna() | (df["product"].astype(str).str.strip().isin(["", "nan", "None"]))
    df.loc[mask, "product"] = df.loc[mask, "product_name"]

# Nếu paper_type trong dữ liệu còn thiếu, trích xuất thêm từ product_name / ingredient
_pn = df["product_name"].fillna("").astype(str).str.lower() if "product_name" in df.columns else pd.Series("", index=df.index)
_ing = df["ingredient"].fillna("").astype(str).str.lower() if "ingredient" in df.columns else pd.Series("", index=df.index)
_source_text = _pn + " " + _ing

_inferred_pt = np.where(_source_text.str.contains("duplex"), "Duplex",
               np.where(_source_text.str.contains("ivory"), "Ivory",
               np.where(_source_text.str.contains(r"kraft|kraf"), "Kraft",
               np.where(_source_text.str.contains(r"couche|couches"), "Couché",
               np.where(_source_text.str.contains("offset"), "Offset",
               np.where(_source_text.str.contains("decal"), "Decal",
               np.where(_source_text.str.contains(r"carbon|cacbon"), "Carbon",
               np.where(_source_text.str.contains("bristol"), "Bristol",
               np.where(_source_text.str.contains(r"c2s|c1s"), "C2S/C1S",
               np.where(_source_text.str.contains(r"ford|fort"), "Ford", ""))))))))))

_mask_need_pt = df["paper_type"].isna() | (df["paper_type"].astype(str).str.strip().isin(["", "nan", "None"]))
df.loc[_mask_need_pt & (_inferred_pt != ""), "paper_type"] = _inferred_pt[_mask_need_pt & (_inferred_pt != "")]

has_paper_type = df["paper_type"].notna().any() and (df["paper_type"].astype(str).str.strip() != "").any()

has_amount = report["has_amount"]
multi_unit = report["multi_unit_products"]

with st.sidebar:
    fmt_msg = {"mdy": "đọc theo mm/dd/yyyy", "dmy": "đọc theo dd/mm/yyyy",
               "excel": "cột ngày đã ở kiểu ngày (Excel/database)",
               "iso": "đọc theo yyyy-mm-dd"}[report["date_format_used"]]
    st.caption(f"Ngày giao dịch: {fmt_msg}.")
    if report["bad_date"] > 0.05 * report["rows_in"]:
        st.warning(f"{fmt_num(report['bad_date'])} dòng không đọc được ngày. "
                   "Có thể định dạng ngày đang chọn chưa đúng với file.")
    if report["date_ambiguous"]:
        st.warning("Không tự nhận diện được ngày là mm/dd hay dd/mm vì mọi giá trị đều ≤ 12. "
                   "Đang tạm đọc theo dd/mm/yyyy. Hãy chọn đúng định dạng ở ô bên trên.")
    split_unit = False
    if multi_unit:
        split_unit = st.checkbox(
            f"Tách theo đơn vị tính ({len(multi_unit)} nhóm có nhiều đơn vị)",
            value=True, help="Thêm [đơn vị] vào cột Sản phẩm để phân biệt, ví dụ "
                             "'HOP CARTON 3 LOP [cái]' và 'HOP CARTON 3 LOP [thùng]'. "
                             "Cột Nhóm sản phẩm (category) giữ nguyên.")
if split_unit:
    df = split_cached(df)

with st.sidebar:
    st.header("Phạm vi")
    dmin, dmax = df["date"].min().date(), df["date"].max().date()
    if as_of_limit is not None:          # tự động: ngày đánh giá là T-1, kể cả khi hôm đó không bán
        dmax = max(dmax, as_of_limit)
    rng = st.date_input("Khoảng thời gian phân tích", value=(dmin, dmax),
                        min_value=dmin, max_value=dmax, format="DD/MM/YYYY",
                        help="Ngày cuối của khoảng là ngày dùng để đánh giá trạng thái "
                             "(sắp đến hạn, quá hạn...).")
    start, end = (rng if isinstance(rng, tuple) and len(rng) == 2 else (dmin, dmax))

    level_label = st.radio("Phân tích theo", ["Khách hàng × Nhóm sản phẩm", "Khách hàng (gộp nhóm SP)"])
    level = "pair" if level_label.startswith("Khách hàng ×") else "customer"

    vb_opts = ["Số lượng", "Thành tiền"] if has_amount else ["Số lượng"]
    vb_label = st.radio(
        "Đo khối lượng mỗi lần mua bằng", vb_opts,
        index=1 if (level == "customer" and has_amount) else 0,
        help="Khi gộp nhiều nhóm sản phẩm khác đơn vị (tờ, kg, hộp), nên đo bằng thành tiền.")
    vb = "qty" if vb_label == "Số lượng" else "amount"
    vol_unit = "đơn vị" if vb == "qty" else "đồng"

    with st.expander("Ngưỡng phân loại"):
        st.caption(
            "**CV (hệ số biến thiên)** đo mức độ dao động so với mức trung bình — "
            "bằng độ lệch chuẩn chia cho trung bình.\n\n"
            "**Ví dụ thời gian:** khách mua cách nhau 29 → 31 → 30 → 28 ngày có CV ≈ 0.04 (rất đều). "
            "Khách mua cách nhau 10 → 5 → 60 → 45 ngày có CV ≈ 0.80 (thất thường).\n\n"
            "**Ví dụ khối lượng:** mỗi lần mua 500 → 490 → 510 → 505 đơn vị có CV ≈ 0.01 (rất ổn định). "
            "500 → 50 → 1200 → 300 đơn vị có CV ≈ 0.96 (dao động nhiều).\n\n"
            "Ngưỡng mặc định 0.5 có nghĩa: nếu độ dao động nhỏ hơn 50% mức trung bình thì coi là đều/ổn định."
        )
        min_orders = st.slider("Số lần mua tối thiểu để đánh giá", 3, 12, 5)
        timing_cv  = st.slider("CV thời gian ≤ ngưỡng này → coi là \"mua đều\"", 0.10, 1.50, 0.50, 0.05)
        qty_cv     = st.slider("CV khối lượng ≤ ngưỡng này → coi là \"ổn định\"", 0.10, 1.50, 0.50, 0.05)
        k          = st.slider("Độ rộng cửa sổ đến hạn (× độ lệch chuẩn)", 0.5, 2.0, 1.0, 0.1)
        churn_days = st.number_input("Coi là ngừng mua nếu im lặng quá (ngày)", 60, 3000, 365, 15)
        churn_mult = st.slider("hoặc quá bao nhiêu lần chu kỳ bình thường", 2.0, 10.0, 5.0, 0.5)

dfw = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
if dfw[dfw["quantity"] > 0].empty:
    st.warning("Không có giao dịch mua nào trong khoảng thời gian đã chọn.")
    st.stop()

as_of = pd.Timestamp(end)
params = dict(vol_basis=vb, min_orders=min_orders, timing_cv=timing_cv, qty_cv=qty_cv, k=k,
              churn_days=int(churn_days), churn_mult=churn_mult, as_of=as_of)
prof, orders = profiles_cached(dfw, level, **params)
prof_c, orders_c = profiles_cached(dfw, "customer", **params)
prof_p, orders_p = profiles_cached(dfw, "pair", **params)

# Bổ sung product_name (tên sản phẩm cụ thể) vào hồ sơ cặp để hiển thị
if "product_name" in dfw.columns:
    _pname = (dfw.dropna(subset=["product_name"])
                 .groupby(["customer", "product"])["product_name"]
                 .first().reset_index())
    prof_p = prof_p.merge(_pname, on=["customer", "product"], how="left")
    if level == "pair":
        prof = prof_p  # prof_p đã có product_name

value_col = "total_amount" if has_amount else "total_qty"
value_name = "giá trị" if has_amount else "sản lượng"

# ------------------------------------------------------------------
# Tiêu đề
# ------------------------------------------------------------------
st.markdown("<h1 style='text-align: center;'>Hồ sơ mua hàng của khách</h1>",
            unsafe_allow_html=True)
st.markdown(
    f"<p class='sub' style='text-align: center;'>{source}: {fmt_num(len(dfw))} dòng giao dịch từ {start:%d/%m/%Y} "
    f"đến {end:%d/%m/%Y}. Trạng thái được đánh giá tại ngày {end:%d/%m/%Y}.</p>",
    unsafe_allow_html=True)

st.caption(f"Dùng {fmt_num(report['rows_out'])} / {fmt_num(report['rows_in'])} dòng "
           + ("trong dữ liệu trích xuất" if auto_mode else "trong file")
           + " sau khi làm sạch.")

# ── Optional tab toggles ──────────────────────────────────────────
_opt_cols = st.columns([1, 1, 6])
show_tab_clean = _opt_cols[0].checkbox("📋 Tab làm sạch dữ liệu", value=False,
    help="Hiện tab chi tiết các bước làm sạch dữ liệu")
show_tab_help  = _opt_cols[1].checkbox("❓ Tab giải thích chỉ số", value=False,
    help="Hiện tab giải thích các chỉ số và thuật ngữ")

_tab_names = ["Tổng quan", "Bảng hồ sơ khách", "Chi tiết một khách", "Lịch sử theo tháng"]
if show_tab_clean:
    _tab_names = ["Làm sạch dữ liệu"] + _tab_names
if show_tab_help:
    _tab_names = _tab_names + ["Giải thích chỉ số"]

_tabs = st.tabs(_tab_names)
_tidx = 0
tab_clean  = _tabs[_tab_names.index("Làm sạch dữ liệu")] if show_tab_clean else None
tab_over   = _tabs[_tab_names.index("Tổng quan")]
tab_table  = _tabs[_tab_names.index("Bảng hồ sơ khách")]
tab_detail = _tabs[_tab_names.index("Chi tiết một khách")]
tab_month  = _tabs[_tab_names.index("Lịch sử theo tháng")]
tab_help   = _tabs[_tab_names.index("Giải thích chỉ số")] if show_tab_help else None


# ------------------------------------------------------------------
# TAB 0: Làm sạch dữ liệu
# ------------------------------------------------------------------
REMOVED_CFG = {
    "source_row": (NC("STT dòng", format="%d",
                      help="Thứ tự dòng trong dữ liệu trích xuất (sắp theo ngày giao dịch)")
                   if auto_mode else
                   NC("Dòng trong file", format="%d", help="Số dòng trong file gốc (dòng 1 là tiêu đề)")),
    "first_row": NC("Trùng với dòng", format="%d"),
    "step": st.column_config.TextColumn("Bước"),
    "reason": st.column_config.TextColumn("Lý do"),
    "date": st.column_config.DateColumn("Ngày", format="DD/MM/YYYY"),
    "customer": st.column_config.TextColumn("Khách hàng"),
    "category": st.column_config.TextColumn("Nhóm sản phẩm"),
    "product": st.column_config.TextColumn("Sản phẩm"),
    "product_name": st.column_config.TextColumn("Sản phẩm"),
    "unit": st.column_config.TextColumn("Đơn vị"),
    "quantity": NC("Số lượng", format="localized"),
    "unit_price": NC("Đơn giá", format="localized"),
    "amount": NC("Thành tiền", format="localized"),
    "contract_number": st.column_config.TextColumn("Số hợp đồng"),
}


STATUS_VN = {"success": "Thành công", "failed": "Lỗi", "running": "Đang chạy / bị ngắt"}


def render_pipeline_status():
    """Lịch sử các lần cập nhật tự động và kết quả kiểm tra dữ liệu thô của bản đang xem."""
    failed_last = bool(runs_recent) and runs_recent[0].get("status") == "failed"
    with st.expander("Lịch sử cập nhật tự động (luồng dữ liệu hằng đêm)", expanded=failed_last):
        if not runs_recent:
            st.caption("Chưa có lần chạy nào.")
            return
        rows = []
        for r_ in runs_recent:
            steps_ = r_.get("steps", {})
            n_warn = sum(len(x.get("warnings", [])) for x in steps_.values())
            dur = sum((x.get("duration_s") or 0) for x in steps_.values())
            rows.append({"as_of": r_.get("as_of"), "status": STATUS_VN.get(r_.get("status"), r_.get("status")),
                         "failed": STEP_LABEL.get(r_.get("failed_step"), "") if r_.get("failed_step") else "",
                         "error": r_.get("error") or "", "warnings": n_warn,
                         "started": r_.get("started_at"), "duration": dur,
                         "trigger": r_.get("trigger"), "run_id": r_.get("run_id")})
        runs_df = pd.DataFrame(rows)
        runs_df["started"] = pd.to_datetime(runs_df["started"], errors="coerce", utc=True)
        st.dataframe(runs_df, hide_index=True, width="stretch", column_config={
            "as_of": st.column_config.TextColumn("Ngày dữ liệu"),
            "status": st.column_config.TextColumn("Kết quả"),
            "failed": st.column_config.TextColumn("Lỗi ở bước"),
            "error": st.column_config.TextColumn("Thông báo lỗi", width="large"),
            "warnings": NC("Cảnh báo", format="%d"),
            "started": st.column_config.DatetimeColumn("Bắt đầu", format="HH:mm DD/MM/YYYY"),
            "duration": NC("Thời gian (giây)", format="%.0f"),
            "trigger": st.column_config.TextColumn("Chạy bởi"),
            "run_id": st.column_config.TextColumn("Mã lần chạy"),
        })
        pick = st.selectbox("Xem chi tiết lần chạy", [r_["run_id"] for r_ in runs_recent],
                            format_func=lambda rid: next(
                                f"{x.get('as_of')} | {STATUS_VN.get(x.get('status'), '')} | {rid}"
                                for x in runs_recent if x["run_id"] == rid))
        run = next(x for x in runs_recent if x["run_id"] == pick)
        srows = []
        for name in STEP_ORDER:
            s_ = run.get("steps", {}).get(name)
            if not s_:
                srows.append({"step": STEP_LABEL[name], "status": "Chưa chạy"})
                continue
            srows.append({"step": s_["label"], "status": STATUS_VN.get(s_["status"], s_["status"]),
                          "duration": s_.get("duration_s"),
                          "metrics": ", ".join(f"{k}: {v}" for k, v in (s_.get("metrics") or {}).items()
                                               if not isinstance(v, (dict, list))),
                          "warnings": " | ".join(s_.get("warnings") or []),
                          "error": s_.get("error") or ""})
        st.dataframe(pd.DataFrame(srows).fillna({"metrics": "", "warnings": "", "error": ""}), hide_index=True, width="stretch", column_config={
            "step": st.column_config.TextColumn("Bước"),
            "status": st.column_config.TextColumn("Kết quả"),
            "duration": NC("Giây", format="%.1f"),
            "metrics": st.column_config.TextColumn("Số liệu", width="large"),
            "warnings": st.column_config.TextColumn("Cảnh báo", width="medium"),
            "error": st.column_config.TextColumn("Lỗi", width="medium"),
        })
        tb = next((x.get("traceback") for x in run.get("steps", {}).values() if x.get("traceback")), None)
        if tb:
            st.code(tb[-3000:], language="text")

        val = storage.read_json(storage.data_dir() / latest["snapshot"] / "validation.json")
        if val:
            st.markdown(f"**Kiểm tra dữ liệu thô của bản đang xem (ngày {val['as_of']})**")
            vdf = pd.DataFrame(val["checks"])
            vdf["result"] = np.where(vdf["passed"], "Đạt",
                                     np.where(vdf["level"] == "error", "Lỗi",
                                              np.where(vdf["level"] == "warning", "Cảnh báo", "")))
            vdf["level"] = vdf["level"].map({"error": "Bắt buộc", "warning": "Cảnh báo",
                                             "info": "Thông tin"})
            st.dataframe(vdf[["check", "level", "result", "detail"]], hide_index=True, width="stretch",
                         column_config={"check": st.column_config.TextColumn("Kiểm tra"),
                                        "level": st.column_config.TextColumn("Mức"),
                                        "result": st.column_config.TextColumn("Kết quả"),
                                        "detail": st.column_config.TextColumn("Chi tiết", width="large")})


def _csv(frame, cfg):
    out = frame.copy()
    out.columns = [cfg[c]["label"] if c in cfg else c for c in out.columns]
    return out.to_csv(index=False).encode("utf-8-sig")


if tab_clean is not None:
  with tab_clean:
    steps = report["steps"]
    removed = report["removed"]
    mapped_now = report["mapped"]
    if auto_mode:
        render_pipeline_status()
    scope_txt = (f"toàn bộ dữ liệu trích xuất đến ngày {as_of_limit:%d/%m/%Y}" if auto_mode
                 else "toàn bộ file")
    st.markdown(
        "Dữ liệu được làm sạch qua **3 bước theo đúng thứ tự** dưới đây. Mỗi bước chỉ xét các dòng "
        f"còn lại sau bước trước. Trang này tính trên **{scope_txt}**, không phụ thuộc khoảng thời "
        "gian ở thanh bên.")

    left, right = st.columns([3, 2], gap="large")
    with left:
        funnel = steps.iloc[:-1]
        labels = ["Tổng số dòng trong file", "Còn lại sau bước 1 (trùng lặp)",
                  "Còn lại sau bước 2 (dòng âm)", "Còn lại sau bước 3 = dùng phân tích"]
        fig = go.Figure(go.Funnel(
            y=labels[:len(funnel)], x=funnel["remaining"],
            textinfo="value+percent initial", texttemplate="%{value:,} dòng (%{percentInitial:.1%})",
            marker=dict(color=["#9FB3C0", "#6F94A8", "#3F7690", PRIMARY][:len(funnel)]),
            connector=dict(line=dict(color=GRID))))
        fig.update_layout(title="Số dòng qua từng bước")
        st.plotly_chart(style(fig, 330, legend=False), width="stretch")
    with right:
        tbl = steps.iloc[1:-1].rename(columns={"step": "Bước", "removed": "Số dòng bị loại",
                                               "remaining": "Còn lại"})
        st.markdown(" ")
        st.dataframe(tbl, hide_index=True, width="stretch", column_config={
            "Số dòng bị loại": NC(format="localized"), "Còn lại": NC(format="localized")})
        st.metric("Dòng dùng để phân tích",
                  f"{fmt_num(report['rows_out'])} / {fmt_num(report['rows_in'])}",
                  help="Sau khi làm sạch / tổng số dòng trong file")

    # ---- Bước 1 ----
    st.subheader("Bước 1. Loại dòng trùng lặp")
    compared = ", ".join(FIELD_LABEL[c].lower() for c in mapped_now)
    st.markdown(
        f"Hai dòng được coi là trùng khi **giống nhau ở mọi cột đã ghép** ({compared}), sau khi đã "
        "chuẩn hóa chữ và bỏ khoảng trắng thừa. Dòng xuất hiện đầu tiên được giữ lại.")
    if "contract_number" not in mapped_now:
        st.caption("File chưa ghép cột số hợp đồng, nên hai dòng giống hệt nhau của hai hợp đồng "
                   "khác nhau cũng bị coi là trùng. Nên ghép cột số hợp đồng nếu file có.")
    if not report["drop_duplicates"]:
        st.warning(f"Tìm thấy {fmt_num(report['dup_found'])} dòng trùng nhưng **chưa xóa** vì tùy chọn "
                   "xóa dòng trùng lặp ở thanh bên đang tắt.")
    if report["dup_found"]:
        with st.expander(f"Xem {fmt_num(report['dup_found'])} dòng trùng (kèm dòng gốc được giữ lại)"):
            ex = report["dup_examples"]
            st.dataframe(ex[[c for c in ["source_row", "first_row"] + mapped_now if c in ex]],
                         hide_index=True, width="stretch", column_config=REMOVED_CFG)
    else:
        st.caption("Không có dòng trùng.")

    # ---- Bước 2 ----
    st.subheader("Bước 2. Loại dòng âm")
    st.markdown("Loại mọi dòng có **số lượng, đơn giá hoặc thành tiền nhỏ hơn 0**: trả hàng, "
                "hủy đơn, điều chỉnh giảm giá.")
    nc = report["neg_counts"]
    cols_ = st.columns(len(nc) + 1)
    cols_[0].metric("Dòng bị loại", fmt_num(int((removed["step"] == "2. Loại dòng âm").sum())))
    for i, (lab, n) in enumerate(nc.items()):
        cols_[i + 1].metric(lab, fmt_num(n))
    st.caption("Một dòng có thể âm ở nhiều cột cùng lúc (ví dụ số lượng âm thì thành tiền cũng âm), "
               "nên các con số theo từng cột cộng lại có thể lớn hơn số dòng bị loại. "
               "Lưu ý: khi một đơn bị hủy rồi xuất lại, dòng hủy bị loại nhưng cả đơn gốc lẫn đơn "
               "xuất lại vẫn còn, nên khách đó có thể bị đếm dư một lần mua.")

    # ---- Bước 3 ----
    st.subheader("Bước 3. Bổ sung dữ liệu thiếu, rồi loại dòng vẫn còn thiếu")
    rules = ["**Số lượng / đơn giá / thành tiền**: nếu thiếu một trong ba mà có hai trường còn lại "
             "thì tính ra (ví dụ đơn giá = thành tiền ÷ số lượng)."]
    if "contract_number" in mapped_now:
        rules += ["**Khách hàng**: lấy theo số hợp đồng, nếu hợp đồng đó chỉ thuộc về một khách.",
                  "**Nhóm sản phẩm**: lấy theo số hợp đồng nếu hợp đồng chỉ có một nhóm sản phẩm. Nếu hợp đồng "
                  "có nhiều nhóm sản phẩm thì thử theo số hợp đồng + đơn giá (chỉ khi trong hợp đồng có "
                  "đúng một nhóm sản phẩm mang đơn giá đó). Không suy ra được thì dòng bị loại."]
    if "unit" in mapped_now:
        rules += ["**Đơn vị tính**: lấy theo nhóm sản phẩm nếu chỉ có một đơn vị. Không suy ra "
                  "được thì ghi \"(không rõ)\", dòng vẫn được giữ."]
    req = [FIELD_LABEL[c].lower() for c in
           ["date", "customer", "product", "quantity", "unit_price", "amount", "contract_number"]
           if c in mapped_now]
    rules += [f"**Bắt buộc phải có sau khi bổ sung**: {', '.join(req)}; và số lượng phải lớn hơn 0."]
    st.markdown("\n".join("- " + r_ for r_ in rules))

    mt = report["missing_table"].copy()
    mt["required"] = mt["required"].map({True: "Có", False: "Không"})
    st.dataframe(mt, hide_index=True, width="stretch", column_config={
        "field": st.column_config.TextColumn("Trường"),
        "required": st.column_config.TextColumn("Bắt buộc"),
        "missing": NC("Trống hoặc không đọc được", format="localized"),
        "filled": NC("Đã bổ sung", format="localized"),
        "how": st.column_config.TextColumn("Cách bổ sung"),
        "still_missing": NC("Vẫn thiếu", format="localized",
                            help="Với trường bắt buộc, các dòng này bị loại"),
    })
    n3 = int((removed["step"] == "3. Loại dòng thiếu dữ liệu").sum())
    st.caption(f"Bước này loại {fmt_num(n3)} dòng. Một dòng có thể thiếu nhiều trường cùng lúc, nên "
               "cột \"Vẫn thiếu\" cộng lại có thể lớn hơn số dòng bị loại.")
    fl = report["fill_log"]
    if len(fl):
        with st.expander(f"Xem {fmt_num(len(fl))} ô đã được bổ sung"):
            fl_cfg = {"source_row": REMOVED_CFG["source_row"],
                      "field": st.column_config.TextColumn("Trường"),
                      "value": st.column_config.TextColumn("Giá trị bổ sung"),
                      "method": st.column_config.TextColumn("Cách bổ sung")}
            st.dataframe(fl, hide_index=True, width="stretch", column_config=fl_cfg)
            st.download_button("Tải danh sách ô đã bổ sung (CSV)", _csv(fl, fl_cfg),
                               file_name="o_da_bo_sung.csv", mime="text/csv")

    # ---- Kiểm tra thêm ----
    st.subheader("Kiểm tra thêm (không xóa dòng)")
    notes = []
    fmt_txt = {"mdy": "tháng/ngày/năm (mm/dd/yyyy)", "dmy": "ngày/tháng/năm (dd/mm/yyyy)",
               "excel": "kiểu ngày (Excel/database)",
               "iso": "năm-tháng-ngày (yyyy-mm-dd)"}[report["date_format_used"]]
    notes.append(f"Cột ngày được đọc theo **{fmt_txt}**.")
    if report["date_ambiguous"]:
        notes.append("Không tự nhận diện được định dạng ngày vì mọi giá trị đều ≤ 12. "
                     "Hãy chọn đúng định dạng ở thanh bên.")
    if report["amount_mismatch"] is not None:
        notes.append(f"**{fmt_num(report['amount_mismatch'])}** dòng có thành tiền lệch quá 1 đồng so với "
                     "số lượng × đơn giá (không tính các dòng vừa được tính bổ sung).")
    if multi_unit:
        notes.append(f"**{len(multi_unit)}** nhóm sản phẩm được bán theo nhiều đơn vị tính: "
                     f"{', '.join(multi_unit[:10])}{'…' if len(multi_unit) > 10 else ''}. "
                     + ("Đang tách riêng theo đơn vị (tùy chọn ở thanh bên)." if split_unit else
                        "Số lượng của các đơn vị khác nhau đang bị cộng chung."))
    st.markdown("\n".join("- " + n_ for n_ in notes))
    me = report["mismatch_examples"]
    if me is not None and len(me):
        with st.expander("Xem các dòng có thành tiền lệch"):
            st.dataframe(me, hide_index=True, width="stretch", column_config=REMOVED_CFG)

    # ---- Toàn bộ dòng bị loại ----
    st.subheader("Tất cả dòng bị loại")
    if removed.empty:
        st.success("Không có dòng nào bị loại.")
    else:
        f1, f2 = st.columns([2, 3])
        step_f = f1.multiselect("Bước", sorted(removed["step"].unique()), placeholder="Tất cả")
        text_f = f2.text_input("Tìm theo lý do, khách hàng, nhóm sản phẩm hoặc số hợp đồng")
        rv = removed
        if step_f:
            rv = rv[rv["step"].isin(step_f)]
        if text_f:
            hay = pd.Series("", index=rv.index)
            for col_ in rv.columns.drop("date"):
                hay = hay + " " + rv[col_].map(lambda v: "" if pd.isna(v) else str(v))
            rv = rv[hay.str.contains(text_f, case=False, regex=False)]
        st.caption(f"{fmt_num(len(rv))} dòng.")
        st.dataframe(rv, hide_index=True, width="stretch", height=380, column_config=REMOVED_CFG)
        st.download_button("Tải toàn bộ dòng bị loại (CSV)", _csv(removed, REMOVED_CFG),
                           file_name="dong_bi_loai.csv", mime="text/csv")

# ------------------------------------------------------------------
# TAB 1: Tổng quan
# ------------------------------------------------------------------
with tab_over:

    # ── Bảng tiêu chí phân loại ────────────────────────────────────
    # st.markdown("#### Tiêu chí phân loại từng nhóm")
    st.markdown("<h4 style='text-align: center;'>Tiêu chí phân loại từng nhóm</h4>", unsafe_allow_html=True)
    st.markdown(
        "Bốn nhóm được xác định dựa trên **mức độ đều đặn của thời gian** "
        "(khoảng cách giữa các lần mua có ổn định không?) "
        "và **mức độ ổn định của số lượng** (mỗi lần mua có gần bằng nhau không?). "
        # f"Ngưỡng đang dùng: CV thời gian **≤ {timing_cv:.2f}** → đều; "
        # f"CV khối lượng **≤ {qty_cv:.2f}** → ổn định."
    )
    seg_info = [
        {"Nhóm": "🟢 Đều thời gian & số lượng",
            "Thời gian mua": "Đều đặn",
            "Số lượng mỗi lần": "Ổn định",
            "Ý nghĩa thực tế": "Biết trước gần như chính xác cả ngày lẫn số lượng → lập kế hoạch nguyên liệu trực tiếp",
            "Hành động gợi ý": "Chuẩn bị đơn theo lịch, không cần tồn kho nhiều"},
        {"Nhóm": "🔵 Đều thời gian, số lượng dao động",
            "Thời gian mua": "Đều đặn",
            "Số lượng mỗi lần": "Dao động",
            "Ý nghĩa thực tế": "Biết khi nào cần chuẩn bị, nhưng số lượng có thể thay đổi → cần tồn kho đệm",
            "Hành động gợi ý": "Chú ý nhắc hàng trước ngày dự kiến; hỏi số lượng trước"},
        {"Nhóm": "🟡 Thời gian thất thường, số lượng ổn định",
            "Thời gian mua": "Không đều",
            "Số lượng mỗi lần": "Ổn định",
            "Ý nghĩa thực tế": "Biết mỗi lần cần bao nhiêu, nhưng không biết khi nào → dùng tồn kho theo điểm đặt hàng lại",
            "Hành động gợi ý": "Duy trì tồn kho tối thiểu; đặt cảnh báo khi hàng xuống thấp"},
        {"Nhóm": "🔴 Thất thường cả hai",
            "Thời gian mua": "Không đều",
            "Số lượng mỗi lần": "Dao động",
            "Ý nghĩa thực tế": "Khó dự báo theo từng khách → nên gộp theo nhóm sản phẩm hoặc khu vực",
            "Hành động gợi ý": "Không lên kế hoạch riêng; theo dõi tổng nhu cầu nhóm"},
        {"Nhóm": "⚪ Chưa đủ dữ liệu",
            "Thời gian mua": "—",
            "Số lượng mỗi lần": "—",
            "Ý nghĩa thực tế": f"Dưới {min_orders} lần mua trong kỳ, chưa đủ để nhận xét xu hướng",
            "Hành động gợi ý": "Tiếp tục theo dõi; có thể là khách mới hoặc mua rất thưa"},
    ]
    st.dataframe(
        pd.DataFrame(seg_info),
        hide_index=True,
        width="stretch",
        column_config={
            "Nhóm": st.column_config.TextColumn("Nhóm", width=240),
            "Thời gian mua": st.column_config.TextColumn("Thời gian", width=110),
            "Số lượng mỗi lần": st.column_config.TextColumn("Số lượng", width=110),
            "Ý nghĩa thực tế": st.column_config.TextColumn("Ý nghĩa", width=340),
            "Hành động gợi ý": st.column_config.TextColumn("Hành động gợi ý", width=260),
        }
    )

    m = st.columns(5)
    m[0].metric("Khách hàng", fmt_num(dfw["customer"].nunique()))
    m[1].metric("Cặp khách × nhóm SP" if level == "pair" else "Khách được phân tích", fmt_num(len(prof)))
    m[2].metric("Lần mua", fmt_num(prof["n_orders"].sum()))
    if has_amount:
        m[3].metric("Tổng thành tiền", fmt_num(prof["total_amount"].sum()))
    else:
        m[3].metric("Tổng số lượng", fmt_num(prof["total_qty"].sum()))
    m[4].metric("Nhóm sản phẩm", fmt_num(dfw["product"].nunique()))

    seg_sum = (prof.groupby("segment", observed=False)
                   .agg(n=("key", "size"), val=(value_col, "sum")).reindex(SEG_ORDER).fillna(0))
    seg_sum["pct_n"] = seg_sum["n"] / seg_sum["n"].sum() * 100
    seg_sum["pct_val"] = seg_sum["val"] / seg_sum["val"].sum() * 100
    predictable = seg_sum.loc[SEG_ORDER[:2], "pct_val"].sum()
    st_val = prof.groupby("status", observed=False)[value_col].sum()
    overdue_n = int((prof["status"] == "Quá hạn").sum())
    due_n = int((prof["status"] == "Sắp đến hạn").sum())
    churn_pct = st_val.get("Đã ngừng mua", 0) / st_val.sum() * 100
    st.markdown(
        f"Nhóm **biết trước thời điểm mua** (hai nhóm đầu) chiếm **{fmt_num(predictable)}%** {value_name}. "
        f"Hiện có **{due_n}** {'cặp' if level == 'pair' else 'khách'} sắp đến hạn và **{overdue_n}** đã quá hạn. "
        f"Các {'cặp' if level == 'pair' else 'khách'} đã ngừng mua từng chiếm {fmt_num(churn_pct)}% {value_name} trong kỳ.")

    left, right = st.columns([3, 2], gap="large")
    with left:

        ev = prof[prof["segment"] != "Chưa đủ dữ liệu"].copy()
        if ev.empty:
            st.info("Chưa có khách nào đủ số lần mua tối thiểu. Hãy giảm ngưỡng ở thanh bên.")
        else:
            xmax = max(timing_cv * 2, np.nanquantile(ev["interval_cv"], 0.98) * 1.1)
            ymax = max(qty_cv * 2, np.nanquantile(ev["qty_cv"], 0.98) * 1.1)
            ev["x"] = ev["interval_cv"].clip(upper=xmax)
            ev["y"] = ev["qty_cv"].clip(upper=ymax)
            ev["size"] = ev[value_col].clip(lower=0)
            fig = px.scatter(
                ev, x="x", y="y", size="size", color="segment", size_max=40,
                color_discrete_map=SEG_COLOR, category_orders={"segment": SEG_ORDER},
                hover_name="key",
                hover_data={"x": False, "y": False, "size": False, "segment": False,
                            "n_orders": True, "avg_interval": ":.0f", "interval_cv": ":.2f",
                            "avg_vol": ":,.0f", "qty_cv": ":.2f", value_col: ":,.0f"},
                labels={"n_orders": "Số lần mua", "avg_interval": "TB ngày/lần",
                        "interval_cv": "CV thời gian", "avg_vol": "TB mỗi lần",
                        "qty_cv": "CV khối lượng", value_col: "Tổng " + value_name},
                title="Bản đồ tính cách: mỗi chấm là một " + ("cặp khách × nhóm SP" if level == "pair" else "khách"))
            fig.add_vline(x=timing_cv, line_dash="dot", line_color=MUTED)
            fig.add_hline(y=qty_cv, line_dash="dot", line_color=MUTED)
            for tx, ty, label, xa, ya in [
                (0.01, 0.01, "Đều cả hai", "left", "bottom"),
                (0.01, 0.99, "Đều thời gian", "left", "top"),
                (0.99, 0.01, "Số lượng ổn định", "right", "bottom"),
                (0.99, 0.99, "Thất thường", "right", "top"),
            ]:
                fig.add_annotation(x=tx, y=ty, xref="x domain", yref="y domain", text=label,
                                   showarrow=False, xanchor=xa, yanchor=ya,
                                   bgcolor="rgba(255,255,255,0.75)", font=dict(color=MUTED, size=12))
            fig.update_xaxes(title="CV thời gian giữa các lần mua (càng thấp càng đều)", range=[0, xmax])
            fig.update_yaxes(title="CV khối lượng mỗi lần (càng thấp càng ổn định)", range=[0, ymax])
            st.plotly_chart(style(fig, 500), width="stretch")
            st.caption("Kích thước chấm theo tổng " + value_name + ". Đường chấm là ngưỡng phân loại "
                       "đang chọn. Nhóm chưa đủ dữ liệu không hiển thị ở đây.")

    with right:
        seg_y = [s.replace(", ", ",<br>") for s in SEG_ORDER]
        fig = go.Figure()
        fig.add_bar(y=seg_y, x=seg_sum["pct_n"], orientation="h", name="% số " +
                    ("cặp" if level == "pair" else "khách"), marker_color="#B8C7D1",
                    text=[f"{v:.0f}%" for v in seg_sum["pct_n"]], textposition="outside")
        fig.add_bar(y=seg_y, x=seg_sum["pct_val"], orientation="h", name="% " + value_name,
                    marker_color=[SEG_COLOR[s] for s in SEG_ORDER],
                    text=[f"{v:.0f}%" for v in seg_sum["pct_val"]], textposition="outside")
        fig.update_layout(barmode="group", title="Nhóm nào đóng góp nhiều nhất",
                          bargap=0.25, bargroupgap=0.05)
        fig.update_yaxes(autorange="reversed")
        fig.update_xaxes(range=[0, max(seg_sum[["pct_n", "pct_val"]].max()) * 1.35], ticksuffix="%")
        fig.update_traces(cliponaxis=False)
        st.plotly_chart(style(fig, 500), width="stretch")

    left, right = st.columns([2, 3], gap="large")
    with left:
        stat = (prof.groupby("status", observed=False)
                    .agg(n=("key", "size"), val=(value_col, "sum")).reindex(STATUS_ORDER).fillna(0))
        fig = go.Figure(go.Bar(
            x=stat["n"], y=STATUS_ORDER, orientation="h",
            marker_color=[STATUS_COLOR[s] for s in STATUS_ORDER],
            text=[f"{int(n)}" for n in stat["n"]], textposition="outside",
            customdata=stat["val"], hovertemplate="%{y}: %{x}<br>Tổng " + value_name + ": %{customdata:,.0f}<extra></extra>"))
        fig.update_layout(title=f"Trạng thái tại ngày {end:%d/%m/%Y}")
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(style(fig, 360, legend=False), width="stretch")

    with right:
        mcol = "amount" if has_amount else "qty"
        mo = orders.merge(prof[["key", "segment"]], on="key", how="left")
        mo = mo.groupby(["month", "segment"], observed=False)[mcol].sum().reset_index()
        mo["month"] = mo["month"].astype(str)
        fig = px.bar(mo, x="month", y=mcol, color="segment", color_discrete_map=SEG_COLOR,
                     category_orders={"segment": SEG_ORDER},
                     labels={"month": "", mcol: "Thành tiền" if has_amount else "Số lượng", "segment": ""},
                     title="Doanh số theo tháng, tách theo nhóm tính cách" if has_amount
                     else "Sản lượng theo tháng, tách theo nhóm tính cách")
        fig.update_layout(bargap=0.15)
        fig.update_xaxes(tickformat="%m/%Y")
        st.plotly_chart(style(fig, 360), width="stretch")

    # ---- Bảng dẫn chứng cho 3 trạng thái có thể dự đoán ----
    DUE_ORDER = ["Quá hạn", "Sắp đến hạn", "Chưa đến hạn"]
    unit_word = "cặp" if level == "pair" else "khách"
    st.subheader(f"Danh sách {unit_word} chưa đến hạn, sắp đến hạn và quá hạn")
    st.caption(
        f"Tính tại ngày {end:%d/%m/%Y}. Chỉ gồm các {unit_word} mua đều về thời gian (CV thời gian dưới "
        f"{timing_cv:.2f}) và đủ {min_orders} lần mua. Cửa sổ đến hạn = TB ngày/lần ± {k:.1f} × độ lệch "
        "chuẩn, tính từ ngày mua gần nhất. Nhóm khó đoán thời điểm, đã ngừng mua và chưa đủ dữ liệu "
        "không nằm trong bảng này.")

    due = prof[prof["status"].isin(DUE_ORDER)].copy()
    if due.empty:
        st.info(f"Không có {unit_word} nào ở ba trạng thái này tại ngày đánh giá.")
    else:
        mc = st.columns(3)
        for i, stt in enumerate(DUE_ORDER):
            sub = due[due["status"] == stt]
            mc[i].metric(stt, f"{len(sub)} {unit_word}",
                         help=f"Chiếm {fmt_num(sub['share_pct'].sum(), 1)}% {value_name}")
        f = st.columns([3, 1, 3])
        due_f = f[0].multiselect("Trạng thái", DUE_ORDER, default=DUE_ORDER, key="due_status")
        due_abc = f[1].multiselect("ABC", ["A", "B", "C"], placeholder="Tất cả", key="due_abc")
        due_q = f[2].text_input("Tìm khách hàng hoặc nhóm sản phẩm", key="due_search")
        if due_f:
            due = due[due["status"].isin(due_f)]
        if due_abc:
            due = due[due["abc"].isin(due_abc)]
        if due_q:
            due = due[due["key"].str.contains(due_q, case=False, regex=False)]

        due["status_rank"] = due["status"].astype(str).map({s_: i for i, s_ in enumerate(DUE_ORDER)})
        due = due.sort_values(["status_rank", "days_left", "share_pct"], ascending=[True, True, False])
        due["evidence"] = [due_evidence(r_, short=True) for _, r_ in due.iterrows()]
        due["evidence_full"] = [due_evidence(r_) for _, r_ in due.iterrows()]
        due["status"] = due["status"].astype(str)
        due["avg_vol"] = due["avg_vol"].round(0)
        # "Căn cứ" đặt ngay sau tên để đọc được mà không phải cuộn ngang
        due_cols = (["status", "customer"] + (["product"] if level == "pair" else []) +
                    (["product_name"] if level == "pair" and "product_name" in due.columns else []) +
                    ["abc", "evidence", "days_since_last", "due_from_days", "due_to_days", "days_left",
                     "cycle_progress", "avg_interval", "std_interval", "last_date", "due_from_date",
                     "due_to_date", "n_orders", "interval_cv", "avg_vol", "share_pct"])
        DUE_CFG = {
            "status": st.column_config.TextColumn("Trạng thái", pinned=True),
            "customer": st.column_config.TextColumn("Khách hàng", pinned=True),
            "product": st.column_config.TextColumn("Nhóm sản phẩm"),
            "product_name": st.column_config.TextColumn("Sản phẩm"),
            "abc": st.column_config.TextColumn("ABC"),
            "share_pct": NC("% " + value_name, format="%.1f%%"),
            "last_date": st.column_config.DateColumn("Mua gần nhất", format="DD/MM/YYYY"),
            "days_since_last": NC("Ngày từ lần cuối", format="%d"),
            "avg_interval": NC("TB ngày/lần", format="%.0f"),
            "std_interval": NC("Độ lệch (± ngày)", format="%.0f"),
            "due_from_days": NC("Thường mua lại từ ngày thứ", format="%d"),
            "due_to_days": NC("đến ngày thứ", format="%d"),
            "due_from_date": st.column_config.DateColumn("Cửa sổ từ", format="DD/MM/YYYY"),
            "due_to_date": st.column_config.DateColumn("Cửa sổ đến", format="DD/MM/YYYY"),
            "days_left": NC("Còn / trễ (ngày)", format="%+d",
                            help="Chưa đến hạn: còn bao nhiêu ngày mới vào cửa sổ. "
                                 "Sắp đến hạn: còn bao nhiêu ngày là hết cửa sổ. "
                                 "Quá hạn: số âm là số ngày đã trễ so với ngày cuối của cửa sổ."),
            "cycle_progress": st.column_config.ProgressColumn(
                "% chu kỳ đã qua", format="%.0f%%", min_value=0,
                max_value=float(max(200, due["cycle_progress"].max() if len(due) else 200)),
                help="Ngày từ lần cuối ÷ TB ngày/lần. 100% là đúng bằng chu kỳ trung bình."),
            "n_orders": NC("Số lần mua", format="%d"),
            "interval_cv": NC("CV thời gian", format="%.2f"),
            "avg_vol": NC("TB mỗi lần" + (" (đồng)" if vb == "amount" else ""), format="localized"),
            "evidence": st.column_config.TextColumn(
                "Căn cứ", width="large",
                help="Số ngày từ lần mua cuối so với khoảng ngày khách thường mua lại"),
            "evidence_full": st.column_config.TextColumn("Diễn giải"),
        }
        st.dataframe(due[due_cols], column_config=DUE_CFG, hide_index=True, width="stretch",
                     height=min(460, 38 + 35 * len(due)))
        st.download_button(
            "Tải danh sách (CSV)",
            due[due_cols + ["evidence_full"]]
               .rename(columns={c_: DUE_CFG[c_]["label"] for c_ in due_cols + ["evidence_full"]})
                         .to_csv(index=False).encode("utf-8-sig"),
            file_name=f"trang_thai_{end:%Y%m%d}.csv", mime="text/csv")

# ------------------------------------------------------------------
# TAB 2: Bảng hồ sơ
# ------------------------------------------------------------------
TABLE_CFG = {
    "customer": st.column_config.TextColumn("Khách hàng", pinned=True),
    "product": st.column_config.TextColumn("Nhóm sản phẩm"),
    "product_name": st.column_config.TextColumn("Sản phẩm"),
    "unit": st.column_config.TextColumn("Đơn vị"),
    "segment": st.column_config.TextColumn("Nhóm tính cách"),
    "status": st.column_config.TextColumn("Trạng thái"),
    "abc": st.column_config.TextColumn("ABC", help="A: nhóm tạo 80% giá trị đầu tiên, B: 15% tiếp theo, C: phần còn lại"),
    "share_pct": st.column_config.ProgressColumn("% " + value_name, format="%.1f%%", min_value=0,
                                                 max_value=float(max(prof["share_pct"].max(), 1))),
    "n_orders": NC("Số lần mua", format="%d"),
    "first_date": st.column_config.DateColumn("Mua lần đầu", format="DD/MM/YYYY"),
    "last_date": st.column_config.DateColumn("Mua gần nhất", format="DD/MM/YYYY"),
    "days_since_last": NC("Ngày từ lần cuối", format="%d"),
    "avg_interval": NC("TB ngày/lần", format="%.1f"),
    "median_interval": NC("Trung vị ngày/lần", format="%.0f"),
    "std_interval": NC("Độ lệch ngày", format="%.1f"),
    "interval_cv": NC("CV thời gian", format="%.2f"),
    "avg_vol": NC("TB mỗi lần", format="localized"),
    "std_vol": NC("Độ lệch mỗi lần", format="localized"),
    "min_vol": NC("Nhỏ nhất/lần", format="localized"),
    "max_vol": NC("Lớn nhất/lần", format="localized"),
    "qty_cv": NC("CV khối lượng", format="%.2f"),
    "total_qty": NC("Tổng số lượng", format="localized"),
    "total_amount": NC("Tổng thành tiền", format="localized"),
    "avg_amount_order": NC("TB tiền/lần", format="localized"),
    "orders_per_month": NC("Lần mua/tháng", format="%.2f"),
    "months_active": NC("Số tháng có mua", format="%d"),
    "active_month_ratio": NC("% tháng có mua", format="%.0f%%"),
    "trend": st.column_config.TextColumn("Xu hướng tần suất"),
    "trend_pct": NC("Thay đổi khoảng cách", format="%+.0f%%"),
    "dominant_dow": st.column_config.TextColumn("Thứ hay mua"),
    "dow_share": NC("% vào thứ đó", format="%.0f%%"),
    "dow_base_share": NC("% chung của thứ đó", format="%.0f%%",
                         help="Tỷ lệ lần mua rơi vào thứ này trên toàn bộ khách hàng"),
    "dow_p": NC("p thứ trong tuần", format="%.3f",
                help="Dưới 0,05 nghĩa là thói quen mua theo thứ có ý nghĩa thống kê"),
    "expected_next": st.column_config.DateColumn("Dự kiến lần tới", format="DD/MM/YYYY"),
    "days_to_due": NC("Còn bao ngày", format="%d"),
}
TABLE_COLS = (["customer"] + (["product"] if level == "pair" else []) +
              (["product_name"] if level == "pair" and "product_name" in prof.columns else []) +
              (["unit"] if prof["unit"].notna().any() else []) +
              ["segment", "status", "abc", "share_pct", "n_orders", "avg_interval", "interval_cv",
               "avg_vol", "qty_cv", "last_date", "days_since_last", "expected_next", "days_to_due",
               "trend", "trend_pct", "dominant_dow", "dow_share", "dow_base_share", "dow_p",
               "median_interval", "std_interval", "min_vol", "max_vol", "std_vol",
               "total_qty", "total_amount", "avg_amount_order", "orders_per_month",
               "months_active", "active_month_ratio", "first_date"])
if not has_amount:
    TABLE_COLS = [c for c in TABLE_COLS if c not in ("total_amount", "avg_amount_order")]

with tab_table:
    f = st.columns([2, 2, 1, 2])
    seg_f = f[0].multiselect("Nhóm tính cách", SEG_ORDER, placeholder="Tất cả")
    stat_f = f[1].multiselect("Trạng thái", STATUS_ORDER, placeholder="Tất cả")
    abc_f = f[2].multiselect("ABC", ["A", "B", "C"], placeholder="Tất cả")
    search = f[3].text_input("Tìm khách hàng hoặc nhóm sản phẩm")

    view = prof.copy()
    if seg_f:
        view = view[view["segment"].isin(seg_f)]
    if stat_f:
        view = view[view["status"].isin(stat_f)]
    if abc_f:
        view = view[view["abc"].isin(abc_f)]
    if search:
        view = view[view["key"].str.contains(search, case=False, regex=False)]

    out = view[TABLE_COLS].copy()
    # số lượng / tiền: làm tròn về số nguyên (không hiện phần thập phân)
    int_cols = [c for c in ("avg_vol", "std_vol", "min_vol", "max_vol", "total_qty",
                            "total_amount", "avg_amount_order") if c in out]
    out[int_cols] = out[int_cols].round(0)
    out["segment"] = out["segment"].astype(str)
    out["status"] = out["status"].astype(str)
    st.caption(f"{len(out)} dòng, sắp theo {value_name} giảm dần. Bấm tiêu đề cột để sắp xếp lại.")
    st.dataframe(out, column_config=TABLE_CFG, hide_index=True, width="stretch", height=560)

    export = out.rename(columns={c: TABLE_CFG[c].get("label", c) if isinstance(TABLE_CFG[c], dict) else c
                                 for c in out.columns})
    st.download_button("Tải bảng (CSV mở được bằng Excel)",
                       export.to_csv(index=False).encode("utf-8-sig"),
                       file_name="ho_so_mua_hang.csv", mime="text/csv")

# ------------------------------------------------------------------
# TAB 3: Chi tiết một khách
# ------------------------------------------------------------------
with tab_detail:
    c1, c2 = st.columns(2)
    cust = c1.selectbox("Khách hàng", prof_c["customer"].tolist(),
                        help="Sắp theo " + value_name + " giảm dần")
    prods = prof_p.loc[prof_p["customer"] == cust, "product"].tolist()
    ALL = "Tất cả nhóm sản phẩm (gộp)"
    prod = c2.selectbox("Nhóm sản phẩm", [ALL] + prods)

    if prod == ALL:
        r = prof_c[prof_c["customer"] == cust].iloc[0]
        o = orders_c[orders_c["customer"] == cust]
    else:
        r = prof_p[(prof_p["customer"] == cust) & (prof_p["product"] == prod)].iloc[0]
        o = orders_p[(orders_p["customer"] == cust) & (orders_p["product"] == prod)]

    st.markdown(badge(r["segment"], SEG_COLOR[r["segment"]]) +
                badge(r["status"], STATUS_COLOR[r["status"]]) +
                badge(f"Hạng {r['abc']}", PRIMARY), unsafe_allow_html=True)
    st.write("")

    # ── Chỉ số tóm tắt — ngôn ngữ dễ hiểu ────────────────────────
    k_ = st.columns(4)
    k_[0].metric("Số lần mua", fmt_num(r["n_orders"]),
                 help="Tổng số lần mua trong kỳ phân tích")
    k_[1].metric("Trung bình mỗi" + (" tháng" if r["avg_interval"] < 35 else " lần"),
                 (f"{fmt_num(r['avg_interval'])} ngày"),
                 help="Số ngày trung bình giữa hai lần mua liên tiếp")
    k_[2].metric("Trung bình mỗi lần" + (" (đồng)" if vb == "amount" else ""),
                 fmt_num(r["avg_vol"]),
                 help="Giá trị/số lượng trung bình mỗi lần mua")
    k_[3].metric("Ngày từ lần mua cuối", fmt_num(r["days_since_last"]),
                 help="Số ngày tính đến ngày đánh giá")

    unit_here = vol_unit
    if vb == "qty" and isinstance(r["unit"], str) and r["unit"] not in ("", "nhiều đơn vị"):
        unit_here = r["unit"]
    with st.container(border=True):
        st.markdown("\n".join("- " + s for s in describe_profile(r, min_orders, timing_cv, qty_cv, unit_here)))
    if vb == "qty" and r["unit"] == "nhiều đơn vị":
        st.caption("Đang gộp số lượng của nhiều sản phẩm có thể khác đơn vị. "
                   "Nên chọn đo khối lượng bằng thành tiền ở thanh bên.")

    left, right = st.columns(2, gap="large")
    with left:
        mvals = monthly_matrix(o, vb, start, end).iloc[0]
        fig = go.Figure(go.Bar(x=mvals.index, y=mvals.values, marker_color=PRIMARY,
                               hovertemplate="%{x}: %{y:,.0f}<extra></extra>"))
        fig.update_layout(title="Doanh số theo từng tháng" if vb == "amount" else "Số lượng theo từng tháng")
        fig.update_xaxes(tickformat="%m/%Y")
        fig.update_yaxes(title="Thành tiền" if vb == "amount" else "Số lượng")
        st.plotly_chart(style(fig, 340, legend=False), width="stretch")
        st.caption("Tháng không có cột = không có giao dịch trong tháng đó.")

    with right:
        fig = go.Figure()
        if pd.notna(r["std_vol"]):
            fig.add_hrect(y0=max(r["avg_vol"] - r["std_vol"], 0), y1=r["avg_vol"] + r["std_vol"],
                          fillcolor=PRIMARY, opacity=0.08, line_width=0)
        fig.add_scatter(x=o["date"], y=o["vol"], mode="lines+markers",
                        name="Mỗi lần mua",
                        line=dict(color="#9FB3C0", width=1), marker=dict(color=PRIMARY, size=7),
                        hovertemplate="%{x|%d/%m/%Y}: %{y:,.0f}<extra></extra>")
        fig.add_hline(y=r["avg_vol"], line_dash="dot", line_color=MUTED,
                      annotation_text="Mức trung bình", annotation_position="top left")
        ytop = o["vol"].max() * 1.05
        if pd.notna(r["expected_next"]) and r["status"] not in ("Đã ngừng mua", "Khó đoán thời điểm"):
            fig.add_scatter(x=[r["expected_next"]] * 2, y=[0, ytop], mode="lines",
                            name=f"Dự kiến lần tới ({r['expected_next']:%d/%m/%Y})",
                            line=dict(color=STATUS_COLOR["Sắp đến hạn"], dash="dash"))
        fig.add_scatter(x=[as_of] * 2, y=[0, ytop], mode="lines", name="Ngày đánh giá",
                        line=dict(color=INK, width=1, dash="dot"))
        fig.update_layout(title="Giá trị từng lần mua theo thời gian" if vb == "amount"
                          else "Số lượng từng lần mua theo thời gian")
        fig.update_xaxes(tickformat="%m/%Y")
        st.plotly_chart(style(fig, 340), width="stretch")
        st.caption("Vùng mờ = khoảng dao động thông thường (trung bình ± 1 lần độ lệch chuẩn). "
                   "Điểm nằm ngoài vùng mờ là lần mua bất thường.")

    left, right = st.columns(2, gap="large")
    with left:
        iv = o["interval"].dropna()
        if len(iv) >= 2:
            fig = px.histogram(iv, nbins=min(30, max(5, len(iv) // 2)),
                               color_discrete_sequence=[PRIMARY])
            fig.add_vline(x=r["avg_interval"], line_dash="dot", line_color=INK,
                          annotation_text=f"TB {fmt_num(r['avg_interval'])} ngày",
                          annotation_position="top right")
            fig.update_layout(title="Khoảng cách giữa các lần mua", bargap=0.08)
            fig.update_xaxes(title="Số ngày")
            fig.update_yaxes(title="Số lần")
            st.plotly_chart(style(fig, 320, legend=False), width="stretch")
        else:
            st.info("Cần ít nhất 3 lần mua để vẽ phân bố khoảng cách.")

    with right:
        dow = o["date"].dt.dayofweek.value_counts().reindex(range(7), fill_value=0)
        all_orders = orders_c if prod == ALL else orders_p
        expected = (all_orders["dow"].value_counts(normalize=True)
                    .reindex(range(7), fill_value=0) * len(o))
        top = int(dow.idxmax())
        fig = go.Figure()
        fig.add_bar(x=DOW_VN, y=dow.values, name="Khách này",
                    marker_color=[PRIMARY if i == top else "#B8C7D1" for i in range(7)])
        fig.add_scatter(x=DOW_VN, y=expected.values, mode="markers", name="Mức chung của mọi khách",
                        marker=dict(symbol="line-ew-open", size=26, color=INK, line=dict(width=2)))
        if pd.isna(r["dow_p"]):
            sig = "chưa đủ dữ liệu"
        elif r["dow_p"] < 0.05:
            sig = f"có thói quen rõ, p = {r['dow_p']:.3f}"
        else:
            sig = f"chưa đủ bằng chứng là thói quen, p = {r['dow_p']:.3f}"
        fig.update_layout(title=f"Mua vào thứ nào trong tuần ({sig})")
        fig.update_yaxes(title="Số lần mua")
        st.plotly_chart(style(fig, 340), width="stretch")
        st.caption("Vạch ngang là số lần mua dự kiến nếu khách này mua theo đúng phân bố chung "
                   "của mọi khách. Cột cao hơn hẳn vạch mới là thói quen riêng.")

    if prod == ALL and len(prods) > 0:
        st.subheader("Các nhóm sản phẩm khách này mua")
        sub = prof_p[prof_p["customer"] == cust].copy()
        sub_cols = (["product"] + (["product_name"] if "product_name" in sub.columns else []) +
                    ["unit", "segment", "status", "n_orders", "avg_interval", "interval_cv",
                     "avg_vol", "qty_cv", "last_date", "expected_next", "trend"])
        sub = sub[sub_cols].assign(avg_vol=lambda d: d["avg_vol"].round(0),
                                   segment=lambda d: d["segment"].astype(str),
                                   status=lambda d: d["status"].astype(str))
        st.dataframe(sub, column_config=TABLE_CFG, hide_index=True, width="stretch")

# ------------------------------------------------------------------
# TAB 4: Lịch sử theo kỳ  (drilldown via streamlit-aggrid)
# ------------------------------------------------------------------
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode, AgGridTheme, ColumnsAutoSizeMode

with tab_month:
    # ── Thanh điều khiển ──────────────────────────────────────────────
    ctrl = st.columns([2, 3])
    mv_opts = (["Thành tiền"] if has_amount else []) + ["Số lượng", "Số lần mua"]
    mv_label = ctrl[0].radio("Hiển thị", mv_opts, horizontal=True)
    mv = {"Thành tiền": "amount", "Số lượng": "qty", "Số lần mua": "n_orders"}[mv_label]

    n_rows = len(prof)
    if n_rows > 5:
        top_n = ctrl[1].slider(
            "Số " + ("cặp" if level == "pair" else "khách") + " hiển thị", 5,
            min(100, n_rows), min(30, n_rows))
    else:
        top_n = n_rows

    seg_m = st.multiselect("Lọc nhóm tính cách", SEG_ORDER, placeholder="Tất cả", key="seg_m")

    if mv == "qty" and (prof["unit"] == "nhiều đơn vị").any():
        st.caption("Một số dòng đang cộng số lượng của nhiều đơn vị tính khác nhau. "
                   "Nên xem theo thành tiền hoặc số lần mua cho các dòng này.")

    pm = prof if not seg_m else prof[prof["segment"].isin(seg_m)]

    # ── Chuẩn bị dữ liệu cho bảng drilldown ────────────────────────
    orders_for_period = orders.copy()

    df_drill = dfw.copy()
    if "product" not in df_drill.columns and "category" in df_drill.columns:
        df_drill["product"] = df_drill["category"]

    if has_paper_type and "paper_type" in df_drill.columns:
        is_bbg = df_drill["product"].astype(str).str.lower().str.contains("bao bì giấy|bao bi giay", na=False)
        df_drill["paper_type"] = np.where(
            is_bbg,
            df_drill["paper_type"].fillna("").astype(str).str.strip(),
            ""
        )
        use_paper_layer = True
        dim_cols   = ["customer", "product", "paper_type"]
        dim_labels = ["Khách hàng", "Nhóm sản phẩm", "Sản phẩm giấy"]
    else:
        use_paper_layer = False
        dim_cols   = ["customer", "product"]
        dim_labels = ["Khách hàng", "Nhóm sản phẩm"]

    # ── Hàm tạo pivot theo một tần suất cố định ──────────────────────
    def _build_pivot_freq(orders_df, dim_cols_, mv_, freq_, start_, end_):
        """Trả về (pivot_df, period_col_names) cho một freq cố định."""
        prange = pd.period_range(
            pd.Timestamp(start_).to_period(freq_),
            pd.Timestamp(end_).to_period(freq_), freq=freq_)
        _df = orders_df.copy()
        _df["_period"] = _df["date"].dt.to_period(freq_)
        if mv_ == "n_orders":
            agg = _df.groupby(dim_cols_ + ["_period"])["date"].nunique().reset_index(name="_val")
        elif mv_ == "qty":
            col_q = "quantity" if "quantity" in _df.columns else "qty"
            agg = _df.groupby(dim_cols_ + ["_period"])[col_q].sum().reset_index(name="_val")
        else:
            col_a = "amount" if "amount" in _df.columns else "total_amount"
            agg = _df.groupby(dim_cols_ + ["_period"])[col_a].sum().reset_index(name="_val")
        pivot = agg.pivot_table(
            index=dim_cols_, columns="_period",
            values="_val", aggfunc="sum", fill_value=0)
        pivot = pivot.reindex(columns=prange, fill_value=0)
        pivot.columns = [str(c) for c in pivot.columns]
        pivot = pivot.reset_index()
        return pivot, [str(c) for c in prange]

    # Lọc top khách hàng theo prof đã lọc
    top_cust_list = list(dict.fromkeys(pm["customer"].head(top_n)))
    all_cust_set  = set(pm["customer"])

    orders_top      = df_drill[df_drill["customer"].isin(top_cust_list)]
    orders_all_filt = df_drill[df_drill["customer"].isin(all_cust_set)]

    if orders_top.empty:
        st.info("Không có dữ liệu cho bộ lọc đang chọn.")
    else:
        # ── Heatmap (overview) ─────────────────────────────────────────
        top_keys = list(pm["key"].head(top_n))
        mat_all  = period_matrix(orders_for_period, value=mv, start=start, end=end, freq="M")
        if use_paper_layer and isinstance(mat_all.index, pd.MultiIndex):
            keys_in  = mat_all.index.get_level_values("key").isin(top_keys)
            mat      = mat_all[keys_in]
            y_labels = [" | ".join(str(x) for x in idx) for idx in mat.index]
        else:
            keys_flat = [x for x in top_keys if x in mat_all.index]
            mat       = mat_all.loc[keys_flat] if keys_flat else mat_all.iloc[0:0]
            y_labels  = list(mat.index)

        if not mat.empty:
            zmax = float(np.nanquantile(mat.values[mat.values > 0], 0.95)) \
                   if (mat.values > 0).any() else 1
            fig = go.Figure(go.Heatmap(
                z=mat.values, x=mat.columns, y=y_labels,
                zmin=0, zmax=zmax,
                colorscale=[[0, "#FFFFFF"], [0.0001, "#DCEBF0"], [1, "#0B4A61"]],
                xgap=1, ygap=1, colorbar=dict(title=None, thickness=10),
                hovertemplate="%{y}<br>%{x}: %{z:,.0f}<extra></extra>"))
            fig.update_layout(title=f"{mv_label} theo tháng (tổng quan)")
            fig.update_yaxes(autorange="reversed", tickfont=dict(size=10))
            fig.update_xaxes(tickformat="%m/%Y")
            st.plotly_chart(
                style(fig, max(320, 22 * len(y_labels) + 140), legend=False),
                width="stretch")
            st.caption("Màu đậm nhất ứng với mức 95% cao nhất.")

        # ── Bảng drilldown Năm → Quý → Tháng ─────────────────────────
        st.markdown("---")
        _c_gr1, _c_gr2 = st.columns([1, 1])
        show_growth = _c_gr1.checkbox(
            "Hiển thị cột tăng trưởng YoY / QoQ / MoM xen kẽ",
            value=True,
            help="Cột % thay đổi so với kỳ liền trước (ví dụ: 2017 → 2018 → 17-18 (YoY) → 2019 → 18-19 (YoY)...)"
        )
        default_time_level = _c_gr2.radio(
            "Mở rộng thời gian mặc định",
            ["Năm (rút gọn)", "Quý", "Tháng (chi tiết)"],
            horizontal=True,
            help="Chọn mức hiển thị mặc định khi tải bảng. Bấm [+] hoặc [-] trên tiêu đề từng cột để mở rộng/thu gọn chi tiết."
        )

        # Build dữ liệu cho 3 cấp: Năm, Quý, Tháng
        p_year,  ycols = _build_pivot_freq(orders_top, dim_cols, mv, "Y", start, end)
        p_qtr,   qcols = _build_pivot_freq(orders_top, dim_cols, mv, "Q", start, end)
        p_month, mcols = _build_pivot_freq(orders_top, dim_cols, mv, "M", start, end)

        # Merge tất cả vào pivot_df
        pivot_df = p_year.merge(p_qtr, on=dim_cols, how="outer").fillna(0)
        pivot_df = pivot_df.merge(p_month, on=dim_cols, how="outer").fillna(0)

        # Đổi tên dim cols
        rename_dim = dict(zip(dim_cols, dim_labels))
        pivot_df   = pivot_df.rename(columns=rename_dim)
        disp_dims  = [rename_dim[c] for c in dim_cols]

        # Tính cột Tổng (tổng các cột năm)
        pivot_df.insert(len(disp_dims), "Tổng", pivot_df[ycols].sum(axis=1))

        # ── Cấu hình ag-Grid ──────────────────────────────────────────
        # Xây dựng cấu trúc đường dẫn phân cấp (treeData)
        # Các cặp (Khách hàng, Nhóm SP) có chia loại giấy thì mở rộng cấp 3 (Sản phẩm giấy)
        # Các nhóm không chia loại giấy (như Hộp carton, Nhãn mác...) là cấp lá (depth 2), không có nút '>'
        has_pt_map = pivot_df[pivot_df["Sản phẩm giấy"] != ""].groupby(["Khách hàng", "Nhóm sản phẩm"]).size().to_dict() \
                     if "Sản phẩm giấy" in pivot_df.columns else {}

        _SEP = "###"

        def make_tree_path(row):
            c = str(row["Khách hàng"]).strip()
            p = str(row["Nhóm sản phẩm"]).strip()
            if (c, p) in has_pt_map:
                pt = str(row.get("Sản phẩm giấy", "")).strip()
                pt_label = pt if pt else "(Chưa phân loại)"
                return f"{c}{_SEP}{p}{_SEP}{pt_label}"
            return f"{c}{_SEP}{p}"

        pivot_df["path_str"] = pivot_df.apply(make_tree_path, axis=1)

        gb = GridOptionsBuilder.from_dataframe(pivot_df)

        # Ẩn các cột chiều phân cấp và cột path_str (hiển thị qua treeData autoGroupColumnDef)
        for dl in disp_dims + ["path_str"]:
            gb.configure_column(dl, hide=True)

        # --- JS formatters ---
        num_fmt_js = JsCode("""
            function(params) {
                if (params.value == null || params.value === '') return '';
                return Math.round(params.value).toLocaleString('vi-VN');
            }
        """)
        growth_pct_fmt = JsCode("""
            function(params) {
                if (params.value == null || params.value === '') return '';
                var sign = params.value >= 0 ? '+' : '';
                return sign + params.value.toFixed(1) + '%';
            }
        """)
        growth_style = JsCode("""
            function(params) {
                if (params.value == null || params.value === '') return {};
                if (params.value > 0)  return {color: '#1F7A5C', fontWeight: '600', background: 'rgba(31,122,92,0.07)'};
                if (params.value < 0)  return {color: '#B5475B', fontWeight: '600', background: 'rgba(181,71,91,0.07)'};
                return {};
            }
        """)

        def _make_growth_getter(prev_c, cur_c):
            return JsCode(f"""
                function(params) {{
                    var cur, prv;
                    if (params.node && params.node.aggData) {{
                        cur = params.node.aggData['{cur_c}'];
                        prv = params.node.aggData['{prev_c}'];
                    }} else if (params.data) {{
                        cur = params.data['{cur_c}'];
                        prv = params.data['{prev_c}'];
                    }}
                    if (prv == null || prv === 0 || cur == null) return null;
                    return ((cur - prv) / Math.abs(prv)) * 100;
                }}
            """)

        # --- Cột Tổng pinned bên trái ---
        gb.configure_column(
            "Tổng", header_name="Tổng", aggFunc="sum",
            type=["numericColumn"], valueFormatter=num_fmt_js,
            pinned="left", width=120,
        )

        # --- Xây dựng Column Groups lồng nhau cho thời gian Năm → Quý → Tháng ---
        open_years = default_time_level in ("Quý", "Tháng (chi tiết)")
        open_qtrs  = default_time_level == "Tháng (chi tiết)"

        time_col_groups = []
        prev_year_col = None
        prev_qtr_col  = None
        prev_mon_col  = None

        years_in_data = sorted({c for c in ycols})
        for yc in years_in_data:
            y_int = int(yc) if yc.isdigit() else None
            y_children = []

            # 1. Cột năm
            y_children.append({
                "headerName": f"{yc}",
                "field": yc,
                "aggFunc": "sum",
                "type": ["numericColumn"],
                "valueFormatter": num_fmt_js,
                "width": 115,
                "cellStyle": {"fontWeight": "600"},
            })

            # 2. Cột YoY xen kẽ
            if show_growth and prev_year_col:
                prev_str = prev_year_col[-2:] if len(prev_year_col) >= 2 else prev_year_col
                cur_str  = yc[-2:] if len(yc) >= 2 else yc
                y_children.append({
                    "headerName": f"{prev_str}-{cur_str} (YoY)",
                    "colId": f"{yc}_YoY",
                    "valueGetter": _make_growth_getter(prev_year_col, yc),
                    "valueFormatter": growth_pct_fmt,
                    "cellStyle": growth_style,
                    "type": ["numericColumn"],
                    "width": 110,
                })
            prev_year_col = yc

            # 3. Quý thuộc năm này
            qs_this_year = sorted([qc for qc in qcols
                                   if (y_int is not None and qc.startswith(str(y_int) + "Q"))
                                       or (y_int is None and qc == yc)])
            for qc in qs_this_year:
                q_children = []
                q_label = qc[-2:] if len(qc) >= 2 else qc

                # Cột quý
                q_children.append({
                    "headerName": q_label,
                    "field": qc,
                    "aggFunc": "sum",
                    "type": ["numericColumn"],
                    "valueFormatter": num_fmt_js,
                    "width": 95,
                    "cellStyle": {"fontWeight": "500"},
                })

                # Cột QoQ xen kẽ
                if show_growth and prev_qtr_col:
                    q_children.append({
                        "headerName": "QoQ",
                        "colId": f"{qc}_QoQ",
                        "valueGetter": _make_growth_getter(prev_qtr_col, qc),
                        "valueFormatter": growth_pct_fmt,
                        "cellStyle": growth_style,
                        "type": ["numericColumn"],
                        "width": 90,
                    })
                prev_qtr_col = qc

                # 4. Tháng thuộc quý này
                q_int = int(qc[-1]) if qc[-1].isdigit() else None
                months_this_qtr = []
                if q_int and y_int:
                    qtr_months = range((q_int - 1) * 3 + 1, (q_int - 1) * 3 + 4)
                    for m in qtr_months:
                        mc = f"{y_int}-{m:02d}"
                        if mc in mcols:
                            months_this_qtr.append((m, mc))
                else:
                    months_this_qtr = [(int(mc[-2:]), mc) for mc in sorted(mcols) if mc.startswith(str(y_int))]

                for (m_num, mc) in months_this_qtr:
                    q_children.append({
                        "headerName": f"T{m_num:02d}",
                        "field": mc,
                        "columnGroupShow": "open",
                        "aggFunc": "sum",
                        "type": ["numericColumn"],
                        "valueFormatter": num_fmt_js,
                        "width": 85,
                    })
                    if show_growth and prev_mon_col:
                        q_children.append({
                            "headerName": "MoM",
                            "colId": f"{mc}_MoM",
                            "columnGroupShow": "open",
                            "valueGetter": _make_growth_getter(prev_mon_col, mc),
                            "valueFormatter": growth_pct_fmt,
                            "cellStyle": growth_style,
                            "type": ["numericColumn"],
                            "width": 85,
                        })
                    prev_mon_col = mc

                y_children.append({
                    "headerName": f"{qc}",
                    "groupId": f"grp_{qc}",
                    "columnGroupShow": "open",
                    "openByDefault": open_qtrs,
                    "children": q_children,
                })

            time_col_groups.append({
                "headerName": f"📅 {yc}",
                "groupId": f"grp_{yc}",
                "openByDefault": open_years,
                "children": y_children,
            })

        go_opts = gb.build()
        # Giữ lại cột Tổng và ghép Column Groups thời gian
        pinned_defs = [c for c in go_opts["columnDefs"] if c.get("field") == "Tổng"]
        go_opts["columnDefs"] = pinned_defs + time_col_groups

        # --- Grid options (Tree Data) ---
        go_opts["treeData"] = True
        go_opts["getDataPath"] = JsCode("function(data) { return (data.path_str || '').split('###'); }")
        go_opts["groupDefaultExpanded"] = 0
        go_opts["animateRows"] = True
        go_opts["autoGroupColumnDef"] = {
            "headerName": " > ".join(disp_dims),
            "minWidth": 340,
            "pinned": "left",
            "cellRendererParams": {"suppressCount": False},
            "cellStyle": {"fontWeight": "500"},
        }
        go_opts["rowHeight"] = 36
        go_opts["headerHeight"] = 34
        go_opts["groupHeaderHeight"] = 32
        go_opts["suppressRowClickSelection"] = True
        go_opts["enableRangeSelection"] = True
        go_opts["suppressAggFuncInHeader"] = True
        go_opts["groupIncludeTotalFooter"] = True
        go_opts["groupIncludeFooter"] = False

        st.markdown(
            f"**Bảng drilldown · {mv_label}** — phân cấp thời gian **Năm → Quý → Tháng**"
            + (" · kèm tăng trưởng xen kẽ" if show_growth else "")
            # + " · bấm **▶** ở cột đầu để mở rộng cấp khách hàng, bấm **[+]** trên tiêu đề để mở rộng cấp thời gian"
        )
        st.caption(
            f"{len(pivot_df)} dòng dữ liệu · cây phân cấp: {' → '.join(disp_dims)}"
            + (" · Sản phẩm giấy là tập con của riêng Bao bì giấy" if use_paper_layer else "")
        )

        AgGrid(
            pivot_df,
            gridOptions=go_opts,
            enable_enterprise_modules=True,
            height=min(680, 70 + 36 * min(len(pivot_df) + len(disp_dims), 20)),
            fit_columns_on_grid_load=False,
            theme=AgGridTheme.BALHAM,
            allow_unsafe_jscode=True,
            update_mode="NO_UPDATE",
            columns_auto_size_mode=ColumnsAutoSizeMode.NO_AUTOSIZE,
        )

    # ── Tải toàn bộ dữ liệu (1 button trực tiếp) ────────────────
    st.markdown("---")
    pf_full, ycols_f = _build_pivot_freq(orders_all_filt, dim_cols, mv, "Y", start, end)
    pf_full_q, qcols_f = _build_pivot_freq(orders_all_filt, dim_cols, mv, "Q", start, end)
    pf_full_m, mcols_f = _build_pivot_freq(orders_all_filt, dim_cols, mv, "M", start, end)
    export_df = pf_full.merge(pf_full_q, on=dim_cols, how="outer") \
                       .merge(pf_full_m, on=dim_cols, how="outer").fillna(0)
    export_df = export_df.rename(columns=rename_dim)
    full_disp_dims = [rename_dim.get(c, c) for c in dim_cols]
    export_df.insert(len(full_disp_dims), "Tổng", export_df[ycols_f].sum(axis=1))

    st.download_button(
        label=f"📥 Tải toàn bộ dữ liệu sau khi lọc (CSV) — {len(export_df)} dòng · {mv_label}",
        data=export_df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"lich_su_full_{mv}_{start:%Y%m%d}_{end:%Y%m%d}.csv",
        mime="text/csv",
        key="dl_full_csv_direct",
        help="Bấm để tải file CSV gồm tất cả khách hàng theo bộ lọc, phân cấp Năm → Quý → Tháng"
    )


# ------------------------------------------------------------------
# TAB 5: Giải thích
# ------------------------------------------------------------------
if tab_help is not None:
  with tab_help:
    st.markdown(f"""
#### Một "lần mua" được tính thế nào
Tất cả dòng giao dịch của cùng một khách (và cùng nhóm sản phẩm, nếu phân tích theo cặp) trong cùng một ngày
được gộp thành **một lần mua**. Nhờ vậy một đơn tách thành nhiều dòng không bị đếm thành nhiều lần mua
cách nhau 0 ngày. Các dòng trùng, dòng âm và dòng thiếu dữ liệu đã được loại ở bước làm sạch
(xem tab Làm sạch dữ liệu).

#### Các chỉ số chính
**TB ngày/lần**: số ngày trung bình giữa hai lần mua liên tiếp. **Trung vị ngày/lần** ít bị ảnh hưởng
bởi một vài khoảng nghỉ dài bất thường, nên khi hai con số này chênh nhau nhiều thì hãy tin trung vị hơn.

**CV (hệ số biến thiên)** = độ lệch chuẩn ÷ trung bình. Nó cho biết mức dao động so với mức bình thường,
nên so sánh được giữa khách mua hằng tuần và khách mua mỗi quý. Ví dụ khách mua cách nhau 28, 30, 32, 29 ngày
có CV khoảng 0,05 (rất đều); khách mua cách nhau 5, 60, 12, 90 ngày có CV khoảng 1 (thất thường).
Ngưỡng hiện tại: CV thời gian dưới **{timing_cv:.2f}** là đều, CV khối lượng dưới **{qty_cv:.2f}** là ổn định.

**% tháng có mua**: trong khoảng từ tháng mua đầu đến tháng mua cuối, bao nhiêu phần trăm số tháng khách có mua.

**Xu hướng tần suất**: đường xu hướng của các khoảng cách theo thời gian. "Đang thưa dần" nghĩa là khoảng cách
đã tăng ít nhất 30% so với chu kỳ trung bình và xu hướng đủ rõ (R² từ 0,2). Đây thường là tín hiệu sớm
trước khi khách ngừng mua.

**Thứ hay mua, % chung của thứ đó và p**: thứ trong tuần khách mua nhiều nhất, so với tỷ lệ của thứ đó trên
toàn bộ khách hàng. p là xác suất thấy mức chênh như vậy chỉ do trùng hợp (đã hiệu chỉnh vì thứ này được chọn
sau khi nhìn dữ liệu). p dưới 0,05 mới nên coi là thói quen thật. Nhờ so với mức chung, doanh nghiệp không bán
cuối tuần không bị báo nhầm là "có thói quen".

**ABC**: xếp theo {value_name}. Nhóm A tạo ra 80% {value_name} đầu tiên, B là 15% tiếp theo, C là phần còn lại.

#### Bốn nhóm tính cách
- **Đều thời gian & số lượng**: gần như biết trước cả ngày lẫn số lượng. Lên kế hoạch nguyên liệu trực tiếp.
- **Đều thời gian, số lượng dao động**: biết khi nào cần chuẩn bị, cộng thêm tồn kho an toàn cho phần số lượng.
- **Thời gian thất thường, số lượng ổn định**: biết mỗi lần cần bao nhiêu, dùng tồn kho theo điểm đặt hàng lại.
- **Thất thường cả hai**: nên dự báo gộp theo nhóm sản phẩm thay vì theo từng khách.
- **Chưa đủ dữ liệu**: dưới {min_orders} lần mua.

#### Trạng thái tại ngày đánh giá
Chỉ các nhóm có thời gian đều mới được xếp **Chưa đến hạn / Sắp đến hạn / Quá hạn**, dựa trên cửa sổ
TB ngày/lần ± {k:.1f} × độ lệch chuẩn, tính từ ngày mua gần nhất. Số ngày từ lần mua cuối nhỏ hơn ngày đầu
của cửa sổ là **Chưa đến hạn**, nằm trong cửa sổ (tính cả hai đầu) là **Sắp đến hạn**, vượt ngày cuối của cửa
sổ là **Quá hạn**. Nhóm thời gian thất thường được ghi là **Khó đoán thời điểm**.
**Đã ngừng mua** khi số ngày im lặng vượt {int(churn_days)} ngày hoặc {churn_mult:.1f} lần chu kỳ bình thường
(lấy mức lớn hơn).
""")
