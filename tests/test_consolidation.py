"""
Testes da consolidação mensal de atestados por colaborador.

Regra: o FGI nunca é calculado por atestado individual.
A consolidação soma dias e horas do mês antes do cálculo.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from backend.services.consolidation import consolidar, AtestadoItem
from backend.services.fgi_calculator import calcular_fgi


def test_unico_atestado():
    atestados = [AtestadoItem(colaborador_cpf="111", dias=3, horas_decimal=0.0)]
    resultado = consolidar(atestados)
    assert len(resultado) == 1
    assert resultado[0].total_dias == 3
    assert resultado[0].total_horas == pytest.approx(0.0)


def test_multiplos_atestados_mesmo_colaborador():
    """Dois atestados no mês devem ser somados, não calculados separadamente."""
    atestados = [
        AtestadoItem(colaborador_cpf="111", dias=2, horas_decimal=1.5),
        AtestadoItem(colaborador_cpf="111", dias=3, horas_decimal=0.5),
    ]
    resultado = consolidar(atestados)
    assert len(resultado) == 1
    assert resultado[0].total_dias == 5
    assert resultado[0].total_horas == pytest.approx(2.0)


def test_multiplos_colaboradores():
    atestados = [
        AtestadoItem(colaborador_cpf="111", dias=1, horas_decimal=0.0),
        AtestadoItem(colaborador_cpf="222", dias=2, horas_decimal=1.0),
        AtestadoItem(colaborador_cpf="111", dias=2, horas_decimal=0.5),
    ]
    resultado = consolidar(atestados)
    assert len(resultado) == 2
    cpfs = {r.colaborador_cpf: r for r in resultado}
    assert cpfs["111"].total_dias == 3
    assert cpfs["111"].total_horas == pytest.approx(0.5)
    assert cpfs["222"].total_dias == 2
    assert cpfs["222"].total_horas == pytest.approx(1.0)


def test_lista_vazia():
    assert consolidar([]) == []


def test_resultado_correto_com_calculo():
    """
    Valida que calcular sobre o consolidado dá o mesmo resultado que
    a planilha (caso Jamille: 6 dias + 1h declarada).
    """
    atestados = [
        AtestadoItem(colaborador_cpf="50302224807", dias=4, horas_decimal=1.0),
        AtestadoItem(colaborador_cpf="50302224807", dias=2, horas_decimal=0.0),
    ]
    consolidado = consolidar(atestados)
    assert len(consolidado) == 1
    c = consolidado[0]
    assert c.total_dias == 6
    assert c.total_horas == pytest.approx(1.0)

    resultado = calcular_fgi(2050, c.total_dias, c.total_horas)
    assert resultado["total_fgi"] == pytest.approx(419.13, abs=0.01)
    assert resultado["total_final"] == pytest.approx(710.56, abs=0.01)
