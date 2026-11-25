"""Validação dos tokens JWT emitidos pelo serviço de Usuários.

O serviço de Usuários assina {"sub", "perfil", "iat", "exp", "iss"} com HS256.
Aqui o token só é aceito se a assinatura, o algoritmo, o emissor e a validade
estiverem corretos e se todas essas claims existirem. Como o perfil está dentro
do conteúdo assinado, quem chama não consegue trocá-lo sem invalidar o token.
"""
from dataclasses import dataclass

import jwt

from app.config import JWT_ALGORITMO, JWT_EMISSOR, JWT_SEGREDO

PERFIS = frozenset({"solicitante", "tecnico", "admin"})


class TokenInvalido(Exception):
    pass


@dataclass(frozen=True)
class UsuarioToken:
    """Quem está logado, segundo o token. Não há consulta ao banco de usuários."""
    id: int
    perfil: str


def ler(token: str) -> UsuarioToken:
    """Devolve o usuário do token, ou lança TokenInvalido."""
    try:
        dados = jwt.decode(
            token, JWT_SEGREDO, algorithms=[JWT_ALGORITMO], issuer=JWT_EMISSOR,
            options={"require": ["exp", "iat", "sub", "iss", "perfil"]},
        )
        usuario_id = int(dados["sub"])
    except (jwt.PyJWTError, ValueError, TypeError) as erro:
        raise TokenInvalido() from erro
    perfil = dados["perfil"]
    if usuario_id <= 0 or not isinstance(perfil, str) or perfil not in PERFIS:
        raise TokenInvalido()
    return UsuarioToken(id=usuario_id, perfil=perfil)
