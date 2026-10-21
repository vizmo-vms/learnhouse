"""Bound active-time claims by server time and merge overlapping sessions."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import select

from src.db.courses.chapter_activities import ChapterActivity
from src.db.courses.study_time import CourseStudySession, CourseStudyTime
from src.db.user_organizations import UserOrganization
from src.db.users import PublicUser
from src.services.courses.activities.access import verify_activity_reader_access_by_uuid

MAX_HEARTBEAT_MS = 30_000


def utc_now():
    return datetime.now(timezone.utc)


def as_utc(value):
    # SQLite test datetimes have no offset; PostgreSQL stores timestamptz.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def time_fields(row):
    return {
        "active_seconds": round(row.active_ms / 1000, 3) if row and row.first_seen_at else None,
        "partially_tracked": bool(row and row.partially_tracked),
        "study_completed_at": as_utc(row.completed_at).isoformat() if row and row.completed_at else None,
    }


def insert_for(db, model):
    return (sqlite_insert if db.bind.dialect.name == "sqlite" else postgres_insert)(model)


async def finish_study_time(user_id, course_id, db):
    """Caller has verified lesson completion and passing assessments."""
    from src.db.courses.courses import Course

    course = await db.get(Course, course_id)
    await db.execute(insert_for(db, CourseStudyTime).values(
        user_id=user_id, course_id=course_id, org_id=course.org_id,
        active_ms=0, partially_tracked=False,
    ).on_conflict_do_nothing())
    row = (await db.execute(select(CourseStudyTime).where(
        CourseStudyTime.user_id == user_id, CourseStudyTime.course_id == course_id,
    ).with_for_update().execution_options(populate_existing=True))).scalars().first()
    if row and row.completed_at is None:
        row.completed_at = utc_now()
        db.add(row)
        await db.commit()


async def record_study_time(request, activity_uuid, current_user, db, session_id, total_ms, partial=False):
    if not isinstance(current_user, PublicUser) or not current_user.id:
        raise HTTPException(status_code=401, detail="A learner session is required")
    activity, course = await verify_activity_reader_access_by_uuid(request, activity_uuid, current_user, db)
    member = (await db.execute(select(UserOrganization.id).where(
        UserOrganization.user_id == current_user.id, UserOrganization.org_id == course.org_id,
    ).limit(1))).scalar_one_or_none()
    linked = (await db.execute(select(ChapterActivity.id).where(
        ChapterActivity.activity_id == activity.id, ChapterActivity.course_id == course.id,
        ChapterActivity.org_id == course.org_id,
    ).limit(1))).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=403, detail="Organization membership is required")
    if not course.published or not activity.published or not linked:
        raise HTTPException(status_code=404, detail="Published lesson not found")
    owner = (current_user.id, course.id, course.org_id, activity.id)
    existing_session = await db.get(CourseStudySession, session_id)
    if existing_session and (existing_session.user_id, existing_session.course_id, existing_session.org_id, existing_session.activity_id) != owner:
        raise HTTPException(status_code=403, detail="Invalid study session")

    now = utc_now()
    await db.execute(insert_for(db, CourseStudyTime).values(
        user_id=current_user.id, course_id=course.id, org_id=course.org_id,
        active_ms=0, partially_tracked=False,
    ).on_conflict_do_nothing())
    row = (await db.execute(select(CourseStudyTime).where(
        CourseStudyTime.user_id == current_user.id, CourseStudyTime.course_id == course.id,
    ).with_for_update().execution_options(populate_existing=True))).scalars().one()
    if row.first_seen_at is None and row.completed_at is None:
        from src.services.courses.certifications import is_course_fully_completed, are_course_assignments_passed

        # Check while holding the same aggregate lock used by finalization.
        # A concurrent first visit must not start a clock after completion.
        if await is_course_fully_completed(current_user.id, course.id, db) and await are_course_assignments_passed(current_user.id, course.id, db):
            row.completed_at = now
            db.add(row)
    if row.completed_at and (existing_session is None or row.first_seen_at is None):
        await db.commit()
        return {"tracking": False, **time_fields(row)}

    created = (await db.execute(insert_for(db, CourseStudySession).values(
        session_id=session_id, user_id=current_user.id, course_id=course.id,
        org_id=course.org_id, activity_id=activity.id, last_total_ms=total_ms, last_seen_at=now,
    ).on_conflict_do_nothing().returning(CourseStudySession.session_id))).scalar_one_or_none()
    session = (await db.execute(select(CourseStudySession).where(
        CourseStudySession.session_id == session_id,
    ).with_for_update().execution_options(populate_existing=True))).scalars().one()
    if (session.user_id, session.course_id, session.org_id, session.activity_id) != owner:
        await db.rollback()
        raise HTTPException(status_code=403, detail="Invalid study session")
    if row.first_seen_at is None:
        row.first_seen_at = now
    row.partially_tracked = row.partially_tracked or partial
    if created:
        # No server-observed interval exists before the handshake.
        row.partially_tracked = row.partially_tracked or total_ms > 0
    elif total_ms > session.last_total_ms:
        requested = total_ms - session.last_total_ms
        elapsed = max(0, int((now - as_utc(session.last_seen_at)).total_seconds() * 1000))
        accepted = min(requested, elapsed, MAX_HEARTBEAT_MS)
        start = now - timedelta(milliseconds=accepted)
        end = min(now, as_utc(row.completed_at)) if row.completed_at else now
        if row.last_accounted_at:
            start = max(start, as_utc(row.last_accounted_at))
        if end > start:
            row.active_ms += int((end - start).total_seconds() * 1000)
            row.last_accounted_at = end
        # Allow small network/rounding differences without calling every visit
        # partial; substantial rejected time remains visible in the report.
        row.partially_tracked = row.partially_tracked or requested - accepted > 2000
        session.last_total_ms = total_ms
        session.last_seen_at = now
        db.add(session)
    db.add(row)
    await db.commit()
    return {"tracking": row.completed_at is None, **time_fields(row)}
