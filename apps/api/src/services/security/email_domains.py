"""Optional deployment-wide boundary for employee account creation and joining."""

import os

from fastapi import HTTPException


def enforce_allowed_email_domain(email: str) -> None:
    allowed = {
        domain.strip().lower()
        for domain in os.environ.get("LEARNHOUSE_ALLOWED_EMAIL_DOMAINS", "").split(",")
        if domain.strip()
    }
    if allowed and email.strip().lower().rsplit("@", 1)[-1] not in allowed:
        raise HTTPException(
            status_code=403,
            detail="Only accounts from the organization's approved email domains can join.",
        )


def verified_google_email(google_user: dict) -> str:
    email = google_user.get("email")
    verified = google_user.get("email_verified")
    is_verified = verified.strip().lower() == "true" if isinstance(verified, str) else verified is True
    if not isinstance(email, str) or not email.strip() or not is_verified:
        raise HTTPException(status_code=401, detail="Google did not return a verified email for this account")
    email = email.strip().lower()
    enforce_allowed_email_domain(email)
    workspace_domain = os.environ.get("LEARNHOUSE_GOOGLE_WORKSPACE_DOMAIN", "").strip().lower()
    if workspace_domain and str(google_user.get("hd", "")).strip().lower() != workspace_domain:
        raise HTTPException(status_code=403, detail="Please sign in with your organization's Google Workspace account.")
    return email


def enforce_google_signup(is_oauth: bool) -> None:
    if os.environ.get("LEARNHOUSE_GOOGLE_ONLY_SIGNUP", "").strip().lower() == "true" and not is_oauth:
        raise HTTPException(status_code=403, detail="Please use Google sign-in to join this organization.")


def enforce_google_org_join() -> None:
    # Restricted deployments must freshly verify Google's Workspace claims at
    # /auth/oauth, rather than trusting an old password or legacy session.
    if os.environ.get("LEARNHOUSE_GOOGLE_WORKSPACE_DOMAIN", "").strip():
        raise HTTPException(status_code=403, detail="Please open your invitation and use Google sign-in to join.")
