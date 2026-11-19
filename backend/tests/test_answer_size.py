"""Tests for nl2sql/answer_size.py: how many rows a question asks for."""

import pytest

from nl2sql.answer_size import DEFAULT_LIST_ROWS, AnswerSize, answer_size

CASES = [
    # Plural ranking with no number: the default list.
    ("What are the least popular movies?", "list", DEFAULT_LIST_ROWS),
    ("least popular movies", "list", DEFAULT_LIST_ROWS),
    ("Show me the most rented films", "list", DEFAULT_LIST_ROWS),
    ("Which customers have spent the most?", "list", DEFAULT_LIST_ROWS),
    ("Who are the top customers?", "list", DEFAULT_LIST_ROWS),
    ("Which customers spent the most money?", "list", DEFAULT_LIST_ROWS),
    ("cheapest films", "list", DEFAULT_LIST_ROWS),
    # Singular ranking: first place and its ties.
    ("What is the least popular movie?", "single", None),
    ("the least popular movie", "single", None),
    ("Who spent the most?", "single", None),
    ("Which actor has appeared in the most films?", "single", None),
    ("Which film was rented the most?", "single", None),
    ("What is the longest film?", "single", None),
    # An explicit number, in digits or words, anywhere it reads as a count.
    ("What are the top 3 film categories by total payment revenue?", "count", 3),
    ("Which two customers have rented the most films?", "count", 2),
    ("Show 25 customers", "count", 25),
    ("list the 50 least popular movies", "count", 50),
    ("top ten actors", "count", 10),
    ("What are the five cheapest films?", "count", 5),
    # Ranking within each group.
    ("What is the most popular film in each category?", "per_group", 1),
    ("Top 3 films per category", "per_group", 3),
    ("Which films are the most rented in each store?", "per_group", DEFAULT_LIST_ROWS),
    # Everything.
    ("List all film categories", "all", None),
    ("Show every customer in London", "all", None),
    # No ranking: filters and counts are not rankings, and numbers in them
    # are values, not row counts.
    ("How many films are there?", "open", None),
    ("Which countries have more than 30 customers?", "open", None),
    ("Which films are longer than 180 minutes?", "open", None),
    ("How many payments were made in March 2022?", "open", None),
    ("How many inventory copies does store 2 hold?", "open", None),
    ("For each store, how many rentals were made from its inventory?", "open", None),
    ("Which films rated PG-13 are less than 60 minutes?", "open", None),
]


@pytest.mark.parametrize(("question", "kind", "rows"), CASES)
def test_answer_size(question: str, kind: str, rows: int | None) -> None:
    assert answer_size(question) == AnswerSize(kind, rows)


def test_absurd_counts_are_ignored() -> None:
    """A number above the 1,000-row cap is not a row count."""
    assert answer_size("top 5000 films").kind != "count"


@pytest.mark.parametrize(
    ("size", "fragment"),
    [
        (AnswerSize("count", 5), "exactly 5 rows"),
        (AnswerSize("list", 10), "Return the top 10"),
        (AnswerSize("single"), "RANK() OVER"),
        (AnswerSize("per_group", 1), "PARTITION BY"),
        (AnswerSize("per_group", 3), "ranks 1 to 3"),
        (AnswerSize("all"), "do not add a LIMIT"),
    ],
)
def test_every_kind_but_open_has_an_instruction(
    size: AnswerSize, fragment: str
) -> None:
    assert fragment in size.instruction


def test_open_questions_add_nothing_to_the_prompt() -> None:
    assert AnswerSize("open").instruction is None


def test_single_answers_never_ask_for_limit_1() -> None:
    assert "Do not use LIMIT 1" in AnswerSize("single").instruction


@pytest.mark.parametrize(
    "question",
    [
        "How many different films have been rented at least once?",
        "Which customers rented at most 12 films?",
    ],
)
def test_at_least_and_at_most_are_filters_not_rankings(question: str) -> None:
    assert answer_size(question).kind == "open"


def test_single_instruction_separates_a_value_from_the_rows_that_reach_it() -> None:
    """'The highest replacement cost' wants MAX(); 'which film' wants ties."""
    text = AnswerSize("single").instruction
    assert "MAX or MIN" in text and "every tied row" in text


@pytest.mark.parametrize(
    "question",
    [
        "give me a list of the top spenders",
        "list the top spenders",
        "top spenders",
        "show me the biggest customers",
        "who are our best customers",
        "list customers by total spend",
        "show films ranked by number of rentals",
        "rank accounts by balance",
    ],
)
def test_lists_without_a_number_default_to_the_top_ten(question: str) -> None:
    assert answer_size(question) == AnswerSize("list", DEFAULT_LIST_ROWS)


