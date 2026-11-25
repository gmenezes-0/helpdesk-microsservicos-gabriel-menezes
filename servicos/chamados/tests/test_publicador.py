"""Testes do publicador da caixa de saída, com um canal falso no lugar do RabbitMQ."""
import json
import threading
import time

import pytest
from pika.exceptions import AMQPConnectionError, ConnectionClosedByBroker, NackError, UnroutableError

from app.eventos import servico as eventos
from app.eventos.publicador import Publicador
from tests.conftest import eventos_gravados

ABRIR = {"titulo": "PC não liga", "descricao": "Nada acontece", "prioridade": "alta"}


class CanalFalso:
    """Registra cada publicação. `falhas` diz o que fazer com a n-ésima tentativa."""

    def __init__(self, falhas=None):
        self.publicados, self.confirmacao = [], False
        self.falhas = dict(falhas or {})
        self._n = 0

    def confirm_delivery(self):
        self.confirmacao = True

    def basic_publish(self, exchange, routing_key, body, properties, mandatory):
        self._n += 1
        falha = self.falhas.get(self._n)
        if falha:
            raise falha
        self.publicados.append({"exchange": exchange, "chave": routing_key, "corpo": json.loads(body),
                                "props": properties, "mandatory": mandatory})


def criar(cliente, contas, n=1):
    for _ in range(n):
        assert cliente.post("/chamados", headers=contas["ana"]["headers"], json=ABRIR).status_code == 201


def pendentes(sessao):
    with sessao() as db:
        return [(e.tentativas, e.ultimo_erro) for e in eventos.pendentes(db)]


def test_publica_com_confirmacao_mandatory_e_marca_como_publicado(cliente, sessao, contas):
    criar(cliente, contas, 2)
    canal = CanalFalso()
    assert Publicador(sessoes=sessao).publicar_pendentes(canal) == (2, 0)
    assert pendentes(sessao) == []
    p = canal.publicados[0]
    assert p["exchange"] == "helpdesk.eventos" and p["chave"] == "chamado.aberto" and p["mandatory"] is True
    assert p["props"].delivery_mode == 2 and p["props"].content_type == "application/json"
    assert p["props"].message_id == p["corpo"]["id"] and p["props"].type == "ChamadoAberto"
    assert [m["corpo"]["dados"]["chamado_id"] for m in canal.publicados] == [1, 2]  # na ordem de gravação


def test_publicado_nao_sai_de_novo(cliente, sessao, contas):
    criar(cliente, contas)
    publicador, canal = Publicador(sessoes=sessao), CanalFalso()
    publicador.publicar_pendentes(canal)
    assert publicador.publicar_pendentes(canal) == (0, 0) and len(canal.publicados) == 1


@pytest.mark.parametrize("erro", [UnroutableError([]), NackError([])])
def test_recusado_pelo_broker_fica_pendente_e_os_outros_seguem(cliente, sessao, contas, erro):
    criar(cliente, contas, 2)
    canal = CanalFalso(falhas={1: erro})
    assert Publicador(sessoes=sessao).publicar_pendentes(canal) == (1, 1)
    assert pendentes(sessao) == [(1, type(erro).__name__)]
    # na próxima rodada, o pendente é publicado
    assert Publicador(sessoes=sessao).publicar_pendentes(CanalFalso()) == (1, 0)
    assert pendentes(sessao) == []


def test_conexao_caindo_no_meio_mantem_o_evento_pendente(cliente, sessao, contas):
    criar(cliente, contas, 3)
    canal = CanalFalso(falhas={2: ConnectionClosedByBroker(320, "CONNECTION_FORCED")})
    with pytest.raises(ConnectionClosedByBroker):
        Publicador(sessoes=sessao).publicar_pendentes(canal)
    assert len(canal.publicados) == 1
    assert pendentes(sessao) == [(1, "ConnectionClosedByBroker"), (0, None)]


def test_queda_entre_confirmacao_e_marcacao_republica_o_mesmo_id(cliente, sessao, contas, monkeypatch):
    # se o processo cai depois da confirmação e antes do commit, o evento sai de novo, com o mesmo id:
    # o consumidor descarta a duplicata (evento_id único no banco de Notificações)
    criar(cliente, contas)
    from sqlalchemy.orm import Session
    original = Session.commit
    monkeypatch.setattr(Session, "commit", lambda self: (_ for _ in ()).throw(RuntimeError("queda")))
    canal = CanalFalso()
    with pytest.raises(RuntimeError):
        Publicador(sessoes=sessao).publicar_pendentes(canal)
    monkeypatch.setattr(Session, "commit", original)
    Publicador(sessoes=sessao).publicar_pendentes(canal)
    assert len(canal.publicados) == 2 and canal.publicados[0]["corpo"]["id"] == canal.publicados[1]["corpo"]["id"]


# ---------- laço de conexão ----------

class ConexaoFalsa:
    def __init__(self, canal):
        self.canal, self.is_open = canal, True

    def channel(self):
        return self.canal

    def sleep(self, segundos):
        time.sleep(min(segundos, 0.05))

    def close(self):
        self.is_open = False


def test_rabbitmq_fora_deixa_pendente_e_entrega_quando_volta(cliente, sessao, contas):
    criar(cliente, contas)
    canal, tentativas, entregue = CanalFalso(), [], threading.Event()

    def conectar():
        tentativas.append(1)
        if len(tentativas) == 1:
            raise AMQPConnectionError("broker fora")
        return ConexaoFalsa(canal)

    publicador = Publicador(conectar=conectar, sessoes=sessao, intervalo=0.05)
    publicador.iniciar()
    for _ in range(100):
        if canal.publicados:
            entregue.set()
            break
        time.sleep(0.05)
    publicador.parar()
    assert entregue.is_set() and canal.confirmacao and len(tentativas) == 2
    assert pendentes(sessao) == []


def test_criar_chamado_nao_espera_o_rabbitmq(cliente, sessao, contas):
    trava = threading.Event()

    def conectar_que_trava():
        trava.wait(10)  # simula um broker que não responde
        raise AMQPConnectionError("sem resposta")

    publicador = Publicador(conectar=conectar_que_trava, sessoes=sessao)
    publicador.iniciar()
    inicio = time.monotonic()
    criar(cliente, contas)
    assert time.monotonic() - inicio < 2
    assert [tipo for tipo, _ in eventos_gravados(sessao)] == ["ChamadoAberto"]
    trava.set()
    publicador.parar()


def test_senha_ausente_nao_derruba_o_servico(sessao, monkeypatch, caplog, tmp_path):
    from app.eventos import publicador as modulo
    monkeypatch.setattr(modulo, "RABBITMQ_SENHA_ARQUIVO", str(tmp_path / "nao-existe"))
    p = Publicador(sessoes=sessao)
    p.iniciar()
    time.sleep(0.2)
    p.parar(tempo_limite=3)
    assert p.estado == "desconectado" and "FileNotFoundError" in caplog.text
