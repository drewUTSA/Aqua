"""Offline private-export seam contracts; every API/DB/process is explicitly fake."""

from contextlib import nullcontext
import inspect
import io
import json
import base64
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import p05_browser_host as host
import p05_browser_worker as worker
import p11a_browser_fixture as fixture
import run_proxy
import run_backend
import privacy_capacity_fixture as capacity
from p10b_browser_fixture import ORIGIN

ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
IMAGE = "sha256:" + "b" * 64


class ExportFixtureTests(unittest.TestCase):
    def test_one_fixed_project_setup_forwards_exact_browser_authority_once(self):
        value, _, service, analysis = self.make()
        item = {
            "id": 1,
            "kind": "request",
            "path": "/api/v1/projects",
            "method": "POST",
            "headers": [
                ["Cookie", "original-browser-cookie"],
                ["X-CSRF-Token", "captured-csrf"],
                ["Origin", ORIGIN],
            ],
            "bodyBase64": base64.b64encode(
                json.dumps(
                    {"client_request_id": ID, "name": fixture.PROJECT_MARKER}
                ).encode()
            ).decode(),
        }
        with patch.object(value, "forward", return_value={"status": 201}) as forward:
            self.assertEqual(
                value.dispatch(item, Mock(), service, None, [], analysis),
                {"status": 201},
            )
            self.assertIs(forward.call_args.args[0], item)
            with self.assertRaises(ValueError):
                value.dispatch(item, Mock(), service, None, [], analysis)
            self.assertEqual(forward.call_count, 1)

    def test_project_setup_rejects_owner_fields_aliases_bad_marker_and_duplicates_before_IO(
        self,
    ):
        valid = {"client_request_id": ID, "name": fixture.PROJECT_MARKER}
        bodies = [
            {**valid, "user_id": ID},
            {**valid, "owner_id": ID},
            {**valid, "name": "other"},
            {**valid, "client_request_id": "invalid"},
            [valid],
        ]
        encoded = [
            base64.b64encode(json.dumps(body).encode()).decode() for body in bodies
        ]
        encoded += [
            base64.b64encode(
                (
                    json.dumps(valid)[:-1] + ',"name":"' + fixture.PROJECT_MARKER + '"}'
                ).encode()
            ).decode(),
            "!",
            base64.b64encode(b" " * 513).decode(),
        ]
        for body in encoded:
            value, _, service, analysis = self.make()
            with (
                self.subTest(body_length=len(body)),
                patch.object(value, "forward") as forward,
            ):
                with self.assertRaises(ValueError):
                    value.dispatch(
                        {
                            "id": 1,
                            "kind": "request",
                            "path": "/api/v1/projects",
                            "method": "POST",
                            "headers": [],
                            "bodyBase64": body,
                        },
                        Mock(),
                        service,
                        None,
                        [],
                        analysis,
                    )
                forward.assert_not_called()
        for path, method in (
            ("/api/v1/projects?owner=forged", "POST"),
            ("/api/v1/projects/", "POST"),
            ("/api/v1/projects", "PUT"),
        ):
            value, _, service, analysis = self.make()
            with (
                self.subTest(path=path, method=method),
                patch.object(value, "forward") as forward,
            ):
                with self.assertRaises(ValueError):
                    value.dispatch(
                        {
                            "id": 1,
                            "kind": "request",
                            "path": path,
                            "method": method,
                            "headers": [],
                            "bodyBase64": base64.b64encode(
                                json.dumps(valid).encode()
                            ).decode(),
                        },
                        Mock(),
                        service,
                        None,
                        [],
                        analysis,
                    )
                forward.assert_not_called()

    def test_export_proxy_has_no_unsafe_baseline_or_mixed_exercise(self):
        with patch.object(run_proxy, "docker") as docker:
            for baseline, identity in ((True, False), (False, True), (True, True)):
                with self.assertRaises(ValueError):
                    run_proxy.run(
                        Mock(),
                        Mock(),
                        baseline,
                        identity_actions=identity,
                        personal_exports=True,
                    )
            docker.assert_not_called()

    def make(self):
        conn = Mock()
        service = Mock()
        service.transaction.return_value = nullcontext(conn)
        analysis = SimpleNamespace(max_executions=12)
        value = fixture.PrivacyFixture(
            service, SimpleNamespace(app_origin=ORIGIN), analysis
        )
        return value, conn, service, analysis

    def test_routes_are_exact_and_cannot_grant_path_format_or_owner_authority(self):
        accepted = [
            (fixture.EXPORTS, "POST"),
            (fixture.EXPORTS, "GET"),
            (fixture.EXPORTS + "/" + ID, "GET"),
            (fixture.EXPORTS + "/by-intent/" + ID, "GET"),
            (fixture.EXPORTS + "/" + ID + "/download", "GET"),
        ]
        for path, method in accepted:
            self.assertTrue(fixture.export_route(path, method))
            for changed in (
                path + "/",
                path + "?owner_id=" + ID,
                path + "#token=private",
                "https://outside.invalid" + path,
                path.replace("/me/", "/%6de/"),
            ):
                self.assertFalse(fixture.export_route(changed, method))
        for path, method in [
            (fixture.EXPORTS + "/" + ID, "POST"),
            (fixture.EXPORTS + "/" + ID + "/download", "HEAD"),
            (fixture.EXPORTS + "/" + ID.upper(), "GET"),
            (fixture.EXPORTS + "/../private", "GET"),
            ("/api/query", "POST"),
        ]:
            self.assertFalse(fixture.export_route(path, method))

    def test_private_mode_is_keyword_only_default_closed_and_requires_schema8_identity(
        self,
    ):
        for function in (host.host, worker.worker):
            mode = inspect.signature(function).parameters["personal_export_fixture"]
            self.assertIs(mode.default, False)
            self.assertEqual(mode.kind, inspect.Parameter.KEYWORD_ONLY)
        with patch.object(host, "Resources") as resources:
            for change in (
                {"personal_export_fixture": 1},
                {"personal_export_fixture": True},
                {"personal_export_fixture": True, "account_security_fixture": True},
            ):
                with self.assertRaises(ValueError):
                    host.host(ORIGIN, IMAGE, True, **change)
            with (
                patch.object(host, "fixture_schema", return_value=7),
                self.assertRaises(ValueError),
            ):
                host.host(
                    ORIGIN,
                    IMAGE,
                    True,
                    account_security_fixture=True,
                    account_identity_fixture=True,
                    personal_export_fixture=True,
                )
            resources.assert_not_called()

    def host_case(self, marker=True):
        child = SimpleNamespace(
            stdin=Mock(),
            stdout=io.BytesIO(
                (
                    json.dumps(
                        {
                            "kind": "ready",
                            "schema_version": 8,
                            "account_security_fixture": True,
                            "account_identity_fixture": True,
                            "personal_export_fixture": marker,
                        }
                    )
                    + "\n"
                ).encode()
            ),
            wait=Mock(return_value=0),
            terminate=Mock(),
            kill=Mock(),
        )
        resources = Mock()
        resources.provision.return_value = "a" * 64
        resources.cleanup.return_value = []
        with (
            patch.object(host, "Resources", return_value=resources),
            patch.object(host.subprocess, "Popen", return_value=child) as launch,
            patch.object(
                host, "message", return_value={"id": "finish", "kind": "finish"}
            ),
            patch.object(host, "emit"),
            patch.multiple(
                host.signal,
                SIGALRM=14,
                SIGHUP=1,
                signal=Mock(),
                alarm=Mock(),
                create=True,
            ),
        ):
            result = host.host(
                ORIGIN,
                IMAGE,
                True,
                account_security_fixture=True,
                account_identity_fixture=True,
                personal_export_fixture=True,
            )
        resources.cleanup.assert_called_once()
        return result, launch.call_args.args[0]

    def test_host_pins_only_export_worker_preserves_caps_and_denies_wrong_marker(self):
        result, command = self.host_case()
        self.assertEqual(result, 0)
        self.assertIn("/checks/tools/checks/p11a_browser_backend.py", command)
        self.assertNotIn("/checks/tools/checks/p10c_browser_backend.py", command)
        self.assertEqual(command[-4:], ["--origin", ORIGIN, "--image", IMAGE])
        self.assertEqual(host.MAX_SECONDS, 300)
        self.assertEqual(self.host_case(False)[0], 1)

    def test_actual_export_forwarding_preserves_captured_request_and_extra_controls_deny(
        self,
    ):
        value, _, service, analysis = self.make()
        item = {
            "id": 1,
            "kind": "request",
            "path": fixture.EXPORTS,
            "method": "POST",
            "headers": [
                ["Origin", ORIGIN],
                ["Cookie", "captured"],
                ["X-CSRF-Token", "captured"],
            ],
            "bodyBase64": "",
        }
        with patch.object(value, "forward", return_value={"id": 1}) as forward:
            self.assertEqual(
                value.dispatch(item, Mock(), service, None, [], analysis), {"id": 1}
            )
            self.assertIs(forward.call_args.args[0], item)
            for changed in (
                {**item, "owner_id": ID},
                {"id": 2, "kind": "export_stats", "owner_id": ID},
                {"id": 3, "kind": "recover_rates"},
                {"id": 4, "kind": "workspace_grant"},
            ):
                with self.assertRaises(ValueError):
                    value.dispatch(changed, Mock(), service, None, [], analysis)
            self.assertEqual(forward.call_count, 1)

    def test_stats_do_not_expose_rows_bytes_ids_tokens_or_grants(self):
        value, conn, service, analysis = self.make()
        anonymous = value.dispatch(
            {"id": 1, "kind": "export_stats"}, Mock(), service, None, [], analysis
        )
        conn.execute.assert_not_called()
        self.assertEqual(anonymous["stored_bytes"], 0)
        value.cookies["__Host-aqua_session"] = "v2." + "s" * 43
        conn.execute.side_effect = [
            SimpleNamespace(fetchone=lambda: (ID, ID, 1, 1)),
            SimpleNamespace(fetchone=lambda: (1, 1, 20)),
        ]
        result = value.dispatch(
            {"id": 2, "kind": "export_stats"}, Mock(), service, None, [], analysis
        )
        self.assertEqual(
            set(result),
            {
                "id",
                "kind",
                "starts",
                "downloads",
                "real_provider_calls",
                "body_exposed",
                "retained_jobs",
                "ready_jobs",
                "stored_bytes",
                "owner_bound",
            },
        )
        self.assertEqual(
            (result["stored_bytes"], result["ready_jobs"], result["body_exposed"]),
            (20, 1, False),
        )

    def test_aggregate_bounds_fail_closed(self):
        for counts in ((6, 1, 0), (1, 2, 0), (1, 1, 33554433), (True, 1, 0)):
            value, conn, service, analysis = self.make()
            value.cookies["__Host-aqua_session"] = "v2." + "s" * 43
            conn.execute.side_effect = [
                SimpleNamespace(fetchone=lambda: (ID, ID, 1, 1)),
                SimpleNamespace(fetchone=lambda: counts),
            ]
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                value.dispatch(
                    {"id": 1, "kind": "export_stats"},
                    Mock(),
                    service,
                    None,
                    [],
                    analysis,
                )

    def test_counters_observe_real_completed_route_results_without_body_parse(self):
        value, _, _, _ = self.make()
        for _ in range(8):
            value.track({"path": fixture.EXPORTS, "method": "POST"}, {"status": 202})
            value.track(
                {"path": fixture.EXPORTS + "/" + ID + "/download", "method": "GET"},
                {"status": 200, "headers": []},
            )
        self.assertEqual(
            value.export_metadata(),
            {
                "starts": 8,
                "downloads": 8,
                "real_provider_calls": 0,
                "body_exposed": False,
            },
        )
        self.assertEqual(value.metadata()["schema_version"], 8)
        self.assertEqual(value.analysis.max_executions, 0)
        with self.assertRaises(ValueError):
            value.track({"path": fixture.EXPORTS, "method": "POST"}, {"status": 202})


