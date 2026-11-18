"""Tests for nl2sql/display.py. The comments are the real ones from
db/financial/02_load.sql, so these also check that every bank code
comment parses."""

from nl2sql.display import Display, code_meanings, display_for, header
from nl2sql.schema import Column, Schema, Table

TRANS_TYPE = (
    "PRIJEM = credit (money in), VYDAJ = debit (money out), VYBER = cash withdrawal."
)
OPERATION = (
    "VYBER KARTOU = card withdrawal, VKLAD = cash deposit, PREVOD Z UCTU = transfer in from"
    " another bank, VYBER = cash withdrawal, PREVOD NA UCET = transfer out to another bank."
)
LOAN_STATUS = (
    "A = finished, paid off; B = finished, not paid; C = running, payments on time;"
    " D = running, client in debt."
)
K_SYMBOL = (
    "Purpose: POJISTNE = insurance, SLUZBY = statement fee, UROK = interest credited,"
    " SANKC. UROK = penalty interest on a negative balance, SIPO = household bills,"
    " DUCHOD = pension, UVER = loan payment; empty or NULL = not given."
)
FREQUENCY = (
    "Statement frequency: POPLATEK MESICNE = monthly, POPLATEK TYDNE = weekly,"
    " POPLATEK PO OBRATU = after each transaction."
)


def table(name: str, columns: list[Column], comment: str = "") -> Table:
    return Table(name, tuple(columns), (), frozenset(), comment)


BANK = Schema(
    tables={
        "trans": table(
            "trans",
            [
                Column("type", "text", True, comment=TRANS_TYPE),
                Column("operation", "text", False, comment=OPERATION),
                Column("k_symbol", "text", False, comment=K_SYMBOL),
                Column(
                    "balance",
                    "integer",
                    True,
                    comment="Account balance after the transaction.",
                ),
                Column("date", "date", True),
            ],
            comment="Account transactions, 1993 to 1998. Amounts in Czech crowns (CZK).",
        ),
        "loan": table(
            "loan",
            [
                Column("status", "text", True, comment=LOAN_STATUS),
                Column("date", "date", True),
            ],
            comment="Loans granted to accounts. Amounts in Czech crowns (CZK).",
        ),
        "account": table(
            "account",
            [
                Column("frequency", "text", True, comment=FREQUENCY),
                Column("date", "date", True, comment="Date the account was opened."),
            ],
        ),
        "district": table(
            "district", [Column("a11", "integer", True, comment="Average salary.")]
        ),
    }
)


def test_codes_with_commas_in_their_meanings_parse() -> None:
    assert code_meanings(LOAN_STATUS) == {
        "A": "Finished, paid off",
        "B": "Finished, not paid",
        "C": "Running, payments on time",
        "D": "Running, client in debt",
    }


def test_multi_word_and_dotted_codes_parse_and_descriptions_are_skipped() -> None:
    meanings = code_meanings(K_SYMBOL)
    assert meanings["SANKC. UROK"] == "Penalty interest on a negative balance"
    assert meanings["UVER"] == "Loan payment"
    assert "empty or NULL" not in meanings  # lower case: a description, not a code
    assert code_meanings(OPERATION)["PREVOD Z UCTU"] == "Transfer in from another bank"


def test_values_are_translated_in_their_own_column() -> None:
    display = display_for(BANK)
    assert display.value("type", "VYDAJ") == "Debit (money out)"
    assert display.value("status", "B") == "Finished, not paid"
    assert display.value("frequency", "POPLATEK TYDNE") == "Weekly"


def test_renamed_columns_still_translate_but_single_letters_do_not() -> None:
    display = display_for(BANK)
    assert display.value("transaction_type", "PRIJEM") == "Credit (money in)"
    assert display.value("grade", "B") == "B"


def test_other_values_are_left_alone() -> None:
    display = display_for(BANK)
    assert display.value("type", "gold") == "gold"
    assert display.value("status", 3) == 3
    assert display.value("k_symbol", None) is None