@pytest.mark.parametrize(
    "question",
    [
        "show rentals by store",
        "How many films by category?",
        "list payments made by Mary Smith",
    ],
)
def test_groupings_and_filters_by_something_are_not_rankings(question: str) -> None:
    assert answer_size(question).kind == "open"


def test_lists_are_ordered_from_highest_unless_asking_for_the_lowest() -> None:
    text = AnswerSize("list", 10).instruction
    assert "from highest to lowest" in text and "lowest first only" in text


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "List the top 4 observatories and show the altitude for each.",
            AnswerSize("count", 4),
        ),
        (
            "List the top four observatories and display the elevation for each of them.",
            AnswerSize("count", 4),
        ),
        (
            "Show the top 4 turbines with their locations for each. Include units.",
            AnswerSize("count", 4),
        ),
        ("Show the top 4 turbines for each wind farm.", AnswerSize("per_group", 4)),
        (
            "Show the top four turbines for each of the regions.",
            AnswerSize("per_group", 4),
        ),
        ("For each of them, show the top four turbines.", AnswerSize("per_group", 4)),
        ("In every wind farm, show the highest turbine first.", AnswerSize("all")),
        (
            "Which turbine has the highest output in each wind farm?",
            AnswerSize("per_group", 1),
        ),
        ("List labs by average humidity, lowest to highest.", AnswerSize("all")),
        (
            "Show average speed per vehicle, highest average speed first.",
            AnswerSize("all"),
        ),
        ("Show building totals in descending order.", AnswerSize("all")),
        (
            "Rank labs by average temperature from highest to lowest.",
            AnswerSize("list", DEFAULT_LIST_ROWS),
        ),
        (
            "Show rates lowest to highest, then return the top 4 districts.",
            AnswerSize("count", 4),
        ),
        (
            "Use lowest bid first and return the bottom 3 per region.",
            AnswerSize("per_group", 3),
        ),
        ("Show top-rated telescopes.", AnswerSize("list", DEFAULT_LIST_ROWS)),
        (
            "Which top-rated telescopes fit in a backpack?",
            AnswerSize("list", DEFAULT_LIST_ROWS),
        ),
        ("Show the top-rated telescope.", AnswerSize("single")),
    ],
)
def test_ranked_selection_and_display_order(
    question: str, expected: AnswerSize
) -> None:
    assert answer_size(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "Show the shortest and longest delivery times.",
        "For each service lane, give the maximum and the minimum waiting time.",
        "List the earliest and latest observation dates, earliest first.",
    ],
)
def test_both_extremes_share_one_instruction(question: str) -> None:
    instruction = answer_size(question).instruction
    assert instruction and "MIN" in instruction and "MAX" in instruction
    assert (
        "both" in instruction
        and "LIMIT" not in instruction
        and "RANK()" not in instruction
    )


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "Compare the two hangars. Show the top three gliders in each.",
            AnswerSize("per_group", 3),
        ),
        (
            "Across the two festivals, give the top four entries from each.",
            AnswerSize("per_group", 4),
        ),
        (
            "Compare the two galleries. Give the top three artworks for each.",
            AnswerSize("per_group", 3),
        ),
        (
            "Compare the two orchestras. Which player has the highest score in each?",
            AnswerSize("per_group", 1),
        ),
        (
            "Across the two boxes, select the top 4 parts from each; include their weights.",
            AnswerSize("per_group", 4),
        ),
        (
            "Which three artists lead? Show their ticket totals for each.",
            AnswerSize("count", 3),
        ),
        (
            "Which four artists lead? Show the ticket total for each of them.",
            AnswerSize("count", 4),
        ),
        (
            "Which probes have the highest scores? Show the lowest reading from each.",
            AnswerSize("list", DEFAULT_LIST_ROWS),
        ),
        (
            "Compare the two schools. Show the top 3 science and arts teams in each.",
            AnswerSize("per_group", 3),
        ),
        (
            "List the top three crews, with their departure times for each.",
            AnswerSize("count", 3),
        ),
        (
            "List the top three panels and give the highest reading from each.",
            AnswerSize("count", 3),
        ),
        (
            "List the top four reservoirs, and display the number of sensors in each.",
            AnswerSize("count", 4),
        ),
        ("Show the top two classrooms in each building.", AnswerSize("per_group", 2)),
    ],
)
def test_terminal_each_in_selection_and_projection(
    question: str, expected: AnswerSize
) -> None:
    assert answer_size(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "Show only the nicknames of the five largest fictional warehouses by volume.",
        "List the busiest depots, names only.",
        "Which courier has the highest score? Return only the courier ID.",
        "For each route show the two fastest couriers. Output surname, then ID.",
    ],
)
def test_rank_uses_sort_fields_without_forcing_them_into_explicit_output(question):
    instruction = answer_size(question).instruction
    assert instruction and "only those fields in the requested order" in instruction
    assert "by default" in instruction and "ranking value" in instruction


