# RabbitMQ 4.4.1 Alpine, fixado por versão e digest (validado na etapa exploratória)
FROM rabbitmq:4.4.1-alpine@sha256:33de492005973b8b07803cf447f45150d3d3e470f11bcf45173f5e3b6109150f

# Pasta de dados do uid 10001 (o mesmo dos serviços) com 0700. Na imagem oficial ela é 1777
# (gravável por todos); o volume novo herda este dono e estas permissões.
RUN chown 10001:10001 /var/lib/rabbitmq && chmod 0700 /var/lib/rabbitmq

# Substitui o 10-defaults.conf da imagem, que libera o usuário guest de qualquer endereço
COPY rabbitmq.conf /etc/rabbitmq/conf.d/10-defaults.conf
# Nenhum plugin: a imagem liga o rabbitmq_prometheus (porta HTTP de métricas) por padrão
COPY enabled_plugins /etc/rabbitmq/enabled_plugins

# Roda sem root: com --user, o entrypoint oficial não tenta trocar dono de arquivos
USER 10001:10001

# Nome do nó fixo (independe do hostname do contêiner) e Erlang (EPMD e clustering)
# escutando só no localhost: na rede fica aberta apenas a porta AMQP 5672
ENV RABBITMQ_NODENAME=rabbit@localhost \
    ERL_EPMD_ADDRESS=127.0.0.1 \
    RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS="-kernel inet_dist_use_interface {127,0,0,1}"

HEALTHCHECK --interval=10s --timeout=15s --start-period=30s --retries=5 \
    CMD ["rabbitmq-diagnostics", "-q", "check_port_connectivity"]
