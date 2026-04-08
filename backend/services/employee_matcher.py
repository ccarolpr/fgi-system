"""
Identificação de colaboradores a partir de dados de atestados.

Regra absoluta: correspondência automática SOMENTE via CPF.
Busca por nome retorna candidatos ordenados por score — seleção é sempre manual.
"""

import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.employee import Employee, StatusColaborador

try:
    from rapidfuzz import fuzz, process as rfprocess
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False


def _normalizar_cpf(cpf: str) -> str:
    return re.sub(r"\D", "", str(cpf))


@dataclass
class CandidatoNome:
    colaborador: Employee
    score: float        # 0–100, quanto maior melhor
    nome_encontrado: str


def match_por_cpf(cpf: str, db: Session) -> Optional[Employee]:
    """
    Busca exata por CPF.
    Retorna o colaborador ativo correspondente, ou None se não encontrado.
    Colaboradores inativos também são retornados (para casos de reativação manual).
    """
    cpf_limpo = _normalizar_cpf(cpf)
    if not cpf_limpo:
        return None
    return db.query(Employee).filter_by(cpf=cpf_limpo).first()


def buscar_por_nome(nome: str, db: Session, limite: int = 5) -> list[CandidatoNome]:
    """
    Busca colaboradores por similaridade de nome.
    Retorna até `limite` candidatos ordenados por score decrescente.

    NÃO faz correspondência automática. O resultado deve ser apresentado
    ao usuário para seleção manual.

    Requer rapidfuzz. Sem ele, retorna lista vazia com aviso.
    """
    if not _HAS_RAPIDFUZZ:
        return []

    todos = db.query(Employee).all()
    if not todos:
        return []

    nomes_map = {str(e.id): e for e in todos}
    choices = {str(e.id): e.nome for e in todos}

    resultados = rfprocess.extract(
        nome,
        choices,
        scorer=fuzz.token_sort_ratio,
        limit=limite,
    )

    candidatos = []
    for _nome_encontrado, score, key in resultados:
        if score >= 40:  # descarta resultados muito distantes
            candidatos.append(CandidatoNome(
                colaborador=nomes_map[key],
                score=score,
                nome_encontrado=_nome_encontrado,
            ))

    return sorted(candidatos, key=lambda c: c.score, reverse=True)


def tem_rapidfuzz() -> bool:
    return _HAS_RAPIDFUZZ