class ProxyHeaderTests(unittest.TestCase):
    def test_repeated_restrictive_fields_pass_but_mixed_or_missing_fields_fail(self):
        from p11a_proxy_probe import private_cache_headers

        for values, expected in (
            ([("Cache-Control", "no-store")], True),
            ([("Cache-Control", "no-store"), ("cache-control", "no-store")], True),
            ([], False),
            ([("Content-Type", "application/json")], False),
            ([("Cache-Control", "public")], False),
            ([("Cache-Control", "no-store"), ("Cache-Control", "public")], False),
            ([("Cache-Control", "no-store, max-age=60")], False),
        ):
            with self.subTest(headers=values):
                self.assertIs(
                    private_cache_headers(SimpleNamespace(getheaders=lambda: values)),
                    expected,
                )


class CapacityFixtureTests(unittest.TestCase):
    @staticmethod
    def xml(*, name=capacity.TEST, classname=capacity.CLASS, child="", tests="1"):
        return (
            '<testsuites><testsuite name="pytest" tests="'
            + tests
            + '" errors="0" failures="0" skipped="0"><testcase classname="'
            + classname
            + '" name="'
            + name
            + '">'
            + child
            + "</testcase></testsuite></testsuites>"
        ).encode()

    def test_actual_disjoint_junit_merge_retains_core_bytes_and_exact_new_id(self):
        with tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parent
        ) as directory:
            root = Path(directory)
            core, extra = root / "bank.xml", root / "capacity-bank.xml"
            original = self.xml(name="old_case", classname="tests.old")
            core.write_bytes(original)
            extra.write_bytes(self.xml())
            proof = capacity.merge_junit(core, extra)
            self.assertEqual((root / "core-bank.xml").read_bytes(), original)
            self.assertEqual(proof["capacity_identity_count"], 1)
            self.assertIn(b"old_case", core.read_bytes())
            self.assertIn(capacity.TEST.encode(), core.read_bytes())
            with self.assertRaises(RuntimeError):
                capacity.merge_junit(core, extra)

    def test_skipped_failed_changed_identity_and_inflated_count_are_denied(self):
        with tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parent
        ) as directory:
            target = Path(directory) / "capacity.xml"
            for values in (
                {"name": "substitute"},
                {"classname": "tests.foreign"},
                {"child": "<skipped/>"},
                {"child": "<failure/>"},
                {"child": "<error/>"},
                {"tests": "2"},
            ):
                with self.subTest(values=values), self.assertRaises(RuntimeError):
                    target.write_bytes(self.xml(**values))
                    capacity.selected_case(target)

    def test_two_fresh_pairs_run_sequentially_with_exact_case_and_original_caps(self):
        events, commands = [], []
        xml = self.xml()

        def create(name, image, *args, command=()):
            if name.endswith("-pg"):
                self.assertIn("--network=none", args)
                self.assertIn(
                    "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,size=536870912,uid=999,gid=999,mode=0700",
                    args,
                )
            events.append(("create", name))
            return name

        def docker(*args, data=None, timeout=60):
            if args[0] == "rm":
                events.append(("remove", args[-1]))
            if "df" in args:
                return b"Filesystem 1K-blocks Used Available Use% Mounted\ntmpfs 524288 65536 458752 13% /var/lib/postgresql/data\n"
            if "cat" in args:
                return xml
            return b""

        def process(args, **kwargs):
            if args[:3] == ["docker", "container", "inspect"]:
                return SimpleNamespace(
                    returncode=1, stdout=b"", stderr=b"No such container"
                )
            commands.append(args)
            self.assertEqual(args[-1], capacity.CAPACITY_CASE)
            self.assertFalse(any("deselect" in value for value in args))
            return SimpleNamespace(returncode=0, stdout=b"passed", stderr=b"")

        with tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parent
        ) as directory:
            root = Path(directory)
            (root / "tools/checks/fixtures").mkdir(parents=True)
            for dataset in ("bank", "pagila"):
                (root / "tools/checks/fixtures" / (dataset + ".sql")).write_bytes(
                    b"fixed synthetic SQL"
                )
                (root / (dataset + ".xml")).write_bytes(
                    self.xml(name="old", classname="tests.old")
                )
            with (
                patch.object(capacity, "initialize"),
                patch.object(capacity.subprocess, "run", side_effect=process),
            ):
                result = capacity.verify(
                    docker, create, root, IMAGE, "known-run", root, b"fixed source"
                )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(commands), 2)
        self.assertLess(
            events.index(("remove", "known-run-capacity-bank-pg")),
            events.index(("create", "known-run-capacity-pagila-pg")),
        )

    def core_lifecycle(self, cleanup_ok=True):
        active, events, commands = set(), [], []

        def provision(image, name, containers):
            self.assertFalse(active, "next dataset started before prior pair absence")
            pair = (name + "-pg", name + "-tests")
            active.update(pair)
            containers.extend(pair)
            events.append(("provision", name.rsplit("-", 1)[1]))
            return pair

        def docker(*args, **kwargs):
            if args[:2] == ("image", "inspect"):
                return (IMAGE + "\n").encode()
            if args[0] == "rm":
                active.discard(args[-1])
                events.append(("remove", args[-1]))
            if "cat" in args:
                return self.xml(name="old", classname="tests.old")
            if "freeze" in args:
                return b"same-locked-image\n"
            return b""

        def process(args, **kwargs):
            if args[:3] == ["docker", "container", "inspect"]:
                return SimpleNamespace(
                    returncode=1 if cleanup_ok else 0,
                    stdout=b"",
                    stderr=b"No such container",
                )
            commands.append(args)
            selected = [arg for arg in args if arg.startswith("--deselect")]
            self.assertEqual(selected, ["--deselect=" + capacity.CAPACITY_CASE])
            return SimpleNamespace(
                returncode=0, stdout=b"fixed synthetic model", stderr=b""
            )

        def restore(docker, pg, runner):
            events.append(("restore", "bank" if "-bank-" in pg else "pagila"))
            return {"status": "passed"}

        with tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parent
        ) as directory:
            with (
                patch.object(run_backend, "provision_core", side_effect=provision),
                patch.object(run_backend, "docker", side_effect=docker),
                patch.object(run_backend.subprocess, "run", side_effect=process),
                patch.object(run_backend, "verify_restore", side_effect=restore),
                patch.object(run_backend, "source_archive", return_value=b"fixed"),
                patch.object(
                    capacity, "verify", return_value={"status": "passed"}
                ) as fresh,
                patch.object(
                    run_backend,
                    "coverage",
                    return_value={
                        "unique_tests": 1680,
                        "passed_in_at_least_one_fixture": 1680,
                    },
                ),
                patch("builtins.print"),
            ):
                code = run_backend.run(IMAGE, Path(directory))
            report = json.loads((Path(directory) / "report.json").read_bytes())
        return code, report, events, commands, fresh.call_count

    def test_ordinary_datasets_get_fresh_pairs_restore_and_absence_before_next(self):
        code, report, events, commands, fresh = self.core_lifecycle()
        self.assertEqual(code, 0)
        self.assertEqual(
            [event for event in events if event[0] == "provision"],
            [("provision", "bank"), ("provision", "pagila")],
        )
        self.assertEqual(
            [event for event in events if event[0] == "restore"],
            [("restore", "bank"), ("restore", "pagila")],
        )
        self.assertEqual(len(commands), 2)
        self.assertEqual(fresh, 1)
        self.assertEqual(set(report["app_restore_by_dataset"]), {"bank", "pagila"})
        self.assertEqual(
            [row["dataset"] for row in report["core_dataset_cleanup"]],
            ["bank", "pagila"],
        )

    def test_uncertain_core_absence_blocks_next_dataset_and_capacity(self):
        code, report, events, commands, fresh = self.core_lifecycle(False)
        self.assertEqual(code, 1)
        self.assertEqual(
            [event for event in events if event[0] == "provision"],
            [("provision", "bank")],
        )
        self.assertEqual(len(commands), 1)
        self.assertEqual(fresh, 0)
        self.assertEqual(report["cleanup"], "failed")

    def test_actual_provisioning_keeps_original_PG_WAL_runner_and_memory_caps(self):
        calls = []

        def create(name, image, *args, command=()):
            calls.append((name, args, command))
            return name

        with tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parent
        ) as directory:
            root = Path(directory)
            (root / "tools/checks/fixtures").mkdir(parents=True)
            for dataset in ("bank", "pagila"):
                (root / "tools/checks/fixtures" / (dataset + ".sql")).write_bytes(
                    b"synthetic"
                )
            with (
                patch.object(run_backend, "ROOT", root),
                patch.object(run_backend, "create", side_effect=create),
                patch.object(run_backend, "docker", return_value=b""),
                patch.object(run_backend, "initialize"),
                patch.object(run_backend, "source_archive", return_value=b"fixed"),
            ):
                owned = []
                pair = run_backend.provision_core(IMAGE, "known-bank", owned)
        self.assertEqual(pair, ("known-bank-pg", "known-bank-tests"))
        self.assertEqual(list(pair), owned)
        self.assertIn(
            "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,size=536870912,uid=999,gid=999,mode=0700",
            calls[0][1],
        )
        self.assertEqual(
            calls[0][2],
            (
                "postgres",
                "-c",
                "max_wal_size=128MB",
                "-c",
                "min_wal_size=32MB",
                "-c",
                "checkpoint_timeout=30s",
            ),
        )
        self.assertEqual(calls[1][2], ("300",))


if __name__ == "__main__":
    unittest.main(verbosity=2)
