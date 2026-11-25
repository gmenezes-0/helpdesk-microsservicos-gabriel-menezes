"""Testes do encaminhamento: serviço certo, método, caminho, query, corpo, token e respostas."""
import asyncio

import httpx
import pytest

from tests.conftest import TOKEN

# Todas as rotas dos serviços, com o serviço que deve atendê-las
ROTAS = [
    ("POST", "/auth/login", "usuarios"),
    ("GET", "/auth/eu", "usuarios"),
    ("POST", "/usuarios", "usuarios"),
    ("GET", "/usuarios", "usuarios"),
    ("GET", "/usuarios/4", "usuarios"),
    ("POST", "/ativos", "inventario"),
    ("GET", "/ativos", "inventario"),
    ("GET", "/ativos/1", "inventario"),
    ("POST", "/chamados", "chamados"),
    ("GET", "/chamados", "chamados"),
    ("GET", "/chamados/painel", "chamados"),
    ("GET", "/chamados/7", "chamados"),
    ("PATCH", "/chamados/7/atribuir", "chamados"),
    ("PATCH", "/chamados/7/status", "chamados"),
    ("POST", "/chamados/7/comentarios", "chamados"),
    ("GET", "/notificacoes", "chamados"),
]


@pytest.mark.parametrize("metodo,caminho,servico", ROTAS)
def test_cada_rota_vai_para_o_servico_certo(cliente, servicos, metodo, caminho, servico):
    corpo = b'{"exemplo": 1}' if metodo in ("POST", "PATCH") else b""
    r = cliente.request(metodo, caminho, headers={"Authorization": TOKEN, "Content-Type": "application/json"}, content=corpo)
    assert r.status_code == 200
    eco = r.json()
    assert eco["servico"] == servico and eco["metodo"] == metodo and eco["caminho"] == caminho
    assert eco["corpo"] == corpo.decode()
    assert eco["cabecalhos"]["authorization"] == TOKEN
    assert len(servicos.pedidos) == 1  # um pedido, só para o serviço certo


@pytest.mark.parametrize("caminho,query", [
    ("/ativos", "setor=RH"),
    ("/usuarios", "perfil=tecnico"),
    ("/chamados", "status=aberto&tecnico_id=4"),
    ("/ativos", "setor=Recursos%20Humanos&setor=TI"),
])
def test_query_string_e_preservada(cliente, caminho, query):
    eco = cliente.get(f"{caminho}?{query}", headers={"Authorization": TOKEN}).json()
    assert eco["query"] == query


def test_corpo_e_tipo_de_conteudo_sao_preservados(cliente):
    corpo = '{"titulo": "Acentuação ç", "descricao": "<b>x</b>", "prioridade": "alta"}'.encode()
    eco = cliente.post("/chamados", headers={"Authorization": TOKEN, "Content-Type": "application/json; charset=utf-8"},
                       content=corpo).json()
    assert eco["corpo"].encode() == corpo
    assert eco["cabecalhos"]["content-type"] == "application/json; charset=utf-8"


def test_sem_authorization_nada_e_inventado(cliente):
    eco = cliente.get("/chamados").json()
    assert "authorization" not in eco["cabecalhos"]


def test_host_original_e_repassado(cliente):
    # assim, redirecionamentos gerados pelos serviços apontam para o gateway, não para o nome interno
    assert cliente.get("/ativos", headers={"Host": "localhost:8000"}).json()["cabecalhos"]["host"] == "localhost:8000"


@pytest.mark.parametrize("status", [201, 400, 401, 403, 404, 409, 413, 422, 429, 500, 503])
def test_codigo_e_corpo_da_resposta_sao_preservados(cliente, servicos, status):
    servicos.resposta["chamados.teste"] = httpx.Response(status, json={"detail": f"resposta {status}"})
    r = cliente.get("/chamados", headers={"Authorization": TOKEN})
    assert r.status_code == status and r.json() == {"detail": f"resposta {status}"}
    assert r.headers["content-type"] == "application/json"


def test_cabecalhos_da_resposta_sao_preservados(cliente, servicos):
    servicos.resposta["chamados.teste"] = httpx.Response(
        401, json={"detail": "Faça login para continuar."}, headers={"WWW-Authenticate": "Bearer"})
    r = cliente.get("/chamados")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_redirecionamento_nao_e_seguido_pelo_gateway(cliente, servicos):
    servicos.resposta["chamados.teste"] = httpx.Response(307, headers={"Location": "http://localhost:8000/chamados"})
    r = cliente.get("/chamados/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "http://localhost:8000/chamados"
    assert len(servicos.pedidos) == 1


def test_resposta_sem_corpo(cliente, servicos):
    servicos.resposta["chamados.teste"] = httpx.Response(204)
    r = cliente.patch("/chamados/1/status", json={"status": "fechado"})
    assert r.status_code == 204 and r.content == b""


@pytest.mark.parametrize("caminho", ["/nada", "/usuariosx", "/ativo", "/chamadosX/1", "/saude/extra", "/admin"])
def test_rota_desconhecida_e_404_sem_chamar_servicos(cliente, servicos, caminho):
    r = cliente.get(caminho)
    assert r.status_code == 404 and servicos.pedidos == []


def chamar_direto(caminho: str) -> int:
    """Chama o app ASGI com o caminho bruto (o cliente de teste normalizaria "/../" antes de enviar)."""
    from app.main import app
    escopo = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
              "path": caminho, "raw_path": caminho.encode(), "root_path": "", "query_string": b"", "headers": [],
              "client": ("10.0.0.9", 5000), "server": ("gateway", 8000)}
    enviados = []

    async def receber():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def enviar(mensagem):
        enviados.append(mensagem)

    asyncio.run(app(escopo, receber, enviar))
    return next(m["status"] for m in enviados if m["type"] == "http.response.start")


@pytest.mark.parametrize("caminho", ["/chamados/../usuarios", "/ativos/./1", "/notificacoes/.."])
def test_caminho_com_ponto_e_recusado(servicos, caminho):
    assert chamar_direto(caminho) == 404 and servicos.pedidos == []


def test_caminho_com_ponto_codificado_e_recusado(cliente, servicos):
    assert cliente.get("/auth/%2e%2e/ativos").status_code == 404 and servicos.pedidos == []
