import os

# Antes de importar o app: banco em memória (nada gravado em disco), segredo fixo de teste
# e endereços falsos dos outros serviços (as respostas são simuladas, nada sai pela rede)
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SEGREDO"] = "segredo-de-teste-do-servico-de-chamados-0123456789"
os.environ.pop("JWT_SEGREDO_ARQUIVO", None)
os.environ["DADOS_EXEMPLO"] = "0"
os.environ["USUARIOS_URL"] = "http://usuarios.teste"
os.environ["INVENTARIO_URL"] = "http://inventario.teste"

from datetime import datetime, timedelta, timezone  # noqa: E402

import httpx  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import clientes, config  # noqa: E402
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


class RedeSimulada:
    """Faz o papel dos serviços de Usuários e Inventário nos testes.

    Guarda cada requisição recebida e pode simular falhas por serviço:
    "timeout", "conexao", "500", "401" ou "json" (resposta que não é JSON).
    """

    def __init__(self):
        self.usuarios = {1: ("Admin", "admin"), 2: ("Ana", "solicitante"),
                         3: ("Bia", "solicitante"), 4: ("Carla", "tecnico")}
        self.ativos = {1: ("PAT-1", "computador", "Desktop", "TI")}
        self.falha = {"usuarios.teste": None, "inventario.teste": None}
        self.pedidos: list[httpx.Request] = []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        host = pedido.url.host
        falha = self.falha.get(host)
        if falha == "timeout":
            raise httpx.ReadTimeout("tempo esgotado", request=pedido)
        if falha == "conexao":
            raise httpx.ConnectError("conexão recusada", request=pedido)
        if falha == "500":
            return httpx.Response(500, json={"detail": "Internal Server Error"})
        if falha == "401":
            return httpx.Response(401, json={"detail": "Faça login para continuar."})
        if falha == "json":
            return httpx.Response(200, text="<html>proxy</html>")

        partes = pedido.url.path.strip("/").split("/")
        if host == "usuarios.teste" and len(partes) == 2 and partes[0] == "usuarios":
            uid = int(partes[1])
            if uid in self.usuarios:
                nome, perfil = self.usuarios[uid]
                return httpx.Response(200, json={"id": uid, "nome": nome, "perfil": perfil})
            return httpx.Response(404, json={"detail": f"Usuário {uid} não encontrado."})
        if host == "inventario.teste" and len(partes) == 2 and partes[0] == "ativos":
            aid = int(partes[1])
            if aid in self.ativos:
                pat, tipo, desc, setor = self.ativos[aid]
                return httpx.Response(200, json={"id": aid, "patrimonio": pat, "tipo": tipo, "descricao": desc, "setor": setor})
            return httpx.Response(404, json={"detail": f"Ativo {aid} não encontrado."})
        return httpx.Response(404, json={"detail": "Not Found"})

    def pedidos_para(self, host: str) -> list[httpx.Request]:
        return [p for p in self.pedidos if p.url.host == host]


@pytest.fixture
def rede():
    simulada = RedeSimulada()
    clientes.usar(clientes.novo_cliente(transport=httpx.MockTransport(simulada)))
    yield simulada
    clientes.fechar()


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
def cliente(sessao, rede):
    with TestClient(app) as c:
        # o TestClient fecha o cliente HTTP ao sair do ciclo de vida; aqui ele já foi trocado pelo simulado
        yield c


@pytest.fixture
def contas():
    """Cabeçalho de login de cada pessoa (mesmos ids da RedeSimulada)."""
    return {
        "admin": {"headers": cabecalho(gerar_token(1, "admin")), "id": 1},
        "ana": {"headers": cabecalho(gerar_token(2, "solicitante")), "id": 2},
        "bia": {"headers": cabecalho(gerar_token(3, "solicitante")), "id": 3},
        "carla": {"headers": cabecalho(gerar_token(4, "tecnico")), "id": 4},
    }


@pytest.fixture
def ativo():
    """Equipamento que existe no Inventário simulado."""
    return {"id": 1}
