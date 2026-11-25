"""Testes de segurança do serviço de Usuários: senhas, permissões, entrada, respostas e segredo JWT."""
import pytest
from sqlalchemy.exc import OperationalError

from app import config
from app.database import get_db
from app.main import app
from tests.conftest import SENHA


# ---------- senhas ----------

def test_senha_guardada_com_hash(sessao, contas):
    from app.usuarios.modelos import Usuario
    with sessao() as db:
        u = db.query(Usuario).filter_by(email="ana@x.com").one()
        assert SENHA not in u.senha_hash and u.senha_hash.startswith("scrypt$")


def test_senha_fraca_e_recusada(cliente, contas):
    r = cliente.post("/usuarios", headers=contas["admin"]["headers"],
                     json={"nome": "Eva", "email": "eva@x.com", "perfil": "solicitante", "senha": "abcdefgh"})
    assert r.status_code == 422


# ---------- permissões ----------

def test_solicitante_nao_cria_usuario(cliente, contas):
    r = cliente.post("/usuarios", headers=contas["ana"]["headers"],
                     json={"nome": "Eva", "email": "eva@x.com", "perfil": "admin", "senha": "Forte1234"})
    assert r.status_code == 403


def test_tecnico_nao_cria_usuario(cliente, contas):
    r = cliente.post("/usuarios", headers=contas["carla"]["headers"],
                     json={"nome": "Eva", "email": "eva@x.com", "perfil": "admin", "senha": "Forte1234"})
    assert r.status_code == 403


# ---------- entrada ----------

def test_campos_extras_sao_recusados(cliente, contas):
    r = cliente.post("/usuarios", headers=contas["admin"]["headers"],
                     json={"nome": "Eva", "email": "eva@x.com", "perfil": "admin", "senha": "Forte1234", "ativo": False})
    assert r.status_code == 422
    assert cliente.post("/auth/login", json={"email": "ana@x.com", "senha": SENHA, "perfil": "admin"}).status_code == 422


def test_perfil_inexistente_e_recusado(cliente, contas):
    r = cliente.post("/usuarios", headers=contas["admin"]["headers"],
                     json={"nome": "Eva", "email": "eva@x.com", "perfil": "root", "senha": "Forte1234"})
    assert r.status_code == 422


def test_nome_grande_demais(cliente, contas):
    r = cliente.post("/usuarios", headers=contas["admin"]["headers"],
                     json={"nome": "x" * 500, "email": "eva@x.com", "perfil": "solicitante", "senha": "Forte1234"})
    assert r.status_code == 422


def test_requisicao_grande_demais(cliente, contas):
    corpo = '{"email": "' + "x" * 70000 + '"}'
    r = cliente.post("/auth/login", headers={"Content-Type": "application/json"}, content=corpo)
    assert r.status_code == 413


# ---------- respostas ----------

def test_cabecalhos_de_seguranca(cliente):
    r = cliente.get("/saude")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_resposta_com_token_nao_vai_para_cache(cliente, contas):
    r = cliente.get("/auth/eu", headers=contas["ana"]["headers"])
    assert r.headers["cache-control"] == "no-store"


# ---------- saúde ----------

def test_saude_nao_exige_login(cliente):
    r = cliente.get("/saude")
    assert r.status_code == 200 and r.json() == {"status": "ok", "servico": "usuarios"}


def test_saude_avisa_quando_o_banco_falha(cliente):
    class BancoFora:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("sem banco"))

    app.dependency_overrides[get_db] = lambda: BancoFora()
    r = cliente.get("/saude")
    assert r.status_code == 503 and r.json()["status"] == "falha"
    assert "sem banco" not in r.text  # não vaza detalhes do erro


# ---------- segredo JWT ----------

def test_segredo_vem_da_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv("JWT_SEGREDO", "s" * 40)
    monkeypatch.setenv("JWT_SEGREDO_ARQUIVO", "/nao/existe")
    assert config.carregar_segredo() == "s" * 40


def test_segredo_vem_do_arquivo_compartilhado(monkeypatch, tmp_path):
    arquivo = tmp_path / "jwt"
    arquivo.write_text("a" * 48 + "\n", encoding="utf-8")
    monkeypatch.delenv("JWT_SEGREDO", raising=False)
    monkeypatch.setenv("JWT_SEGREDO_ARQUIVO", str(arquivo))
    assert config.carregar_segredo() == "a" * 48


def test_arquivo_de_segredo_ausente_impede_o_servico_de_subir(monkeypatch, tmp_path):
    monkeypatch.delenv("JWT_SEGREDO", raising=False)
    monkeypatch.setenv("JWT_SEGREDO_ARQUIVO", str(tmp_path / "nao-existe"))
    with pytest.raises(config.SegredoInvalido):
        config.carregar_segredo()


def test_arquivo_de_segredo_curto_impede_o_servico_de_subir(monkeypatch, tmp_path):
    arquivo = tmp_path / "jwt"
    arquivo.write_text("Xq7pZ", encoding="utf-8")
    monkeypatch.delenv("JWT_SEGREDO", raising=False)
    monkeypatch.setenv("JWT_SEGREDO_ARQUIVO", str(arquivo))
    with pytest.raises(config.SegredoInvalido) as erro:
        config.carregar_segredo()
    assert "Xq7pZ" not in str(erro.value)  # a mensagem nunca mostra o segredo


def test_sem_segredo_configurado_usa_um_aleatorio_forte(monkeypatch):
    monkeypatch.delenv("JWT_SEGREDO", raising=False)
    monkeypatch.delenv("JWT_SEGREDO_ARQUIVO", raising=False)
    primeiro, segundo = config.carregar_segredo(), config.carregar_segredo()
    assert len(primeiro) >= 32 and primeiro != segundo


def test_segredo_curto_na_variavel_nao_e_usado(monkeypatch):
    monkeypatch.setenv("JWT_SEGREDO", "curto")
    monkeypatch.delenv("JWT_SEGREDO_ARQUIVO", raising=False)
    segredo = config.carregar_segredo()
    assert segredo != "curto" and len(segredo) >= 32
