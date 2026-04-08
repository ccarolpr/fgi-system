"""
Consolidação mensal de atestados por colaborador.

O FGI nunca é calculado por atestado individual.
A fórmula é aplicada uma única vez sobre os totais do mês:
  - total_dias  = soma de todos os dias de atestado do colaborador no mês
  - total_horas = soma de todas as horas declaradas do colaborador no mês (decimal)
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class AtestadoItem:
    """Representa um atestado individual antes da consolidação."""
    colaborador_cpf: str
    dias: int
    horas_decimal: float   # já convertido via hours_parser.parse_horas()


@dataclass
class ConsolidadoMensal:
    """Resultado da consolidação de todos os atestados de um colaborador no mês."""
    colaborador_cpf: str
    total_dias: int
    total_horas: float


def consolidar(atestados: List[AtestadoItem]) -> List[ConsolidadoMensal]:
    """
    Agrupa atestados por CPF e soma dias e horas dentro do mesmo período.

    Args:
        atestados: Lista de AtestadoItem com status 'confirmado' do período.

    Returns:
        Lista de ConsolidadoMensal, um por CPF único, ordenada por CPF.
        Colaboradores sem atestado confirmado no mês NÃO aparecem na lista.
    """
    totais: dict[str, dict] = {}

    for a in atestados:
        cpf = a.colaborador_cpf
        if cpf not in totais:
            totais[cpf] = {"dias": 0, "horas": 0.0}
        totais[cpf]["dias"] += a.dias
        totais[cpf]["horas"] += a.horas_decimal

    return [
        ConsolidadoMensal(
            colaborador_cpf=cpf,
            total_dias=dados["dias"],
            total_horas=dados["horas"],
        )
        for cpf, dados in sorted(totais.items())
    ]
