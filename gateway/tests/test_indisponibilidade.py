"""Testes de serviço fora do ar, tempo limite e saúde agregada."""
import httpx
import pytest

from app import config, proxy
from tests.conftest import TOKEN

DETALHES_INTERNOS = ("chamados.teste", "inventario.teste", "usuarios.teste", "notificacoes.teste", "tempo esgotado", "recusada",
                     "ConnectError", "ReadTimeout", "Traceback")


# ---------- tempo limite ----------

def test_tempo_limite_padrao_e_de_10_segundos():
    assert config.TIMEOUT_SEGUNDOS == 10
    cliente = proxy.novo_cliente()
    assert cliente.timeout.read == cliente.timeout.connect == 10 and cliente.follow_redirects is False


# ---------- serviço fora do ar ----------

@pytest.mark.parametrize("falha", ["timeout", "conexao"])
@pytest.mark.parametrize("caminho,host,nome", [
    ("/auth/login", "usuarios.teste", "usuários"),
    ("/ativos", "inventario.teste", "inventário"),
    ("/chamados", "chamados.teste", "chamados"),
    ("/notificacoes", "notificacoes.teste", "notificações"),
])
def test_servico_fora_do_ar_responde_503_sem_detalhes(cliente, servicos, falha, caminho, host, nome):
    servicos.falha[host] = falha
    r = cliente.get(caminho, headers={"Authorization": TOKEN})
    assert r.status_code == 503
    assert r.json() == {"detail": f"O serviço de {nome} está indisponível no momento. Tente novamente em instantes."}
    assert all(detalhe not in r.text for detalhe in DETALHES_INTERNOS)
    assert r.headers["x-frame-options"] == "DENY"  # resposta de erro também leva os cabeçalhos de segurança


def test_um_servico_fora_nao_afeta_os_outros(cliente, servicos):
    servicos.falha["inventario.teste"] = "conexao"
    h = {"Authorization": TOKEN}
    assert cliente.get("/ativos", headers=h).status_code == 503
    assert cliente.get("/usuarios", headers=h).status_code == 200
    assert cliente.get("/chamados", headers=h).status_code == 200
    assert cliente.get("/notificacoes", headers=h).status_code == 200
    assert cliente.get("/").status_code == 200


def test_erro_503_do_proprio_servico_passa_como_veio(cliente, servicos):
    # ex.: Chamados respondendo 503 porque o Inventário caiu: a mensagem dele chega à tela
    detalhe = "O serviço de inventário está indisponível no momento. Tente novamente em instantes."
    servicos.resposta["chamados.teste"] = httpx.Response(503, json={"detail": detalhe})
    r = cliente.post("/chamados", headers={"Authorization": TOKEN}, json={"ativo_id": 1})
    assert r.status_code == 503 and r.json()["detail"] == detalhe


# ---------- saúde agregada ----------

def test_saude_com_tudo_no_ar(cliente, servicos):
    r = cliente.get("/saude")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "servico": "gateway",
                        "servicos": {"usuarios": "ok", "inventario": "ok", "chamados": "ok", "notificacoes": "ok"}}
    assert {p.url.host for p in servicos.pedidos} == {"usuarios.teste", "inventario.teste", "chamados.teste",
                                                      "notificacoes.teste"}


@pytest.mark.parametrize("falha", ["timeout", "conexao"])
def test_saude_mostra_qual_servico_caiu(cliente, servicos, falha):
    servicos.falha["inventario.teste"] = falha
    r = cliente.get("/saude")
    assert r.status_code == 200  # o gateway continua no ar
    assert r.json()["status"] == "degradado"
    assert r.json()["servicos"] == {"usuarios": "ok", "inventario": "fora do ar", "chamados": "ok", "notificacoes": "ok"}


def test_saude_considera_fora_do_ar_quem_responde_falha(cliente, servicos):
    def doente(pedido):
        if pedido.url.host == "chamados.teste":
            return httpx.Response(503, json={"status": "falha", "servico": "chamados"})
        return httpx.Response(200, json={"status": "ok"})

    proxy.usar(proxy.novo_cliente(transport=httpx.MockTransport(doente)))
    assert cliente.get("/saude").json()["servicos"]["chamados"] == "fora do ar"


def test_saude_nao_exige_login_e_nao_repassa_token(cliente, servicos):
    cliente.get("/saude", headers={"Authorization": TOKEN})
    assert all("authorization" not in p.headers for p in servicos.pedidos)


# ---------- serviço de Notificações ----------

@pytest.mark.parametrize("falha", ["timeout", "conexao"])
def test_notificacoes_fora_nao_afeta_chamados_e_aparece_na_saude(cliente, servicos, falha):
    servicos.falha["notificacoes.teste"] = falha
    h = {"Authorization": TOKEN}
    r = cliente.get("/notificacoes", headers=h)
    assert r.status_code == 503
    assert r.json() == {"detail": "O serviço de notificações está indisponível no momento. Tente novamente em instantes."}
    assert cliente.post("/chamados", headers=h, json={"titulo": "x"}).status_code == 200  # eco do Chamados
    assert cliente.get("/").status_code == 200
    saude = cliente.get("/saude").json()
    assert saude["status"] == "degradado" and saude["servicos"]["notificacoes"] == "fora do ar"


def test_notificacoes_vai_so_para_o_servico_de_notificacoes(cliente, servicos):
    cliente.get("/notificacoes", headers={"Authorization": TOKEN})
    assert [p.url.host for p in servicos.pedidos] == ["notificacoes.teste"]
    assert servicos.pedidos[0].headers["authorization"] == TOKEN  # token repassado como veio
