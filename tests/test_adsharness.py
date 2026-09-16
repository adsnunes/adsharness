import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from adsharness.core import Catalog, MAX_FILE
from adsharness.server import create_server


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.home / ".codex")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.catalog = Catalog(self.home, self.home / "state", self.home / "project")
        self.write(".codex/config.toml", '[mcp_servers.docs]\ncommand = "echo"\nargs = ["SECRET_ARGUMENT"]\nenabled = false\n[mcp_servers.docs.env]\nTOKEN = "SECRET_TOKEN"\n')
        self.write(".gemini/config/mcp_config.json", json.dumps({"mcpServers": {"remote": {"serverUrl": "https://user:SECRET_PASSWORD@example.invalid/mcp?token=SECRET_URL", "headers": {"Authorization": "SECRET_HEADER"}}}}))
        self.write(".agents/skills/example/SKILL.md", '---\nname: example\ndescription: Example skill\n---\nInitial content\n')
        self.write("project/AGENTS.md", "Project instructions")

    def write(self, relative, content):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def skill(self):
        return next(i for i in self.catalog.inventory()["items"] if i["kind"] == "skill")


class CatalogTests(Fixture):
    def test_inventory_omits_credentials_and_commands(self):
        data = self.catalog.inventory()
        self.assertNotIn("SECRET_", json.dumps(data))
        servers = {i["name"]: i for i in data["items"] if i["kind"] == "mcp"}
        self.assertFalse(servers["docs"]["enabled"])
        self.assertEqual(servers["remote"]["transport"], "HTTP / remote")
        self.assertTrue(servers["remote"]["credentials"])
        self.assertTrue(any(i["scope"] == "project" for i in data["items"]))

    def test_metadata_cannot_override_provider_fields(self):
        item = self.skill()
        self.write("state/library.json", json.dumps({item["id"]: {"favorite": True, "tags": [], "editable": False, "name": "Injected"}}))
        result = self.skill()
        self.assertEqual(result["name"], "example")
        self.assertTrue(result["editable"])
        self.assertTrue(result["favorite"])

    def test_malformed_metadata_is_reported(self):
        self.write("state/library.json", json.dumps({"bad": ["not a record"]}))
        self.assertTrue(self.catalog.inventory()["issues"])
        with self.assertRaises(ValueError):
            self.catalog.organize(self.skill()["id"], True, [])

    def test_corrupt_provider_does_not_hide_other_items(self):
        self.write(".codex/config.toml", "invalid = [")
        data = self.catalog.inventory()
        self.assertEqual(len(data["issues"]), 1)
        self.assertTrue(any(i["name"] == "remote" for i in data["items"]))

    def test_favorites_and_tags_persist_without_provider_changes(self):
        item = self.skill()
        before = (self.home / ".codex/config.toml").read_bytes()
        self.catalog.organize(item["id"], True, [" research ", "research", ""])
        fresh = Catalog(self.home, self.home / "state")
        result = next(i for i in fresh.inventory()["items"] if i["id"] == item["id"])
        self.assertTrue(result["favorite"])
        self.assertEqual(result["tags"], ["research"])
        self.assertEqual(before, (self.home / ".codex/config.toml").read_bytes())

    def test_save_backs_up_and_rejects_stale_revision(self):
        item = self.skill()
        old = self.catalog.document(item["id"])
        result = self.catalog.save_document(item["id"], old["revision"], "New content")
        self.assertNotEqual(result["revision"], old["revision"])
        self.assertEqual(self.catalog.document(item["id"])["content"], "New content")
        backups = list((self.home / "state/backups").glob("*.md"))
        self.assertEqual(backups[0].read_bytes(), old["content"].encode("utf-8"))
        with self.assertRaises(ValueError):
            self.catalog.save_document(item["id"], old["revision"], "Stale edit")

    def test_external_edit_is_preserved(self):
        item = self.skill()
        revision = self.catalog.document(item["id"])["revision"]
        path = self.write(".agents/skills/example/SKILL.md", "External change")
        with self.assertRaises(ValueError):
            self.catalog.save_document(item["id"], revision, "Overwrite")
        self.assertEqual(path.read_text(), "External change")

    def test_system_skills_are_read_only(self):
        self.write(".codex/skills/.system/builtin/SKILL.md", "Built in")
        item = next(i for i in self.catalog.inventory()["items"] if i["name"] == "builtin")
        doc = self.catalog.document(item["id"])
        self.assertFalse(doc["editable"])
        with self.assertRaises(ValueError):
            self.catalog.save_document(item["id"], doc["revision"], "No")

    def test_symlink_document_cannot_be_written(self):
        target = self.write("external.md", "Outside")
        link = self.home / "project/GEMINI.md"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Symlink permission unavailable")
        self.assertFalse(any(i["name"] == "GEMINI.md" for i in self.catalog.inventory()["items"]))
        self.assertEqual(target.read_text(), "Outside")

    def test_project_skill_and_config_symlinks_cannot_escape_workspace(self):
        outside = self.write("external/SKILL.md", "Private source")
        folder = self.home / "project/.agents/skills"
        folder.mkdir(parents=True)
        config = self.home / "project/.codex/config.toml"
        config.parent.mkdir(parents=True)
        try:
            (folder / "escape").symlink_to(outside.parent, target_is_directory=True)
            config.symlink_to(self.home / ".codex/config.toml")
        except OSError:
            self.skipTest("Symlink permission unavailable")
        items = self.catalog.inventory()["items"]
        self.assertFalse(any(i["name"] == "escape" for i in items))
        self.assertFalse(any(i["provider"] == "codex" and i["scope"] == "project" for i in items))
        self.assertTrue(any(i["provider"] == "codex" and i["scope"] == "global" for i in items))

    def test_unknown_ids_and_invalid_tags_rejected(self):
        with self.assertRaises(ValueError):
            self.catalog.document("../../outside")
        with self.assertRaises(ValueError):
            self.catalog.organize(self.skill()["id"], True, ["x" * 41])

    def test_oversized_file_is_reported(self):
        self.write(".agents/skills/huge/SKILL.md", "x" * (MAX_FILE + 1))
        self.assertTrue(self.catalog.inventory()["issues"])


