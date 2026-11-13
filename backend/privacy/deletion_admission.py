"""Short purpose-bound receipt reads retain a shared durable finite budget."""

from datetime import timedelta

from workspace.errors import WorkspaceError


def admit(storage, digest):
    with storage.transaction() as conn:
        conn.execute(
            "SELECT singleton FROM app.retirement_control WHERE singleton FOR UPDATE"
        )
        now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        conn.execute(
            "DELETE FROM app.deletion_admission WHERE (scope,key_digest) IN (SELECT scope,key_digest FROM app.deletion_admission WHERE expires_at<=%s ORDER BY expires_at,scope,key_digest LIMIT 64)",
            (now,),
        )
        count = conn.execute("SELECT count(*) FROM app.deletion_admission").fetchone()[
            0
        ]
        selected = []
        for scope, key, maximum in (
            ("metadata:global", bytes(32), 120),
            ("metadata:receipt", digest, 20),
        ):
            row = conn.execute(
                "SELECT hits,expires_at FROM app.deletion_admission WHERE scope=%s AND key_digest=%s",
                (scope, key),
            ).fetchone()
            count += row is None
            if count > 2048 or row and row[1] > now and row[0] >= maximum:
                raise WorkspaceError("rate_limited", 429)
            selected.append(
                (
                    scope,
                    key,
                    1 if row is None or row[1] <= now else row[0] + 1,
                    (
                        now + timedelta(minutes=1)
                        if row is None or row[1] <= now
                        else row[1]
                    ),
                )
            )
        for scope, key, hits, expires in selected:
            conn.execute(
                "INSERT INTO app.deletion_admission(scope,key_digest,hits,expires_at) VALUES(%s,%s,%s,%s) ON CONFLICT(scope,key_digest) DO UPDATE SET hits=EXCLUDED.hits,expires_at=EXCLUDED.expires_at",
                (scope, key, hits, expires),
            )
