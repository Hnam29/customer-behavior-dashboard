"""
behavior.py - Phân tích "tính cách mua hàng" của từng khách hàng.

Tách riêng khỏi giao diện để có thể dùng lại trong pipeline khác:
    from behavior import clean_transactions, compute_profiles

Nguyên tắc chính (khắc phục các lỗi đã review ở bản cũ):
  * 1 "lần mua" = 1 (khách, [sản phẩm], ngày). Nhiều dòng cùng ngày được gộp,
    nên không còn khoảng cách 0 ngày làm méo trung bình và CV.
  * Làm sạch theo thứ tự: trùng lặp -> dòng âm -> bổ sung/loại dòng thiếu
    (xem clean_transactions). Mọi dòng bị loại đều được ghi lại kèm lý do.
  * Thói quen mua theo thứ trong tuần được kiểm định so với mức chung của toàn
    bộ khách, để tránh "trùng hợp" khi có ít đơn và tránh báo nhầm khi doanh
    nghiệp không bán cuối tuần.
  * Xu hướng tần suất được chuẩn hóa theo chu kỳ riêng của từng khách.
"""

import numpy as np
import pandas as pd
import re
import unicodedata

# ------------------------------------------------------------------
# Nhãn hiển thị
# ------------------------------------------------------------------
SEG_LABEL = {
    "FIXED_CYCLE": "Đều thời gian & số lượng",
    "PREDICTABLE_TIMING_VAR_QTY": "Đều thời gian, số lượng dao động",
    "VARIABLE_TIMING_STABLE_QTY": "Thời gian thất thường, số lượng ổn định",
    "IRREGULAR": "Thất thường cả hai",
    "INSUFFICIENT_DATA": "Chưa đủ dữ liệu",
}
SEG_ORDER = list(SEG_LABEL.values())

STATUS_ORDER = ["Chưa đến hạn", "Sắp đến hạn", "Quá hạn",
                "Khó đoán thời điểm", "Chưa đủ dữ liệu", "Đã ngừng mua"]

DOW_VN = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]

STD_COLS = ["date", "customer", "product", "unit", "quantity", "unit_price", "amount",
            "contract_number", "category", "ingredient", "product_name", "paper_type"]

DATE_FORMATS = {"auto": "Tự nhận diện", "mdy": "Tháng/Ngày/Năm (mm/dd/yyyy)",
                "dmy": "Ngày/Tháng/Năm (dd/mm/yyyy)"}
REQUIRED_COLS = ["date", "customer", "product", "quantity"]   # bắt buộc phải ghép cột


# ------------------------------------------------------------------
# 1. Đọc ngày
# ------------------------------------------------------------------
_DATE_RE = r"^\s*(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{2,4})"


