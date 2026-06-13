# EduVault Production Database

- `mysql_8_4_production_schema.sql`: schema đích dành cho triển khai thực tế.
- `PRODUCTION_DATABASE_ARCHITECTURE.md`: ERD, quyết định kiến trúc, index,
  partition, retention, compliance và kế hoạch migration.

Không chạy schema production trực tiếp lên database MVP đang hoạt động. Thực
hiện migration theo các giai đoạn trong tài liệu kiến trúc, gồm shadow schema,
backfill, dual-write, kiểm tra đối soát và cutover.

DDL mặc định tạo shadow schema `eduvault_v2` để không đụng vào database MVP
`eduvault`. Sau cutover, ứng dụng có thể trỏ trực tiếp tới `eduvault_v2` hoặc
DBA đổi tên theo quy ước triển khai của đơn vị.

Đây là DDL bootstrap một lần trên schema trống, không phải migration idempotent.
Các thay đổi tiếp theo phải đi qua Flyway, Alembic hoặc Liquibase với version
và checksum rõ ràng.
