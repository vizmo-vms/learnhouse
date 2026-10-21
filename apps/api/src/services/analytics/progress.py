"""Read-only learning progress from PostgreSQL; no event service required."""

from sqlalchemy import String, case, cast, func, tuple_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.activities import Activity
from src.db.courses.chapter_activities import ChapterActivity
from src.db.courses.courses import Course
from src.db.courses.study_time import CourseStudyTime
from src.db.trail_runs import StatusEnum, TrailRun
from src.db.trail_steps import TrailStep
from src.db.user_organizations import UserOrganization
from src.db.users import User
from src.db.courses.assessment_legacy_completions import AssessmentLegacyCompletion


async def assessment_results(db: AsyncSession, org_id: int, rows) -> dict:
    """Latest assessment attempts for this report page; never expose answer keys."""
    from src.db.courses.assignments import (
        Assignment, AssignmentTask, AssignmentUserSubmission,
        AssignmentUserSubmissionStatus,
    )
    from src.services.courses.activities.assignments import compute_assignment_grade

    pairs = {(row["user_id"], row["course_id"]) for row in rows if row["course_id"] is not None}
    if not pairs:
        return {}
    max_grades = (
        select(AssignmentTask.assignment_id, func.sum(AssignmentTask.max_grade_value).label("max_grade"))
        .where(AssignmentTask.org_id == org_id)
        .group_by(AssignmentTask.assignment_id).subquery()
    )
    results = (await db.execute(
        select(TrailRun.user_id, Assignment, AssessmentLegacyCompletion.user_id, AssignmentUserSubmission, max_grades.c.max_grade)
        .select_from(TrailRun)
        .join(Assignment, (Assignment.course_id == TrailRun.course_id) & (Assignment.org_id == org_id))
        .join(Activity, (Activity.id == Assignment.activity_id) & (Activity.org_id == org_id))
        .outerjoin(AssignmentUserSubmission,
                   (AssignmentUserSubmission.assignment_id == Assignment.id)
                   & (AssignmentUserSubmission.user_id == TrailRun.user_id))
        .outerjoin(max_grades, max_grades.c.assignment_id == Assignment.id)
        .outerjoin(AssessmentLegacyCompletion,
                   (AssessmentLegacyCompletion.assignment_id == Assignment.id)
                   & (AssessmentLegacyCompletion.user_id == TrailRun.user_id)
                   & (AssessmentLegacyCompletion.org_id == org_id))
        .where(
            TrailRun.org_id == org_id,
            tuple_(TrailRun.user_id, TrailRun.course_id).in_(sorted(pairs)),
            Assignment.published == True,
            Activity.published == True,
            Activity.id.in_(select(ChapterActivity.activity_id).where(
                ChapterActivity.course_id == Assignment.course_id,
                ChapterActivity.org_id == org_id,
            )),
        )
        .order_by(Assignment.id)
    )).all()
    by_enrollment = {}
    for user_id, assignment, preserved_user_id, submission, max_grade in results:
        status = submission.submission_status if submission else None
        graded = status == AssignmentUserSubmissionStatus.GRADED and not assignment.ungraded and (max_grade or 0) > 0
        grade = compute_assignment_grade(
            submission.grade, max_grade, assignment.grading_type,
            pass_threshold_percentage=assignment.pass_threshold_percentage,
        ) if graded else None
        by_enrollment.setdefault((user_id, assignment.course_id), []).append({
            "assignment_uuid": assignment.assignment_uuid,
            "title": assignment.title,
            "submission_status": getattr(status, "value", status) or "NOT_STARTED",
            "percentage": grade["percentage"] if grade else None,
            "passed": grade["passed"] if grade else None,
            "attempt_number": submission.attempt_number if submission else 0,
            "updated_at": submission.update_date if submission else None,
            "previous_completion_preserved": preserved_user_id is not None,
        })
    return by_enrollment


def published_activities(org_id: int):
    return (
        select(ChapterActivity.course_id, ChapterActivity.activity_id)
        .join(Activity, Activity.id == ChapterActivity.activity_id)
        .where(
            ChapterActivity.org_id == org_id,
            Activity.org_id == org_id,
            Activity.course_id == ChapterActivity.course_id,
            Activity.published == True,
        )
        .distinct()
        .subquery()
    )


