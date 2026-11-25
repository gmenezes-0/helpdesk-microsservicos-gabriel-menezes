"""Testes de segurança do serviço de Chamados: permissões, entrada, respostas, saúde e segredo JWT."""
import pytest
from sqlalchemy.exc import OperationalError

from app import config
from app.database import get_db
from app.main import app
from tests.conftest import eventos_gravados


def abrir(cliente, h, **extra):
    return cliente.post("/chamados", headers=h, json={"titulo": "Teste", "descricao": "Teste", "prioridade": "baixa", **extra})


# ---------- permissões ----------

def test_solicitante_nao_ve_chamado_de_outra_pessoa(cliente, contas):
    cid = abrir(cliente, contas["ana"]["headers"]).json()["id"]
    assert cliente.get(f"/chamados/{cid}", headers=contas["bia"]["headers"]).status_code == 404
    assert cliente.get("/chamados", headers=contas["bia"]["headers"]).json() == []


def test_chamado_de_outra_pessoa_tem_a_mesma_resposta_que_inexistente(cliente, contas):
    cid = abrir(cliente, contas["ana"]["headers"]).json()["id"]
    outro = cliente.get(f"/chamados/{cid}", headers=contas["bia"]["headers"]).json()["detail"]
    assert outro == f"Chamado {cid} não encontrado."


def test_solicitante_nao_comenta_nem_muda_chamado_de_outra_pessoa(cliente, contas):
    cid = abrir(cliente, contas["ana"]["headers"]).json()["id"]
    h = contas["bia"]["headers"]
    assert cliente.post(f"/chamados/{cid}/comentarios", headers=h, json={"texto": "oi"}).status_code == 404
    assert cliente.patch(f"/chamados/{cid}/status", headers=h, json={"status": "fechado"}).status_code == 404


def test_solicitante_nao_atribui_nem_resolve(cliente, contas):
    cid = abrir(cliente, contas["ana"]["headers"]).json()["id"]
    h = contas["ana"]["headers"]
    assert cliente.patch(f"/chamados/{cid}/atribuir", headers=h, json={"tecnico_id": contas["carla"]["id"]}).status_code == 403
    assert cliente.patch(f"/chamados/{cid}/status", headers=h, json={"status": "em_atendimento"}).status_code == 403


def test_admin_ve_e_atribui(cliente, contas):
    cid = abrir(cliente, contas["ana"]["headers"]).json()["id"]
    h = contas["admin"]["headers"]
    assert cliente.get(f"/chamados/{cid}", headers=h).status_code == 200
    assert cliente.patch(f"/chamados/{cid}/atribuir", headers=h, json={"tecnico_id": contas["carla"]["id"]}).status_code == 200


def test_nao_da_para_abrir_chamado_em_nome_de_outro(cliente, contas):
    r = abrir(cliente, contas["ana"]["headers"], solicitante_id=contas["bia"]["id"])
    assert r.status_code == 422  # campo extra é recusado


def test_nao_da_para_comentar_em_nome_de_outro(cliente, contas):
    cid = abrir(cliente, contas["ana"]["headers"]).json()["id"]
    r = cliente.post(f"/chamados/{cid}/comentarios", headers=contas["ana"]["headers"],
                     json={"texto": "oi", "autor_id": contas["carla"]["id"]})
    assert r.status_code == 422


def test_nao_da_para_definir_status_ou_tecnico_ao_abrir(cliente, contas):
    for extra in ({"status": "fechado"}, {"tecnico_id": 4}, {"perfil": "tecnico"}):
        assert abrir(cliente, contas["ana"]["headers"], **extra).status_code == 422, extra


def test_evento_do_chamado_vai_so_para_o_solicitante(cliente, sessao, contas):
    abrir(cliente, contas["ana"]["headers"])
    assert [dados["destinatario_id"] for _, dados in eventos_gravados(sessao)] == [contas["ana"]["id"]]


def test_rota_antiga_de_notificacoes_saiu_do_chamados(cliente, contas):
    # agora é do serviço de Notificações (o gateway passa a encaminhar para lá)
    assert cliente.get("/notificacoes", headers=contas["ana"]["headers"]).status_code == 404


# ---------- entrada ----------

def test_titulo_grande_demais(cliente, contas):
    assert abrir(cliente, contas["ana"]["headers"], titulo="x" * 500).status_code == 422


def test_prioridade_e_status_desconhecidos(cliente, contas):
    assert abrir(cliente, contas["ana"]["headers"], prioridade="urgentissima").status_code == 422
    cid = abrir(cliente, contas["ana"]["headers"]).json()["id"]
    r = cliente.patch(f"/chamados/{cid}/status", headers=contas["carla"]["headers"], json={"status": "cancelado"})
    assert r.status_code == 422


def test_ids_invalidos(cliente, contas):
    assert abrir(cliente, contas["ana"]["headers"], ativo_id=0).status_code == 422
    cid = abrir(cliente, contas["ana"]["headers"]).json()["id"]
    r = cliente.patch(f"/chamados/{cid}/atribuir", headers=contas["carla"]["headers"], json={"tecnico_id": -1})
    assert r.status_code == 422


def test_requisicao_grande_demais(cliente, contas):
    corpo = '{"titulo": "' + "x" * 70000 + '"}'
    r = cliente.post("/chamados", headers={**contas["ana"]["headers"], "Content-Type": "application/json"}, content=corpo)
    assert r.status_code == 413


def test_texto_com_html_e_guardado_como_texto(cliente, contas):
    r = abrir(cliente, contas["ana"]["headers"], titulo="<script>alert(1)</script>")
    assert r.status_code == 201 and r.json()["titulo"] == "<script>alert(1)</script>"


# ---------- respostas ----------

def test_cabecalhos_de_seguranca(cliente):
    r = cliente.get("/saude")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_resposta_com_token_nao_vai_para_cache(cliente, contas):
    assert cliente.get("/chamados", headers=contas["ana"]["headers"]).headers["cache-control"] == "no-store"


def test_token_nao_aparece_na_representacao_do_usuario():
    from app.auth.tokens import UsuarioToken
    assert "segredo" not in repr(UsuarioToken(id=1, perfil="admin", autorizacao="Bearer segredo"))


# ---------- saúde ----------

def test_saude_nao_exige_login(cliente):
    r = cliente.get("/saude")
    assert r.status_code == 200 and r.json() == {"status": "ok", "servico": "chamados"}


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
