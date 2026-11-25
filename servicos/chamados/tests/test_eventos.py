"""Testes da caixa de saída: cada fato vira exatamente um evento, na mesma transação do chamado."""
import json
import uuid
from datetime import datetime

import pytest
from sqlalchemy import func, select

from app.chamados.modelos import Chamado
from app.eventos import servico as eventos
from app.eventos.modelos import EventoSaida
from tests.conftest import eventos_gravados

ABRIR = {"titulo": "PC não liga", "descricao": "Nada acontece", "prioridade": "alta", "ativo_id": 1}


def abrir(cliente, contas, quem="ana"):
    return cliente.post("/chamados", headers=contas[quem]["headers"], json=ABRIR)


def mensagens(sessao):
    with sessao() as db:
        return [(e.chave, json.loads(e.conteudo), e) for e in eventos.listar(db)]


def test_abrir_grava_um_evento_com_o_contrato_completo(cliente, sessao, contas):
    c = abrir(cliente, contas).json()
    [(chave, m, linha)] = mensagens(sessao)
    assert chave == "chamado.aberto" and linha.publicado_em is None and linha.tentativas == 0
    assert set(m) == {"id", "tipo", "versao", "ocorrido_em", "dados"}
    assert m["tipo"] == "ChamadoAberto" and m["versao"] == 1 and m["id"] == linha.evento_id
    uuid.UUID(m["id"])
    datetime.fromisoformat(m["ocorrido_em"])
    assert m["dados"] == {"chamado_id": c["id"], "destinatario_id": contas["ana"]["id"], "prazo_sla": c["prazo_sla"]}


def test_atribuir_e_resolver_gravam_um_evento_cada(cliente, sessao, contas):
    cid = abrir(cliente, contas).json()["id"]
    tec = contas["carla"]["headers"]
    cliente.patch(f"/chamados/{cid}/atribuir", headers=tec, json={"tecnico_id": 4})
    cliente.patch(f"/chamados/{cid}/status", headers=tec, json={"status": "resolvido"})
    assert [(chave, m["tipo"], m["dados"]["destinatario_id"]) for chave, m, _ in mensagens(sessao)] == [
        ("chamado.aberto", "ChamadoAberto", 2),
        ("chamado.atribuido", "ChamadoAtribuido", 4),
        ("chamado.resolvido", "ChamadoResolvido", 2),
    ]


def test_comentar_fechar_e_reabrir_nao_geram_eventos(cliente, sessao, contas):
    # como no monólito: só abertura, atribuição e resolução avisam alguém
    cid = abrir(cliente, contas).json()["id"]
    tec = contas["carla"]["headers"]
    cliente.patch(f"/chamados/{cid}/atribuir", headers=tec, json={"tecnico_id": 4})
    cliente.post(f"/chamados/{cid}/comentarios", headers=tec, json={"texto": "Verificando"})
    cliente.patch(f"/chamados/{cid}/status", headers=tec, json={"status": "resolvido"})
    cliente.patch(f"/chamados/{cid}/status", headers=contas["ana"]["headers"], json={"status": "em_atendimento"})
    cliente.patch(f"/chamados/{cid}/status", headers=tec, json={"status": "resolvido"})
    cliente.patch(f"/chamados/{cid}/status", headers=contas["ana"]["headers"], json={"status": "fechado"})
    tipos = [tipo for tipo, _ in eventos_gravados(sessao)]
    assert tipos == ["ChamadoAberto", "ChamadoAtribuido", "ChamadoResolvido", "ChamadoResolvido"]


def test_operacao_recusada_nao_gera_evento(cliente, sessao, contas):
    cid = abrir(cliente, contas).json()["id"]
    assert cliente.patch(f"/chamados/{cid}/atribuir", headers=contas["ana"]["headers"], json={"tecnico_id": 4}).status_code == 403
    assert cliente.patch(f"/chamados/{cid}/atribuir", headers=contas["carla"]["headers"], json={"tecnico_id": 2}).status_code == 422
    assert [tipo for tipo, _ in eventos_gravados(sessao)] == ["ChamadoAberto"]


def test_rollback_desfaz_chamado_e_evento_juntos(cliente, sessao, contas, monkeypatch):
    abrir(cliente, contas)
    repetido = mensagens(sessao)[0][2].evento_id
    monkeypatch.setattr(eventos, "novo_id", lambda: repetido)  # força o commit a falhar no evento
    r = abrir(cliente, contas)
    assert r.status_code == 409
    with sessao() as db:
        assert db.scalar(select(func.count()).select_from(Chamado)) == 1  # o segundo chamado não ficou
        assert db.scalar(select(func.count()).select_from(EventoSaida)) == 1


def test_falha_ao_gravar_o_evento_nao_deixa_chamado_sem_evento(cliente, sessao, contas, monkeypatch):
    def quebrar(*args, **kwargs):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(eventos, "registrar", quebrar)
    with pytest.raises(RuntimeError):
        abrir(cliente, contas)
    with sessao() as db:
        assert db.scalar(select(func.count()).select_from(Chamado)) == 0


def test_evento_nao_leva_token_email_nem_texto_do_chamado(cliente, sessao, contas):
    abrir(cliente, contas)
    with sessao() as db:
        conteudo = db.scalar(select(EventoSaida.conteudo))
    token = contas["ana"]["headers"]["Authorization"].split()[1]
    for proibido in (token, "Bearer", "PC não liga", "Nada acontece", "@"):
        assert proibido not in conteudo
    assert len(conteudo.encode()) < 1024  # bem abaixo do limite de 8 KB do consumidor


def test_ids_dos_eventos_sao_unicos(cliente, sessao, contas):
    for _ in range(5):
        abrir(cliente, contas)
    ids = [m["id"] for _, m, _ in mensagens(sessao)]
    assert len(set(ids)) == 5


def test_criar_chamado_nao_depende_do_rabbitmq(cliente, sessao, contas):
    # sem broker configurado nos testes: o chamado é criado e o evento fica pendente
    assert abrir(cliente, contas).status_code == 201
    with sessao() as db:
        assert [e.publicado_em for e in eventos.pendentes(db)] == [None]
