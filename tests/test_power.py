"""Checks for the Kiro Power in ``power/`` (spec: .kiro/specs/kiro-power).

The power is static files: ``plugin.json`` and four skills. These tests keep it
in the Agent Plugins 1.0.0 shape, keep every ``hauntlet ...`` command in the
skills parseable by the real CLI parser (so the docs can't drift), and enforce
the safety rules on every file under ``power/``.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import shlex
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from hauntlet.cli import build_parser
from hauntlet.rooms import default_rooms

ROOT = Path(__file__).resolve().parent.parent
POWER = ROOT / "power"
SKILLS = POWER / "skills"

SCHEMA_URL = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
REPO_URL = "https://github.com/kuberaplutus224/hauntlet"
GIT_PREFIX = ["uvx", "--from", f"git+{REPO_URL}"]

EXPECTED_SKILLS = {"run-range", "exorcist", "test-my-mcp-client", "test-my-browser-agent"}
EXPECTED_KEYWORDS = [
    "hauntlet", "agent security", "prompt injection", "mcp",
    "red team", "guardrails", "canary", "haunted",
]
SCHEMA_PROPERTIES = {
    "$schema", "name", "version", "description", "author",
    "homepage", "repository", "license", "keywords", "extensions",
}
PLUGIN_NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
APPROVED_WORDING = "some client behaviours are out of reach of config"


# --------------------------------------------------------------------------- helpers


def _plugin() -> dict:
    return json.loads((POWER / "plugin.json").read_text(encoding="utf-8"))


def _skill_dirs() -> list[Path]:
    return sorted(p for p in SKILLS.iterdir() if p.is_dir())


def _power_files() -> list[Path]:
    return sorted(p for p in POWER.rglob("*") if p.is_file())


def _skill_markdown() -> list[Path]:
    return sorted(SKILLS.rglob("*.md"))


def parse_frontmatter(text: str) -> dict[str, str]:
    """The YAML frontmatter of a SKILL.md, as flat ``key: value`` pairs.

    Raises ValueError if the file does not start with a ``---`` block.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("no frontmatter: the file must start with ---")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError("frontmatter is not closed with ---") from None
    out: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep or line[:1].isspace():
            raise ValueError(f"unsupported frontmatter line: {line!r}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def frontmatter_problems(dirname: str, text: str) -> list[str]:
    try:
        fm = parse_frontmatter(text)
    except ValueError as exc:
        return [str(exc)]
    problems = []
    if set(fm) != {"name", "description"}:
        problems.append(f"frontmatter keys must be exactly name and description, got {sorted(fm)}")
    name = fm.get("name", "")
    if name != dirname:
        problems.append(f"name {name!r} does not match directory {dirname!r}")
    if not SKILL_NAME_RE.fullmatch(name) or len(name) > 64:
        problems.append(f"name {name!r} is not lowercase letters, digits and single hyphens (<= 64)")
    desc = fm.get("description", "")
    if not 1 <= len(desc) <= 1024:
        problems.append(f"description is {len(desc)} characters; must be 1 to 1024")
    return problems


# --------------------------------------------------------------------------- command extraction

_FENCE_RE = re.compile(r"^[ \t]*```([\w-]*)[^\n]*\n(.*?)^[ \t]*```", re.M | re.S)
_SPAN_RE = re.compile(r"`([^`\n]+)`")
_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SHELL_LANGS = {"sh", "bash", "shell", "zsh", "text", "console", ""}


def _argv_from_tokens(tokens: list[str]) -> list[str] | None:
    """The CLI argv if ``tokens`` is a ``hauntlet <subcommand> ...`` command, else None."""
    while tokens and _ENV_RE.match(tokens[0]):
        tokens = tokens[1:]
    if tokens[:2] == ["uv", "run"]:
        tokens = tokens[2:]
    elif tokens[:3] == GIT_PREFIX:
        tokens = tokens[3:]
    if len(tokens) >= 2 and tokens[0] == "hauntlet":
        return tokens[1:]
    return None


def _split(text: str, comments: bool) -> list[str] | None:
    try:
        return shlex.split(text, comments=comments)
    except ValueError:
        return None


def _json_args(node: object) -> list[list[str]]:
    found: list[list[str]] = []
    if isinstance(node, dict):
        args = node.get("args")
        if isinstance(args, list) and "hauntlet" in args and all(isinstance(a, str) for a in args):
            rest = args[args.index("hauntlet") + 1:]
            if rest:
                found.append(rest)
        for v in node.values():
            found.extend(_json_args(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_json_args(v))
    return found


def extract_commands(markdown: str) -> list[tuple[str, list[str]]]:
    """Every ``hauntlet ...`` command in a Markdown text, as (source text, argv).

    Sources (design.md "Command extraction"): lines of shell/text fenced blocks
    (with ``\\`` continuations joined), ``args`` lists in JSON blocks, and
    inline code spans outside fenced blocks. A shell line that cannot be split
    is returned with argv ``["<unparseable>", line]`` so the caller fails it.
    """
    commands: list[tuple[str, list[str]]] = []
    for m in _FENCE_RE.finditer(markdown):
        lang, body = m.group(1).lower(), m.group(2)
        if lang == "json":
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                continue
            commands.extend((json.dumps(a), a) for a in _json_args(data))
        elif lang in _SHELL_LANGS:
            joined = re.sub(r"\\\n\s*", " ", body)
            for line in joined.splitlines():
                if "hauntlet" not in line:
                    continue
                tokens = _split(line, comments=True)
                if tokens is None:
                    commands.append((line, ["<unparseable>", line]))
                    continue
                argv = _argv_from_tokens(tokens)
                if argv is not None:
                    commands.append((line.strip(), argv))
    outside = _FENCE_RE.sub("", markdown)
    for m in _SPAN_RE.finditer(outside):
        span = m.group(1)
        tokens = _split(span, comments=False)
        if tokens is None:
            if re.search(r"(^|\s)hauntlet\s", span):
                commands.append((span, ["<unparseable>", span]))
            continue
        argv = _argv_from_tokens(tokens)
        if argv is not None:
            commands.append((span, argv))
    return commands


def command_problem(argv: list[str]) -> str | None:
    """None if ``hauntlet <argv>`` parses and names a valid room, else the reason."""
    if argv[:1] == ["<unparseable>"]:
        return "cannot be split as a shell command"
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            args = build_parser().parse_args(argv)
    except SystemExit:
        return "argparse refused it: " + (err.getvalue().strip().splitlines() or ["(no message)"])[-1]
    rooms = default_rooms()
    room = getattr(args, "room", None)
    if args.cmd in ("run", "mcp", "exorcist") and room is not None:
        if room not in rooms:
            return f"unknown room {room!r}; known: {sorted(rooms)}"
        if args.cmd == "exorcist" and getattr(args, "exorcist_cmd", None) == "demo" and room == "parlor":
            return "the Exorcist demo does not support parlor"
    return None


# --------------------------------------------------------------------------- content scanner

_URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s)\]>\"'`]+", re.I)
_BARE_DOMAIN_RE = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|dev|ai|app|co|xyz|me)\b", re.I)


