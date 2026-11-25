"""Testes das credenciais e definições do RabbitMQ geradas pelo gerador (Linux: uid e permissões POSIX)."""
import base64
import hashlib
import importlib
import json
import os
import stat
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="permissões POSIX")

CLIENTES = {"chamados", "notificacoes"}


def carregar(monkeypatch, jwt, mq=None):
    monkeypatch.setenv("SEGREDO_PASTA", str(jwt))
    if mq is None:
        monkeypatch.delenv("MQ_SEGREDOS_PASTA", raising=False)
    else:
        monkeypatch.setenv("MQ_SEGREDOS_PASTA", str(mq))
    sys.path.insert(0, os.path.dirname(__file__))
    try:
        return importlib.reload(importlib.import_module("gerar_segredo"))
    finally:
        sys.path.pop(0)


def liberar(*pastas):
    """Devolve a escrita às pastas (o gerador as deixa 0500) para o teste mexer ou o pytest apagar."""
    for pasta in pastas:
        for raiz, subpastas, _ in os.walk(pasta):
            os.chmod(raiz, 0o700)
            for sub in subpastas:
                os.chmod(os.path.join(raiz, sub), 0o700)


@pytest.fixture
def pastas(tmp_path):
    jwt, mq = tmp_path / "jwt", tmp_path / "mq"
    jwt.mkdir(mode=0o700)
    mq.mkdir(mode=0o700)
    yield jwt, mq
    liberar(jwt, mq)


@pytest.fixture
def gerado(pastas, monkeypatch, capsys):
    jwt, mq = pastas
    gerador = carregar(monkeypatch, jwt, mq)
    gerador.main()
    saida = capsys.readouterr()
    senhas = {u: (mq / u / "senha").read_text() for u in CLIENTES}
    definicoes = json.loads((mq / "rabbitmq" / "definicoes.json").read_text())
    return gerador, senhas, definicoes, saida


def conferir_hash_como_o_rabbitmq(senha: str, hash_b64: str) -> bool:
    # Implementação independente da do gerador: sal = 4 primeiros bytes; resto = SHA-256(sal + senha)
    bruto = base64.b64decode(hash_b64)
    return len(bruto) == 36 and hashlib.sha256(bruto[:4] + senha.encode()).digest() == bruto[4:]


# ---------- comportamento anterior preservado ----------

def test_sem_a_variavel_so_gera_o_segredo_jwt(pastas, monkeypatch):
    jwt, mq = pastas
    carregar(monkeypatch, jwt).main()
    assert (jwt / "jwt").is_file()
    assert list(mq.iterdir()) == []


def test_segredo_jwt_existente_e_preservado_ao_ligar_o_rabbitmq(pastas, monkeypatch):
    jwt, mq = pastas
    carregar(monkeypatch, jwt).main()
    antes = (jwt / "jwt").read_text()
    carregar(monkeypatch, jwt, mq).main()
    assert (jwt / "jwt").read_text() == antes
    assert (mq / "rabbitmq" / "definicoes.json").is_file()


# ---------- geração ----------

def test_gera_um_arquivo_por_subpasta_com_permissoes_restritas(gerado, pastas):
    _, mq = pastas
    assert {p.name for p in mq.iterdir()} == {"rabbitmq", "chamados", "notificacoes"}  # sem temporários
    for sub, arquivo in [("rabbitmq", "definicoes.json"), ("chamados", "senha"), ("notificacoes", "senha")]:
        assert [p.name for p in (mq / sub).iterdir()] == [arquivo]
        assert stat.S_IMODE((mq / sub / arquivo).stat().st_mode) == 0o400
        assert stat.S_IMODE((mq / sub).stat().st_mode) == 0o500
    assert stat.S_IMODE(mq.stat().st_mode) == 0o500


def test_senhas_fortes_e_distintas(gerado, pastas):
    _, senhas, _, _ = gerado
    jwt, _ = pastas
    assert all(len(s) >= 43 for s in senhas.values())  # 32 bytes aleatórios
    assert len(set(senhas.values())) == 2
    assert (jwt / "jwt").read_text() not in senhas.values()


def test_cada_geracao_produz_senhas_diferentes(tmp_path, monkeypatch):
    resultados = []
    for i in range(2):
        jwt, mq = tmp_path / f"jwt{i}", tmp_path / f"mq{i}"
        jwt.mkdir(mode=0o700)
        mq.mkdir(mode=0o700)
        carregar(monkeypatch, jwt, mq).main()
        resultados.append((mq / "chamados" / "senha").read_text())
        liberar(jwt, mq)
    assert resultados[0] != resultados[1]


def test_nenhuma_senha_aparece_na_saida(gerado):
    _, senhas, _, saida = gerado
    assert all(s not in saida.out + saida.err for s in senhas.values())


# ---------- hashes ----------

def test_definicoes_tem_so_hashes_nunca_a_senha(gerado, pastas):
    _, senhas, definicoes, _ = gerado
    _, mq = pastas
    texto = (mq / "rabbitmq" / "definicoes.json").read_text()
    assert all(s not in texto for s in senhas.values())
    usuarios = {u["name"]: u for u in definicoes["users"]}
    assert set(usuarios) == CLIENTES
    for nome, usuario in usuarios.items():
        assert set(usuario) == {"name", "password_hash", "hashing_algorithm", "tags"}
        assert usuario["hashing_algorithm"] == "rabbit_password_hashing_sha256"
        assert usuario["tags"] == []  # nenhum usuário administrador
        assert conferir_hash_como_o_rabbitmq(senhas[nome], usuario["password_hash"])
        assert not conferir_hash_como_o_rabbitmq(senhas[nome] + "x", usuario["password_hash"])


