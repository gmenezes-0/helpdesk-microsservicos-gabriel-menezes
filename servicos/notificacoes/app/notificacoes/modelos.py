from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Notificacao(Base):
    __tablename__ = "notificacoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Id do evento que gerou o aviso: único, para que um evento reentregue não vire dois avisos
    evento_id: Mapped[str] = mapped_column(String(36), unique=True)
    tipo: Mapped[str] = mapped_column(String(40))
    destinatario_id: Mapped[int] = mapped_column(index=True)
    mensagem: Mapped[str] = mapped_column(String(300))
    criada_em: Mapped[datetime] = mapped_column(DateTime)    # quando o fato aconteceu (no Chamados)
    recebida_em: Mapped[datetime] = mapped_column(DateTime)  # quando o evento chegou aqui
