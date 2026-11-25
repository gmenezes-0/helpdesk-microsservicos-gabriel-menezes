"""Testes de segurança do serviço de Inventário: entrada, respostas, saúde e segredo JWT."""
import pytest
from sqlalchemy.exc import OperationalError

from app import config
from app.database import get_db
from app.main import app

ATIVO = {"patrimonio": "PAT-5", "tipo": "computador", "descricao": "Desktop", "setor": "TI"}


# ---------- entrada ----------

def test_campos_extras_sao_recusados(cliente, contas):
    r = cliente.post("/ativos", headers=contas["carla"]["headers"], json={**ATIVO, "id": 50})
    assert r.status_code == 422


def test_patrimonio_com_caracteres_invalidos(cliente, contas):
    for patrimonio in ("PAT 1", "<script>", "PA"):
        r = cliente.post("/ativos", headers=contas["carla"]["headers"], json={**ATIVO, "patrimonio": patrimonio})
        assert r.status_code == 422, patrimonio


def test_tipo_desconhecido(cliente, contas):
    r = cliente.post("/ativos", headers=contas["carla"]["headers"], json={**ATIVO, "tipo": "geladeira"})
    assert r.status_code == 422


def test_descricao_grande_demais(cliente, contas):
    r = cliente.post("/ativos", headers=contas["carla"]["headers"], json={**ATIVO, "descricao": "x" * 500})
    assert r.status_code == 422


def test_filtro_de_setor_grande_demais(cliente, contas):
    assert cliente.get("/ativos", params={"setor": "x" * 81}, headers=contas["ana"]["headers"]).status_code == 422


def test_requisicao_grande_demais(cliente, contas):
    corpo = '{"descricao": "' + "x" * 70000 + '"}'
    r = cliente.post("/ativos", headers={**contas["carla"]["headers"], "Content-Type": "application/json"}, content=corpo)
    assert r.status_code == 413


def test_texto_com_html_e_guardado_como_texto(cliente, contas):
    r = cliente.post("/ativos", headers=contas["carla"]["headers"], json={**ATIVO, "descricao": "<b>HP</b>"})
    assert r.status_code == 201 and r.json()["descricao"] == "<b>HP</b>"


# ---------- respostas ----------

def test_cabecalhos_de_seguranca(cliente):
    r = cliente.get("/saude")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_resposta_com_token_nao_vai_para_cache(cliente, contas):
    assert cliente.get("/ativos", headers=contas["ana"]["headers"]).headers["cache-control"] == "no-store"


# ---------- saúde ----------

def test_saude_nao_exige_login(cliente):
    r = cliente.get("/saude")
    assert r.status_code == 200 and r.json() == {"status": "ok", "servico": "inventario"}


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
