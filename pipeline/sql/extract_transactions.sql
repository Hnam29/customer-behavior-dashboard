/* =====================================================================
   CÂU SQL TRÍCH XUẤT GIAO DỊCH
   Dán câu SQL của bạn vào đây (thay cho phần ví dụ bên dưới), với 2 yêu cầu:

   1) ĐẶT TÊN CỘT KẾT QUẢ đúng như sau (dùng AS):
        [date]            ngày giao dịch                 (bắt buộc)
        customer          tên hoặc mã khách hàng         (bắt buộc)
        product           tên hoặc mã sản phẩm           (bắt buộc)
        category          nhóm sản phẩm chính            (bắt buộc - xem CASE bên dưới)
        quantity          số lượng                       (bắt buộc)
        unit              đơn vị tính                    (nên có)
        unit_price        đơn giá                        (nên có)
        amount            thành tiền                     (nên có)
        contract_number   số hợp đồng                    (nên có)
        ingredient        tên nguyên liệu gốc            (tra cứu / lọc chi tiết)

   2) GIỮ ĐIỀU KIỆN NGÀY với đúng 2 tham số :start_date và :end_date
        WHERE <cột ngày> >= :start_date AND <cột ngày> < :end_date
      (:start_date tính cả ngày đó, :end_date KHÔNG tính ngày đó.
       Luồng dữ liệu tự điền 2 tham số này, bạn không cần sửa.)

   Cột [category] phân loại tự động từ tên thành phẩm (hoặc nguyên liệu).
   Nếu xuất hiện sản phẩm/nguyên liệu mới chưa được phân loại, giá trị sẽ là N'Khác'
   — kiểm tra tab "Làm sạch dữ liệu" trên dashboard để bổ sung từ khoá vào
   phần CASE WHEN bên dưới cho phù hợp.

   Được dùng WITH (CTE), JOIN, bảng tạm... như bình thường.
   Không cần ORDER BY. Kiểm tra bằng lệnh: python -m pipeline.check_connection
   ===================================================================== */


