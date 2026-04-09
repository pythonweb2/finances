import datetime as dt
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False, unique=True)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(nullable=False)
    payee: Mapped[str | None]
    amount: Mapped[Decimal] = mapped_column(nullable=False)
    category: Mapped[str | None]
    tags: Mapped[str | None]
    notes: Mapped[str | None]
    check_no: Mapped[str | None]
    transaction_id: Mapped[str] = mapped_column(nullable=False, unique=True)
    account_id: Mapped[int] = mapped_column(
        sa.ForeignKey("accounts.id"), nullable=False
    )

    account: Mapped["Account"] = relationship(back_populates="transactions")


# Database setup
DB_DIR = Path.home() / ".finances"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = DB_DIR / "transactions.db"

engine = sa.create_engine(f"sqlite:///{DB_FILE}")
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)
