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


@pytest.fixture
async def assessment(db, progress):
    from src.db.courses.assignments import Assignment, AssignmentTask

    assignment = Assignment(
        id=10, title="Course assessment", description="Final assessment",
        published=True, grading_type="PERCENTAGE", pass_threshold_percentage=80,
        org_id=1, course_id=1, chapter_id=1, activity_id=1,
        assignment_uuid="assignment_report", creation_date="2026-10-01", update_date="2026-10-01",
    )
    db.add(assignment)
    db.add(AssignmentTask(
        title="Questions", description="", hint="", assignment_type="QUIZ",
        contents={"questions": [{"answers": [{"correct": True}]}]},
        max_grade_value=200, assignment_id=10, org_id=1, course_id=1, chapter_id=1,
        activity_id=1, assignment_task_uuid="assignmenttask_report",
        creation_date="2026-10-01", update_date="2026-10-01",
    ))
    await db.commit()
    return assignment


@pytest.mark.parametrize("status,raw,expected,passed", [
    ("GRADED", 160, 80, True),
    ("GRADED", 150, 75, False),
    ("GRADED", 0, 0, False),
    ("PENDING", 160, None, None),
    ("SUBMITTED", 160, None, None),
    (None, 0, None, None),
])
async def test_report_normalizes_latest_assessment_grade_without_answers(
    client, db, assessment, regular_user, status, raw, expected, passed,
):
    from src.db.courses.assignments import AssignmentUserSubmission

    if status:
        db.add(AssignmentUserSubmission(
            assignment_id=assessment.id, user_id=regular_user.id, grade=raw,
            submission_status=status, attempt_number=2,
            assignmentusersubmission_uuid="aus_report",
            creation_date="2026-10-01", update_date="2026-10-02",
        ))
        await db.commit()
    response = await client.get("/analytics/dashboard/db/learner_progress?org_id=1&search=regular")
    assert response.status_code == 200
    result = response.json()["data"][0]["assessments"]
    assert len(result) == 1
    assert result[0]["percentage"] == expected
    assert result[0]["passed"] is passed
    assert result[0]["submission_status"] == (status or "NOT_STARTED")
    assert result[0]["attempt_number"] == (2 if status else 0)
    assert "correct" not in response.text
    assert "contents" not in response.text


async def test_report_excludes_draft_and_unlinked_assessments(client, db, assessment, activity):
    assessment.published = False
    db.add(assessment)
    await db.commit()
    response = await client.get("/analytics/dashboard/db/learner_progress?org_id=1&search=regular")
    assert response.json()["data"][0]["assessments"] == []
    assessment.published = True
    activity.published = False
    db.add_all([assessment, activity])
    await db.commit()
    response = await client.get("/analytics/dashboard/db/learner_progress?org_id=1&search=regular")
    assert response.json()["data"][0]["assessments"] == []


def quiz_questions():
    return [{"question": "Which answer is correct?", "answers": [
        {"answer": "The correct option", "correct": True},
        {"answer": "A distractor", "correct": False},
    ]}]


@pytest.mark.parametrize("already_complete", [False, True])
async def test_conversion_preserves_history_and_previous_completions(
    db, course, activity, progress, already_complete,
):
    from scripts.convert_course_assessments import convert
    from src.db.courses.assignments import Assignment, AssignmentTask, AssignmentUserSubmission
    from src.db.courses.activity_versions import ActivityVersion

    original = {"type": "doc", "content": [{"type": "blockQuiz", "attrs": {"questions": quiz_questions()}}]}
    activity.content = original
    if already_complete:
        progress.status = StatusEnum.STATUS_COMPLETED
    db.add_all([activity, progress])
    await db.commit()
    assert (await convert(db, 1, {}, 1))["converted"] == 1
    assert not (await db.execute(select(Assignment))).scalars().all()
    result = await convert(db, 1, {}, 1, apply=True)
    await db.commit()
    assignment = (await db.execute(select(Assignment))).scalars().one()
    assert assignment.pass_threshold_percentage == 80
    assert assignment.max_retries == 3
    assert assignment.auto_grading and not assignment.show_correct_answers
    assert assignment.due_date is None
    task = (await db.execute(select(AssignmentTask))).scalars().one()
    assert task.contents["questions"][0]["options"][0]["assigned_right_answer"] is True
    assert activity.content == {}
    assert (await db.execute(select(ActivityVersion))).scalars().one().content == original
    step = (await db.execute(select(TrailStep).where(TrailStep.activity_id == 1))).scalars().one()
    assert step.complete is already_complete
    assert result["preserved_completions"] == int(already_complete)
    assert not (await db.execute(select(AssignmentUserSubmission))).scalars().all()
    assert (await convert(db, 1, {}, 1, apply=True))["already_converted"] == 1


async def test_new_assessment_keeps_previous_completion_without_fabricating_grade(db, course, activity, progress):
    from scripts.convert_course_assessments import convert
    from src.db.courses.assignments import Assignment, AssignmentUserSubmission

    progress.status = StatusEnum.STATUS_COMPLETED
    db.add(progress)
    await db.commit()
    result = await convert(db, 1, {course.name: quiz_questions()}, 1, apply=True)
    await db.commit()
    assert result["new_activities"] == 1
    assignment = (await db.execute(select(Assignment))).scalars().one()
    step = (await db.execute(select(TrailStep).where(TrailStep.activity_id == assignment.activity_id))).scalars().one()
    assert step.complete
    assert step.grade == ""
    assert not (await db.execute(select(AssignmentUserSubmission))).scalars().all()


async def test_invalid_question_bank_blocks_all_conversion(db, course, activity):
    from scripts.convert_course_assessments import convert
    from src.db.courses.assignments import Assignment

    invalid = [{"question": "No key", "answers": [{"answer": "One"}, {"answer": "Two"}]}]
    with pytest.raises(ValueError, match="Invalid assessment question"):
        await convert(db, 1, {course.name: invalid}, 1, apply=True)
    assert not (await db.execute(select(Assignment))).scalars().all()