def test_headers_come_from_short_comments_only() -> None:
    labels = display_for(BANK).column_labels
    assert labels["a11"] == "Average salary"
    assert labels["frequency"] == "Statement frequency"
    assert labels["k_symbol"] == "Purpose"
    assert "type" not in labels and "status" not in labels  # bare code lists
    assert "date" not in labels  # only one of the three date columns has a comment
    assert header("x" * 60) is None


def test_currency_comes_from_table_comments() -> None:
    assert display_for(BANK).currency == "CZK"
    mixed = Schema(
        tables={
            "a": table("a", [], comment="Amounts in Czech crowns (CZK)."),
            "b": table("b", [], comment="Amounts in euros (EUR)."),
        }
    )
    assert display_for(mixed).currency is None


def test_a_database_without_comments_displays_as_is() -> None:
    plain = Schema(tables={"film": table("film", [Column("rating", "text", False)])})
    assert display_for(plain) == Display()


def test_rows_are_translated_cell_by_cell() -> None:
    rows = display_for(BANK).rows(["type", "amount"], [("VYDAJ", 100), ("PRIJEM", 50)])
    assert rows == [("Debit (money out)", 100), ("Credit (money in)", 50)]


def result(question, sql, columns, values, schema=BANK):
    from nl2sql.pipeline import Answer
    from nl2sql.response import to_response

    body = to_response(
        Answer(question=question, sql=sql, columns=columns, rows=[tuple(values)]),
        display_for(schema),
    )
    return list(body["tables"][0]["rows"][0].values()), body["message"]


def test_aliases_and_explicit_stored_code_share_one_projected_representation():
    sql = "SELECT t.type AS ledger_kind, COUNT(*) AS entries FROM public.trans AS t GROUP BY t.type"
    args = (sql, ["ledger_kind", "entries"], ["PRIJEM", 3])
    for question in (
        "Display the stored transaction type code and the entry count.",
        "Make a bar chart of entries by the original stored type code.",
        "Return ledger_kind as a raw code, and the entry count.",
    ):
        values, message = result(question, *args)
        assert values == ["PRIJEM", 3] and "PRIJEM" in message
    assert result("Show the transaction types and entry counts.", *args)[0] == [
        "Credit (money in)",
        3,
    ]


def test_explicit_filter_codes_do_not_override_an_output_request_for_labels():
    sql = "SELECT status AS loan_state FROM loan WHERE status='B'"
    for question in (
        "Filter on status code B. Show the loan state label.",
        "Show loan state for loans whose status code is B.",
    ):
        assert result(question, sql, ["loan_state"], ["B"])[0] == ["Finished, not paid"]


def test_mixed_independent_fields_record_exact_scope_and_do_not_depend_on_values():
    sql = "SELECT t.type AS category, a.frequency AS cadence FROM trans t JOIN account a ON a.account_id=t.account_id"
    for row, wanted in (
        (["VYDAJ", "POPLATEK TYDNE"], ["VYDAJ", "Weekly"]),
        ([None, "FUTURE"], [None, "FUTURE"]),
    ):
        values, _ = result(
            "Return transaction type code and a readable statement frequency.",
            sql,
            ["category", "cadence"],
            row,
        )
        assert values == wanted


def test_same_source_can_return_a_code_and_its_label_in_either_order():
    for aliases, values in (
        (["original_operation", "description"], ["VKLAD", "Cash deposit"]),
        (["description", "original_operation"], ["Cash deposit", "VKLAD"]),
    ):
        sql = f"SELECT operation AS {aliases[0]}, operation AS {aliases[1]} FROM trans"
        assert (
            result(
                "Show the stored operation code and a readable description.",
                sql,
                aliases,
                ["VKLAD", "VKLAD"],
            )[0]
            == values
        )


def test_display_never_substitutes_an_unrelated_column_literal_or_expression():
    columns = ["note", "type", "amount", "grade"]
    sql = "SELECT d.a11 AS note, 'PRIJEM' AS type, COALESCE(t.type, '') AS amount, 'B' AS grade FROM district d JOIN trans t ON TRUE"
    values = ["VYDAJ", "PRIJEM", "PRIJEM", "B"]
    assert result("Show the values.", sql, columns, values)[0] == values


