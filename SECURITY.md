# Security

Read the README's boundary before using sensitive CSVs. RowVerdict is not a sandbox,
an anonymizer, an accounting validator or a global agent firewall.

## Trust and storage

- Only explicitly operator-allowlisted CSV roots; no tool broadens them.
- No network, telemetry, secret reads, subprocesses, arbitrary code or runtime updater.
- Only RowVerdict's private plugin-data is written; original CSVs remain untouched.
- Source and explicit contract hashes bind a plan. Changes invalidate an unexported plan.
- The native export hook asks the host approval gate. No dashboard export route exists.
- Raw rejected cells persist only in the private `quarantine.json` export. State and
  outputs are not encrypted. Plans expose paths, headers, contracts and aggregate
  metadata to the configured Hermes model.
- Formula-like text quarantines, not executes. Use type-aware importers and text
  columns for identifiers. Formula defense is conservative, not universal.
- POSIX local filesystems and the OS account are trusted. Symlink checks do not
  promise resistance to a hostile concurrent same-user process.

## Reporting

Do not publish real rows, tokens or private paths in a public issue. Once the public
repository exists, use GitHub private vulnerability reporting if enabled. Otherwise
contact the repository owner privately through a channel you already trust. Include
a synthetic reproducer, platform, version and the expected/actual behavior.

No disclosure destination/account is invented by this document.
