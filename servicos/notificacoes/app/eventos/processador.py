"""Transforma uma mensagem da fila em aviso no banco. Não conhece o RabbitMQ: é testável sozinho."""
from enum import Enum

from app.config import log
from app.eventos import esquemas
from app.notificacoes import servico


class Resultado(str, Enum):
    PROCESSADO = "processado"            # aviso gravado → ack
    DUPLICADO = "duplicado"              # já processado antes → ack (nada muda)
    INVALIDO = "invalido"                # fora do contrato → reject sem requeue (vai para a DLQ)
    FALHA_TEMPORARIA = "falha_temporaria"  # banco indisponível etc. → reject com requeue (conta no delivery-limit)


def processar(corpo: bytes, sessoes) -> Resultado:
    try:
        evento = esquemas.ler(corpo)
    except esquemas.EventoInvalido as erro:
        log.warning("Mensagem recusada (%s); %d bytes", erro, len(corpo) if isinstance(corpo, bytes) else -1)
        return Resultado.INVALIDO
    try:
        with sessoes() as db:
            novo = servico.registrar(db, evento)
    except Exception as erro:  # banco travado, disco cheio...: tenta de novo mais tarde
        log.error("Falha ao gravar o aviso do evento %s (%s)", evento.id, type(erro).__name__)
        return Resultado.FALHA_TEMPORARIA
    return Resultado.PROCESSADO if novo else Resultado.DUPLICADO
