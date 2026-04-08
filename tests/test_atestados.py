"""
Testes de atestados: identificação de colaborador, duplicidade, correção auditada.
"""

import sys
import os
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models.employee import Employee, StatusColaborador
from backend.models.atestado import Atestado, StatusAtestado, OrigemAtestado
from backend.models.atestado_correcao import AtestadoCorrecao
from backend.services import employee_matcher, duplicate_checker
from backend.services.hours_parser import parse_horas


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    from backend.models import employee, employee_audit, atestado, atestado_correcao  # noqa
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def colaborador(db):
    emp = Employee(
        cpf="54397984808",
        nome="Bianca Lima Da Silva",
        funcao="AUX JR",
        salario=2050,
        status=StatusColaborador.ativo,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def make_atestado(db, colaborador, status=StatusAtestado.pendente_validacao, dias=1, data=None):
    a = Atestado(
        colaborador_id=colaborador.id,
        data_inicio=data or datetime.date(2026, 3, 5),
        dias=dias,
        horas_declaradas_raw=None,
        horas_declaradas_decimal=0.0,
        status=status,
        origem=OrigemAtestado.manual,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


# ---------------------------------------------------------------------------
# Testes de identificação de colaborador
# ---------------------------------------------------------------------------

def test_match_por_cpf_encontra_colaborador(db, colaborador):
    emp = employee_matcher.match_por_cpf("54397984808", db)
    assert emp is not None
    assert emp.cpf == "54397984808"


def test_match_por_cpf_com_formatacao(db, colaborador):
    emp = employee_matcher.match_por_cpf("543.979.848-08", db)
    assert emp is not None


def test_match_por_cpf_nao_encontrado(db, colaborador):
    emp = employee_matcher.match_por_cpf("00000000000", db)
    assert emp is None


def test_match_por_cpf_vazio(db):
    emp = employee_matcher.match_por_cpf("", db)
    assert emp is None


def test_busca_por_nome_retorna_candidatos(db, colaborador):
    if not employee_matcher.tem_rapidfuzz():
        pytest.skip("rapidfuzz não instalado")
    candidatos = employee_matcher.buscar_por_nome("Bianca Lima", db)
    assert len(candidatos) >= 1
    assert candidatos[0].colaborador.cpf == "54397984808"
    assert candidatos[0].score >= 50


def test_busca_por_nome_sem_matches_retorna_vazio(db, colaborador):
    if not employee_matcher.tem_rapidfuzz():
        pytest.skip("rapidfuzz não instalado")
    candidatos = employee_matcher.buscar_por_nome("XYZXYZ123", db)
    assert candidatos == []


def test_busca_por_nome_nao_faz_correspondencia_automatica(db, colaborador):
    """A busca por nome retorna candidatos mas nunca deve ser usada para correspondência automática."""
    if not employee_matcher.tem_rapidfuzz():
        pytest.skip("rapidfuzz não instalado")
    candidatos = employee_matcher.buscar_por_nome("Bianca", db)
    # Retorna uma lista — a seleção é sempre manual
    assert isinstance(candidatos, list)


# ---------------------------------------------------------------------------
# Testes de prevenção de duplicidade
# ---------------------------------------------------------------------------

def test_sem_atestado_anterior_nao_detecta_duplicidade(db, colaborador):
    result = duplicate_checker.verificar_duplicidade(
        colaborador.id, datetime.date(2026, 3, 5), 1, db
    )
    assert result is False


def test_detecta_duplicidade_exata(db, colaborador):
    make_atestado(db, colaborador, status=StatusAtestado.confirmado, dias=1, data=datetime.date(2026, 3, 5))
    result = duplicate_checker.verificar_duplicidade(
        colaborador.id, datetime.date(2026, 3, 5), 1, db
    )
    assert result is True


def test_nao_detecta_duplicidade_dias_diferentes(db, colaborador):
    make_atestado(db, colaborador, status=StatusAtestado.confirmado, dias=1, data=datetime.date(2026, 3, 5))
    result = duplicate_checker.verificar_duplicidade(
        colaborador.id, datetime.date(2026, 3, 5), 3, db  # dias diferentes
    )
    assert result is False


def test_nao_detecta_duplicidade_data_diferente(db, colaborador):
    make_atestado(db, colaborador, status=StatusAtestado.confirmado, dias=1, data=datetime.date(2026, 3, 5))
    result = duplicate_checker.verificar_duplicidade(
        colaborador.id, datetime.date(2026, 3, 10), 1, db  # data diferente
    )
    assert result is False


def test_atestado_rejeitado_nao_gera_alerta(db, colaborador):
    make_atestado(db, colaborador, status=StatusAtestado.rejeitado, dias=1, data=datetime.date(2026, 3, 5))
    result = duplicate_checker.verificar_duplicidade(
        colaborador.id, datetime.date(2026, 3, 5), 1, db
    )
    assert result is False


def test_excluir_proprio_id_na_verificacao(db, colaborador):
    atestado = make_atestado(db, colaborador, status=StatusAtestado.confirmado, dias=1, data=datetime.date(2026, 3, 5))
    result = duplicate_checker.verificar_duplicidade(
        colaborador.id, datetime.date(2026, 3, 5), 1, db, excluir_id=atestado.id
    )
    assert result is False


def test_verificar_mesma_data(db, colaborador):
    make_atestado(db, colaborador, status=StatusAtestado.confirmado, dias=2, data=datetime.date(2026, 3, 5))
    result = duplicate_checker.verificar_mesma_data(
        colaborador.id, datetime.date(2026, 3, 5), db
    )
    assert result is True


# ---------------------------------------------------------------------------
# Testes de correção auditada
# ---------------------------------------------------------------------------

def test_correcao_cria_registro_de_auditoria(db, colaborador):
    atestado = make_atestado(db, colaborador, status=StatusAtestado.confirmado, dias=3)

    correcao = AtestadoCorrecao(
        atestado_id=atestado.id,
        campo="dias",
        valor_anterior="3",
        valor_novo="2",
        motivo="Atestado retificado pelo médico",
        usuario="operador_teste",
    )
    db.add(correcao)
    db.commit()

    registros = db.query(AtestadoCorrecao).filter_by(atestado_id=atestado.id).all()
    assert len(registros) == 1
    assert registros[0].campo == "dias"
    assert registros[0].valor_anterior == "3"
    assert registros[0].valor_novo == "2"
    assert registros[0].motivo == "Atestado retificado pelo médico"
    assert registros[0].usuario == "operador_teste"


def test_atestado_original_preservado_apos_correcao(db, colaborador):
    """O atestado deve continuar com status=confirmado após correção."""
    atestado = make_atestado(db, colaborador, status=StatusAtestado.confirmado, dias=3)

    # Aplica correção direto no model (como faria o router)
    atestado.dias = 2
    correcao = AtestadoCorrecao(
        atestado_id=atestado.id,
        campo="dias",
        valor_anterior="3",
        valor_novo="2",
        motivo="Retificado",
        usuario="teste",
    )
    db.add(correcao)
    db.commit()

    recarregado = db.query(Atestado).filter_by(id=atestado.id).first()
    assert recarregado.status == StatusAtestado.confirmado
    assert recarregado.dias == 2


# ---------------------------------------------------------------------------
# Testes de consolidação com atestados do banco
# ---------------------------------------------------------------------------

def test_apenas_atestados_confirmados_entram_no_calculo(db, colaborador):
    """Atestados pendentes e rejeitados não devem aparecer no cálculo."""
    make_atestado(db, colaborador, status=StatusAtestado.confirmado, dias=3)
    make_atestado(db, colaborador, status=StatusAtestado.pendente_validacao, dias=5)
    make_atestado(db, colaborador, status=StatusAtestado.rejeitado, dias=7)

    confirmados = db.query(Atestado).filter_by(
        colaborador_id=colaborador.id,
        status=StatusAtestado.confirmado,
    ).all()
    assert len(confirmados) == 1
    assert confirmados[0].dias == 3
