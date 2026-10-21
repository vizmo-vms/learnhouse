"""Convert standalone inline quizzes to native assessments, atomically.

Run from apps/api with PYTHONPATH=.; defaults to a read-only plan. Supply a
private JSON map of course names to inline-format questions for missing quizzes.
Take database/media backups and rehearse against a database copy before --apply.
No answer keys or employee identifiers are printed.
"""
import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import delete, func, text
from sqlmodel import select

from src.db.course_embeddings import CourseEmbedding
from src.db.courses.activities import Activity, ActivitySubTypeEnum, ActivityTypeEnum
from src.db.courses.activity_versions import ActivityVersion
from src.db.courses.assignments import Assignment, AssignmentTask
from src.db.courses.assessment_legacy_completions import AssessmentLegacyCompletion
from src.db.courses.certifications import CertificateUser, Certifications
from src.db.courses.chapter_activities import ChapterActivity
from src.db.courses.course_chapters import CourseChapter
from src.db.courses.courses import Course
from src.db.trail_runs import StatusEnum, TrailRun
from src.db.trail_steps import TrailStep

ROLLOUT = "assessment_rollout"
DESCRIPTION = (
    "Complete every lesson and pass this assessment to earn your certificate. "
    "The pass mark is 80%. You have three total attempts. Answer every question "
    "before submitting. Answer keys are not revealed. There is no time limit."
)


def native_questions(questions, seed):
    """Translate keys on the server; a learner never receives these flags."""
    if not isinstance(questions, list) or not questions:
        raise ValueError("An assessment needs questions")
    converted = []
    for index, question in enumerate(questions):
        answers = question.get("answers", [])
        if (not question.get("question", "").strip() or len(answers) < 2
                or any(not a.get("answer", "").strip() for a in answers)
                or not any(a.get("correct") is True for a in answers)):
            raise ValueError(f"Invalid assessment question {index + 1}")
        correct = sum(a.get("correct") is True for a in answers)
        response = question.get("response_type") or ("multiple" if correct > 1 else "single")
        if response not in ("single", "multiple") or (response == "single" and correct != 1):
            raise ValueError(f"Invalid response mode for question {index + 1}")
        qid = str(uuid5(NAMESPACE_URL, f"{seed}/question/{index}"))
        converted.append({
            "questionUUID": f"question_{qid}", "questionText": question["question"],
            "response_type": response,
            "options": [{
                "optionUUID": f"option_{uuid5(NAMESPACE_URL, f'{qid}/{i}')}",
                "text": answer["answer"], "type": "text", "fileID": "",
                "assigned_right_answer": answer.get("correct") is True,
            } for i, answer in enumerate(answers)],
        })
    return {"questions": converted, "grading_mode": "all_or_nothing"}


