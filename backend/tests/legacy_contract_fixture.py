"""Pure HTTP/query tests keep their existing schema/provider/cache test seams.

Real durable admission, process fencing and current DB authorization are tested
separately by test_p07_security_*; this adapter is never imported by production.
"""

import json

from fastapi.responses import JSONResponse

import main


class PureLegacy:
    def legacy(self, session, question, model):
        result = main.workspace_query(question, model, session, main.app.state.settings)
        if isinstance(result, JSONResponse):
            return json.loads(result.body), result.status_code
        return result, 200


def install(monkeypatch):
    monkeypatch.setitem(
        main.app.dependency_overrides, main.get_analysis, lambda: PureLegacy()
    )
