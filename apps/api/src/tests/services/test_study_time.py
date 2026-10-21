"""Active-time accounting is bounded, idempotent and owned by the learner."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import select

from src.db.courses.study_time import CourseStudyTime, CourseStudySession
from src.db.users import APITokenUser, SuperadminAPITokenUser
from src.services.courses import study_time
from src.tests.security.test_course_management_access import restrict_course


@pytest.fixture
def clock(monkeypatch):
    instant = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    offset = [0]
    monkeypatch.setattr(study_time, "utc_now", lambda: instant + timedelta(seconds=offset[0]))
    return offset


async def record(db, user, request, activity, session, total):
    return await study_time.record_study_time(request, activity.activity_uuid, user, db, str(session), total)


async def test_duplicate_and_out_of_order_heartbeats_do_not_inflate_time(db, activity, regular_user, mock_request, clock):
    session = uuid4()
    assert (await record(db, regular_user, mock_request, activity, session, 0))["active_seconds"] == 0
    clock[0] = 15
    assert (await record(db, regular_user, mock_request, activity, session, 15000))["active_seconds"] == 15
    for instant, counter in [(16, 15000), (17, 10000), (30, 30000)]:
        clock[0] = instant
        result = await record(db, regular_user, mock_request, activity, session, counter)
    assert result["active_seconds"] == 30


async def test_overlapping_tabs_share_one_course_total(db, activity, regular_user, mock_request, clock):
    first, second = uuid4(), uuid4()
    await record(db, regular_user, mock_request, activity, first, 0)
    clock[0] = 5
    await record(db, regular_user, mock_request, activity, second, 0)
    clock[0] = 15
    await record(db, regular_user, mock_request, activity, first, 15000)
    clock[0] = 20
    result = await record(db, regular_user, mock_request, activity, second, 15000)
    assert result["active_seconds"] == 20


async def test_large_counter_cannot_claim_time_without_server_elapsed_time(db, activity, regular_user, mock_request, clock):
    session = uuid4()
    await record(db, regular_user, mock_request, activity, session, 0)
    clock[0] = 1
    result = await record(db, regular_user, mock_request, activity, session, 1000000)
    assert result["active_seconds"] == 1
    assert result["partially_tracked"]
    clock[0] = 601
    result = await record(db, regular_user, mock_request, activity, session, 1600000)
    assert result["active_seconds"] == 31


async def test_completion_accepts_only_a_late_final_interval_before_the_finish(db, activity, regular_user, mock_request, clock):
    session = uuid4()
    await record(db, regular_user, mock_request, activity, session, 0)
    clock[0] = 15
    await record(db, regular_user, mock_request, activity, session, 15000)
    clock[0] = 22
    await study_time.finish_study_time(regular_user.id, activity.course_id, db)
    clock[0] = 23
    result = await record(db, regular_user, mock_request, activity, session, 23000)
    assert result["active_seconds"] == 22 and not result["tracking"]
    clock[0] = 60
    result = await record(db, regular_user, mock_request, activity, session, 60000)
    assert result["active_seconds"] == 22
    result = await record(db, regular_user, mock_request, activity, uuid4(), 999999)
    assert result["active_seconds"] == 22


async def test_historical_partial_record_is_not_fabricated(db, activity, regular_user, mock_request, clock):
    db.add(CourseStudyTime(user_id=regular_user.id, course_id=activity.course_id, org_id=activity.org_id, partially_tracked=True))
    await db.commit()
    session = uuid4()
    result = await record(db, regular_user, mock_request, activity, session, 0)
    assert result["active_seconds"] == 0 and result["partially_tracked"]
    clock[0] = 15
    result = await record(db, regular_user, mock_request, activity, session, 15000)
    assert result["active_seconds"] == 15 and result["partially_tracked"]


async def test_session_cannot_be_reused_by_another_user(db, activity, regular_user, admin_user, mock_request, clock):
    session = uuid4()
    await record(db, regular_user, mock_request, activity, session, 0)
    with pytest.raises(HTTPException) as error:
        await record(db, admin_user, mock_request, activity, session, 15000)
    assert error.value.status_code == 403
    assert len((await db.execute(select(CourseStudySession))).scalars().all()) == 1


async def test_inaccessible_course_cannot_record_time(db, activity, course, org, regular_user, mock_request, clock):
    await restrict_course(db, org, course)
    with pytest.raises(HTTPException):
        await record(db, regular_user, mock_request, activity, uuid4(), 0)
    assert not (await db.execute(select(CourseStudyTime))).scalars().all()


@pytest.mark.parametrize("principal", [APITokenUser(org_id=1, id=2), SuperadminAPITokenUser(id=2)])
async def test_api_tokens_cannot_impersonate_learner_time(db, activity, mock_request, clock, principal):
    with pytest.raises(HTTPException) as error:
        await record(db, principal, mock_request, activity, uuid4(), 0)
    assert error.value.status_code == 401


async def test_completion_before_first_heartbeat_never_creates_history(db, activity, regular_user, mock_request, clock):
    await study_time.finish_study_time(regular_user.id, activity.course_id, db)
    clock[0] = 15
    result = await record(db, regular_user, mock_request, activity, uuid4(), 15000)
    assert result["active_seconds"] is None and result["tracking"] is False
    assert not (await db.execute(select(CourseStudySession))).scalars().all()


@pytest.mark.parametrize("passed", [False, True])
async def test_completion_freezes_only_after_assessment_pass_without_requiring_certificate(db, activity, regular_user, mock_request, clock, monkeypatch, passed):
    from unittest.mock import AsyncMock
    from src.services.courses import certifications

    session = uuid4()
    await record(db, regular_user, mock_request, activity, session, 0)
    clock[0] = 15
    await record(db, regular_user, mock_request, activity, session, 15000)
    monkeypatch.setattr(certifications, "are_course_assignments_passed", AsyncMock(return_value=passed))
    clock[0] = 22
    created_cert = await certifications.check_course_completion_and_create_certificate(mock_request, regular_user.id, activity.course_id, db, is_complete=True)
    assert created_cert is False  # Native return value still means a newly issued certificate.
    row = await db.get(CourseStudyTime, (regular_user.id, activity.course_id))
    assert bool(row.completed_at) is passed


@pytest.mark.parametrize("draft", ["course", "activity", "unlinked"])
async def test_unpublished_or_unlinked_content_cannot_create_time(db, activity, course, admin_user, mock_request, clock, draft):
    from src.db.courses.chapter_activities import ChapterActivity
    if draft == "unlinked":
        await db.delete((await db.execute(select(ChapterActivity))).scalars().one())
    else:
        item = course if draft == "course" else activity
        item.published = False
        db.add(item)
    await db.commit()
    with pytest.raises(HTTPException):
        await record(db, admin_user, mock_request, activity, uuid4(), 0)
    assert not (await db.execute(select(CourseStudySession))).scalars().all()


async def test_unobservable_embeds_mark_coverage_partial(db, activity, regular_user, mock_request, clock):
    result = await study_time.record_study_time(mock_request, activity.activity_uuid, regular_user, db, str(uuid4()), 0, partial=True)
    assert result["active_seconds"] == 0 and result["partially_tracked"] is True
