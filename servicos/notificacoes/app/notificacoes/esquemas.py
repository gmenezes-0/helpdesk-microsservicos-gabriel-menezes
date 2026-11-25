from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificacaoSaida(BaseModel):
    """Mesmos campos que o monólito devolvia em GET /notificacoes."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo: str
    destinatario_id: int
    mensagem: str
    criada_em: datetime