def url_allowed(url: str) -> bool:
    if url == SCHEMA_URL:
        return True
    bare = url[4:] if url.lower().startswith("git+") else url
    if bare in (REPO_URL, REPO_URL + ".git"):
        return True
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and host in ("127.0.0.1", "localhost")


def scan_text(text: str) -> list[str]:
    """Safety-rule violations in one file's text (design.md "Content scanner")."""
    problems: list[str] = []
    for m in re.finditer(r"HAUNTLET-DUMMY-(?!…)", text):
        problems.append(f"non-truncated dummy secret at offset {m.start()}")
    for m in re.finditer(r"hauntlet-mark-(?!…)", text):
        problems.append(f"non-truncated marker at offset {m.start()}")
    for m in re.finditer(r"/c/(?!<token>|…)", text):
        problems.append(f"canary path with a token at offset {m.start()}")
    rest = text
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;:")
        if not url_allowed(url):
            problems.append(f"URL not allowed: {url}")
        rest = rest.replace(m.group(0), " ")
    for m in _BARE_DOMAIN_RE.finditer(rest):
        problems.append(f"bare domain name: {m.group(0)}")
    return problems


# =========================================================================== manifest


def test_plugin_json_fields():
    p = _plugin()
    assert set(p) <= SCHEMA_PROPERTIES, set(p) - SCHEMA_PROPERTIES
    assert p["$schema"] == SCHEMA_URL
    assert p["name"] == "hauntlet"
    assert p["version"] == "0.1.0"
    assert isinstance(p["description"], str) and p["description"].strip()
    assert p["author"] == {"name": "kuberaplutus224"}
    assert set(p["author"]) <= {"name", "email", "url"}
    assert p["keywords"] == EXPECTED_KEYWORDS
    assert p["homepage"] == REPO_URL
    assert p["repository"] == REPO_URL
    for required in ("version", "description", "author", "keywords"):
        assert required in p


