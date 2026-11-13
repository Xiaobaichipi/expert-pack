from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from expert_pack.pipeline import BatchItem, BatchPipeline, PipelineContext, Stage


class PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_stages_run_in_order(self) -> None:
        order: list[str] = []

        def make(name: str):
            def run(_ctx, item):
                order.append(f"{item.id}:{name}")
                item.data[name] = True
            return run

        pipeline = BatchPipeline([Stage("a", make("a")), Stage("b", make("b"))])
        report = pipeline.run([BatchItem(id="x", payload={})], PipelineContext(run_id="r"))
        self.assertEqual(order, ["x:a", "x:b"])
        self.assertEqual(report.done[0].completed, ["a", "b"])

    def test_failure_is_isolated_and_checkpointed(self) -> None:
        def explode(_ctx, item):
            if item.id == "bad":
                raise RuntimeError("boom")

        def after(_ctx, item):
            item.data["after"] = True

        pipeline = BatchPipeline(
            [Stage("solve", explode, on_error="skip"), Stage("record", after)],
            state_dir=self.root,
        )
        report = pipeline.run(
            [BatchItem(id="good"), BatchItem(id="bad")], PipelineContext(run_id="r")
        )
        self.assertEqual(sorted(item.id for item in report.done), ["good"])
        self.assertEqual([item.id for item in report.failed], ["bad"])
        self.assertIn("solve: RuntimeError: boom", report.failed[0].error)
        self.assertNotIn("record", report.failed[0].completed)

    def test_resume_skips_completed_items(self) -> None:
        calls: list[str] = []

        def count(_ctx, item):
            calls.append(item.id)

        pipeline = BatchPipeline([Stage("count", count)], state_dir=self.root)
        items = [BatchItem(id="one"), BatchItem(id="two")]
        first = pipeline.run(items, PipelineContext(run_id="r"))
        self.assertEqual(len(first.done), 2)
        self.assertEqual(calls, ["one", "two"])

        calls.clear()
        second = pipeline.run(
            [BatchItem(id="one"), BatchItem(id="two"), BatchItem(id="three")],
            PipelineContext(run_id="r"),
            resume=True,
        )
        self.assertEqual(calls, ["three"])
        self.assertEqual(len(second.resumed), 2)
        self.assertEqual(sorted(item.id for item in second.done), ["one", "three", "two"])

    def test_resume_continues_a_partial_item(self) -> None:
        steps: list[str] = []
        failures = {"count": 0}

        def first(_ctx, item):
            steps.append("first")
            if failures["count"] == 0:
                failures["count"] = 1
                raise RuntimeError("stop here")

        def second(_ctx, item):
            steps.append("second")

        pipeline = BatchPipeline(
            [Stage("first", first, on_error="continue"), Stage("second", second)],
            state_dir=self.root,
        )
        report = pipeline.run([BatchItem(id="x")], PipelineContext(run_id="r"))
        # The record step ran, but the item is still reported failed: one stage
        # did not complete successfully.
        self.assertEqual(report.failed[0].completed, ["second"])
        self.assertIn("first: RuntimeError", report.failed[0].error)

        steps.clear()
        resumed = pipeline.run([BatchItem(id="x")], PipelineContext(run_id="r"), resume=True)
        self.assertEqual(steps, ["first"])
        self.assertEqual(resumed.done[0].completed, ["second", "first"])
        self.assertIsNone(resumed.done[0].error)

    def test_duplicate_stage_ids_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BatchPipeline([Stage("a", lambda c, i: i), Stage("a", lambda c, i: i)])

    def test_empty_pipeline_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BatchPipeline([])


if __name__ == "__main__":
    unittest.main()
