"""Closed purposes share existing capacity and delivery groups; no new quota."""

NOTICES = frozenset(
    {
        "password_changed",
        "password_added",
        "email_changed",
        "google_linked",
        "google_unlinked",
    }
)
ACCOUNT_TOKENS = frozenset({"email_change_new", "email_change_old", "password_add"})
GROUPS = {
    "password_changed": tuple(sorted(NOTICES)),
    "reset_password": ("reset_password",),
    "verify_email": ("verify_email", *sorted(ACCOUNT_TOKENS)),
}
PURPOSES = frozenset(purpose for values in GROUPS.values() for purpose in values)


def group(purpose):
    for name, values in GROUPS.items():
        if purpose in values:
            return name
    raise ValueError("account_mail_purpose_invalid")


def recipient_group(purpose):
    name = group(purpose)
    if name == "password_changed":
        raise ValueError("account_mail_purpose_invalid")
    return name


# Exact request/session/epoch/primary and optional Google provenance for all
# new token jobs, reused by enqueue and the worker's pre-delivery eligibility.
ACCOUNT_MAIL_SQL = (
    "EXISTS (SELECT 1 FROM app.account_security_requests r JOIN app.users u ON u.id=r.user_id "
    "JOIN app.user_emails e ON e.user_id=u.id AND e.is_primary AND e.verified_at IS NOT NULL "
    "JOIN app.sessions s ON s.user_id=u.id AND s.id=r.session_id "
    "WHERE r.id=c.account_request_id AND r.user_id=c.user_id AND r.session_id=c.session_id "
    "AND r.auth_epoch=c.password_auth_epoch AND u.auth_epoch=r.auth_epoch AND u.status='active' "
    "AND r.consumed_at IS NULL AND r.expires_at=c.expires_at AND r.expires_at>clock_timestamp() "
    "AND e.id=r.source_email_id AND e.email_key=r.source_email_key AND u.email_revision=r.source_email_revision "
    "AND s.auth_epoch=r.auth_epoch AND s.revoked_at IS NULL AND s.idle_expires_at>clock_timestamp() "
    "AND s.absolute_expires_at>clock_timestamp() "
    "AND (r.source_google_identity_id IS NULL OR EXISTS(SELECT 1 FROM app.external_identities g "
    "WHERE g.user_id=u.id AND g.id=r.source_google_identity_id AND g.is_active AND g.revision=r.source_google_identity_revision)) "
    "AND ((c.purpose='password_add' AND r.operation='password_add' AND c.target_email_key=r.source_email_key "
    "AND NOT EXISTS(SELECT 1 FROM app.password_credentials p WHERE p.user_id=u.id)) "
    "OR (r.operation='email_change' AND ((c.purpose='email_change_new' AND c.target_email_key=r.target_email_key) "
    "OR (c.purpose='email_change_old' AND c.target_email_key=r.source_email_key)))))"
)

ELIGIBLE_MAIL_SQL = (
    "(m.purpose IN ('password_changed','password_added','email_changed','google_linked','google_unlinked') OR "
    "EXISTS (SELECT 1 FROM app.auth_challenges c WHERE c.id=m.challenge_id "
    "AND c.consumed_at IS NULL AND c.expires_at>clock_timestamp() AND c.expires_at=m.expires_at "
    "AND sha256(convert_to(c.target_email_key,'UTF8'))=m.recipient_digest AND ("
    "(m.purpose='verify_email' AND c.purpose='verify_email' AND c.user_id IS NULL) OR "
    "(m.purpose='reset_password' AND c.purpose='password_reset' AND EXISTS(SELECT 1 FROM app.users u "
    "JOIN app.user_emails e ON e.user_id=u.id JOIN app.password_credentials p ON p.user_id=u.id "
    "WHERE u.id=c.user_id AND u.status='active' AND u.auth_epoch=c.password_auth_epoch "
    "AND e.email_key=c.target_email_key AND e.is_primary AND e.verified_at IS NOT NULL)) OR "
    "(m.purpose=c.purpose AND m.purpose IN ('email_change_new','email_change_old','password_add') AND "
    + ACCOUNT_MAIL_SQL
    + "))))"
)
