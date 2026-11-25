"""Testes de segurança do gateway: endereço de origem, cabeçalhos, limite de tamanho e logs."""
import logging

from tests.conftest import TOKEN


# ---------- endereço de origem ----------

def test_x_forwarded_for_do_cliente_e_substituido(cliente):
    eco = cliente.post("/auth/login", headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}, json={}).json()
    # o TestClient conecta como "testclient": é esse o endereço real da conexão
    assert eco["cabecalhos"]["x-forwarded-for"] == "testclient"


def test_outros_cabecalhos_de_origem_sao_descartados(cliente):
    falsos = {"X-Real-IP": "1.2.3.4", "Forwarded": "for=1.2.3.4", "X-Forwarded-Host": "malicioso.com",
              "X-Forwarded-Proto": "https", "X-Forwarded-Port": "443"}
    cabecalhos = cliente.get("/ativos", headers=falsos).json()["cabecalhos"]
    for nome in ("x-real-ip", "forwarded", "x-forwarded-host", "x-forwarded-port"):
        assert nome not in cabecalhos, nome
    assert cabecalhos["x-forwarded-proto"] == "http"  # definido pelo gateway


def test_cabecalhos_de_conexao_nao_sao_repassados(cliente):
    cabecalhos = cliente.get("/ativos", headers={"Proxy-Authorization": "Basic x", "X-Interno": "1",
                                                 "Connection": "X-Interno"}).json()["cabecalhos"]
    assert "proxy-authorization" not in cabecalhos and "x-interno" not in cabecalhos


# ---------- limite de tamanho ----------

def test_requisicao_grande_demais(cliente, servicos):
    corpo = '{"titulo": "' + "x" * 70000 + '"}'
    r = cliente.post("/chamados", headers={"Authorization": TOKEN, "Content-Type": "application/json"}, content=corpo)
    assert r.status_code == 413 and servicos.pedidos == []


def test_requisicao_grande_demais_sem_content_length(cliente, servicos):
    def pedacos():  # corpo enviado em partes (chunked), sem Content-Length
        for _ in range(70):
            yield b"x" * 1024

    r = cliente.post("/chamados", headers={"Authorization": TOKEN}, content=pedacos())
    assert r.status_code == 413 and servicos.pedidos == []


def test_requisicao_no_limite_passa(cliente, servicos):
    corpo = b"x" * (64 * 1024)
    assert cliente.post("/chamados", content=corpo).status_code == 200


def test_content_length_invalido(cliente, servicos):
    r = cliente.post("/chamados", headers={"Content-Length": "abc"}, content=b"{}")
    assert r.status_code == 413 and servicos.pedidos == []


# ---------- cabeçalhos das respostas ----------

def test_cabecalhos_de_seguranca_na_tela(cliente):
    r = cliente.get("/")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_cabecalhos_de_seguranca_nas_respostas_dos_servicos(cliente):
    r = cliente.get("/chamados", headers={"Authorization": TOKEN})
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"  # resposta de quem está logado não vai para cache


def test_cabecalhos_de_seguranca_nao_duplicam(cliente):
    r = cliente.get("/chamados")
    assert len(r.headers.get_list("x-frame-options")) == 1
    assert len(r.headers.get_list("content-security-policy")) == 1


def test_csp_da_documentacao_libera_so_o_swagger(cliente):
    csp = cliente.get("/docs").headers["content-security-policy"]
    assert "https://cdn.jsdelivr.net" in csp and "frame-ancestors 'none'" in csp


# ---------- logs ----------

def test_token_nunca_vai_para_o_log(cliente, servicos, caplog):
    servicos.falha["chamados.teste"] = "conexao"
    with caplog.at_level(logging.DEBUG):
        cliente.get("/chamados?status=aberto", headers={"Authorization": TOKEN})
    assert caplog.records  # a falha foi registrada...
    assert all("eyJ" not in r.getMessage() and "Bearer" not in r.getMessage() for r in caplog.records)  # ...sem o token
