import os

# Antes de importar o app: banco em memória, segredo fixo de teste e nenhum RabbitMQ
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SEGREDO"] = "segredo-de-teste-do-servico-de-notificacoes-0123456789"
os.environ.pop("JWT_SEGREDO_ARQUIVO", None)
os.environ.pop("RABBITMQ_HOST", None)

import json  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import config  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


def gerar_token(usuario_id, perfil, segredo: str | None = None, sem: tuple = (), **mudancas) -> str:
    """Token no mesmo formato que o serviço de Usuários emite."""
    agora = datetime.now(timezone.utc)
    dados = {"sub": str(usuario_id), "perfil": perfil, "iat": agora,
             "exp": agora + timedelta(minutes=60), "iss": config.JWT_EMISSOR, **mudancas}
    for claim in sem:
        dados.pop(claim)
    return jwt.encode(dados, segredo or config.JWT_SEGREDO, algorithm="HS256")


def cabecalho(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def evento(tipo="ChamadoAberto", chamado_id=7, destinatario_id=2, id=None, ocorrido_em="2026-11-25T14:03:00",
           bruto=False, **mudancas):
    """Evento no formato que o Chamados publica (versão 1). Com bruto=True, devolve o dicionário."""
    dados = {"chamado_id": chamado_id, "destinatario_id": destinatario_id}
    if tipo == "ChamadoAberto":
        dados["prazo_sla"] = "2026-11-25T22:03:00"
    mensagem = {"id": id or str(uuid.uuid4()), "tipo": tipo, "versao": 1, "ocorrido_em": ocorrido_em,
                "dados": dados, **mudancas}
    return mensagem if bruto else json.dumps(mensagem).encode()


@pytest.fixture
def sessao():
    """Banco novo, em memória, para cada teste; serve à API e ao processador."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Sessao = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def db_de_teste():
        db = Sessao()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = db_de_teste
    yield Sessao
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def cliente(sessao):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def contas():
    return {
        "ana": {"headers": cabecalho(gerar_token(2, "solicitante")), "id": 2},
        "bia": {"headers": cabecalho(gerar_token(3, "solicitante")), "id": 3},
        "carla": {"headers": cabecalho(gerar_token(4, "tecnico")), "id": 4},
        "admin": {"headers": cabecalho(gerar_token(1, "admin")), "id": 1},
    }


class CanalFalso:
    """Faz o papel do canal do Pika: registra acks e rejects. O nack é proibido neste projeto."""

    def __init__(self, ao_ack=None):
        self.acoes = []
        self._ao_ack = ao_ack

    def basic_ack(self, delivery_tag):
        if self._ao_ack:
            self._ao_ack()
        self.acoes.append(("ack", delivery_tag))

    def basic_reject(self, delivery_tag, requeue):
        self.acoes.append(("reject", delivery_tag, requeue))

    def basic_nack(self, *args, **kwargs):
        raise AssertionError("basic_nack não conta para o delivery-limit no RabbitMQ 4.4: use basic_reject")


class Metodo:
    def __init__(self, tag=1):
        self.delivery_tag = tag


class Propriedades:
    def __init__(self, message_id=None):
        self.message_id = message_id
