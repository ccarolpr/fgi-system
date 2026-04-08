"""
Detecção de possíveis atestados duplicados.

O alerta não bloqueia — o usuário decide se confirma ou descarta.
Duplicatas rejeitadas ficam no log de atestados com status 'rejeitado'.
"""

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.atestado import Atestado, StatusAtestado


def verificar_duplicidade(
    colaborador_id: int,
    data_inicio: date,
    dias: int,
    db: Session,
    excluir_id: Optional[int] = None,
) -> bool:
    """
    Retorna True se existe atestado confirmado (ou pendente de validação)
    para o mesmo colaborador na mesma data_inicio com a mesma quantidade de dias.

    Args:
        colaborador_id: ID do colaborador vinculado.
        data_inicio:    Data de início do atestado.
        dias:           Quantidade de dias.
        db:             Sessão SQLAlchemy.
        excluir_id:     ID de atestado a ignorar na busca (ex: o próprio em edição).

    Returns:
        True se suspeita de duplicidade, False caso contrário.
    """
    status_relevantes = [StatusAtestado.confirmado, StatusAtestado.pendente_validacao]

    q = (
        db.query(Atestado)
        .filter(
            Atestado.colaborador_id == colaborador_id,
            Atestado.data_inicio == data_inicio,
            Atestado.dias == dias,
            Atestado.status.in_(status_relevantes),
        )
    )
    if excluir_id:
        q = q.filter(Atestado.id != excluir_id)

    return q.count() > 0


def verificar_mesma_data(
    colaborador_id: int,
    data_inicio: date,
    db: Session,
    excluir_id: Optional[int] = None,
) -> bool:
    """
    Retorna True se já existe qualquer atestado ativo para o colaborador
    na mesma data de início (independente da quantidade de dias).
    Usado quando dias divergem mas a data coincide — suspeita mais branda.
    """
    status_relevantes = [StatusAtestado.confirmado, StatusAtestado.pendente_validacao]

    q = (
        db.query(Atestado)
        .filter(
            Atestado.colaborador_id == colaborador_id,
            Atestado.data_inicio == data_inicio,
            Atestado.status.in_(status_relevantes),
        )
    )
    if excluir_id:
        q = q.filter(Atestado.id != excluir_id)

    return q.count() > 0
