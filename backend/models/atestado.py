from datetime import datetime, date, timezone
from typing import Optional
from sqlalchemy import String, Float, Integer, Date, DateTime, ForeignKey, Enum as SAEnum, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base
import enum


class StatusAtestado(str, enum.Enum):
    pendente_validacao = "pendente_validacao"  # extraído por OCR, aguarda revisão
    sem_vinculo        = "sem_vinculo"         # colaborador não identificado
    confirmado         = "confirmado"           # revisado e salvo, entra no cálculo
    rejeitado          = "rejeitado"            # descartado (log mantido)


class OrigemAtestado(str, enum.Enum):
    ocr    = "ocr"
    manual = "manual"


class Atestado(Base):
    __tablename__ = "atestados"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Vínculo ao colaborador — nullable enquanto status=sem_vinculo
    colaborador_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employees.id"), nullable=True, index=True
    )

    # Período do atestado
    data_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    dias: Mapped[int] = mapped_column(Integer, nullable=False)

    # Horas declaradas (além do atestado em dias)
    horas_declaradas_raw: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # "01:30"
    horas_declaradas_decimal: Mapped[float] = mapped_column(Float, default=0.0)

    # Diagnóstico (opcional)
    cid: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Rastreabilidade
    status: Mapped[StatusAtestado] = mapped_column(
        SAEnum(StatusAtestado), default=StatusAtestado.pendente_validacao, nullable=False
    )
    origem: Mapped[OrigemAtestado] = mapped_column(SAEnum(OrigemAtestado), nullable=False)
    ocr_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # texto bruto extraído

    # Nome sugerido pelo OCR (preservado mesmo após vinculação)
    nome_ocr: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    cpf_ocr: Mapped[Optional[str]] = mapped_column(String(14), nullable=True)

    # Confirmação
    confirmado_por: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    confirmado_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    colaborador: Mapped[Optional["Employee"]] = relationship("Employee", foreign_keys=[colaborador_id])  # type: ignore

    def __repr__(self) -> str:
        return (
            f"<Atestado id={self.id} colaborador_id={self.colaborador_id} "
            f"data={self.data_inicio} dias={self.dias} status={self.status}>"
        )
