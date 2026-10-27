"""Independent adversarial controls over real disposable identity/workspace rows."""

from copy import deepcopy
from threading import Event, Lock
import time

import pytest

from auth.security import UserSession
from auth.sessions import session_cookie_name, token_digest
from storage.pool import Storage
from workspace import completion, submissions
from workspace.contracts import FirstSubmission, Submission
from workspace.database import guard
from workspace_fixtures import GOOD


class Engine:
    """A bounded fake can deliberately ignore one final cooperative auth check."""

    def __init__(self):
        self.calls = []
        self.entered, self.release = Event(), Event()
        self.release.set()
        self.hook = None
        self.active = self.maximum = 0
        self.lock = Lock()

    def run(self, payload, control):
        with self.lock:
            self.calls.append(deepcopy(payload))
            self.active += 1
            self.maximum = max(self.maximum, self.active)
        self.entered.set()
        try:
            control(None)
            for _ in range(100):
                if self.release.wait(0.05):
                    break
                control(None)
            else:
                raise AssertionError("independent_fake_deadline")
            if self.hook:
                self.hook()
            return deepcopy(GOOD), 200
        finally:
            with self.lock:
                self.active -= 1

    def wait_active(self, expected):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with self.lock:
                if self.active == expected:
                    return
            time.sleep(0.01)
        raise AssertionError("independent_fake_not_started")

    def close(self):
        self.release.set()


class SecurityWorld:
    def __init__(self, world):
        from analysis import policy

        assert (
            policy.RUNNING_GLOBAL,
            policy.QUEUED_GLOBAL,
            policy.RUNNING_OWNER,
            policy.QUEUED_OWNER,
        ) == (2, 8, 1, 2)
        self.world, self.storage = world, world.storage
        self.engine = Engine()
        self.services = []

    def session(self, label="A", *, grant=True):
        client, owner = self.world.client(label, grant=grant)
        raw = client.cookies.get(session_cookie_name(self.world.settings))
        digest = token_digest(raw)
        stored = self.world.store.authenticate(digest, meaningful_activity=False)
        session = UserSession(
            stored.user,
            client.headers["X-CSRF-Token"],
            digest,
            stored.can_query,
            stored.grant_version,
            stored.auth_epoch,
            stored.dataset_key,
        )
        assert session.user["id"] == owner
        return client, session

    def service(self, engine=None):
        from analysis.service import Analysis

        service = Analysis(
            Storage(self.storage.settings),
            self.world.policy,
            self.world.settings.session_secret,
            self.world.settings,
            engine=engine or self.engine,
            start=False,
        )
        self.services.append(service)
        return service

    def seed(self, session, question="Earlier question", *, chat_id=None, result=None):
        """Create a valid owned historical turn without invoking a provider/job."""
        body = (FirstSubmission if chat_id is None else Submission)(
            **self.world.body(question)
        )
        with self.storage.transaction() as conn:
            guard(conn, session, self.world.policy, data=True)
            request, created = submissions.begin(
                conn,
                session,
                body,
                chat_id=chat_id,
                input_id=None,
                default_model="ollama",
            )
            assert created
            completion.finish(conn, session, request, deepcopy(result or GOOD))
            return completion.snapshot(conn, session.user["id"], request, session)

    def close(self):
        self.engine.release.set()
        for service in reversed(self.services):
            service.close()
            service.storage.close()


@pytest.fixture
def security(world):
    fixture = SecurityWorld(world)
    try:
        yield fixture
    finally:
        fixture.close()
