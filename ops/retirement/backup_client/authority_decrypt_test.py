"""Owned Python pipe models verify bounds, auth-exit and signal cleanup only."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import authority_bridge as bridge
import authority_decrypt as decrypt


class DecryptTests(unittest.TestCase):
    def modeled_process(self, program, maximum=1024, seconds=1):
        real_popen = subprocess.Popen
        children = []

        def own_child(command, **options):
            self.assertEqual(command[0], "/modeled-age-never-executed")
            child = real_popen([sys.executable, "-c", program], **options)
            children.append(child)
            return child

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cipher, identity = root / "model.age", root / "model.identity"
            for path in (cipher, identity):
                path.write_bytes(b"PUBLIC-SYNTHETIC-MODEL")
                path.chmod(0o600)
            with (
                patch.object(
                    decrypt.stream,
                    "age_binary",
                    return_value="/modeled-age-never-executed",
                ),
                patch.object(decrypt.subprocess, "Popen", side_effect=own_child),
                patch.object(decrypt.archive, "MAX_ARCHIVE", maximum),
            ):
                try:
                    return decrypt.decrypt_ram(cipher, identity, seconds=seconds)
                finally:
                    self.assertTrue(all(child.poll() is not None for child in children))
                    self.assertEqual(len(list(root.iterdir())), 2)

    def test_modeled_output_returns_only_after_success_exit(self):
        self.assertEqual(
            self.modeled_process(
                "import sys;sys.stdout.buffer.write(b'public RAM archive')"
            ),
            b"public RAM archive",
        )

    def test_nonzero_auth_exit_never_returns_earlier_plaintext(self):
        with self.assertRaisesRegex(
            bridge.stream.BackupError, "authenticated_decryption_failed"
        ):
            self.modeled_process(
                "import sys;sys.stdout.buffer.write(b'UNAUTHENTICATED');sys.stdout.flush();raise SystemExit(1)"
            )

    def test_oversize_and_stalled_owned_processes_are_stopped(self):
        for program, seconds, category in (
            (
                "import sys;sys.stdout.buffer.write(b'x'*1025);sys.stdout.flush()",
                1,
                "decrypt_capacity",
            ),
            ("import time;time.sleep(10)", 0.05, "decrypt_deadline"),
        ):
            with (
                self.subTest(category=category),
                self.assertRaisesRegex(bridge.stream.BackupError, category),
            ):
                self.modeled_process(program, seconds=seconds)

    def test_operation_SIGTERM_then_repeat_during_owned_cleanup_is_finite(self):
        program = r"""
import json,os,signal,subprocess,sys
import authority_bridge as b
child=None;cleaned=False
try:
 with b.Operation():
  try:
   child=subprocess.Popen([sys.executable,'-c','import signal;signal.pause()'],start_new_session=True)
   os.kill(os.getpid(),signal.SIGTERM)
  finally:
   os.kill(os.getpid(),signal.SIGTERM)
   b.stream.stop_owned(child)
   cleaned=True
except b.stream.BackupError as error:
 assert str(error)=='authority_operation_cancelled' and cleaned and child.poll() is not None
 print(json.dumps({'controlled_cancellation':True,'own_child_reaped':True,'SSH_age_Docker_actions':0}))
else:raise AssertionError('cancelled_operation_was_green')
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", program],
            cwd=Path(bridge.__file__).parent,
            capture_output=True,
            timeout=6,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(
            json.loads(result.stdout),
            {
                "controlled_cancellation": True,
                "own_child_reaped": True,
                "SSH_age_Docker_actions": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
