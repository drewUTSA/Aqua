"""Offline source-preservation guards; actual PostgreSQL execution is separate."""

import ast
import hashlib
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "db"
ORIGINAL_INDEX = (
    "CREATE INDEX IF NOT EXISTS example_query_embedding_idx\n"
    "    ON retrieval.example_query USING diskann (embedding vector_cosine_ops);\n"
)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def read(name):
    return (DB / name).read_text(encoding="utf-8")


class PortableAnalyticsSource(unittest.TestCase):
    def test_original_tiger_extensions_and_reader_grants_are_unchanged(self):
        for name, expected in (
            (
                "01_extensions.sql",
                "68c98b1aa049277bcf17bfdc99901fee5ca0e43dba25c28ce41b8d811a7c936b",
            ),
            (
                "03_users.sql",
                "7f65eca66c5d39e8a304220a0a3a934d680bf026f55be6495967b41876dd616d",
            ),
        ):
            source = read(name)
            if name == "03_users.sql":
                # Pin the complete reviewed script as well as the original
                # password handling and grants after removing only the additions.
                self.assertEqual(
                    digest(source),
                    "69a923852b8ccdf0e109cf9202379f7dcebda43e421e5467fc6256117af763a5",
                )
                source, count = re.subn(
                    r"(?ms)^-- Check before changing an existing reader's password or table grants\.\n"
                    r"DO \$limits\$\n.*?^\$limits\$;\n",
                    "",
                    source,
                )
                self.assertEqual(count, 1)
                limits = (
                    "ALTER ROLE nl2sql_reader SET work_mem = '4MB';\n"
                    "ALTER ROLE nl2sql_reader SET temp_file_limit = '64MB';\n"
                )
                self.assertTrue(source.endswith(limits))
                source = source.removesuffix(limits)
            self.assertEqual(digest(source), expected, name)

    def test_shared_retrieval_ddl_and_grants_preserve_the_legacy_body(self):
        source = read("04_retrieval.sql")
        source, count = re.subn(
            r"-- BEGIN reviewed index profile\..*?"
            r"-- END reviewed index profile\.\n\n",
            "",
            source,
            flags=re.S,
        )
        self.assertEqual(count, 1)
        source, count = re.subn(
            r"-- BEGIN reviewed optional index\.\n.*?"
            r"-- END reviewed optional index\.\n",
            ORIGINAL_INDEX,
            source,
            flags=re.S,
        )
        self.assertEqual(count, 1)
        self.assertEqual(
            digest(source),
            "8384c2de183735662e6ba7d31d5e904b1a13d3c47a777cbbe8489e5077f0c326",
        )

    def test_shared_hidden_grants_preserve_standalone_transaction_and_body(self):
        fragment = read("hidden_staff_grants.sql")
        self.assertNotRegex(fragment, r"(?im)^\s*(BEGIN|COMMIT|ROLLBACK)\s*;")
        body = fragment[fragment.index("REVOKE SELECT") :].rstrip()
        expanded = read("05_hide_columns.sql").replace(
            "\\ir hidden_staff_grants.sql", body
        )
        self.assertEqual(
            digest(expanded),
            "e0f3f2d9145da45ca0800cc81924df174062f9652926372d50036c3921a29d74",
        )

    def test_only_closed_index_profiles_and_legacy_default_exist(self):
        source = read("04_retrieval.sql")
        self.assertIn("\\set aqua_retrieval_index diskann", source)
        self.assertIn(":'aqua_retrieval_index' IN ('diskann', 'exact')", source)
        self.assertIn("retrieval_index_configuration_invalid", source)
        self.assertLess(
            source.index("retrieval_index_configuration_invalid"),
            source.index("CREATE SCHEMA"),
        )
        self.assertEqual(source.count(ORIGINAL_INDEX), 1)
        self.assertIn("\\if :retrieval_diskann\n" + ORIGINAL_INDEX, source)
        self.assertNotIn("USING hnsw", source)
        self.assertIn("retrieval_exact_index_state_invalid", source)

    def test_portable_entrypoint_is_atomic_and_contains_only_fixed_includes(self):
        source = read("portable/bootstrap_pagila.psql")
        self.assertEqual(
            re.findall(r"(?m)^\\ir (.+)$", source),
            [
                "preflight.sql",
                "../03_users.sql",
                "../04_retrieval.sql",
                "../hidden_staff_grants.sql",
                "verify.sql",
            ],
        )
        self.assertEqual(
            re.findall(r"(?m)^(BEGIN|COMMIT);$", source), ["BEGIN", "COMMIT"]
        )
        self.assertLess(source.index("BEGIN;"), source.index("\\ir preflight.sql"))
        self.assertLess(
            source.index("\\ir preflight.sql"), source.index("CREATE EXTENSION")
        )
        self.assertLess(source.index("\\ir verify.sql"), source.index("COMMIT;"))
        self.assertIn("\\set ON_ERROR_STOP on", source)
        self.assertIn("\\set aqua_retrieval_index exact", source)
        for name in ("03_users.sql", "04_retrieval.sql", "hidden_staff_grants.sql"):
            self.assertNotRegex(read(name), r"(?im)^\s*(BEGIN|COMMIT|ROLLBACK)\s*;")

    def test_no_portable_script_has_shell_network_or_destructive_commands(self):
        for path in sorted((DB / "portable").glob("*")):
            source = path.read_text()
            self.assertNotRegex(source, r"(?im)^\s*(DROP|TRUNCATE|DELETE|UPDATE)\b")
            self.assertNotRegex(source, r"(?im)^\s*ALTER\s+(SYSTEM|DATABASE)\b")
            self.assertNotRegex(source, r"(?im)^\\(?:!|copy|connect|include)\b")
            self.assertNotIn("CASCADE;", source)
            self.assertNotIn("CREATE DATABASE", source)

    def test_pagila_manifest_matches_production_metadata_policy(self):
        module = ast.parse((ROOT / "backend/nl2sql/metadata_policy.py").read_text())
        expected = next(
            ast.literal_eval(node.value.args[0])
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "PAGILA_TABLES"
                for target in node.targets
            )
        )
        source = read("portable/preflight.sql")
        match = re.search(
            r"IF tables IS DISTINCT FROM ARRAY\[(.*?)\]::text\[\]", source, re.S
        )
        self.assertIsNotNone(match)
        self.assertEqual(set(re.findall(r"'([a-z_]+)'", match[1])), expected)
        self.assertIn("c.relkind = 'f'", source)
        self.assertIn("portable_pagila_partition_scope_invalid", source)
        self.assertIn("portable_pagila_view_scope_invalid", source)
        commit = re.search(
            r'PAGILA_COMMIT="([a-f0-9]{40})"', read("02_load_pagila.sh")
        )[1]
        self.assertIn("pagila_v3_1_0_" + commit, source)

    def test_request_extension_and_privilege_denials_are_explicit(self):
        preflight = read("portable/preflight.sql")
        self.assertIn("current_database() = :'aqua_expected_database'", preflight)
        self.assertIn("'aqua_analytics_pagila'", preflight)
        self.assertIn(":'aqua_portable_index' = 'exact'", preflight)
        self.assertIn("= 18", preflight)
        self.assertIn("n.nspname <> 'public'", preflight)
        self.assertIn("e.extversion <> :'aqua_vector_version'", preflight)
        self.assertIn("portable_fresh_destination_required", preflight)
        self.assertIn("portable_pagila_counts_invalid", preflight)
        verify = read("portable/verify.sql")
        self.assertIn("a.atttypmod = 768", verify)
        self.assertIn("portable_role_separation_invalid", verify)
        self.assertIn("'password','SELECT'", verify)
        self.assertIn("'picture','SELECT'", verify)

    def test_builtin_resolution_and_reader_column_write_denial_are_preserved(self):
        bootstrap = read("portable/bootstrap_pagila.psql")
        self.assertIn("SET LOCAL search_path = pg_catalog, public;", bootstrap)
        self.assertNotIn("SET LOCAL search_path = public, pg_catalog;", bootstrap)
        verify = read("portable/verify.sql")
        # PUBLIC column grants can authorize a write without a table-level
        # grant. Both public business tables and retrieval need this denial.
        checks = verify.split("IF EXISTS (", 1)[1]
        public_check, retrieval_check = checks.split(") OR EXISTS (", 1)
        for fragment in (public_check, retrieval_check):
            self.assertIn(
                "has_any_column_privilege('nl2sql_reader',c.oid,'INSERT,UPDATE')",
                fragment,
            )
            self.assertIn(
                "has_table_privilege('nl2sql_reader',c.oid,'INSERT,UPDATE,DELETE,TRUNCATE')",
                fragment,
            )

    def test_portable_roles_are_reserved_before_legacy_password_prompts(self):
        source = read("portable/bootstrap_pagila.psql")
        self.assertEqual(
            re.findall(r"(?m)^CREATE ROLE (.+);$", source),
            ["nl2sql_reader NOLOGIN", "nl2sql_indexer NOLOGIN"],
        )
        positions = [
            source.index(statement)
            for statement in (
                "\\ir preflight.sql",
                "CREATE ROLE nl2sql_reader NOLOGIN;",
                "CREATE ROLE nl2sql_indexer NOLOGIN;",
                "\\ir ../03_users.sql",
                "\\ir ../04_retrieval.sql",
                "\\ir verify.sql",
                "COMMIT;",
            )
        ]
        self.assertEqual(positions, sorted(positions))

    def test_partition_manifest_filters_out_partition_indexes(self):
        source = read("portable/preflight.sql")
        query = re.search(
            r"SELECT array_agg\(c\.relname::text ORDER BY c\.relname\) "
            r"INTO partitions\s+(.*?);",
            source,
            re.S,
        )
        self.assertIsNotNone(query)
        # pg_class.relispartition is true for table AND index partitions.
        # Isolate this query: the table-manifest query's existing relkind
        # predicate must not accidentally satisfy this regression guard.
        self.assertRegex(
            query[1],
            r"WHERE n\.nspname = 'public' AND c\.relkind IN \('r','p'\)"
            r"\s+AND c\.relispartition\Z",
        )
        expected = re.search(
            r"IF partitions IS DISTINCT FROM ARRAY\[(.*?)\]::text\[\]",
            source,
            re.S,
        )
        self.assertIsNotNone(expected)
        self.assertEqual(
            re.findall(r"'([a-z0-9_]+)'", expected[1]),
            [f"payment_p2022_{month:02d}" for month in range(1, 8)],
        )


if __name__ == "__main__":
    unittest.main()
