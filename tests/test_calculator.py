"""
Testes de validação do motor de cálculo FGI contra dados reais de março/2026 (CEINT).

Critério de aceite: todos os valores devem coincidir com a planilha original,
centavo a centavo, após arredondamento para 2 casas decimais.

Dados extraídos diretamente de: 2026.3 - FG INCERTO CEINT.xlsx
  Total FGI    (col R, soma): R$  7.173,76
  Com Encargos (col V, soma): R$ 11.635,84
  Total Final  (col X, soma): R$ 12.161,78
"""

import sys
import os
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from backend.services.fgi_calculator import calcular_fgi
from backend.services.hours_parser import parse_horas
from backend.services.consolidation import consolidar, AtestadoItem


# ---------------------------------------------------------------------------
# Dados reais extraídos da planilha (março/2026)
# Campos: (nome, salario, dias, horas_raw, total_fgi_esperado, total_final_esperado)
# horas_raw: datetime.time ou None conforme lido da planilha
# ---------------------------------------------------------------------------
DADOS_MAR26 = [
    # nome                              sal    dias  horas_raw              fgi_bruto   total_final
    ("ANA CLARA DE MORAES",            2150,  1,    None,                  71.63,      121.44),
    ("AURA CRISTINA VALLES RODRIGUEZ", 2050,  0,    datetime.time(1, 50),  17.08,      28.96),
    ("BIANCA LIMA DA SILVA",           2050,  1,    datetime.time(5, 13),  116.91,     198.20),
    ("CARLA VIVIANE VICENTE",          2050,  0,    datetime.time(3, 0),   27.95,      47.39),
    ("CELIA PEREIRA KNUPFER RODRIGUES",2150,  0,    datetime.time(4, 0),   39.09,      66.27),
    ("ELEDIANE FATIMA DA SILVA SOUZA", 2050,  0,    datetime.time(3, 30),  32.61,      55.29),
    ("FABIO HENRIQUE COSTA",           2050,  3,    None,                  204.91,     347.38),
    ("FELIPE AREDES SANTOS",           2050,  2,    None,                  136.60,     231.59),
    ("FERNANDO FARIA LIMA",            2050,  12,   None,                  819.63,     1389.53),
    ("FERNANDO PEREIRA DA SILVA",      2050,  2,    None,                  136.60,     231.59),
    ("GABRIEL LUCAS MENDES COTRIN",    2050,  0,    datetime.time(1, 30),  13.98,      23.70),
    ("GABRIEL PRADO JUSTO",            2050,  1,    None,                  68.30,      115.79),
    ("JAMILLE DE SOUZA FERREIRA",      2050,  6,    datetime.time(1, 0),   419.13,     710.56),
    ("JEFERSON VIEIRA DE FRANCA",      2050,  0,    datetime.time(0, 52),  8.08,       13.69),
    ("KLEIBER DO NASCIMENTO LUCAS",    2050,  2,    None,                  136.60,     231.59),
    ("LETICIA PEREIRA DE ALMEIDA",     2050,  0,    datetime.time(4, 0),   37.27,      63.19),
    ("LUANA FERREIRA DE SOUZA",        2050,  5,    None,                  341.51,     578.97),
    ("MARIA LEONICE DE ANDRADE SILVA", 2150,  2,    None,                  143.27,     242.88),
    ("MARISA SOUZA SILVA",             2050,  0,    datetime.time(1, 53),  17.55,      29.75),
    ("MAYARA APARECIDA SANTOS",        2050,  1,    None,                  68.30,      115.79),
    ("MICHELLY VICENTE SOUZA",         2050,  15,   None,                  1024.53,    1736.91),
    ("PRISCILA NICODEMOS DA SILVA",    2500,  10,   datetime.time(2, 0),   855.68,     1450.65),
    ("RAQUEL DA SILVA LIMA",           2150,  7,    datetime.time(2, 20),  524.24,     888.75),
    ("RENATA NAIR DE CARVALHO SILVA",  2050,  3,    None,                  204.91,     347.38),
    ("ROSEANE DA SILVA LIMA",          2050,  0,    datetime.time(2, 36),  24.23,      41.07),
    ("ROSELI GOMES DA SILVA",          2150,  2,    None,                  143.27,     242.88),
    ("RUBEM FERREIRA DA CRUZ",         2150,  0,    datetime.time(4, 0),   39.09,      66.27),
    ("SILVANA DOS REIS SILVA",         2150,  0,    datetime.time(2, 35),  25.25,      42.80),
    ("TAMILES DE JESUS SANTOS",        2050,  6,    datetime.time(4, 58),  456.09,     773.22),
    ("TAMIRES OLIVEIRA ROCHA",         2050,  1,    None,                  68.30,      115.79),
    ("THAIS SOARES GOMES",             2050,  1,    datetime.time(5, 17),  117.53,     199.26),
    ("THAMIRES KAWANY EGYDIO FERREIRA",2050,  2,    None,                  136.60,     231.59),
    ("VIVIANE MARIA DA SILVA",         2050,  3,    datetime.time(1, 30),  218.88,     371.08),
    ("WALKER SOUZA FERNANDES CAMPOS",  2050,  7,    None,                  478.12,     810.56),
]

