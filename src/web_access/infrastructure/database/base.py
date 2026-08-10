"""Declarative metadata owner; v0.1 intentionally defines no tables."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
