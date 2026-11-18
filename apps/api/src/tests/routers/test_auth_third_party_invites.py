"""Invite handling in the third_party_login OAuth handler (src/routers/auth.py).

test_auth_third_party.py covers the gate itself (open org, missing invite,
existing member, Redis down). These cover what happens once an invite is
found: a pending email invite is honoured and then marked accepted, an invite
code's usergroup is attached, and a failed group assignment prompts a retry.
"""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest
from fastapi import HTTPException, Response, status

from src.db.organization_config import OrganizationConfig
from src.db.usergroups import UserGroup
from src.db.users import AnonymousUser
from src.routers.auth import third_party_login

# The handler reads the config again after sign-in (custom-domain binding), so
# the fake carries a single-tenant hosting block that skips that lookup.
_REDIS_CONFIG = SimpleNamespace(
    redis_config=SimpleNamespace(redis_connection_string="redis://localhost:6379"),
    hosting_config=SimpleNamespace(tenancy="single"),
)


async def _make_invite_only(db, org_id: int):
    db.add(
        OrganizationConfig(
            org_id=org_id,
            config={
                "config_version": "1.0",
                "features": {"members": {"signup_mode": "inviteOnly"}},
            },
        )
    )
    await db.commit()


def _google_body(email="invitee@example.com"):
    return SimpleNamespace(email=email, provider="google", access_token="tok")


def _invite_key(email, org):
    return f"invited_user:{email}:org:{org.org_uuid}"


async def _login(db, org, body=None, invite_code=None):
    return await third_party_login(
        request=SimpleNamespace(),
        response=Response(),
        body=body or _google_body(),
        org_id=org.id,
        invite_code=invite_code,
        current_user=AnonymousUser(),
        db_session=db,
    )


@pytest.fixture
def signed_in():
    """Patch the Google round-trip and cookie writing so the handler runs to
    completion; yields the signWithGoogle mock."""
    sign_with_google = AsyncMock(
        return_value=SimpleNamespace(id=7, email="invitee@example.com")
    )
    with patch("src.routers.auth.signWithGoogle", sign_with_google), patch(
        "src.routers.auth.set_auth_cookies"
    ), patch("src.routers.auth.UserRead") as user_read, patch(
        "src.routers.auth.get_google_user_info",
        AsyncMock(return_value={"email": "invitee@example.com", "email_verified": True}),
    ):
        user_read.model_validate.side_effect = lambda u: u
        yield sign_with_google


@pytest.fixture
def redis_server():
    """A shared fake Redis server; every ``Redis.from_url`` call gets a fresh
    client on it, like the real connection pool would."""
    server = fakeredis.FakeServer()
    with patch(
        "src.routers.auth.get_learnhouse_config", return_value=_REDIS_CONFIG
    ), patch(
        "redis.Redis.from_url",
        side_effect=lambda *a, **k: fakeredis.FakeRedis(server=server),
    ):
        yield server


class TestNonGoogleProviderInInviteOnlyOrg:
    async def test_unsupported_provider_is_rejected_before_invite_lookup(self, db, org):
        """Only a verified Google identity can authorize an OAuth invitation."""
        await _make_invite_only(db, org.id)
        mock_redis = MagicMock(get=MagicMock(return_value=None))

        with patch(
            "src.routers.auth.get_learnhouse_config", return_value=_REDIS_CONFIG
        ), patch("redis.Redis.from_url", return_value=mock_redis):
            with pytest.raises(HTTPException) as exc_info:
                await _login(
                    db,
                    org,
                    body=SimpleNamespace(
                        email="  Invitee@Example.COM ",
                        provider="github",
                        access_token="tok",
                    ),
                )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "Unsupported provider"
        mock_redis.get.assert_not_called()


