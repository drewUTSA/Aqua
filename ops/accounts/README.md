# Invite one employee by email

An authorized deployment operator may request a password invitation for one approved mailbox on an invitation-only Aqua site. The employee receives a verification link through the existing mail worker, opens the link, chooses a password and signs in. A newly verified password account starts with zero dataset grants.

Run the approved revision of `invite.py` inside the **currently serving backend container**, as its normal unprivileged user, from `/app`. This Linux operator example reads the single mailbox from an owner-only input file. Set `AQUA_BACKEND_ID` to the verified current container ID and `AQUA_INVITE_INPUT` to that file. The Python source in the command argument is public code. The mailbox travels over standard input.

```sh
docker exec -i --workdir=/app "$AQUA_BACKEND_ID" python -B -c "$(cat ops/accounts/invite.py)" < "$AQUA_INVITE_INPUT"
```

The command accepts one ASCII address up to 254 bytes, with an optional LF or CRLF line ending. It prints **Invitation request accepted.** when the request was processed. Existing accounts, repeats and recipient limits may suppress delivery. **Invitation unavailable.** indicates an invalid input, a disabled or inconsistent configuration, a stopped web service, a busy physical gate, recovery work, or another operational failure. Diagnose the deployment’s standard readiness and mail controls before retrying.

Issuance uses the runtime’s configured password lifetimes, encrypted outbox and existing delivery limits. It checks the real web process’s readiness and the database recovery controls. When an authority is installed, it also checks the protected signed checkpoint against the application’s acknowledged retirement history while holding the existing physical lock. This one-shot operator uses at most two short application-database leases. Mail delivery, later account creation and any analytical access grant are separate operations.
