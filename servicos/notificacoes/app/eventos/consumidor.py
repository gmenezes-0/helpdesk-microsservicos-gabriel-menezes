"""Consumidor da fila de eventos (Pika 1.5.0, BlockingConnection, numa thread própria).

- ack só depois do commit do aviso no banco;
- mensagem fora do contrato: basic_reject(requeue=False) → fila de mensagens mortas;
- falha temporária: basic_reject(requeue=True). No RabbitMQ 4.4, o reject conta para o
  delivery-limit da fila (5) e o nack não conta (verificado na etapa exploratória): por isso
  o nack nunca é usado, e uma mensagem que sempre falha acaba na fila de mensagens mortas;
- conexão perdida: reconecta com espera crescente (1 s → 30 s); as mensagens sem ack são
  reentregues pelo broker e a deduplicação por evento_id evita aviso repetido.
"""
import threading
import time
import warnings
from functools import partial
from pathlib import Path

import pika
from pika.exceptions import AMQPError

from app.config import (FILA_EVENTOS, PREFETCH, RABBITMQ_HOST, RABBITMQ_PORTA, RABBITMQ_SENHA_ARQUIVO,
                        RABBITMQ_USUARIO, RABBITMQ_VHOST, log)
from app.database import SessionLocal
from app.eventos.processador import Resultado, processar

ESPERA_FALHA_TEMPORARIA = 1.0   # segundos antes de devolver à fila (não reentregar em rajada)
ESPERA_MAXIMA = 30.0


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


def tratar(canal, metodo, propriedades, corpo: bytes, sessoes=SessionLocal, espera=ESPERA_FALHA_TEMPORARIA) -> Resultado:
    """Callback de cada mensagem. Decide entre ack e reject, sempre depois de processar."""
    resultado = processar(corpo, sessoes)
    if resultado in (Resultado.PROCESSADO, Resultado.DUPLICADO):
        canal.basic_ack(delivery_tag=metodo.delivery_tag)
    elif resultado is Resultado.INVALIDO:
        canal.basic_reject(delivery_tag=metodo.delivery_tag, requeue=False)
    else:
        time.sleep(espera)
        canal.basic_reject(delivery_tag=metodo.delivery_tag, requeue=True)
    identificador = str(getattr(propriedades, "message_id", "") or "")[:36]
    log.info("Mensagem %s: %s", identificador or "sem id", resultado.value)
    return resultado


class Consumidor:
    """Mantém o consumo da fila numa thread própria, reconectando quando preciso."""

    def __init__(self, conectar=conectar_rabbitmq, sessoes=SessionLocal):
        self._conectar = conectar
        self._sessoes = sessoes
        self._parar = threading.Event()
        self._conexao = None
        self._canal = None
        self._thread: threading.Thread | None = None
        self.estado = "desconectado"

    def iniciar(self) -> None:
        self._thread = threading.Thread(target=self._executar, name="consumidor-eventos", daemon=True)
        self._thread.start()

    def parar(self, tempo_limite: float = 5) -> None:
        self._parar.set()
        conexao = self._conexao
        if conexao is not None:
            try:
                conexao.add_callback_threadsafe(self._interromper)  # stop_consuming na thread da conexão
            except Exception:  # conexão já fechada
                pass
        if self._thread is not None:
            self._thread.join(tempo_limite)

    def _interromper(self) -> None:
        if self._canal is not None:
            self._canal.stop_consuming()

    def _executar(self) -> None:
        espera = 1.0
        while not self._parar.is_set():
            try:
                self._conexao = self._conectar()
                canal = self._conexao.channel()
                canal.basic_qos(prefetch_count=PREFETCH)
                canal.basic_consume(FILA_EVENTOS, partial(tratar, sessoes=self._sessoes))
                self._canal, self.estado, espera = canal, "conectado", 1.0
                log.info("Consumidor conectado à fila %s", FILA_EVENTOS)
                canal.start_consuming()
            except (AMQPError, OSError) as erro:
                log.warning("Consumidor sem conexão com o RabbitMQ (%s); nova tentativa em %.0f s",
                            type(erro).__name__, espera)
            finally:
                self.estado, self._canal = "desconectado", None
                self._fechar()
            self._parar.wait(espera)
            espera = min(espera * 2, ESPERA_MAXIMA)

    def _fechar(self) -> None:
        conexao, self._conexao = self._conexao, None
        if conexao is not None and conexao.is_open:
            try:
                conexao.close()
            except Exception:
                pass
