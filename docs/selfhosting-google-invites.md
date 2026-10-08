# Employee Google sign-in and invitations

The Vizmo deployment keeps public password signup hidden. `/signup?inviteCode=...`
redirects to `/login?inviteCode=...`, and Google login carries the code into the
API. Already signed-in employees can use the same link and sign in with Google
again to prove their current Workspace identity.

Set these server environment variables in the deployment environment file, then
reference them in the Compose app service environment:

```dotenv
LEARNHOUSE_ALLOWED_EMAIL_DOMAINS=vizmo.in
LEARNHOUSE_GOOGLE_WORKSPACE_DOMAIN=vizmo.in
LEARNHOUSE_GOOGLE_ONLY_SIGNUP=true
```

```yaml
environment:
  LEARNHOUSE_ALLOWED_EMAIL_DOMAINS: ${LEARNHOUSE_ALLOWED_EMAIL_DOMAINS}
  LEARNHOUSE_GOOGLE_WORKSPACE_DOMAIN: ${LEARNHOUSE_GOOGLE_WORKSPACE_DOMAIN}
  LEARNHOUSE_GOOGLE_ONLY_SIGNUP: ${LEARNHOUSE_GOOGLE_ONLY_SIGNUP}
```

- The email allowlist uses exact domains and supports comma-separated entries.
- The Workspace check requires Google's verified email and hosted-domain (`hd`)
  claim. Request-body email addresses are never used to authorize joining.
- Google-only signup rejects public password account creation, including attempts
  to claim an allowed email address through the API.
- Workspace-restricted deployments join through fresh Google OAuth. The generic
  authenticated join endpoint directs callers back to Google sign-in.
- Keep the organization's join mode **Closed** to require a shareable code or a
  pending email invitation for new members. Existing members can log in normally.
- The group is resolved from the supplied code or the code UUID stored on a
  pending email invitation, and must belong to the same organization.
- Group assignment is idempotent. Reopening a valid code link also applies its
  mapped group to an existing member. A group-write failure is reported and the
  email invitation remains pending for retry.
- Accepted email invitations are not reapplied on ordinary login, so removing a
  member from a group remains effective. Historical missed assignments need a
  one-time repair or explicit acceptance of the valid code link.

Without these environment variables, upstream deployments retain unrestricted
email domains and their existing signup/join behavior.
