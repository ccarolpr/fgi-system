from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Integer, DateTime, LargeBinary, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from backend.database import Base
import enum


class StatusPeriodo(str, enum.Enum):
    aberto    = "aberto"      # atestados podem ser lançados e corrigidos
    previewed = "previewed"   # prévia visualizada, aguarda confirmação para gerar Excel
    gerado    = "gerado"      # Excel gerado após confirmação da prévia
    fechado   = "fechado"     # período travado, nenhuma alteração permitida


class Period(Base):
    __tablename__ = "periods"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ano: Mapped[int] = mapped_column(Integer, nullable=False)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    cliente: Mapped[str] = mapped_column(String(50), nullable=False, default="CEINT")
    status: Mapped[StatusPeriodo] = mapped_column(
        SAEnum(StatusPeriodo), default=StatusPeriodo.aberto, nullable=False
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    previewed_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    gerado_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    fechado_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    excel_bytes: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)

    def __repr__(self) -> str:
        return f"<Period {self.ano}/{self.mes:02d} cliente={self.cliente} status={self.status}>"
