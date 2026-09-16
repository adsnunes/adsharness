"""Optional browser check. Requires Playwright and a local Chromium installation."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from adsharness.core import Catalog
from adsharness.server import create_server


def main():
    with tempfile.TemporaryDirectory(prefix="adsharness-browser-") as directory:
        home = Path(directory)
        cli_home = home / ".codex"
        cli_home.mkdir()
        config = cli_home / "config.toml"
        config.write_text('[mcp_servers.demo]\ncommand = "example"\nenabled = false\n[mcp_servers.demo.env]\nTOKEN = "synthetic-private-value"\n')
        skill = home / ".agents/skills/example/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text('# Example skill\n<script>window.injected = true</script>\nOriginal instructions.\n')
        project = home / "project"
        project.mkdir()
        (project / "README.md").write_text("# Example project\n")
        release_login = threading.Event()

        def runner(argv, folder, input_text="", on_output=None, **kwargs):
            if on_output:
                on_output("https://auth.openai.com/codex/device\nABCD-EFGH")
                while not release_login.wait(0.05):
                    if kwargs["cancel"].is_set():
                        raise ValueError("Operation cancelled.")
                return 0, "Signed in", ""
            if "status" in argv or "models" in argv:
                return 0, "Connection verified", ""
            request = json.loads(input_text.split("\n", 1)[1])
            proposal = {"summary": "Enable the example MCP server.", "content": request["document"].replace("enabled = false", "enabled = true")}
            (Path(folder) / "response.json").write_text(json.dumps(proposal))
            return 0, "", ""

        with patch.dict(os.environ, {"CODEX_HOME": str(cli_home)}), patch("adsharness.agents.find_cli", return_value=sys.executable):
            server = create_server(Catalog(home, home / "state", project), 0)
            server.agents.runner = runner
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel=os.environ.get("ADSHARNESS_BROWSER_CHANNEL") or None)
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{server.server_port}")
                    expect(page.locator(".card")).to_have_count(3)
                    page.get_by_role("button", name="Connect agents", exact=True).click()
                    page.get_by_role("button", name="Sign in with device code").click()
                    expect(page.locator("#auth-code")).to_have_text("ABCD-EFGH")
                    page.reload()
                    page.get_by_role("button", name="Connect agents", exact=True).click()
                    expect(page.locator("#auth-code")).to_have_text("ABCD-EFGH")
                    expect(page.get_by_role("button", name="Sign in with device code")).to_be_disabled()
                    page.get_by_role("button", name="Cancel operation", exact=True).click()
                    expect(page.get_by_role("button", name="Sign in with device code")).to_be_enabled(timeout=5000)
                    page.get_by_role("button", name="Sign in with device code").click()
                    expect(page.locator("#auth-code")).to_have_text("ABCD-EFGH")
                    release_login.set()
                    expect(page.locator("#auth-message")).to_contain_text("Sign-in complete", timeout=5000)
                    page.get_by_role("button", name="Close agent connections").click()
                    page.locator(".card-title").filter(has_text="example").click()
                    expect(page.locator("#source-viewer")).to_contain_text("Original instructions.")
                    assert page.evaluate("window.injected") is None
                    page.get_by_role("button", name="Edit file", exact=True).click()
                    page.locator("#editor").fill("# Example skill\nEdited manually.\n")
                    page.get_by_role("button", name="Save original file").click()
                    expect(page.locator("#detail-message")).to_contain_text("Saved. Backup:")
                    assert "Edited manually." in skill.read_text()
                    page.get_by_role("button", name="Close details").click()
                    page.locator(".card-title").filter(has_text="demo").click()
                    expect(page.locator("#source-viewer")).to_contain_text("PROTECTED")
                    assert "synthetic-private-value" not in page.locator("#source-viewer").inner_text()
                    page.once("dialog", lambda dialog: dialog.accept())
                    page.get_by_role("button", name="Reveal original", exact=True).click()
                    expect(page.locator("#source-viewer")).to_contain_text("synthetic-private-value")
                    page.get_by_role("button", name="Hide protected values").click()
                    page.get_by_role("button", name="Ask an agent", exact=True).click()
                    page.locator("#edit-instruction").fill("Enable this MCP server.")
                    page.get_by_role("button", name="Generate proposal").click()
                    expect(page.locator("#proposal")).to_be_visible(timeout=5000)
                    expect(page.locator("#proposal-diff")).to_contain_text("+enabled = true")
                    assert "enabled = false" in config.read_text()
                    page.get_by_role("button", name="Apply to original file").click()
                    expect(page.locator("#agent-progress")).to_contain_text("Applied to the original file")
                    assert "enabled = true" in config.read_text()
                    assert "synthetic-private-value" in config.read_text()
                    page.get_by_role("button", name="Read source", exact=True).click()
                    artifacts = Path(".adsharness")
                    artifacts.mkdir(exist_ok=True)
                    page.screenshot(path=str(artifacts / "source-reader.png"))
                    page.get_by_role("button", name="Close details").click()
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    assert not errors, errors
                    browser.close()
                    print("Browser smoke passed: device login, safe source viewer, manual edit, agent diff/apply, credential preservation, and mobile layout.")
            finally:
                release_login.set()
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    main()
