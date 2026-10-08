"""Employee onboarding through real membership/group writes and mocked Google/Redis."""

import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException, Response
from sqlmodel import select

from src.db.organization_config import OrganizationConfig
from src.db.usergroup_user import UserGroupUser
from src.db.usergroups import UserGroup
from src.db.user_organizations import UserOrganization
from src.db.users import AnonymousUser, User, UserCreate
from src.routers.auth import third_party_login
from src.services.orgs.invites import resolve_org_invitation
from src.services.orgs.join import JoinOrg, join_org
from src.services.security.email_domains import verified_google_email
from src.services.users.users import create_user, create_user_without_org

CODE_UUID = "org_invite_code_12345678-1234-1234-1234-123456789abc"


@pytest.fixture
def employee_boundary(monkeypatch):
    monkeypatch.setenv("LEARNHOUSE_ALLOWED_EMAIL_DOMAINS", "vizmo.in")
    monkeypatch.setenv("LEARNHOUSE_GOOGLE_WORKSPACE_DOMAIN", "vizmo.in")
    monkeypatch.setenv("LEARNHOUSE_GOOGLE_ONLY_SIGNUP", "true")


@pytest.mark.parametrize("claims,status", [
    ({"email": "employee@gmail.com", "email_verified": True, "hd": "vizmo.in"}, 403),
    ({"email": "employee@evilvizmo.in", "email_verified": True, "hd": "vizmo.in"}, 403),
    ({"email": "employee@sub.vizmo.in", "email_verified": True, "hd": "vizmo.in"}, 403),
    ({"email": "employee@vizmo.in", "email_verified": "false", "hd": "vizmo.in"}, 401),
    ({"email": "employee@vizmo.in", "email_verified": True}, 403),
    ({"email": "employee@vizmo.in", "email_verified": True, "hd": "other.in"}, 403),
])
def test_only_verified_workspace_identity_is_accepted(employee_boundary, claims, status):
    with pytest.raises(HTTPException) as exc:
        verified_google_email(claims)
    assert exc.value.status_code == status


def test_workspace_email_normalization(employee_boundary):
    assert verified_google_email({"email": " Employee@Vizmo.IN ", "email_verified": "true", "hd": "vizmo.in"}) == "employee@vizmo.in"


@pytest.mark.parametrize("with_org", [False, True])
async def test_public_password_signup_cannot_claim_an_employee_address(employee_boundary, db, mock_request, org, with_org):
    user = UserCreate(username="fakeemployee", email="fakeemployee@vizmo.in", password="Password-123456!")
    with pytest.raises(HTTPException) as exc:
        if with_org:
            await create_user(mock_request, db, AnonymousUser(), user, org.id)
        else:
            await create_user_without_org(mock_request, db, AnonymousUser(), user)
    assert exc.value.status_code == 403
    assert (await db.execute(select(User).where(User.email == user.email))).scalars().first() is None


