"""
Motor de cálculo do Fato Gerador Incerto (FGI).

Replica fielmente a lógica da planilha Excel '2026.3 - FG INCERTO CEINT.xlsx':
  G = salario / HORAS_MES          (valor hora)
  H = G * HORAS_DIA                (valor dia)
  P = G * horas_declaradas         (custo de horas declaradas)
  Q = H * dias_atestado            (custo de dias de atestado)
  R = P + Q                        (Total FGI)
  V = R * (1 + ENCARGOS)           (Total sem imposto)
  X = V * (1 + IMPOSTOS)           (Total final)

Regras de precisão:
  - Todos os intermediários são calculados com float de precisão total.
  - Arredondamento para 2 casas decimais somente nos valores de saída do dict.
  - Isso replica o comportamento do Excel, que exibe valores arredondados
    mas usa precisão total nos cálculos encadeados.
"""

from backend.config import HORAS_MES, HORAS_DIA, ENCARGOS, IMPOSTOS


def calcular_fgi(
    salario: float,
    dias_atestado: int,
    horas_declaradas: float,
) -> dict:
    """
    Calcula o FGI de um colaborador para um período mensal consolidado.

    Args:
        salario:           Salário projetado mensal em reais.
        dias_atestado:     Total de dias de atestado no mês (já consolidado).
        horas_declaradas:  Total de horas declaradas no mês em decimal (já consolidado).
                           Usar hours_parser.parse_horas() antes de chamar esta função.

    Returns:
        dict com todas as colunas da planilha, arredondadas para 2 casas:
            valor_hora, valor_dia,
            custo_horas (col P), custo_dias (col Q),
            total_fgi (col R), com_encargos (col V), total_final (col X)

    Raises:
        ValueError se salario <= 0.
    """
    if salario <= 0:
        raise ValueError(f"Salário inválido: {salario}. Deve ser positivo.")

    valor_hora = salario / HORAS_MES
    valor_dia = valor_hora * HORAS_DIA

    custo_horas = valor_hora * horas_declaradas
    custo_dias = valor_dia * dias_atestado

    total_fgi = custo_horas + custo_dias
    com_encargos = total_fgi * (1 + ENCARGOS)
    total_final = com_encargos * (1 + IMPOSTOS)

    return {
        # Valores arredondados para 2 casas (exibição, Excel, linha por linha)
        "valor_hora": round(valor_hora, 2),
        "valor_dia": round(valor_dia, 2),
        "custo_horas": round(custo_horas, 2),
        "custo_dias": round(custo_dias, 2),
        "total_fgi": round(total_fgi, 2),
        "com_encargos": round(com_encargos, 2),
        "total_final": round(total_final, 2),
        # Valores brutos para acumulação correta nos totais
        # (somar arredondados gera diferença de centavos nos totais)
        "_total_fgi_raw": total_fgi,
        "_com_encargos_raw": com_encargos,
        "_total_final_raw": total_final,
    }
