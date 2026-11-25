"""Configurações do API Gateway, lidas das variáveis de ambiente.

O gateway não tem banco e não precisa do segredo JWT: quem confere o token
é cada serviço. Aqui ficam só os endereços dos serviços e os limites.
"""
import logging
import os

log = logging.getLogger("helpdesk.gateway")

NOME_SERVICO = "gateway"

# Endereços dos serviços. Dentro do Docker Compose, cada serviço é chamado pelo nome.
SERVICOS = {
    "usuarios": os.getenv("USUARIOS_URL", "http://usuarios:8000").rstrip("/"),
    "inventario": os.getenv("INVENTARIO_URL", "http://inventario:8000").rstrip("/"),
    "chamados": os.getenv("CHAMADOS_URL", "http://chamados:8000").rstrip("/"),
    "notificacoes": os.getenv("NOTIFICACOES_URL", "http://notificacoes:8000").rstrip("/"),
}

# Nome de cada serviço nas mensagens de erro
NOMES = {"usuarios": "usuários", "inventario": "inventário", "chamados": "chamados", "notificacoes": "notificações"}

# Qual serviço atende cada prefixo de rota
ROTAS = {
    "/auth": "usuarios",
    "/usuarios": "usuarios",
    "/ativos": "inventario",
    "/chamados": "chamados",
    "/notificacoes": "notificacoes",
}

# Tempo limite para repassar uma requisição. Fica acima do tempo limite que o serviço
# de Chamados usa para chamar os outros (3 s), para que o 503 dele chegue até a tela.
TIMEOUT_MAXIMO_SEGUNDOS = 10.0
TIMEOUT_SEGUNDOS = float(os.getenv("GATEWAY_TIMEOUT_SEGUNDOS", str(TIMEOUT_MAXIMO_SEGUNDOS)))
if not 0 < TIMEOUT_SEGUNDOS <= TIMEOUT_MAXIMO_SEGUNDOS:
    log.warning("GATEWAY_TIMEOUT_SEGUNDOS deve ficar entre 0 e %.0f; usando %.0f.", TIMEOUT_MAXIMO_SEGUNDOS, TIMEOUT_MAXIMO_SEGUNDOS)
    TIMEOUT_SEGUNDOS = TIMEOUT_MAXIMO_SEGUNDOS

# Tempo limite de cada checagem de saúde (curto: a rota /saude deve responder rápido)
SAUDE_TIMEOUT_SEGUNDOS = float(os.getenv("SAUDE_TIMEOUT_SEGUNDOS", "2"))

# Tamanho máximo do corpo de uma requisição (em bytes)
TAMANHO_MAXIMO_REQUISICAO = 64 * 1024

DOCS_ATIVA = os.getenv("DOCS", "1") == "1"
