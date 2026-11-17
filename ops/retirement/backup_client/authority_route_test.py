"""Synthetic cached modules only; never execute actual retirement source."""

import builtins
import io
import stat
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import authority_route as route

STAGE = "/srv/bank-ai/.check-results/p11bc-release-20261117123456789-0123abcd"


class RouteTests(unittest.TestCase):
    def synthetic(self, *, exporter=None):
        values = {name: b"pass\n" for name in route.FILES}
        values["maintenance.py"] = (
            b"import builtins\nbuiltins._aqua_route_events.append('maintenance_imported')\nTOKEN='reviewed_synthetic'\n"
        )
        values["install.py"] = (
            b"from .maintenance import TOKEN\ndef source_token(): return TOKEN\n"
        )
        values["export.py"] = (
            exporter
            or b"from . import maintenance\nimport builtins,sys\nbuiltins._aqua_route_events.append('export_imported')\ndef main():\n from .install import source_token\n return {'token':source_token(),'package':__package__,'argv':list(sys.argv)}\n"
        )
        manifest = route.canonical(
            {name: route.digest(raw) for name, raw in values.items()}
        )
        return values, manifest

    def test_all_hashes_precede_any_eager_or_lazy_cached_module_execution(self):
        values, manifest = self.synthetic()
        events = []

        def fetch(name):
            events.append("fetched:" + name)
            return values[name]

        with patch.object(builtins, "_aqua_route_events", events, create=True):
            closure = route.verify_cache(manifest, route.digest(manifest), fetch)
            self.assertEqual(
                events, ["fetched:" + name for name in sorted(route.FILES)]
            )
            result = route.run_verified(
                closure,
                Path("/synthetic/ops/retirement"),
                "head",
                "a" * 64,
                route.digest(values["export.py"]),
            )
        self.assertEqual(result["token"], "reviewed_synthetic")
        self.assertEqual(result["package"], route.PACKAGE)
        self.assertEqual(
            result["argv"][1:], ["--action", "head", "--profile-sha256", "a" * 64]
        )
        self.assertEqual(events[-2:], ["maintenance_imported", "export_imported"])
        self.assertFalse(
            any(
                name == route.PACKAGE or name.startswith(route.PACKAGE + ".")
                for name in sys.modules
            )
        )

    def test_last_source_mismatch_denies_before_any_module_runs(self):
        values, manifest = self.synthetic()
        values[max(route.FILES)] = b"raise RuntimeError('must_not_execute')\n"
        events = []
        with (
            patch.object(builtins, "_aqua_route_events", events, create=True),
            self.assertRaises(route.RouteDenied),
        ):
            route.verify_cache(manifest, route.digest(manifest), values.__getitem__)
        self.assertEqual(events, [])

    def test_cached_bytes_ignore_later_disk_or_input_map_changes(self):
        values, manifest = self.synthetic()
        closure = route.verify_cache(
            manifest, route.digest(manifest), values.__getitem__
        )
        values["maintenance.py"] = b"raise AssertionError('unverified_replacement')\n"
        with self.assertRaises(TypeError):
            closure.files["maintenance.py"] = values["maintenance.py"]
        with patch.object(builtins, "_aqua_route_events", [], create=True):
            result = route.run_verified(
                closure,
                "/synthetic/ops/retirement",
                "export",
                "a" * 64,
                route.digest(values["export.py"]),
            )
        self.assertEqual(result["token"], "reviewed_synthetic")

    def test_manifest_must_match_independent_pin_and_exact_closed_inventory(self):
        values, manifest = self.synthetic()
        fetches = []
        bad_manifests = [
            manifest + b"\n",
            b"{}",
            manifest.replace(b'"archive.py":', b'"../outside.py":', 1),
            manifest[:-1] + b',"archive.py":"' + b"0" * 64 + b'"}',
            b" " * (route.MAX_MANIFEST + 1),
            manifest.decode().encode("utf-16"),
        ]
        for raw in bad_manifests:
            with self.subTest(bytes=len(raw)), self.assertRaises(route.RouteDenied):
                route.verify_cache(
                    raw,
                    route.digest(raw),
                    lambda name: fetches.append(name) or values[name],
                )
        with self.assertRaises(route.RouteDenied):
            route.verify_cache(manifest, "0" * 64, values.__getitem__)
        self.assertEqual(fetches, [])

    def test_poisoned_package_and_unlisted_sibling_never_fall_back_to_filesystem(self):
        values, manifest = self.synthetic()
        closure = route.verify_cache(
            manifest, route.digest(manifest), values.__getitem__
        )
        poison = ModuleType(route.PACKAGE + ".maintenance")
        with patch.dict(sys.modules, {poison.__name__: poison}):
            with self.assertRaises(route.RouteDenied):
                route.run_verified(
                    closure,
                    "/synthetic",
                    "head",
                    "a" * 64,
                    route.digest(values["export.py"]),
                )
            self.assertIs(sys.modules[poison.__name__], poison)
        values, manifest = self.synthetic(
            exporter=b"from . import not_in_manifest\ndef main(): return None\n"
        )
        closure = route.verify_cache(
            manifest, route.digest(manifest), values.__getitem__
        )
        with self.assertRaises(route.RouteDenied):
            route.run_verified(
                closure,
                "/synthetic",
                "head",
                "a" * 64,
                route.digest(values["export.py"]),
            )

    def test_route_is_fixed_isolated_python_and_has_no_ssh_or_private_values(self):
        pins = {
            "helper_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "exporter_sha256": "c" * 64,
            "profile_sha256": "d" * 64,
        }
        argv = route.remote_argv(STAGE, "head", **pins)
        self.assertEqual(argv[:6], ["/usr/bin/python3", "-I", "-E", "-s", "-B", "-c"])
        self.assertEqual(argv[6], route.BOOTSTRAP)
        self.assertEqual(
            argv[7:], [STAGE, "a" * 64, "b" * 64, "c" * 64, "head", "d" * 64]
        )
        for stage, action in (
            ("/srv/bank-ai", "head"),
            (STAGE + "/../other", "head"),
            (STAGE, "shell"),
            (STAGE, []),
        ):
            with (
                self.subTest(type=type(action).__name__),
                self.assertRaises(route.RouteDenied),
            ):
                route.remote_argv(stage, action, **pins)
        with self.assertRaises(route.RouteDenied):
            route.remote_argv(STAGE, "head", **(pins | {"helper_sha256": "foreign"}))

    def test_exporter_separate_pin_is_required_even_with_valid_closure(self):
        values, manifest = self.synthetic()
        closure = route.verify_cache(
            manifest, route.digest(manifest), values.__getitem__
        )
        with self.assertRaises(route.RouteDenied):
            route.run_verified(closure, "/synthetic", "head", "a" * 64, "0" * 64)

    def test_source_file_and_total_cache_budgets_are_enforced_before_execution(self):
        for oversized in (True, False):
            values, _ = self.synthetic()
            values = {name: b"x" * (route.MAX_FILE + int(oversized)) for name in values}
            manifest = route.canonical(
                {name: route.digest(raw) for name, raw in values.items()}
            )
            with (
                self.subTest(per_file_overflow=oversized),
                self.assertRaises(route.RouteDenied),
            ):
                route.verify_cache(manifest, route.digest(manifest), values.__getitem__)

    def test_owned_reader_models_mode_owner_link_inode_and_parent_changes(self):
        raw = b"pass\n"

        def info(**changes):
            return SimpleNamespace(
                **(
                    {
                        "st_mode": stat.S_IFREG | 0o600,
                        "st_uid": 1000,
                        "st_nlink": 1,
                        "st_size": len(raw),
                        "st_dev": 7,
                        "st_ino": 8,
                        "st_mtime_ns": 9,
                    }
                    | changes
                )
            )

        parent = info(st_mode=stat.S_IFDIR | 0o700, st_ino=3)
        variants = (
            (info(), info(), info(), parent),
            (info(st_uid=999), info(), info(), parent),
            (info(st_nlink=2), info(), info(), parent),
            (info(st_mode=stat.S_IFREG | 0o644), info(), info(), parent),
            (info(), info(st_ino=88), info(), parent),
            (info(), info(), info(st_ino=88), parent),
            (info(), info(), info(), info(st_mode=stat.S_IFDIR | 0o700, st_ino=33)),
        )
        for index, (before, after, named, parent_after) in enumerate(variants):
            fake = SimpleNamespace()
            fake.parent = SimpleNamespace()
            fake.resolve = lambda fake=fake, **kwargs: fake
            fake.lstat = lambda named=named: named
            with (
                self.subTest(variant=index),
                patch.object(route, "Path", return_value=fake),
                patch.object(
                    fake.parent,
                    "lstat",
                    side_effect=[parent, parent_after],
                    create=True,
                ),
                patch.object(route.os, "O_NOFOLLOW", 0, create=True),
                patch.object(route.os, "O_NONBLOCK", 0, create=True),
                patch.object(route.os, "O_CLOEXEC", 0, create=True),
                patch.object(route.os, "open", return_value=17),
                patch.object(route.os, "fstat", side_effect=[before, after]),
                patch.object(route.os, "fdopen", return_value=io.BytesIO(raw)),
                patch.object(route.os, "close"),
            ):
                if index == 0:
                    self.assertEqual(route.read_owned("synthetic", 128), raw)
                else:
                    with self.assertRaises(route.RouteDenied):
                        route.read_owned("synthetic", 128)


if __name__ == "__main__":
    unittest.main()
