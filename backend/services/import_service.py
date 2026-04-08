"""
Importação de colaboradores via planilha Excel da contabilidade.

Regras:
  - CPF é a chave de upsert. Sem CPF no registro → erro, linha ignorada.
  - Campos atualizados: nome, funcao, salario, data_demissao, status.
  - Alterações de salário são registradas em EmployeeAudit sempre.
  - Variações acima do threshold (config.py) geram alerta_ativo=True.
  - Salário <= 0 bloqueia o registro com erro explícito (nunca silencioso).
  - Demitidos: status → inativo (soft delete), histórico preservado.
  - Novos colaboradores: inseridos com status ativo.

Formato esperado da planilha (colunas obrigatórias, nomes flexíveis via mapeamento):
  CPF | NOME | FUNÇÃO | SALÁRIO | DATA ADMISSÃO | DATA DEMISSÃO (opcional)

O serviço detecta os cabeçalhos automaticamente por similaridade (case-insensitive).
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import openpyxl
import pandas as pd
from sqlalchemy.orm import Session

from backend.config import SALARIO_ALERT_ABS, SALARIO_ALERT_PCT
from backend.models.employee import Employee, StatusColaborador
from backend.models.employee_audit import EmployeeAudit, OrigemAlteracao


# ---------------------------------------------------------------------------
# Mapeamento de cabeçalhos aceitos (normalizado → campo interno)
# ---------------------------------------------------------------------------
HEADER_MAP = {
    "cpf": "cpf",
    "nome": "nome",
    "funcao": "funcao",
    "função": "funcao",
    "salario": "salario",
    "salário": "salario",
    "salario projetado": "salario",
    "salário projetado": "salario",
    "admissao": "data_admissao",
    "admissão": "data_admissao",
    "data admissao": "data_admissao",
    "data admissão": "data_admissao",
    "demissao": "data_demissao",
    "demissão": "data_demissao",
    "data demissao": "data_demissao",
    "data demissão": "data_demissao",
}

CAMPOS_OBRIGATORIOS = {"cpf", "nome", "funcao", "salario"}


# ---------------------------------------------------------------------------
# Resultado da importação
# ---------------------------------------------------------------------------
@dataclass
class ImportResult:
    inseridos: int = 0
    atualizados: int = 0
    erros: list = field(default_factory=list)
    alertas_salario: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalizar_cpf(cpf: str) -> str:
    """Remove pontos, traços e espaços. Retorna somente dígitos."""
    return re.sub(r"\D", "", str(cpf))


def _parse_date(valor) -> Optional[date]:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, (datetime, pd.Timestamp)):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        valor = valor.strip()
        if not valor:
            return None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(valor, fmt).date()
            except ValueError:
                continue
    return None


def _variacao_relevante(anterior: float, novo: float) -> bool:
    if anterior == 0:
        return True
    pct = abs(novo - anterior) / anterior
    abso = abs(novo - anterior)
    return pct > SALARIO_ALERT_PCT or abso > SALARIO_ALERT_ABS


# ---------------------------------------------------------------------------
# Leitura e detecção de cabeçalhos
# ---------------------------------------------------------------------------
def _detectar_cabecalhos(df: pd.DataFrame) -> dict[str, str]:
    """Mapeia colunas do DataFrame para nomes internos via HEADER_MAP."""
    mapeamento = {}
    for col in df.columns:
        chave = str(col).strip().lower()
        if chave in HEADER_MAP:
            mapeamento[HEADER_MAP[chave]] = col
    return mapeamento


def _ler_planilha(caminho_ou_bytes) -> pd.DataFrame:
    """Lê a primeira aba da planilha, pulando linhas vazias no início."""
    # Tenta encontrar a linha de cabeçalho (primeira linha com ≥3 células não-nulas)
    wb = openpyxl.load_workbook(caminho_ou_bytes, data_only=True)
    ws = wb.active
    header_row = None
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        nao_nulos = sum(1 for c in row if c is not None)
        if nao_nulos >= 3:
            header_row = i
            break
    if header_row is None:
        raise ValueError("Não foi possível identificar a linha de cabeçalho na planilha.")

    df = pd.read_excel(
        caminho_ou_bytes,
        header=header_row,
        dtype=str,
    )
    df.dropna(how="all", inplace=True)
    return df


# ---------------------------------------------------------------------------
# Função principal de importação
# ---------------------------------------------------------------------------
def importar_colaboradores(
    caminho_ou_bytes,
    db: Session,
    origem: OrigemAlteracao = OrigemAlteracao.importacao_planilha,
) -> ImportResult:
    """
    Lê planilha e aplica upsert por CPF no banco de dados.

    Args:
        caminho_ou_bytes: Caminho para o arquivo Excel ou objeto bytes/BytesIO.
        db:              Sessão SQLAlchemy ativa.
        origem:          Origem registrada no audit log.

    Returns:
        ImportResult com contagens e listas de erros/alertas.
    """
    resultado = ImportResult()

    df = _ler_planilha(caminho_ou_bytes)
    mapa = _detectar_cabecalhos(df)

    ausentes = CAMPOS_OBRIGATORIOS - set(mapa.keys())
    if ausentes:
        resultado.erros.append(
            f"Planilha não contém colunas obrigatórias: {', '.join(ausentes)}. "
            f"Colunas encontradas: {list(df.columns)}"
        )
        return resultado

    for idx, row in df.iterrows():
        linha_num = idx + 2  # +2: cabeçalho + índice base-0

        # --- CPF ---
        cpf_raw = row.get(mapa["cpf"], "")
        cpf = _normalizar_cpf(cpf_raw)
        if len(cpf) not in (11, 14):
            resultado.erros.append(f"Linha {linha_num}: CPF inválido '{cpf_raw}' — ignorado.")
            continue

        # --- Nome ---
        nome = str(row.get(mapa["nome"], "")).strip()
        if not nome:
            resultado.erros.append(f"Linha {linha_num} (CPF {cpf}): nome vazio — ignorado.")
            continue

        # --- Função ---
        funcao = str(row.get(mapa["funcao"], "")).strip()
        if not funcao:
            resultado.erros.append(f"Linha {linha_num} (CPF {cpf}): função vazia — ignorado.")
            continue

        # --- Salário ---
        try:
            salario = float(str(row.get(mapa["salario"], "0")).replace(",", ".").strip())
        except ValueError:
            resultado.erros.append(
                f"Linha {linha_num} (CPF {cpf}): salário inválido '{row.get(mapa['salario'])}' — ignorado."
            )
            continue

        if salario <= 0:
            resultado.erros.append(
                f"Linha {linha_num} (CPF {cpf}): salário <= 0 ({salario}) — "
                "bloqueado para evitar impacto no cálculo."
            )
            continue

        # --- Datas ---
        data_admissao = _parse_date(row.get(mapa.get("data_admissao"))) if "data_admissao" in mapa else None
        data_demissao = _parse_date(row.get(mapa.get("data_demissao"))) if "data_demissao" in mapa else None
        novo_status = StatusColaborador.inativo if data_demissao else StatusColaborador.ativo

        # --- Upsert ---
        existente = db.query(Employee).filter_by(cpf=cpf).first()

        if existente is None:
            # Inserção
            novo = Employee(
                cpf=cpf,
                nome=nome,
                funcao=funcao,
                salario=salario,
                data_admissao=data_admissao,
                data_demissao=data_demissao,
                status=novo_status,
            )
            db.add(novo)
            db.flush()  # obtém ID antes do audit
            resultado.inseridos += 1
        else:
            # Atualização — registrar alterações de campos críticos
            alteracoes = {}
            if existente.nome != nome:
                alteracoes["nome"] = (existente.nome, nome)
                existente.nome = nome
            if existente.funcao != funcao:
                alteracoes["funcao"] = (existente.funcao, funcao)
                existente.funcao = funcao
            if existente.salario != salario:
                alteracoes["salario"] = (existente.salario, salario)
                existente.salario = salario
            if data_demissao and existente.data_demissao != data_demissao:
                alteracoes["data_demissao"] = (str(existente.data_demissao), str(data_demissao))
                existente.data_demissao = data_demissao
            if existente.status != novo_status:
                alteracoes["status"] = (existente.status.value, novo_status.value)
                existente.status = novo_status

            for campo, (anterior, novo_val) in alteracoes.items():
                eh_salario = campo == "salario"
                alerta = eh_salario and _variacao_relevante(float(anterior or 0), float(novo_val))

                audit = EmployeeAudit(
                    employee_id=existente.id,
                    campo=campo,
                    valor_anterior=str(anterior),
                    valor_novo=str(novo_val),
                    origem=origem,
                    alerta_ativo=alerta,
                )
                db.add(audit)

                if alerta:
                    resultado.alertas_salario.append({
                        "cpf": cpf,
                        "nome": nome,
                        "salario_anterior": anterior,
                        "salario_novo": novo_val,
                    })

            if alteracoes:
                resultado.atualizados += 1

    db.commit()
    return resultado
