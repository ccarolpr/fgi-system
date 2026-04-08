"""
Extração de dados de atestados médicos a partir de PDFs.

Estratégia em duas camadas:
  1. pdfplumber — extrai texto de PDFs com camada de texto (digitais)
  2. pytesseract — OCR sobre imagem renderizada (PDFs escaneados/fotos)

O resultado é SEMPRE uma sugestão. Nunca é gravado sem revisão humana.

Campos extraídos (quando presentes no documento):
  - nome       → nome do paciente
  - cpf        → CPF do paciente (somente dígitos)
  - data_inicio → data de início do afastamento
  - dias        → quantidade de dias
  - horas       → horas declaradas em HH:MM (se houver)
  - cid         → código CID-10
  - raw_text    → texto bruto completo para auditoria
"""

import re
from datetime import date, datetime
from typing import Optional
import io

try:
    import pdfplumber
    _HAS_PDFPLUMBER = True
except ImportError:
    _HAS_PDFPLUMBER = False

try:
    import pytesseract
    from PIL import Image
    _HAS_TESSERACT = True
except ImportError:
    _HAS_TESSERACT = False


# ---------------------------------------------------------------------------
# Resultado da extração
# ---------------------------------------------------------------------------
class OcrResult:
    def __init__(self):
        self.nome: Optional[str] = None
        self.cpf: Optional[str] = None
        self.data_inicio: Optional[date] = None
        self.dias: Optional[int] = None
        self.horas: Optional[str] = None     # formato HH:MM
        self.cid: Optional[str] = None
        self.raw_text: str = ""
        self.confianca: str = "baixa"        # "alta" | "media" | "baixa"
        self.avisos: list[str] = []

    def to_dict(self) -> dict:
        return {
            "nome": self.nome,
            "cpf": self.cpf,
            "data_inicio": self.data_inicio.isoformat() if self.data_inicio else None,
            "dias": self.dias,
            "horas": self.horas,
            "cid": self.cid,
            "raw_text": self.raw_text,
            "confianca": self.confianca,
            "avisos": self.avisos,
        }


# ---------------------------------------------------------------------------
# Extração de texto do PDF
# ---------------------------------------------------------------------------
def _extrair_texto_pdfplumber(conteudo: bytes) -> str:
    if not _HAS_PDFPLUMBER:
        return ""
    try:
        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            partes = []
            for page in pdf.pages:
                texto = page.extract_text()
                if texto:
                    partes.append(texto)
            return "\n".join(partes)
    except Exception:
        return ""


def _extrair_texto_tesseract(conteudo: bytes) -> str:
    if not _HAS_TESSERACT or not _HAS_PDFPLUMBER:
        return ""
    try:
        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            partes = []
            for page in pdf.pages:
                img = page.to_image(resolution=300).original
                texto = pytesseract.image_to_string(img, lang="por")
                if texto:
                    partes.append(texto)
            return "\n".join(partes)
    except Exception:
        return ""


def _extrair_texto(conteudo: bytes) -> tuple[str, str]:
    """Retorna (texto, metodo_usado)."""
    texto = _extrair_texto_pdfplumber(conteudo)
    if texto.strip():
        return texto, "pdfplumber"
    texto = _extrair_texto_tesseract(conteudo)
    if texto.strip():
        return texto, "tesseract"
    return "", "nenhum"


# ---------------------------------------------------------------------------
# Parsers de campos com regex
# ---------------------------------------------------------------------------

# CPF: 000.000.000-00 ou 00000000000
_RE_CPF = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")

# CID-10: letra + 2-3 dígitos opcionalmente seguidos de letra/dígito
_RE_CID = re.compile(r"\b([A-Z]\d{2}(?:\.\d{1,2})?)\b")

# Dias: "X dias" ou "afastamento de X dias" ou "prazo de X dias"
_RE_DIAS = re.compile(
    r"(?:afastamento\s+de\s+|repouso\s+de\s+|prazo\s+de\s+|por\s+)?(\d{1,2})\s*dia[s]?",
    re.IGNORECASE,
)

# Data no formato DD/MM/YYYY ou DD-MM-YYYY
_RE_DATA = re.compile(r"\b(\d{2})[/\-](\d{2})[/\-](\d{4})\b")

# Horas declaradas: "X hora(s)" ou "Xh" ou "X:MM"
_RE_HORAS = re.compile(
    r"(\d{1,2})[h:h](\d{2})?\s*(?:hora[s]?|h\b)?",
    re.IGNORECASE,
)

