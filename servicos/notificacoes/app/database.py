"""Conexão com o banco do serviço de Notificações (banco próprio, sem acesso de outros serviços)."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 10} if DATABASE_URL.startswith("sqlite") else {},
)


@event.listens_for(engine, "connect")
def _ajustar_sqlite(conexao, _):
    # A API lê enquanto o consumidor grava: WAL evita que um bloqueie o outro
    if DATABASE_URL.startswith("sqlite") and DATABASE_URL not in ("sqlite://", "sqlite:///:memory:"):
        cursor = conexao.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """Abre uma sessão por requisição e fecha no final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
