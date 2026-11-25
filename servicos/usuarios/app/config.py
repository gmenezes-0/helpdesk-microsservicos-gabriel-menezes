"""Configurações do serviço de Usuários, lidas das variáveis de ambiente."""
import logging
import os
import secrets
from pathlib import Path

log = logging.getLogger("helpdesk.usuarios")

NOME_SERVICO = "usuarios"

# Banco próprio do serviço: nenhum outro serviço lê ou grava nele.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./usuarios.db")

TAMANHO_MINIMO_SEGREDO = 32


class SegredoInvalido(RuntimeError):
    """O segredo JWT configurado não pode ser usado."""


def carregar_segredo() -> str:
    """Devolve o segredo que assina os tokens JWT.

    Ordem de procura:
    1. JWT_SEGREDO: o próprio segredo na variável de ambiente;
    2. JWT_SEGREDO_ARQUIVO: caminho de um arquivo com o segredo (no Docker Compose,
       um volume compartilhado entre os serviços, gerado automaticamente);
    3. nenhum dos dois: segredo aleatório, válido só para este processo
       (serve para rodar o serviço sozinho; os logins expiram ao reiniciar).

    Um arquivo configurado que não existe ou tem segredo curto é erro de configuração:
    o serviço não sobe, para nunca assinar tokens com um segredo diferente dos outros.
    """
    segredo = os.getenv("JWT_SEGREDO") or ""
    arquivo = os.getenv("JWT_SEGREDO_ARQUIVO") or ""

    if not segredo and arquivo:
        try:
            segredo = Path(arquivo).read_text(encoding="utf-8").strip()
        except OSError as erro:
            raise SegredoInvalido(f"Não foi possível ler o segredo JWT em {arquivo}.") from erro
        if len(segredo) < TAMANHO_MINIMO_SEGREDO:
            raise SegredoInvalido(f"O segredo JWT em {arquivo} tem menos de {TAMANHO_MINIMO_SEGREDO} caracteres.")
        return segredo

    if len(segredo) < TAMANHO_MINIMO_SEGREDO:
        if segredo:
            log.warning("JWT_SEGREDO tem menos de %d caracteres; usando um segredo aleatório.", TAMANHO_MINIMO_SEGREDO)
        else:
            log.warning("JWT_SEGREDO não definido; usando um segredo aleatório (só para este processo).")
        segredo = secrets.token_urlsafe(48)
    return segredo


JWT_SEGREDO = carregar_segredo()
JWT_ALGORITMO = "HS256"
JWT_EMISSOR = "helpdesk-ti"
TOKEN_MINUTOS = int(os.getenv("TOKEN_MINUTOS", "60"))

# Proteção contra tentativas de adivinhar senhas
LOGIN_MAX_FALHAS = int(os.getenv("LOGIN_MAX_FALHAS", "5"))
LOGIN_JANELA_SEGUNDOS = int(os.getenv("LOGIN_JANELA_SEGUNDOS", "300"))

# Tamanho máximo do corpo de uma requisição (em bytes)
TAMANHO_MAXIMO_REQUISICAO = 64 * 1024

DOCS_ATIVA = os.getenv("DOCS", "1") == "1"