class ServerTests(Fixture):
    def setUp(self):
        super().setUp()
        self.server = create_server(self.catalog, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            conn.request(method, path, body=json.dumps(body) if body else None, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            conn.close()

    def test_static_assets_and_session(self):
        for path in ("/", "/app.js", "/style.css"):
            status, body, headers = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertTrue(body)
            self.assertEqual(headers["X-Frame-Options"], "DENY")
        status, body, _ = self.request("GET", "/api/session")
        self.assertEqual(json.loads(body)["token"], self.server.token)

    def test_rejects_foreign_origins_hosts_and_missing_token(self):
        for headers in ({"Host": "attacker.invalid"}, {"Origin": "https://attacker.invalid"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.request("GET", "/api/session", headers=headers)[0], 403)
        self.assertEqual(self.request("GET", "/api/inventory")[0], 403)
        self.assertEqual(self.request("POST", "/api/organize", {"id": "fake"})[0], 403)

    def test_inventory_and_mutation_with_token(self):
        headers = {"X-adsharness-token": self.server.token}
        status, body, _ = self.request("GET", "/api/inventory", headers=headers)
        self.assertEqual(status, 200)
        self.assertNotIn(b"SECRET_", body)
        item = self.skill()
        status, _, _ = self.request("POST", "/api/organize", {"id": item["id"], "favorite": True, "tags": ["test"]}, headers)
        self.assertEqual(status, 200)
        self.assertTrue(self.skill()["favorite"])

    def test_unknown_asset_cannot_traverse(self):
        self.assertEqual(self.request("GET", "/../core.py")[0], 404)


if __name__ == "__main__":
    unittest.main()
