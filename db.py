from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = (
    f"postgresql+psycopg2://{os.getenv('PGUSER')}:"
    f"{os.getenv('PGPASSWORD')}@{os.getenv('PGHOST')}:"
    f"{os.getenv('PGPORT')}/{os.getenv('PGDATABASE')}"
)

engine = create_engine(
    DATABASE_URL,
    sslmode="require",
    pool_pre_ping=True
)

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()