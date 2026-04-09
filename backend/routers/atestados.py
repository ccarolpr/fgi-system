"""
Endpoints de atestados.

POST   /atestados/upload              — upload PDF, extrai OCR, retorna para revisão
POST   /atestados/manual              — entrada manual
GET    /atestados                     — lista (filtros: status, mes, ano, colaborador_id)
GET    /atestados/{id}                — detalhe
PATCH  /atestados/{id}/vincular       — vincula colaborador (para sem_vinculo)
PATCH  /atestados/{id}/confirmar      — confirma após revisão
PATCH  /atestados/{id}/rejeitar       — rejeita atestado
POST   /atestados/{id}/correcao       — correção auditada pós-confirmação
GET    /atestados/{id}/correcoes      — histórico de correções
GET    /atestados/busca-nome          — busca candidatos por nome (para vinculação manual)
"""

import io
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.atestado import Atestado, StatusAtestado, OrigemAtestado
from backend.models.atestado_correcao import AtestadoCorrecao
from backend.models.employee import Employee
from backend.services import ocr_service, employee_matcher, duplicate_checker
from backend.services.hours_parser import parse_horas

router = APIRouter(prefix="/atestados", tags=["Atestados"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AtestadoOut(BaseModel):
    id: int
    colaborador_id: Optional[int]
    data_inicio: date
    dias: int
    horas_declaradas_raw: Optional[str]
    horas_declaradas_decimal: float
    cid: Optional[str]
    status: StatusAtestado
    origem: OrigemAtestado
    nome_ocr: Optional[str]
    cpf_ocr: Optional[str]
    confirmado_por: Optional[str]
    confirmado_em: Optional[datetime]
    criado_em: datetime

    model_config = {"from_attributes": True}


class AtestadoManualInput(BaseModel):
    cpf: Optional[str] = None
    colaborador_id: Optional[int] = None
    data_inicio: date
    dias: int
    horas_declaradas: Optional[str] = None  # "HH:MM"
    cid: Optional[str] = None

    @field_validator("dias")
    @classmethod
    def dias_positivo(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Dias não pode ser negativo.")
        return v

    @field_validator("horas_declaradas")
    @classmethod
    def horas_formato(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            parse_horas(v)  # valida o formato — lança ValueError se inválido
        return v


class ConfirmarInput(BaseModel):
    # Campos opcionais: usuário pode corrigir durante a confirmação
    colaborador_id: Optional[int] = None
    data_inicio: Optional[date] = None
    dias: Optional[int] = None
    horas_declaradas: Optional[str] = None
    cid: Optional[str] = None
    usuario: str = "sistema"
    forcar_duplicidade: bool = False  # True = confirma mesmo com alerta de duplicidade


class VincularInput(BaseModel):
    colaborador_id: int


class CorrecaoInput(BaseModel):
    campo: str
    valor_novo: str
    motivo: str
    usuario: str = "sistema"

    @field_validator("campo")
    @classmethod
    def campo_permitido(cls, v: str) -> str:
        permitidos = {"dias", "horas_declaradas_raw", "data_inicio", "cid", "colaborador_id"}
        if v not in permitidos:
            raise ValueError(f"Campo '{v}' não pode ser corrigido. Permitidos: {permitidos}")
        return v


class CorrecaoOut(BaseModel):
    id: int
    atestado_id: int
    campo: str
    valor_anterior: Optional[str]
    valor_novo: str
    motivo: str
    usuario: str
    criado_em: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_atestado_ou_404(id: int, db: Session) -> Atestado:
    a = db.query(Atestado).filter_by(id=id).first()
    if not a:
        raise HTTPException(status_code=404, detail=f"Atestado {id} não encontrado.")
    return a


def _resolver_colaborador(
    cpf: Optional[str],
    colaborador_id: Optional[int],
    db: Session,
) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Tenta identificar o colaborador.
    Retorna: (colaborador_id, nome_ocr, cpf_ocr)
    """
    import re

    if cpf:
        cpf_limpo = re.sub(r"\D", "", cpf)
        emp = employee_matcher.match_por_cpf(cpf_limpo, db)
        if emp:
            return emp.id, emp.nome, cpf_limpo
        return None, None, cpf_limpo  # CPF informado mas não cadastrado

    if colaborador_id:
        emp = db.query(Employee).filter_by(id=colaborador_id).first()
        if not emp:
            raise HTTPException(status_code=404, detail=f"Colaborador ID {colaborador_id} não encontrado.")
        return emp.id, emp.nome, None

    return None, None, None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=dict, status_code=201)
async def upload_atestado(
    file: UploadFile = File(..., description="Atestado médico em PDF"),
    db: Session = Depends(get_db),
):
    """
    Envia PDF, extrai dados via OCR e cria atestado para revisão.
    Retorna o atestado criado + candidatos de colaborador + alertas de duplicidade.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Arquivo deve ser PDF.")

    conteudo = await file.read()
    resultado_ocr = ocr_service.extrair_atestado(conteudo)

    # Tenta identificar colaborador por CPF (automático)
    colab_id = None
    nome_ocr = resultado_ocr.nome
    cpf_ocr = resultado_ocr.cpf

    candidatos = []
    if resultado_ocr.cpf:
        emp = employee_matcher.match_por_cpf(resultado_ocr.cpf, db)
        if emp:
            colab_id = emp.id
        else:
            resultado_ocr.avisos.append(
                f"CPF {resultado_ocr.cpf} não encontrado — possível erro de leitura OCR. "
                "Veja os candidatos abaixo pelo nome."
            )
            # Fallback: busca por nome quando CPF não bate (OCR pode ter errado dígitos)
            if resultado_ocr.nome:
                matches = employee_matcher.buscar_por_nome(resultado_ocr.nome, db)
                candidatos = [
                    {"id": c.colaborador.id, "nome": c.colaborador.nome, "cpf": c.colaborador.cpf, "score": c.score}
                    for c in matches
                ]
    elif resultado_ocr.nome:
        # Sem CPF → busca por nome para apresentar candidatos ao usuário
        matches = employee_matcher.buscar_por_nome(resultado_ocr.nome, db)
        candidatos = [
            {"id": c.colaborador.id, "nome": c.colaborador.nome, "cpf": c.colaborador.cpf, "score": c.score}
            for c in matches
        ]
        if not candidatos:
            resultado_ocr.avisos.append("Nenhum colaborador similar encontrado. Vinculação manual obrigatória.")

    status_inicial = (
        StatusAtestado.pendente_validacao if colab_id or resultado_ocr.cpf
        else StatusAtestado.sem_vinculo
    )

    horas_dec = parse_horas(resultado_ocr.horas) if resultado_ocr.horas else 0.0

    atestado = Atestado(
        colaborador_id=colab_id,
        data_inicio=resultado_ocr.data_inicio or date.today(),
        dias=resultado_ocr.dias or 0,
        horas_declaradas_raw=resultado_ocr.horas,
        horas_declaradas_decimal=horas_dec,
        cid=resultado_ocr.cid,
        status=status_inicial,
        origem=OrigemAtestado.ocr,
        ocr_raw=resultado_ocr.raw_text[:4000] if resultado_ocr.raw_text else None,
        nome_ocr=nome_ocr,
        cpf_ocr=cpf_ocr,
    )
    db.add(atestado)
    db.commit()
    db.refresh(atestado)

    return {
        "atestado": AtestadoOut.model_validate(atestado).model_dump(),
        "ocr": resultado_ocr.to_dict(),
        "candidatos_colaborador": candidatos,
        "avisos": resultado_ocr.avisos,
        "instrucao": "Revise os dados, vincule o colaborador se necessário e confirme via PATCH /atestados/{id}/confirmar",
    }


@router.post("/manual", response_model=AtestadoOut, status_code=201)
def cadastrar_manual(data: AtestadoManualInput, db: Session = Depends(get_db)):
    """Entrada manual de atestado — cria diretamente como pendente de validação."""
    colab_id, nome_ocr, cpf_ocr = _resolver_colaborador(data.cpf, data.colaborador_id, db)

    status_inicial = (
        StatusAtestado.pendente_validacao if colab_id
        else StatusAtestado.sem_vinculo
    )

    horas_dec = parse_horas(data.horas_declaradas) if data.horas_declaradas else 0.0

    atestado = Atestado(
        colaborador_id=colab_id,
        data_inicio=data.data_inicio,
        dias=data.dias,
        horas_declaradas_raw=data.horas_declaradas,
        horas_declaradas_decimal=horas_dec,
        cid=data.cid,
        status=status_inicial,
        origem=OrigemAtestado.manual,
        nome_ocr=nome_ocr,
        cpf_ocr=cpf_ocr,
    )
    db.add(atestado)
    db.commit()
    db.refresh(atestado)
    return atestado


@router.get("/busca-nome", response_model=list[dict])
def buscar_colaborador_por_nome(
    nome: str = Query(..., min_length=3),
    db: Session = Depends(get_db),
):
    """Retorna candidatos de colaborador ordenados por similaridade de nome."""
    candidatos = employee_matcher.buscar_por_nome(nome, db)
    return [
        {"id": c.colaborador.id, "nome": c.colaborador.nome, "cpf": c.colaborador.cpf, "score": c.score}
        for c in candidatos
    ]


@router.get("", response_model=list[AtestadoOut])
def listar_atestados(
    status: Optional[StatusAtestado] = None,
    colaborador_id: Optional[int] = None,
    mes: Optional[int] = Query(None, ge=1, le=12),
    ano: Optional[int] = Query(None, ge=2020),
    db: Session = Depends(get_db),
):
    q = db.query(Atestado)
    if status:
        q = q.filter(Atestado.status == status)
    if colaborador_id:
        q = q.filter(Atestado.colaborador_id == colaborador_id)
    if mes and ano:
        from sqlalchemy import extract
        q = q.filter(
            extract("month", Atestado.data_inicio) == mes,
            extract("year", Atestado.data_inicio) == ano,
        )
    return q.order_by(Atestado.criado_em.desc()).all()


@router.get("/{id}", response_model=AtestadoOut)
def detalhe_atestado(id: int, db: Session = Depends(get_db)):
    return _get_atestado_ou_404(id, db)


@router.patch("/{id}/vincular", response_model=AtestadoOut)
def vincular_colaborador(id: int, data: VincularInput, db: Session = Depends(get_db)):
    """Vincula colaborador a atestado sem_vinculo. Não requer confirmação adicional."""
    atestado = _get_atestado_ou_404(id, db)
    if atestado.status == StatusAtestado.confirmado:
        raise HTTPException(status_code=409, detail="Atestado já confirmado. Use /correcao para alterar.")
    if atestado.status == StatusAtestado.rejeitado:
        raise HTTPException(status_code=409, detail="Atestado rejeitado não pode ser alterado.")

    emp = db.query(Employee).filter_by(id=data.colaborador_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail=f"Colaborador {data.colaborador_id} não encontrado.")

    atestado.colaborador_id = data.colaborador_id
    atestado.status = StatusAtestado.pendente_validacao
    db.commit()
    db.refresh(atestado)
    return atestado


@router.patch("/{id}/confirmar", response_model=dict)
def confirmar_atestado(id: int, data: ConfirmarInput, db: Session = Depends(get_db)):
    """
    Confirma atestado após revisão. Aplica correções informadas no body.
    Verifica duplicidade antes de confirmar.
    """
    atestado = _get_atestado_ou_404(id, db)

    if atestado.status == StatusAtestado.confirmado:
        raise HTTPException(status_code=409, detail="Atestado já confirmado.")
    if atestado.status == StatusAtestado.rejeitado:
        raise HTTPException(status_code=409, detail="Atestado rejeitado não pode ser confirmado.")

    # Aplica correções do body antes de confirmar
    if data.colaborador_id is not None:
        emp = db.query(Employee).filter_by(id=data.colaborador_id).first()
        if not emp:
            raise HTTPException(status_code=404, detail=f"Colaborador {data.colaborador_id} não encontrado.")
        atestado.colaborador_id = data.colaborador_id

    if data.data_inicio is not None:
        atestado.data_inicio = data.data_inicio
    if data.dias is not None:
        if data.dias < 0:
            raise HTTPException(status_code=400, detail="Dias não pode ser negativo.")
        atestado.dias = data.dias
    if data.horas_declaradas is not None:
        atestado.horas_declaradas_raw = data.horas_declaradas
        atestado.horas_declaradas_decimal = parse_horas(data.horas_declaradas)
    if data.cid is not None:
        atestado.cid = data.cid

    if not atestado.colaborador_id:
        raise HTTPException(
            status_code=400,
            detail="Colaborador não vinculado. Use /vincular antes de confirmar.",
        )

    # Verificação de duplicidade
    alerta_duplicidade = None
    eh_duplicata = duplicate_checker.verificar_duplicidade(
        atestado.colaborador_id, atestado.data_inicio, atestado.dias, db, excluir_id=id
    )
    if not eh_duplicata:
        # Verifica mesma data (suspeita mais branda)
        eh_duplicata = duplicate_checker.verificar_mesma_data(
            atestado.colaborador_id, atestado.data_inicio, db, excluir_id=id
        )
        if eh_duplicata:
            alerta_duplicidade = "Já existe atestado para este colaborador nesta data."

    if eh_duplicata and not data.forcar_duplicidade:
        alerta_duplicidade = alerta_duplicidade or "Possível duplicidade detectada (CPF + data + dias)."
        return {
            "confirmado": False,
            "alerta_duplicidade": alerta_duplicidade,
            "instrucao": "Para confirmar mesmo assim, envie forcar_duplicidade=true no body.",
        }

    atestado.status = StatusAtestado.confirmado
    atestado.confirmado_por = data.usuario
    atestado.confirmado_em = datetime.now(timezone.utc)
    db.commit()
    db.refresh(atestado)

    return {
        "confirmado": True,
        "atestado": AtestadoOut.model_validate(atestado).model_dump(),
        "alerta_duplicidade": alerta_duplicidade,
    }


@router.patch("/{id}/rejeitar", response_model=AtestadoOut)
def rejeitar_atestado(id: int, db: Session = Depends(get_db)):
    atestado = _get_atestado_ou_404(id, db)
    if atestado.status == StatusAtestado.confirmado:
        raise HTTPException(status_code=409, detail="Atestado confirmado não pode ser rejeitado. Use /correcao.")
    atestado.status = StatusAtestado.rejeitado
    db.commit()
    db.refresh(atestado)
    return atestado


@router.post("/{id}/correcao", response_model=CorrecaoOut, status_code=201)
def corrigir_atestado(id: int, data: CorrecaoInput, db: Session = Depends(get_db)):
    """
    Correção auditada de atestado confirmado.
    O atestado original é preservado no histórico.
    """
    atestado = _get_atestado_ou_404(id, db)
    if atestado.status != StatusAtestado.confirmado:
        raise HTTPException(
            status_code=400,
            detail="Correção auditada é permitida apenas para atestados confirmados.",
        )

    campo = data.campo
    valor_anterior = str(getattr(atestado, campo, None))

    # Aplica a correção no atestado
    if campo == "horas_declaradas_raw":
        parse_horas(data.valor_novo)  # valida formato
        atestado.horas_declaradas_raw = data.valor_novo
        atestado.horas_declaradas_decimal = parse_horas(data.valor_novo)
    elif campo == "dias":
        atestado.dias = int(data.valor_novo)
    elif campo == "data_inicio":
        atestado.data_inicio = date.fromisoformat(data.valor_novo)
    elif campo == "cid":
        atestado.cid = data.valor_novo
    elif campo == "colaborador_id":
        emp = db.query(Employee).filter_by(id=int(data.valor_novo)).first()
        if not emp:
            raise HTTPException(status_code=404, detail=f"Colaborador {data.valor_novo} não encontrado.")
        atestado.colaborador_id = int(data.valor_novo)

    correcao = AtestadoCorrecao(
        atestado_id=id,
        campo=campo,
        valor_anterior=valor_anterior,
        valor_novo=data.valor_novo,
        motivo=data.motivo,
        usuario=data.usuario,
    )
    db.add(correcao)
    db.commit()
    db.refresh(correcao)
    return correcao


@router.get("/{id}/correcoes", response_model=list[CorrecaoOut])
def listar_correcoes(id: int, db: Session = Depends(get_db)):
    _get_atestado_ou_404(id, db)
    return db.query(AtestadoCorrecao).filter_by(atestado_id=id).order_by(AtestadoCorrecao.criado_em).all()