def test_unknown_projection_scope_stays_raw():
    for sql in (
        "WITH s AS (SELECT type FROM trans) SELECT type FROM s",
        "SELECT type FROM trans UNION ALL SELECT 'PRIJEM'",
        "SELECT status FROM private.loan",
        "SELECT 'x' AS status, status FROM loan",
        "SELECT type FROM trans AS t JOIN trans AS t2 ON TRUE",
        "SELECT status FROM loan AS l(x, status)",
    ):
        assert result("Show the category.", sql, ["status"], ["VYDAJ"])[0] == ["VYDAJ"]


def test_output_binding_uses_the_actual_source_even_with_a_colliding_alias():
    sql = "SELECT t.operation AS type, t.type AS operation, l.status AS renamed FROM trans t JOIN loan l ON TRUE"
    values, _ = result(
        "Show readable categories.",
        sql,
        ["type", "operation", "renamed"],
        ["VKLAD", "PRIJEM", "B"],
    )
    assert values == ["Cash deposit", "Credit (money in)", "Finished, not paid"]


def test_table_qualifier_disambiguates_two_selected_type_fields():
    schema = Schema(
        {
            **BANK.tables,
            "disp": table(
                "disp", [Column("type", "text", True, comment="OWNER = account owner.")]
            ),
        }
    )
    sql = "SELECT t.type AS direction, d.type AS permission FROM trans t JOIN disp d ON TRUE"
    args = (sql, ["direction", "permission"], ["PRIJEM", "OWNER"], schema)
    assert result(
        "I need the transaction type code and the disposition type label.", *args
    )[0] == ["PRIJEM", "Account owner"]
    assert result("Return type code and labels.", *args)[0] == [
        "Credit (money in)",
        "Account owner",
    ]
    assert result("Show trans.type code and disp.type label.", *args)[0] == [
        "PRIJEM",
        "Account owner",
    ]


def test_negative_and_label_selections_do_not_activate_stored_codes():
    for question in (
        "Show labels instead of loan status codes.",
        "Do not show the status code. Show the readable loan status.",
        "Display the stored status label.",
        "Show the loan status, not the status code.",
    ):
        assert result(question, "SELECT status FROM loan", ["status"], ["B"])[0] == [
            "Finished, not paid"
        ]


def test_only_postgresql_identifier_case_and_returned_projection_positions_bind():
    sql = 'SELECT "A".status AS first, "a".status AS second FROM public.loan "A" JOIN public.loan "a" ON TRUE'
    assert result(
        "Return first as a stored code and a readable second.",
        sql,
        ["first", "second"],
        ["B", "A"],
    )[0] == ["B", "Finished, paid off"]
    assert result("Show a label.", 'SELECT "STATUS" FROM loan', ["STATUS"], ["B"])[
        0
    ] == ["B"]


def test_qualified_and_possessive_stored_code_requests():
    for question in ("Show loan.status code.", "Show status with its stored code."):
        assert result(question, "SELECT status FROM loan", ["status"], ["B"])[0] == [
            "B"
        ]
    assert result(
        "Show readable status for records with status code B.",
        "SELECT status FROM loan",
        ["status"],
        ["B"],
    )[0] == ["Finished, not paid"]


def test_grouping_or_sorting_by_a_stored_value_preserves_the_requested_label():
    args = (
        "SELECT operation AS description, COUNT(*) AS entries FROM trans GROUP BY operation ORDER BY operation NULLS LAST",
        ["description", "entries"],
        ["VKLAD", 4],
    )
    for question in (
        "For staff orientation, show the readable operation label and entry count for each operation. Include missing values and sort by the original operation.",
        "Return the operation label and count, ordering by original operation.",
        "Show the operation label and group by the stored operation.",
        "Show the readable operation label, using original operation for sorting.",
    ):
        assert result(question, *args)[0] == ["Cash deposit", 4]
