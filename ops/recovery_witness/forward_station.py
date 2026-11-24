"""Create one separate DPAPI identity for a new, owner-designated forward installation."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from retirement.fingerprints import canonical_uuid

ACL = """
$ErrorActionPreference='Stop'
$path=$env:AQUA_FORWARD_IDENTITY_DIRECTORY
$user=[Security.Principal.WindowsIdentity]::GetCurrent().User
$local=[Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
if($path -ne (Join-Path $local 'Aqua/RecoveryIdentities')){throw 'installation path'}
for($d=[IO.DirectoryInfo]::new($path); $d; $d=$d.Parent){
 if(!$d.Exists -or ($d.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'directory identity'}
}
$acl=Get-Acl -LiteralPath $path
if(!$acl.AreAccessRulesProtected -or $acl.GetOwner([Security.Principal.SecurityIdentifier]) -ne $user){throw 'directory ACL'}
$rules=$acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])
if($rules.Count -ne 2){throw 'directory principals'}
foreach($r in $rules){
 if($r.IdentityReference.Value -notin @($user.Value,'S-1-5-18') -or
    $r.AccessControlType -ne 'Allow' -or $r.FileSystemRights -ne 'FullControl' -or
    ($r.InheritanceFlags -band [Security.AccessControl.InheritanceFlags]::ObjectInherit) -eq 0){throw 'directory policy'}
}
"""


def protected_bytes(value):
    script = """
$ErrorActionPreference='Stop';$s=[IO.MemoryStream]::new()
try{[Console]::OpenStandardInput().CopyTo($s);$raw=$s.ToArray()
if($raw.Length -ne 32){throw 'key size'}
$blob=[Security.Cryptography.ProtectedData]::Protect($raw,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
$out=[Console]::OpenStandardOutput();$out.Write($blob,0,$blob.Length);$out.Flush()
}finally{if($raw){[Array]::Clear($raw,0,$raw.Length)};$s.Dispose()}
"""
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
        input=value,
        capture_output=True,
        timeout=10,
    )
    if result.returncode or not 32 < len(result.stdout) <= 4096:
        raise ValueError("checkpoint_station_key_protection")
    return result.stdout


def create_once(path, generate, wrap):
    """The exclusive file survives interrupted creation and cannot be overwritten."""
    with path.open("xb") as out:
        private = generate()
        public = private.public_key().public_bytes_raw()
        sealed = wrap(private.private_bytes_raw())
        out.write(sealed)
        out.flush()
        os.fsync(out.fileno())
    return public


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    installation = canonical_uuid(args.installation)
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "installation_id": installation,
                    "writes": 0,
                }
            )
        )
        return
    if sys.platform != "win32":
        raise ValueError("checkpoint_station_windows_required")
    if __package__:
        from .station import load_station_key
    else:
        from station import load_station_key
    from types import SimpleNamespace

    vault = Path(os.environ["LOCALAPPDATA"]) / "Aqua"
    directory = vault / "RecoveryIdentities"
    checked = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ACL],
        env={**os.environ, "AQUA_FORWARD_IDENTITY_DIRECTORY": str(directory)},
        capture_output=True,
        timeout=10,
    )
    if checked.returncode:
        raise ValueError("checkpoint_station_owner_custody_required")
    witness_dir = vault / "Recovery" / "witness" / installation
    if witness_dir.exists() or witness_dir.is_symlink():
        raise ValueError("checkpoint_station_forward_installation_already_present")
    path = directory / ("witness-" + installation + ".dpapi")
    public = create_once(path, Ed25519PrivateKey.generate, protected_bytes)
    recovered = load_station_key(SimpleNamespace(installation=installation), public)
    challenge = os.urandom(32)
    recovered.public_key().verify(recovered.sign(challenge), challenge)
    print(
        json.dumps(
            {
                "status": "created_and_verified",
                "installation_id": installation,
                "witness_public_key": public.hex(),
            }
        )
    )


if __name__ == "__main__":
    main()
