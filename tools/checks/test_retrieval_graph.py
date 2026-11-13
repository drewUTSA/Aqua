"""Offline retrieval relationship checks: synthetic metadata, no DB or provider."""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from nl2sql.retrieval.graph import join_graph, select_tables  # noqa: E402


def tables(edges, extra=()):
    names = set(extra) | {name for edge in edges for name in edge}
    return {
        name: SimpleNamespace(
            references=frozenset(b for a, b in edges if a == name), columns=()
        )
        for name in names
    }


class RetrievalGraphTests(unittest.TestCase):
    def test_existing_one_step_bridges_remain_in_both_directions(self):
        data = tables([("film_category", "film"), ("film_category", "category")])
        self.assertEqual(select_tables(data, ["film", "category"], []), set(data))
        self.assertEqual(join_graph(data)["film"], frozenset({"film_category"}))

    def test_multihop_joins_supply_intermediate_tables_the_model_needs(self):
        data = tables(
            [("payment", "rental"), ("rental", "inventory"), ("inventory", "film")],
            ["unrelated"],
        )
        self.assertEqual(
            select_tables(data, ["payment", "film"], []),
            {"payment", "rental", "inventory", "film"},
        )

    def test_partition_column_links_are_retained_without_unknown_relations(self):
        data = tables([], ["payment", "customer"])
        data["payment"].columns = tuple(
            SimpleNamespace(name=name)
            for name in ("customer_id", "missing_id", "payment_id")
        )
        data["customer"].references = frozenset({"secret_application_table"})
        self.assertEqual(
            select_tables(data, ["PAYMENT"], ["customer", "secret_application_table"]),
            {"payment", "customer"},
        )
        self.assertEqual(set(join_graph(data)), set(data))
        self.assertNotIn(
            "secret_application_table", set().union(*join_graph(data).values())
        )

    def test_disconnected_tables_do_not_invent_relationships(self):
        data = tables([("a", "b"), ("x", "y")])
        self.assertEqual(select_tables(data, ["a", "x"], []), {"a", "x"})

    def test_equal_paths_are_deterministic_across_catalog_order(self):
        data = tables(
            [("a", "b"), ("b", "d"), ("d", "z"), ("a", "c"), ("c", "e"), ("e", "z")]
        )
        expected = {"a", "b", "d", "z"}
        self.assertEqual(select_tables(data, ["z", "a"], []), expected)
        self.assertEqual(
            select_tables(dict(reversed(list(data.items()))), ["a", "z"], []), expected
        )

    def test_cycles_and_hop_limit_keep_context_bounded(self):
        data = tables([(f"t{i}", f"t{i+1}") for i in range(12)] + [("t3", "t1")])
        self.assertEqual(select_tables(data, ["t0", "t12"], []), {"t0", "t12"})
        self.assertLessEqual(len(select_tables(data, ["t0", "t4"], [])), 10)

    def test_graph_build_visits_each_column_sequence_once(self):
        visits = []

        class Columns:
            def __iter__(self):
                visits.append(1)
                return iter(())

        data = tables([(f"t{i}", f"t{i+1}") for i in range(255)])
        for item in data.values():
            item.columns = Columns()
        select_tables(data, ["t0", "t3"], [])
        self.assertEqual(len(visits), len(data))

    def test_no_catalog_mutation_or_cross_call_state(self):
        data = tables([("a", "b"), ("b", "c"), ("c", "z")])
        before = {name: item.references for name, item in data.items()}
        self.assertEqual(select_tables(data, ["a", "z"], []), set(data))
        self.assertEqual(
            select_tables(tables([], ["owner_two"]), ["a", "z"], []), set()
        )
        self.assertEqual({name: item.references for name, item in data.items()}, before)

    def test_added_join_context_has_a_global_eight_table_cap(self):
        edges = []
        for index in range(6):
            edges += [
                ("root", f"a{index}"),
                (f"a{index}", f"b{index}"),
                (f"b{index}", f"leaf{index}"),
            ]
        data = tables(edges)
        selected = {"root", *(f"leaf{index}" for index in range(6))}
        result = select_tables(data, selected, [])
        self.assertTrue(selected <= result <= set(data))
        self.assertLessEqual(len(result - selected), 8)

    def test_more_than_twelve_anchors_keeps_legacy_context_without_path_expansion(self):
        edges = []
        for index in range(13):
            edges += [
                ("root", f"a{index}"),
                (f"a{index}", f"b{index}"),
                (f"b{index}", f"leaf{index}"),
            ]
        selected = {"root", *(f"leaf{index}" for index in range(13))}
        self.assertEqual(select_tables(tables(edges), selected, []), selected)


if __name__ == "__main__":
    unittest.main()
