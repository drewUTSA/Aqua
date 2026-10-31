# Phase10 Identity

Add explicit Google identity linking/removal, first-password setup, and primary
email changes with fresh action-specific verification. Changes revoke sessions,
preserve account and data-grant separation, and issue mandatory security notices.
Optional generic success messages use a separate saved consent. Keep the
simplified homepage and both visual themes.

Validation: all 21 isolated gates, 1,635 backend cases retaining every previous
case, 528 frontend units, both builds, all 42 browser gates, and root review of
104 selected screenshots passed. The schema-7-compatible recovery image passes
1,530 backend cases and 24 browser gates; the migration rehearsal preserves all
29 existing tables. Synthetic accounts/providers only. Prior failures remain
recorded in the portable evidence.

Release requires all five jobs on both PR and merged main, exact image/proxy
proofs, and a fresh authenticated encrypted backup after writers stop. Migration
0007 is additive. Recovery after migration uses the verified schema-7-compatible
image or maintenance; never an older-schema image or a database rewind.
