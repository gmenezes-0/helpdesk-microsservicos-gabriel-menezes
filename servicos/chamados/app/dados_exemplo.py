"""Cria os chamados de exemplo quando o banco está vazio (só para aula).

São os mesmos chamados do monólito. Como cada serviço tem o seu banco, aqui
usamos os ids que os dados de exemplo dos outros serviços criam:
- Usuários: 2 Ana (solicitante), 3 Bruno (solicitante), 4 Carla (técnica);
- Inventário: 1 PAT-0001 (computador), 2 PAT-0002 (impressora).

Não há chamada HTTP aqui: ao iniciar, não existe token de usuário para repassar
e os outros serviços podem ainda não estar no ar. Por isso o chamado é gravado
pelas mesmas funções que `abrir` e `atribuir` usam depois de conferir os dados.
"""
from sqlalchemy.orm import Session

from app.chamados import repositorio
from app.chamados import servico as chamados
from app.chamados.esquemas import ChamadoCriar

ANA, BRUNO, CARLA = 2, 3, 4
COMPUTADOR, IMPRESSORA = 1, 2


def carregar(db: Session) -> None:
    if repositorio.listar(db):
        return
    c1 = chamados.registrar_abertura(db, ChamadoCriar(titulo="Computador não liga", descricao="Apertei o botão e nada acontece.", prioridade="alta", ativo_id=COMPUTADOR), ANA)
    chamados.registrar_abertura(db, ChamadoCriar(titulo="Impressora atolando papel", descricao="Atola a cada 3 folhas.", prioridade="media", ativo_id=IMPRESSORA), BRUNO)
    chamados.registrar_abertura(db, ChamadoCriar(titulo="Acesso ao sistema de RH", descricao="Preciso de acesso para a nova estagiária.", prioridade="baixa"), BRUNO)
    chamados.registrar_atribuicao(db, c1, CARLA)
