# Constantes do cálculo do Fato Gerador Incerto (FGI)
# Replicam exatamente os valores hardcoded na planilha Excel de referência.
# Alterar apenas com aprovação formal, pois impacta diretamente o faturamento.

# Base de cálculo salarial
HORAS_MES: float = 220       # Horas de trabalho mensais (divisor do salário → valor hora)
HORAS_DIA: float = 7.33      # Horas por dia útil (multiplicador → valor dia)

# Multiplicadores de custo
ENCARGOS: float = 0.622      # Overhead sobre o FGI bruto (INSS patronal, FGTS, férias, 13º, etc.)
IMPOSTOS: float = 0.0452     # Tributos aplicados sobre o total com encargos

# Thresholds de alerta de variação salarial (usados em import_service)
SALARIO_ALERT_PCT: float = 0.10   # Alerta se variação percentual > 10%
SALARIO_ALERT_ABS: float = 200.0  # Alerta se variação absoluta > R$ 200
