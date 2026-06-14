# EduVault V2 Demo

## Chạy nhanh với fallback cục bộ

```powershell
pip install -r requirements.txt
cd frontend
npm install
cd ..
.\run_v2_demo.ps1
```

Mở `http://127.0.0.1:3000`. Các tài khoản demo là `GV001`, `GVNEW`, `TBM01`,
`ADMIN`; mật khẩu giống mã tài khoản.

## Chạy đầy đủ hạ tầng V2

```powershell
docker compose -f docker-compose.v2.yml up -d
```

Cập nhật `.env`:

```text
DATABASE_PROVIDER=mysql
MINIO_ENABLED=true
REDIS_ENABLED=true
QDRANT_ENABLED=true
```

Sau đó chạy lại `.\run_v2_demo.ps1`.

Nếu Docker/MySQL chưa chạy, backend tự dùng `sqlite-fallback` để demo vẫn khởi
động được. Dashboard hiển thị provider đang thực sự được sử dụng.

Các dịch vụ:

- Frontend: `http://127.0.0.1:3000`
- API docs: `http://127.0.0.1:8080/docs`
- MinIO console: `http://127.0.0.1:9001`
- Qdrant dashboard: `http://127.0.0.1:6333/dashboard`

Endpoint `/api/v2/status` hiển thị dịch vụ đang dùng hạ tầng thật hay fallback.

## Luồng demo đề xuất

1. Đăng nhập `GV001`, upload một file và xem metadata/folder được đề xuất.
2. Mở dashboard để xem object storage, vector store và queue của V2.
3. Tạo tài liệu Private và đăng nhập actor khác để gửi yêu cầu truy cập.
4. Đăng nhập chủ sở hữu để phê duyệt rồi kiểm tra tải file.
5. Đăng nhập `TBM01` để xem chuyển giao, chất lượng kho và báo cáo.
6. Đăng nhập `ADMIN` để xem policy, audit, backup và trạng thái hạ tầng.