def enrollment_progress(org_id: int):
    """One row per run; ignore draft, removed and another run's lesson steps."""
    activities = published_activities(org_id)
    totals = (
        select(activities.c.course_id, func.count().label("total"))
        .group_by(activities.c.course_id)
        .subquery()
    )
    steps = (
        select(
            TrailStep.trailrun_id,
            func.count(
                func.distinct(case((TrailStep.complete == True, TrailStep.activity_id)))
            ).label("done"),
            func.max(TrailStep.update_date).label("last_activity_at"),
        )
        .join(
            activities,
            (activities.c.course_id == TrailStep.course_id)
            & (activities.c.activity_id == TrailStep.activity_id),
        )
        .join(
            TrailRun,
            (TrailRun.id == TrailStep.trailrun_id)
            & (TrailRun.user_id == TrailStep.user_id)
            & (TrailRun.course_id == TrailStep.course_id)
            & (TrailRun.org_id == TrailStep.org_id),
        )
        .where(TrailStep.org_id == org_id)
        .group_by(TrailStep.trailrun_id)
        .subquery()
    )
    total = func.coalesce(totals.c.total, 0)
    done = func.coalesce(steps.c.done, 0)
    return (
        select(
            TrailRun.id.label("trailrun_id"),
            TrailRun.user_id,
            TrailRun.course_id,
            Course.course_uuid,
            Course.name.label("course_name"),
            TrailRun.status,
            TrailRun.creation_date.label("enrolled_at"),
            TrailRun.update_date.label("updated_at"),
            done.label("activities_completed"),
            total.label("activities_total"),
            case((total > 0, 100.0 * done / total), else_=0.0).label("progress_pct"),
            steps.c.last_activity_at,
            case((CourseStudyTime.first_seen_at.is_not(None), CourseStudyTime.active_ms / 1000.0)).label("active_seconds"),
            CourseStudyTime.partially_tracked,
            CourseStudyTime.completed_at.label("study_completed_at"),
        )
        .join(Course, (Course.id == TrailRun.course_id) & (Course.org_id == org_id))
        .join(
            UserOrganization,
            (UserOrganization.user_id == TrailRun.user_id)
            & (UserOrganization.org_id == org_id),
        )
        .outerjoin(CourseStudyTime,
                   (CourseStudyTime.user_id == TrailRun.user_id)
                   & (CourseStudyTime.course_id == TrailRun.course_id)
                   & (CourseStudyTime.org_id == org_id))
        .outerjoin(totals, totals.c.course_id == Course.id)
        .outerjoin(steps, steps.c.trailrun_id == TrailRun.id)
        .where(TrailRun.org_id == org_id)
    )


def progress_row(row) -> dict:
    result = dict(row)
    result["progress_pct"] = round(float(result["progress_pct"] or 0), 1)
    result["active_seconds"] = round(float(result["active_seconds"]), 3) if result.get("active_seconds") is not None else None
    result["partially_tracked"] = bool(result.get("partially_tracked"))
    result["status"] = getattr(result["status"], "value", result["status"])
    return result


