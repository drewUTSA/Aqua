"""An employee can review supplied cash terms in a private chat before calculating."""

import re

from bank_demo.calculations import CalculationRequest, calculate
from bank_demo.source import SyntheticReportSource
from workspace.database import one

CONFIRM = "Confirm cash comparison for "
CASH = r"(?:available (?:cash|liquidity|funds)|cash(?: (?:available|on hand))?|funds on hand|liquidity on hand)"
OUT = r"(?:(?:forecast(?:ed)?|expected|projected|net|outgoing|scheduled)\s+)*(?:outflows?|payments?|disbursements?|payables?)"
COMPARISON = re.compile(
    r"\b(?:cover(?:age|ed)?|compare|comparison|enough|sufficient|short(?:fall)?|surplus|cushion|difference|left over|leftover|meet|gap|headroom)\b",
    re.I,
)
OTHER_SOURCE = re.compile(
    r"\b(?:reports?|snapshot|database|dataset|portfolio|transactions?|records?|table|rows?|branches|rank|group by|aggregate|average|chart|plot|graph|historical|retrieve|look up|look it up|pull|from the bank|regulatory|regulation|regulator|official|filing|lcr|approve|authorize|execute|transfer|wire|send money|move funds|pay the|credit line|customer quote)\b",
    re.I,
)
NUMBER = re.compile(
    r"(?<![\w.])(?:[1-9][0-9]{0,2}(?:,[0-9]{3})+|0|[1-9][0-9]*)(?:\.[0-9]{1,2})?(?![\w]|[.,][0-9])"
)
USD = r"(?:USD|US dollars?|U\.S\. dollars?|US\$)"
MONEY = rf"(?:{USD}\s*\$?\s*)?\$?\s*#(?:\s*{USD})?"
BETWEEN = r"(?:\s+(?:is|of|are|was|were|comes? to|total(?:s|ed)?|equals?|stands? at|at|amounts? to|will be))?\s*[:=]?\s*"
AFTER = r"\s*(?:(?:of|in|as|for|is|are|was|were)\s+)?(?:the\s+)?"
WINDOWS = {
    "day": r"today|tomorrow|yesterday|tonight|daily|day|monday|tuesday|wednesday|thursday|friday|saturday|sunday",
    "month": r"monthly|month|january|february|march|april|may|june|july|august|september|october|november|december",
    "quarter": r"quarterly|quarter",
    "year": r"annually|annual|yearly|year",
}
TIME = re.compile(
    r"\b(?:(?:this|last|next|current|previous|prior|same|the)\s+)?(?:"
    + "|".join(WINDOWS.values())
    + r")\b",
    re.I,
)
WINDOW_HINT = "Which single day, month, quarter or year do both the available cash and the projected outflows cover? Please give both USD figures for that same window."
AMOUNT_HINT = "Please label the available cash amount and the projected outflows amount in USD for the same period. Which figure goes with each?"
CURRENCY_HINT = "What are the verified USD amounts for available cash and projected outflows for the same period?"


def _window(text):
    text = re.sub(r"\bmay (?=we |i |you |be |not )", "", text)
    labels = {match.group().removeprefix("the ") for match in TIME.finditer(text)}
    if len(labels) != 1 or re.search(
        r"\b(?:week(?:s|ly)?|days|months|years|quarters|ytd|periods|different|another period|prior period|next period)\b",
        text,
    ):
        return None
    label = labels.pop()
    word = label.split()[-1]
    period = next(
        key for key, pattern in WINDOWS.items() if re.fullmatch(pattern, word)
    )
    return period, label


def _label(text, match):
    """Match a local label on either side, without crossing another operand."""
    before = text[: match.start()]
    after = text[match.end() :]
    marker = before + "#" + after
    names = set()
    for key, noun in (("cash", CASH), ("outflows", OUT)):
        if re.search(rf"\b{noun}\b{BETWEEN}{MONEY}", marker, re.I) or re.search(
            rf"{MONEY}{AFTER}{noun}\b", marker, re.I
        ):
            names.add(key)
    return names.pop() if len(names) == 1 else None


