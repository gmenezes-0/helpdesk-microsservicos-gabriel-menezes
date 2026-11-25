"""Publicador da caixa de saída (Pika 1.5.0, BlockingConnection, numa thread própria).

A cada intervalo, lê os eventos pendentes e publica cada um na exchange helpdesk.eventos:
- com publisher confirms: basic_publish só retorna depois que o broker aceitou a mensagem;
- com mandatory: uma mensagem sem fila ligada volta como erro, em vez de sumir;
- persistente (delivery_mode 2), com message_id = id do evento.

Só depois da confirmação o evento é marcado como publicado. Se o processo cair entre a
confirmação e a marcação, o evento sai de novo: o consumidor descarta a duplicata pelo id.
Com o RabbitMQ fora, os eventos esperam no banco e a conexão é refeita com espera crescente.
"""
import threading
import warnings
from datetime import datetime
from pathlib import Path

import pika
from pika.exceptions import AMQPError, NackError, UnroutableError
from sqlalchemy.exc import SQLAlchemyError

from app.config import (EXCHANGE_EVENTOS, PUBLICADOR_INTERVALO_SEGUNDOS, RABBITMQ_HOST, RABBITMQ_PORTA,
                        RABBITMQ_SENHA_ARQUIVO, RABBITMQ_USUARIO, RABBITMQ_VHOST, log)
from app.database import SessionLocal
from app.eventos import servico

LOTE = 50
ESPERA_MAXIMA = 30.0
ESPERA_COM_RECUSA = 5.0  # broker recusou ou não roteou: não insistir a cada segundo


def conectar_rabbitmq() -> pika.BlockingConnection:
    # A senha vem só do arquivo gerado (volume somente leitura), nunca do ambiente nem do código
    senha = Path(RABBITMQ_SENHA_ARQUIVO).read_text(encoding="utf-8").strip()
    parametros = pika.ConnectionParameters(
        host=RABBITMQ_HOST, port=RABBITMQ_PORTA, virtual_host=RABBITMQ_VHOST,
        credentials=pika.PlainCredentials(RABBITMQ_USUARIO, senha),
        heartbeat=30, blocked_connection_timeout=30, connection_attempts=1, socket_timeout=5,
    )
    with warnings.catch_warnings():
        # Decisão do projeto: BlockingConnection (obsoleta na 1.5, ainda suportada até a 2.0), isolada neste módulo
        warnings.simplefilter("ignore", DeprecationWarning)
        return pika.BlockingConnection(parametros)


def propriedades(evento) -> pika.BasicProperties:
    return pika.BasicProperties(content_type="application/json", delivery_mode=pika.DeliveryMode.Persistent,
                                message_id=evento.evento_id, type=evento.tipo, app_id="chamados")


class Publicador:
    def __init__(self, conectar=conectar_rabbitmq, sessoes=SessionLocal, intervalo=PUBLICADOR_INTERVALO_SEGUNDOS):
        self._conectar = conectar
        self._sessoes = sessoes
        self._intervalo = intervalo
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self.estado = "desconectado"

    def iniciar(self) -> None:
        self._thread = threading.Thread(target=self._executar, name="publicador-eventos", daemon=True)
        self._thread.start()

    def parar(self, tempo_limite: float = 5) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(tempo_limite)

    def publicar_pendentes(self, canal) -> tuple[int, int]:
        """Publica um lote de pendentes. Devolve (publicados, recusados). Erro de conexão sobe."""
        publicados = recusados = 0
        with self._sessoes() as db:
            for evento in servico.pendentes(db, LOTE):
                if self._parar.is_set():
                    break
                try:
                    canal.basic_publish(EXCHANGE_EVENTOS, evento.chave, evento.conteudo.encode("utf-8"),
                                        propriedades(evento), mandatory=True)
                except (UnroutableError, NackError) as erro:  # o broker não aceitou ou não roteou
                    evento.tentativas, evento.ultimo_erro = evento.tentativas + 1, type(erro).__name__
                    db.commit()
                    recusados += 1
                    log.warning("Evento %s não publicado (%s); fica pendente", evento.evento_id, type(erro).__name__)
                    continue
                except (AMQPError, OSError) as erro:  # conexão caiu: registra e deixa o laço reconectar
                    evento.tentativas, evento.ultimo_erro = evento.tentativas + 1, type(erro).__name__
                    db.commit()
                    raise
                evento.publicado_em, evento.ultimo_erro = datetime.now(), None
                evento.tentativas += 1
                db.commit()  # só depois da confirmação do broker
                publicados += 1
        return publicados, recusados

    def _executar(self) -> None:
        espera = 1.0
        while not self._parar.is_set():
            conexao = None
            try:
                conexao = self._conectar()
                canal = conexao.channel()
                canal.confirm_delivery()
                self.estado, espera = "conectado", 1.0
                log.info("Publicador conectado ao RabbitMQ")
                while not self._parar.is_set():
                    _, recusados = self.publicar_pendentes(canal)
                    conexao.sleep(ESPERA_COM_RECUSA if recusados else self._intervalo)  # mantém os heartbeats
            except (AMQPError, OSError, SQLAlchemyError) as erro:
                log.warning("Publicador sem conexão com o RabbitMQ (%s); eventos seguem pendentes; "
                            "nova tentativa em %.0f s", type(erro).__name__, espera)
            finally:
                self.estado = "desconectado"
                if conexao is not None and getattr(conexao, "is_open", False):
                    try:
                        conexao.close()
                    except Exception:
                        pass
            self._parar.wait(espera)
            espera = min(espera * 2, ESPERA_MAXIMA)