async def learner_progress(
    db: AsyncSession,
    org_id: int,
    acting_user_id: int,
    course_id: int | None,
    search: str,
    status: str | None,
    page: int,
    per_page: int,
) -> dict:
    from src.services.demo.guards import hide_other_visitors, is_demo_org

    enrollments = enrollment_progress(org_id)
    if course_id is not None:
        enrollments = enrollments.where(TrailRun.course_id == course_id)
    e = enrollments.subquery()
    statement = (
        select(
            User.id.label("user_id"),
            User.first_name,
            User.last_name,
            User.username,
            User.email,
            e.c.trailrun_id,
            e.c.course_id,
            e.c.course_uuid,
            e.c.course_name,
            func.coalesce(cast(e.c.status, String), "NOT_ENROLLED").label("status"),
            e.c.enrolled_at,
            e.c.updated_at,
            func.coalesce(e.c.activities_completed, 0).label("activities_completed"),
            func.coalesce(e.c.activities_total, 0).label("activities_total"),
            func.coalesce(e.c.progress_pct, 0).label("progress_pct"),
            e.c.last_activity_at,
            e.c.active_seconds,
            e.c.partially_tracked,
            e.c.study_completed_at,
        )
        .join(
            UserOrganization,
            (UserOrganization.user_id == User.id) & (UserOrganization.org_id == org_id),
        )
        .outerjoin(e, e.c.user_id == User.id)
    )
    if await is_demo_org(org_id, db):
        statement = hide_other_visitors(statement, acting_user_id)
    if search.strip():
        # Treat % and _ as literal search text, not SQL wildcards.
        term = (
            "%"
            + search.strip()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            + "%"
        )
        statement = statement.where(
            User.first_name.ilike(term, escape="\\")
            | User.last_name.ilike(term, escape="\\")
            | (User.first_name + " " + User.last_name).ilike(term, escape="\\")
            | User.username.ilike(term, escape="\\")
            | User.email.ilike(term, escape="\\")
            | e.c.course_name.ilike(term, escape="\\")
        )
    if status == "NOT_ENROLLED":
        statement = statement.where(e.c.trailrun_id.is_(None))
    elif status:
        statement = statement.where(e.c.status == status)

    filtered = statement.subquery()
    summary = dict(
        (
            await db.execute(
                select(
                    func.count().label("total"),
                    func.count(func.distinct(filtered.c.user_id)).label("learners"),
                    func.count(filtered.c.trailrun_id).label("enrollments"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    filtered.c.status
                                    == StatusEnum.STATUS_COMPLETED.value,
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("completions"),
                    func.avg(
                        case(
                            (
                                filtered.c.trailrun_id.is_not(None),
                                filtered.c.progress_pct,
                            )
                        )
                    ).label("average_progress"),
                ).select_from(filtered)
            )
        )
        .mappings()
        .one()
    )
    summary["average_progress"] = round(float(summary["average_progress"] or 0), 1)
    rows = (
        (
            await db.execute(
                statement.order_by(
                    e.c.last_activity_at.desc().nulls_last(), User.id, e.c.trailrun_id
                )
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        )
        .mappings()
        .all()
    )
    assessments = await assessment_results(db, org_id, rows)
    return {
        "data": [dict(progress_row(row), assessments=assessments.get((row["user_id"], row["course_id"]), [])) for row in rows],
        "summary": summary,
        "total": summary["total"],
        "page": page,
        "per_page": per_page,
    }


async def postgres_overview(org_id: int, db: AsyncSession) -> dict:
    e = enrollment_progress(org_id).subquery()
    summary = dict(
        (
            await db.execute(
                select(
                    select(func.count(UserOrganization.id))
                    .where(UserOrganization.org_id == org_id)
                    .scalar_subquery()
                    .label("learners"),
                    select(func.count(Course.id))
                    .where(Course.org_id == org_id)
                    .scalar_subquery()
                    .label("courses"),
                    func.count(e.c.trailrun_id).label("enrollments"),
                    func.coalesce(
                        func.sum(
                            case(
                                (e.c.status == StatusEnum.STATUS_COMPLETED, 1), else_=0
                            )
                        ),
                        0,
                    ).label("completions"),
                    func.coalesce(func.sum(e.c.activities_completed), 0).label(
                        "completed_activities"
                    ),
                ).select_from(e)
            )
        )
        .mappings()
        .one()
    )
    summary["completion_rate"] = (
        round(summary["completions"] / summary["enrollments"] * 100, 1)
        if summary["enrollments"]
        else 0.0
    )
    a = published_activities(org_id)
    totals = (
        select(a.c.course_id, func.count().label("total"))
        .group_by(a.c.course_id)
        .subquery()
    )
    courses = (
        (
            await db.execute(
                select(
                    Course.course_uuid,
                    Course.name,
                    Course.published,
                    func.count(e.c.trailrun_id).label("enrollments"),
                    func.coalesce(
                        func.sum(
                            case(
                                (e.c.status == StatusEnum.STATUS_COMPLETED, 1), else_=0
                            )
                        ),
                        0,
                    ).label("completions"),
                    func.coalesce(totals.c.total, 0).label("activities"),
                    func.coalesce(func.avg(e.c.progress_pct), 0).label(
                        "average_progress"
                    ),
                )
                .outerjoin(e, e.c.course_id == Course.id)
                .outerjoin(totals, totals.c.course_id == Course.id)
                .where(Course.org_id == org_id)
                .group_by(
                    Course.id,
                    Course.course_uuid,
                    Course.name,
                    Course.published,
                    totals.c.total,
                )
                .order_by(func.count(e.c.trailrun_id).desc(), Course.name)
            )
        )
        .mappings()
        .all()
    )
    recent = (
        (
            await db.execute(
                select(
                    e.c.enrolled_at,
                    e.c.status,
                    e.c.course_uuid,
                    e.c.course_name,
                    func.coalesce(
                        func.nullif(
                            func.trim(User.first_name + " " + User.last_name), ""
                        ),
                        User.username,
                        "Learner",
                    ).label("learner_name"),
                )
                .join(User, User.id == e.c.user_id)
                .order_by(e.c.enrolled_at.desc(), e.c.trailrun_id.desc())
                .limit(10)
            )
        )
        .mappings()
        .all()
    )
    return {
        "summary": summary,
        "courses": [
            {
                **dict(row),
                "average_progress": round(float(row["average_progress"] or 0), 1),
            }
            for row in courses
        ],
        "recent_enrollments": [dict(row) for row in recent],
    }
