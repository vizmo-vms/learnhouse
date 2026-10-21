"""Durable active-time totals and idempotent browser-session cursors."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, text
from sqlmodel import Field, SQLModel


class CourseStudyTime(SQLModel, table=True):
    __tablename__ = "course_study_time"
    __table_args__ = (Index("ix_course_study_time_org_course", "org_id", "course_id"),)
    user_id: int = Field(sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), primary_key=True))
    course_id: int = Field(sa_column=Column(Integer, ForeignKey("course.id", ondelete="CASCADE"), primary_key=True))
    org_id: int = Field(sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False))
    active_ms: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    partially_tracked: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("false")))
    first_seen_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    last_accounted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    completed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))


class CourseStudySession(SQLModel, table=True):
    __tablename__ = "course_study_session"
    session_id: str = Field(primary_key=True, max_length=36)
    user_id: int = Field(sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True))
    course_id: int = Field(sa_column=Column(Integer, ForeignKey("course.id", ondelete="CASCADE"), nullable=False, index=True))
    org_id: int = Field(sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False))
    activity_id: int = Field(sa_column=Column(Integer, ForeignKey("activity.id", ondelete="CASCADE"), nullable=False))
    last_total_ms: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    last_seen_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
