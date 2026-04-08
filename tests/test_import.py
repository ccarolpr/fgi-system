"""
Testes do serviço de importação de colaboradores.

Valida: upsert por CPF, audit log de salário, soft delete,
alerta de variação relevante, bloqueio de salário <= 0.
"""

import sys
import os
import io
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import openpyxl
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models.employee import Employee, StatusColaborador
from backend.models.employee_audit import EmployeeAudit, OrigemAlteracao
from backend.services.import_service import importar_colaboradores


# ---------------------------------------------------------------------------
# Fixture: banco de dados em memória por teste
# ---------------------------------------------------------------------------
@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    from backend.models import employee, employee_audit  # noqa — registra mappers
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Helper: gera planilha Excel em memória
# ---------------------------------------------------------------------------
def make_xlsx(rows: list[dict]) -> io.BytesIO:
    """Cria planilha com cabeçalho padrão e as linhas fornecidas."""
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = ["CPF", "NOME", "FUNÇÃO", "SALÁRIO", "ADMISSÃO", "DEMISSÃO"]
    ws.append(headers)
    for row in rows:
        ws.append([
            row.get("cpf", ""),
            row.get("nome", ""),
            row.get("funcao", ""),
            row.get("salario", ""),
            row.get("admissao", ""),
            row.get("demissao", ""),
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

def test_insercao_novo_colaborador(db):
    xlsx = make_xlsx([{"cpf": "54397984808", "nome": "Bianca Lima", "funcao": "AUX JR", "salario": 2050}])
    res = importar_colaboradores(xlsx, db)
    assert res.inseridos == 1
    assert res.atualizados == 0
    assert res.erros == []
    emp = db.query(Employee).filter_by(cpf="54397984808").first()
    assert emp is not None
    assert emp.nome == "Bianca Lima"
    assert emp.salario == 2050
    assert emp.status == StatusColaborador.ativo


def test_upsert_atualiza_salario(db):
    xlsx1 = make_xlsx([{"cpf": "54397984808", "nome": "Bianca Lima", "funcao": "AUX JR", "salario": 2050}])
    importar_colaboradores(xlsx1, db)

    xlsx2 = make_xlsx([{"cpf": "54397984808", "nome": "Bianca Lima", "funcao": "AUX JR", "salario": 2150}])
    res = importar_colaboradores(xlsx2, db)

    assert res.inseridos == 0
    assert res.atualizados == 1
    emp = db.query(Employee).filter_by(cpf="54397984808").first()
    assert emp.salario == 2150


def test_audit_log_registra_mudanca_de_salario(db):
    xlsx1 = make_xlsx([{"cpf": "54397984808", "nome": "Bianca", "funcao": "AUX", "salario": 2050}])
    importar_colaboradores(xlsx1, db)

    xlsx2 = make_xlsx([{"cpf": "54397984808", "nome": "Bianca", "funcao": "AUX", "salario": 2150}])
    importar_colaboradores(xlsx2, db)

    emp = db.query(Employee).filter_by(cpf="54397984808").first()
    audits = db.query(EmployeeAudit).filter_by(employee_id=emp.id, campo="salario").all()
    assert len(audits) == 1
    assert audits[0].valor_anterior == "2050.0"
    assert audits[0].valor_novo == "2150.0"
    assert audits[0].origem == OrigemAlteracao.importacao_planilha


def test_alerta_salario_variacao_grande(db):
    xlsx1 = make_xlsx([{"cpf": "54397984808", "nome": "Bianca", "funcao": "AUX", "salario": 2050}])
    importar_colaboradores(xlsx1, db)

    # Variação de >10% → deve gerar alerta
    xlsx2 = make_xlsx([{"cpf": "54397984808", "nome": "Bianca", "funcao": "AUX", "salario": 3000}])
    res = importar_colaboradores(xlsx2, db)

    assert len(res.alertas_salario) == 1
    assert res.alertas_salario[0]["cpf"] == "54397984808"

    emp = db.query(Employee).filter_by(cpf="54397984808").first()
    audit = db.query(EmployeeAudit).filter_by(employee_id=emp.id, campo="salario").first()
    assert audit.alerta_ativo is True


def test_sem_alerta_variacao_pequena(db):
    xlsx1 = make_xlsx([{"cpf": "54397984808", "nome": "Bianca", "funcao": "AUX", "salario": 2050}])
    importar_colaboradores(xlsx1, db)

    # Variação de ~1% → sem alerta
    xlsx2 = make_xlsx([{"cpf": "54397984808", "nome": "Bianca", "funcao": "AUX", "salario": 2070}])
    res = importar_colaboradores(xlsx2, db)

    assert res.alertas_salario == []
    emp = db.query(Employee).filter_by(cpf="54397984808").first()
    audit = db.query(EmployeeAudit).filter_by(employee_id=emp.id, campo="salario").first()
    assert audit.alerta_ativo is False


def test_salario_zero_bloqueado(db):
    xlsx = make_xlsx([{"cpf": "54397984808", "nome": "Bianca", "funcao": "AUX", "salario": 0}])
    res = importar_colaboradores(xlsx, db)
    assert res.inseridos == 0
    assert len(res.erros) == 1
    assert "bloqueado" in res.erros[0].lower()


def test_salario_negativo_bloqueado(db):
    xlsx = make_xlsx([{"cpf": "54397984808", "nome": "Bianca", "funcao": "AUX", "salario": -100}])
    res = importar_colaboradores(xlsx, db)
    assert res.inseridos == 0
    assert len(res.erros) == 1


def test_cpf_invalido_ignorado(db):
    xlsx = make_xlsx([{"cpf": "123", "nome": "X", "funcao": "AUX", "salario": 2050}])
    res = importar_colaboradores(xlsx, db)
    assert res.inseridos == 0
    assert len(res.erros) == 1


def test_soft_delete_via_demissao(db):
    xlsx1 = make_xlsx([{"cpf": "54397984808", "nome": "Bianca", "funcao": "AUX", "salario": 2050}])
    importar_colaboradores(xlsx1, db)

    xlsx2 = make_xlsx([{
        "cpf": "54397984808", "nome": "Bianca", "funcao": "AUX",
        "salario": 2050, "demissao": "31/03/2026"
    }])
    importar_colaboradores(xlsx2, db)

    emp = db.query(Employee).filter_by(cpf="54397984808").first()
    assert emp.status == StatusColaborador.inativo
    assert emp.data_demissao == datetime.date(2026, 3, 31)
    # Histórico preservado
    assert emp is not None


def test_multiplos_colaboradores(db):
    xlsx = make_xlsx([
        {"cpf": "54397984808", "nome": "Bianca", "funcao": "AUX JR", "salario": 2050},
        {"cpf": "49855600819", "nome": "Ana Clara", "funcao": "AUX PL", "salario": 2150},
        {"cpf": "32873456809", "nome": "Michelly", "funcao": "AUX JR", "salario": 2050},
    ])
    res = importar_colaboradores(xlsx, db)
    assert res.inseridos == 3
    assert db.query(Employee).count() == 3


def test_segunda_importacao_sem_alteracao_nao_conta_como_atualizado(db):
    xlsx = make_xlsx([{"cpf": "54397984808", "nome": "Bianca", "funcao": "AUX JR", "salario": 2050}])
    importar_colaboradores(xlsx, db)

    xlsx2 = make_xlsx([{"cpf": "54397984808", "nome": "Bianca", "funcao": "AUX JR", "salario": 2050}])
    res = importar_colaboradores(xlsx2, db)

    assert res.atualizados == 0
    assert res.inseridos == 0
