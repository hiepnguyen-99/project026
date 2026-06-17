import json

from pgvector.sqlalchemy import Vector
from sqlalchemy.types import TEXT, TypeDecorator


class VectorType(TypeDecorator):
    """Vector trên PostgreSQL (pgvector); fallback TEXT(JSON) trên SQLite để test offline."""

    impl = TEXT
    cache_ok = True

    def __init__(self, dim: int):
        self.dim = dim
        super().__init__()

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(TEXT())

    def process_bind_param(self, value, dialect):
        if value is None or dialect.name == "postgresql":
            return value
        return json.dumps(list(value))

    def process_result_value(self, value, dialect):
        if value is None or dialect.name == "postgresql":
            return value
        return json.loads(value)
