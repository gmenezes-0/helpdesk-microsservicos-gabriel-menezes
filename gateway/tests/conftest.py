import os

# Antes de importar o app: endereços falsos dos serviços (as respostas são simuladas)
os.environ["USUARIOS_URL"] = "http://usuarios.teste"
os.environ["INVENTARIO_URL"] = "http://inventario.teste"
os.environ["CHAMADOS_URL"] = "http://chamados.teste"
os.environ["NOTIFICACOES_URL"] = "http://notificacoes.teste"
os.environ["DOCS"] = "1"

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import proxy  # noqa: E402
from app.main import app  # noqa: E402

TOKEN = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIyIn0.assinatura-de-teste"


def especificacao(nome: str, caminhos: dict, esquemas: dict) -> dict:
    """OpenAPI mínimo, no formato que o FastAPI de cada serviço gera."""
    comum = {"HTTPValidationError": {"title": "HTTPValidationError", "type": "object"}}
    return {"openapi": "3.1.0", "info": {"title": f"HelpDesk TI · {nome}", "version": "2.0.0"},
            "paths": {"/saude": {"get": {"summary": "Saude"}}, **caminhos},
            "components": {"schemas": {**comum, **esquemas},
                           "securitySchemes": {"HTTPBearer": {"type": "http", "scheme": "bearer"}}}}


ESPECIFICACOES = {
    "usuarios.teste": especificacao("Usuários", {
        "/auth/login": {"post": {"summary": "Login"}}, "/auth/eu": {"get": {"summary": "Quem Sou Eu"}},
        "/usuarios": {"get": {"summary": "Listar Usuarios"}, "post": {"summary": "Criar Usuario"}},
        "/usuarios/{usuario_id}": {"get": {"summary": "Obter Usuario"}}},
        {"UsuarioSaida": {"type": "object"}}),
    "inventario.teste": especificacao("Inventário", {
        "/ativos": {"get": {"summary": "Listar Ativos"}}, "/ativos/{ativo_id}": {"get": {"summary": "Obter Ativo"}}},
        {"AtivoSaida": {"type": "object"}}),
    "chamados.teste": especificacao("Chamados", {
        "/chamados": {"get": {"summary": "Listar Chamados"}}, "/chamados/painel": {"get": {"summary": "Painel"}}},
        {"ChamadoSaida": {"type": "object"}}),
    "notificacoes.teste": especificacao("Notificações", {
        "/notificacoes": {"get": {"summary": "Minhas Notificacoes"}}},
        {"NotificacaoSaida": {"type": "object"}}),
}


class ServicosSimulados:
    """Faz o papel dos quatro serviços nos testes.

    Por padrão, cada um devolve um "eco" do que recebeu. Pode simular, por serviço:
    "timeout", "conexao", ou uma resposta pronta (httpx.Response) em `resposta`.
    """

    def __init__(self):
        self.falha: dict[str, str | None] = {}
        self.resposta: dict[str, httpx.Response] = {}
        self.pedidos: list[httpx.Request] = []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        host = pedido.url.host
        falha = self.falha.get(host)
        if falha == "timeout":
            raise httpx.ReadTimeout("tempo esgotado", request=pedido)
        if falha == "conexao":
            raise httpx.ConnectError("conexão recusada", request=pedido)
        if pedido.url.path == "/saude":
            return httpx.Response(200, json={"status": "ok", "servico": host.split(".")[0]})
        if pedido.url.path == "/openapi.json":
            return httpx.Response(200, json=ESPECIFICACOES[host])
        if host in self.resposta:
            return self.resposta[host]
        return httpx.Response(200, json={
            "servico": host.split(".")[0], "metodo": pedido.method, "caminho": pedido.url.raw_path.decode(),
            "query": pedido.url.query.decode(), "corpo": pedido.content.decode(),
            "cabecalhos": {k.lower(): v for k, v in pedido.headers.multi_items()},
        })

    def pedidos_para(self, host: str) -> list[httpx.Request]:
        return [p for p in self.pedidos if p.url.host == host]


@pytest.fixture
def servicos():
    simulados = ServicosSimulados()
    proxy.usar(proxy.novo_cliente(transport=httpx.MockTransport(simulados)))
    yield simulados
    proxy.usar(None)


@pytest.fixture
def cliente(servicos):
    with TestClient(app) as c:
        yield c
