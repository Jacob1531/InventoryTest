from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# Fallback defaults here are NOT real credentials - they only exist so this
# module can be safely imported (and its pure-logic neighbors tested)
# without the Postgres env vars set, e.g. running the test suite locally.
# In production every one of these is set for real via Azure App Service
# configuration, so this changes nothing about actual deployed behavior.
# SQLAlchemy's create_engine() is lazy about connecting but NOT lazy about
# parsing the URL - an unset PGPORT becomes the literal string "None",
# which fails at import time (before a real connection is ever attempted)
# rather than with a clear "couldn't connect" error later.
DATABASE_URL = (
    f"postgresql+psycopg2://{os.getenv('PGUSER', '')}:"
    f"{os.getenv('PGPASSWORD', '')}@{os.getenv('PGHOST', 'localhost')}:"
    f"{os.getenv('PGPORT', '5432')}/{os.getenv('PGDATABASE', '')}"
)

engine = create_engine(
    DATABASE_URL,
    connect_args={"sslmode": "require"},
    pool_pre_ping=True
)

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()