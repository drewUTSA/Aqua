"""Opt-in verified exporter route; no SSH or private read on import."""

import hashlib
import importlib.abc
import importlib.util
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

PACKAGE = "_aqua_p11_verified_export"
STAGE = re.compile(
    r"/srv/bank-ai/\.check-results/p11bc-release-[0-9]{17}-[a-f0-9]{8}\Z"
)
HEX = re.compile(r"[a-f0-9]{64}\Z")
MAX_FILE = 131072
MAX_MANIFEST = 8192
MAX_CLOSURE = 2 * 1024**2
FILES = frozenset(
    {
        "append_provision.py",
        "archive.py",
        "backup_protocol.py",
        "export_code.py",
        "export_peer.py",
        "export_protocol.py",
        "export_resources.py",
        "export.py",
        "initialize.py",
        "install_resources.py",
        "install.py",
        "installed_publisher.py",
        "maintenance.py",
        "materialize.py",
        "operator_deadline.py",
        "operator_files.py",
        "operator_scope.py",
        "publisher_launcher.py",
        "recover.py",
        "recovery_driver.py",
        "retirement_host.py",
    }
)


class RouteDenied(ValueError):
    pass


def require(condition, category):
    if not condition:
        raise RouteDenied(category)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pairs(items):
    result = {}
    for name, value in items:
        require(name not in result, "authority_route_duplicate_manifest_field")
        result[name] = value
    return result


@dataclass(frozen=True)
class VerifiedClosure:
    files: object
    manifest_sha256: str