def test_strict_count_per_group_uses_ordered_row_numbers():
    question = (
        "For each service tier show exactly the top three counters by activity. "
        "Break ties by counter ID in ascending order."
    )
    instruction = answer_size(question).instruction
    assert instruction and "ROW_NUMBER()" in instruction
    assert "specified tie-break fields and directions" in instruction
    assert "row numbers up to 3" in instruction
    assert "helper" in instruction


def test_secondary_display_order_does_not_break_explicit_ties_at_cutoff():
    question = (
        "Give the top three couriers per route, including all ties by speed. "
        "Within each tie display courier IDs in ascending order."
    )
    instruction = answer_size(question).instruction
    assert instruction and "RANK()" in instruction
    assert "all ties" in instruction and "after selection" in instruction


def test_global_count_preserves_explicit_cutoff_ties():
    question = "Show the top four research stations by snowfall, including all ties at the cutoff."
    instruction = answer_size(question).instruction
    assert instruction and "include all ties" in instruction
    assert "RANK()" in instruction and "ranks <= 4" in instruction
    assert "exactly" not in instruction


@pytest.mark.parametrize(
    ("question", "kind", "rows", "peers"),
    [
        (
            "List the busiest depots, including all ties at the cutoff.",
            "list",
            10,
            "cutoff",
        ),
        ("Show the top four depots, including all ties.", "count", 4, "cutoff"),
        (
            "Rank depots by total shipments. Include every tied entry.",
            "list",
            10,
            "cutoff",
        ),
        ("Give the five busiest depots. Break ties by depot ID.", "count", 5, None),
    ],
)
def test_global_limit_and_tie_inclusive_ordering_are_separate(
    question, kind, rows, peers
):
    size = answer_size(question)
    assert size == AnswerSize(kind, rows, peers)
    if peers:
        assert "RANK()" in size.instruction and f"ranks <= {rows}" in size.instruction
        assert "secondary display order after selection" in size.instruction
        assert f"LIMIT {rows}" not in size.instruction
    else:
        assert f"tie-breaks before LIMIT {rows}" in size.instruction


def test_all_records_is_distinct_from_all_peers_at_a_cutoff():
    assert answer_size(
        "Show all depots ranked by volume, including all ties."
    ) == AnswerSize("all")
    assert answer_size("Show every tied entry.") == AnswerSize("all")


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Show the two slowest riders in each race.", AnswerSize("per_group", 2)),
        ("Sort all entries fastest to slowest.", AnswerSize("all")),
        ("List couriers by travel time, fastest first.", AnswerSize("all")),
        ("Give the fastest and slowest travel times.", AnswerSize("extremes")),
    ],
)
def test_speed_ranking_and_display_order(question, expected):
    assert answer_size(question) == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "Which workshops had the lowest delay? Include ties.",
            AnswerSize("single", 1, "cutoff"),
        ),
        (
            "Name every orchard with the highest apple yield.",
            AnswerSize("single", 1, "cutoff"),
        ),
        ("Which teams share the lead?", AnswerSize("single", 1, "cutoff")),
        (
            "List the top three scores including ties. Within each tie sort by name.",
            AnswerSize("count", 3, "cutoff"),
        ),
        (
            "List the top two distinct finish times, including ties.",
            AnswerSize("count", 2, "distinct"),
        ),
        (
            "For each league, list the top two distinct score levels, including ties.",
            AnswerSize("per_group", 2, "distinct"),
        ),
        (
            "What are the top two different deposit amounts? Include ties.",
            AnswerSize("count", 2, "distinct"),
        ),
        (
            "For each pond, find all sensors with the lowest reading.",
            AnswerSize("per_group", 1, "cutoff"),
        ),
    ],
)
def test_explicit_peer_membership(question, expected):
    assert answer_size(question) == expected
    if expected.peers == "distinct":
        assert "DENSE_RANK()" in expected.instruction


@pytest.mark.parametrize(
    "question",
    [
        "Show exactly the top two suburbs by mileage, including ties.",
        "Give the four longest intervals. Do not include ties.",
        "List all teams ordered by wins including ties.",
        "Return top 3 designers by awards. Break ties by name.",
        "Which teams are not tied for first place?",
        "Show two ties from the apparel department.",
    ],
)
def test_plain_ordering_fixed_counts_and_nonrank_uses_do_not_expand(question):
    assert answer_size(question).peers is None
