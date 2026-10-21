"""Server-only record of completions preserved when assessments were introduced."""
from sqlalchemy import Column, ForeignKey, Integer
from sqlmodel import Field, SQLModel


class AssessmentLegacyCompletion(SQLModel, table=True):
    assignment_id: int = Field(sa_column=Column(Integer, ForeignKey("assignment.id", ondelete="CASCADE"), index=True))
    activity_id: int = Field(sa_column=Column(Integer, ForeignKey("activity.id", ondelete="CASCADE"), primary_key=True))
    user_id: int = Field(sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), primary_key=True))
    org_id: int = Field(sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), index=True))
    course_id: int = Field(sa_column=Column(Integer, ForeignKey("course.id", ondelete="CASCADE"), index=True))
    preserved_at: str
