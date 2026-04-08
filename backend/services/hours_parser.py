"""
Conversão de horas declaradas no formato HH:MM para decimal.

Regra crítica: "01:30" → 1.5  (não 1.30)
A divisão dos minutos por 60 é obrigatória.
"""

import datetime
from typing import Union


def parse_horas(valor: Union[str, datetime.time, None]) -> float:
    """
    Converte horas declaradas para decimal.

    Aceita:
      - str "HH:MM"          ex: "01:30" → 1.5
      - datetime.time        ex: time(1, 30) → 1.5
      - None / vazio         → 0.0

    Raises:
      ValueError se o formato string não for HH:MM válido.
    """
    if valor is None:
        return 0.0

    if isinstance(valor, datetime.time):
        return valor.hour + valor.minute / 60

    if isinstance(valor, str):
        valor = valor.strip()
        if not valor:
            return 0.0
        partes = valor.split(":")
        if len(partes) != 2:
            raise ValueError(f"Formato de hora inválido: '{valor}'. Use HH:MM.")
        try:
            horas = int(partes[0])
            minutos = int(partes[1])
        except ValueError:
            raise ValueError(f"Formato de hora inválido: '{valor}'. Use HH:MM.")
        if minutos < 0 or minutos >= 60:
            raise ValueError(f"Minutos fora do intervalo válido (0-59): '{valor}'.")
        return horas + minutos / 60

    raise TypeError(f"Tipo não suportado para parse_horas: {type(valor)}")
