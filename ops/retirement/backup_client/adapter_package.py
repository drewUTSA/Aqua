"""Exact keyless verifier source inventory, framing and verified-byte loading."""

import hashlib
import io
import json
from pathlib import Path
import re
import struct
import tarfile

MAX_SOURCE = 1048576
MAX_DUMP = 128 * 1024**2
MAX_CHAIN = 250001 * 208
MAX_HEADER = 16384


def read_packet(stream):
    """Caller owns an input alarm; no resource exists while reading."""

    def take(size):
        data = bytearray()
        while len(data) < size:
            part = stream.read(min(65536, size - len(data)))
            if not part:
                raise ValueError("verifier_request_truncated")
            data.extend(part)
        return bytes(data)

    h, s, d, c = struct.unpack("!4Q", take(32))
    if (
        not 0 < h <= MAX_HEADER
        or not 0 < s <= MAX_SOURCE
        or not 0 < d <= MAX_DUMP
        or not 208 <= c <= MAX_CHAIN
        or c % 208
    ):
        raise ValueError("verifier_request_capacity")
    result = (json.loads(take(h)), take(s), take(d), take(c))
    if stream.read(1):
        raise ValueError("verifier_request_trailing_data")
    return result


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def source_files(directory):
    root = Path(directory)
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("verifier_source_symlink_denied")
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        name = path.relative_to(root).as_posix()
        if path.suffix not in {".py", ".psql"}:
            raise ValueError("verifier_unreviewed_source_type")
        if not re.fullmatch(
            r"(?:verifier_[a-z_]+\.py|retirement/[a-z_]+\.py|sql/[a-z_]+\.psql)", name
        ):
            raise ValueError("verifier_unreviewed_source_path")
        raw = path.read_bytes()
        if not 0 < len(raw) <= 131072:
            raise ValueError("verifier_source_file_capacity")
        files[name] = raw
    if not {
        "verifier_controller.py",
        "verifier_process.py",
        "verifier_resources.py",
        "verifier_setup.py",
        "verifier_probe.py",
        "verifier_validation.py",
        "verifier_checks.py",
        "sql/bootstrap.psql",
        "sql/schema.psql",
        "sql/backup.psql",
    } <= set(files):
        raise ValueError("verifier_source_incomplete")
    return files


def manifest(files):
    return canonical(
        {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
    )


def pack(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, raw in [*sorted(files.items()), ("manifest.json", manifest(files))]:
            item = tarfile.TarInfo(name)
            item.size, item.mode = len(raw), 0o600
            archive.addfile(item, io.BytesIO(raw))
    value = output.getvalue()
    if len(value) > MAX_SOURCE:
        raise ValueError("verifier_source_archive_capacity")
    return value


def unpack(raw, expected):
    if not 0 < len(raw) <= MAX_SOURCE or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("verifier_source_pin_invalid")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for item in archive:
            if (
                not item.isfile()
                or item.name in files
                or item.name.startswith("/")
                or ".." in item.name.split("/")
                or not 0 < item.size <= 131072
            ):
                raise ValueError("verifier_source_member_invalid")
            files[item.name] = archive.extractfile(item).read(131073)
    pin = files.pop("manifest.json")
    if hashlib.sha256(pin).hexdigest() != expected or pin != manifest(files):
        raise ValueError("verifier_source_manifest_mismatch")
    return files


def packet(header, package, dump, chain):
    raw = canonical(header)
    if (
        not 0 < len(raw) <= MAX_HEADER
        or not 0 < len(package) <= MAX_SOURCE
        or not 0 < len(dump) <= MAX_DUMP
        or not 208 <= len(chain) <= MAX_CHAIN
        or len(chain) % 208
    ):
        raise ValueError("verifier_request_capacity")
    return (
        struct.pack("!4Q", len(raw), len(package), len(dump), len(chain))
        + raw
        + package
        + dump
        + chain
    )


REMOTE = r"""import hashlib,io,json,os,signal,struct,sys,tarfile,types,time
started=time.monotonic()
signal.alarm(15)
def read(n):
 out=bytearray()
 while len(out)<n:
  part=sys.stdin.buffer.read(min(65536,n-len(out)))
  if not part:raise RuntimeError('verifier_request_truncated')
  out.extend(part)
 return bytes(out)
h,s,d,c=struct.unpack('!4Q',read(32))
assert 0<h<=16384 and 0<s<=1048576 and 0<d<=134217728 and 208<=c<=52000208 and c%208==0
header=json.loads(read(h));package=read(s);dump=read(d);chain=read(c);assert not sys.stdin.buffer.read(1)
signal.alarm(0)
files={}
with tarfile.open(fileobj=io.BytesIO(package),mode='r:') as archive:
 for m in archive:
  assert m.isfile() and m.name not in files and not m.name.startswith('/') and '..' not in m.name.split('/') and 0<m.size<=131072
  files[m.name]=archive.extractfile(m).read(131073)
manifest=files.pop('manifest.json');assert hashlib.sha256(manifest).hexdigest()==sys.argv[1]
actual={name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}
assert json.dumps(actual,sort_keys=True,separators=(',',':')).encode()==manifest
for name in ('verifier_process','verifier_resources','verifier_setup','verifier_controller'):
 module=types.ModuleType(name);module.__file__='/verified/'+name+'.py';sys.modules[name]=module
 exec(compile(files[name+'.py'],module.__file__,'exec'),module.__dict__)
remaining=header['seconds']-10-(time.monotonic()-started)
result=sys.modules['verifier_controller'].execute(files,dump,chain,header['expected'],header['image'],sys.argv[1],remaining,header['run'])
print(json.dumps(result,sort_keys=True));raise SystemExit(result['status']!='passed')
"""
