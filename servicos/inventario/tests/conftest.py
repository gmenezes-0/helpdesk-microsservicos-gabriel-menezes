import os

# Antes de importar o app: banco em memória (nada gravado em disco) e segredo fixo de teste
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SEGREDO"] = "segredo-de-teste-do-servico-de-inventario-0123456789"
os.environ.pop("JWT_SEGREDO_ARQUIVO", None)
os.environ["DADOS_EXEMPLO"] = "0"

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
    """Token no mesmo formato que o serviço de Usuários emite (auth/tokens.py: criar).

    `sem` lista claims a retirar; `mudancas` troca o valor de outras (para os testes de token inválido).
    """
    agora = datetime.now(timezone.utc)
    dados = {"sub": str(usuario_id), "perfil": perfil, "iat": agora,
             "exp": agora + timedelta(minutes=60), "iss": config.JWT_EMISSOR, **mudancas}
    for claim in sem:
        dados.pop(claim)
    return jwt.encode(dados, segredo or config.JWT_SEGREDO, algorithm="HS256")


def cabecalho(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sessao(monkeypatch):
    """Banco novo, em memória, para cada teste."""
    monkeypatch.setenv("DADOS_EXEMPLO", "0")
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
    """Cabeçalho de login de cada perfil (os ids são os dos dados de exemplo de Usuários)."""
    return {
        "admin": {"headers": cabecalho(gerar_token(1, "admin")), "id": 1},
        "ana": {"headers": cabecalho(gerar_token(2, "solicitante")), "id": 2},
        "carla": {"headers": cabecalho(gerar_token(4, "tecnico")), "id": 4},
    }


@pytest.fixture
def ativo(cliente, contas):
    return cliente.post("/ativos", headers=contas["carla"]["headers"],
                        json={"patrimonio": "PAT-1", "tipo": "computador", "descricao": "Desktop", "setor": "TI"}).json()
