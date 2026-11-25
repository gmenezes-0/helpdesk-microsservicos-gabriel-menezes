"""Contrato dos eventos (versão 1).

Formato, igual para os três tipos:
    {"id": "<uuid>", "tipo": "ChamadoAberto", "versao": 1, "ocorrido_em": "<data ISO>",
     "dados": {"chamado_id": 7, "destinatario_id": 2, "prazo_sla": "<data ISO>"}}

A validação é rígida (modo strict do pydantic): campos a mais, campos faltando, tipos
convertidos ("7" no lugar de 7), tipo de evento desconhecido ou outra versão são recusados.
O evento só leva ids e datas: nada de token, e-mail ou texto livre.
"""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, TypeAdapter, ValidationError

from app.config import TAMANHO_MAXIMO_MENSAGEM


def _sem_fuso(valor: datetime) -> datetime:
    # As datas do sistema são locais e sem fuso (como no monólito); com fuso, converte
    return valor.astimezone().replace(tzinfo=None) if valor.tzinfo else valor


Id = Annotated[StrictInt, Field(gt=0, le=2**31 - 1)]
DataHora = Annotated[datetime, AfterValidator(_sem_fuso)]


class _Rigido(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DadosAberto(_Rigido):
    chamado_id: Id
    destinatario_id: Id  # o solicitante
    prazo_sla: DataHora


class DadosDoChamado(_Rigido):
    chamado_id: Id
    destinatario_id: Id  # o técnico (atribuído) ou o solicitante (resolvido)


class _Envelope(_Rigido):
    id: UUID
    versao: Annotated[StrictInt, Field(ge=1, le=1)]  # StrictInt: Literal[1] aceitaria true (True == 1)
    ocorrido_em: DataHora


class ChamadoAberto(_Envelope):
    tipo: Literal["ChamadoAberto"]
    dados: DadosAberto


class ChamadoAtribuido(_Envelope):
    tipo: Literal["ChamadoAtribuido"]
    dados: DadosDoChamado


class ChamadoResolvido(_Envelope):
    tipo: Literal["ChamadoResolvido"]
    dados: DadosDoChamado


Evento = Annotated[ChamadoAberto | ChamadoAtribuido | ChamadoResolvido, Field(discriminator="tipo")]
_adaptador = TypeAdapter(Evento)


class EventoInvalido(Exception):
    """A mensagem não segue o contrato. O motivo é curto e nunca inclui o conteúdo da mensagem."""


def ler(corpo: bytes) -> Evento:
    if not isinstance(corpo, bytes) or len(corpo) > TAMANHO_MAXIMO_MENSAGEM:
        raise EventoInvalido("tamanho")
    try:
        return _adaptador.validate_json(corpo, strict=True)
    except ValidationError:
        # from None: o erro do pydantic repete trechos da mensagem, e eles não devem ir para o log
        raise EventoInvalido("contrato") from None