def verify_cache(manifest, expected_manifest, fetch):
    """Check every module before any exporter code is compiled or imported.

    expected_manifest must be an independent ROOT-reviewed pin. A self-hashed
    manifest supplied by an untrusted party does not establish source approval.
    fetch is a trusted byte reader; remote_main uses the strict owned reader.
    """
    require(
        type(manifest) is bytes and 0 < len(manifest) <= MAX_MANIFEST,
        "authority_route_manifest_budget",
    )
    require(
        type(expected_manifest) is str
        and HEX.fullmatch(expected_manifest)
        and digest(manifest) == expected_manifest,
        "authority_route_manifest_changed",
    )
    try:
        values = json.loads(manifest.decode("utf-8"), object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise RouteDenied("authority_route_manifest_invalid") from None
    require(
        type(values) is dict and set(values) == FILES,
        "authority_route_closed_manifest_required",
    )
    require(
        all(type(pin) is str and HEX.fullmatch(pin) for pin in values.values()),
        "authority_route_source_pin_invalid",
    )
    require(
        manifest == canonical(values) and callable(fetch),
        "authority_route_closed_manifest_required",
    )
    cache = {}
    total = 0
    for name in sorted(FILES):
        raw = fetch(name)
        require(
            type(raw) is bytes and 0 < len(raw) <= MAX_FILE,
            "authority_route_source_budget",
        )
        total += len(raw)
        require(
            total <= MAX_CLOSURE and digest(raw) == values[name],
            "authority_route_source_changed",
        )
        cache[name] = raw
    return VerifiedClosure(MappingProxyType(cache), expected_manifest)


class CachedModules(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serve only verified RAM bytes; never search sibling directories."""

    def __init__(self, closure, source_root):
        self.closure, self.source_root = closure, Path(source_root)

    def find_spec(self, fullname, path=None, target=None):
        if fullname == PACKAGE:
            return importlib.util.spec_from_loader(fullname, self, is_package=True)
        if fullname.startswith(PACKAGE + "."):
            stem = fullname[len(PACKAGE) + 1 :]
            require(
                "." not in stem and stem + ".py" in self.closure.files,
                "authority_route_unlisted_import",
            )
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        if module.__name__ == PACKAGE:
            module.__path__ = []
            return
        filename = module.__name__[len(PACKAGE) + 1 :] + ".py"
        module.__file__ = str(self.source_root / filename)
        # The complete independently pinned closure was cached before execution.
        exec(  # noqa: S102
            compile(self.closure.files[filename], module.__file__, "exec"),
            module.__dict__,
        )


def run_verified(closure, source_root, action, profile_sha256, exporter_sha256):
    require(
        type(closure) is VerifiedClosure, "authority_route_verified_closure_required"
    )
    require(
        type(action) is str and action in {"head", "export"},
        "authority_route_action_invalid",
    )
    require(
        type(profile_sha256) is str
        and HEX.fullmatch(profile_sha256)
        and type(exporter_sha256) is str
        and HEX.fullmatch(exporter_sha256),
        "authority_route_expected_pin_invalid",
    )
    require(
        digest(closure.files["export.py"]) == exporter_sha256,
        "authority_route_exporter_pin_changed",
    )
    require(
        not any(
            name == PACKAGE or name.startswith(PACKAGE + ".") for name in sys.modules
        ),
        "authority_route_package_already_loaded",
    )
    finder = CachedModules(closure, source_root)
    previous_argv = sys.argv
    sys.argv = [
        str(Path(source_root) / "export.py"),
        "--action",
        action,
        "--profile-sha256",
        profile_sha256,
    ]
    sys.meta_path.insert(0, finder)
    try:
        module = __import__(PACKAGE + ".export", fromlist=["export"])
        return module.main()
    finally:
        sys.argv = previous_argv
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)
        for name, module in list(sys.modules.items()):
            if (name == PACKAGE or name.startswith(PACKAGE + ".")) and getattr(
                module, "__loader__", None
            ) is finder:
                del sys.modules[name]


def read_owned(path, limit):
    path = Path(path)
    parent = path.parent.lstat()
    require(
        path.resolve(strict=True) == path
        and stat.S_ISDIR(parent.st_mode)
        and parent.st_uid == 1000
        and stat.S_IMODE(parent.st_mode) == 0o700,
        "authority_route_directory_invalid",
    )
    descriptor = os.open(
        path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    )
    try:
        before = os.fstat(descriptor)
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_uid == 1000
            and before.st_nlink == 1
            and stat.S_IMODE(before.st_mode) == 0o600
            and 0 < before.st_size <= limit,
            "authority_route_file_invalid",
        )
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(limit + 1)
        after, named, parent_after = (
            os.fstat(descriptor),
            path.lstat(),
            path.parent.lstat(),
        )

        def identity(info):
            return (
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_uid,
                info.st_mode,
                info.st_nlink,
                info.st_ctime_ns,
            )

        def parent_identity(info):
            return info.st_dev, info.st_ino, info.st_mode, info.st_uid

        require(
            len(raw) == before.st_size
            and identity(before) == identity(after) == identity(named)
            and parent_identity(parent) == parent_identity(parent_after)
            and path.resolve(strict=True) == path,
            "authority_route_file_changed",
        )
        return raw
    finally:
        os.close(descriptor)


def remote_main(stage, manifest_sha256, exporter_sha256, action, profile_sha256):
    require(
        type(stage) is str and STAGE.fullmatch(stage), "authority_route_stage_invalid"
    )
    root = Path(stage)
    manifest = read_owned(root / "authority-route-manifest.json", MAX_MANIFEST)
    source_root = root / "ops/retirement"
    closure = verify_cache(
        manifest, manifest_sha256, lambda name: read_owned(source_root / name, MAX_FILE)
    )
    return run_verified(closure, source_root, action, profile_sha256, exporter_sha256)


# ROOT must separately stage this exact module as authority-route.py and pin
# its full bytes. This tiny launcher verifies that foundation before importing
# it; it does not put an unverified sibling directory or cwd on sys.path.
BOOTSTRAP = r"""import hashlib,os,pathlib,re,stat,sys,types
try:
 stage,helper_pin,*arguments=sys.argv[1:]
 if not re.fullmatch(r'/srv/bank-ai/\.check-results/p11bc-release-[0-9]{17}-[a-f0-9]{8}',stage) or not re.fullmatch(r'[a-f0-9]{64}',helper_pin):raise ValueError()
 root=pathlib.Path(stage);d=root.lstat()
 if root.resolve(strict=True)!=root or not stat.S_ISDIR(d.st_mode) or d.st_uid!=1000 or stat.S_IMODE(d.st_mode)!=0o700:raise ValueError()
 p=root/'authority-route.py';fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
 try:
  a=os.fstat(fd)
  if not stat.S_ISREG(a.st_mode) or a.st_uid!=1000 or a.st_nlink!=1 or stat.S_IMODE(a.st_mode)!=0o600 or not 0<a.st_size<=131072:raise ValueError()
  with os.fdopen(fd,'rb',closefd=False) as f:raw=f.read(131073)
  b,n,after_root=os.fstat(fd),p.lstat(),root.lstat();identity=lambda v:(v.st_dev,v.st_ino,v.st_size,v.st_mtime_ns,v.st_uid,v.st_mode,v.st_nlink,v.st_ctime_ns)
  if len(raw)!=a.st_size or identity(a)!=identity(b) or identity(a)!=identity(n) or (d.st_dev,d.st_ino,d.st_mode,d.st_uid)!=(after_root.st_dev,after_root.st_ino,after_root.st_mode,after_root.st_uid) or p.resolve(strict=True)!=p or hashlib.sha256(raw).hexdigest()!=helper_pin:raise ValueError()
 finally:os.close(fd)
 name='_aqua_p11_route_bootstrap'
 if name in sys.modules:raise ValueError()
 module=types.ModuleType(name);module.__file__=str(p);sys.modules[name]=module
 exec(compile(raw,str(p),'exec'),module.__dict__)
 module.remote_main(stage,*arguments)
except BaseException:
 sys.stderr.write('authority_route_rejected\n')
 raise SystemExit(1) from None
"""


def remote_argv(
    stage, action, *, helper_sha256, manifest_sha256, exporter_sha256, profile_sha256
):
    """Return fixed remote argv only. ROOT's verified SSH helper must wrap it."""
    require(
        type(stage) is str and STAGE.fullmatch(stage), "authority_route_stage_invalid"
    )
    require(
        type(action) is str and action in {"head", "export"},
        "authority_route_action_invalid",
    )
    require(
        all(
            type(pin) is str and HEX.fullmatch(pin)
            for pin in (helper_sha256, manifest_sha256, exporter_sha256, profile_sha256)
        ),
        "authority_route_expected_pin_invalid",
    )
    return [
        "/usr/bin/python3",
        "-I",
        "-E",
        "-s",
        "-B",
        "-c",
        BOOTSTRAP,
        stage,
        helper_sha256,
        manifest_sha256,
        exporter_sha256,
        action,
        profile_sha256,
    ]
