"""
Testes do parser de horas HH:MM → decimal.
"""

import sys
import os
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from backend.services.hours_parser import parse_horas


def test_string_hora_inteira():
    assert parse_horas("01:00") == pytest.approx(1.0)

def test_string_trinta_minutos():
    assert parse_horas("01:30") == pytest.approx(1.5)

def test_string_nao_e_virgula_decimal():
    # "01:30" deve ser 1.5, nunca 1.30
    assert parse_horas("01:30") != 1.30

def test_string_cinquenta_e_dois_minutos():
    # Jeferson: 0:52 = 52/60 = 0.8666...
    assert parse_horas("00:52") == pytest.approx(52 / 60)

def test_string_cinco_horas_treze_minutos():
    # Bianca: 5:13 = 5 + 13/60 = 5.21666...
    assert parse_horas("05:13") == pytest.approx(5 + 13 / 60)

def test_datetime_time():
    assert parse_horas(datetime.time(1, 30)) == pytest.approx(1.5)

def test_datetime_time_zero():
    assert parse_horas(datetime.time(0, 0)) == pytest.approx(0.0)

def test_none_retorna_zero():
    assert parse_horas(None) == 0.0

def test_string_vazia_retorna_zero():
    assert parse_horas("") == 0.0

def test_formato_invalido_levanta_erro():
    with pytest.raises(ValueError):
        parse_horas("130")

def test_minutos_invalidos_levanta_erro():
    with pytest.raises(ValueError):
        parse_horas("01:60")

def test_tipo_invalido_levanta_erro():
    with pytest.raises(TypeError):
        parse_horas(130)
