"""Read-only learning progress from PostgreSQL; no event service required."""

from sqlalchemy import String, case, cast, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.activities import Activity
from src.db.courses.chapter_activities import ChapterActivity
from src.db.courses.courses import Course
from src.db.trail_runs import StatusEnum, TrailRun
from src.db.trail_steps import TrailStep
from src.db.user_organizations import UserOrganization
from src.db.users import User


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
        )
        .join(Course, (Course.id == TrailRun.course_id) & (Course.org_id == org_id))
        .join(
            UserOrganization,
            (UserOrganization.user_id == TrailRun.user_id)
            & (UserOrganization.org_id == org_id),
        )
        .outerjoin(totals, totals.c.course_id == Course.id)
        .outerjoin(steps, steps.c.trailrun_id == TrailRun.id)
        .where(TrailRun.org_id == org_id)
    )


def progress_row(row) -> dict:
    result = dict(row)
    result["progress_pct"] = round(float(result["progress_pct"] or 0), 1)
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
    return {
        "data": [progress_row(row) for row in rows],
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
