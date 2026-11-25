"""Testes da comunicação HTTP com Usuários e Inventário: repasse do token, timeout e falhas."""
import httpx
import pytest

from app import clientes, config

ABRIR = {"titulo": "PC não liga", "descricao": "Nada acontece", "prioridade": "alta", "ativo_id": 1}
FALHAS = ["timeout", "conexao", "500", "401", "json"]


def abrir(cliente, contas, quem="ana", **extra):
    return cliente.post("/chamados", headers=contas[quem]["headers"], json={**ABRIR, **extra})


# ---------- configuração ----------

def test_tempo_limite_padrao_e_de_3_segundos():
    assert config.HTTP_TIMEOUT_SEGUNDOS == 3
    with clientes.novo_cliente() as http:
        assert http.timeout.connect == http.timeout.read == http.timeout.write == http.timeout.pool == 3
        assert http.follow_redirects is False


# ---------- repasse do token ----------

def test_abrir_consulta_o_inventario_repassando_o_token(cliente, contas, rede):
    assert abrir(cliente, contas).status_code == 201
    [pedido] = rede.pedidos_para("inventario.teste")
    assert pedido.method == "GET" and pedido.url.path == "/ativos/1"
    assert pedido.headers["authorization"] == contas["ana"]["headers"]["Authorization"]


def test_atribuir_consulta_usuarios_repassando_o_token(cliente, contas, rede):
    cid = abrir(cliente, contas).json()["id"]
    cliente.patch(f"/chamados/{cid}/atribuir", headers=contas["carla"]["headers"], json={"tecnico_id": 4})
    [pedido] = rede.pedidos_para("usuarios.teste")
    assert pedido.method == "GET" and pedido.url.path == "/usuarios/4"
    assert pedido.headers["authorization"] == contas["carla"]["headers"]["Authorization"]


def test_token_e_repassado_exatamente_como_chegou(cliente, contas, rede):
    original = "bearer " + contas["ana"]["headers"]["Authorization"].split()[1]  # esquema em minúsculas
    assert cliente.post("/chamados", headers={"Authorization": original}, json=ABRIR).status_code == 201
    assert rede.pedidos_para("inventario.teste")[0].headers["authorization"] == original


def test_sem_token_valido_nao_chama_outros_servicos(cliente, contas, rede):
    assert cliente.post("/chamados", json=ABRIR).status_code == 401
    assert cliente.post("/chamados", headers={"Authorization": "Bearer abc"}, json=ABRIR).status_code == 401
    assert rede.pedidos == []


def test_solicitante_que_tenta_atribuir_nao_gera_chamada_http(cliente, contas, rede):
    cid = abrir(cliente, contas).json()["id"]
    rede.pedidos.clear()
    assert cliente.patch(f"/chamados/{cid}/atribuir", headers=contas["ana"]["headers"], json={"tecnico_id": 4}).status_code == 403
    assert rede.pedidos == []


# ---------- recurso inexistente ----------

def test_equipamento_inexistente_e_404(cliente, contas):
    r = abrir(cliente, contas, ativo_id=999)
    assert r.status_code == 404 and r.json()["detail"] == "Ativo 999 não encontrado."


def test_tecnico_inexistente_e_404(cliente, contas):
    cid = abrir(cliente, contas).json()["id"]
    r = cliente.patch(f"/chamados/{cid}/atribuir", headers=contas["carla"]["headers"], json={"tecnico_id": 77})
    assert r.status_code == 404 and r.json()["detail"] == "Usuário 77 não encontrado."


# ---------- Inventário com problema ----------

@pytest.mark.parametrize("falha", FALHAS)
def test_inventario_com_problema_responde_503_sem_detalhes(cliente, contas, rede, falha):
    rede.falha["inventario.teste"] = falha
    r = abrir(cliente, contas)
    assert r.status_code == 503
    assert r.json() == {"detail": "O serviço de inventário está indisponível no momento. Tente novamente em instantes."}
    for detalhe in ("inventario.teste", "timeout", "tempo esgotado", "recusada", "Internal", "html", "Traceback"):
        assert detalhe not in r.text
    assert cliente.get("/chamados", headers=contas["carla"]["headers"]).json() == []  # nada foi gravado
    assert cliente.get("/notificacoes", headers=contas["ana"]["headers"]).json() == []


def test_inventario_fora_nao_impede_o_resto(cliente, contas, rede):
    rede.falha["inventario.teste"] = "conexao"
    sem_equipamento = {k: v for k, v in ABRIR.items() if k != "ativo_id"}
    assert cliente.post("/chamados", headers=contas["ana"]["headers"], json=sem_equipamento).status_code == 201
    assert len(cliente.get("/chamados", headers=contas["ana"]["headers"]).json()) == 1
    assert cliente.get("/chamados/painel", headers=contas["ana"]["headers"]).status_code == 200
    assert cliente.get("/notificacoes", headers=contas["ana"]["headers"]).status_code == 200


# ---------- Usuários com problema ----------

@pytest.mark.parametrize("falha", FALHAS)
def test_usuarios_com_problema_responde_503_e_nao_atribui(cliente, contas, rede, falha):
    cid = abrir(cliente, contas).json()["id"]
    rede.falha["usuarios.teste"] = falha
    r = cliente.patch(f"/chamados/{cid}/atribuir", headers=contas["carla"]["headers"], json={"tecnico_id": 4})
    assert r.status_code == 503
    assert r.json() == {"detail": "O serviço de usuários está indisponível no momento. Tente novamente em instantes."}
    c = cliente.get(f"/chamados/{cid}", headers=contas["carla"]["headers"]).json()
    assert c["status"] == "aberto" and c["tecnico_id"] is None


def test_usuarios_fora_nao_impede_listar_comentar_e_mudar_status(cliente, contas, rede):
    cid = abrir(cliente, contas).json()["id"]
    tec = contas["carla"]["headers"]
    cliente.patch(f"/chamados/{cid}/atribuir", headers=tec, json={"tecnico_id": 4})
    rede.falha["usuarios.teste"] = "conexao"
    rede.falha["inventario.teste"] = "conexao"
    assert cliente.get("/chamados", headers=tec).status_code == 200
    assert cliente.post(f"/chamados/{cid}/comentarios", headers=tec, json={"texto": "ok"}).status_code == 201
    assert cliente.patch(f"/chamados/{cid}/status", headers=tec, json={"status": "resolvido"}).status_code == 200


# ---------- respostas fora do esperado ----------

def test_resposta_com_outro_ativo_e_503(cliente, contas):
    clientes.usar(clientes.novo_cliente(transport=httpx.MockTransport(
        lambda pedido: httpx.Response(200, json={"id": 2, "patrimonio": "PAT-2"}))))
    assert abrir(cliente, contas).status_code == 503


def test_resposta_de_usuario_sem_perfil_e_503(cliente, contas):
    cid = abrir(cliente, contas, ativo_id=None).json()["id"]
    clientes.usar(clientes.novo_cliente(transport=httpx.MockTransport(
        lambda pedido: httpx.Response(200, json={"id": 4, "nome": "Carla"}))))
    r = cliente.patch(f"/chamados/{cid}/atribuir", headers=contas["carla"]["headers"], json={"tecnico_id": 4})
    assert r.status_code == 503