# Totais consolidados esperados da planilha
TOTAL_FGI_ESPERADO     = 7173.76
TOTAL_COM_ENC_ESPERADO = 11635.84
TOTAL_FINAL_ESPERADO   = 12161.78


# ---------------------------------------------------------------------------
# Testes individuais
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nome,salario,dias,horas_raw,fgi_esperado,final_esperado", DADOS_MAR26)
def test_total_fgi_por_colaborador(nome, salario, dias, horas_raw, fgi_esperado, final_esperado):
    """Verifica total_fgi (col R) de cada colaborador."""
    horas = parse_horas(horas_raw)
    resultado = calcular_fgi(salario, dias, horas)
    assert resultado["total_fgi"] == pytest.approx(fgi_esperado, abs=0.01), (
        f"{nome}: total_fgi esperado {fgi_esperado}, obtido {resultado['total_fgi']}"
    )


@pytest.mark.parametrize("nome,salario,dias,horas_raw,fgi_esperado,final_esperado", DADOS_MAR26)
def test_total_final_por_colaborador(nome, salario, dias, horas_raw, fgi_esperado, final_esperado):
    """Verifica total_final (col X) de cada colaborador."""
    horas = parse_horas(horas_raw)
    resultado = calcular_fgi(salario, dias, horas)
    assert resultado["total_final"] == pytest.approx(final_esperado, abs=0.01), (
        f"{nome}: total_final esperado {final_esperado}, obtido {resultado['total_final']}"
    )


# ---------------------------------------------------------------------------
# Teste de totais consolidados do mês
# ---------------------------------------------------------------------------

def test_totais_consolidados_marco_2026():
    """
    Soma os valores de todos os 34 colaboradores e valida contra os totais
    da linha de total da planilha original.
    """
    soma_fgi = 0.0
    soma_enc = 0.0
    soma_final = 0.0

    for nome, salario, dias, horas_raw, _, _ in DADOS_MAR26:
        horas = parse_horas(horas_raw)
        r = calcular_fgi(salario, dias, horas)
        soma_fgi += r["total_fgi"]
        soma_enc += r["com_encargos"]
        soma_final += r["total_final"]

    assert soma_fgi == pytest.approx(TOTAL_FGI_ESPERADO, abs=0.05), (
        f"Total FGI: esperado {TOTAL_FGI_ESPERADO}, obtido {round(soma_fgi, 2)}"
    )
    assert soma_enc == pytest.approx(TOTAL_COM_ENC_ESPERADO, abs=0.05), (
        f"Total c/ encargos: esperado {TOTAL_COM_ENC_ESPERADO}, obtido {round(soma_enc, 2)}"
    )
    assert soma_final == pytest.approx(TOTAL_FINAL_ESPERADO, abs=0.05), (
        f"Total final: esperado {TOTAL_FINAL_ESPERADO}, obtido {round(soma_final, 2)}"
    )
