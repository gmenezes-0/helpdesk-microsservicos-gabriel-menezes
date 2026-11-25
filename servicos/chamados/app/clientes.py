"""Clientes HTTP para os serviços de Usuários e Inventário.

Substituem as chamadas de função do monólito (`usuarios.servico.obter_tecnico`
e `inventario.servico.obter`). Regras:

- o cabeçalho Authorization de quem fez o pedido é repassado como veio;
- cada chamada tem tempo limite de HTTP_TIMEOUT_SEGUNDOS (3 s por padrão);
- 404 do outro serviço vira NaoEncontrado (404 aqui, com a mesma mensagem do monólito);
- sem resposta, tempo esgotado, erro 5xx, token recusado lá (401/403) ou resposta
  fora do esperado viram ServicoIndisponivel (503). Nada disso é tratado como regra
  de negócio, e a mensagem é genérica: os detalhes ficam só no log.
"""
import logging
from threading import Lock

import httpx

from app.config import HTTP_TIMEOUT_SEGUNDOS, INVENTARIO_URL, USUARIOS_URL
from app.erros import NaoEncontrado, RegraDeNegocio, ServicoIndisponivel

log = logging.getLogger("helpdesk.chamados.clientes")

_cliente: httpx.Client | None = None
_trava = Lock()


def novo_cliente(**opcoes) -> httpx.Client:
    # trust_env=False: chamadas internas não passam por proxies configurados no ambiente
    return httpx.Client(timeout=HTTP_TIMEOUT_SEGUNDOS, follow_redirects=False, trust_env=False, **opcoes)


def cliente() -> httpx.Client:
    """Cliente HTTP compartilhado (reaproveita conexões entre requisições)."""
    global _cliente
    with _trava:
        if _cliente is None:
            _cliente = novo_cliente()
        return _cliente


def usar(novo: httpx.Client | None) -> None:
    """Troca o cliente HTTP (os testes usam um cliente com respostas simuladas)."""
    global _cliente
    with _trava:
        antigo, _cliente = _cliente, novo
    if antigo is not None and antigo is not novo:
        antigo.close()


def fechar() -> None:
    usar(None)


def _indisponivel(servico: str) -> ServicoIndisponivel:
    return ServicoIndisponivel(f"O serviço de {servico} está indisponível no momento. Tente novamente em instantes.")


def _consultar(servico: str, base: str, caminho: str, autorizacao: str) -> dict | None:
    """GET no outro serviço: devolve o JSON, None se o recurso não existe (404) ou lança ServicoIndisponivel."""
    try:
        resposta = cliente().get(f"{base}{caminho}", headers={"Authorization": autorizacao})
    except httpx.TimeoutException:
        log.warning("Tempo limite esgotado ao chamar o serviço de %s (%s)", servico, caminho)
        raise _indisponivel(servico) from None
    except httpx.HTTPError as erro:  # conexão recusada, nome não encontrado, conexão caiu...
        log.warning("Falha ao chamar o serviço de %s (%s): %s", servico, caminho, type(erro).__name__)
        raise _indisponivel(servico) from None

    if resposta.status_code == 404:
        return None
    if resposta.status_code != 200:
        log.error("Resposta inesperada do serviço de %s (%s): HTTP %d", servico, caminho, resposta.status_code)
        raise _indisponivel(servico)
    try:
        dados = resposta.json()
    except ValueError:
        dados = None
    if not isinstance(dados, dict):
        log.error("Resposta do serviço de %s (%s) não é um objeto JSON", servico, caminho)
        raise _indisponivel(servico)
    return dados


def obter_ativo(ativo_id: int, autorizacao: str) -> dict:
    """Confere no Inventário (GET /ativos/{id}) que o equipamento existe."""
    dados = _consultar("inventário", INVENTARIO_URL, f"/ativos/{ativo_id}", autorizacao)
    if dados is None:
        raise NaoEncontrado(f"Ativo {ativo_id} não encontrado.")
    if dados.get("id") != ativo_id:
        log.error("O serviço de inventário devolveu outro ativo para o id %d", ativo_id)
        raise _indisponivel("inventário")
    return dados


def obter_tecnico(usuario_id: int, autorizacao: str) -> dict:
    """Confere em Usuários (GET /usuarios/{id}) que a pessoa existe e é técnica."""
    dados = _consultar("usuários", USUARIOS_URL, f"/usuarios/{usuario_id}", autorizacao)
    if dados is None:
        raise NaoEncontrado(f"Usuário {usuario_id} não encontrado.")
    if dados.get("id") != usuario_id or not isinstance(dados.get("perfil"), str):
        log.error("O serviço de usuários devolveu dados inesperados para o id %d", usuario_id)
        raise _indisponivel("usuários")
    if dados["perfil"] != "tecnico":
        raise RegraDeNegocio(f"Usuário {usuario_id} não é técnico.")
    return dados
