"""Testes do processamento dos eventos: textos, deduplicação, contrato e falhas (sem broker)."""
import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.eventos.processador import Resultado, processar
from app.notificacoes.modelos import Notificacao
from tests.conftest import evento


def avisos(sessao):
    with sessao() as db:
        return [(n.tipo, n.destinatario_id, n.mensagem) for n in db.scalars(select(Notificacao).order_by(Notificacao.id))]


# ---------- os três eventos ----------

@pytest.mark.parametrize("tipo,destinatario,texto", [
    ("ChamadoAberto", 2, "Seu chamado #7 foi aberto. Prazo: 25/11 22:03."),
    ("ChamadoAtribuido", 4, "O chamado #7 foi atribuído a você."),
    ("ChamadoResolvido", 2, "Seu chamado #7 foi resolvido. Confirme se está tudo certo."),
])
def test_cada_evento_vira_o_mesmo_aviso_do_monolito(sessao, tipo, destinatario, texto):
    assert processar(evento(tipo, destinatario_id=destinatario), sessao) is Resultado.PROCESSADO
    assert avisos(sessao) == [(tipo, destinatario, texto)]


def test_data_do_aviso_e_a_do_fato_no_chamados(sessao):
    processar(evento(ocorrido_em="2026-11-25T14:03:00"), sessao)
    with sessao() as db:
        n = db.scalar(select(Notificacao))
    assert n.criada_em.isoformat() == "2026-11-25T14:03:00" and n.recebida_em >= n.criada_em


def test_data_com_fuso_e_convertida_para_hora_local(sessao):
    assert processar(evento(ocorrido_em="2026-11-25T14:03:00+00:00"), sessao) is Resultado.PROCESSADO


# ---------- duplicadas e reprocessamento ----------

def test_evento_repetido_gera_um_aviso_so(sessao):
    corpo = evento()
    assert processar(corpo, sessao) is Resultado.PROCESSADO
    assert processar(corpo, sessao) is Resultado.DUPLICADO
    assert processar(corpo, sessao) is Resultado.DUPLICADO
    assert len(avisos(sessao)) == 1


def test_mesmo_id_com_conteudo_diferente_tambem_e_duplicado(sessao):
    # o id do evento é a identidade: uma reentrega nunca cria um segundo aviso
    processar(evento(id="8f14e45f-ceea-467f-a0e6-1e3a0c8b3c01"), sessao)
    assert processar(evento("ChamadoResolvido", id="8f14e45f-ceea-467f-a0e6-1e3a0c8b3c01"), sessao) is Resultado.DUPLICADO
    assert len(avisos(sessao)) == 1


def test_falha_do_banco_e_temporaria_e_nada_e_gravado(sessao, monkeypatch):
    from sqlalchemy.orm import Session

    def falhar(self):
        raise OperationalError("COMMIT", {}, Exception("database is locked"))

    corpo = evento()
    monkeypatch.setattr(Session, "commit", falhar)
    assert processar(corpo, sessao) is Resultado.FALHA_TEMPORARIA
    monkeypatch.undo()
    assert avisos(sessao) == []
    # reprocessamento: quando o banco volta, a mesma mensagem é gravada uma vez
    assert processar(corpo, sessao) is Resultado.PROCESSADO
    assert processar(corpo, sessao) is Resultado.DUPLICADO
    assert len(avisos(sessao)) == 1


def test_banco_inacessivel_e_falha_temporaria(sessao):
    def sem_banco():
        raise OperationalError("connect", {}, Exception("unable to open database file"))
    assert processar(evento(), sem_banco) is Resultado.FALHA_TEMPORARIA


# ---------- contrato ----------

def _sem(campo):
    m = evento(bruto=True)
    m.pop(campo)
    return json.dumps(m).encode()


def _dados(**mudancas):
    m = evento(bruto=True)
    m["dados"] = {**m["dados"], **mudancas}
    return json.dumps(m).encode()


INVALIDAS = {
    "não é JSON": b"isto nao e json",
    "não é UTF-8": b"\xff\xfe\x00{",
    "lista em vez de objeto": b"[1, 2]",
    "vazia": b"",
    "tipo desconhecido": evento("ChamadoApagado"),
    "versão 2": evento(versao=2),
    "versão como texto": evento(versao="1"),
    "versão como booleano": evento(versao=True),
    "campo extra no envelope": evento(token="eyJhbGciOi..."),
    "sem id": _sem("id"),
    "sem dados": _sem("dados"),
    "sem ocorrido_em": _sem("ocorrido_em"),
    "id que não é UUID": evento(id="123"),
    "data inválida": evento(ocorrido_em="ontem"),
    "campo extra nos dados": _dados(email="ana@empresa.com"),
    "chamado_id como texto": _dados(chamado_id="7"),
    "chamado_id negativo": _dados(chamado_id=-1),
    "destinatario_id zero": _dados(destinatario_id=0),
    "destinatario_id enorme": _dados(destinatario_id=2**40),
    "destinatario_id fracionário": _dados(destinatario_id=2.5),
    "aberto sem prazo_sla": json.dumps({**evento(bruto=True), "dados": {"chamado_id": 7, "destinatario_id": 2}}).encode(),
    "atribuído com prazo_sla": json.dumps({**evento("ChamadoAtribuido", bruto=True),
                                           "dados": {"chamado_id": 7, "destinatario_id": 4, "prazo_sla": "2026-11-25T22:03:00"}}).encode(),
    "grande demais": json.dumps({**evento(bruto=True), "lixo": "x" * 9000}).encode(),
}


@pytest.mark.parametrize("motivo", INVALIDAS)
def test_mensagem_fora_do_contrato_e_invalida_e_nao_grava_nada(sessao, motivo):
    assert processar(INVALIDAS[motivo], sessao) is Resultado.INVALIDO, motivo
    assert avisos(sessao) == []


def test_mensagem_grande_e_recusada_antes_de_ler_o_json(sessao, monkeypatch):
    from app.eventos import esquemas
    monkeypatch.setattr(esquemas._adaptador, "validate_json", lambda *a, **k: pytest.fail("não deveria ler"))
    assert processar(b"{" + b" " * 9000 + b"}", sessao) is Resultado.INVALIDO


def test_log_de_mensagem_invalida_nao_mostra_o_conteudo(sessao, caplog):
    processar(_dados(email="segredo-que-nao-pode-vazar@empresa.com"), sessao)
    assert "segredo-que-nao-pode-vazar" not in caplog.text and "recusada" in caplog.text


def test_contagem_por_destinatario(sessao):
    for destinatario in (2, 2, 4):
        processar(evento(destinatario_id=destinatario), sessao)
    with sessao() as db:
        assert db.scalar(select(func.count()).where(Notificacao.destinatario_id == 2)) == 2
