"""Trust one public fixture CA in a new Firefox profile using the installed NSS."""

import ctypes as c
import os
from pathlib import Path

FIREFOX = Path(os.environ["ProgramFiles"]) / "Mozilla Firefox"


def trust(profile: Path, certificate: bytes):
    if profile.exists() and list(profile.iterdir()):
        raise ValueError("trust requires a new empty profile")
    profile.mkdir(exist_ok=True)
    if certificate.count(b"BEGIN CERTIFICATE") != 1 or b"PRIVATE" in certificate:
        raise ValueError("one public certificate required")
    with os.add_dll_directory(str(FIREFOX)):
        nss = c.CDLL(str(FIREFOX / "nss3.dll"))
        ptr, integer, string = c.c_void_p, c.c_int, c.c_char_p

        def call(name, retval, types, *args):
            func = getattr(nss, name)
            func.restype, func.argtypes = retval, types
            return func(*args)

        def ok(result):
            if result != 0:
                raise RuntimeError(
                    "nss_error_" + str(call("PORT_GetError", integer, []))
                )

        class Trust(c.Structure):
            _fields_ = [("ssl", c.c_uint), ("mail", c.c_uint), ("sign", c.c_uint)]

        ok(
            call(
                "NSS_InitReadWrite",
                integer,
                [string],
                ("sql:" + str(profile.resolve())).encode(),
            )
        )
        slot = temp = stored = None
        try:
            slot = call("PK11_GetInternalKeySlot", ptr, [])
            if not slot:
                raise RuntimeError("no_internal_test_slot")
            if call("PK11_NeedUserInit", integer, [ptr], slot):
                ok(
                    call(
                        "PK11_InitPin", integer, [ptr, string, string], slot, None, b""
                    )
                )
            temp = call(
                "CERT_DecodeCertFromPackage",
                ptr,
                [string, integer],
                certificate,
                len(certificate),
            )
            if not temp:
                raise RuntimeError("invalid_fixture_certificate")
            name = b"Aqua temporary presenter root"
            ok(
                call(
                    "PK11_ImportCert",
                    integer,
                    [ptr, ptr, c.c_ulong, string, integer],
                    slot,
                    temp,
                    0,
                    name,
                    0,
                )
            )
            db = call("CERT_GetDefaultCertDB", ptr, [])
            stored = call("CERT_FindCertByNickname", ptr, [ptr, string], db, name)
            if not stored:
                raise RuntimeError("fixture_import_missing")
            settings = Trust()
            ok(
                call(
                    "CERT_DecodeTrustString",
                    integer,
                    [c.POINTER(Trust), string],
                    c.byref(settings),
                    b"C,,",
                )
            )
            ok(
                call(
                    "CERT_ChangeCertTrust",
                    integer,
                    [ptr, ptr, c.POINTER(Trust)],
                    db,
                    stored,
                    c.byref(settings),
                )
            )
        finally:
            for cert in (stored, temp):
                if cert:
                    call("CERT_DestroyCertificate", None, [ptr], cert)
            if slot:
                call("PK11_FreeSlot", None, [ptr], slot)
            ok(call("NSS_Shutdown", integer, []))
    if not (profile / "cert9.db").is_file():
        raise RuntimeError("profile_database_missing")
