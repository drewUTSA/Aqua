"""Fresh nonce-bound identity assertions; never create a login or merge account."""

from datetime import datetime, timezone

from google.auth.exceptions import GoogleAuthError, TransportError

from auth.config import AuthDenied
from auth.google import verify_google_token
from auth.security import identity_from_claims, tokens_match
from workspace.errors import WorkspaceError


def fresh_identity(credential, settings, nonce, created_at):
    if not settings.google_client_id:
        raise WorkspaceError("method_unavailable", 403)
    try:
        claims = verify_google_token(credential, settings.google_client_id)
        instant = datetime.now(timezone.utc).timestamp()
        issued = claims.get("iat")
        if (
            type(issued) is not int
            or issued < created_at.timestamp() - 30
            or issued < instant - 300
            or issued > instant + 30
            or claims.get("aud") != settings.google_client_id
            or not isinstance(claims.get("nonce"), str)
            or not tokens_match(claims["nonce"], nonce)
        ):
            raise ValueError("fresh_identity_invalid")
        return identity_from_claims(claims)
    except TransportError:
        raise WorkspaceError("security_unavailable", 503) from None
    except (ValueError, TypeError, KeyError, GoogleAuthError, AuthDenied):
        raise WorkspaceError("proof_invalid", 403) from None
