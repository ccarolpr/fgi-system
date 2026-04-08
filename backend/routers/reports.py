"""
Endpoints de relatórios e controle de período.

GET  /reports/{ano}/{mes}/preview   — prévia consolidada + alertas
POST /reports/{ano}/{mes}/generate  — gera Excel após confirmação da prévia
GET  /reports/{ano}/{mes}/download  — baixa o Excel do período
POST /reports/{ano}/{mes}/fechar    — trava o período
GET  /reports/{ano}/{mes}/status    — status atual do período
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.period import Period, StatusPeriodo
from backend.services.preview_service import gerar_previa
from backend.services.report_service import gerar_excel

router = APIRouter(prefix="/reports", tags=["Relatórios"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_create_period(ano: int, mes: int, db: Session, cliente: str = "CEINT") -> Period:
    period = db.query(Period).filter_by(ano=ano, mes=mes, cliente=cliente).first()
    if not period:
        period = Period(ano=ano, mes=mes, cliente=cliente, status=StatusPeriodo.aberto)
        db.add(period)
        db.commit()
        db.refresh(period)
    return period


def _check_periodo_aberto(period: Period):
    if period.status == StatusPeriodo.fechado:
        raise HTTPException(
            status_code=423,
            detail=f"Período {period.ano}/{period.mes:02d} está fechado. Nenhuma alteração permitida.",
        )


# ---------------------------------------------------------------------------
# Schemas de saída
# ---------------------------------------------------------------------------

class LinhaOut(BaseModel):
    colaborador_id: int
    nome: str
    funcao: str
    cpf: str
    salario: float
    dias_atestado: int
    horas_declaradas_raw: Optional[str]
    horas_declaradas_decimal: float
    valor_hora: float
    valor_dia: float
    custo_horas: float
    custo_dias: float
    total_fgi: float
    com_encargos: float
    total_final: float


class TotaisOut(BaseModel):
    total_fgi: float
    total_com_encargos: float
    total_final: float
    num_colaboradores: int


class AlertaOut(BaseModel):
    tipo: str
    mensagem: str
    colaborador_nome: str
    colaborador_cpf: str


class PreviaOut(BaseModel):
    ano: int
    mes: int
    pode_gerar: bool
    pendencias: list[str]
    alertas: list[AlertaOut]
    linhas: list[LinhaOut]
    totais: Optional[TotaisOut]
    status_periodo: str


class PeriodoOut(BaseModel):
    ano: int
    mes: int
    cliente: str
    status: StatusPeriodo


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/{ano}/{mes}/status", response_model=PeriodoOut)
def status_periodo(ano: int, mes: int, db: Session = Depends(get_db)):
    period = _get_or_create_period(ano, mes, db)
    return PeriodoOut(ano=period.ano, mes=period.mes, cliente=period.cliente, status=period.status)


@router.get("/{ano}/{mes}/preview", response_model=PreviaOut)
def preview_periodo(ano: int, mes: int, db: Session = Depends(get_db)):
    """
    Retorna a prévia consolidada do FGI do período.
    Inclui alertas internos (salário alterado, volume alto de dias, pendências).
    Esses alertas NUNCA aparecem no Excel de saída.
    """
    period = _get_or_create_period(ano, mes, db)
    _check_periodo_aberto(period)

    previa = gerar_previa(ano, mes, db)

    # Avança status para "previewed" se ainda não estava
    if period.status == StatusPeriodo.aberto and previa.pode_gerar:
        period.status = StatusPeriodo.previewed
        period.previewed_em = datetime.now(timezone.utc)
        db.commit()

    return PreviaOut(
        ano=ano,
        mes=mes,
        pode_gerar=previa.pode_gerar,
        pendencias=previa.pendencias,
        alertas=[
            AlertaOut(
                tipo=a.tipo,
                mensagem=a.mensagem,
                colaborador_nome=a.colaborador_nome,
                colaborador_cpf=a.colaborador_cpf,
            )
            for a in previa.alertas
        ],
        linhas=[
            LinhaOut(
                colaborador_id=l.colaborador_id,
                nome=l.nome,
                funcao=l.funcao,
                cpf=l.cpf,
                salario=l.salario,
                dias_atestado=l.dias_atestado,
                horas_declaradas_raw=l.horas_declaradas_raw,
                horas_declaradas_decimal=l.horas_declaradas_decimal,
                valor_hora=l.valor_hora,
                valor_dia=l.valor_dia,
                custo_horas=l.custo_horas,
                custo_dias=l.custo_dias,
                total_fgi=l.total_fgi,
                com_encargos=l.com_encargos,
                total_final=l.total_final,
            )
            for l in previa.linhas
        ],
        totais=TotaisOut(
            total_fgi=previa.totais.total_fgi,
            total_com_encargos=previa.totais.total_com_encargos,
            total_final=previa.totais.total_final,
            num_colaboradores=previa.totais.num_colaboradores,
        ) if previa.totais else None,
        status_periodo=period.status.value,
    )


@router.post("/{ano}/{mes}/generate")
def generate_excel(ano: int, mes: int, db: Session = Depends(get_db)):
    """
    Gera o Excel do período após confirmação da prévia.
    Requer que a prévia tenha sido visualizada (status=previewed ou gerado).
    Bloqueia se houver atestados pendentes.
    """
    period = _get_or_create_period(ano, mes, db)
    _check_periodo_aberto(period)

    if period.status == StatusPeriodo.aberto:
        raise HTTPException(
            status_code=400,
            detail="Visualize a prévia primeiro via GET /reports/{ano}/{mes}/preview.",
        )

    previa = gerar_previa(ano, mes, db)

    if not previa.pode_gerar:
        raise HTTPException(
            status_code=400,
            detail={"mensagem": "Não é possível gerar o Excel.", "pendencias": previa.pendencias},
        )

    if not previa.linhas:
        raise HTTPException(
            status_code=400,
            detail="Nenhum atestado confirmado no período. Não há dados para gerar o relatório.",
        )

    xlsx_bytes = gerar_excel(previa, ano, mes, period.cliente)

    # Persiste o arquivo no banco para download posterior
    period.status = StatusPeriodo.gerado
    period.gerado_em = datetime.now(timezone.utc)
    # Armazena os bytes como BLOB no período
    from sqlalchemy import LargeBinary, Column
    period.excel_bytes = xlsx_bytes
    db.commit()

    return {
        "mensagem": f"Excel do período {ano}/{mes:02d} gerado com sucesso.",
        "num_colaboradores": previa.totais.num_colaboradores if previa.totais else 0,
        "total_final": previa.totais.total_final if previa.totais else 0,
        "instrucao": f"Baixe o arquivo via GET /reports/{ano}/{mes}/download",
    }


@router.get("/{ano}/{mes}/download")
def download_excel(ano: int, mes: int, db: Session = Depends(get_db)):
    """Download do Excel gerado. Regenera se necessário."""
    period = _get_or_create_period(ano, mes, db)

    if period.status in (StatusPeriodo.aberto, StatusPeriodo.previewed):
        raise HTTPException(
            status_code=400,
            detail="Excel ainda não gerado. Use POST /reports/{ano}/{mes}/generate primeiro.",
        )

    # Recupera bytes armazenados ou regenera
    xlsx_bytes = getattr(period, "excel_bytes", None)
    if not xlsx_bytes:
        previa = gerar_previa(ano, mes, db)
        xlsx_bytes = gerar_excel(previa, ano, mes, period.cliente)

    mes_nome = {
        1: "JAN", 2: "FEV", 3: "MAR", 4: "ABR", 5: "MAI", 6: "JUN",
        7: "JUL", 8: "AGO", 9: "SET", 10: "OUT", 11: "NOV", 12: "DEZ",
    }.get(mes, str(mes))

    filename = f"FG_INCERTO_{period.cliente}_{ano}{mes:02d}.xlsx"

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{ano}/{mes}/fechar", response_model=PeriodoOut)
def fechar_periodo(ano: int, mes: int, db: Session = Depends(get_db)):
    """
    Trava o período. Após fechado, nenhuma alteração é permitida.
    Requer que o Excel tenha sido gerado ao menos uma vez.
    """
    period = _get_or_create_period(ano, mes, db)

    if period.status == StatusPeriodo.fechado:
        raise HTTPException(status_code=409, detail="Período já está fechado.")

    if period.status in (StatusPeriodo.aberto, StatusPeriodo.previewed):
        raise HTTPException(
            status_code=400,
            detail="Gere o Excel antes de fechar o período via POST /reports/{ano}/{mes}/generate.",
        )

    # Valida que não há pendências
    previa = gerar_previa(ano, mes, db)
    if previa.pendencias:
        raise HTTPException(
            status_code=400,
            detail={"mensagem": "Resolva as pendências antes de fechar.", "pendencias": previa.pendencias},
        )

    period.status = StatusPeriodo.fechado
    period.fechado_em = datetime.now(timezone.utc)
    db.commit()
    db.refresh(period)

    return PeriodoOut(ano=period.ano, mes=period.mes, cliente=period.cliente, status=period.status)
