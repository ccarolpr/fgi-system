"""
Endpoints de colaboradores.

GET    /employees           — listar (filtro por status)
GET    /employees/{cpf}     — buscar por CPF
POST   /employees           — cadastro manual
PATCH  /employees/{cpf}     — atualização manual
DELETE /employees/{cpf}     — soft delete (marca como inativo)
POST   /employees/import    — upsert via planilha Excel
"""

import io
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.employee import Employee, StatusColaborador
from backend.models.employee_audit import EmployeeAudit, OrigemAlteracao
from backend.services.import_service import importar_colaboradores
from backend.config import SALARIO_ALERT_ABS, SALARIO_ALERT_PCT

router = APIRouter(prefix="/employees", tags=["Colaboradores"])


# ---------------------------------------------------------------------------
# Schemas Pydantic
# ---------------------------------------------------------------------------

class EmployeeCreate(BaseModel):
    cpf: str
    nome: str
    funcao: str
    salario: float
    data_admissao: Optional[date] = None
    data_demissao: Optional[date] = None

    @field_validator("cpf")
    @classmethod
    def cpf_somente_digitos(cls, v: str) -> str:
        import re
        digits = re.sub(r"\D", "", v)
        if len(digits) not in (11, 14):
            raise ValueError("CPF deve conter 11 ou 14 dígitos.")
        return digits

    @field_validator("salario")
    @classmethod
    def salario_positivo(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Salário deve ser positivo.")
        return v


class EmployeeUpdate(BaseModel):
    nome: Optional[str] = None
    funcao: Optional[str] = None
    salario: Optional[float] = None
    data_admissao: Optional[date] = None
    data_demissao: Optional[date] = None

    @field_validator("salario")
    @classmethod
    def salario_positivo(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("Salário deve ser positivo.")
        return v


class EmployeeOut(BaseModel):
    id: int
    cpf: str
    nome: str
    funcao: str
    salario: float
    data_admissao: Optional[date]
    data_demissao: Optional[date]
    status: StatusColaborador

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[EmployeeOut])
def listar_colaboradores(
    status: Optional[StatusColaborador] = Query(None, description="Filtrar por status"),
    db: Session = Depends(get_db),
):
    q = db.query(Employee)
    if status:
        q = q.filter(Employee.status == status)
    return q.order_by(Employee.nome).all()


@router.get("/{cpf}", response_model=EmployeeOut)
def buscar_colaborador(cpf: str, db: Session = Depends(get_db)):
    import re
    cpf = re.sub(r"\D", "", cpf)
    emp = db.query(Employee).filter_by(cpf=cpf).first()
    if not emp:
        raise HTTPException(status_code=404, detail=f"Colaborador CPF {cpf} não encontrado.")
    return emp


@router.post("", response_model=EmployeeOut, status_code=201)
def cadastrar_colaborador(data: EmployeeCreate, db: Session = Depends(get_db)):
    existente = db.query(Employee).filter_by(cpf=data.cpf).first()
    if existente:
        raise HTTPException(status_code=409, detail=f"CPF {data.cpf} já cadastrado.")
    emp = Employee(
        cpf=data.cpf,
        nome=data.nome,
        funcao=data.funcao,
        salario=data.salario,
        data_admissao=data.data_admissao,
        data_demissao=data.data_demissao,
        status=StatusColaborador.inativo if data.data_demissao else StatusColaborador.ativo,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@router.patch("/{cpf}", response_model=EmployeeOut)
def atualizar_colaborador(cpf: str, data: EmployeeUpdate, db: Session = Depends(get_db)):
    import re
    cpf = re.sub(r"\D", "", cpf)
    emp = db.query(Employee).filter_by(cpf=cpf).first()
    if not emp:
        raise HTTPException(status_code=404, detail=f"Colaborador CPF {cpf} não encontrado.")

    campos = data.model_dump(exclude_none=True)
    for campo, novo_val in campos.items():
        anterior = getattr(emp, campo)
        if anterior == novo_val:
            continue

        alerta = False
        if campo == "salario":
            pct = abs(novo_val - anterior) / anterior if anterior else 1
            alerta = pct > SALARIO_ALERT_PCT or abs(novo_val - anterior) > SALARIO_ALERT_ABS

        audit = EmployeeAudit(
            employee_id=emp.id,
            campo=campo,
            valor_anterior=str(anterior),
            valor_novo=str(novo_val),
            origem=OrigemAlteracao.manual,
            alerta_ativo=alerta,
        )
        db.add(audit)
        setattr(emp, campo, novo_val)

    if data.data_demissao:
        emp.status = StatusColaborador.inativo

    db.commit()
    db.refresh(emp)
    return emp


@router.delete("/{cpf}", status_code=204)
def desativar_colaborador(cpf: str, db: Session = Depends(get_db)):
    """Soft delete: marca colaborador como inativo. Histórico preservado."""
    import re
    cpf = re.sub(r"\D", "", cpf)
    emp = db.query(Employee).filter_by(cpf=cpf).first()
    if not emp:
        raise HTTPException(status_code=404, detail=f"Colaborador CPF {cpf} não encontrado.")
    emp.status = StatusColaborador.inativo
    db.commit()


@router.post("/import", status_code=200)
async def importar_planilha(
    file: UploadFile = File(..., description="Planilha Excel (.xlsx) da contabilidade"),
    db: Session = Depends(get_db),
):
    """
    Upsert de colaboradores via planilha Excel.
    CPF é a chave de correspondência. Retorna relatório da importação.
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Arquivo deve ser .xlsx ou .xls.")

    conteudo = await file.read()
    resultado = importar_colaboradores(io.BytesIO(conteudo), db)

    return {
        "inseridos": resultado.inseridos,
        "atualizados": resultado.atualizados,
        "erros": resultado.erros,
        "alertas_salario": resultado.alertas_salario,
        "mensagem": (
            f"{resultado.inseridos} inserido(s), {resultado.atualizados} atualizado(s), "
            f"{len(resultado.erros)} erro(s)."
        ),
    }
