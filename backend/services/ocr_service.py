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
    import os
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    os.environ["TESSDATA_PREFIX"] = r"C:\Users\KWAY07\AppData\Local\tessdata"
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


def _preprocessar_imagem(img):
    """
    Pré-processamento padrão: brilho + contraste + nitidez + binarização.
    Funciona bem para scans comuns e levemente escuros.
    """
    from PIL import ImageEnhance
    img_gray = img.convert("L")
    img_gray = ImageEnhance.Brightness(img_gray).enhance(1.8)
    img_gray = ImageEnhance.Contrast(img_gray).enhance(2.5)
    img_gray = ImageEnhance.Sharpness(img_gray).enhance(2.0)
    return img_gray.point(lambda x: 255 if x > 140 else 0, "1")


def _preprocessar_imagem_denoised(img):
    """
    Pré-processamento com denoising para scans muito ruidosos.
    Aplica filtro mediana antes de binarizar — reduz ruído de fundo.
    """
    from PIL import ImageEnhance, ImageFilter
    img_gray = img.convert("L")
    img_gray = img_gray.filter(ImageFilter.MedianFilter(size=3))
    img_gray = ImageEnhance.Contrast(img_gray).enhance(3.0)
    img_gray = ImageEnhance.Sharpness(img_gray).enhance(1.5)
    return img_gray.point(lambda x: 255 if x > 128 else 0, "1")


def _melhor_ocr_pagina(img) -> str:
    """
    Tenta múltiplas estratégias de pré-processamento e configurações do Tesseract.
    Retorna o texto com mais conteúdo reconhecido.
    """
    config_psm6 = "--psm 6"
    config_psm4 = "--psm 4"

    candidatos = []

    # Estratégia 1: padrão
    img_std = _preprocessar_imagem(img)
    t1 = pytesseract.image_to_string(img_std, lang="por", config=config_psm6)
    candidatos.append(t1)

    # Só testa alternativas se o resultado padrão for ruim (<80 chars úteis)
    if len(t1.strip()) < 80:
        # Estratégia 2: denoising + threshold mais brando
        img_dn = _preprocessar_imagem_denoised(img)
        t2 = pytesseract.image_to_string(img_dn, lang="por", config=config_psm6)
        candidatos.append(t2)

        # Estratégia 3: denoising com PSM 4 (coluna única)
        t3 = pytesseract.image_to_string(img_dn, lang="por", config=config_psm4)
        candidatos.append(t3)

    # Retorna o candidato com mais conteúdo reconhecido
    return max(candidatos, key=lambda t: len(t.strip()))


def _extrair_texto_tesseract(conteudo: bytes) -> str:
    if not _HAS_TESSERACT or not _HAS_PDFPLUMBER:
        return ""
    import logging
    logger = logging.getLogger(__name__)
    try:
        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            partes = []
            for page in pdf.pages:
                img = page.to_image(resolution=300).original
                texto = _melhor_ocr_pagina(img)
                if texto.strip():
                    partes.append(texto)
            return "\n".join(partes)
    except Exception as e:
        logger.error("Tesseract OCR falhou: %s", e, exc_info=True)
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

# Dias: "X dias", "X (DOIS) dias", "período de X dias", "afastamento de X dias"
# Aceita variações de OCR no numeral por extenso (ex: "GOIS" no lugar de "DOIS")
_RE_DIAS = re.compile(
    r"(?:afastamento\s+de\s+|repouso\s+de\s+|prazo\s+de\s+|per[íi]odo\s+de\s+|por\s+)?"
    r"(\d{1,2})\s*(?:\(?\s*[A-Za-zÀ-Ú]{2,10}\s*\)?)?\s*dia[s]?",
    re.IGNORECASE,
)

# Data no formato DD/MM/YYYY ou DD-MM-YYYY
_RE_DATA = re.compile(r"\b(\d{2})[/\-](\d{2})[/\-](\d{4})\b")

# Horas declaradas: exige a palavra "hora(s)" ou sufixo "h" explícito
# Não deve capturar horários de atendimento como "08:37"
_RE_HORAS = re.compile(
    r"(\d{1,2})[h:](\d{2})\s*hora[s]?"
    r"|(\d{1,2})h(\d{2})?\b",
    re.IGNORECASE,
)

