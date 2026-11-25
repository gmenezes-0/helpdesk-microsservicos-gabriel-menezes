"""Porta pública do módulo de eventos: registrar um fato e consultar a caixa de saída."""
import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.eventos.modelos import EventoSaida

# Tipo do evento → routing key na exchange helpdesk.eventos
CHAVES = {
    "ChamadoAberto": "chamado.aberto",
    "ChamadoAtribuido": "chamado.atribuido",
    "ChamadoResolvido": "chamado.resolvido",
}
VERSAO = 1


def novo_id() -> str:
    return str(uuid.uuid4())


def registrar(db: Session, tipo: str, dados: dict) -> EventoSaida:
    """Adiciona o evento à sessão, SEM commit: ele vai junto com o commit do chamado.

    `dados` só leva ids e datas (nada de token, e-mail ou texto do chamado).
    """
    agora = datetime.now()
    evento_id = novo_id()
    mensagem = {"id": evento_id, "tipo": tipo, "versao": VERSAO, "ocorrido_em": agora.isoformat(), "dados": dados}
    evento = EventoSaida(evento_id=evento_id, tipo=tipo, chave=CHAVES[tipo],
                         conteudo=json.dumps(mensagem, separators=(",", ":")), criado_em=agora)
    db.add(evento)
    return evento


def pendentes(db: Session, limite: int = 50) -> list[EventoSaida]:
    consulta = (select(EventoSaida).where(EventoSaida.publicado_em.is_(None))
                .order_by(EventoSaida.id).limit(limite))
    return list(db.scalars(consulta))


def listar(db: Session) -> list[EventoSaida]:
    return list(db.scalars(select(EventoSaida).order_by(EventoSaida.id)))