def test_plugin_license_matches_repo_license():
    first = (ROOT / "LICENSE").read_text(encoding="utf-8").splitlines()[0].strip()
    assert first.endswith(" License"), first
    assert _plugin()["license"] == first.removesuffix(" License")


def test_plugin_name_matches_schema_pattern():
    name = _plugin()["name"]
    assert 1 <= len(name) <= 64
    assert PLUGIN_NAME_RE.fullmatch(name)


def test_only_agent_plugins_manifest():
    assert (POWER / "plugin.json").is_file()
    assert not (POWER / "POWER.md").exists()


# =========================================================================== skills


def test_skill_set():
    assert {p.name for p in _skill_dirs()} == EXPECTED_SKILLS


@pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
def test_skill_frontmatter_and_size(name):
    path = SKILLS / name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    assert frontmatter_problems(name, text) == []
    assert len(text.splitlines()) < 500


REFERENCE_RE = re.compile(r"[\w./-]*references/[\w.-]+\.md")


def missing_references(md: Path) -> list[str]:
    """Reference paths named in ``md`` that don't exist relative to it.

    Kiro installs a copy of the power, so a path only resolves reliably from
    the file being read. Any prefix (``../other-skill/``, or a stale
    ``skills/...`` one) is resolved against that file's own directory.
    """
    text = md.read_text(encoding="utf-8")
    return [
        m.group(0)
        for m in REFERENCE_RE.finditer(text)
        if not (md.parent / m.group(0)).resolve().is_file()
    ]


@pytest.mark.parametrize(
    "md", sorted(SKILLS.rglob("*.md")), ids=lambda p: str(p.relative_to(SKILLS))
)
def test_skill_references_exist(md):
    assert missing_references(md) == []


def test_missing_reference_is_reported(tmp_path):
    skill = tmp_path / "skills" / "a"
    (skill / "references").mkdir(parents=True)
    (skill / "references" / "here.md").write_text("x", encoding="utf-8")
    other = tmp_path / "skills" / "b" / "references"
    other.mkdir(parents=True)
    (other / "there.md").write_text("x", encoding="utf-8")
    (skill / "SKILL.md").write_text(
        "`references/here.md` `../b/references/there.md` "
        "`references/gone.md` `../b/references/gone.md` "
        "`skills/b/references/there.md`",
        encoding="utf-8",
    )
    assert missing_references(skill / "SKILL.md") == [
        "references/gone.md",
        "../b/references/gone.md",
        "skills/b/references/there.md",
    ]


@pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
def test_skill_states_approved_wording_and_safety_rules(name):
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    assert APPROVED_WORDING in text.lower()
    assert ".kiro/steering/safety-rules.md" in text


def test_no_mcp_json_anywhere():
    assert not [p for p in POWER.rglob("mcp.json")]


# =========================================================================== command drift


@pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
def test_every_skill_has_commands(name):
    found = []
    for md in sorted((SKILLS / name).rglob("*.md")):
        found.extend(extract_commands(md.read_text(encoding="utf-8")))
    assert found, f"no hauntlet commands extracted from skill {name}"


def test_every_command_parses():
    failures = []
    count = 0
    for md in _skill_markdown():
        for source, argv in extract_commands(md.read_text(encoding="utf-8")):
            count += 1
            problem = command_problem(argv)
            if problem:
                failures.append(f"{md.relative_to(ROOT)}: {source!r}: {problem}")
    assert count > 0
    assert failures == []


