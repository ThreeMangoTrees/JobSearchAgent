from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.Model.base import Base


class CompanyCareerPageInstruction(Base):
    __tablename__ = "company_career_page_instructions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    careers_page_url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    job_id_extraction_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    location_extraction_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    role_extraction_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
