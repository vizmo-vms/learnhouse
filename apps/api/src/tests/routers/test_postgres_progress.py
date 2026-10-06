"""Admin progress reports work from durable data without event analytics."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from src.core.events.database import get_db_session
from src.db.courses.activities import Activity
from src.db.courses.chapter_activities import ChapterActivity
from src.db.trail_runs import StatusEnum, TrailRun
from src.db.trail_steps import TrailStep
from src.db.trails import Trail
from src.routers.analytics import router
from src.routers.audit import router as audit_router
from src.security.auth import get_current_user


@pytest.fixture
def app(db, admin_user):
    app = FastAPI()
    app.include_router(router, prefix="/analytics")
    app.include_router(audit_router, prefix="/audit")
    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin_user
    return app


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
async def progress(db, activity, chapter, regular_user):
    db.add(Trail(id=1, org_id=1, user_id=regular_user.id, trail_uuid="trail_test"))
    await db.commit()
    run = TrailRun(
        id=1,
        data={},
        status=StatusEnum.STATUS_IN_PROGRESS,
        trail_id=1,
        course_id=1,
        org_id=1,
        user_id=regular_user.id,
        creation_date="2026-10-01",
        update_date="2026-10-05",
    )
    db.add(run)
    # One published lesson completed; another published lesson still pending.
    # Draft and unlinked lessons must not inflate either side of the percentage.
    for activity_id, published, linked in [
        (2, True, True),
        (3, False, True),
        (4, True, False),
    ]:
        db.add(
            Activity(
                **{
                    **activity.model_dump(),
                    "id": activity_id,
                    "activity_uuid": f"activity_{activity_id}",
                    "published": published,
                }
            )
        )
        if linked:
            db.add(
                ChapterActivity(
                    activity_id=activity_id,
                    chapter_id=chapter.id,
                    course_id=1,
                    org_id=1,
                    order=activity_id,
                    creation_date="2026-10-01",
                    update_date="2026-10-01",
                )
            )
    for activity_id in [1, 3, 4]:
        db.add(
            TrailStep(
                complete=True,
                teacher_verified=False,
                grade="",
                data={},
                trailrun_id=1,
                trail_id=1,
                activity_id=activity_id,
                course_id=1,
                org_id=1,
                user_id=regular_user.id,
                creation_date="2026-10-01",
                update_date="2026-10-05",
            )
        )
    await db.commit()
    return run


async def test_progress_and_overview_agree_and_are_read_only(
    client, db, progress, regular_user
):
    response = await client.get("/analytics/dashboard/db/learner_progress?org_id=1")
    assert response.status_code == 200
    report = response.json()
    learner = next(row for row in report["data"] if row["user_id"] == regular_user.id)
    assert learner["activities_completed"] == 1
    assert learner["activities_total"] == 2
    assert learner["progress_pct"] == 50
    assert learner["last_activity_at"] == "2026-10-05"
    assert report["total"] == 2
    assert report["summary"]["enrollments"] == 1
    assert (
        next(row for row in report["data"] if row["user_id"] == 1)["status"]
        == "NOT_ENROLLED"
    )
    overview = (
        await client.get("/analytics/dashboard/db/basic_overview?org_id=1")
    ).json()
    assert overview["courses"][0]["average_progress"] == 50
    assert overview["summary"]["completed_activities"] == 1
    dossier = (await client.get(f"/audit/user/{regular_user.id}?org_id=1")).json()
    assert dossier["courses"][0]["progress_pct"] == 50
    assert (
        await db.execute(select(TrailRun))
    ).scalars().one().status == StatusEnum.STATUS_IN_PROGRESS
    assert len((await db.execute(select(TrailStep))).scalars().all()) == 3


async def test_search_status_and_pagination(client, progress):
    report = (
        await client.get(
            "/analytics/dashboard/db/learner_progress?org_id=1&search=regular&per_page=1"
        )
    ).json()
    assert report["total"] == 1
    assert len(report["data"]) == 1
    assert (
        await client.get(
            "/analytics/dashboard/db/learner_progress?org_id=1&search=Regular%20User"
        )
    ).json()["total"] == 1
    assert (
        await client.get("/analytics/dashboard/db/learner_progress?org_id=1&search=%25")
    ).json()["total"] == 0
    report = (
        await client.get(
            "/analytics/dashboard/db/learner_progress?org_id=1&status=NOT_ENROLLED"
        )
    ).json()
    assert report["total"] == 1
    assert report["data"][0]["user_id"] == 1
    assert (
        await client.get(
            "/analytics/dashboard/db/learner_progress?org_id=1&page=2&per_page=1"
        )
    ).json()["total"] == 2
    assert (
        await client.get(
            "/analytics/dashboard/db/learner_progress?org_id=1&per_page=101"
        )
    ).status_code == 422


async def test_course_filter_accepts_clean_uuid_and_rejects_other_org(
    client, course, progress, other_org, db
):
    from src.db.courses.courses import Course

    db.add(
        Course(
            **{
                **course.model_dump(),
                "id": 2,
                "org_id": other_org.id,
                "course_uuid": "course_other",
            }
        )
    )
    await db.commit()
    response = await client.get(
        "/analytics/dashboard/db/learner_progress?org_id=1&course_uuid=test"
    )
    assert response.status_code == 200
    assert response.json()["summary"]["enrollments"] == 1
    assert (
        await client.get(
            "/analytics/dashboard/db/learner_progress?org_id=1&course_uuid=other"
        )
    ).status_code == 404


async def test_admin_and_org_permissions(app, client, regular_user, other_org):
    assert (
        await client.get("/analytics/dashboard/db/learner_progress?org_id=2")
    ).status_code == 403

    app.dependency_overrides[get_current_user] = lambda: regular_user
    assert (
        await client.get("/analytics/dashboard/db/learner_progress?org_id=1")
    ).status_code == 403


async def test_completion_filter_uses_recorded_course_status(client, db, progress):
    progress.status = StatusEnum.STATUS_COMPLETED
    db.add(progress)
    await db.commit()
    response = await client.get(
        "/analytics/dashboard/db/learner_progress?org_id=1&status=STATUS_COMPLETED"
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["summary"]["completions"] == 1
    overview = (
        await client.get("/analytics/dashboard/db/basic_overview?org_id=1")
    ).json()
    assert overview["summary"]["completions"] == 1
