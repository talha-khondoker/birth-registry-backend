from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def now():
    return datetime.now(timezone.utc)


class Officer(Base):
    __tablename__ = "officers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    api_key: Mapped[str] = mapped_column(String(64), unique=True)


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    tracking_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)

    child_name: Mapped[str] = mapped_column(String(150))
    child_dob: Mapped[date] = mapped_column(Date, index=True)
    child_gender: Mapped[str] = mapped_column(String(10))

    father_nid: Mapped[str] = mapped_column(String(17), index=True)
    mother_nid: Mapped[str] = mapped_column(String(17), index=True)

    applicant_nid: Mapped[str] = mapped_column(String(17), index=True)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), index=True)  # কাঁচা ডেটা নয়, শুধু হ্যাশ
    iris_hash: Mapped[str] = mapped_column(String(64), index=True)

    status: Mapped[str] = mapped_column(String(30), index=True)
    flags: Mapped[str] = mapped_column(Text, default="")
    assigned_officer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("officers.id"), nullable=True)

    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_step: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    certificate_no: Mapped[Optional[str]] = mapped_column(String(30), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(50))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)