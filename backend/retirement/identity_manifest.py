"""Build bounded keyed identity metadata before any account payload is purged."""

import re

from retirement.fingerprints import ISSUER
from retirement.interlock import RetirementUnavailable
from retirement.pages import encode, manifest

# This reserved namespace suppresses automatic reapproval even after the
# configured analytical dataset changes. An operator can still grant explicitly.
GLOBAL_DATASET = "0" * 64
DATASET = re.compile(r"[a-f0-9]{64}\Z")
MAX_IDENTITIES = 1000


def capture(conn, owner, key, configured_dataset):
    """The caller holds the canonical user lock, fencing identity mutations.

    Both historical primary mailboxes and inactive Google identities are kept by
    the existing identity schema; no row content, email or subject enters the
    independent manifest. Grant evidence covers former approved observations.
    """
    emails = conn.execute(
        "SELECT email_key FROM app.user_emails WHERE user_id=%s ORDER BY id LIMIT %s",
        (owner, MAX_IDENTITIES + 1),
    ).fetchall()
    identities = conn.execute(
        "SELECT issuer,subject,observed_email_key FROM app.external_identities WHERE user_id=%s ORDER BY id LIMIT %s",
        (owner, MAX_IDENTITIES + 1),
    ).fetchall()
    grants = conn.execute(
        "SELECT dataset_key,approval_kind,approval_evidence FROM app.dataset_grants WHERE user_id=%s ORDER BY dataset_key LIMIT %s",
        (owner, MAX_IDENTITIES + 1),
    ).fetchall()
    if any(len(rows) > MAX_IDENTITIES for rows in (emails, identities, grants)):
        raise RetirementUnavailable()
    datasets = {GLOBAL_DATASET}
    if configured_dataset:
        if not DATASET.fullmatch(configured_dataset):
            raise RetirementUnavailable()
        datasets.add(configured_dataset)
    fingerprints = {key.mailbox(value[0]) for value in emails}
    for issuer, subject, observed in identities:
        fingerprints.add(key.google(issuer, subject))
        if observed:
            fingerprints.add(key.mailbox(observed))
    for dataset, kind, evidence in grants:
        if not DATASET.fullmatch(dataset):
            raise RetirementUnavailable()
        datasets.add(dataset)
        if kind == "google_email":
            fingerprints.add(key.mailbox(evidence))
        elif kind == "google_subject":
            fingerprints.add(key.google(ISSUER, evidence))
    if not fingerprints or len(datasets) * len(fingerprints) > 100000:
        raise RetirementUnavailable()
    return manifest(
        encode(dataset, fingerprint)
        for dataset in sorted(datasets)
        for fingerprint in sorted(
            fingerprints, key=lambda value: (value.kind, value.digest)
        )
    )
