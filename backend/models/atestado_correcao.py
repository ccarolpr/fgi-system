from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class AtestadoCorrecao(Base):
    """
    Correção auditada de um atestado já confirmado.

    Atestados confirmados são imutáveis diretamente.
    Toda alteração passa por este registro: campo, valor anterior,
    valor novo, motivo e usuário ficam gravados para auditoria.
    """
    __tablename__ = "atestado_correcoes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    atestado_id: Mapped[int] = mapped_column(
        ForeignKey("atestados.id"), nullable=False, index=True
    )
    campo: Mapped[str] = mapped_column(String(50), nullable=False)
    valor_anterior: Mapped[str] = mapped_column(String(200), nullable=True)
    valor_novo: Mapped[str] = mapped_column(String(200), nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    usuario: Mapped[str] = mapped_column(String(100), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    atestado: Mapped["Atestado"] = relationship("Atestado", foreign_keys=[atestado_id])  # type: ignore

    def __repr__(self) -> str:
        return (
            f"<AtestadoCorrecao atestado_id={self.atestado_id} "
            f"campo={self.campo} {self.valor_anterior!r}→{self.valor_novo!r}>"
        )
