"""Closed HTTP doorway; every operation is server-owned and explicitly invoked."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from context_notes import rules
from context_notes.contracts import NoteCreate, NotePatch, NoteSelection
from context_notes.policy import ContextNotesPolicy
from context_notes.service import ContextNotes
from workspace.dependencies import Service, Session, perform
from workspace.errors import WorkspaceError

router = APIRouter(prefix="/api/v1/me/context-notes", tags=["private saved context"])


def invoke(request, session, workspace, action, *, note_id=None, body=None):
    if request.query_params:
        raise WorkspaceError("invalid_request", 422)
    if note_id is not None:
        try:
            rules.identifier(note_id)
        except ValueError:
            raise WorkspaceError("invalid_request", 422) from None
    try:
        result, status = ContextNotes(
            workspace,
            getattr(request.app.state, "context_notes_policy", ContextNotesPolicy()),
        ).perform(session, action, note_id=note_id, body=body)
        return JSONResponse(result, status_code=status)
    except (ValueError, KeyError, TypeError, UnicodeError, OverflowError):
        raise WorkspaceError("service_unavailable", 503) from None


@router.get("")
def listing(request: Request, session: Session, workspace: Service):
    return perform(lambda: invoke(request, session, workspace, "listing"))


@router.get("/{note_id}")
def detail(note_id: str, request: Request, session: Session, workspace: Service):
    return perform(
        lambda: invoke(request, session, workspace, "detail", note_id=note_id)
    )


@router.post("")
def create(body: NoteCreate, request: Request, session: Session, workspace: Service):
    return perform(lambda: invoke(request, session, workspace, "create", body=body))


@router.patch("/{note_id}")
def patch(
    note_id: str,
    body: NotePatch,
    request: Request,
    session: Session,
    workspace: Service,
):
    return perform(
        lambda: invoke(request, session, workspace, "patch", note_id=note_id, body=body)
    )


@router.post("/{note_id}/forget")
def forget(
    note_id: str,
    body: NoteSelection,
    request: Request,
    session: Session,
    workspace: Service,
):
    return perform(
        lambda: invoke(
            request, session, workspace, "forget", note_id=note_id, body=body
        )
    )


@router.post("/{note_id}/prepare")
def prepare(
    note_id: str,
    body: NoteSelection,
    request: Request,
    session: Session,
    workspace: Service,
):
    return perform(
        lambda: invoke(
            request, session, workspace, "prepare", note_id=note_id, body=body
        )
    )