def parse_dates(series, date_format="auto"):
    """
    Đọc cột ngày một cách tường minh, KHÔNG để pandas tự đoán từng dòng.
    Lý do: với chuỗi 03/05/2024, việc đoán theo từng dòng sẽ hiểu là 3/5 ở
    dòng này nhưng 25/3 ở dòng 03/25/2024, làm lệch ngày mà không báo lỗi.

    date_format: "mdy", "dmy" hoặc "auto" (dựa vào các dòng có phần > 12).
    Ô đã là kiểu ngày của Excel được giữ nguyên; số seri ngày Excel
    (vd 45371) cũng được đổi đúng.
    Trả về (series_datetime, định_dạng_đã_dùng, có_mơ_hồ_không).
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return series, "excel", False
    if pd.api.types.is_numeric_dtype(series):
        return (pd.to_datetime(series, unit="D", origin="1899-12-30", errors="coerce"),
                "excel", False)

    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    is_dt = series.map(lambda v: isinstance(v, (pd.Timestamp, np.datetime64)) or
                       hasattr(v, "year") and hasattr(v, "month"))
    if is_dt.any():
        out[is_dt] = pd.to_datetime(series[is_dt], errors="coerce")

    txt = series[~is_dt].astype(str)
    parts = txt.str.extract(_DATE_RE)
    a, b, c = (pd.to_numeric(parts[i], errors="coerce") for i in range(3))

    iso = parts[0].str.len() == 4                      # yyyy-mm-dd
    used, ambiguous = date_format, False
    if date_format == "auto" and a.notna().any() and iso[a.notna()].all():
        used = "iso"                                   # toàn bộ là yyyy-mm-dd: không mơ hồ
    elif date_format == "auto":
        # Đếm "bằng chứng" theo đa số, không dựa vào 1 dòng: một ô nhập sai như
        # 13/45/2024 (cả 2 phần > 12) không được phép làm lật định dạng cả cột.
        ev_dmy = int(((a > 12) & (b <= 12) & ~iso).sum())
        ev_mdy = int(((b > 12) & (a <= 12) & ~iso).sum())
        if ev_dmy == 0 and ev_mdy == 0:
            used, ambiguous = "dmy", bool((~iso & a.notna()).any())
        else:
            used = "dmy" if ev_dmy > ev_mdy else "mdy"

    if used == "mdy":
        month, day, year = a, b, c
    else:
        day, month, year = a, b, c
    year = year.where(year >= 100, year + 2000)
    y = a.where(iso, year)
    m = b.where(iso, month)
    d = c.where(iso, day)
    built = pd.to_datetime(pd.DataFrame({"year": y, "month": m, "day": d}), errors="coerce")
    out[~is_dt] = built.values
    return out, used, ambiguous


# ------------------------------------------------------------------
# 2. Làm sạch
# ------------------------------------------------------------------
FIELD_LABEL = {"date": "Ngày", "customer": "Khách hàng", "product": "Nhóm sản phẩm",
               "unit": "Đơn vị tính", "quantity": "Số lượng", "unit_price": "Đơn giá",
               "amount": "Thành tiền", "contract_number": "Số hợp đồng",
               "category": "Nhóm sản phẩm", "product_name": "Sản phẩm cụ thể",
               "ingredient": "Nguyên liệu gốc", "paper_type": "Sản phẩm giấy"}


def _is_blank(s):
    """Ô trống: NaN/None hoặc chỉ có khoảng trắng."""
    return s.isna() | s.astype(str).str.strip().isin(["", "nan", "NaN", "None", "NaT"])


def _clean_text(s, case=None):
    """
    Chuẩn hóa chữ: bỏ khoảng trắng thừa (cả ở giữa), ô trống -> NaN.
    Số nguyên bị Excel lưu dạng 12345.0 -> "12345" (hay gặp ở số hợp đồng, mã KH).
    """
    def conv(v):
        if v is None or v is pd.NA or v is pd.NaT:
            return np.nan
        if isinstance(v, (float, np.floating)):
            if np.isnan(v):
                return np.nan
            if float(v).is_integer():
                v = int(v)
        t = " ".join(str(v).split())
        return t if t and t.lower() not in ("nan", "none", "null", "nat") else np.nan

    out = s.map(conv).astype(object)
    if case == "upper":
        out = out.map(lambda v: v.upper() if isinstance(v, str) else v)
    elif case == "lower":
        out = out.map(lambda v: v.lower() if isinstance(v, str) else v)
    return out


def _to_number(s):
    """
    Đổi sang số, hiểu được các kiểu viết hay gặp trong file xuất:
    1,234,567.5 | 1.234.567,5 | 12,5 | (1.200) = -1200 | có khoảng trắng.
    """
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce").astype(float)
    t = s.astype("string").str.replace(r"\s", "", regex=True)
    neg = t.str.match(r"^\(.*\)$").fillna(False).astype(bool)
    t = t.str.replace(r"^\((.*)\)$", r"\1", regex=True)
    us = t.str.match(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$").fillna(False).astype(bool)
    vn = t.str.match(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$").fillna(False).astype(bool)
    dec_comma = t.str.match(r"^-?\d+,\d+$").fillna(False).astype(bool) & ~us
    t = t.mask(us, t.str.replace(",", "", regex=False))
    t = t.mask(vn, t.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    t = t.mask(dec_comma, t.str.replace(",", ".", regex=False))
    out = pd.to_numeric(t, errors="coerce").astype(float)
    return out.mask(neg, -out)


def classify_category(product_series):
    """
    Phân loại nhóm sản phẩm (category) từ tên sản phẩm / tên thành phẩm / vật tư.
 
    Logic:
      1. Chuẩn hóa Unicode (NFC), viết thường, gộp khoảng trắng.
      2. Danh từ chính = từ khóa xuất hiện SỚM NHẤT trong tên; trùng vị trí -> cụm dài hơn.
         ("Tem dán thùng" -> nhãn mác, "Hộp đựng thẻ cào" -> bao bì giấy)
      3. Khớp theo ranh giới từ, không khớp chuỗi con.
      4. Tên có dấu -> khớp từ khóa có dấu; không thấy -> thử lại trên bản bỏ dấu.
      5. Hộp/vỏ/khay/box có dấu hiệu sóng hoặc khai triển vượt khổ tờ offset -> hộp carton.
      6. "Gia công ..." là bổ ngữ: phân loại theo phần còn lại.
    """
    # ------------------------------------------------------------------
    # Nhóm chi tiết -> nhóm đầu ra. Mặc định giữ đúng tập nhóm cũ (khớp SQL).
    # Muốn tách riêng, đổi giá trị, ví dụ: "vat_tu": "vật tư", "hang_nhua": "hàng nhựa",
    # "dich_vu": "dịch vụ gia công".
    # ------------------------------------------------------------------
    report_group = {
        "the_cao": "thẻ cào",
        "nhan_mac": "nhãn mác",
        "hop_carton": "hộp carton",
        "bao_bi_giay": "bao bì giấy",
        "bao_bi_giay_hop": "bao bì giấy",
        "an_pham": "ấn phẩm",
        "vat_tu": "ấn phẩm",
        "hang_nhua": "nhãn mác",
        "dich_vu": "Khác",
        "khac": "Khác",
    }
    offset_max_sheet_mm = 1060   # cạnh dài tối đa tờ in Rapida 106
    glue_flap_mm = 30
 
    # Tiền tố "!" = chỉ khớp khi tên có dấu (bản bỏ dấu dễ trùng: sổ/số, bìa/bia, kẽm/kem, phí/phi...)
    head_rules = [
        ("the_cao", [r"thẻ cào", r"phiếu cào", r"thẻ nạp", r"thẻ điện thoại", r"scratch\s*cards?",
                     r"thẻ giấy"]),
        ("nhan_mac", [r"nhãn", r"tem", r"decal", r"đề can", r"stickers?", r"labels?", r"màng co",
                      r"thẻ treo", r"hang\s*tags?"]),
        ("hang_nhua", [r"quai nhựa", r"thùng nhựa", r"hộp nhựa", r"khay nhựa", r"nhựa"]),
        ("hop_carton", [r"thùng", r"tấm sóng", r"carton", r"master\s*carton"]),
        ("bao_bi_giay_hop", [r"hộp", r"vỏ hộp", r"!vỏ", r"(paper |gift |colou?r )?box(es)?", r"khay",
                             r"trays?", r"hg", r"ib"]),
        ("bao_bi_giay", [r"túi", r"bags?", r"tút", r"!bìa", r"giấy", r"sleeve"]),
        ("an_pham", [r"catalogue", r"catalog", r"brochure", r"tờ rơi", r"tờ gấp", r"leaflet", r"flyer",
                     r"poster", r"lịch", r"!sổ", r"!sách", r"tạp chí", r"hướng dẫn sử dụng", r"hdsd",
                     r"manual", r"phiếu", r"thẻ bảo hành", r"thiệp", r"danh thiếp", r"name\s*card",
                     r"card visit", r"phong bì", r"voucher", r"coupon", r"standee", r"wobbler",
                     r"(hóa|hoá) đơn", r"biểu mẫu", r"tờ in", r"(ủy|uỷ) nhiệm thu", r"thông báo cước",
                     r"giấy chứng nhận", r"giấy mời", r"giấy khen", r"bìa hồ sơ", r"bìa sách"]),
        ("vat_tu", [r"mực offset", r"!mực", r"bản kẽm", r"!kẽm",
                    r"màng (pvc|pet|opp|bopp|mờ|bóng|ép nhũ)", r"!màng", r"keo bồi", r"keo dán", r"!keo"]),
        ("dich_vu", [r"bản in", r"chế bản", r"khuôn bế", r"!khuôn", r"!phí", r"cán màng", r"!bế",
                     r"dán hộp"]),
    ]
    carton_signals = [r"!sóng", r"song [ebc]{1,2}", r"\d\s*lớp", r"carton", r"flute", r"bồi sóng"]
 
    gia_cong_re = re.compile(r"(?<!\w)gia c[ôo]ng(?!\w)")
    size_re = re.compile(
        r"(\d+(?:[.,]\d+)?)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*(mm|cm)?"
    )
 
    def _strip_accents(t):
        t = t.replace("đ", "d").replace("Đ", "D")
        return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
 
    def _compile(p):
        accent_only = p.startswith("!")
        p = p.lstrip("!")
        acc = re.compile(rf"(?<!\w){p}(?!\w)")
        noacc = None if accent_only else re.compile(rf"(?<!\w){_strip_accents(p)}(?!\w)")
        return acc, noacc
 
    heads = [(i, sub, _compile(p)) for i, (sub, pats) in enumerate(head_rules) for p in pats]
    cartons = [_compile(p) for p in carton_signals]
 
    def _find_head(text, accented):
        best = None
        for order, sub, (acc, noacc) in heads:
            rx = acc if accented else noacc
            if rx is None:
                continue
            m = rx.search(text)
            if m:
                key = (m.start(), -(m.end() - m.start()), order)
                if best is None or key < best[0]:
                    best = (key, sub)
        return None if best is None else best[1]
 
    def _has_carton_signal(text, accented):
        for acc, noacc in cartons:
            rx = acc if accented else noacc
            if rx is not None and rx.search(text):
                return True
        return False
 
    def _blank_length_mm(text):
        m = size_re.search(text)
        if not m:
            return None
        dims = [float(x.replace(",", ".")) for x in m.groups()[:3]]
        if m.group(4) == "cm" or (m.group(4) is None and max(dims) <= 60):
            dims = [d * 10 for d in dims]
        a, b, _ = sorted(dims)
        return 2 * (a + b) + glue_flap_mm
 
    cache = {}
 
    def _cat(s):
        try:
            if pd.isna(s):
                return report_group["khac"]
        except (TypeError, ValueError):
            pass
        raw = str(s)
        if raw in cache:
            return cache[raw]
 
        t = re.sub(r"\s+", " ", unicodedata.normalize("NFC", raw)).strip().lower()
        if not t:
            cache[raw] = report_group["khac"]
            return cache[raw]
 
        gia_cong = bool(gia_cong_re.search(t))
        body = gia_cong_re.sub(" ", t).strip() if gia_cong else t
 
        accented = _strip_accents(body) != body
        text = body
        sub = _find_head(body, True) if accented else None
        if sub is None:
            accented, text = False, _strip_accents(body)
            sub = _find_head(text, False)
 
        if sub is None:
            sub = "dich_vu" if gia_cong else "khac"
        elif sub == "bao_bi_giay_hop":
            blank = _blank_length_mm(text)
            if _has_carton_signal(text, accented) or (blank and blank > offset_max_sheet_mm):
                sub = "hop_carton"
 
        cache[raw] = report_group[sub]
        return cache[raw]
 
    return product_series.map(_cat)



def _unique_map(df, key_cols, value_col):
    """key -> value, chỉ giữ các key có đúng 1 giá trị khác nhau (không mơ hồ)."""
    known = df.dropna(subset=key_cols + [value_col])
    if known.empty:
        return pd.Series(dtype=object), set()
    g = known.groupby(key_cols)[value_col]
    nun = g.nunique()
    first = g.first()
    return first[nun == 1], set(nun[nun > 1].index)


def clean_transactions(raw, mapping, drop_exact_duplicates=True, date_format="auto"):
    """
    Làm sạch theo đúng thứ tự:
      0. Chuẩn hóa định dạng (không xóa dòng): đọc ngày, đọc số, bỏ khoảng trắng thừa
      1. Loại dòng trùng lặp hoàn toàn
      2. Loại dòng âm (số lượng, đơn giá hoặc thành tiền < 0)
      3. Bổ sung dữ liệu thiếu khi suy ra được chắc chắn, rồi loại dòng vẫn còn thiếu
         - Số lượng / đơn giá / thành tiền: tính từ 2 trường còn lại
         - Khách hàng: lấy theo số hợp đồng (nếu hợp đồng chỉ thuộc 1 khách)
         - Sản phẩm: lấy theo số hợp đồng (nếu hợp đồng chỉ có 1 sản phẩm), hoặc theo
           số hợp đồng + đơn giá (nếu trong hợp đồng chỉ 1 sản phẩm có đơn giá đó)
         - Đơn vị tính: lấy theo sản phẩm (nếu sản phẩm chỉ có 1 đơn vị)
         Bắt buộc có: ngày, khách, sản phẩm, số lượng > 0; và đơn giá, thành tiền,
         số hợp đồng nếu các cột này có trong file.

    mapping: {tên chuẩn: tên cột trong file hoặc None}
    Trả về (df_sạch, report). report chứa số liệu từng bước và các bảng chi tiết
    (dòng bị loại kèm lý do, dòng được bổ sung, ví dụ dòng trùng...).
    """
    missing_cols = [c for c in REQUIRED_COLS if mapping.get(c) is None]
    if missing_cols:
        raise ValueError(f"Thiếu cột bắt buộc: {', '.join(missing_cols)}")

    df = pd.DataFrame({k: raw[c].values for k, c in mapping.items() if c is not None})
    df.insert(0, "source_row", np.arange(len(raw)) + 2)     # dòng 1 là tiêu đề
    mapped = [c for c in STD_COLS if c in df]
    report = {"rows_in": len(df), "mapped": mapped, "drop_duplicates": drop_exact_duplicates}

    # ---------- Bước 0: chuẩn hóa ----------
    blank0 = {c: _is_blank(df[c]) for c in mapped}
    raw_date = df["date"].copy()
    d, used_fmt, ambiguous = parse_dates(df["date"], date_format)
    df["date"] = pd.to_datetime(d).dt.normalize()
    for c in ("quantity", "unit_price", "amount"):
        if c in df:
            df[c] = _to_number(df[c])
    df["customer"] = _clean_text(df["customer"])
    df["product"] = _clean_text(df["product"], "upper")
    if "category" in df:
        df["category"] = _clean_text(df["category"], "lower")
    if "ingredient" in df:
        df["ingredient"] = _clean_text(df["ingredient"], "upper")
    if "product_name" in df:
        df["product_name"] = _clean_text(df["product_name"], "upper")
    if "unit" in df:
        df["unit"] = _clean_text(df["unit"], "lower")
    if "contract_number" in df:
        df["contract_number"] = _clean_text(df["contract_number"], "upper")
    unreadable = {c: df[c].isna() & ~blank0[c] for c in mapped}
    report.update(date_format_used=used_fmt, date_ambiguous=ambiguous,
                  bad_date=int((df["date"].isna()).sum()))

    removed, steps = [], [("Tổng số dòng trong file", 0, len(df))]
    info_cols = ["source_row"] + mapped

    def _drop(mask, step, reasons):
        nonlocal df
        part = df.loc[mask, info_cols].copy()
        part.insert(1, "step", step)
        part.insert(2, "reason", reasons[mask] if isinstance(reasons, pd.Series) else reasons)
        removed.append(part)
        df = df[~mask].copy()
        steps.append((step, int(mask.sum()), len(df)))

    # ---------- Bước 1: trùng lặp ----------
    # So sánh trên giá trị đã chuẩn hóa. Riêng ngày không đọc được thì so theo chữ
    # gốc, để 2 dòng khác ngày cùng bị lỗi ngày không bị coi là trùng nhau.
    cmp = df.drop(columns="source_row").copy()
    cmp["date"] = df["date"].dt.strftime("%Y-%m-%d").where(df["date"].notna(),
                                                           "raw:" + raw_date.astype(str))
    cmp_cols = list(cmp.columns)
    dup_mask = cmp.duplicated(keep="first")
    dup_any = cmp.duplicated(keep=False)
    first_row = cmp.assign(_r=df["source_row"]).groupby(cmp_cols, dropna=False)["_r"].transform("first")
    report["dup_found"] = int(dup_mask.sum())
    report["dup_examples"] = (df[dup_any].assign(first_row=first_row[dup_any])
                                .sort_values(["first_row", "source_row"]).head(300))
    step1 = "1. Loại dòng trùng lặp"
    if drop_exact_duplicates:
        _drop(dup_mask, step1, "Trùng hoàn toàn với dòng " + first_row.astype(int).astype(str))
    else:
        steps.append((step1 + " (đang tắt)", 0, len(df)))

    # ---------- Bước 2: dòng âm ----------
    neg_fields = {c: (df[c] < 0) for c in ("quantity", "unit_price", "amount") if c in df}
    neg_mask = pd.concat(neg_fields.values(), axis=1).any(axis=1)
    reason = pd.Series("", index=df.index, dtype=object)
    for c, m in neg_fields.items():
        reason = reason.where(~m, reason + np.where(reason == "", "", ", ") + FIELD_LABEL[c] + " âm")
    report["neg_counts"] = {FIELD_LABEL[c] + " âm": int(m.sum()) for c, m in neg_fields.items()}
    _drop(neg_mask, "2. Loại dòng âm", reason)

    # ---------- Bước 3: bổ sung, rồi loại dòng còn thiếu ----------
    miss_start = {c: int(df[c].isna().sum()) for c in mapped}
    fills = []

    def _fill(mask, col, values, method):
        mask = mask & pd.Series(values, index=df.index).notna()
        if mask.any():
            df.loc[mask, col] = pd.Series(values, index=df.index)[mask]
            fills.append(pd.DataFrame({"source_row": df.loc[mask, "source_row"],
                                       "field": FIELD_LABEL[col],
                                       "value": df.loc[mask, col].astype(str),
                                       "method": method}))

    has_p, has_a = "unit_price" in df, "amount" in df
    if has_p and has_a:
        q, p, a = df["quantity"], df["unit_price"], df["amount"]
        _fill(q.isna() & p.gt(0) & a.notna(), "quantity", (a / p).round(6), "Thành tiền ÷ đơn giá")
        q = df["quantity"]
        _fill(p.isna() & q.gt(0) & a.notna(), "unit_price", (a / q).round(6), "Thành tiền ÷ số lượng")
        p = df["unit_price"]
        _fill(a.isna() & q.notna() & p.notna(), "amount", q * p, "Số lượng × đơn giá")

    ambig = {"customer": pd.Series(False, index=df.index), "product": pd.Series(False, index=df.index)}
    if "contract_number" in df:
        hd = df["contract_number"]
        cmap, c_multi = _unique_map(df, ["contract_number"], "customer")
        m = df["customer"].isna() & hd.notna()
        _fill(m, "customer", hd.map(cmap), "Theo số hợp đồng")
        ambig["customer"] = df["customer"].isna() & hd.isin(c_multi)

        pmap, p_multi = _unique_map(df, ["contract_number"], "product")
        m = df["product"].isna() & hd.notna()
        _fill(m, "product", hd.map(pmap), "Theo số hợp đồng (hợp đồng chỉ có 1 sản phẩm)")
        if has_p:
            pp_map, _ = _unique_map(df, ["contract_number", "unit_price"], "product")
            m = df["product"].isna() & hd.notna() & df["unit_price"].notna()
            if m.any() and len(pp_map):
                keys = pd.MultiIndex.from_arrays([hd[m], df.loc[m, "unit_price"]])
                vals = pd.Series(pp_map.reindex(keys).values, index=df.index[m])
                _fill(m, "product", vals.reindex(df.index), "Theo số hợp đồng + đơn giá")
        ambig["product"] = df["product"].isna() & hd.isin(p_multi)

    if "unit" in df:
        umap, _ = _unique_map(df, ["product"], "unit")
        _fill(df["unit"].isna() & df["product"].notna(), "unit", df["product"].map(umap),
              "Theo sản phẩm (sản phẩm chỉ có 1 đơn vị)")

    if not has_a:                       # không có cột thành tiền -> tự tính
        df["amount"] = df["quantity"] * df["unit_price"] if has_p else np.nan

    required = ["date", "customer", "product", "quantity"] + \
               [c for c in ("unit_price", "amount", "contract_number") if c in mapped]
    reason = pd.Series("", index=df.index, dtype=object)
    miss_end = {}
    for c in required:
        m = df[c].isna()
        miss_end[c] = int(m.sum())
        word = np.where(unreadable[c].reindex(df.index, fill_value=False), "không đọc được", "trống")
        extra = ""
        if c in ambig:
            extra = np.where(ambig[c], f" (hợp đồng có nhiều {FIELD_LABEL[c].lower()})", "")
        txt = FIELD_LABEL[c] + " " + pd.Series(word, index=df.index) + extra
        reason = reason.where(~m, reason + np.where(reason == "", "", "; ") + txt)
    zero = df["quantity"].eq(0)
    reason = reason.where(~zero, reason + np.where(reason == "", "", "; ") + "Số lượng = 0")
    _drop(reason != "", "3. Loại dòng thiếu dữ liệu", reason)

    fill_log = (pd.concat(fills, ignore_index=True) if fills
                else pd.DataFrame(columns=["source_row", "field", "value", "method"]))
    rows = []
    for c in mapped:
        n_fill = int((fill_log["field"] == FIELD_LABEL[c]).sum())
        how = ", ".join(fill_log.loc[fill_log["field"] == FIELD_LABEL[c], "method"].unique())
        rows.append({"field": FIELD_LABEL[c], "required": c in required,
                     "missing": miss_start[c], "filled": n_fill, "how": how,
                     "still_missing": miss_end.get(c, int(df[c].isna().sum()) if c in df else 0)})
    rows.append({"field": "Số lượng = 0", "required": True, "missing": int(zero.sum()),
                 "filled": 0, "how": "", "still_missing": int(zero.sum())})
    report["missing_table"] = pd.DataFrame(rows)
    report["fill_log"] = fill_log
    steps.append(("Dùng để phân tích", 0, len(df)))
    report["steps"] = pd.DataFrame(steps, columns=["step", "removed", "remaining"])
    report["removed"] = (pd.concat(removed, ignore_index=True) if removed
                         else pd.DataFrame(columns=["source_row", "step", "reason"] + mapped))

    # ---------- Kiểm tra thêm (không xóa dòng) ----------
    if has_p and has_a:
        derived = set(fill_log.loc[fill_log["field"].isin(["Đơn giá", "Thành tiền", "Số lượng"]),
                                   "source_row"])
        mism = ((df["amount"] - df["quantity"] * df["unit_price"]).abs() > 1) & \
               ~df["source_row"].isin(derived)
        report["amount_mismatch"] = int(mism.sum())
        report["mismatch_examples"] = df.loc[mism, info_cols].head(200)
    else:
        report["amount_mismatch"] = None
        report["mismatch_examples"] = None
    if "unit" in df:
        n_units = df.dropna(subset=["unit"]).groupby("product")["unit"].nunique()
        report["multi_unit_products"] = sorted(n_units[n_units > 1].index.tolist())
        df["unit"] = df["unit"].fillna("(không rõ)")
    else:
        report["multi_unit_products"] = []
    report["rows_out"] = len(df)
    report["has_amount"] = bool(df["amount"].notna().any())
    return df.reset_index(drop=True), report


def split_products_by_unit(df, products=None):
    """
    Sản phẩm bán theo nhiều đơn vị tính (vd vừa 'cái' vừa 'thùng') thì cộng số
    lượng không có nghĩa. Hàm này tách thành 'TÊN SP [đơn vị]' cho các sản
    phẩm đó (mặc định: mọi sản phẩm có > 1 đơn vị).

    Khi có cột product_name (tên sản phẩm cụ thể), chỉ thêm [đơn vị] vào cột đó;
    cột product (nhóm sản phẩm / category) giữ nguyên để không làm vỡ nhãn nhóm.
    """
    if "unit" not in df:
        return df
    # Ưu tiên tách product_name nếu có, để category không bị gắn đơn vị
    split_col = "product_name" if "product_name" in df.columns else "product"
    if products is None:
        n_units = df.groupby(split_col)["unit"].nunique()
        products = n_units[n_units > 1].index
    df = df.copy()
    mask = df[split_col].isin(products)
    df.loc[mask, split_col] = df.loc[mask, split_col] + " [" + df.loc[mask, "unit"] + "]"
    return df


# ------------------------------------------------------------------
# 3. Tiện ích thống kê
# ------------------------------------------------------------------
def rayleigh_p(n, r):
    """
    p-value kiểm định Rayleigh (xấp xỉ Zar). p nhỏ (< 0.05) = các lần mua
    tập trung vào 1 điểm trong chu kỳ nhiều hơn mức ngẫu nhiên.
    """
    n = np.asarray(n, dtype=float)
    rn = n * np.asarray(r, dtype=float)
    with np.errstate(invalid="ignore"):
        p = np.exp(np.sqrt(1 + 4 * n + 4 * (n ** 2 - rn ** 2)) - (1 + 2 * n))
    return np.clip(p, 0, 1)


def dominant_day_p(k, n, p0, n_days):
    """
    p-value cho câu hỏi: "khách có mua vào thứ phổ biến nhất của họ NHIỀU HƠN
    mức chung của toàn bộ khách hàng không?"
    - k: số lần khách mua vào thứ đó, n: tổng số lần mua
    - p0: tỷ lệ chung của thứ đó trên toàn bộ dữ liệu (vd B2B: thứ 7 gần 0%)
    - n_days: số thứ có phát sinh đơn -> hiệu chỉnh Bonferroni vì "thứ phổ biến
      nhất" được chọn sau khi đã nhìn dữ liệu.
    So với mức chung (không phải 7 ngày đều nhau) nên doanh nghiệp không bán cuối
    tuần không còn bị báo "có thói quen" nhầm.
    """
    from math import exp, lgamma, log
    out = []
    for kk, nn, pp in zip(k, n, p0):
        if not (nn > 0) or not (0 < pp < 1) or pd.isna(kk):
            out.append(np.nan)
            continue
        kk, nn = int(kk), int(nn)
        tail = 0.0
        for j in range(kk, nn + 1):
            tail += exp(lgamma(nn + 1) - lgamma(j + 1) - lgamma(nn - j + 1)
                        + j * log(pp) + (nn - j) * log(1 - pp))
        out.append(min(1.0, tail * n_days))
    return np.array(out, dtype=float)


def _safe_div(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(b > 0, a / b, np.nan)
    return out


# ------------------------------------------------------------------
# 4. Hồ sơ hành vi
# ------------------------------------------------------------------
def build_orders(df, keys):
    """Gộp dòng giao dịch dương thành 'lần mua' theo ngày."""
    pos = df[df["quantity"] > 0]
    orders = (pos.groupby(keys + ["date"], as_index=False)
                 .agg(qty=("quantity", "sum"), amount=("amount", "sum"),
                      n_lines=("quantity", "size")))
    if not df["amount"].notna().any():
        orders["amount"] = np.nan
    return orders.sort_values(keys + ["date"]).reset_index(drop=True)


def compute_profiles(df, level="pair", vol_basis="qty", min_orders=5,
                     timing_cv=0.5, qty_cv=0.5, k=1.0,
                     churn_days=365, churn_mult=5.0, as_of=None,
                     trend_pct=30.0, trend_r2=0.2):
    """
    level      : "pair" (khách × sản phẩm) hoặc "customer" (gộp mọi sản phẩm)
    vol_basis  : "qty" hoặc "amount" - dùng để đo độ ổn định khối lượng mỗi lần.
                 Ở cấp khách hàng nên dùng "amount" vì các sản phẩm khác đơn vị.
    as_of      : ngày đánh giá trạng thái (mặc định = ngày cuối dữ liệu)

    Trả về (profiles, orders). Mỗi dòng profiles là 1 khách (hoặc 1 cặp).
    """
    keys = ["customer"] if level == "customer" else ["customer", "product"]
    as_of = pd.Timestamp(as_of) if as_of is not None else df["date"].max()
    df = df[df["date"] <= as_of]          # không dùng dữ liệu sau ngày đánh giá

    orders = build_orders(df, keys)
    orders["vol"] = orders[vol_basis]
    orders["interval"] = orders.groupby(keys)["date"].diff().dt.days
    orders["month"] = orders["date"].dt.to_period("M")
    orders["dow"] = orders["date"].dt.dayofweek
    ang_w = 2 * np.pi * orders["dow"] / 7
    ang_m = 2 * np.pi * (orders["date"].dt.day - 1) / 31
    orders["w_c"], orders["w_s"] = np.cos(ang_w), np.sin(ang_w)
    orders["m_c"], orders["m_s"] = np.cos(ang_m), np.sin(ang_m)

    g = orders.groupby(keys)
    prof = g.agg(
        n_orders=("date", "size"),
        first_date=("date", "min"),
        last_date=("date", "max"),
        total_qty=("qty", "sum"),
        total_amount=("amount", "sum"),
        avg_vol=("vol", "mean"),
        median_vol=("vol", "median"),
        std_vol=("vol", "std"),
        min_vol=("vol", "min"),
        max_vol=("vol", "max"),
        avg_interval=("interval", "mean"),
        median_interval=("interval", "median"),
        std_interval=("interval", "std"),
        min_interval=("interval", "min"),
        max_interval=("interval", "max"),
        months_active=("month", "nunique"),
        w_c=("w_c", "mean"), w_s=("w_s", "mean"),
        m_c=("m_c", "mean"), m_s=("m_s", "mean"),
    ).reset_index()
    if not df["amount"].notna().any():
        prof["total_amount"] = np.nan

    # --- đơn vị tính (để hiển thị "1.200 hộp" thay vì "1.200 đơn vị") ---
    if "unit" in df:
        u = df[df["quantity"] > 0].groupby(keys)["unit"].agg(n_units="nunique", unit="first").reset_index()
        u["unit"] = u["unit"].where(u["n_units"] == 1, "nhiều đơn vị")
        prof = prof.merge(u[keys + ["unit"]], on=keys, how="left")
    else:
        prof["unit"] = None

    # --- chỉ số dẫn xuất ---
    prof["interval_cv"] = _safe_div(prof["std_interval"], prof["avg_interval"])
    prof["qty_cv"] = _safe_div(prof["std_vol"], prof["avg_vol"])
    span_m = ((prof["last_date"].dt.year - prof["first_date"].dt.year) * 12
              + prof["last_date"].dt.month - prof["first_date"].dt.month + 1)
    prof["span_months"] = span_m
    prof["active_month_ratio"] = _safe_div(prof["months_active"], span_m) * 100
    prof["avg_amount_order"] = _safe_div(prof["total_amount"], prof["n_orders"])
    prof["orders_per_month"] = _safe_div(prof["n_orders"], span_m)
    prof["days_since_last"] = (as_of - prof["last_date"]).dt.days
    prof["expected_next"] = prof["last_date"] + pd.to_timedelta(prof["avg_interval"].round(), unit="D")
    prof["days_to_due"] = (prof["expected_next"] - as_of).dt.days

    # --- mẫu hình lịch ---
    prof["dom_R"] = np.sqrt(prof["m_c"] ** 2 + prof["m_s"] ** 2)
    prof["dom_p"] = rayleigh_p(prof["n_orders"], prof["dom_R"])
    mean_ang = np.mod(np.arctan2(prof["m_s"], prof["m_c"]), 2 * np.pi)
    prof["dom_center"] = np.round(mean_ang / (2 * np.pi) * 31 + 1).clip(1, 31)

    top_dow = (orders.groupby(keys + ["dow"]).size().rename("c").reset_index()
                     .sort_values(keys + ["c"], ascending=[True] * len(keys) + [False])
                     .drop_duplicates(keys))
    prof = prof.merge(top_dow, on=keys, how="left")
    prof["dow_share"] = _safe_div(prof["c"], prof["n_orders"]) * 100
    prof["dominant_dow"] = prof["dow"].map(lambda i: DOW_VN[int(i)] if pd.notna(i) else None)
    # so với tỷ lệ chung của thứ đó trên toàn bộ lần mua (không giả định 7 ngày đều nhau)
    base = orders["dow"].value_counts(normalize=True)
    prof["dow_base_share"] = prof["dow"].map(base) * 100
    prof["dow_lift"] = _safe_div(prof["dow_share"], prof["dow_base_share"])
    prof["dow_p"] = dominant_day_p(prof["c"], prof["n_orders"], prof["dow"].map(base),
                                   n_days=int((base > 0).sum()))
    prof = prof.drop(columns=["c", "dow", "w_c", "w_s", "m_c", "m_s"])

    # --- xu hướng khoảng cách (hồi quy tuyến tính, vector hóa) ---
    iv = orders.dropna(subset=["interval"])[keys + ["interval"]].copy()
    iv["x"] = iv.groupby(keys).cumcount().astype(float)
    gi = iv.groupby(keys)
    iv["dx"] = iv["x"] - gi["x"].transform("mean")
    iv["dy"] = iv["interval"] - gi["interval"].transform("mean")
    iv["sxy"], iv["sxx"], iv["syy"] = iv["dx"] * iv["dy"], iv["dx"] ** 2, iv["dy"] ** 2
    tr = iv.groupby(keys).agg(n_int=("x", "size"), sxy=("sxy", "sum"),
                              sxx=("sxx", "sum"), syy=("syy", "sum")).reset_index()
    tr["trend_slope"] = _safe_div(tr["sxy"], tr["sxx"])
    tr["trend_r2"] = _safe_div(tr["sxy"] ** 2, tr["sxx"] * tr["syy"])
    prof = prof.merge(tr[keys + ["n_int", "trend_slope", "trend_r2"]], on=keys, how="left")
    # % thay đổi của khoảng cách (theo đường xu hướng) từ lần đầu đến lần cuối,
    # so với chu kỳ trung bình -> so sánh được giữa khách chu kỳ ngắn và dài
    prof["trend_pct"] = _safe_div(prof["trend_slope"] * (prof["n_int"] - 1), prof["avg_interval"]) * 100
    has_trend = (prof["n_int"] >= 3) & (prof["trend_r2"] >= trend_r2)
    prof["trend"] = np.select(
        [prof["n_int"].fillna(0) < 3,
         has_trend & (prof["trend_pct"] >= trend_pct),
         has_trend & (prof["trend_pct"] <= -trend_pct)],
        ["Chưa đủ dữ liệu", "Đang thưa dần", "Đang dày lên"], "Ổn định")
    prof = prof.drop(columns=["n_int"])

    # --- phân loại ---
    enough = prof["n_orders"] >= min_orders
    t_reg = prof["interval_cv"] < timing_cv
    q_reg = prof["qty_cv"] < qty_cv
    seg = np.select([~enough, t_reg & q_reg, t_reg & ~q_reg, ~t_reg & q_reg],
                    ["INSUFFICIENT_DATA", "FIXED_CYCLE", "PREDICTABLE_TIMING_VAR_QTY",
                     "VARIABLE_TIMING_STABLE_QTY"], "IRREGULAR")
    prof["segment_code"] = seg
    prof["segment"] = pd.Categorical(prof["segment_code"].map(SEG_LABEL),
                                     categories=SEG_ORDER, ordered=True)

    # --- trạng thái tại ngày as_of ---
    std_i = prof["std_interval"].fillna(0)
    lower = prof["avg_interval"] - k * std_i
    upper = prof["avg_interval"] + k * std_i
    churn_thr = np.maximum(churn_days, churn_mult * prof["avg_interval"].fillna(0))
    ds = prof["days_since_last"]
    # Sắp đến hạn: lower <= ds <= upper (tính cả ngày cuối của cửa sổ)
    # Quá hạn    : ds > upper
    status = np.select(
        [ds >= churn_thr, ~enough, ~t_reg, ds > upper, ds >= lower],
        ["Đã ngừng mua", "Chưa đủ dữ liệu", "Khó đoán thời điểm", "Quá hạn", "Sắp đến hạn"],
        "Chưa đến hạn")
    prof["status"] = pd.Categorical(status, categories=STATUS_ORDER, ordered=True)
    prof["due_lower"], prof["due_upper"] = lower, upper

    # Cửa sổ đến hạn tính bằng số ngày nguyên, khớp đúng với cách phân trạng thái ở trên
    # (ds là số nguyên nên lower <= ds <= upper  <=>  ceil(lower) <= ds <= floor(upper)).
    prof["due_from_days"] = np.ceil(lower).clip(lower=0)
    prof["due_to_days"] = np.floor(upper)
    prof["due_from_date"] = prof["last_date"] + pd.to_timedelta(prof["due_from_days"], unit="D")
    prof["due_to_date"] = prof["last_date"] + pd.to_timedelta(prof["due_to_days"], unit="D")
    # Số ngày: dương = còn bao lâu (đến lúc vào cửa sổ / đến hết cửa sổ), âm = đã trễ bao lâu
    prof["days_left"] = np.select(
        [prof["status"] == "Chưa đến hạn", prof["status"] == "Sắp đến hạn",
         prof["status"] == "Quá hạn"],
        [prof["due_from_days"] - ds, prof["due_to_days"] - ds, prof["due_to_days"] - ds], np.nan)
    prof["cycle_progress"] = _safe_div(ds, prof["avg_interval"]) * 100

    # Ngày dự kiến và cửa sổ chỉ có nghĩa khi khách còn mua VÀ mua đều về thời gian.
    # Với khách đã ngừng mua, khó đoán thời điểm hoặc chưa đủ dữ liệu -> để trống.
    predictable = prof["status"].isin(["Chưa đến hạn", "Sắp đến hạn", "Quá hạn"])
    prof.loc[~predictable, ["expected_next", "days_to_due", "due_from_days", "due_to_days",
                            "due_from_date", "due_to_date", "days_left"]] = np.nan

    # --- xếp hạng ABC (Pareto) ---
    val = prof["total_amount"] if prof["total_amount"].notna().any() else prof["total_qty"]
    prof["_val"] = val
    prof = prof.sort_values("_val", ascending=False).reset_index(drop=True)
    share = prof["_val"] / prof["_val"].sum() * 100
    prof["share_pct"] = share
    cum = share.cumsum()
    prof["abc"] = np.select([cum - share < 80, cum - share < 95], ["A", "B"], "C")
    prof = prof.drop(columns=["_val"])

    # --- khóa hiển thị ---
    if level == "customer":
        prof["key"] = prof["customer"]
        orders["key"] = orders["customer"]
    else:
        prof["key"] = prof["customer"] + " | " + prof["product"]
        orders["key"] = orders["customer"] + " | " + orders["product"]

    return prof, orders


# ------------------------------------------------------------------
# 5. Lịch sử theo tháng
# ------------------------------------------------------------------
def monthly_matrix(orders, value="qty", start=None, end=None):
    """Ma trận key × tháng; tháng không mua = 0 (không bị bỏ trống)."""
    start = start if start is not None else orders["date"].min()
    end = end if end is not None else orders["date"].max()
    months = pd.period_range(pd.Timestamp(start).to_period("M"),
                             pd.Timestamp(end).to_period("M"), freq="M")
    if value == "n_orders":
        m = orders.groupby(["key", "month"]).size().unstack(fill_value=0)
    else:
        m = orders.groupby(["key", "month"])[value].sum().unstack(fill_value=0)
    m = m.reindex(columns=months, fill_value=0)
    m.columns = [str(c) for c in m.columns]
    return m


def period_matrix(orders, value="qty", start=None, end=None, freq="M"):
    """
    Ma trận key × kỳ; kỳ không mua = 0.  freq: 'M' tháng, 'Q' quý, 'Y' năm.
    Trả về DataFrame với MultiIndex nếu có cột paper_type (drilldown).
    """
    start = start if start is not None else orders["date"].min()
    end   = end   if end   is not None else orders["date"].max()
    freq_map = {"M": "M", "Q": "Q", "Y": "Y"}
    pf = freq_map.get(freq, "M")
    periods = pd.period_range(pd.Timestamp(start).to_period(pf),
                              pd.Timestamp(end).to_period(pf), freq=pf)
    grp_cols = ["key"]
    if "paper_type" in orders.columns:
        grp_cols = ["key", "paper_type"]
    if value == "n_orders":
        m = orders.groupby(grp_cols + ["period"]).size() if "period" in orders.columns \
            else orders.assign(period=orders["date"].dt.to_period(pf)) \
                       .groupby(grp_cols + ["period"]).size()
    else:
        if "period" not in orders.columns:
            orders = orders.assign(period=orders["date"].dt.to_period(pf))
        m = orders.groupby(grp_cols + ["period"])[value].sum()
    m = m.unstack(fill_value=0)
    m = m.reindex(columns=periods, fill_value=0)
    m.columns = [str(c) for c in m.columns]
    return m


def compute_period_growth(mat, freq):
    """
    Tính % thay đổi theo kỳ trước liền kề (MoM, QoQ, YoY tuỳ freq).
    Trả về DataFrame cùng shape với NaN cho kỳ đầu tiên không có so sánh.
    freq: 'M' -> MoM, 'Q' -> QoQ, 'Y' -> YoY.
    """
    # shift 1 kỳ (cột = kỳ theo thứ tự)
    prev = mat.shift(1, axis=1)
    growth = ((mat - prev) / prev.replace(0, np.nan)) * 100
    return growth


# ------------------------------------------------------------------
# 6. Diễn giải bằng lời
# ------------------------------------------------------------------
def fmt_num(x, d=0):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    s = f"{x:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def due_evidence(r, short=False):
    """
    Câu giải thích vì sao khách được xếp Chưa đến hạn / Sắp đến hạn / Quá hạn.
    short=True: bản ngắn để vừa một ô trong bảng.
    """
    ds, lo, hi = r["days_since_last"], r["due_from_days"], r["due_to_days"]
    if pd.isna(lo) or pd.isna(hi):
        return ""
    if short:
        rng_ = f"{fmt_num(lo)}–{fmt_num(hi)} ngày" if hi >= lo else f"~{fmt_num(r['avg_interval'])} ngày"
        return {"Chưa đến hạn": f"{fmt_num(ds)} ngày, thường {rng_} → còn {fmt_num(lo - ds)} ngày",
                "Sắp đến hạn": f"{fmt_num(ds)} ngày, trong khoảng {rng_} → còn {fmt_num(hi - ds)} ngày",
                "Quá hạn": f"{fmt_num(ds)} ngày, vượt {rng_} → trễ {fmt_num(ds - hi)} ngày",
                }.get(r["status"], "")
    win = (f"khoảng {fmt_num(lo)} đến {fmt_num(hi)} ngày" if hi >= lo
           else f"khoảng quanh {fmt_num(r['avg_interval'])} ngày")
    if r["status"] == "Chưa đến hạn":
        return (f"Mới {fmt_num(ds)} ngày từ lần mua cuối. Khách thường mua lại sau {win}, "
                f"nên còn {fmt_num(lo - ds)} ngày nữa mới đến hạn.")
    if r["status"] == "Sắp đến hạn":
        return (f"Đã {fmt_num(ds)} ngày từ lần mua cuối, nằm trong {win} mà khách thường mua lại. "
                f"Còn {fmt_num(hi - ds)} ngày là hết khoảng này.")
    return (f"Đã {fmt_num(ds)} ngày từ lần mua cuối, vượt {win} mà khách thường mua lại. "
            f"Đã trễ {fmt_num(ds - hi)} ngày (bằng {fmt_num(ds / r['avg_interval'], 1)} lần "
            f"chu kỳ trung bình).")


def describe_profile(r, min_orders, timing_cv, qty_cv, vol_unit="sản phẩm"):
    """Tóm tắt bằng lời thường cho 1 dòng hồ sơ."""
    lines = []
    n = int(r["n_orders"])
    if n < min_orders:
        lines.append(f"Mới có {n} lần mua, chưa đủ {min_orders} lần để đánh giá nhịp mua "
                     "một cách đáng tin cậy.")
    else:
        lo = max(r["avg_interval"] - r["std_interval"], 0)
        hi = r["avg_interval"] + r["std_interval"]
        t_word = "khá đều" if r["interval_cv"] < timing_cv else "không đều"
        lines.append(f"Trung bình **{fmt_num(r['avg_interval'])} ngày** mua một lần, "
                     f"thường trong khoảng {fmt_num(lo)} đến {fmt_num(hi)} ngày "
                     f"(CV thời gian {fmt_num(r['interval_cv'], 2)}, tức là {t_word}).")
        q_word = "ổn định" if r["qty_cv"] < qty_cv else "dao động nhiều"
        lines.append(f"Mỗi lần mua trung bình **{fmt_num(r['avg_vol'])} {vol_unit}**, "
                     f"nhỏ nhất {fmt_num(r['min_vol'])}, lớn nhất {fmt_num(r['max_vol'])} "
                     f"(CV khối lượng {fmt_num(r['qty_cv'], 2)}, tức là {q_word}).")
        if r["dow_p"] < 0.05:
            lines.append(f"Có thói quen đặt vào **{r['dominant_dow']}** "
                         f"({fmt_num(r['dow_share'])}% số lần mua, trong khi mức chung của mọi "
                         f"khách là {fmt_num(r['dow_base_share'])}%).")
        if r["dom_p"] < 0.05:
            lines.append(f"Các lần mua tập trung quanh **ngày {int(r['dom_center'])}** hằng tháng.")
        if r["trend"] == "Đang thưa dần":
            lines.append(f"Khoảng cách giữa các lần mua đang **giãn ra** (tăng khoảng "
                         f"{fmt_num(r['trend_pct'])}% so với chu kỳ trung bình). Cần theo dõi.")
        elif r["trend"] == "Đang dày lên":
            lines.append(f"Khoảng cách giữa các lần mua đang **ngắn lại** (giảm khoảng "
                         f"{fmt_num(abs(r['trend_pct']))}% so với chu kỳ trung bình).")

    st = r["status"]
    tail = f"Lần mua gần nhất cách đây {fmt_num(r['days_since_last'])} ngày"
    if st == "Đã ngừng mua":
        lines.append(f"{tail}, lâu hơn nhiều so với nhịp thường lệ. Nhiều khả năng đã ngừng mua.")
    elif st in ("Chưa đến hạn", "Sắp đến hạn", "Quá hạn"):
        lines.append(due_evidence(r) + " " + {
            "Quá hạn": "Nên liên hệ hỏi nhu cầu.",
            "Sắp đến hạn": "Nên chuẩn bị nguyên liệu.",
            "Chưa đến hạn": f"Dự kiến lần tới khoảng {r['expected_next']:%d/%m/%Y}.",
        }[st])
    elif st == "Khó đoán thời điểm":
        lines.append(f"{tail}. Nhịp mua không đều nên không dự đoán được ngày đặt tiếp theo.")
    return lines


# ------------------------------------------------------------------
# 7. Dữ liệu mẫu để chạy thử
# ------------------------------------------------------------------
def make_sample_data(seed=7):
    rng = np.random.default_rng(seed)
    start, end = pd.Timestamp("2023-01-02"), pd.Timestamp("2026-06-30")
    units = {"HOP CARTON 3 LOP": "cái", "HOP CARTON 5 LOP": "cái", "TUI GIAY KRAFT": "cái",
             "NHAN DECAL": "tờ", "HOP QUA COUCHE": "hộp", "THUNG GIAY LON": "thùng"}
    prices = {"HOP CARTON 3 LOP": 4200, "HOP CARTON 5 LOP": 6800, "TUI GIAY KRAFT": 1500,
              "NHAN DECAL": 350, "HOP QUA COUCHE": 12500, "THUNG GIAY LON": 21000}
    # (khách, sản phẩm, kiểu, chu kỳ ngày, SL gốc, ngày dừng)
    profiles = [
        ("CTY AN PHAT", "HOP CARTON 3 LOP", "fixed", 30, 1200, None),
        ("CTY AN PHAT", "NHAN DECAL", "fixed", 30, 5000, None),
        ("CTY BINH MINH", "HOP CARTON 5 LOP", "timing", 14, 800, None),
        ("CTY BINH MINH", "THUNG GIAY LON", "timing", 28, 150, None),
        ("CTY CAT TUONG", "TUI GIAY KRAFT", "qty", 45, 3000, None),
        ("CTY DAI VIET", "HOP QUA COUCHE", "irregular", 40, 600, None),
        ("CTY DONG A", "HOP CARTON 3 LOP", "fixed", 21, 2000, "2025-03-15"),
        ("CTY HOANG LONG", "NHAN DECAL", "slowing", 20, 8000, None),
        ("CTY HOANG LONG", "TUI GIAY KRAFT", "irregular", 25, 1000, None),
        ("CTY MINH KHANG", "HOP QUA COUCHE", "timing", 60, 1500, None),
        ("CTY PHUC THINH", "THUNG GIAY LON", "fixed", 7, 60, None),
        ("CTY SAO VIET", "HOP CARTON 5 LOP", "qty", 20, 500, None),
        ("CTY THANH CONG", "HOP CARTON 3 LOP", "irregular", 15, 900, None),
        ("CTY THANH CONG", "HOP CARTON 5 LOP", "irregular", 35, 400, None),
        ("CTY VAN XUAN", "TUI GIAY KRAFT", "fixed", 30, 2500, None),
        ("KH LE NGOC", "NHAN DECAL", "rare", 200, 1000, None),
        ("KH TRAN HUNG", "TUI GIAY KRAFT", "rare", 150, 300, None),
    ]
    rows = []
    for cust, prod, kind, interval, qty, stop in profiles:
        stop_d = pd.Timestamp(stop) if stop else end
        d = start + pd.Timedelta(days=int(rng.integers(0, interval)))
        step = 0
        while d <= stop_d:
            if kind == "fixed":
                q, gap = qty * rng.normal(1, 0.08), interval * rng.normal(1, 0.08)
            elif kind == "timing":
                q, gap = qty * rng.lognormal(0, 0.7), interval * rng.normal(1, 0.1)
            elif kind == "qty":
                q, gap = qty * rng.normal(1, 0.1), interval * rng.exponential(1)
            elif kind == "slowing":
                q, gap = qty * rng.normal(1, 0.1), interval * (1 + 0.06 * step) * rng.normal(1, 0.1)
            else:
                q, gap = qty * rng.lognormal(0, 0.8), interval * rng.exponential(1)
            if kind in ("fixed", "timing", "slowing") and d.dayofweek >= 5:
                d -= pd.Timedelta(days=d.dayofweek - 4)   # dời về thứ 6
            q = max(1, round(q))
            p = prices[prod]
            # chia 1 đơn thành 2 dòng đôi khi (giống dữ liệu xuất kho thật)
            if rng.random() < 0.2 and q > 2:
                q1 = int(q * 0.6)
                rows += [(d, cust, prod, units[prod], q1, p, q1 * p),
                         (d, cust, prod, units[prod], q - q1, p, (q - q1) * p)]
            else:
                rows.append((d, cust, prod, units[prod], q, p, q * p))
            r = rng.random()
            if r < 0.04:                                   # trả 1 phần hàng
                rq = -max(1, round(q * 0.1))
                rows.append((d + pd.Timedelta(days=int(rng.integers(3, 20))), cust, prod,
                             units[prod], rq, p, rq * p))
            elif r < 0.07:                                 # hủy đơn rồi xuất lại
                d_cancel = d + pd.Timedelta(days=int(rng.integers(0, 3)))
                rows.append((d_cancel, cust, prod, units[prod], -q, p, -q * p))
                rows.append((d_cancel + pd.Timedelta(days=int(rng.integers(1, 6))), cust, prod,
                             units[prod], q, p, q * p))
            elif r < 0.09:                                 # điều chỉnh giảm giá
                adj = -round(p * 0.05)
                rows.append((d + pd.Timedelta(days=int(rng.integers(1, 10))), cust, prod,
                             units[prod], q, adj, q * adj))
            d += pd.Timedelta(days=max(1, int(round(gap))))
            step += 1
    cols = ["date", "customer", "product", "unit", "quantity", "unit_price", "amount"]
    out = pd.DataFrame(rows, columns=cols)
    out = out[out["date"] <= end].sort_values("date", kind="stable").reset_index(drop=True)

    # Sinh category và ingredient tương ứng với sản phẩm
    _cat = {
        "HOP CARTON 3 LOP": "hộp carton",
        "HOP CARTON 5 LOP": "hộp carton",
        "TUI GIAY KRAFT":   "bao bì giấy",
        "NHAN DECAL":        "nhãn mác",
        "HOP QUA COUCHE":   "bao bì giấy",
        "THUNG GIAY LON":   "hộp carton",
    }
    _ing = {
        "HOP CARTON 3 LOP": "SONG E 3 LOP",
        "HOP CARTON 5 LOP": "SONG B 5 LOP",
        "TUI GIAY KRAFT":   "GIAY KRAFT 90G",
        "NHAN DECAL":        "GIAY DECAL TRANG",
        "HOP QUA COUCHE":   "GIAY COUCHE 300G",
        "THUNG GIAY LON":   "TAM SONG E",
    }
    out["category"]   = out["product"].map(_cat)
    out["ingredient"] = out["product"].map(_ing)

    # số hợp đồng: mỗi khách 1 hợp đồng/quý, dùng chung cho mọi sản phẩm của khách đó
    cust_code = {c: i + 1 for i, c in enumerate(sorted(out["customer"].unique()))}
    out["contract_number"] = [f"HD{d.year % 100:02d}Q{(d.month - 1) // 3 + 1}-{cust_code[c]:03d}"
                              for d, c in zip(out["date"], out["customer"])]
    out["date"] = out["date"].dt.strftime("%m/%d/%Y").astype(object)   # giống file thật: mm/dd/yyyy
    out = out.astype({"customer": object, "product": object, "unit_price": object,
                      "quantity": object, "contract_number": object})

    # ---- cài sẵn vài lỗi dữ liệu thường gặp để minh họa bước làm sạch ----
    idx = rng.permutation(out.index[out["quantity"].astype(float) > 0])
    take = iter(np.array_split(idx[:60], 10))
    for i in next(take)[:4]:
        out.loc[i, "customer"] = None                        # thiếu khách -> bổ sung theo HĐ
    for i in next(take)[:5]:
        out.loc[i, "product"] = None                         # thiếu SP -> bổ sung theo HĐ (+ đơn giá)
    for i in next(take)[:4]:
        out.loc[i, "unit_price"] = None                      # thiếu đơn giá -> tính từ thành tiền
    for i in next(take)[:2]:
        out.loc[i, "quantity"] = None                        # thiếu SL -> tính từ thành tiền
    for i in next(take)[:3]:
        out.loc[i, "contract_number"] = None                 # thiếu số HĐ -> bị loại
    for i in next(take)[:2]:
        out.loc[i, "date"] = "13/45/2024"                    # ngày sai -> bị loại
    for i in next(take)[:2]:
        out.loc[i, "quantity"] = 0                           # SL = 0 -> bị loại
    for i in next(take)[:3]:
        out.loc[i, "customer"] = "  " + str(out.loc[i, "customer"]).replace(" ", "  ") + " "
    for i in next(take)[:2]:                                 # thiếu cả SP lẫn đơn giá, thành tiền
        out.loc[i, ["product", "unit_price", "amount"]] = [None, None, None]
    dups = out.loc[next(take)[:5]]                           # xuất trùng dòng
    out = pd.concat([out, dups]).sort_index(kind="stable").reset_index(drop=True)
    return out
