from datetime import datetime, date, timezone
from typing import Optional
from sqlalchemy import String, Float, Date, DateTime, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from backend.database import Base
import enum


class StatusColaborador(str, enum.Enum):
    ativo = "ativo"
    inativo = "inativo"


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cpf: Mapped[str] = mapped_column(String(14), unique=True, nullable=False, index=True)
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    funcao: Mapped[str] = mapped_column(String(100), nullable=False)
    salario: Mapped[float] = mapped_column(Float, nullable=False)
    data_admissao: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    data_demissao: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[StatusColaborador] = mapped_column(
        SAEnum(StatusColaborador), default=StatusColaborador.ativo, nullable=False
    )
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<Employee cpf={self.cpf} nome={self.nome} status={self.status}>"