def _terms(question):
    """Return no route, a value-free clarification, or two uniquely labelled terms."""
    from mcp_demo.finance import FinanceDenied, money

    text = " ".join(question.lower().split())
    if not (
        re.search(rf"\b{CASH}\b", text)
        and re.search(rf"\b{OUT}\b", text)
        and COMPARISON.search(text)
        and re.search(r"\d", text)
    ) or OTHER_SOURCE.search(text):
        return None
    amounts = list(NUMBER.finditer(text))
    if not re.search(rf"\b{USD}|\$", text, re.I) or re.search(
        r"[€£¥₹₩₽]|(?:\b(?:eur|gbp|cad|aud|jpy|cny|chf|mxn|canadian|australian|euros?|pounds?|pesos?|yen|yuan)\b)|(?<![a-z])[ac]\$",
        text,
    ):
        return CURRENCY_HINT
    window = _window(text)
    if window is None:
        return WINDOW_HINT
    if re.search(
        r"[+−–()#%]|\s-\s*\d|-\s*(?:usd|\$|\d)|\b(?:minus|negative|overdraft|overdrawn|below zero|million|billion|thousand|cents|double|triple|multiply|subtract|instead of|superseded|revised from)\b",
        text,
    ):
        return AMOUNT_HINT
    if len(amounts) == 1:
        known = _label(text, amounts[0])
        if known == "cash":
            return "What are the projected outflows in USD for the same period as the available cash?"
        if known == "outflows":
            return "How much cash is available in USD for the same period as those projected outflows?"
    if len(amounts) != 2:
        return AMOUNT_HINT
    shared_usd = re.search(
        r"\b(?:both|all) (?:amounts |figures |values )?(?:(?:are in|are|in) )?(?:usd|us dollars)\b|\busd (?:worksheet|figures|amounts|cash worksheet)\b",
        text,
    )
    roles = {}
    for match in amounts:
        # An adjacent three-letter unit can qualify even a shared "both USD"
        # preface. Only familiar English connectors and the supported unit
        # may sit beside an operand; an unknown code needs verification.
        preceding = re.search(r"\b([a-z]{3})\s*\$?\s*$", text[: match.start()])
        following = re.match(r"\s*([a-z]{3})\b", text[match.end() :])
        if any(
            word
            and word.group(1)
            not in {
                "usd",
                "and",
                "are",
                "was",
                "had",
                "has",
                "for",
                "the",
                "our",
                "net",
                "can",
                "per",
            }
            for word in (preceding, following)
        ):
            return CURRENCY_HINT
        if not shared_usd and not (
            re.search(rf"\b{USD}\s*\$?\s*$", text[: match.start()], re.I)
            or re.match(rf"\s*{USD}\b", text[match.end() :], re.I)
        ):
            return CURRENCY_HINT
        role = _label(text, match)
        if role is None or role in roles:
            return AMOUNT_HINT
        try:
            roles[role] = format(
                money(match.group().replace(",", ""), positive=role == "outflows"),
                ".2f",
            )
        except FinanceDenied:
            return AMOUNT_HINT
    return {
        "cash": roles["cash"],
        "outflows": roles["outflows"],
        "period": window[0],
        "window": window[1],
    }


def _answer(message, **extra):
    return {
        "status": "success",
        "message": message,
        "sql": "",
        "model": "",
        "tables": [],
        "visualizations": [],
        "kpis": [],
        "error": None,
        **extra,
    }


def _confirmation(terms):
    return (
        f"{CONFIRM}{terms['window']} using USD {terms['cash']} available cash "
        f"and USD {terms['outflows']} projected outflows."
    )


def saved_cash_response(conn, job, sequence, question, policy):
    """The latest saved offer, current account and grant bind a confirmed calculation."""
    confirm = question.startswith(CONFIRM)
    if not policy.enabled:
        return (
            _answer("There is no available cash calculation to confirm in this chat.")
            if confirm
            else None
        )
    terms = None if confirm else _terms(question)
    if not confirm and terms is None:
        return None
    from mcp_demo import web
    from mcp_demo.protocol import actor_for

    persona = policy.for_account(str(job["user_id"]))
    scope = actor_for(persona).scope
    if (
        "public_education" not in scope.tool_ids
        or "public_finance" not in scope.object_ids
    ):
        return _answer("This account does not have access to the banking calculator.")
    if not confirm:
        if isinstance(terms, str):
            return _answer(terms)
        confirmation = _confirmation(terms)
        return _answer(
            f"For {terms['window']}, I read USD {terms['cash']} as available cash and "
            f"USD {terms['outflows']} as projected outflows. Confirm these terms to calculate your surplus or shortfall.",
            bank_cash_review={
                "confirmation": confirmation,
                "source_revision": web.SOURCE_REVISION,
            },
        )
    previous = one(
        conn,
        """
        SELECT original.content, result.response->'bank_cash_review' AS offer
        FROM app.analysis_requests current_request
        JOIN app.messages reply ON reply.user_id=current_request.user_id AND reply.chat_id=current_request.chat_id
            AND reply.sequence=%s AND reply.role='aqua' AND reply.status='complete'
        JOIN app.analysis_requests old ON old.user_id=reply.user_id AND old.chat_id=reply.chat_id
            AND old.reply_message_id=reply.id AND old.state='complete' AND old.dataset_key=%s AND old.grant_version=%s
        JOIN app.messages original ON original.user_id=old.user_id AND original.chat_id=old.chat_id AND original.id=old.input_message_id
        JOIN app.visual_results result ON result.user_id=old.user_id AND result.chat_id=old.chat_id AND result.request_id=old.id
        WHERE current_request.user_id=%s AND current_request.id=%s
        """,
        (
            sequence - 1,
            job["dataset_key"],
            job["grant_version"],
            job["user_id"],
            job["request_id"],
        ),
    )
    terms = _terms(previous["content"]) if previous and previous["offer"] else None
    if (
        not isinstance(terms, dict)
        or previous["offer"]
        != {"confirmation": question, "source_revision": web.SOURCE_REVISION}
        or _confirmation(terms) != question
    ):
        return _answer(
            "Please submit the available cash, projected outflows and shared period again to review the current terms in this chat."
        )
    request = CalculationRequest(
        schemaVersion=1,
        confirmed=True,
        expected_source_revision=web.SOURCE_REVISION,
        operation="liquidity_coverage",
        currency="USD",
        parameters={
            "available_liquidity_usd": terms["cash"],
            "projected_outflows_usd": terms["outflows"],
            "period": terms["period"],
        },
    )
    payload = calculate(request, SyntheticReportSource(persona), lambda: None)
    if "calculation" not in payload:
        return _answer(AMOUNT_HINT)
    calculation = payload["calculation"]
    return _answer(
        f"{calculation['explanation']} This uses your confirmed USD figures for {terms['window']}.",
        bank_calculation={
            key: calculation[key]
            for key in (
                "operation",
                "currency",
                "inputs",
                "result",
                "source",
                "sourceRevision",
            )
        },
    )
