"""Erros de negócio e de comunicação do serviço de Chamados."""


class NaoEncontrado(Exception):
    """O recurso pedido não existe (ou o usuário não pode vê-lo)."""


class RegraDeNegocio(Exception):
    """A operação viola uma regra do sistema."""


class SemPermissao(Exception):
    """O usuário está logado, mas não pode fazer esta operação."""


class ServicoIndisponivel(Exception):
    """Um serviço do qual a operação depende não respondeu ou respondeu algo inesperado."""