async def convert(db, org_id, drafts, expected_count, apply=False):
    if db.bind.dialect.name == "postgresql":
        await db.execute(text("SET LOCAL lock_timeout = '5s'"))
        locked = (await db.execute(text("SELECT pg_try_advisory_xact_lock(1792410784, :org)"), {"org": org_id})).scalar_one()
        if not locked:
            raise ValueError("Another assessment migration is running")
    courses = (await db.execute(select(Course).where(Course.org_id == org_id, Course.published == True).order_by(Course.id))).scalars().all()
    if len(courses) != expected_count:
        raise ValueError("Published course count changed; inspect a fresh plan")
    plan = []
    skipped = 0
    for course in courses:
        activities = (await db.execute(select(Activity).where(Activity.course_id == course.id, Activity.org_id == org_id).with_for_update())).scalars().all()
        if any((a.extra_metadata or {}).get(ROLLOUT) for a in activities):
            skipped += 1
            continue
        if (await db.execute(select(Assignment.id).where(Assignment.course_id == course.id))).first():
            raise ValueError(f"Course {course.id} already has an assessment; review manually")
        quizzes = [(a, [n for n in (a.content or {}).get("content", []) if n.get("type") == "blockQuiz"]) for a in activities]
        quizzes = [(a, blocks) for a, blocks in quizzes if blocks]
        if quizzes:
            if len(quizzes) != 1 or len(quizzes[0][1]) != 1:
                raise ValueError(f"Course {course.id} needs a manual consolidation")
            activity, blocks = quizzes[0]
            if any(n.get("type") not in ("paragraph", "blockQuiz") for n in activity.content.get("content", [])):
                raise ValueError(f"Course {course.id} quiz also contains lesson material")
            questions = blocks[0].get("attrs", {}).get("questions", [])
            link = (await db.execute(select(ChapterActivity).where(ChapterActivity.activity_id == activity.id, ChapterActivity.course_id == course.id))).scalars().one()
            chapter_id = link.chapter_id
        else:
            activity = None
            questions = drafts.get(course.name)
            chapter_id = (await db.execute(select(CourseChapter.chapter_id).where(CourseChapter.course_id == course.id).order_by(CourseChapter.order.desc()).limit(1))).scalar_one()
        contents = native_questions(questions, course.course_uuid)
        plan.append((course, activity, chapter_id, contents))
    summary = {"converted": len(plan), "already_converted": skipped, "questions": sum(len(p[3]["questions"]) for p in plan), "new_activities": sum(p[1] is None for p in plan)}
    if not apply:
        return summary
    now = datetime.now(timezone.utc).isoformat()
    preserved = reset = 0
    for course, activity, chapter_id, contents in plan:
        runs = (await db.execute(select(TrailRun).where(TrailRun.course_id == course.id, TrailRun.org_id == org_id).with_for_update())).scalars().all()
        certified = set((await db.execute(select(CertificateUser.user_id).join(Certifications, Certifications.id == CertificateUser.certification_id).where(Certifications.course_id == course.id))).scalars().all())
        legacy_users = certified | {r.user_id for r in runs if r.status == StatusEnum.STATUS_COMPLETED}
        marker = {"at": now}
        if activity is None:
            activity = Activity(
                name="Course assessment", activity_type=ActivityTypeEnum.TYPE_ASSIGNMENT,
                activity_sub_type=ActivitySubTypeEnum.SUBTYPE_ASSIGNMENT_ANY,
                content={}, published=True, org_id=org_id, course_id=course.id,
                activity_uuid=f"activity_{uuid5(NAMESPACE_URL, course.course_uuid + '/assessment-v1')}",
                creation_date=now, update_date=now,
            )
            db.add(activity)
            await db.flush()
            last_order = (await db.execute(select(func.max(ChapterActivity.order)).where(ChapterActivity.chapter_id == chapter_id))).scalar_one()
            db.add(ChapterActivity(activity_id=activity.id, chapter_id=chapter_id, course_id=course.id, org_id=org_id, order=(last_order or 0) + 1, creation_date=now, update_date=now))
        else:
            marker["previous_type"] = activity.activity_type.value
            marker["previous_subtype"] = activity.activity_sub_type.value
            marker["previous_name"] = activity.name
            db.add(ActivityVersion(activity_id=activity.id, org_id=org_id, version_number=activity.current_version, content=activity.content, created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
            activity.current_version += 1
            activity.name = re.sub(r"\bquiz\b", "assessment", activity.name, flags=re.I)
            activity.activity_type = ActivityTypeEnum.TYPE_ASSIGNMENT
            activity.activity_sub_type = ActivitySubTypeEnum.SUBTYPE_ASSIGNMENT_ANY
            activity.content = {}
            activity.update_date = now
        activity.extra_metadata = {**(activity.extra_metadata or {}), ROLLOUT: marker}
        db.add(activity)
        assignment = Assignment(
            title=f"{course.name} — Assessment", description=DESCRIPTION,
            due_date=None, published=True, grading_type="PERCENTAGE", auto_grading=True,
            show_correct_answers=False, solution_reveal="NEVER", allow_retries=True,
            max_retries=3, pass_threshold_percentage=80, ungraded=False,
            org_id=org_id, course_id=course.id, chapter_id=chapter_id, activity_id=activity.id,
            assignment_uuid=f"assignment_{uuid5(NAMESPACE_URL, course.course_uuid + '/assessment-v1')}",
            creation_date=now, update_date=now,
        )
        db.add(assignment)
        await db.flush()
        for user_id in legacy_users:
            db.add(AssessmentLegacyCompletion(assignment_id=assignment.id, activity_id=activity.id, user_id=user_id, org_id=org_id, course_id=course.id, preserved_at=now))
        db.add(AssignmentTask(
            title="Course knowledge assessment", description="Answer every question, then submit for grading.", hint="",
            assignment_type="QUIZ", contents=contents, max_grade_value=100, order=0,
            assignment_id=assignment.id, org_id=org_id, course_id=course.id, chapter_id=chapter_id, activity_id=activity.id,
            assignment_task_uuid=f"assignmenttask_{uuid5(NAMESPACE_URL, assignment.assignment_uuid + '/questions')}",
            creation_date=now, update_date=now,
        ))
        steps = (await db.execute(select(TrailStep).where(TrailStep.activity_id == activity.id))).scalars().all()
        for step in steps:
            if step.user_id not in legacy_users and step.complete:
                step.complete = False
                step.update_date = now
                db.add(step)
                reset += 1
        for run in runs:
            if run.user_id not in legacy_users:
                continue
            existing = next((s for s in steps if s.trailrun_id == run.id and s.user_id == run.user_id), None)
            if existing:
                existing.complete = True
                db.add(existing)
            else:
                db.add(TrailStep(complete=True, teacher_verified=False, grade="", data={"prior_completion_preserved": True}, trailrun_id=run.id, trail_id=run.trail_id, activity_id=activity.id, course_id=course.id, org_id=org_id, user_id=run.user_id, creation_date=now, update_date=now))
            preserved += 1
        # Remove obsolete search snippets; the normal scheduler rebuilds them
        # from the assessment extractor's allowlist (never answer keys).
        await db.execute(delete(CourseEmbedding).where(CourseEmbedding.activity_id == activity.id))
        course.description = re.sub(r"\bquiz\b", "assessment", course.description or "", flags=re.I)
        db.add(course)
    await db.flush()
    return dict(summary, preserved_completions=preserved, reset_ungraded_checks=reset)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", type=int, required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--drafts", type=Path, required=True)
    parser.add_argument("--database", help="Optional database copy on the configured server")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--prepare-schema", action="store_true", help="Create only the empty preservation ledger before deploying the new API")
    args = parser.parse_args()
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession
    from src.core.events.database import engine
    target = create_async_engine(engine.url.set(database=args.database)) if args.database else engine
    factory = async_sessionmaker(target, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        if args.apply or args.prepare_schema:
            connection = await db.connection()
            await connection.run_sync(lambda sync: AssessmentLegacyCompletion.__table__.create(sync, checkfirst=True))
        if args.prepare_schema:
            await db.commit()
            print(json.dumps({"preservation_schema_ready": True, "course_data_changed": False}))
            await target.dispose()
            return
        result = await convert(db, args.org_id, json.loads(args.drafts.read_text()), args.expected_count, args.apply)
        if args.apply:
            await db.commit()
        else:
            await db.rollback()
        print(json.dumps(dict(result, applied=args.apply)))
    await target.dispose()


if __name__ == "__main__":
    asyncio.run(main())
