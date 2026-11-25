"""Testes de segurança do serviço de Notificações: respostas, saúde, segredos e isolamento."""
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from app import config
from app.database import get_db
from app.main import app


def test_cabecalhos_de_seguranca(cliente):
    r = cliente.get("/saude")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"


def test_resposta_com_token_nao_vai_para_cache(cliente, contas):
    assert cliente.get("/notificacoes", headers=contas["ana"]["headers"]).headers["cache-control"] == "no-store"


def test_requisicao_grande_demais(cliente, contas):
    r = cliente.post("/notificacoes", headers={**contas["ana"]["headers"], "Content-Type": "application/json"},
                     content="x" * 70000)
    assert r.status_code == 413


def test_nao_ha_rota_para_criar_avisos(cliente, contas):
    # avisos só nascem de eventos da fila: ninguém cria aviso pela API
    for metodo in ("post", "put", "patch", "delete"):
        assert getattr(cliente, metodo)("/notificacoes", headers=contas["admin"]["headers"]).status_code == 405, metodo


def test_saude_sem_login_e_com_estado_do_consumidor(cliente):
    r = cliente.get("/saude")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "servico": "notificacoes", "consumidor": "desligado"}


def test_saude_com_banco_fora(cliente):
    class SemBanco:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("unable to open database file"))

    app.dependency_overrides[get_db] = lambda: SemBanco()
    r = cliente.get("/saude")
    assert r.status_code == 503 and r.json()["status"] == "falha" and "database" not in r.text


def test_senha_do_rabbitmq_nao_vem_do_ambiente():
    # só existe o caminho do arquivo; não há variável com a senha
    assert not any("SENHA" in nome and nome != "RABBITMQ_SENHA_ARQUIVO" for nome in dir(config) if nome.isupper())


def test_codigo_nao_tem_senhas_nem_tokens_embutidos():
    codigo = "".join(p.read_text(encoding="utf-8") for p in Path(config.__file__).parent.rglob("*.py"))
    assert "guest" not in codigo and "eyJ" not in codigo and "PlainCredentials(RABBITMQ_USUARIO, senha)" in codigo


@pytest.mark.parametrize("valor", ["Xq7pZ", ""])
def test_segredo_jwt_curto_no_arquivo_impede_a_subida(tmp_path, monkeypatch, valor):
    arquivo = tmp_path / "jwt"
    arquivo.write_text(valor)
    monkeypatch.delenv("JWT_SEGREDO")
    monkeypatch.setenv("JWT_SEGREDO_ARQUIVO", str(arquivo))
    with pytest.raises(config.SegredoInvalido) as erro:
        config.carregar_segredo()
    assert "Xq7pZ" not in str(erro.value)  # o valor do segredo nunca aparece na mensagem
