"""Read provider files without executing their commands or exposing credentials."""
import hashlib
import difflib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import tomllib

from .documents import mask_config, parse_config, restore_config, sensitive_values, value_at

MAX_FILE = 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_bytes(path):
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValueError("File exceeds 1 MB")
    return data


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".adsharness-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Catalog:
    def __init__(self, home, state_dir, workspace=None):
        self.home = Path(home).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.workspace = Path(workspace).resolve() if workspace else None
        self.lock = threading.RLock()
        self.targets = {}
        self.codex = Path(os.environ.get("CODEX_HOME") or self.home / ".codex").expanduser().resolve()

    def label(self, path):
        try:
            return "~/" + str(path.relative_to(self.home))
        except ValueError:
            return str(path)

    def source_allowed(self, path):
        """Project files may not resolve outside the selected workspace."""
        if not self.workspace or not path.is_relative_to(self.workspace):
            return True
        try:
            return path.resolve().is_relative_to(self.workspace)
        except (OSError, RuntimeError):
            return False

    def metadata(self):
        file = self.state_dir / "library.json"
        if not file.exists():
            return {}
        data = json.loads(read_bytes(file))
        if not isinstance(data, dict):
            raise ValueError("Invalid local library")
        for value in data.values():
            if (not isinstance(value, dict) or type(value.get("favorite", False)) is not bool
                    or not isinstance(value.get("tags", []), list)
                    or any(not isinstance(tag, str) for tag in value.get("tags", []))):
                raise ValueError("Invalid local library")
        return {key: {"favorite": value.get("favorite", False), "tags": value.get("tags", [])}
                for key, value in data.items()}

    def inventory(self):
        with self.lock:
            items, issues, targets = [], [], {}
            try:
                metadata = self.metadata()
            except (OSError, ValueError):
                metadata = {}
                issues.append("Could not read local organization data. Check library.json.")
            sources = [("codex", "global", self.codex / "config.toml"),
                       ("antigravity", "global", self.home / ".gemini/config/mcp_config.json"),
                       ("antigravity", "global · legacy IDE", self.home / ".gemini/antigravity/mcp_config.json")]
            if self.workspace:
                sources += [("codex", "project", self.workspace / ".codex/config.toml"),
                            ("antigravity", "project", self.workspace / ".agents/mcp_config.json")]
            def add(kind, name, provider, scope, path, **extra):
                ident = digest(f"{kind}:{provider}:{path}:{name}".encode())[:24]
                entry = dict(id=ident, kind=kind, name=name, provider=provider, scope=scope,
                             source=self.label(path), **extra)
                entry.update(metadata.get(ident, {}))
                items.append(entry)
                targets[ident] = path
            for provider, scope, path in sources:
                if not self.source_allowed(path) or not path.is_file():
                    continue
                try:
                    raw = read_bytes(path)
                    config = tomllib.loads(raw.decode()) if path.suffix == ".toml" else json.loads(raw)
                    servers = config.get("mcp_servers" if provider == "codex" else "mcpServers", {})
                    if not isinstance(servers, dict):
                        raise ValueError("Invalid MCP configuration")
                    for name, value in servers.items():
                        if not isinstance(value, dict):
                            continue
                        remote = any(key in value for key in ("url", "serverUrl", "httpUrl"))
                        add("mcp", name, provider, scope, path,
                            transport="HTTP / remote" if remote else "stdio",
                            enabled=value.get("enabled", True) is not False and value.get("disabled", False) is not True,
                            description="Server configured · connection not tested",
                            credentials=bool(value.get("env") or value.get("headers") or value.get("http_headers") or value.get("bearer_token_env_var")))
                    if provider == "codex":
                        allowed = {k: config[k] for k in ("model", "model_provider", "model_reasoning_effort", "approval_policy", "sandbox_mode") if isinstance(config.get(k), (str, bool, int))}
                        add("harness", "Codex", provider, scope, path, settings=allowed,
                            description="Preferences declared in the file; host policies may take precedence.")
                except (OSError, ValueError, TypeError, AttributeError):
                    issues.append(f"Could not parse {self.label(path)}")
            for settings in (self.home / ".gemini/settings.json", self.home / ".gemini/antigravity-cli/settings.json"):
                if self.source_allowed(settings) and settings.is_file():
                    add("harness", "Antigravity", "antigravity", "global", settings,
                        settings={}, description="Local agent settings. Open the source to inspect or edit them.")
            roots = [("shared", "global", self.home / ".agents/skills"),
                     ("codex", "global", self.codex / "skills"),
                     ("antigravity", "global", self.home / ".gemini/skills"),
                     ("antigravity", "global · IDE", self.home / ".gemini/antigravity/skills")]
            if self.workspace:
                roots += [(p, "project", self.workspace / rel) for p, rel in
                          [("shared", ".agents/skills"), ("codex", ".codex/skills"), ("antigravity", ".agent/skills")]]
            for provider, scope, folder in roots:
                if not self.source_allowed(folder) or not folder.is_dir():
                    continue
                try:
                    paths = sorted(folder.glob("*/SKILL.md")) + sorted(folder.glob(".system/*/SKILL.md"))
                    for path in paths:
                        if not self.source_allowed(path):
                            continue
                        try:
                            content = read_bytes(path).decode("utf-8")
                            description = "Local skill"
                            if content.startswith("---"):
                                for line in content.split("---", 2)[1].splitlines():
                                    if line.startswith("description:"):
                                        description = line.partition(":")[2].strip().strip('"').strip("'")[:240]
                                        break
                            add("skill", path.parent.name, provider, scope, path,
                                description=description, fingerprint=digest(content.encode())[:12],
                                editable=".system" not in path.parts and not path.is_symlink() and not path.parent.is_symlink())
                        except (OSError, ValueError, UnicodeError):
                            issues.append(f"Could not read {self.label(path)}")
                except OSError:
                    issues.append(f"Could not access {self.label(folder)}")
            instructions = [("codex", "global", self.codex / "AGENTS.md"),
                            ("antigravity", "global", self.home / ".gemini/GEMINI.md")]
            if self.workspace:
                instructions += [("shared", "project", self.workspace / "AGENTS.md"),
                                 ("antigravity", "project", self.workspace / "GEMINI.md")]
            for provider, scope, path in instructions:
                if self.source_allowed(path) and path.is_file():
                    add("instruction", path.name, provider, scope, path,
                        description="Agent instructions", editable=not path.is_symlink())
            self.targets = targets
            return {"items": items, "issues": issues, "workspace": self.label(self.workspace) if self.workspace else None}

    def _source(self, ident):
        if not isinstance(ident, str):
            raise ValueError("Invalid document identifier")
        inventory = self.inventory()
        item = next((x for x in inventory["items"] if x["id"] == ident), None)
        if not item or ident not in self.targets:
            raise ValueError("Document not found")
        if not self.source_allowed(self.targets[ident]):
            raise ValueError("Source is outside the workspace")
        return item, self.targets[ident]

    def document(self, ident, reveal=False):
        with self.lock:
            item, path = self._source(ident)
            data = read_bytes(path)
            content = data.decode("utf-8")
            config = path.suffix in (".toml", ".json")
            masked, count, error = False, 0, ""
            if config and not reveal:
                try:
                    content, replacements = mask_config(content, path.suffix)
                    masked, count = bool(replacements), len(replacements)
                except ValueError:
                    content = "Preview unavailable: configuration could not be parsed. Use Reveal original to inspect it locally."
                    error = "Configuration parsing failed. Agent editing is unavailable."
            editable = item.get("editable", True) and not any(p.is_symlink() for p in [path, *path.parents])
            return {"content": content, "revision": digest(data), "editable": editable and not error,
                    "source": self.label(path), "format": path.suffix.lstrip("."), "masked": masked,
                    "protected_values": count, "error": error, "revealed": bool(reveal),
                    "configuration": config}

    def _prepare(self, ident, revision, content, reveal=False):
        current = self.document(ident, reveal=reveal)
        if not current["editable"]:
            raise ValueError("Read-only document")
        if current["revision"] != revision:
            raise ValueError("The file changed outside adsharness. Reopen it before saving.")
        if not isinstance(content, str) or len(content.encode()) > MAX_FILE:
            raise ValueError("Invalid content or content larger than 1 MB")
        target = self.targets[ident]
        old = read_bytes(target)
        if digest(old) != revision:
            raise ValueError("The file changed; reopen it before saving")
        if current["configuration"]:
            if not reveal:
                _, replacements = mask_config(old.decode("utf-8"), target.suffix)
                content = restore_config(content, replacements)
            parsed = parse_config(content, target.suffix)
            if not reveal:
                for path, value in sensitive_values(parse_config(old.decode("utf-8"), target.suffix)).items():
                    if value_at(parsed, path) != value:
                        raise ValueError("Protected values cannot be moved or removed. Use the original-file editor for explicit credential changes.")
        return target, old, content

    def preview_document(self, ident, revision, content):
        with self.lock:
            self._prepare(ident, revision, content)
            original = self.document(ident)["content"]
            return "".join(difflib.unified_diff(original.splitlines(keepends=True),
                           content.splitlines(keepends=True), fromfile="original", tofile="proposal"))

    def save_document(self, ident, revision, content, reveal=False):
        with self.lock:
            target, old, content = self._prepare(ident, revision, content, reveal)
            backup = self.state_dir / "backups" / f"{ident}-{time.time_ns()}{target.suffix}"
            atomic_write(backup, old)
            atomic_write(target, content.encode())
            return {"revision": digest(content.encode()), "backup": self.label(backup)}

    def organize(self, ident, favorite, tags):
        with self.lock:
            if not any(i["id"] == ident for i in self.inventory()["items"]):
                raise ValueError("Item not found")
            if type(favorite) is not bool or not isinstance(tags, list) or len(tags) > 12 or any(not isinstance(t, str) or len(t) > 40 for t in tags):
                raise ValueError("Invalid tags: use up to 12 tags of 40 characters each")
            data = self.metadata()
            data[ident] = {"favorite": favorite, "tags": list(dict.fromkeys(t.strip() for t in tags if t.strip()))}
            atomic_write(self.state_dir / "library.json", json.dumps(data, ensure_ascii=False, indent=2).encode())
            return {"ok": True}
