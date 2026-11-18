import getpass
from sqlalchemy import select
from src.db.session import SessionLocal, engine
from src.db.base import Base
import src.db.models
from src.db.models import User
from src.core.security import hash_password

def main():
    Base.metadata.create_all(bind=engine)  # new DB only; migrate existing DB first
    username = input("Admin username: ").strip()
    password = getpass.getpass("Admin password (min 10 characters): ")
    if len(password) < 10:
        raise SystemExit("Password must be at least 10 characters")
    with SessionLocal.begin() as db:
        if db.scalar(select(User.id).where(User.username == username)) is not None:
            raise SystemExit("Username already exists")
        db.add(User(username=username, password_hash=hash_password(password), is_superuser=True, is_active=True))
    print("Superuser created")

if __name__ == "__main__":
    main()