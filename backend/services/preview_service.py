"""
Serviço de pré-visualização do FGI mensal.

Consolida atestados confirmados do período, calcula FGI por colaborador
e coleta alertas internos (variações de salário, volume alto de dias,
colaboradores novos, pendências).

Os alertas NUNCA vão para o Excel de saída — são exibidos apenas na tela
de prévia para o operador revisar antes de gerar o relatório.
"""

from datetime import date
from typing import Optional
from dataclasses import dataclass, field

from sqlalchemy import extract
from sqlalchemy.orm import Session

from backend.models.atestado import Atestado, StatusAtestado
from backend.models.employee import Employee
from backend.models.employee_audit import EmployeeAudit
from backend.services.consolidation import consolidar, AtestadoItem
from backend.services.fgi_calculator import calcular_fgi


# Colaboradores com mais de X dias de atestado no mês geram alerta informativo
LIMITE_DIAS_ALERTA = 10


@dataclass
class LinhaPrevia:
    """Dados de um colaborador na prévia — espelho das colunas do Excel."""
    colaborador_id: int
    nome: str
    funcao: str
    cpf: str
    data_admissao: Optional[date]
    data_demissao: Optional[date]
    salario: float
    dias_atestado: int
    horas_declaradas_raw: Optional[str]    # HH:MM para exibição
    horas_declaradas_decimal: float
    # Resultados calculados
    valor_hora: float
    valor_dia: float
    custo_horas: float
    custo_dias: float
    total_fgi: float
    com_encargos: float
    total_final: float


@dataclass
class TotaisPrevia:
    total_fgi: float
    total_com_encargos: float
    total_final: float
    num_colaboradores: int


@dataclass
class AlertaPrevia:
    tipo: str       # "salario_alterado" | "volume_alto" | "colaborador_novo"
    mensagem: str
    colaborador_nome: str
    colaborador_cpf: str


@dataclass
class PreviaResult:
    linhas: list[LinhaPrevia] = field(default_factory=list)
    totais: Optional[TotaisPrevia] = None
    alertas: list[AlertaPrevia] = field(default_factory=list)
    pendencias: list[str] = field(default_factory=list)   # bloqueiam geração do Excel
    pode_gerar: bool = False


