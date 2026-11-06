"""Actual keyless SQL verifier inside the sole network-none owned probe."""

import hashlib
import json
from pathlib import Path
import re
import signal
import sys

from verifier_process import Failure, PROBE_CODES


def connection(role):
    import psycopg

    from verifier_setup import PASSWORD

    return psycopg.connect(
        host="/run/aqua-app-db",
        dbname="aqua_retirement",
        user="aqua_retirement_" + role,
        password=PASSWORD,
        connect_timeout=2,
        autocommit=True,
        prepare_threshold=None,
    )


def denied_second_slot(error):
    """Startup libpq errors lack PGresult SQLSTATE; match only fixed RAM text."""
    import psycopg

    if error.sqlstate == "53300":
        return "sqlstate_53300"
    if type(error) is psycopg.OperationalError and error.sqlstate is None:
        text = str(error)
        if len(text.encode("utf-8")) <= 1024 and re.fullmatch(
            r"(?:connection (?:failed|is bad): connection to server on socket "
            r'"/run/aqua-app-db/\.s\.PGSQL\.5432" failed: )?'
            r'FATAL: {1,2}too many connections for role "aqua_retirement_backup"\n?',
            text,
        ):
            return "libpq_startup_exact_role_limit"
    raise Failure("verifier_backup_second_slot_not_proven")


def main():
    signal.alarm(int(sys.argv[1]))
    subphase = "imports"

    def diagnostic(value):
        nonlocal subphase
        subphase = value

    try:
        import psycopg

        from verifier_validation import validate

        request = json.loads(Path("/checks/public.json").read_bytes())
        chain = Path("/checks/chain.bin").read_bytes()
        subphase = "connections"
        with connection("backup") as backup, connection("recovery") as recovery:
            # An actual second connection must be denied while backup's only slot lives.
            subphase = "backup_slot"
            if backup.execute(
                "SELECT current_user,session_user,rolconnlimit FROM pg_roles WHERE rolname=current_user"
            ).fetchone() != (
                "aqua_retirement_backup",
                "aqua_retirement_backup",
                1,
            ):
                raise Failure("verifier_backup_second_slot_not_proven")
            try:
                extra = connection("backup")
            except psycopg.Error as error:
                mechanism = denied_second_slot(error)
            else:
                extra.close()
                raise Failure("verifier_backup_second_slot_admitted")
            result = validate(
                backup, recovery, chain, request["expected"], diagnostic=diagnostic
            )
        # Same fixed DSN/credential after physical close: reject unrelated outage,
        # authentication or endpoint failure masquerading as role-slot denial.
        subphase = "backup_slot"
        with connection("backup") as control:
            if control.execute("SELECT current_user,session_user,1").fetchone() != (
                "aqua_retirement_backup",
                "aqua_retirement_backup",
                1,
            ):
                raise Failure("verifier_backup_second_slot_not_proven")
        print(
            json.dumps(
                {
                    "status": "passed",
                    **result,
                    "backup_role_denial_mechanism": mechanism,
                    "backup_role_first_authenticated": True,
                    "backup_role_post_release_control": True,
                    "head_sha256": hashlib.sha256(
                        bytes.fromhex(request["expected"]["head_hex"])
                    ).hexdigest(),
                    "dump_sha256": request["dump_sha256"],
                },
                sort_keys=True,
            )
        )
    except Exception as error:
        code = (
            error.args[0] if type(error) is Failure and len(error.args) == 1 else None
        )
        print(
            json.dumps(
                {
                    "status": "failed",
                    "probe_subphase": subphase,
                    "probe_failure_code": (
                        code
                        if type(code) is str and code in PROBE_CODES
                        else "unclassified_failure"
                    ),
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