SELECT
    NGAYNHAP                        AS [date],
    DM_Vattu.TENVATTU               AS [ingredient],
    Dm_ThanhPham.TenThanhPham       AS [product],

    /* ----------------------------------------------------------------
       CATEGORY — nhóm sản phẩm chính (dùng làm bộ lọc trên dashboard)
       Thứ tự WHEN quan trọng: nhóm đặc thù hơn phải đứng trước.
       Bổ sung từ khoá mới vào đúng nhóm bên dưới nếu cần.
       ---------------------------------------------------------------- */
    CASE
        /* ── Thẻ cào ────────────────────────────────────────────── */
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%thẻ cào%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%the cao%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%thẻ giấy%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%the giay%'
            THEN N'thẻ cào'

        /* ── Hộp carton ─────────────────────────────────────────── */
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%hộp carton%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%hop carton%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%thùng carton%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%thung carton%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%tấm sóng%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%tam song%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%thùng bia%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%thung bia%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%sóng%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%song%'
            THEN N'hộp carton'

        /* ── Nhãn mác ────────────────────────────────────────────── */
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%quai nhựa%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%quai nhua%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%thùng nhựa%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%thung nhua%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%hộp nhựa%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%hop nhua%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%nhãn%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%nhan%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%decal%'
            THEN N'nhãn mác'

        /* ── Bao bì giấy ─────────────────────────────────────────── */
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%giấy duplex%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%giay duplex%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%giấy kraf%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%giay kraf%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%giấy kraft%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%giay kraft%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%giấy ivory%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%giay ivory%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%giấy couche%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%giay couche%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%giấy%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%giay%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%hộp%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%hop%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%thùng%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%thung%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%vỏ%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%túi%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%tui%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%khay%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%bìa%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%hg %'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%ib %'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%tút%'
            THEN N'bao bì giấy'

        /* ── Ấn phẩm (mực, màng, keo, bản kẽm, tờ in...) ─────────── */
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%mực offset%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%muc offset%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%mực%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%muc%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%bản kẽm%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%ban kem%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%màng pvc%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%mang pvc%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%màng pet%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%mang pet%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%màng mờ%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%mang mo%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%màng ép nhũ%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%mang ep nhu%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%màng%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%mang%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%keo bồi%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%keo boi%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%keo%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%tờ in%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%to in%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%ủy nhiệm thu%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%uy nhiem thu%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%thông báo cước%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%thong bao cuoc%'
            THEN N'ấn phẩm'

        /* ── Chưa phân loại ──────────────────────────────────────── */
        ELSE N'Khác'
    END                             AS [category],

    /* ----------------------------------------------------------------
       PAPER_TYPE — loại giấy nguyên liệu / thành phẩm, trích từ
       Dm_ThanhPham.TenThanhPham hoặc DM_Vattu.TENVATTU.
       Chỉ điền khi có tên loại giấy rõ ràng; còn lại để NULL.
       ---------------------------------------------------------------- */
    CASE
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%duplex%'
            THEN N'Duplex'
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%ivory%'
            THEN N'Ivory'
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%kraft%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%kraf%'
            THEN N'Kraft'
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%couche%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%couches%'
            THEN N'Couché'
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%offset%'
            THEN N'Offset'
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%decal%'
            THEN N'Decal'
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%cacbon%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%carbon%'
            THEN N'Carbon'
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%c2s%'
            THEN N'C2S'
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%c1s%'
            THEN N'C1S'
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%bristol%'
            THEN N'Bristol'
        WHEN COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%ford%'
          OR COALESCE(Dm_ThanhPham.TenThanhPham, DM_Vattu.TENVATTU) LIKE N'%fort%'
            THEN N'Ford'
        ELSE NULL
    END                             AS [paper_type],

    DM_Donvitinh.TenDonViTinh      AS [unit],
    SOLUONG                         AS [quantity],
    DONGIA                          AS [unit_price],
    ThanhTien                       AS [amount],
    Sohoadon                        AS [contract_number],
    DsKhachHang.TenKhachHang        AS [customer]

FROM NMINHNI.dbo.DSPhieuNhapXuat WITH (NOLOCK)
    LEFT JOIN NMINHNI.dbo.DM_Vattu
        ON DSPhieuNhapXuat.IDVATTU          = DM_Vattu.MAVATTU
    LEFT JOIN NMINHNI.dbo.DsKhachHang
        ON DSPhieuNhapXuat.IdDoituong       = DsKhachHang.MaKhachHang
    LEFT JOIN NMINHNI.dbo.DsKhachHang       DsKhachHang_1
        ON DSPhieuNhapXuat.IdDoituong       = DsKhachHang_1.MaKhachHang
    LEFT JOIN NMINHNI.dbo.Dm_ThanhPham
        ON DSPhieuNhapXuat.IdThanhPham      = Dm_ThanhPham.MaThanhPham
    LEFT JOIN NMINHNI.dbo.DM_TaiKhoan
        ON DSPhieuNhapXuat.IDTaiKhoanNo     = DM_TaiKhoan.MaTaiKhoan
    LEFT JOIN NMINHNI.dbo.DM_TaiKhoan      DM_TaiKhoan_1
        ON DSPhieuNhapXuat.IDTaiKhoanNo     = DM_TaiKhoan_1.MaTaiKhoan
    LEFT JOIN NMINHNI.dbo.DM_Donvitinh
        ON DSPhieuNhapXuat.IDDonvitinh      = DM_Donvitinh.MaDonViTinh

WHERE IdTaiKhoanNo IN (
        SELECT MaTaiKhoan
        FROM   NMINHNI.dbo.DM_TaiKhoan
        WHERE  MaTaiKhoanBD LIKE N'131%'
    )
  AND IdTaiKhoanCo IN (
        SELECT MaTaiKhoan
        FROM   NMINHNI.dbo.DM_TaiKhoan
        WHERE  MaTaiKhoanBD LIKE N'5112%'
    )
  AND NGAYNHAP >= :start_date
  AND NGAYNHAP <  :end_date;