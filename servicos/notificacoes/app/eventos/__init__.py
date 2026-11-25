"""Eventos publicados pelo serviço de Chamados e consumidos aqui, pela fila do RabbitMQ.

- esquemas.py: o contrato (versão 1) de cada evento, validado com rigor;
- processador.py: evento → aviso no banco, sem duplicar (testável sem broker);
- consumidor.py: a conexão com o RabbitMQ, com ack só depois do commit.
"""