# Nome: "Sr(a). NOME", "o(a) Sr(a). NOME", "Paciente: NOME", "Nome: NOME"
# Trata variações comuns em atestados: Sr. / Sra. / Sr(a). / o(a) Sr(a).
_RE_NOME = re.compile(
    r"(?:"
    r"(?:o\s*\(?\s*a\s*\)?\s*)?sr\s*\(?\s*a?\s*\)?\s*\.?\s*"  # Sr(a). / o(a) Sr(a).
    r"|sra?\s*\.?\s*"                                            # Sra. / Sr.
    r"|paciente\s*[:\-]?\s*"
    r"|nome\s*[:\-]?\s*"
    r"|senhor[a]?\s*[:\-]?\s*"
    r")"
    r"[\(\)\s]*"                             # parênteses ou espaços residuais: "() " em "Sr. ()"
    r"([A-ZÀÁÂÃÉÊÍÓÔÕÚÇ][A-Za-zÀ-ú][A-Za-zÀ-ú\s]{4,58})",
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


_RE_REPOUSO_HOJE = re.compile(
    r"dia\s+de\s+hoje"                          # qualquer menção a "dia de hoje"
    r"|rep\w{2,5}\s+hoje"                       # repo*so hoje (tolerante a OCR)
    r"|afastado\s+(?:n[oó]\s+)?hoje"
    r"|rep\w{2,5}\s+n[oó]\s+dia"               # repouso no dia (variantes OCR)
    r"|compareceu\s+nesse\s+servi[çc]o"         # presença no serviço = 1 dia
    r"|neste\s+dia\s+de\s+atendimento",
    re.IGNORECASE,
)

_RE_PERIODO_PARCIAL = re.compile(
    r"per[íi]odo\s+(?:da\s+)?(?:vespertino|matutino|manha|manh[ãa]|tarde)"
    r"|(?:vespertino|matutino|manh[ãa]|tarde)\s+(?:deste\s+dia|de\s+hoje|apenas)"
    r"|repouso\s+no\s+hor[aá]rio\s+acima"
    r"|repousar?\s+no\s+hor[aá]rio\s+acima"
    r"|repouso\s+no\s+per[íi]odo\s+d[ao]",
    re.IGNORECASE,
)


def _eh_formulario_checkbox(texto: str) -> bool:
    """
    Retorna True se o texto parece ser um formulário impresso com todas as opções
    listadas (checkboxes), onde não é possível determinar qual foi marcada.
    Heurística: 3+ ocorrências de "deverá permanecer em repouso no".
    """
    ocorrencias = len(re.findall(r"dev[eé]r[áa]\s+permanecer\s+em\s+repo", texto, re.IGNORECASE))
    return ocorrencias >= 3


def _parse_dias(texto: str) -> Optional[int]:
    # Corrige confusões OCR de números: Tl→1, Il→1
    texto_c = re.sub(r"\b[TtIi][l1]\b", "1", texto)
    texto_c = re.sub(r"\b[lI](\d)\b", r"1\1", texto_c)

    # Padrões explícitos de quantidade de dias
    m = _RE_DIAS.search(texto_c)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass

    # Fallback numérico: número antes de "dia"
    for m2 in re.finditer(r"(\d{1,2})\s*(?:\(?\s*\w+\s*\)?)?\s*dia[s]?", texto_c, re.IGNORECASE):
        try:
            v = int(m2.group(1))
            if 1 <= v <= 30:
                return v
        except ValueError:
            continue

    # "repouso no dia de hoje" → 1 dia
    # Só aplica se NÃO for formulário com todas as opções listadas
    if _RE_REPOUSO_HOJE.search(texto_c) and not _eh_formulario_checkbox(texto_c):
        return 1

    return None


def _parse_data(texto: str) -> Optional[date]:
    # Corrige confusões comuns de OCR em dígitos
    c = texto
    c = re.sub(r"[OoQq](?=[\d/])", "0", c)   # O/Q → 0
    c = re.sub(r"[lI](?=[\d/])",   "1", c)   # l/I → 1
    c = re.sub(r"\bD(\d)/",        r"0\1/", c)  # D4/ → 04/  (D confundido com 0)
    c = re.sub(r"\bt(\d)/",        r"1\1/", c)  # t4/ → 14/  (t confundido com 1)

    # Prefere data associada a "a partir desta data" / "afastado a partir de"
    for pat in [
        r"(?:a partir desta data|a partir de|afastamento a partir de)\s+(\d{2}[/\-]\d{2}[/\-]\d{4})",
    ]:
        m = re.search(pat, c, re.IGNORECASE)
        if m:
            try:
                for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
                    try:
                        return datetime.strptime(m.group(1), fmt).date()
                    except ValueError:
                        continue
            except Exception:
                pass

    # Fallback: primeira data válida no texto
    for m in _RE_DATA.finditer(c):
        try:
            dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 2020 <= ano <= 2030 and 1 <= mes <= 12 and 1 <= dia <= 31:
                return date(ano, mes, dia)
        except ValueError:
            continue
    return None


def _parse_nome(texto: str) -> Optional[str]:
    melhor = None
    for m in _RE_NOME.finditer(texto):
        nome_raw = m.group(1).strip()
        # Extrai apenas palavras capitalizadas consecutivas (o nome próprio)
        # Para após primeira palavra em minúsculo ou caractere especial
        palavras_nome = []
        for palavra in nome_raw.split():
            # Remove pontuação residual
            p = re.sub(r"[^\w]", "", palavra)
            if not p:
                continue
            # Para quando encontrar palavra em minúsculo (verbo/artigo/lixo OCR)
            if p[0].islower() and len(p) >= 2:
                break
            palavras_nome.append(p)
            if len(palavras_nome) >= 5:  # nomes têm no máximo ~5 palavras
                break

        if len(palavras_nome) < 2:
            continue
        # Descarta se maioria são letras únicas (lixo OCR: "R A A")
        letras_unicas = sum(1 for p in palavras_nome if len(p) == 1)
        if letras_unicas > len(palavras_nome) // 2:
            continue

        nome = " ".join(palavras_nome)
        if melhor is None or len(palavras_nome) > len(melhor.split()):
            melhor = nome
    return melhor.title() if melhor else None


def _parse_horas(texto: str) -> Optional[str]:
    # Formulário checkbox: todas as opções listadas, não é possível saber qual foi marcada
    if _eh_formulario_checkbox(texto):
        return None
    # Período parcial (vespertino/matutino/manhã/tarde) → 4 horas declaradas
    if _RE_PERIODO_PARCIAL.search(texto):
        return "04:00"

    m = _RE_HORAS.search(texto)
    if not m:
        return None
    # Grupo 1+2: "Xh:MM horas" | Grupo 3+4: "XhMM"
    if m.group(1) is not None:
        h, mins_raw = int(m.group(1)), m.group(2)
    else:
        h, mins_raw = int(m.group(3)), m.group(4)
    mins = int(mins_raw) if mins_raw else 0
    if 0 <= h <= 12 and 0 <= mins < 60:
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