# Nome: "Paciente: ...", "Nome: ...", "Sr./Sra. ..."
_RE_NOME = re.compile(
    r"(?:paciente|nome|sr\.|sra\.|senhor|senhora)\s*[:\-]?\s*([A-ZÀ-Ú][A-Za-zÀ-ú\s]{5,60})",
    re.IGNORECASE,
)


def _parse_cpf(texto: str) -> Optional[str]:
    m = _RE_CPF.search(texto)
    if m:
        return re.sub(r"\D", "", m.group(1))
    return None


def _parse_cid(texto: str) -> Optional[str]:
    # Prioriza CID que apareça perto da palavra "CID"
    for m in re.finditer(r"CID[\s\-:]*([A-Z]\d{2}(?:\.\d{1,2})?)", texto, re.IGNORECASE):
        return m.group(1).upper()
    m = _RE_CID.search(texto)
    return m.group(1).upper() if m else None


def _parse_dias(texto: str) -> Optional[int]:
    m = _RE_DIAS.search(texto)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _parse_data(texto: str) -> Optional[date]:
    for m in _RE_DATA.finditer(texto):
        try:
            dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 2020 <= ano <= 2030 and 1 <= mes <= 12 and 1 <= dia <= 31:
                return date(ano, mes, dia)
        except ValueError:
            continue
    return None


def _parse_nome(texto: str) -> Optional[str]:
    m = _RE_NOME.search(texto)
    if m:
        nome = m.group(1).strip()
        # Remove lixo no final (ex: data colada)
        nome = re.split(r"[\d,\.\n]", nome)[0].strip()
        if len(nome) >= 5:
            return nome.title()
    return None


def _parse_horas(texto: str) -> Optional[str]:
    m = _RE_HORAS.search(texto)
    if not m:
        return None
    h = int(m.group(1))
    mins_raw = m.group(2)
    mins = int(mins_raw) if mins_raw else 0
    if 0 <= h <= 23 and 0 <= mins < 60:
        return f"{h:02d}:{mins:02d}"
    return None


# ---------------------------------------------------------------------------
# Função pública
# ---------------------------------------------------------------------------
def extrair_atestado(conteudo: bytes) -> OcrResult:
    """
    Extrai dados de um atestado médico em PDF.

    Args:
        conteudo: Bytes do arquivo PDF.

    Returns:
        OcrResult com campos extraídos e avisos de confiabilidade.
        SEMPRE deve ser revisado pelo usuário antes de salvar.
    """
    resultado = OcrResult()

    if not _HAS_PDFPLUMBER:
        resultado.avisos.append(
            "pdfplumber não instalado. Instale com: pip install pdfplumber"
        )
        resultado.confianca = "baixa"
        return resultado

    texto, metodo = _extrair_texto(conteudo)
    resultado.raw_text = texto

    if not texto.strip():
        resultado.avisos.append(
            "Não foi possível extrair texto do PDF. "
            "Verifique se o arquivo está legível ou tente outro formato."
        )
        resultado.confianca = "baixa"
        return resultado

    resultado.cpf = _parse_cpf(texto)
    resultado.cid = _parse_cid(texto)
    resultado.dias = _parse_dias(texto)
    resultado.data_inicio = _parse_data(texto)
    resultado.nome = _parse_nome(texto)
    resultado.horas = _parse_horas(texto)

    # Confiança baseada em quantos campos foram extraídos
    campos_extraidos = sum([
        resultado.cpf is not None,
        resultado.dias is not None,
        resultado.data_inicio is not None,
        resultado.nome is not None,
    ])
    if campos_extraidos >= 3:
        resultado.confianca = "alta"
    elif campos_extraidos >= 2:
        resultado.confianca = "media"
    else:
        resultado.confianca = "baixa"

    if metodo == "tesseract":
        resultado.avisos.append(
            "Texto extraído via OCR (imagem). Confira os dados com atenção — "
            "erros de reconhecimento são possíveis."
        )

    if resultado.dias is None:
        resultado.avisos.append("Quantidade de dias não identificada — preencha manualmente.")
    if resultado.data_inicio is None:
        resultado.avisos.append("Data de início não identificada — preencha manualmente.")
    if resultado.nome is None and resultado.cpf is None:
        resultado.avisos.append(
            "Colaborador não identificado (sem nome nem CPF). Vinculação manual obrigatória."
        )

    return resultado
