import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from adsharness.agents import AgentManager, parse_proposal, proposal_command, run_cli
from adsharness.documents import mask_config, restore_config
from test_adsharness import Fixture


def finished(manager, ident):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        job = manager.get(ident)
        if job["status"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("Operation did not finish")


class SourceTests(Fixture):
    def mcp(self):
        return next(i for i in self.catalog.inventory()["items"] if i["name"] == "docs")

    def test_config_reader_masks_secrets_and_reveals_original_on_request(self):
        ident = self.mcp()["id"]
        doc = self.catalog.document(ident)
        self.assertNotIn("SECRET_", doc["content"])
        self.assertTrue(doc["masked"])
        self.assertEqual(self.catalog.document(ident, reveal=True)["content"], (self.home / ".codex/config.toml").read_text())

    def test_masked_edit_preserves_secrets_comments_and_unknown_fields(self):
        path = self.home / ".codex/config.toml"
        path.write_text(path.read_text() + '\n# private comment\n')
        item = self.mcp()
        doc = self.catalog.document(item["id"])
        proposed = doc["content"].replace("enabled = false", "enabled = true")
        self.catalog.save_document(item["id"], doc["revision"], proposed)
        result = path.read_text()
        self.assertIn("SECRET_TOKEN", result)
        self.assertIn("SECRET_ARGUMENT", result)
        self.assertIn("# private comment", result)
        self.assertIn("enabled = true", result)
        self.assertEqual(len(list((self.home / "state/backups").glob("*.toml"))), 1)

    def test_configuration_syntax_and_marker_removal_are_rejected(self):
        item = self.mcp()
        doc = self.catalog.document(item["id"])
        with self.assertRaises(ValueError):
            self.catalog.save_document(item["id"], doc["revision"], "[broken", reveal=True)
        with self.assertRaises(ValueError):
            self.catalog.save_document(item["id"], doc["revision"], "model = 'replacement'")
        self.assertIn("SECRET_TOKEN", self.catalog.document(item["id"], reveal=True)["content"])

    def test_remote_credentials_do_not_enter_preview(self):
        item = next(i for i in self.catalog.inventory()["items"] if i["name"] == "remote")
        doc = self.catalog.document(item["id"])
        self.assertNotIn("SECRET_", doc["content"])
        self.assertIn("PROTECTED", doc["content"])

    def test_connection_urls_mask_credentials_for_all_schemes(self):
        for url in ("wss://user:private-value@example.invalid/mcp", "ws://example.invalid/?key=private-value",
                    "HTTPS://example.invalid/#private-value", "postgresql://user:private-value@example.invalid/db"):
            with self.subTest(scheme=url.split(":", 1)[0]):
                original = json.dumps({"url": url})
                masked, replacements = mask_config(original, ".json")
                self.assertNotIn("private-value", masked)
                self.assertEqual(restore_config(masked, replacements), original)

    def test_duplicate_json_keys_fail_closed(self):
        with self.assertRaises(ValueError):
            mask_config('{"env":{"TOKEN":"first","TOKEN":"second"}}', ".json")

    def test_shell_command_is_protected(self):
        original = '{"command":"TOKEN=private-value launch-server"}'
        masked, replacements = mask_config(original, ".json")
        self.assertNotIn("private-value", masked)
        self.assertEqual(restore_config(masked, replacements), original)

    def test_repeated_values_only_mask_sensitive_paths(self):
        original = '{"enabled": false, "name": "same", "env": {"FLAG": false, "TOKEN": "same", "NUMBER": -123, "EXPONENT": 1e6}}'
        masked, replacements = mask_config(original, ".json")
        parsed = json.loads(masked)
        self.assertIs(parsed["enabled"], False)
        self.assertEqual(parsed["name"], "same")
        self.assertNotIn("-123", masked)
        self.assertNotIn("1e6", masked)
        self.assertEqual(restore_config(masked, replacements), original)

    def test_protected_value_cannot_move_to_a_different_field(self):
        item = self.mcp()
        doc = self.catalog.document(item["id"])
        changed = doc["content"].replace("TOKEN =", "OTHER =")
        with self.assertRaises(ValueError):
            self.catalog.save_document(item["id"], doc["revision"], changed)

    def test_project_documents_are_excluded(self):
        self.write("project/docs/setup.md", "# Setup")
        self.write("project/README.md", "# Project")
        self.write("project/AGENTS.md", "# Agent instructions")
        items = self.catalog.inventory()["items"]
        self.assertFalse(any(i["kind"] == "document" for i in items))
        self.assertFalse(any(i["name"] in ("setup.md", "README.md") for i in items))
        self.assertTrue(any(i["name"] == "AGENTS.md" and i["kind"] == "instruction" for i in items))

    def test_json_escaped_secret_round_trip(self):
        original = json.dumps({"mcpServers": {"demo": {"env": {"TOKEN": 'quote " newline\n unicode \u00e9'}, "url": "https://example.invalid/mcp"}}})
        masked, replacements = mask_config(original, ".json")
        self.assertNotIn("newline", masked)
        self.assertEqual(restore_config(masked, replacements), original)

    def test_preview_reports_conflicting_source(self):
        item = self.skill()
        doc = self.catalog.document(item["id"])
        self.write(".agents/skills/example/SKILL.md", "Changed externally")
        with self.assertRaises(ValueError):
            self.catalog.preview_document(item["id"], doc["revision"], "Proposal")


class AgentTests(Fixture):
    def setUp(self):
        super().setUp()
        self.cli = patch("adsharness.agents.find_cli", return_value=sys.executable)
        self.cli.start()
        self.addCleanup(self.cli.stop)

    def manager(self, runner):
        manager = AgentManager(self.catalog, runner)
        self.addCleanup(manager.close)
        return manager

    def fake_proposal(self, argv, folder, input_text="", **kwargs):
        prompt = input_text
        if "--input-format" in argv:
            prompt = json.loads(input_text)["message"]["content"]
        request = json.loads(prompt.split("\n", 1)[1])
        self.assertNotIn("SECRET_", prompt)
        proposal = {"summary": "Improve clarity", "content": request["document"] + "\nUpdated by agent.\n"}
        if "exec" in argv:
            (Path(folder) / "response.json").write_text(json.dumps(proposal))
            return 0, "", ""
        return 0, json.dumps({"event": "result", "result": {"status": "SUCCESS", "structured_output": proposal}}), ""

    def test_both_providers_return_reviewable_proposals_without_writing(self):
        for provider in ("codex", "antigravity"):
            with self.subTest(provider=provider):
                manager = self.manager(self.fake_proposal)
                item = self.skill()
                doc = self.catalog.document(item["id"])
                ident = manager.propose(provider, item["id"], doc["revision"], "Improve this skill")["id"]
                result = finished(manager, ident)
                self.assertEqual(result["status"], "ready", result)
                self.assertIn("+Updated by agent.", result["diff"])
                self.assertEqual(self.catalog.document(item["id"])["content"], doc["content"])
                manager.apply(ident)
                self.assertIn("Updated by agent.", self.catalog.document(item["id"])["content"])
                with self.assertRaises(ValueError):
                    manager.apply(ident)

    def test_apply_rejects_external_change(self):
        manager = self.manager(self.fake_proposal)
        item = self.skill()
        doc = self.catalog.document(item["id"])
        ident = manager.propose("codex", item["id"], doc["revision"], "Improve")["id"]
        finished(manager, ident)
        self.write(".agents/skills/example/SKILL.md", "User changed it")
        with self.assertRaises(ValueError):
            manager.apply(ident)

    def test_unexpected_worker_error_does_not_block_future_jobs(self):
        def broken(*args, **kwargs):
            raise TypeError("Unexpected internal detail")
        manager = self.manager(broken)
        first = manager.check("codex")["id"]
        self.assertEqual(finished(manager, first)["status"], "failed")
        self.assertNotIn("Unexpected internal detail", manager.get(first)["message"])
        second = manager.check("codex")["id"]
        self.assertEqual(finished(manager, second)["status"], "failed")

    def test_null_agent_response_fails_cleanly(self):
        manager = self.manager(lambda *a, **k: (0, '{"event":"result","result":{"status":"SUCCESS","response":null}}', ""))
        item = self.skill()
        doc = self.catalog.document(item["id"])
        ident = manager.propose("antigravity", item["id"], doc["revision"], "Improve")["id"]
        self.assertEqual(finished(manager, ident)["status"], "failed")

    def test_timeout_diagnostics_reject_partial_success(self):
        def partial(*args, **kwargs):
            return 0, '{"event":"result","result":{"status":"SUCCESS","response":""}}', "[agy] print timeout after 3m"
        manager = self.manager(partial)
        item = self.skill()
        doc = self.catalog.document(item["id"])
        ident = manager.propose("antigravity", item["id"], doc["revision"], "Improve")["id"]
        self.assertEqual(finished(manager, ident)["status"], "failed")

    def test_active_job_can_be_recovered_and_cancelled_after_client_reload(self):
        def blocking(*args, cancel, **kwargs):
            cancel.wait(3)
            raise ValueError("Operation cancelled.")
        manager = self.manager(blocking)
        ident = manager.login("codex")["id"]
        recovered = next(p["active_job"] for p in manager.status() if p["active_job"])
        self.assertEqual(recovered, {"id": ident, "provider": "codex", "kind": "login", "status": "running"})
        with self.assertRaisesRegex(ValueError, "Open Connect agents"):
            manager.check("antigravity")
        manager.cancel(recovered["id"])
        self.assertEqual(finished(manager, ident)["status"], "cancelled")
        self.assertTrue(all(p["active_job"] is None for p in manager.status()))
        manager.runner = lambda *a, **k: (0, "Connected", "")
        self.assertEqual(finished(manager, manager.check("antigravity")["id"])["status"], "completed")

    def test_cancel_prevents_apply(self):
        def blocking(*args, cancel, **kwargs):
            cancel.wait(2)
            raise ValueError("Operation cancelled.")
        manager = self.manager(blocking)
        item = self.skill()
        doc = self.catalog.document(item["id"])
        ident = manager.propose("codex", item["id"], doc["revision"], "Improve")["id"]
        manager.cancel(ident)
        self.assertEqual(finished(manager, ident)["status"], "cancelled")
        with self.assertRaises(ValueError):
            manager.apply(ident)

    def test_device_sign_in_exposes_only_code_and_allowed_url(self):
        emitted = threading.Event()
        release = threading.Event()
        def login(argv, folder, on_output, **kwargs):
            on_output("https://attacker.invalid/steal https://auth.openai.com/codex/device\nABCD-EFGH\nprivate log")
            emitted.set()
            release.wait(2)
            return 0, "private log", ""
        manager = self.manager(login)
        ident = manager.login("codex")["id"]
        self.assertTrue(emitted.wait(2))
        job = manager.get(ident)
        self.assertEqual(job["url"], "https://auth.openai.com/codex/device")
        self.assertEqual(job["code"], "ABCD-EFGH")
        self.assertNotIn("private log", json.dumps(job))
        release.set()
        self.assertEqual(finished(manager, ident)["status"], "completed")
        self.assertNotIn("code", manager.get(ident))

    def test_connection_check_and_missing_cli(self):
        manager = self.manager(lambda *a, **k: (0, "Logged in using ChatGPT", ""))
        ident = manager.check("codex")["id"]
        finished(manager, ident)
        self.assertEqual(manager.status()[0]["state"], "connected")
        with patch("adsharness.agents.find_cli", side_effect=ValueError("Missing")):
            self.assertFalse(manager.status()[0]["installed"])

    def test_native_antigravity_login_uses_fixed_cli_command(self):
        manager = self.manager(self.fake_proposal)
        with patch("adsharness.agents.sys.platform", "darwin"), patch("adsharness.agents.subprocess.run") as run:
            result = manager.login("antigravity")
            self.assertTrue(result["external"])
            self.assertEqual(run.call_args.args[0][0], "/usr/bin/osascript")
            self.assertIn("--sandbox --mode plan", run.call_args.args[0][-1])

    def test_commands_do_not_bypass_cli_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            for provider in ("codex", "antigravity"):
                argv, stdin = proposal_command(provider, "cli", Path(folder), "prompt", "example-model")
                self.assertNotIn("--dangerously-skip-permissions", argv)
                self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)
                self.assertIn("--sandbox", argv)
                self.assertIn("example-model", argv)
                self.assertNotIn("prompt", argv)


class ProcessTests(unittest.TestCase):
    def test_stdin_and_both_streams_are_drained(self):
        with tempfile.TemporaryDirectory() as folder:
            code, out, err = run_cli([sys.executable, "-c", "import sys; print(sys.stdin.read()); print('diagnostic',file=sys.stderr)"], folder, "input", timeout=2)
            self.assertEqual(code, 0)
            self.assertIn("input", out)
            self.assertIn("diagnostic", err)

    def test_timeout_terminates_child(self):
        with tempfile.TemporaryDirectory() as folder:
            started = time.monotonic()
            with self.assertRaises(ValueError):
                run_cli([sys.executable, "-c", "import time; time.sleep(30)"], folder, timeout=0.1)
            self.assertLess(time.monotonic() - started, 4)


if __name__ == "__main__":
    unittest.main()
