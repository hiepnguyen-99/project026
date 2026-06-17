"""Tạo 3 user mẫu cho 3 vai trò. Chạy: python scripts/seed_users.py"""
import asyncio

from sqlalchemy import select

from src.backend.app.core.security import hash_password
from src.backend.app.db.session import AsyncSessionLocal
from src.backend.app.models.user import User, UserRole

SEED_USERS = [
    ("GV001", "Nguyễn Văn A", "giangvien123", UserRole.giang_vien),
    ("TBM001", "Trần Thị B", "truongbomon123", UserRole.truong_bo_mon),
    ("QT001", "Lê Quản Trị", "quantri123", UserRole.quan_tri),
]


async def main() -> None:
    async with AsyncSessionLocal() as session:
        for code, full_name, password, role in SEED_USERS:
            existing = await session.execute(select(User).where(User.code == code))
            if existing.scalar_one_or_none():
                print(f"[seed] bỏ qua {code} (đã tồn tại)")
                continue
            session.add(
                User(
                    code=code,
                    full_name=full_name,
                    hashed_password=hash_password(password),
                    role=role,
                )
            )
            print(f"[seed] tạo {code} / {password} ({role.value})")
        await session.commit()
    print("[seed] Xong.")


if __name__ == "__main__":
    asyncio.run(main())
