from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EventoSaida(Base):
    """Caixa de saída: eventos gravados junto com o chamado, à espera de publicação."""
    __tablename__ = "eventos_saida"

    id: Mapped[int] = mapped_column(primary_key=True)
    evento_id: Mapped[str] = mapped_column(String(36), unique=True)
    tipo: Mapped[str] = mapped_column(String(40))
    chave: Mapped[str] = mapped_column(String(60))       # routing key, ex.: chamado.aberto
    conteudo: Mapped[str] = mapped_column(Text)          # a mensagem JSON, pronta para publicar
    criado_em: Mapped[datetime] = mapped_column(DateTime)
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime, index=True, default=None)
    tentativas: Mapped[int] = mapped_column(default=0)
    ultimo_erro: Mapped[str | None] = mapped_column(String(80), default=None)  # só o tipo do erro