def gerar_previa(ano: int, mes: int, db: Session) -> PreviaResult:
    """
    Consolida e calcula o FGI de todos os colaboradores com atestado confirmado
    no período informado.

    Args:
        ano: Ano do período (ex: 2026).
        mes: Mês do período (ex: 3 para março).
        db:  Sessão SQLAlchemy.

    Returns:
        PreviaResult com linhas calculadas, totais e alertas internos.
    """
    resultado = PreviaResult()

    # -----------------------------------------------------------------------
    # 1. Verificar pendências que bloqueiam a geração
    # -----------------------------------------------------------------------
    pendentes = (
        db.query(Atestado)
        .filter(
            Atestado.status.in_([StatusAtestado.pendente_validacao, StatusAtestado.sem_vinculo]),
            extract("month", Atestado.data_inicio) == mes,
            extract("year", Atestado.data_inicio) == ano,
        )
        .count()
    )
    if pendentes:
        resultado.pendencias.append(
            f"{pendentes} atestado(s) com status pendente ou sem vínculo no período. "
            "Resolva antes de gerar o relatório."
        )

    # -----------------------------------------------------------------------
    # 2. Buscar atestados confirmados do período
    # -----------------------------------------------------------------------
    atestados_db = (
        db.query(Atestado)
        .filter(
            Atestado.status == StatusAtestado.confirmado,
            Atestado.colaborador_id.isnot(None),
            extract("month", Atestado.data_inicio) == mes,
            extract("year", Atestado.data_inicio) == ano,
        )
        .all()
    )

    if not atestados_db:
        resultado.pode_gerar = len(resultado.pendencias) == 0
        return resultado

    # -----------------------------------------------------------------------
    # 3. Consolidar por colaborador
    # -----------------------------------------------------------------------
    items = [
        AtestadoItem(
            colaborador_cpf=str(a.colaborador_id),  # usamos ID como chave interna
            dias=a.dias,
            horas_decimal=a.horas_declaradas_decimal,
        )
        for a in atestados_db
    ]

    # Mapeia horas_raw por colaborador_id (pega a última não-nula)
    horas_raw_map: dict[int, Optional[str]] = {}
    for a in atestados_db:
        if a.horas_declaradas_raw:
            horas_raw_map[a.colaborador_id] = a.horas_declaradas_raw

    consolidados = consolidar(items)
    # consolidados usa colaborador_cpf como chave — que aqui é o ID como string
    consolidados_map = {c.colaborador_cpf: c for c in consolidados}

    # -----------------------------------------------------------------------
    # 4. Buscar dados dos colaboradores e calcular FGI
    # -----------------------------------------------------------------------
    ids_colaboradores = list({a.colaborador_id for a in atestados_db})
    colaboradores = {
        e.id: e
        for e in db.query(Employee).filter(Employee.id.in_(ids_colaboradores)).all()
    }

    # Alertas de salário: colaboradores que tiveram alerta_ativo no período
    alertas_salario_ids = set(
        row.employee_id
        for row in db.query(EmployeeAudit)
        .filter(
            EmployeeAudit.employee_id.in_(ids_colaboradores),
            EmployeeAudit.campo == "salario",
            EmployeeAudit.alerta_ativo == True,  # noqa: E712
        )
        .all()
    )

    soma_fgi = 0.0
    soma_enc = 0.0
    soma_final = 0.0

    # Ordena por nome para exibição consistente
    for emp in sorted(colaboradores.values(), key=lambda e: e.nome):
        chave = str(emp.id)
        if chave not in consolidados_map:
            continue

        c = consolidados_map[chave]
        fgi = calcular_fgi(emp.salario, c.total_dias, c.total_horas)

        linha = LinhaPrevia(
            colaborador_id=emp.id,
            nome=emp.nome,
            funcao=emp.funcao,
            cpf=emp.cpf,
            data_admissao=emp.data_admissao,
            data_demissao=emp.data_demissao,
            salario=emp.salario,
            dias_atestado=c.total_dias,
            horas_declaradas_raw=horas_raw_map.get(emp.id),
            horas_declaradas_decimal=c.total_horas,
            valor_hora=fgi["valor_hora"],
            valor_dia=fgi["valor_dia"],
            custo_horas=fgi["custo_horas"],
            custo_dias=fgi["custo_dias"],
            total_fgi=fgi["total_fgi"],
            com_encargos=fgi["com_encargos"],
            total_final=fgi["total_final"],
        )
        resultado.linhas.append(linha)

        # Acumula com precisão total para evitar erro de centavos no total
        soma_fgi += fgi["_total_fgi_raw"]
        soma_enc += fgi["_com_encargos_raw"]
        soma_final += fgi["_total_final_raw"]

        # -----------------------------------------------------------------------
        # 5. Coletar alertas internos (apenas para prévia, nunca para o Excel)
        # -----------------------------------------------------------------------
        if emp.id in alertas_salario_ids:
            ultimo_audit = (
                db.query(EmployeeAudit)
                .filter_by(employee_id=emp.id, campo="salario", alerta_ativo=True)
                .order_by(EmployeeAudit.alterado_em.desc())
                .first()
            )
            if ultimo_audit:
                resultado.alertas.append(AlertaPrevia(
                    tipo="salario_alterado",
                    mensagem=(
                        f"Salário alterado: R$ {ultimo_audit.valor_anterior} → "
                        f"R$ {ultimo_audit.valor_novo} "
                        f"(origem: {ultimo_audit.origem.value})"
                    ),
                    colaborador_nome=emp.nome,
                    colaborador_cpf=emp.cpf,
                ))

        if c.total_dias >= LIMITE_DIAS_ALERTA:
            resultado.alertas.append(AlertaPrevia(
                tipo="volume_alto",
                mensagem=f"{c.total_dias} dias de atestado no mês — verifique se está correto.",
                colaborador_nome=emp.nome,
                colaborador_cpf=emp.cpf,
            ))

    resultado.totais = TotaisPrevia(
        total_fgi=round(soma_fgi, 2),
        total_com_encargos=round(soma_enc, 2),
        total_final=round(soma_final, 2),
        num_colaboradores=len(resultado.linhas),
    )
    resultado.pode_gerar = len(resultado.pendencias) == 0

    return resultado
