# Optional inherited budget and exporter route

These Python APIs prepare authority capture and recovery. The default CLI still
does no work, legacy callers retain their previous timeouts and command shapes,
and capture/recovery receipt fields are unchanged. Nothing enables a production
release, supplies missing retention/readback contracts or establishes off-host,
globally latest or total-host recovery coverage.

Pass one exact `authority_budget.Deadline` instance as the optional `deadline=`
keyword to both `authority_bridge.collect` and `verify_recovered`. Construct it
before requesting installation, using the original install start and owner,
client and run ends from the same caller monotonic clock. Its immutable end is
their minimum and the original install start plus180seconds. These arguments
are trusted operator declarations, not authenticated evidence. Server UTC or
server monotonic values cannot be compared directly with the client clock.
The installer's later alarm/hold resets do not extend this separate budget.

The client checks the deadline before key/transport work, clips each metadata,
encryption and decryption call, and checks results after work. Archive validation
spends the same budget: `authority_verify.verify_ram` recomputes the SQL cap
immediately before calling the original callback. The exact
`type(restore_verify) is NativeSQLAdapter` gate is retained; do not wrap or
subclass that adapter to inject timing. Original caps remain20seconds for head
metadata and120seconds for other operations. Existing cleanup is reserved
inside the inherited end:4seconds for metadata/decryption,8seconds for the
two-process encryption pipeline and3seconds for the SQL controller's local
process wait. SQL admission still requires more than45seconds; its remote
30-second cleanup is already included in the supplied duration. Insufficient
time, clock rollback/nonfinite readings or late success deny rather than reset.

Checks are cooperative. They cannot preempt archive CPU work, blocking local
filesystem calls or a child that ignores its transport. The enclosing operator
must enforce its inherited hard end and preserve an honest stopped/unknown
cleanup outcome. If a late post-publication check fails, the already published
ciphertext is retained and no successful receipt is returned. No arbitrary
backup deletion or ownership repair is added.

For explicit sibling import integrity, construct
`authority_contract.ExporterRoute(helper_sha256, manifest_sha256)` and pass it
to `Transport(route=...)`. Both hashes must be independently reviewed public
pins. In a fresh correctly owned release stage, separately stage this exact
`authority_route.py` as `authority-route.py`, a canonical
`authority-route-manifest.json`, and all21 closed `ops/retirement/*.py` files.
Do not repin an old qualified receipt or silently stage changed source. A
manifest is not approval, and a route object is not authentication.
The enclosing reviewed operator must verify its entire local client/helper
closure before importing it; these opt-in classes do not authenticate their own
local imports or replace independent source review.

The fixed isolated Python bootstrap verifies the helper before compiling it.
The helper checks every file hash before any exporter module executes, then
serves eager and lazy sibling imports only from immutable verified RAM bytes.
There is no sibling disk fallback. Existing independent exporter/profile pins,
SSH host/key pins, ownership/link/mode checks and exporter resource guards
remain in force. Bounds are131,072bytes/file,8KiB manifest and2MiB source. All
staged files are owner1000/mode0600/one-link regular files in owned0700 parents;
canonical paths and descriptor/name/parent identity are rechecked while read.
This is source integrity for reviewed Python, not a sandbox for malicious code.

The new CI tests use fake clocks, synthetic archives/modules and modeled
transports/filesystem metadata. A patched exact native-adapter callback tests
type/admission only; it does not run SQL. The original closed56 backup model
inventory, vendor manifest, SQL-verifier manifest and qualified historical
evidence are unchanged. New source and a new helper hash require fresh
source-bound Linux/bootstrap, actual exporter, encrypted recovery and exact
native SQL qualification before operator use. Missing retention16/readback9,
durable independent storage and full guarded schema9 release remain separate
gates; these tests do not supply them.