class TestPendingEmailInvite:
    async def test_invalid_shared_code_does_not_consume_pending_email_invite(
        self, db, org, signed_in, redis_server
    ):
        """A shared link must resolve its own code and group mapping."""
        await _make_invite_only(db, org.id)
        key = _invite_key("invitee@example.com", org)
        seed = fakeredis.FakeRedis(server=redis_server)
        seed.set(key, json.dumps({"email": "invitee@example.com", "pending": True}), ex=3600)

        with patch(
            "src.services.orgs.invites.get_invite_code",
            AsyncMock(side_effect=HTTPException(status_code=404, detail="Invalid code")),
        ):
            with pytest.raises(HTTPException) as invalid:
                await _login(db, org, invite_code="BADCODE")
            assert invalid.value.status_code == 404
            assert json.loads(seed.get(key))["pending"] is True
            signed_in.assert_not_awaited()

        result = await _login(db, org)
        assert result["tokens"]["access_token"]
        assert signed_in.await_args.args[3] == org.id

        record = json.loads(seed.get(key))
        assert record["pending"] is False
        assert 0 < seed.ttl(key) <= 3600

    async def test_invite_without_ttl_is_kept_without_expiry(
        self, db, org, signed_in, redis_server
    ):
        await _make_invite_only(db, org.id)
        key = _invite_key("invitee@example.com", org)
        seed = fakeredis.FakeRedis(server=redis_server)
        seed.set(key, json.dumps({"pending": True}))

        await _login(db, org)

        assert json.loads(seed.get(key))["pending"] is False
        assert seed.ttl(key) == -1

    async def test_failure_to_mark_invite_accepted_does_not_fail_sign_in(
        self, db, org, signed_in, caplog
    ):
        await _make_invite_only(db, org.id)
        gate_client = MagicMock(get=MagicMock(return_value=b'{"pending": true}'))
        # Second connection (the "mark accepted" step) is broken end to end,
        # including close().
        broken_client = MagicMock(
            get=MagicMock(side_effect=ConnectionError("redis went away")),
            close=MagicMock(side_effect=ConnectionError("already closed")),
        )

        with patch(
            "src.routers.auth.get_learnhouse_config", return_value=_REDIS_CONFIG
        ), patch(
            "redis.Redis.from_url", side_effect=[gate_client, broken_client]
        ), caplog.at_level(logging.WARNING, logger="src.services.orgs.invites"):
            result = await _login(db, org)

        assert result["tokens"]["access_token"]
        broken_client.set.assert_not_called()
        broken_client.close.assert_called_once()
        assert "Could not mark invitation as accepted" in caplog.text


@pytest.fixture
async def invite_group(db, org):
    group = UserGroup(org_id=org.id, name="New employees", description="", usergroup_uuid="usergroup_oauth_invite")
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


class TestInviteCodeUsergroup:
    async def test_usergroup_from_invite_code_is_attached(self, db, org, signed_in, redis_server, invite_group):
        await _make_invite_only(db, org.id)
        add_to_group = AsyncMock()

        with patch(
            "src.services.orgs.invites.get_invite_code",
            AsyncMock(return_value={"invite_code": "CODE", "usergroup_id": str(invite_group.id)}),
        ), patch("src.services.users.usergroups.add_users_to_usergroup", add_to_group):
            result = await _login(db, org, invite_code="CODE")

        assert result["tokens"]["access_token"]
        args = add_to_group.await_args.args
        # usergroup id coerced to int, user id passed as the comma-list string.
        assert args[3] == invite_group.id
        assert args[4] == "7"

    async def test_usergroup_failure_requires_retry(
        self, db, org, signed_in, redis_server, invite_group, caplog
    ):
        await _make_invite_only(db, org.id)

        with patch(
            "src.services.orgs.invites.get_invite_code",
            AsyncMock(return_value={"invite_code": "CODE", "usergroup_id": invite_group.id}),
        ), patch(
            "src.services.users.usergroups.add_users_to_usergroup",
            AsyncMock(side_effect=HTTPException(status_code=400, detail="gone")),
        ), caplog.at_level(logging.WARNING, logger="src.routers.auth"):
            with pytest.raises(HTTPException) as error:
                await _login(db, org, invite_code="CODE")

        assert error.value.status_code == 503
        assert "Could not attach OAuth user to invite usergroup" in caplog.text