def test_room_list_matches_cli():
    text = (SKILLS / "run-range" / "references" / "rooms-and-levels.md").read_text(encoding="utf-8")
    listed = re.findall(r"^\|\s*`([a-z0-9-]+)`\s*\|", text, re.M)
    assert sorted(listed) == sorted(default_rooms())
    assert len(listed) == len(set(listed))


# =========================================================================== content scanner


def test_power_files_are_utf8_and_clean():
    problems = []
    for path in _power_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"{path.relative_to(ROOT)}: not UTF-8 text")
            continue
        problems.extend(f"{path.relative_to(ROOT)}: {p}" for p in scan_text(text))
    assert problems == []


# =========================================================================== negative cases


@pytest.mark.parametrize(
    "text",
    [
        "the secret was HAUNTLET-DUMMY-abc123-t1-xyz",
        "marker hauntlet-mark-1234",
        "fetch /c/AbCdEf123",
        "see https://example.org/x",
        "git+https://github.com/someone-else/hauntlet",
        "http://10.0.0.5:8666/health",
        "go to evil.com for details",
    ],
)
def test_scanner_catches_bad_text(text):
    assert scan_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "shown as HAUNTLET-DUMMY-…",
        "canary links look like /c/<token>",
        "http://127.0.0.1:8666/health and http://localhost:8666/runs",
        f"{REPO_URL} and git+{REPO_URL} and {REPO_URL}.git",
        SCHEMA_URL,
        "run scripts/install.sh, then read plugin.json and SKILL.md",
    ],
)
def test_scanner_allows_good_text(text):
    assert scan_text(text) == []


@pytest.mark.parametrize(
    "markdown",
    [
        "`hauntlet mcp serve --room cursed-repo --run=X`",
        "`hauntlet run --room nope`",
        "`hauntlet exorcist demo --room parlor`",
        "`hauntlet mcp finalize`",
        "```sh\nuv run hauntlet run --bogus\n```",
        '```json\n{"args": ["hauntlet", "mcp", "serve", "--room", "parlor", "--run=R"]}\n```',
        "```sh\nHAUNTLET_DB=/x hauntlet parlor open\n```",
    ],
)
def test_extractor_and_checker_catch_bad_commands(markdown):
    commands = extract_commands(markdown)
    assert commands, markdown
    assert all(command_problem(argv) for _, argv in commands)


def test_extractor_reads_indented_fences():
    md = "1. Generate:\n\n   ```sh\n   hauntlet exorcist generate --run=RUN_ID\n   ```\n"
    assert [argv for _, argv in extract_commands(md)] == [["exorcist", "generate", "--run=RUN_ID"]]


def test_extractor_finds_every_form():
    md = (
        "Run `hauntlet selftest`; a name like `hauntlet-poltergeist` is not a command.\n"
        "```sh\nHAUNTLET_DB=/a/b.db uvx --from git+" + REPO_URL + " hauntlet \\\n  run --room threshold --agent naive\n```\n"
        '```json\n{"mcpServers": {"x": {"args": ["run", "--directory", "/p", "hauntlet", "mcp", "serve", '
        '"--room", "poltergeist", "--run=RUN_ID"]}}}\n```\n'
    )
    argvs = [argv for _, argv in extract_commands(md)]
    assert ["selftest"] in argvs
    assert ["run", "--room", "threshold", "--agent", "naive"] in argvs
    assert ["mcp", "serve", "--room", "poltergeist", "--run=RUN_ID"] in argvs
    assert len(argvs) == 3
    assert all(command_problem(a) is None for a in argvs)


def test_frontmatter_check_catches_bad_skills():
    assert frontmatter_problems("run-range", "---\nname: run_range\ndescription: x\n---\n")
    assert frontmatter_problems("run-range", "---\nname: other\ndescription: x\n---\n")
    assert frontmatter_problems("run-range", "---\nname: run-range\ndescription: " + "x" * 1025 + "\n---\n")
    assert frontmatter_problems("run-range", "---\nname: run-range\ndescription: x\nlicense: MIT\n---\n")
    assert frontmatter_problems("run-range", "# no frontmatter\n")
    assert frontmatter_problems("run-range", "---\nname: run-range\ndescription: ok\n---\n") == []
