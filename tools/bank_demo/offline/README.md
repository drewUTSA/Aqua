# Aqua fictional bank MCP demo

This private, offline demo lets an employee review a month-end reconciliation, inspect historical trends, calculate financial illustrations and draft an action for human review. It uses Aqua’s bundled fictional U.S. bank ledger. The analyst role can read authorized aggregates and prepare proposals. No account, transaction or approval can be changed.

## Windows

Before extraction, compare the ZIP’s SHA-256 with the digest from the person who supplied the demo. Use `Get-FileHash -Algorithm SHA256` on Windows or `sha256sum` on Linux. The archive’s internal manifest checks the extracted files on setup.

Extract the ZIP to a new local folder. Open PowerShell there. Use a 64-bit CPython 3.12 installation.

```powershell
py -3.12 -B -I setup_demo.py
.\.aqua-demo-venv\Scripts\python.exe -B -Es walkthrough.py
```

## Linux

Extract the ZIP to a new local folder. Use 64-bit CPython 3.12 on x86_64 Linux with glibc 2.17 or later and the standard venv and ensurepip support.

```sh
python3.12 -B -I setup_demo.py
./.aqua-demo-venv/bin/python -B -Es walkthrough.py
```

Setup verifies the included source and wheel hashes, installs into a dedicated local environment with package indexes disabled, and prints the MCP host entry. It records a fingerprint of the installed files, including Python bytecode, in `.aqua-demo-install.json`. Run setup again with the same system Python command to verify the environment before reuse. If verification fails or the first installation was interrupted, extract a new copy to a fresh folder. The setup and walkthrough need no bank account, internet connection, database service, API key or model download.

## What the walkthrough shows

The official MCP client starts the server locally over standard input and output. It asks for the analyst’s context, obtains a reconciliation report, examines complete months in the historical operating-surplus series and uses the report revision to prepare a draft. Check the Central branch difference, number of months, excluded partial period and human-review status in the output. The historical evaluation is descriptive. The website's separate synthetic CZK ledger uses a different dataset from this fictional USD bank snapshot.

To use a local MCP host that accepts `mcpServers` entries, copy the entry printed by setup into its configuration. The command uses absolute paths and works from the host’s usual working directory. Keep the extraction in place. The host chooses the synthetic persona. A launcher without an explicit persona starts with no grants. Use this package with fictional data only.

### Calculate a financial illustration

For a financial illustration, call `calculate_finance` with the operation and its named parameters. Declare `"currency": "USD"` once, either beside `operation` or inside `parameters`. For instance, `{"operation":"simple_interest","currency":"USD","parameters":{"principal_usd":"1000","annual_rate_percent":"6","term_months":"12"}}` returns USD 60.00 in simple interest.

When the calculator declines an input, read its message before trying again. An authorized employee receives guidance about the USD declaration, allowed period, numeric format, published operand names or a loan that cannot amortize after cent rounding. Confirm corrections against the employee's stated inputs. A different currency needs an appropriate calculator. A loan that still cannot amortize has no illustration under these terms. The protocol keeps its existing error flag, denied status and generic reason.

### Try another employee role

Run the same walkthrough command with `--role teller` to check the fictional service queue and its cited complaint procedure. Use `--role manager` to read the held-wire amount and the separate service-incident count. Each invocation starts a fresh local server with that role’s grants. The default `analyst` walkthrough covers reconciliation, historical trends and a proposed action for human review.
