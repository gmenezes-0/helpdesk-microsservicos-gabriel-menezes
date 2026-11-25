"""Cria os usuários de exemplo quando o banco está vazio.

Uso apenas em aula: todos os usuários de exemplo têm a mesma senha
(variável SENHA_EXEMPLO). Em produção, rode com DADOS_EXEMPLO=0.

A ordem de criação é a mesma do monólito, então os ids também são:
1 Admin TI, 2 Ana, 3 Bruno, 4 Carla, 5 Diego. Os dados de exemplo dos
outros serviços (chamados) usam estes ids.
"""
import os

from sqlalchemy.orm import Session

from app.usuarios import servico as usuarios
from app.usuarios.esquemas import UsuarioCriar

SENHA = os.getenv("SENHA_EXEMPLO", "Helpdesk2026")

USUARIOS_EXEMPLO = [
    ("Admin TI", "admin@empresa.com", "admin"),
    ("Ana Souza", "ana@empresa.com", "solicitante"),
    ("Bruno Lima", "bruno@empresa.com", "solicitante"),
    ("Carla Dias", "carla@empresa.com", "tecnico"),
    ("Diego Rocha", "diego@empresa.com", "tecnico"),
]


def carregar(db: Session) -> None:
    if usuarios.listar(db):
        return
    for nome, email, perfil in USUARIOS_EXEMPLO:
        usuarios.criar(db, UsuarioCriar(nome=nome, email=email, perfil=perfil, senha=SENHA))
