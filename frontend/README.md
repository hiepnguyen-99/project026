# EduVault Enterprise Frontend

Frontend Next.js 15 cho AI Knowledge Repository System, đã kết nối với backend
FastAPI hiện có.

## Chạy cục bộ

Chạy backend trong cửa sổ PowerShell thứ nhất:

```powershell
cd C:\Users\Admin\C2-App-012\he_thong_kho_luu_tru_tri_thuc
python run_mvp.py
```

Chạy frontend trong cửa sổ PowerShell thứ hai:

```powershell
cd C:\Users\Admin\C2-App-012\he_thong_kho_luu_tru_tri_thuc\frontend
npm install
npm run dev
```

Mở `http://localhost:3000`. Frontend mặc định gọi backend tại
`http://127.0.0.1:8080`.

Trình duyệt mặc định gọi API cùng origin qua `/api`; Next.js proxy request tới
`BACKEND_URL`. Sao chép `.env.example` thành `.env.local` khi cần đổi địa chỉ
backend. Chỉ đặt `NEXT_PUBLIC_API_URL` khi trình duyệt phải gọi trực tiếp một
API public trên domain riêng.

Tài khoản demo: `GV001`, `GVNEW`, `TBM01`, `ADMIN`. Mật khẩu mặc định giống mã
tài khoản.

## Kiểm tra production

```powershell
npm run build
npm start
```

Production build sử dụng Next.js standalone output để thuận tiện đóng gói
frontend vào container.

Các route chính: `/`, `/repository`, `/assistant`, `/knowledge-transfer`,
`/versions`, `/backup`, `/permissions`, `/reports`, `/settings` và
`/documents/[id]`.

Các luồng đã kết nối: đăng nhập, dashboard, repository/upload, AI analyze,
RAG search, document provenance/download, version/rollback, chuyển giao,
permissions, backup, reports và policies.