def test_hash_usa_sal_aleatorio(gerado):
    gerador = gerado[0]
    assert gerador.hash_senha_rabbitmq("mesma") != gerador.hash_senha_rabbitmq("mesma")
    assert gerador.hash_confere("mesma", gerador.hash_senha_rabbitmq("mesma"))
    assert not gerador.hash_confere("mesma", "nao-e-base64!")


# ---------- permissões e topologia ----------

def test_permissoes_minimas(gerado):
    definicoes = gerado[2]
    permissoes = {p["user"]: (p["vhost"], p["configure"], p["write"], p["read"]) for p in definicoes["permissions"]}
    assert permissoes == {
        "chamados": ("helpdesk", "^$", r"^helpdesk\.eventos$", "^$"),          # só publica
        "notificacoes": ("helpdesk", "^$", "^$", r"^notificacoes\.eventos$"),  # só consome
    }
    assert definicoes["vhosts"] == [{"name": "helpdesk"}]


def test_exchanges_filas_ligacoes_e_mensagens_mortas(gerado):
    definicoes = gerado[2]
    exchanges = {e["name"]: (e["type"], e["durable"]) for e in definicoes["exchanges"]}
    assert exchanges == {"helpdesk.eventos": ("topic", True), "helpdesk.eventos.dlx": ("fanout", True)}
    filas = {f["name"]: f for f in definicoes["queues"]}
    assert filas["notificacoes.eventos"]["durable"] is True
    assert filas["notificacoes.eventos"]["arguments"] == {
        "x-queue-type": "quorum", "x-delivery-limit": 5, "x-dead-letter-exchange": "helpdesk.eventos.dlx"}
    assert filas["notificacoes.eventos.dlq"]["arguments"] == {"x-queue-type": "quorum"}
    ligacoes = {(b["source"], b["destination"], b["routing_key"]) for b in definicoes["bindings"]}
    assert ligacoes == {("helpdesk.eventos", "notificacoes.eventos", "chamado.*"),
                        ("helpdesk.eventos.dlx", "notificacoes.eventos.dlq", "")}
    assert all(item["vhost"] == "helpdesk" for chave in ("exchanges", "queues", "bindings") for item in definicoes[chave])


# ---------- não sobrescrita e estados inválidos ----------

def test_nao_sobrescreve_credenciais_existentes(gerado, pastas, monkeypatch, capsys):
    jwt, mq = pastas
    antes = {p: p.read_bytes() for p in mq.rglob("*") if p.is_file()}
    jwt_antes = (jwt / "jwt").read_text()
    carregar(monkeypatch, jwt, mq).main()
    assert {p: p.read_bytes() for p in mq.rglob("*") if p.is_file()} == antes
    assert (jwt / "jwt").read_text() == jwt_antes
    assert "mantidas" in capsys.readouterr().out


def _falha(monkeypatch, jwt, mq, capsys):
    with pytest.raises(SystemExit) as saida:
        carregar(monkeypatch, jwt, mq).main()
    assert saida.value.code == 1
    return capsys.readouterr().err


def test_credenciais_incompletas_sao_erro_e_nada_e_completado(gerado, pastas, monkeypatch, capsys):
    jwt, mq = pastas
    _, senhas, _, _ = gerado
    liberar(mq)
    (mq / "notificacoes" / "senha").unlink()
    erro = _falha(monkeypatch, jwt, mq, capsys)
    assert "incompletas" in erro and "notificacoes/senha" in erro
    assert not (mq / "notificacoes" / "senha").exists()
    assert (mq / "chamados" / "senha").read_text() == senhas["chamados"]


def test_senha_trocada_sem_o_hash_e_erro(gerado, pastas, monkeypatch, capsys):
    jwt, mq = pastas
    liberar(mq)
    arquivo = mq / "chamados" / "senha"
    os.chmod(arquivo, 0o600)
    arquivo.write_text("Xq7pZ" * 10)
    erro = _falha(monkeypatch, jwt, mq, capsys)
    assert "não correspondem" in erro and "Xq7pZ" not in erro
    assert arquivo.read_text() == "Xq7pZ" * 10  # não foi corrigido sozinho


def test_definicoes_corrompidas_sao_erro(gerado, pastas, monkeypatch, capsys):
    jwt, mq = pastas
    liberar(mq)
    arquivo = mq / "rabbitmq" / "definicoes.json"
    os.chmod(arquivo, 0o600)
    arquivo.write_text("{ isto não é json")
    assert "corrompidas" in _falha(monkeypatch, jwt, mq, capsys)


def test_senha_em_texto_puro_nas_definicoes_e_erro(gerado, pastas, monkeypatch, capsys):
    jwt, mq = pastas
    _, senhas, definicoes, _ = gerado
    liberar(mq)
    arquivo = mq / "rabbitmq" / "definicoes.json"
    os.chmod(arquivo, 0o600)
    definicoes["users"][0]["comentario"] = senhas[definicoes["users"][0]["name"]]
    arquivo.write_text(json.dumps(definicoes))
    erro = _falha(monkeypatch, jwt, mq, capsys)
    assert "texto puro" in erro and all(s not in erro for s in senhas.values())


def test_link_simbolico_no_lugar_da_senha_e_recusado(gerado, pastas, monkeypatch, capsys, tmp_path):
    jwt, mq = pastas
    liberar(mq)
    alvo = tmp_path / "alvo"
    alvo.write_text("y" * 64)
    (mq / "chamados" / "senha").unlink()
    (mq / "chamados" / "senha").symlink_to(alvo)
    assert "não é um arquivo comum" in _falha(monkeypatch, jwt, mq, capsys)


def test_pasta_do_rabbitmq_ausente_e_erro(pastas, monkeypatch, capsys):
    jwt, mq = pastas
    assert "não existe" in _falha(monkeypatch, jwt, mq / "nao-existe", capsys)
