"""Eventos do serviço de Chamados, publicados no RabbitMQ pelo padrão de caixa de saída.

- servico.py: grava o evento na tabela eventos_saida, na mesma transação do chamado
  (ou os dois são gravados, ou nenhum);
- publicador.py: numa thread própria, publica os pendentes com confirmação do broker
  e só então os marca como publicados. Com o RabbitMQ fora, eles esperam no banco.

A resposta HTTP nunca espera pelo RabbitMQ.
"""
