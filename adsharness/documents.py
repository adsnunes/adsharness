"""Configuration validation and reversible masking for source previews."""
import json
import re
import tomllib
from urllib.parse import urlsplit

SENSITIVE = re.compile(r"secret|password|token|api.?key|credential|authorization|^env$|headers|^args$", re.I)
# Match strings before comments and scalar tokens so comment markers inside URLs stay intact.
TOKEN = re.compile(r'"{3}[\s\S]*?"{3}|\x27{3}[\s\S]*?\x27{3}|"(?:\\.|[^"\\])*"|\x27[^\x27]*\x27|#[^\n]*|(?<![\w.])(?:true|false|null|[+-]?(?:inf|nan|0[xob][0-9A-Fa-f_]+|[0-9][0-9_]*(?:\.[0-9_]+)?(?:[eE][+-]?[0-9_]+)?))(?![\w.])')
PREFIX = "__ADSHARNESS_PROTECTED_"


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate configuration key")
        result[key] = value
    return result


def reject_constant(_value):
    raise ValueError("Non-finite JSON value")


def parse_config(content, suffix):
    try:
        value = tomllib.loads(content) if suffix == ".toml" else json.loads(content, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (ValueError, TypeError):
        raise ValueError("Invalid configuration syntax. Fix the JSON or TOML before saving.") from None
    if not isinstance(value, dict):
        raise ValueError("Configuration must be an object or TOML table.")
    for key in ("mcp_servers", "mcpServers"):
        if key in value and (not isinstance(value[key], dict) or any(not isinstance(v, dict) for v in value[key].values())):
            raise ValueError("MCP servers must be named configuration objects.")
    return value


def value_at(value, path):
    try:
        for key in path:
            value = value[key]
        return value
    except (KeyError, IndexError, TypeError):
        return None


def sensitive_values(config):
    result = {}

    def collect(value, path=(), sensitive=False):
        if isinstance(value, dict):
            for key, child in value.items():
                shell_command = key == "command" and isinstance(child, str) and bool(re.search(r"\s|=", child))
                collect(child, (*path, key), sensitive or bool(SENSITIVE.search(key)) or shell_command)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                collect(child, (*path, index), sensitive)
        else:
            remote_secret = False
            if isinstance(value, str) and re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
                url = urlsplit(value)
                remote_secret = bool(url.username or url.password or url.query or url.fragment)
            if sensitive or remote_secret:
                result[path] = value
    collect(config)
    return result


def mask_config(content, suffix):
    """Protect credential fields and comments without reserializing the original file."""
    if PREFIX in content:
        raise ValueError("The source already contains reserved protection markers.")
    config = parse_config(content, suffix)
    protected = sensitive_values(config)
    replacements = {}
    parse_work = 0

    def replace(match):
        nonlocal parse_work
        token = match.group()
        comment = token.startswith("#")
        marker = f"{PREFIX}{len(replacements):04d}__"
        replacement = "# " + marker if comment else json.dumps(marker)
        if not comment:
            try:
                value = tomllib.loads("v = " + token)["v"] if suffix == ".toml" else json.loads(token)
            except ValueError:
                return token
            paths = [path for path, secret in protected.items() if type(secret) is type(value) and secret == value]
            if not paths:
                return token
            # A probe maps this lexical value to its semantic path. This avoids
            # masking unrelated values or keys that happen to equal a secret.
            parse_work += len(content)
            if parse_work > 32 * 1024 * 1024:
                raise ValueError("Configuration is too complex for a protected preview.")
            try:
                probe = parse_config(content[:match.start()] + replacement + content[match.end():], suffix)
            except ValueError:
                return token
            if not any(value_at(probe, path) == marker for path in paths):
                return token
        replacements[replacement] = token
        return replacement

    masked = TOKEN.sub(replace, content)
    parsed = parse_config(masked, suffix)
    # Fail closed for unusual scalar formats that were not tokenized.
    for path in protected:
        if not str(value_at(parsed, path)).startswith(PREFIX):
            raise ValueError("A sensitive value could not be masked safely.")
    return masked, replacements


def restore_config(content, replacements):
    for marker in replacements:
        if content.count(marker) != 1:
            raise ValueError("Protected values must remain unchanged. Reopen the file and keep every protection marker.")
    restored = content
    for marker, original in replacements.items():
        restored = restored.replace(marker, original)
    if PREFIX in restored:
        raise ValueError("Unknown protection marker in the proposed file.")
    return restored
