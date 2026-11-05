# P11a export activation boundary

Status: implementation under review. No production activation or topology proof
has been performed for P11a. The historical isolated draft is prior evidence,
not a canonical check of the materialized Phase 11 source.

Private exports default off. `PRIVATE_DATA_EXPORT_ENABLED=true` is an explicit
operator gate only after the release's read-only topology preflight proves one
supported Compose backend container with its reviewed immutable image, exact
Docker command, Docker init and one direct Uvicorn process. An environment count
does not discover other host containers or prove deployment topology.

Runtime activation also rejects multiple-worker/manager/reload arguments,
noncanonical worker counts, a multiprocessing child and any web pool size other
than four. The fixed planned runtime budget is web4 + privacy worker1 + private
download2 + existing mail worker1 = 8 connections; two probe connections remain
reserved under the existing runtime role limit12. Neither the role limit nor the
storage pool is changed automatically. The preflight and existing storage/role
checks must validate the actual release deployment before this gate is enabled.

`tools/checks/privacy_topology.py` is read only. Its metadata receipt does not
authorize activation by itself and never sets a flag, starts a service, reads a
private environment file or emits DSNs/credentials. An uncertain/changed
topology, process manager, duplicate web worker or unknown image fails closed.
The supported deployment remains one backend container and one web process;
multi-process scaling needs a new reviewed physical-admission protocol.

Within that supported process, the downloader must retain local global2 and
owner1 physical admission until the actual ASGI task/send has stopped, including
after PostgreSQL backend termination or cancellation. Session advisory locks
alone disappear with their DB session and cannot provide this guarantee.
Independent pool/owner/backend-termination regressions are required. Database
session locks remain an additional check; they do not establish a distributed
physical-stream guarantee after connection loss.

The existing `preferences.capabilities.private_data_export` stays false unless
the explicit gate, supported runtime configuration and schema8 prerequisites
pass. The 13-field account/method capability schema is unchanged. Unit and
disposable database fixtures may explicitly model their known single process
and enable synthetic configuration; those checks are not a production topology
attestation.

The future gated release may change only this new boolean export flag in
addition to the reviewed additive 0008 migration. All other private environment
bytes, flags, credentials, grants, mail key/cron/worker controls and DB volumes
must retain the existing preservation checks. Do not enable public signup or
alter Google configuration as part of export activation.

A schema8 forward fallback must keep export activation false and fence/expire
cached output before reopening. An expired output remains terminal and its
one-hour expiry is never extended by retry, download or later reactivation.
Neither a schema7 image nor an untested C149 + 0008/readiness overlay is a proven
schema8 fallback: workspace deletion epoch bumps and export-session FK cleanup
also belong to its compatibility proof. No DB rewind is authorized.
