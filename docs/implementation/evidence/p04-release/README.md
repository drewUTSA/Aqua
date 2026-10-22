# P04 merged-package release evidence

This checkpoint covers main `067fb5a0aacc90ce646138fedbb770ecea6f0c92`: source synchronization, image build, isolated release checks and the completed schema 3 cutover with password/mail features disabled.

- `p04-release-sync.json`: source and existing P03 health/schema/disabled-feature observations.
- `p04-release-build.json`: exact new candidate images; its historical `built_not_deployed` status precedes the cutover receipt.
- `p04-release-check.json`: packaged file hashes, corpus/dependency checks, synthetic hash-cost measurement and complete check summaries.
- `p04-release-backup.json`: operator-supplied reviewed-helper receipt for encrypted off-server snapshot `78be69244e2127185de80acd0c9872453efe9d37b7be80b05dfcc6f3b3791d19`, tagged `pre-p04-067fb5a`; schema 2 before/after export and repository data integrity passed. No production restore was performed.
- `p04-release-cutover.json`: explicit schema 3 migration, repeat migration, healthy checked images and disabled runtime capabilities.
- `p04-release-verify.json`: private schema, checksum, privilege, recovery and network-boundary verification.
- `p04-release-public.json`: all 12 bounded public checks passed; no provider or data-query traffic.
- `checks/`: synthetic backend JUnit results, pytest summaries, package versions and proxy exercise result.
- `artifact-hashes.json`: SHA-256 and byte length of every evidence file above, plus this README. The manifest excludes itself.

These are sanitized check reports, public source/image identifiers and synthetic test metadata. No runtime secret files, credentials, helper secret output, backup repository, real database dump or live application log is included. Dump digests and lengths in isolated checks identify synthetic dumps held in memory; the dumps themselves are absent. Test case names can contain deliberately synthetic recipients, fixture-only DSNs and malformed-input examples. The fixture DSNs in JUnit case names belong to the redaction and forbidden-configuration tests, not runtime credentials.

All disposable test resources reported removal with absence confirmed. The release check is a blue retest; development red cases remain in the adjacent `../p04/` evidence tree. These checks establish the scoped behavior exercised, not an assurance that no attack is possible. See [release status](../../P04_RELEASE.md) for the live deployment boundary and remaining gate.
