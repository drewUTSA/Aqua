"""Carry encrypted traffic between the presenter's Windows and container loopbacks."""

import socket
import socketserver
import subprocess
import threading
from contextlib import contextmanager

PEER = """
import os,socket,threading
with socket.create_connection(('127.0.0.1',8443),timeout=8) as dest:
    dest.settimeout(300)
    def inbound():
        try:
            while data := os.read(0, 65536):
                dest.sendall(data)
            dest.shutdown(socket.SHUT_WR)
        except OSError:
            pass
    threading.Thread(target=inbound, daemon=True).start()
    try:
        while data := dest.recv(65536):
            view = memoryview(data)
            while view:
                view = view[os.write(1, view):]
    except OSError:
        pass
"""


@contextmanager
def relay(container):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            if self.client_address[0] != "127.0.0.1":
                return
            proc = subprocess.Popen(
                [
                    "docker",
                    "--context",
                    "desktop-linux",
                    "exec",
                    "-i",
                    container,
                    "python",
                    "-B",
                    "-c",
                    PEER,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            assert proc.stdin is not None and proc.stdout is not None

            def inbound():
                try:
                    while data := self.request.recv(65536):
                        view = memoryview(data)
                        while view:
                            view = view[proc.stdin.write(view) :]
                except (OSError, ValueError):
                    pass
                finally:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass

            with self.server.guard:
                self.server.procs.add(proc)
            threading.Thread(target=inbound, daemon=True).start()
            try:
                while data := proc.stdout.read(65536):
                    self.request.sendall(data)
            except OSError:
                pass
            finally:
                proc.stdout.close()
                if proc.poll() is None:
                    proc.terminate()
                proc.wait(timeout=3)
                with self.server.guard:
                    self.server.procs.discard(proc)

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = False

        def process_request(self, request, client_address):
            if not self.slots.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, client_address)
            except BaseException:
                self.slots.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self.slots.release()

        def server_bind(self):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    with Server(("127.0.0.1", 0), Handler) as server:
        server.guard = threading.Lock()
        server.procs = set()
        server.slots = threading.BoundedSemaphore(16)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_address[1]
        finally:
            server.shutdown()
            thread.join(3)
            with server.guard:
                procs = list(server.procs)
            for proc in procs:
                if proc.poll() is None:
                    proc.terminate()
                proc.wait(timeout=3)
