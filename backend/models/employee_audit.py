from datetime import datetime, timezone
from sqlalchemy import String, Float, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base
import enum


class OrigemAlteracao(str, enum.Enum):
    manual = "manual"
    importacao_planilha = "importacao_planilha"


class EmployeeAudit(Base):
    """
    Registra toda alteração em campos críticos de um colaborador.
    Salário zerado/negativo nunca é salvo aqui — é bloqueado antes.
    Alterações acima do threshold geram alerta_ativo=True.
    """
    __tablename__ = "employee_audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    campo: Mapped[str] = mapped_column(String(50), nullable=False)
    valor_anterior: Mapped[str] = mapped_column(String(200), nullable=True)
    valor_novo: Mapped[str] = mapped_column(String(200), nullable=False)
    origem: Mapped[OrigemAlteracao] = mapped_column(SAEnum(OrigemAlteracao), nullable=False)
    alerta_ativo: Mapped[bool] = mapped_column(default=False)  # True se variação > threshold
    alterado_em: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    employee: Mapped["Employee"] = relationship("Employee", foreign_keys=[employee_id])  # type: ignore

    def __repr__(self) -> str:
        return (
            f"<EmployeeAudit employee_id={self.employee_id} campo={self.campo} "
            f"{self.valor_anterior!r}→{self.valor_novo!r}>"
        )
