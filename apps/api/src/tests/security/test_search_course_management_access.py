"""Lesson search must preserve the fork's organization-scoped course management rights."""

import pytest
from fastapi import HTTPException

from src.db.roles import Role, RoleTypeEnum
from src.db.user_organizations import UserOrganization
from src.services.courses.activities.access import verify_activity_reader_access
from src.services.search.search import search_across_org
from src.tests.conftest import USER_RIGHTS
from src.tests.security.test_course_management_access import assign_role, restrict_course


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["manager", "maintainer"])
@pytest.mark.parametrize("restriction", ["course_group", "lesson_locks", "both"])
async def test_managers_find_lessons_they_can_already_read(
    db, org, course, chapter, activity, regular_user, mock_request, kind, restriction,
):
    await assign_role(db, regular_user, org, kind=kind)
    if restriction in {"course_group", "both"}:
        await restrict_course(db, org, course)
    if restriction in {"lesson_locks", "both"}:
        chapter.lock_type = "restricted"
        activity.lock_type = "restricted"
        db.add(chapter)
        db.add(activity)
        await db.commit()

    await verify_activity_reader_access(mock_request, activity, course, regular_user, db)
    result = await search_across_org(mock_request, regular_user, org.slug, "Test", db)

    assert [c.course_uuid for c in result.courses] == [course.course_uuid]
    assert [a.activity_uuid for a in result.activities] == [activity.activity_uuid]
    assert result.total_activities == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["learner", "instructor"])
async def test_learner_and_own_only_roles_cannot_search_other_department_lessons(
    db, org, course, activity, regular_user, mock_request, kind,
):
    await assign_role(db, regular_user, org, kind=kind)
    await restrict_course(db, org, course)

    with pytest.raises(HTTPException) as exc:
        await verify_activity_reader_access(mock_request, activity, course, regular_user, db)
    assert exc.value.status_code == 403
    result = await search_across_org(mock_request, regular_user, org.slug, "Test", db)

    assert result.courses == []
    assert result.activities == []
    assert result.total_activities == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["manager", "maintainer"])
async def test_course_management_in_another_org_does_not_grant_lesson_search(
    db, org, other_org, course, chapter, activity, regular_user, mock_request, kind,
):
    await assign_role(db, regular_user, org, kind=kind)
    course.org_id = other_org.id
    chapter.org_id = other_org.id
    activity.org_id = other_org.id
    db.add(course)
    db.add(chapter)
    db.add(activity)
    db.add(Role(
        id=11,
        name="Other org learner",
        org_id=other_org.id,
        role_type=RoleTypeEnum.TYPE_ORGANIZATION,
        role_uuid="role_other_org_learner",
        rights=USER_RIGHTS.model_dump(),
    ))
    db.add(UserOrganization(
        user_id=regular_user.id,
        org_id=other_org.id,
        role_id=11,
        creation_date="",
        update_date="",
    ))
    await db.commit()
    await restrict_course(db, other_org, course)

    with pytest.raises(HTTPException) as exc:
        await verify_activity_reader_access(mock_request, activity, course, regular_user, db)
    assert exc.value.status_code == 403
    result = await search_across_org(mock_request, regular_user, other_org.slug, "Test", db)

    assert result.courses == []
    assert result.activities == []
    assert result.total_activities == 0
