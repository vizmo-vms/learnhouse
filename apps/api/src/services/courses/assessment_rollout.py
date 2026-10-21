"""Grandfather only the specific assessments introduced at the cutover.

The ledger has no public write endpoint. It does not grant a passing grade.
"""
from sqlmodel import select
from src.db.courses.assessment_legacy_completions import AssessmentLegacyCompletion
from src.db.courses.assignments import Assignment


async def preserves_prior_completion(db, activity_id: int, user_id: int) -> bool:
    return (await db.execute(select(AssessmentLegacyCompletion.user_id).join(Assignment, Assignment.id == AssessmentLegacyCompletion.assignment_id).where(
        AssessmentLegacyCompletion.activity_id == activity_id,
        AssessmentLegacyCompletion.user_id == user_id,
        Assignment.activity_id == activity_id,
    ))).first() is not None
