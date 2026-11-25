"""Testes do consumidor: ack só depois do commit, reject (nunca nack) e reconexão."""
import threading

from pika.exceptions import AMQPConnectionError
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.eventos.consumidor import Consumidor, tratar
from app.eventos.processador import Resultado
from app.notificacoes.modelos import Notificacao
from tests.conftest import CanalFalso, Metodo, Propriedades, evento


def total(sessao):
    with sessao() as db:
        return db.scalar(select(func.count()).select_from(Notificacao))


def test_ack_so_depois_do_commit(sessao):
    vistos = []
    canal = CanalFalso(ao_ack=lambda: vistos.append(total(sessao)))  # quantos avisos existem na hora do ack
    assert tratar(canal, Metodo(5), Propriedades(), evento(), sessoes=sessao) is Resultado.PROCESSADO
    assert canal.acoes == [("ack", 5)] and vistos == [1]


def test_duplicado_recebe_ack_sem_novo_aviso(sessao):
    corpo, canal = evento(), CanalFalso()
    tratar(canal, Metodo(1), Propriedades(), corpo, sessoes=sessao)
    tratar(canal, Metodo(2), Propriedades(), corpo, sessoes=sessao)
    assert canal.acoes == [("ack", 1), ("ack", 2)] and total(sessao) == 1


def test_invalida_vai_para_mensagens_mortas_sem_requeue(sessao):
    canal = CanalFalso()
    assert tratar(canal, Metodo(3), Propriedades(), b"{lixo", sessoes=sessao) is Resultado.INVALIDO
    assert canal.acoes == [("reject", 3, False)] and total(sessao) == 0


def test_falha_temporaria_volta_para_a_fila_com_reject(sessao, monkeypatch):
    from sqlalchemy.orm import Session
    monkeypatch.setattr(Session, "commit", lambda self: (_ for _ in ()).throw(OperationalError("x", {}, Exception())))
    canal = CanalFalso()  # basic_nack levanta erro no canal falso
    assert tratar(canal, Metodo(4), Propriedades(), evento(), sessoes=sessao, espera=0) is Resultado.FALHA_TEMPORARIA
    assert canal.acoes == [("reject", 4, True)]


def test_reentrega_depois_da_falha_grava_uma_vez(sessao, monkeypatch):
    from sqlalchemy.orm import Session
    corpo, canal = evento(), CanalFalso()
    original = Session.commit
    monkeypatch.setattr(Session, "commit", lambda self: (_ for _ in ()).throw(OperationalError("x", {}, Exception())))
    tratar(canal, Metodo(1), Propriedades(), corpo, sessoes=sessao, espera=0)
    monkeypatch.setattr(Session, "commit", original)
    tratar(canal, Metodo(2), Propriedades(), corpo, sessoes=sessao, espera=0)  # o broker reentregou
    assert canal.acoes == [("reject", 1, True), ("ack", 2)] and total(sessao) == 1


def test_log_mostra_so_o_id_da_mensagem(sessao, caplog):
    caplog.set_level("INFO")
    tratar(CanalFalso(), Metodo(), Propriedades("abc-123"), evento(destinatario_id=99), sessoes=sessao)
    assert "abc-123" in caplog.text and "Seu chamado" not in caplog.text


# ---------- conexão ----------

class ConexaoFalsa:
    def __init__(self, ao_consumir):
        self.is_open, self._ao_consumir, self.fechada = True, ao_consumir, False
        self.canal = None

    def channel(self):
        conexao = self

        class Canal:
            def basic_qos(self, prefetch_count):
                self.prefetch = prefetch_count

            def basic_consume(self, fila, callback):
                self.fila, self.callback = fila, callback

            def start_consuming(self):
                conexao._ao_consumir(self)

            def stop_consuming(self):
                pass

        self.canal = Canal()
        return self.canal

    def add_callback_threadsafe(self, funcao):
        funcao()

    def close(self):
        self.is_open, self.fechada = False, True


def test_reconecta_depois_de_falha_e_consome_a_fila_certa(sessao):
    tentativas, pronto = [], threading.Event()
    conexoes = []

    def conectar():
        tentativas.append(1)
        if len(tentativas) == 1:
            raise AMQPConnectionError("broker fora")

        def consumir(canal):
            pronto.set()
            consumidor._parar.wait(5)

        conexoes.append(ConexaoFalsa(consumir))
        return conexoes[-1]

    consumidor = Consumidor(conectar=conectar, sessoes=sessao)
    consumidor.iniciar()
    assert pronto.wait(5)  # tentou de novo depois de ~1 s
    assert consumidor.estado == "conectado"
    canal = conexoes[-1].canal
    assert canal.fila == "notificacoes.eventos" and canal.prefetch == 10
    consumidor.parar()
    assert consumidor.estado == "desconectado" and conexoes[-1].fechada and len(tentativas) == 2


def test_senha_ausente_nao_derruba_o_servico(sessao, monkeypatch, caplog, tmp_path):
    from app.eventos import consumidor as modulo
    monkeypatch.setattr(modulo, "RABBITMQ_SENHA_ARQUIVO", str(tmp_path / "nao-existe"))
    c = Consumidor(sessoes=sessao)
    c.iniciar()
    c.parar(tempo_limite=3)
    assert c.estado == "desconectado" and "FileNotFoundError" in caplog.text
