"""Cria os equipamentos de exemplo quando o banco está vazio (só para aula).

A ordem de criação é a mesma do monólito, então os ids também são:
1 PAT-0001 (computador), 2 PAT-0002 (impressora), 3 PAT-0003 (notebook).
Os chamados de exemplo usam estes ids.
"""
from sqlalchemy.orm import Session

from app.inventario import servico as inventario
from app.inventario.esquemas import AtivoCriar

ATIVOS_EXEMPLO = [
    AtivoCriar(patrimonio="PAT-0001", tipo="computador", descricao="Desktop Dell OptiPlex", setor="Financeiro"),
    AtivoCriar(patrimonio="PAT-0002", tipo="impressora", descricao="Impressora HP LaserJet", setor="RH"),
    AtivoCriar(patrimonio="PAT-0003", tipo="notebook", descricao="Notebook Lenovo ThinkPad", setor="TI"),
]


def carregar(db: Session) -> None:
    if inventario.listar(db):
        return
    for ativo in ATIVOS_EXEMPLO:
        inventario.criar(db, ativo)
