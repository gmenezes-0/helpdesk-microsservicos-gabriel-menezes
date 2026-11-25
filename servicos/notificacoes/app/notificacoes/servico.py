"""Regras do módulo de notificações. É a porta pública do módulo."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.eventos.esquemas import Evento
from app.notificacoes.modelos import Notificacao


def redigir(evento: Evento) -> str:
    """Texto do aviso: o mesmo que o monólito gravava para cada fato."""
    dados = evento.dados
    if evento.tipo == "ChamadoAberto":
        return f"Seu chamado #{dados.chamado_id} foi aberto. Prazo: {dados.prazo_sla:%d/%m %H:%M}."
    if evento.tipo == "ChamadoAtribuido":
        return f"O chamado #{dados.chamado_id} foi atribuído a você."
    return f"Seu chamado #{dados.chamado_id} foi resolvido. Confirme se está tudo certo."


def registrar(db: Session, evento: Evento) -> bool:
    """Grava o aviso do evento. Devolve False se o evento já tinha sido processado (duplicado)."""
    db.add(Notificacao(
        evento_id=str(evento.id), tipo=evento.tipo, destinatario_id=evento.dados.destinatario_id,
        mensagem=redigir(evento), criada_em=evento.ocorrido_em, recebida_em=datetime.now(),
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.scalar(select(Notificacao.id).where(Notificacao.evento_id == str(evento.id))) is not None:
            return False  # já existia: a mensagem foi reentregue
        raise
    return True


def listar(db: Session, destinatario_id: int) -> list[Notificacao]:
    # Por data do fato: com reentregas, os eventos podem chegar fora de ordem
    consulta = (select(Notificacao).where(Notificacao.destinatario_id == destinatario_id)
                .order_by(Notificacao.criada_em, Notificacao.id))
    return list(db.scalars(consulta))
