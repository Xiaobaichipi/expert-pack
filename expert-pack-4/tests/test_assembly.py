from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from expert_pack.assembly import build_runtime, inspect_assembly, load_assembly
from expert_pack.errors import AssemblyError, ContractError, VacancyError
from expert_pack.slots import SlotRegistry


def write_assembly(directory: Path, bindings: list[dict], agent: dict | None = None) -> Path:
    path = directory / "assembly.json"
    path.write_text(
        json.dumps({"version": 1, "name": "test", "agent": agent or {}, "bindings": bindings}),
        encoding="utf-8",
    )
    return path


class SlotsTest(unittest.TestCase):
    def test_default_report_has_one_required_stub(self) -> None:
        report = SlotRegistry().describe()
        self.assertFalse(report.ok)
        state = report.state("model")
        self.assertEqual(state.status, "builtin")
        self.assertEqual(state.quality, "stub")
        self.assertIn("required slot holds a stub", " ".join(report.strict_problems()))

    def test_vacancies_lists_open_and_vacant(self) -> None:
        report = SlotRegistry().describe()
        ids = {state.spec.id for state in report.vacancies}
        self.assertEqual(ids, {"tools", "skills"})

    def test_table_and_json_agree(self) -> None:
        report = SlotRegistry().describe()
        payload = json.loads(report.to_json())
        self.assertEqual(len(payload["slots"]), len(report.states))
        self.assertIn("model", report.table())

    def test_duplicate_single_binding_is_rejected(self) -> None:
        from expert_pack.slots import Binding

        registry = SlotRegistry()
        registry.bind(Binding("model", "builtin", "unbound"))
        with self.assertRaises(Exception):
            registry.bind(Binding("model", "builtin", "scripted", config={"planner": "demo"}))

    def test_unknown_slot_is_rejected(self) -> None:
        from expert_pack.slots import Binding

        with self.assertRaises(Exception):
            SlotRegistry().bind(Binding("nope", "builtin", "unbound"))


class AssemblyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_offline_scripted_assembly_resolves(self) -> None:
        path = write_assembly(
            self.root,
            [
                {"slot": "model", "type": "builtin", "target": "scripted", "config": {"planner": "demo"}},
            ],
        )
        assembly, report = inspect_assembly(path)
        self.assertEqual(assembly.name, "test")
        self.assertTrue(report.ok, report.strict_problems())
        runtime = build_runtime(assembly, strict=True)
        try:
            self.assertEqual(runtime.model.name, "demo-planner")
            self.assertEqual(runtime.store.path.endswith(".sqlite3"), True)
        finally:
            runtime.close()

    def test_env_expansion(self) -> None:
        os.environ["EXPERT_PACK_TEST_BETA"] = "1.5"
        try:
            path = write_assembly(
                self.root,
                [
                    {
                        "slot": "policy",
                        "type": "builtin",
                        "target": "jitrl",
                        "config": {"beta": "${EXPERT_PACK_TEST_BETA}"},
                    }
                ],
            )
            _assembly, report = inspect_assembly(path)
            self.assertEqual(report.state("policy").status, "bound")
        finally:
            del os.environ["EXPERT_PACK_TEST_BETA"]

    def test_missing_env_is_an_error(self) -> None:
        path = write_assembly(
            self.root,
            [{"slot": "store", "type": "builtin", "target": "sqlite", "config": {"path": "${NOPE_MISSING}"}}],
        )
        with self.assertRaises(AssemblyError):
            load_assembly(path)

    def test_unknown_config_key_is_an_error(self) -> None:
        path = write_assembly(
            self.root,
            [{"slot": "policy", "type": "builtin", "target": "jitrl", "config": {"gammaa": 1}}],
        )
        _assembly, report = inspect_assembly(path)
        self.assertEqual(report.state("policy").status, "invalid")
        self.assertIn("unknown keys", " ".join(report.state("policy").problems))

    def test_unknown_agent_option_is_an_error(self) -> None:
        path = write_assembly(self.root, [], agent={"maxstep": 3})
        with self.assertRaises(AssemblyError):
            load_assembly(path)

    def test_bad_binding_shape_is_an_error(self) -> None:
        path = write_assembly(self.root, [{"slot": "model", "type": "telepathy", "target": "x"}])
        with self.assertRaises(AssemblyError):
            load_assembly(path)

    def test_strict_refuses_unbound_model(self) -> None:
        with self.assertRaises(VacancyError):
            build_runtime(None, strict=True)

    def test_contract_violation_is_reported(self) -> None:
        class Broken:
            name = "broken"
            # no complete()

        path = write_assembly(self.root, [])
        _assembly, report = inspect_assembly(path)
        with self.assertRaises(ContractError):
            build_runtime(_assembly, overrides={"model": Broken()})

    def test_module_binding_with_config(self) -> None:
        path = write_assembly(
            self.root,
            [
                {
                    "slot": "model",
                    "type": "module",
                    "target": "expert_pack.adapters.model_scripted:ScriptedModel",
                    "config": {"responses": ["{}"]},
                }
            ],
        )
        _assembly, report = inspect_assembly(path)
        self.assertEqual(report.state("model").status, "bound")

    def test_skills_slot_loads_builtin_skills(self) -> None:
        path = write_assembly(
            self.root,
            [
                {"slot": "model", "type": "builtin", "target": "scripted", "config": {"planner": "demo"}},
                {
                    "slot": "skills",
                    "type": "skill_dir",
                    "target": str(Path(__file__).resolve().parent.parent / "expert_pack" / "builtin" / "skills"),
                },
            ],
        )
        assembly, report = inspect_assembly(path)
        runtime = build_runtime(assembly)
        try:
            names = sorted(skill.spec.name for skill in runtime.skills)
            self.assertEqual(names, ["grounded-answer", "verify-arithmetic"])
            ids = {item["action_id"] for item in runtime.agent.available_actions()}
            self.assertIn("skill:verify-arithmetic", ids)
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