@pytest.mark.parametrize("invite_kind", ["shared", "email", "email_retry"])
@pytest.mark.parametrize("existing_account", [False, True])
async def test_google_invite_creates_org_and_mapped_group_membership(
    employee_boundary, db, org, user_role, mock_request, invite_kind, existing_account,
):
    db.add(OrganizationConfig(org_id=org.id, config={"config_version": "1.0", "features": {"members": {"signup_mode": "inviteOnly"}}}))
    group = UserGroup(org_id=org.id, name="Vizmo", description="Employees", usergroup_uuid="ug_vizmo")
    db.add(group)
    if existing_account:
        user = User(email="employee@vizmo.in", username="employee", first_name="Employee", last_name="Test", password="", email_verified=True)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    await db.commit()
    await db.refresh(group)
    key = f"invited_user:employee@vizmo.in:org:{org.org_uuid}"
    code_key = f"{CODE_UUID}:org:{org.org_uuid}:code:GOOD1234"
    code = {"invite_code": "GOOD1234", "invite_code_uuid": CODE_UUID, "usergroup_id": group.id}
    records = {code_key: json.dumps(code)}
    if invite_kind != "shared":
        records[key] = json.dumps({"pending": invite_kind != "consumed_email", "invite_code_uuid": CODE_UUID})
    redis = Mock(get=lambda k: records.get(k), scan_iter=Mock(return_value=iter([code_key])), close=Mock())
    claims = {"email": "employee@vizmo.in", "email_verified": True, "hd": "vizmo.in", "given_name": "Employee", "family_name": "Test"}
    config = SimpleNamespace(redis_config=SimpleNamespace(redis_connection_string="redis://test"))
    with ExitStack() as stack:
        for target in ["src.routers.auth.get_google_user_info", "src.services.auth.utils.get_google_user_info"]:
            stack.enter_context(patch(target, AsyncMock(return_value=claims)))
        stack.enter_context(patch("src.services.orgs.invites.get_learnhouse_config", return_value=config))
        stack.enter_context(patch("src.services.orgs.invites._get_redis", return_value=redis))
        stack.enter_context(patch("redis.Redis.from_url", return_value=redis))
        for target in [
            "src.services.users.users.check_limits_with_usage", "src.services.users.users.increase_feature_usage",
            "src.security.features_utils.usage.check_limits_with_usage", "src.security.features_utils.usage.increase_feature_usage",
            "src.services.users.users.track", "src.services.users.users.dispatch_webhooks", "src.services.users.usergroups.dispatch_webhooks",
            "src.services.orgs.join_notifications.notify_user_joined_org", "src.services.auth.utils.record_audit_event",
        ]:
            stack.enter_context(patch(target, AsyncMock()))
        stack.enter_context(patch("src.services.users.users.send_account_creation_email"))
        stack.enter_context(patch("src.routers.users._invalidate_session_cache"))
        stack.enter_context(patch("src.routers.auth.issue_session_or_challenge", AsyncMock(return_value=SimpleNamespace(mfa_required=False, access_token="test", refresh_token="test"))))
        stack.enter_context(patch("src.routers.auth.set_auth_cookies"))
        if invite_kind == "email_retry":
            from src.services.users.usergroups import add_users_to_usergroup
            attempts = 0
            async def flaky_group_write(*args, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("transient group write failure")
                return await add_users_to_usergroup(*args, **kwargs)
            stack.enter_context(patch("src.services.users.usergroups.add_users_to_usergroup", flaky_group_write))
            with pytest.raises(HTTPException) as exc:
                await third_party_login(mock_request, Response(), SimpleNamespace(provider="google", access_token="google-test", email="forged@external.com"), org_id=org.id, current_user=AnonymousUser(), db_session=db)
            assert exc.value.status_code == 503
            redis.set.assert_not_called()
            redis.scan_iter.return_value = iter([code_key])
            await db.refresh(org)
            await db.refresh(group)
        result = await third_party_login(mock_request, Response(), SimpleNamespace(provider="google", access_token="google-test", email="forged@external.com"), org_id=org.id, invite_code="GOOD1234" if invite_kind == "shared" else None, current_user=AnonymousUser(), db_session=db)
        user_id = result["user"].id
        # Repeat shared links must repair or retain the group without duplicates.
        redis.scan_iter.return_value = iter([code_key])
        await third_party_login(mock_request, Response(), SimpleNamespace(provider="google", access_token="google-test", email="forged@external.com"), org_id=org.id, invite_code="GOOD1234", current_user=AnonymousUser(), db_session=db)
    assert len((await db.execute(select(UserOrganization).where(UserOrganization.user_id == user_id, UserOrganization.org_id == org.id))).scalars().all()) == 1
    assert len((await db.execute(select(UserGroupUser).where(UserGroupUser.user_id == user_id, UserGroupUser.usergroup_id == group.id))).scalars().all()) == 1
    if invite_kind in {"email", "email_retry"}:
        assert redis.set.call_args.kwargs == {"xx": True, "keepttl": True}
        assert json.loads(redis.set.call_args.args[1])["pending"] is False


@pytest.mark.parametrize("failure", ["expired", "redis_down", "group_removed"])
async def test_stale_invitation_cannot_lock_out_existing_member(db, org, failure):
    pending = json.dumps({"pending": True, "invite_code_uuid": CODE_UUID})
    code = json.dumps({"usergroup_id": 999999})
    redis = Mock(get=Mock(side_effect=[pending, code]), scan_iter=Mock(return_value=[] if failure == "expired" else ["key"]), close=Mock())
    if failure == "redis_down":
        redis.get.side_effect = OSError("offline")
    config = SimpleNamespace(redis_config=SimpleNamespace(redis_connection_string="redis://test"))
    with patch("src.services.orgs.invites.get_learnhouse_config", return_value=config), patch("redis.Redis.from_url", return_value=redis):
        assert await resolve_org_invitation(Mock(), org, "employee@vizmo.in", None, AnonymousUser(), db, existing_member=True) == (None, None)


async def test_signed_in_password_session_must_reauthenticate_with_google(employee_boundary, db, org, regular_user, mock_request):
    db.add(OrganizationConfig(org_id=org.id, config={"config_version": "1.0", "features": {"members": {"signup_mode": "inviteOnly"}}}))
    user = (await db.execute(select(User).where(User.id == regular_user.id))).scalars().one()
    user.email = "employee@vizmo.in"
    user.email_verified = True
    db.add(user)
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await join_org(mock_request, JoinOrg(org_id=org.id, user_id=regular_user.id, invite_code="GOOD1234"), regular_user, db)
    assert exc.value.status_code == 403
    assert "Google sign-in" in exc.value.detail


async def test_external_google_identity_cannot_redeem_an_employee_invite(employee_boundary, db, org, mock_request):
    claims = {"email": "outsider@gmail.com", "email_verified": True, "hd": "vizmo.in"}
    with patch("src.routers.auth.get_google_user_info", AsyncMock(return_value=claims)), patch("src.routers.auth.signWithGoogle", AsyncMock()) as sign:
        with pytest.raises(HTTPException) as exc:
            await third_party_login(mock_request, Response(), SimpleNamespace(provider="google", access_token="test", email="employee@vizmo.in"), org_id=org.id, invite_code="GOOD1234", current_user=AnonymousUser(), db_session=db)
    assert exc.value.status_code == 403
    sign.assert_not_awaited()


@pytest.mark.parametrize("code_data", [None, {"usergroup_id": 999999}])
async def test_removed_code_or_group_cannot_authorize_new_join(db, org, code_data):
    pending = json.dumps({"pending": True, "invite_code_uuid": CODE_UUID})
    redis = Mock(get=Mock(side_effect=[pending, json.dumps(code_data)]), scan_iter=Mock(return_value=[] if code_data is None else ["key"]), close=Mock())
    config = SimpleNamespace(redis_config=SimpleNamespace(redis_connection_string="redis://test"))
    with patch("src.services.orgs.invites.get_learnhouse_config", return_value=config), patch("redis.Redis.from_url", return_value=redis):
        with pytest.raises(HTTPException) as exc:
            await resolve_org_invitation(Mock(), org, "employee@vizmo.in", None, AnonymousUser(), db)
    assert exc.value.status_code == 403


async def test_shared_code_does_not_consume_unrelated_email_mapping(db, org):
    group = UserGroup(org_id=org.id, name="Shared group", description="", usergroup_uuid="ug_shared")
    db.add(group)
    await db.commit()
    await db.refresh(group)
    shared = {"invite_code_uuid": "org_invite_code_aaaaaaaa-1234-1234-1234-123456789abc", "usergroup_id": group.id}
    redis = Mock(get=Mock(return_value=json.dumps({"pending": True, "invite_code_uuid": CODE_UUID})), close=Mock())
    config = SimpleNamespace(redis_config=SimpleNamespace(redis_connection_string="redis://test"))
    with patch("src.services.orgs.invites.get_learnhouse_config", return_value=config), patch("src.services.orgs.invites.get_invite_code", AsyncMock(return_value=shared)), patch("redis.Redis.from_url", return_value=redis):
        code, pending_key = await resolve_org_invitation(Mock(), org, "employee@vizmo.in", "SHARED", AnonymousUser(), db)
    assert code == shared
    assert pending_key is None


async def test_accepted_email_invite_does_not_reapply_a_removed_group(db, org):
    redis = Mock(get=Mock(return_value=json.dumps({"pending": False, "invite_code_uuid": CODE_UUID})), close=Mock())
    config = SimpleNamespace(redis_config=SimpleNamespace(redis_connection_string="redis://test"))
    with patch("src.services.orgs.invites.get_learnhouse_config", return_value=config), patch("redis.Redis.from_url", return_value=redis):
        assert await resolve_org_invitation(Mock(), org, "employee@vizmo.in", None, AnonymousUser(), db, existing_member=True) == (None, None)
    redis.scan_iter.assert_not_called()
