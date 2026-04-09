"""
Importação de colaboradores via planilha Excel da contabilidade (KWAY MATRIZ).

Regras:
  - Importa APENAS colaboradores dos contratos "CORREIOS - CEINT" e "CORREIOS - CLI".
  - CPF é a chave de upsert. Sem CPF no registro → erro, linha ignorada.
  - Campos atualizados: nome, funcao, salario, contrato, data_admissao, data_demissao, status.
  - Alterações de salário são registradas em EmployeeAudit sempre.
  - Variações acima do threshold (config.py) geram alerta_ativo=True.
  - Salário <= 0 bloqueia o registro com erro explícito (nunca silencioso).
  - Demitidos: coluna "Demissão" preenchida → status inativo, histórico preservado.
  - Ativos: coluna "Demissão" vazia → status ativo.

Formato esperado (planilha ATIVOS E DEM KWAY MATRIZ):
  Empresa | Nome da Empresa | Funcionário | Matricula eSocial | Nome do Funcionário
  | Função | CBO | Salário Base | Departamento | Admissão | Demissão | ...
  | CPF | ...

Contratos importados:
  - CORREIOS - CEINT
  - CORREIOS - CLI
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from backend.config import SALARIO_ALERT_ABS, SALARIO_ALERT_PCT
from backend.models.employee import Employee, StatusColaborador
from backend.models.employee_audit import EmployeeAudit, OrigemAlteracao


# ---------------------------------------------------------------------------
# Contratos aceitos na importação
# ---------------------------------------------------------------------------
CONTRATOS_ACEITOS = {"CORREIOS - CEINT", "CORREIOS - CLI"}

# Mapeamento: nome interno → possíveis nomes de coluna na planilha (lowercase sem acento)
HEADER_ALIASES = {
    "nome":           ["nome do funcionario", "nome funcionario", "nome"],
    "funcao":         ["funcao", "função"],
    "salario":        ["salario base", "salario", "salário base", "salário", "salario projetado"],
    "contrato":       ["departamento"],
    "data_admissao":  ["admissao", "admissão", "data admissao", "data admissão"],
    "data_demissao":  ["demissao", "demissão", "data demissao", "data demissão"],
    "cpf":            ["cpf"],
}

CAMPOS_OBRIGATORIOS = {"cpf", "nome", "funcao", "salario", "contrato"}


# ---------------------------------------------------------------------------
# Resultado da importação
# ---------------------------------------------------------------------------
@dataclass
class ImportResult:
    inseridos: int = 0
    atualizados: int = 0
    ignorados_outros_contratos: int = 0
    erros: list = field(default_factory=list)
    alertas_salario: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalizar_texto(s: str) -> str:
    """Minúsculas, remove acentos simples para comparação."""
    return (
        str(s).strip().lower()
        .replace("á", "a").replace("ã", "a").replace("â", "a").replace("à", "a")
        .replace("é", "e").replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o").replace("õ", "o").replace("ô", "o")
        .replace("ú", "u").replace("ü", "u")
        .replace("ç", "c")
    )


def _normalizar_cpf(cpf) -> str:
    """Remove pontos, traços e espaços. Retorna somente dígitos."""
    return re.sub(r"\D", "", str(cpf))


def _parse_date(valor, datemode: int = 0) -> Optional[date]:
    """
    Converte vários formatos para date:
      - float/int: número serial Excel (xlrd)
      - datetime / pd.Timestamp
      - date
      - string: tenta múltiplos formatos
      - vazio / NaN: None
    """
    if valor is None:
        return None
    if isinstance(valor, float):
        if pd.isna(valor):
            return None
        if valor == 0.0:
            return None
        # Número serial do Excel — xlrd datemode (0 = 1900, 1 = 1904)
        try:
            import xlrd
            return xlrd.xldate_as_datetime(valor, datemode).date()
        except Exception:
            return None
    if isinstance(valor, (datetime, pd.Timestamp)):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        valor = valor.strip()
        if not valor:
            return None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y",
                    "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
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
    """
    Mapeia campo interno → coluna real do DataFrame.
    Usa HEADER_ALIASES com normalização de texto.
    """
    # Índice reverso: alias normalizado → campo interno
    alias_map: dict[str, str] = {}
    for campo, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            alias_map[_normalizar_texto(alias)] = campo

    mapeamento: dict[str, str] = {}
    for col in df.columns:
        chave = _normalizar_texto(str(col))
        if chave in alias_map:
            campo_interno = alias_map[chave]
            if campo_interno not in mapeamento:  # primeira ocorrência vence
                mapeamento[campo_interno] = col
    return mapeamento


def _ler_planilha(caminho_ou_bytes, filename: str = "") -> tuple[pd.DataFrame, int]:
    """
    Lê a primeira aba da planilha.
    Suporta .xls (xlrd) e .xlsx (openpyxl).
    Retorna (DataFrame, datemode) — datemode necessário para converter seriais do Excel.
    """
    is_xls = str(filename).lower().endswith(".xls") if filename else False

    if is_xls:
        import xlrd
        # Detecta datemode para converter datas corretamente
        if hasattr(caminho_ou_bytes, "read"):
            data = caminho_ou_bytes.read()
            wb = xlrd.open_workbook(file_contents=data)
            # Relê como BytesIO para o pandas
            import io
            caminho_ou_bytes = io.BytesIO(data)
        else:
            wb = xlrd.open_workbook(caminho_ou_bytes)
        datemode = wb.datemode

        df = pd.read_excel(caminho_ou_bytes, engine="xlrd", dtype=str)
    else:
        datemode = 0
        df = pd.read_excel(caminho_ou_bytes, engine="openpyxl", dtype=str)

    df.dropna(how="all", inplace=True)
    return df, datemode


# ---------------------------------------------------------------------------
# Função principal de importação
# ---------------------------------------------------------------------------
def importar_colaboradores(
    caminho_ou_bytes,
    db: Session,
    origem: OrigemAlteracao = OrigemAlteracao.importacao_planilha,
    filename: str = "",
) -> ImportResult:
    """
    Lê planilha da contabilidade (KWAY MATRIZ) e aplica upsert por CPF.
    Importa apenas colaboradores dos contratos CORREIOS - CEINT e CORREIOS - CLI.

    Args:
        caminho_ou_bytes: Caminho para o arquivo ou objeto bytes/BytesIO.
        db:               Sessão SQLAlchemy ativa.
        origem:           Origem registrada no audit log.
        filename:         Nome original do arquivo (usado para detectar .xls vs .xlsx).

    Returns:
        ImportResult com contagens e listas de erros/alertas.
    """
    resultado = ImportResult()

    df, datemode = _ler_planilha(caminho_ou_bytes, filename)
    mapa = _detectar_cabecalhos(df)

    ausentes = CAMPOS_OBRIGATORIOS - set(mapa.keys())
    if ausentes:
        resultado.erros.append(
            f"Planilha não contém colunas obrigatórias: {', '.join(sorted(ausentes))}. "
            f"Colunas encontradas: {list(df.columns[:15])}"
        )
        return resultado

    for idx, row in df.iterrows():
        linha_num = idx + 2  # +2: cabeçalho + índice base-0

        # --- Filtro por contrato ---
        contrato_raw = str(row.get(mapa["contrato"], "")).strip()
        contrato = contrato_raw.upper()
        if contrato not in CONTRATOS_ACEITOS:
            resultado.ignorados_outros_contratos += 1
            continue

        # --- CPF ---
        cpf_raw = row.get(mapa["cpf"], "")
        cpf = _normalizar_cpf(cpf_raw)
        if len(cpf) not in (11, 14):
            resultado.erros.append(f"Linha {linha_num}: CPF inválido '{cpf_raw}' [{contrato}] — ignorado.")
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
        salario_raw = row.get(mapa["salario"], "0")
        try:
            salario = float(str(salario_raw).replace(",", ".").strip())
        except (ValueError, TypeError):
            resultado.erros.append(
                f"Linha {linha_num} (CPF {cpf}): salário inválido '{salario_raw}' — ignorado."
            )
            continue

        if salario <= 0:
            resultado.erros.append(
                f"Linha {linha_num} (CPF {cpf}): salário <= 0 ({salario}) — "
                "bloqueado para evitar impacto no cálculo."
            )
            continue

        # --- Datas ---
        adm_raw = row.get(mapa.get("data_admissao")) if "data_admissao" in mapa else None
        dem_raw = row.get(mapa.get("data_demissao")) if "data_demissao" in mapa else None

        # Valores lidos como string pelo dtype=str; tenta converter para float se for serial
        def _to_numeric_or_str(val):
            if val is None:
                return None
            s = str(val).strip()
            if not s or s.lower() in ("nan", "none", ""):
                return None
            try:
                return float(s)
            except ValueError:
                return s

        data_admissao = _parse_date(_to_numeric_or_str(adm_raw), datemode)
        data_demissao = _parse_date(_to_numeric_or_str(dem_raw), datemode)
        novo_status = StatusColaborador.inativo if data_demissao else StatusColaborador.ativo

        # --- Upsert ---
        existente = db.query(Employee).filter_by(cpf=cpf).first()

        if existente is None:
            novo = Employee(
                cpf=cpf,
                nome=nome,
                funcao=funcao,
                salario=salario,
                contrato=contrato_raw,
                data_admissao=data_admissao,
                data_demissao=data_demissao,
                status=novo_status,
            )
            db.add(novo)
            db.flush()
            resultado.inseridos += 1
        else:
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
            if existente.contrato != contrato_raw:
                alteracoes["contrato"] = (existente.contrato, contrato_raw)
                existente.contrato = contrato_raw
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
