"""Unified git worktree management tool.

Usage:
    workit create [branch-name]
    workit remove [branch-name]
    workit abandon [branch-name]
    workit pr [branch-name]
    workit summary [branch-name]
    workit open [branch-name]
    workit config
    workit tldr
    workit help

Subcommand aliases:
    create: new
    remove: delete, del, rm
    summary: sum, summarize

Jira integration (requires acli):
    When creating a branch, workit optionally creates a Jira ticket and links it
    to an epic. Epics are presented via a fuzzy picker populated from recently
    used epics (MRU cache) and all open epics fetched live from Jira.
    Configure which projects are queried via jira_projects / epic_projects.

'workit pr' can be run from either the main repo checkout or from inside a
worktree. When run from a worktree, it automatically detects the main repo,
cd's there, and runs the full pr flow with complete cleanup support.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path
import re as _re


from InquirerPy.base.control import Choice
from InquirerPy.prompts.confirm import ConfirmPrompt
from InquirerPy.prompts.fuzzy import FuzzyPrompt
from InquirerPy.prompts.input import InputPrompt
from InquirerPy.prompts.list import ListPrompt
from InquirerPy.separator import Separator


# --- Configuration ---

_CONFIG_DIR = Path.home() / ".config" / "workit"
_CONFIG_FILE = _CONFIG_DIR / "config.json"
_PROMPTS_DIR = _CONFIG_DIR / "prompts"

# "claude-4.6-sonnet"

_CONFIG_DEFAULTS: dict = {
    "jira_projects": ["AE", "STARLING", "MAP"],
    "epic_projects": [],
    "branch_prefix": "",
    "model": "",
    "jira_assignee": "",
    "status_report": "~/workit_status_report.md",
    "jira_base_url": "https://wavecomp.atlassian.net",
}


def _load_config() -> dict:
    """Load config from ~/.config/workit/config.json, falling back to defaults."""
    config = dict(_CONFIG_DEFAULTS)
    if _CONFIG_FILE.exists():
        try:
            with _CONFIG_FILE.open() as f:
                user_config = json.load(f)
            config.update(user_config)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Could not read config file '{_CONFIG_FILE}': {e}")
    return config


config = _load_config()

# --- Verbose logging ---

_verbose: bool = False


def vlog(*args, **kwargs) -> None:
    """Print only when --verbose is active."""
    if _verbose:
        print(*args, **kwargs)


PR_FORMATTER = (
    "\n\nExamine all changes on the branch '${BRANCH}' relative to main (or the default base branch). "
    "Write a clear Level 1 markdown (#) PR title on the first line, followed by a blank line, "
    "then break the changes into high-level unrelated functional blocks and write a level 2 titled single "
    "paragraph for each functional change. Each paragraph should be 3 to 6 sentences "
    "long and written for a management audience. Do not use filenames or code syntax in "
    "the description, just describe the changes in plain language. "
    "Be factual and concise. Do not include filler phrases.  Emphasize UX and customer impact where possible."
)

COMMIT_FORMATTER = (
    "\n\nWrite a clear level one markdown title (#) commit summary on the first line, followed by a blank line, "
    "then break the changes into functional blocks and write a level 2 titled single "
    "paragraph for each functional change. Each paragraph should be 2 to 4 sentences "
    "long and written for a technical audience. "
    "Be factual and concise. Do not include filler phrases.  Emphasize UX and customer impact where possible."
)

POST_PR_FORMATTER = (
    "\n\nExamine all changes in PR #${PR_NUMBER} using 'gh pr view ${PR_NUMBER}' for the title "
    "and metadata and 'gh pr diff ${PR_NUMBER}' for the full diff. "
    "Write the level one markdown title (#) PR title on the first line, followed by a blank line, "
    "then break the changes into high-level unrelated functional blocks and write a level 2 titled single "
    "paragraph for each functional change. Each paragraph should be 3 to 6 sentences "
    "long and written for a management audience. Do not use filenames or code syntax in "
    "the description, just describe the changes in plain language. "
    "Be factual and concise. Do not include filler phrases. Emphasize UX and customer impact where possible."
)

_DEFAULT_PROMPTS: dict[str, str] = {
    "PR Branch Summary": (
        "You are a helpful assistant that writes concise GitHub pull request descriptions.\n"
        "Examine the git log and diff for the branch '${BRANCH}' in this repository."
    )
    + PR_FORMATTER,
    "Last Commit Summary": (
        "You are a helpful assistant that summarizes the last commit on a given branch.\n"
        "Examine the git log and diff for the last commit on this branch in this repository."
    )
    + COMMIT_FORMATTER,
    "Working Copy Summary": (
        "You are a helpful assistant that summarizes the working copy changes.\n"
        "Examine the unstaged changes in this working copy."
    )
    + COMMIT_FORMATTER,
    "Stage Changes Summary": (
        "You are a helpful assistant that summarizes the staged changes.\n"
        "Examine the staged changes in this working copy."
    )
    + COMMIT_FORMATTER,
    "Post PR Summary": (
        "You are a helpful assistant that writes concise post-merge summaries of GitHub pull requests."
    )
    + POST_PR_FORMATTER,
}

_PR_PROMPT_NAME = "PR Branch Summary"
_COMMIT_PROMPT_NAME = "Last Commit Summary"
_UNCOMMITTED_PROMPT_NAME = "Working Copy Summary"
_STAGED_PROMPT_NAME = "Stage Changes Summary"
_POST_PR_PROMPT_NAME = "Post PR Summary"


def _get_available_prompts() -> dict[str, str]:
    """Return all available prompts: built-in defaults merged with any files in _PROMPTS_DIR."""
    prompts = dict(_DEFAULT_PROMPTS)
    if _PROMPTS_DIR.is_dir():
        for f in sorted(_PROMPTS_DIR.glob("*.md")):
            name = f.stem.replace("_", " ").replace("-", " ")
            prompts[name] = f.read_text().strip()
    return prompts


def _load_prompt(name: str) -> str:
    """Load a prompt by name, checking built-ins and ~/.config/workit/prompts/."""
    prompts = _get_available_prompts()
    if name in prompts:
        return prompts[name]
    print(f"Error: No prompt named '{name}' found.")
    print(f"Available prompts: {', '.join(prompts)}")
    raise FileNotFoundError(f"Missing prompt: {name}")


def _strip_copilot_work_log(text: str) -> str:
    """Remove the copilot agentic tool-call display lines from CLI output.

    Strategy 1 (preferred): if the output contains a level-1 markdown heading
    (a line starting with '# '), discard everything before that line.

    Strategy 2 (fallback): drop lines matching the copilot work-log display
    patterns (●, │, └) and collapse stray blank lines.
    """
    # Strip ANSI escape codes first
    ansi_escape = _re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
    cleaned = ansi_escape.sub("", text)

    # Strategy 1: find the first level-1 markdown title and keep from there
    lines = cleaned.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return "\n".join(lines[i:])

    # Strategy 2: regex-based work-log line removal
    work_log_pattern = _re.compile(
        r"^(\s*[●•]\s|"  # ● Tool name lines
        r"\s*[│|]\s|"  # │ content lines
        r"\s*[└╰]\s)",  # └ N lines... footer
        _re.UNICODE,
    )
    filtered = [line for line in lines if not work_log_pattern.match(line)]

    # Collapse multiple consecutive blank lines into one
    result_lines: list[str] = []
    prev_blank = False
    for line in filtered:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        result_lines.append(line)
        prev_blank = is_blank

    return "\n".join(result_lines)


def generate_summary(
    branch: str,
    repo: str,
    prompt_name: str = _PR_PROMPT_NAME,
    pr_number: str | None = None,
    cwd: str | Path | None = None,
) -> str:
    """Generate a summary using the copilot CLI with the specified prompt."""
    copilot_path = shutil.which("copilot")
    if not copilot_path:
        raise RuntimeError("'copilot' CLI not found on PATH")
    vlog(f"copilot binary: {copilot_path}")

    prompt = _load_prompt(prompt_name)
    prompt = (
        prompt.replace("${BRANCH}", branch)
        .replace("${REPO}", repo)
        .replace("${PR_NUMBER}", pr_number or "")
    )
    vlog("Summary prompt:")
    vlog()
    vlog(prompt)
    vlog()

    cmd = ["copilot"]
    model = config.get("model", "default")
    if model != "default":
        cmd += ["--model", model]
    cmd += ["-p", prompt]

    vlog(f"Running command: {' '.join(cmd[:-1])} '<prompt>'")
    if cwd:
        vlog(f"cwd: {cwd}")
    vlog()

    result_holder: list = []

    def _run() -> None:
        result_holder.append(
            subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        )

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    spinner = ["|", "/", "-", "\\"]  # noqa: W605
    idx = 0
    while thread.is_alive():
        print(f"\r  {spinner[idx % len(spinner)]} Thinking...", end="", flush=True)
        idx += 1
        time.sleep(0.1)
    print("\r  ✓ Done.          ", flush=True)

    thread.join()
    result = result_holder[0]

    vlog(f"Exit code: {result.returncode}")
    if result.stdout:
        vlog(f"stdout ({len(result.stdout)} chars):")
        vlog(result.stdout)
    else:
        vlog("stdout: (empty)")
    if result.stderr:
        vlog(f"stderr ({len(result.stderr)} chars):")
        vlog(result.stderr)
    else:
        vlog("stderr: (empty)")

    if result.returncode != 0:
        raise RuntimeError(f"copilot CLI exited with code {result.returncode}")
    if not result.stdout.strip():
        raise RuntimeError("copilot CLI returned empty output")
    return _strip_copilot_work_log(result.stdout).strip()


def create_jira_workitem(
    title: str,
    summary: str,
    jira_key: str | None = None,
    epic_key: str | None = None,
) -> tuple[str, str] | None:
    """Create a Jira workitem via ACLI. Returns (issue_id, issue_url) or None."""
    title = title.lstrip("#").strip()
    if not shutil.which("acli"):
        print("Warning: acli is not installed or not on PATH.")
        proceed = ConfirmPrompt(
            message="Continue without a Jira ticket?",
            default=True,
        ).execute()
        return (
            None if proceed else (_ for _ in ()).throw(RuntimeError("acli not found"))
        )

    if jira_key:
        project = jira_key
    else:
        projects = config["jira_projects"]
        if len(projects) == 1:
            project = projects[0]
            print(f"Jira project: {project}")
        else:
            project = ListPrompt(
                message="Select Jira project:",
                choices=projects,
                default=projects[0],
            ).execute()

    cmd = [
        "acli",
        "jira",
        "workitem",
        "create",
        "--summary",
        title,
        "--project",
        project,
        "--type",
        "Task",
        "--description",
        summary,
    ]
    if config.get("jira_assignee"):
        cmd += ["--assignee", config["jira_assignee"]]
    if epic_key:
        cmd += ["--parent", epic_key]

    print("Creating Jira workitem...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout.strip() or result.stderr.strip()

    if result.returncode != 0:
        print(f"Error: acli failed.\n{output}")
        proceed = ConfirmPrompt(
            message="Continue without a Jira ticket?",
            default=True,
        ).execute()
        return None if proceed else (_ for _ in ()).throw(RuntimeError("acli error"))

    match = re.search(r"Work item (\S+) created: (\S+)", output)
    if not match:
        print(f"Warning: Could not parse acli output:\n{output}")
        proceed = ConfirmPrompt(
            message="Continue without a Jira ticket?",
            default=True,
        ).execute()
        return (
            None if proceed else (_ for _ in ()).throw(RuntimeError("acli parse error"))
        )

    issue_id, issue_url = match.group(1), match.group(2)
    print(f"Created: {issue_id} — {issue_url}")
    return issue_id, issue_url


# --- Status report ---


def append_status_report(title: str, summary: str) -> None:
    """Append PR title and summary to the configured status_report file."""
    import datetime

    report_path_str = config.get("status_report", "")
    if not report_path_str:
        return
    report_path = Path(report_path_str).expanduser()
    merge_date = datetime.date.today().isoformat()
    try:
        with report_path.open("a") as f:
            f.write(f"\n## {title}\nDate merged: {merge_date}\n\n{summary}\n")
        print(f"Status report updated: {report_path}")
    except OSError as e:
        print(f"Warning: Could not write to status report '{report_path}': {e}")


# --- Utilities ---


def open_vscode_with_countdown(path: str | Path, seconds: int = 3) -> None:
    """Print a countdown then open VS Code at the given path in a new window."""
    for remaining in range(seconds, 0, -1):
        print(
            f"Opening VS Code in {remaining} second{'s' if remaining != 1 else ''}...",
            end="\r",
            flush=True,
        )
        time.sleep(1)
    print(" " * 40, end="\r")  # clear the line
    subprocess.run(["code", str(path), "--new-window"])


def run_git(
    *args: str, capture: bool = True, cwd: str | None = None
) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    cmd = ["git"] + list(args)
    return subprocess.run(cmd, capture_output=capture, text=True, cwd=cwd)


def get_repo_name() -> str:
    return Path.cwd().name


def get_repo_slug() -> str:
    """Return the org/repo slug (e.g. 'mgfarmer/kjm_tools') from gh CLI."""
    result = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return get_repo_name()


def get_worktree_base() -> Path:
    return Path.cwd().parent / f"{get_repo_name()}-worktrees"


def get_target_path(branch_name: str) -> Path:
    return get_worktree_base() / branch_name


def branch_exists(branch_name: str) -> bool:
    result = run_git("show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}")
    return result.returncode == 0


def get_existing_worktrees() -> list[str]:
    """Return list of branch names that have worktrees in the worktrees directory.

    Uses 'git worktree list --porcelain' as the authoritative source rather than
    walking the filesystem, which avoids spawning thousands of subprocesses.
    """
    base = get_worktree_base()
    result = run_git("worktree", "list", "--porcelain")
    if result.returncode != 0:
        return []
    results = []
    current_path: str | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = line[len("worktree ") :].strip()
        elif line.startswith("branch "):
            if current_path:
                wt_path = Path(current_path).resolve()
                if wt_path.is_relative_to(base.resolve()):
                    branch_name = line[len("branch refs/heads/") :].strip()
                    if branch_name:
                        results.append(branch_name)
            current_path = None
    return sorted(results)


def get_unpushed_commits(branch_name: str) -> list[str]:
    result = run_git("log", "--oneline", branch_name, "--not", "--remotes")
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return result.stdout.strip().splitlines()


def get_worktree_status(target_path: Path) -> list[str]:
    result = run_git("-C", str(target_path), "status", "--porcelain")
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return result.stdout.strip().splitlines()


def prompt_select_worktree(action_description: str) -> str | None:
    """Prompt user to select from existing worktrees."""
    worktrees = get_existing_worktrees()
    if not worktrees:
        print("No existing worktrees found.")
        return None

    if len(worktrees) == 1:
        print(f"Auto-selected worktree: {worktrees[0]}")
        return worktrees[0]

    branch = ListPrompt(
        message=f"Select a worktree to {action_description}:",
        choices=worktrees,
    ).execute()
    return branch


def prompt_branch_name() -> str | None:
    """Prompt user for a new branch name."""
    branch = InputPrompt(
        message="Enter the new branch name:",
        validate=lambda x: len(x.strip()) > 0,
        invalid_message="Branch name cannot be empty.",
    ).execute()
    return branch.strip() if branch else None


def extract_ticket_id(branch_name: str) -> str | None:
    """Extract a Jira ticket ID prefix from the last segment of a branch name.

    E.g. 'kjm/AE-123-my-feature' → 'AE-123', 'main' → None.
    """
    last_segment = branch_name.rsplit("/", 1)[-1]
    m = re.match(r"^([A-Z]+-\d+)-", last_segment)
    return m.group(1) if m else None


# --- Epic cache ---


def load_epic_cache() -> list[dict]:
    """Load the epic cache from config.json. Returns a list of {key, summary} dicts."""
    try:
        if _CONFIG_FILE.exists():
            with _CONFIG_FILE.open() as f:
                data = json.load(f)
            cache = data.get("epic_cache", [])
            if isinstance(cache, list):
                return cache[:5]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_epic_cache(epic_key: str, epic_summary: str) -> None:
    """Prepend an epic to the cache in config.json, deduplicate by key, truncate to 5."""
    cache = load_epic_cache()
    cache = [e for e in cache if e.get("key") != epic_key]
    cache.insert(0, {"key": epic_key, "summary": epic_summary})
    cache = cache[:5]
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        existing: dict = {}
        if _CONFIG_FILE.exists():
            with _CONFIG_FILE.open() as f:
                existing = json.load(f)
        existing["epic_cache"] = cache
        with _CONFIG_FILE.open("w") as f:
            json.dump(existing, f, indent=2)
    except OSError as e:
        print(f"Warning: Could not write epic cache: {e}")


def fetch_epic_summary(epic_key: str) -> str:
    """Fetch the summary/title of a Jira epic via acli. Falls back to the key itself."""
    try:
        result = subprocess.run(
            [
                "acli",
                "jira",
                "workitem",
                "view",
                epic_key,
                "--json",
                "--fields",
                "summary",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, list):
                data = data[0]
            fields = data.get("fields", {})
            return fields.get("summary", epic_key)
    except (json.JSONDecodeError, OSError, KeyError, IndexError):
        pass
    return epic_key


def _run_epic_search(jql: str) -> list[dict] | None:
    """Run acli epic search for a given JQL. Returns parsed list or None on failure."""
    try:
        result = subprocess.run(
            [
                "acli",
                "jira",
                "workitem",
                "search",
                "--jql",
                jql,
                "--json",
                "--fields",
                "key,summary",
                "--paginate",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        data = json.loads(result.stdout)
        if not isinstance(data, list):
            return None
        epics = []
        for item in data:
            key = item.get("key", "")
            summary = item.get("fields", {}).get("summary", key)
            if key:
                epics.append({"key": key, "summary": summary})
        return epics
    except (json.JSONDecodeError, OSError):
        return None


def fetch_open_epics() -> list[dict]:
    """Fetch all non-DONE epics from Jira via acli. Returns [{key, summary}, ...]."""
    if not shutil.which("acli"):
        return []
    projects = list(
        dict.fromkeys(config.get("jira_projects", []) + config.get("epic_projects", []))
    )
    if projects:
        quoted = ", ".join(f'"{p}"' for p in projects)
        jql = f"issuetype = Epic AND status != Done AND project in ({quoted}) ORDER BY updated DESC"
        epics = _run_epic_search(jql)
        if epics is not None:
            return epics
        # Combined query failed (likely an invalid project key) — try each individually
        vlog("Warning: combined project JQL failed, retrying per-project...")
        seen_keys: set[str] = set()
        epics = []
        for project in projects:
            jql = f'issuetype = Epic AND status != Done AND project = "{project}" ORDER BY updated DESC'
            result = _run_epic_search(jql)
            if result:
                for e in result:
                    if e["key"] not in seen_keys:
                        seen_keys.add(e["key"])
                        epics.append(e)
        return epics
    else:
        return (
            _run_epic_search(
                "issuetype = Epic AND status != Done ORDER BY updated DESC"
            )
            or []
        )


def prompt_epic(epic_key_from_cli: str | None) -> tuple[str, str] | None:
    """Prompt the user to select or enter an epic to link to the new ticket.

    Returns (epic_key, epic_summary) or None if skipped.
    """
    if epic_key_from_cli:
        epic_key = epic_key_from_cli.strip().upper()
        print(f"Fetching epic details for {epic_key}...")
        summary = fetch_epic_summary(epic_key)
        save_epic_cache(epic_key, summary)
        print(f"Epic: {epic_key}: {summary}")
        return epic_key, summary

    cache = load_epic_cache()

    epic_projects = list(
        dict.fromkeys(config.get("jira_projects", []) + config.get("epic_projects", []))
    )
    pick_label = (
        f"Pick from open epics in {', '.join(epic_projects)}"
        if epic_projects
        else "Pick from open epics"
    )

    action = ListPrompt(
        message="Link to an epic?",
        choices=[
            Choice(value="pick", name=pick_label),
            Choice(value="__other__", name="Enter an epic key manually"),
            Choice(value="__skip__", name="Skip (do not link to an epic)"),
        ],
        default="pick",
    ).execute()

    if action == "__skip__":
        return None

    if action == "__other__":
        epic_key = InputPrompt(
            message="Enter epic key (e.g. AE-42):",
            validate=lambda x: len(x.strip()) > 0,
            invalid_message="Epic key cannot be empty.",
        ).execute()
        epic_key = epic_key.strip().upper()
        print(f"Fetching epic details for {epic_key}...")
        summary = fetch_epic_summary(epic_key)
        save_epic_cache(epic_key, summary)
        print(f"Epic: {epic_key}: {summary}")
        return epic_key, summary

    # action == "pick" — fetch epics and show fuzzy picker
    print("Fetching open epics from Jira...", end="", flush=True)
    open_epics = fetch_open_epics()
    print(" done." if open_epics else " (none found)")

    cache_keys = {e["key"] for e in cache}

    choices: list = []
    for entry in cache:
        choices.append(
            Choice(
                value=entry["key"],
                name=f"[recent] {entry['key']}: {entry['summary']}",
            )
        )
    for entry in open_epics:
        if entry["key"] not in cache_keys:
            choices.append(
                Choice(
                    value=entry["key"],
                    name=f"{entry['key']}: {entry['summary']}",
                )
            )

    selection = FuzzyPrompt(
        message="Select an epic:",
        choices=choices,
        default="",
        max_height="40%",
        instruction="(↑↓ navigate, type to fuzzy-search, Enter to select)",
    ).execute()

    # Selected an epic — look up summary from cache or fetched list, then promote to top
    epic_key = selection
    all_known = cache + open_epics
    summary = next((e["summary"] for e in all_known if e["key"] == epic_key), epic_key)
    save_epic_cache(epic_key, summary)
    print(f"Epic: {epic_key}: {summary}")
    return epic_key, summary


def cmd_create(branch_name: str | None, epic: str | None = None) -> int:
    """Create a new worktree and branch."""
    print()
    print("workit — Create a new worktree")
    print()
    if not branch_name:
        branch_name = prompt_branch_name()
        if not branch_name:
            print("Aborted.")
            return 1

    # Optionally create a Jira ticket and embed its ID in the branch name
    if shutil.which("acli"):
        create_ticket = ConfirmPrompt(
            message="Create a Jira ticket for this branch?",
            default=True,
        ).execute()
        if create_ticket:
            epic_result = prompt_epic(epic)
            epic_key = epic_result[0] if epic_result else None
            try:
                jira_result = create_jira_workitem(branch_name, "", epic_key=epic_key)
            except RuntimeError:
                return 1
            if jira_result:
                issue_id, issue_url = jira_result
                branch_name = f"{issue_id}-{branch_name}"
                print(f"Branch name updated to: {branch_name}")

    branch_prefix = config.get("branch_prefix", "")
    if branch_prefix:
        branch_name = f"{branch_prefix}/{branch_name}"

    target_path = get_target_path(branch_name)

    # Verify worktree folder does not already exist
    if target_path.is_dir():
        print(f"Error: Worktree folder '{target_path}' already exists.")
        return 1

    print(f"Creating worktree for branch '{branch_name}' at '{target_path}'...")

    # Create the worktree, reusing the branch if it already exists
    if branch_exists(branch_name):
        result = run_git("worktree", "add", str(target_path), branch_name)
    else:
        result = run_git("worktree", "add", "-b", branch_name, str(target_path))
    if result.returncode != 0:
        print("Error: Failed to create worktree.")
        if result.stderr:
            print(result.stderr)
        return 1

    # Open VS Code in the new directory
    open_vscode_with_countdown(target_path)

    print("Done! Worktree is ready.")
    return 0


def cmd_remove(branch_name: str | None, force: bool = False) -> int:
    """Remove a worktree and delete its branch.

    Use this when the branch has been merged or the work is otherwise complete
    and you simply want to clean up the worktree and local branch. It does NOT
    touch any associated Jira ticket. For discarding a branch that will never
    be merged and closing its Jira ticket, use 'abandon' instead.
    """
    print()
    print("workit — Remove a worktree")
    print()
    if not branch_name:
        branch_name = prompt_select_worktree("remove")
        if not branch_name:
            return 1

    target_path = get_target_path(branch_name)

    # Warning banner
    print()
    print("WARNING: POTENTIAL PERMANENT LOSS OF WORK")
    print()
    print("  This will DESTROY the worktree and branch:")
    print(f"    Branch:   {branch_name}")
    print(f"    Path:     {target_path}")
    print()
    print("  Any uncommitted changes, untracked files, and unpushed")
    print("  commits in this worktree will be PERMANENTLY LOST.")
    print("  This action CANNOT be undone.")
    print()

    # Verify the branch exists
    if not branch_exists(branch_name):
        print(f"Error: Branch '{branch_name}' does not exist.")
        return 1

    # Verify the worktree folder exists
    if not target_path.is_dir():
        print(f"Error: Worktree folder '{target_path}' does not exist.")
        return 1

    # Check PR status
    if shutil.which("gh"):
        pr_result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                branch_name,
                "--state",
                "all",
                "--json",
                "number,title,state,url",
            ],
            capture_output=True,
            text=True,
        )
        if pr_result.returncode == 0 and pr_result.stdout.strip() not in ("", "[]"):
            import json

            prs = json.loads(pr_result.stdout)
            for pr in prs:
                state = pr.get("state", "UNKNOWN")
                number = pr.get("number", "?")
                title = pr.get("title", "")
                url = pr.get("url", "")
                icon = (
                    "[merged]"
                    if state == "MERGED"
                    else "[open]  "
                    if state == "OPEN"
                    else "[closed]"
                )
                print(f"  {icon} PR #{number} ({state}): {title}")
                if url:
                    print(f"     {url}")
            print()
        else:
            print("  No pull request found for this branch.")
            print()

    # Check for unpushed commits
    unpushed = get_unpushed_commits(branch_name)
    if unpushed:
        print(f"DANGER: UNPUSHED COMMITS DETECTED ON '{branch_name}'!")
        print()
        print("  The following commits have NOT been pushed to any remote:")
        print()
        for line in unpushed:
            print(f"    {line}")
        print()
        print("  Deleting this branch will PERMANENTLY DESTROY these commits.")
        print(f"  Consider pushing first: git push origin {branch_name}")
        print()

    # Check for uncommitted changes
    status = get_worktree_status(target_path)
    if status:
        print("DANGER: UNCOMMITTED CHANGES in the worktree!")
        print()
        for line in status:
            print(f"    {line}")
        print()
        print("  These files will be PERMANENTLY DELETED.")
        print()

    # Step 1: Remove the worktree
    print(f"Step 1: Remove worktree at '{target_path}'")
    if not force:
        confirm = ConfirmPrompt(
            message="Are you sure you want to remove this worktree?",
            default=False,
        ).execute()
        if not confirm:
            print("Aborted.")
            return 0

    print("  Removing worktree...")
    result = run_git("worktree", "remove", "--force", str(target_path))
    if result.returncode != 0:
        print("Error: Failed to remove worktree.")
        if result.stderr:
            print(result.stderr)
        return 1
    print("  Worktree removed.")
    print()

    # Step 2: Delete the local branch
    print(f"Step 2: Delete local branch '{branch_name}'")
    print("  This will permanently delete the branch and all its commits")
    print("     that have not been pushed or merged elsewhere.")
    if not force:
        confirm = ConfirmPrompt(
            message="Are you sure you want to delete this branch?",
            default=False,
        ).execute()
        if not confirm:
            print("Aborted. Note: the worktree has already been removed.")
            print(
                f"The branch '{branch_name}' still exists and can be checked out normally."
            )
            return 0

    print("  Deleting branch...")
    result = run_git("branch", "-D", branch_name)
    if result.returncode != 0:
        print("Error: Failed to delete branch.")
        if result.stderr:
            print(result.stderr)
        return 1
    print("  Branch deleted.")
    print()

    print(f"Done. Worktree and branch '{branch_name}' have been removed.")
    return 0


def cmd_abandon(branch_name: str | None) -> int:
    """Abandon a worktree: delete the worktree, branch, and associated Jira ticket.

    Use this when a line of work is no longer viable and should be discarded
    entirely — the worktree, branch, and Jira ticket are all removed. Each
    deletion is confirmed separately. For cleaning up after a successful merge
    without touching Jira, use 'remove' instead.
    """
    print()
    print("workit — Abandon a worktree")
    print()
    if not branch_name:
        branch_name = prompt_select_worktree("abandon")
        if not branch_name:
            return 1

    target_path = get_target_path(branch_name)
    ticket_id = extract_ticket_id(branch_name)

    if not branch_exists(branch_name):
        print(f"Error: Branch '{branch_name}' does not exist.")
        return 1

    # Show summary of what will be destroyed
    print("This will PERMANENTLY DESTROY:")
    print(f"  Worktree:    {target_path}")
    print(f"  Branch:      {branch_name}")
    if ticket_id:
        jira_base_url = config.get("jira_base_url", "")
        ticket_url = (
            f"{jira_base_url}/browse/{ticket_id}" if jira_base_url else ticket_id
        )
        print(f"  Jira ticket: {ticket_id} — {ticket_url}")
    else:
        print("  Jira ticket: (none detected in branch name)")
    print()

    # Step 1: Remove the worktree
    worktree_exists = target_path.is_dir()
    if worktree_exists:
        print(f"Step 1: Remove worktree at '{target_path}'")
        confirm = ConfirmPrompt(
            message="Delete this worktree?",
            default=False,
        ).execute()
        if not confirm:
            print("Aborted.")
            return 0
        result = run_git("worktree", "remove", "--force", str(target_path))
        if result.returncode != 0:
            print("Error: Failed to remove worktree.")
            if result.stderr:
                print(result.stderr)
            return 1
        print("  Worktree removed.")
        print()
    else:
        print(f"Step 1: Worktree at '{target_path}' does not exist, skipping.")
        print()

    # Step 2: Delete the local branch
    print(f"Step 2: Delete local branch '{branch_name}'")
    confirm = ConfirmPrompt(
        message="Delete this branch?",
        default=False,
    ).execute()
    if not confirm:
        print("Aborted. Note: the worktree has already been removed (if it existed).")
        return 0
    result = run_git("branch", "-D", branch_name)
    if result.returncode != 0:
        print("Error: Failed to delete branch.")
        if result.stderr:
            print(result.stderr)
        return 1
    print("  Branch deleted.")
    print()

    # Step 3: Delete the Jira ticket
    if ticket_id:
        if shutil.which("acli"):
            print(f"Step 3: Delete Jira ticket '{ticket_id}'")
            confirm = ConfirmPrompt(
                message=f"Delete Jira ticket {ticket_id}?",
                default=False,
            ).execute()
            if confirm:
                result = subprocess.run(
                    ["acli", "jira", "workitem", "delete", "--key", ticket_id],
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    print(f"Warning: Failed to delete Jira ticket {ticket_id}.")
                    output = result.stdout.strip() or result.stderr.strip()
                    if output:
                        print(output)
                else:
                    print(f"  Jira ticket {ticket_id} deleted.")
            else:
                print(f"  Jira ticket {ticket_id} not deleted.")
            print()
        else:
            print(
                f"Step 3: acli not found — Jira ticket '{ticket_id}' was not deleted."
            )
            print()
    else:
        print("Step 3: No Jira ticket detected in branch name — skipping.")
        print()

    print(f"Done. Worktree and branch '{branch_name}' have been abandoned.")
    return 0


def cmd_pr(
    branch_name: str | None,
    in_worktree: bool = False,
    from_worktree: bool = False,
    jira_key: str | None = None,
    yes: bool = False,
    ai: bool = True,
    merge: bool = False,
) -> int:
    """Create a pull request for the specified worktree branch."""
    print()
    print("workit — Create a pull request")
    print()
    if merge and not yes:
        print("Error: --merge requires --yes.")
        return 1

    # Verify gh CLI is available
    if not shutil.which("gh"):
        print("Error: GitHub CLI (gh) is not installed.")
        print("Install it from: https://cli.github.com/")
        return 1

    # Verify gh CLI is authenticated
    auth_result = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True
    )
    if auth_result.returncode != 0:
        print("Error: GitHub CLI is not authenticated.")
        print("Run: gh auth login")
        return 1

    if not branch_name:
        if in_worktree:
            branch_name = run_git("branch", "--show-current").stdout.strip()
            if not branch_name:
                print("Error: Could not determine current branch.")
                return 1
        else:
            branch_name = prompt_select_worktree("create a PR for")
            if not branch_name:
                return 1

    # Guard: refuse to create a PR from the default branch
    default_branch = (
        run_git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        .stdout.strip()
        .removeprefix("origin/")
        or "main"
    )
    if branch_name == default_branch:
        print(f"Error: Cannot create a PR from the default branch '{default_branch}'.")
        print("Switch to or specify a feature branch.")
        return 1

    target_path = Path.cwd() if in_worktree else get_target_path(branch_name)

    # Verify the branch exists
    if not branch_exists(branch_name):
        print(f"Error: Branch '{branch_name}' does not exist.")
        return 1

    # Verify the worktree folder exists (skip when already running from it)
    if not in_worktree and not target_path.is_dir():
        print(f"Error: Worktree folder '{target_path}' does not exist.")
        return 1

    # Check for uncommitted changes
    status = get_worktree_status(target_path)
    if status:
        print("Error: Uncommitted changes detected in the worktree:")
        print()
        for line in status:
            print(f"  {line}")
        print()
        print("Please commit or stash your changes before creating a PR.")
        return 1

    # Check for unpushed commits
    unpushed = get_unpushed_commits(branch_name)
    if unpushed:
        print(f"Unpushed commits detected on '{branch_name}':")
        print()
        for line in unpushed:
            print(f"  {line}")
        print()
        print("Pushing branch to origin...")
        result = run_git("push", "-u", "origin", branch_name)
        if result.returncode != 0:
            print("Error: Failed to push branch.")
            if result.stderr:
                print(result.stderr)
            return 1
        print()

    # Determine Jira ticket ID from branch name or --key override
    if jira_key:
        issue_id: str | None = jira_key
    else:
        issue_id = extract_ticket_id(branch_name)
        if not issue_id:
            raw = InputPrompt(
                message="Enter Jira ticket ID (e.g. PROJ-123), or press Enter to skip:",
            ).execute()
            issue_id = raw.strip().upper() or None

    issue_url: str | None = None
    if issue_id:
        jira_base_url = config.get("jira_base_url", "")
        issue_url = f"{jira_base_url}/browse/{issue_id}" if jira_base_url else None
        print(f"Jira ticket: {issue_id}" + (f" — {issue_url}" if issue_url else ""))
        print()

    # Open VS Code for the user to write/paste title and summary
    placeholder = f"Title for {branch_name}\n\nReplace this text with your summary content, then save and close this file tab to continue.\n"
    if ai:
        print("Generating AI summary via copilot CLI...")
        print()
        try:
            repo = get_repo_slug()
            ai_output = generate_summary(branch_name, repo, cwd=target_path)
            initial_content = ai_output + "\n"
        except (RuntimeError, FileNotFoundError) as e:
            print(f"Warning: AI summary failed ({e}). Falling back to template.")
            initial_content = placeholder
    else:
        initial_content = placeholder
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", prefix="workit_pr_", delete=False
    ) as tmp:
        tmp.write(initial_content)
        tmp_path = tmp.name

    while True:
        print("Opening VS Code — write the PR title on the first line, summary below.")
        print()
        subprocess.run(["code", "--wait", tmp_path])

        content = Path(tmp_path).read_text().strip()

        if not content:
            Path(tmp_path).unlink(missing_ok=True)
            print("Aborted: no content provided.")
            return 1

        if content == placeholder.strip():
            action = ListPrompt(
                message="The template content was not changed. What would you like to do?",
                choices=[
                    Choice("edit", "Edit it again"),
                    Choice("abort", "Abort"),
                ],
            ).execute()
            if action == "abort":
                Path(tmp_path).unlink(missing_ok=True)
                print("Aborted.")
                return 1
            # loop back and re-open the editor
            continue

        action = ListPrompt(
            message="Summary ready. What would you like to do?",
            choices=[
                Choice("continue", "Continue with this summary"),
                Choice("edit", "Edit again"),
                Choice("abort", "Abort"),
            ],
            default="continue",
        ).execute()
        if action == "abort":
            Path(tmp_path).unlink(missing_ok=True)
            print("Aborted.")
            return 1
        if action == "edit":
            continue

        break

    Path(tmp_path).unlink(missing_ok=True)

    if not content:
        print("Aborted: no content provided.")
        return 1

    lines = content.splitlines()
    title = lines[0].strip().lstrip("#").strip()
    summary = "\n".join(lines[1:]).strip()

    if issue_id:
        title = f"[{issue_id}] {title}"
        if issue_url:
            summary = f"{summary}\n\n{issue_url}"

    print()

    # Create the PR
    print(f"Creating pull request for branch '{branch_name}'...")
    print()
    pr_result = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--head",
            branch_name,
            "--title",
            title,
            "--body",
            summary,
        ],
        capture_output=True,
        text=True,
    )
    if pr_result.returncode != 0:
        print("Error: Failed to create PR.")
        if pr_result.stderr:
            print(pr_result.stderr)
        return pr_result.returncode

    pr_url = pr_result.stdout.strip()
    print(f"PR created: {pr_url}")
    print()

    # Add PR URL as a comment on the Jira workitem
    if issue_id:
        pr_number = pr_url.rstrip("/").rsplit("/", 1)[-1]
        repo_slug = get_repo_slug()
        pr_comment = json.dumps(
            {
                "version": 1,
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "PR: "},
                            {
                                "type": "text",
                                "text": f"{repo_slug} #{pr_number}",
                                "marks": [{"type": "link", "attrs": {"href": pr_url}}],
                            },
                        ],
                    }
                ],
            }
        )
        comment_result = subprocess.run(
            [
                "acli",
                "jira",
                "workitem",
                "comment",
                "create",
                "--key",
                issue_id,
                "--body",
                pr_comment,
            ],
            capture_output=True,
            text=True,
        )
        if comment_result.returncode != 0:
            print(f"Warning: Failed to comment on Jira workitem {issue_id}.")
            if comment_result.stderr:
                print(comment_result.stderr)
        else:
            print(f"PR URL added as comment on {issue_id}.")
        print()

    # Post-creation menu
    if merge:
        action = "merge"
    else:
        merge_label = (
            "Squash-and-merge, then close and delete worktree and branch (no confirmations due to --yes)"
            if yes
            else "Squash-and-merge, then close and delete worktree and branch (with confirmations)"
        )
        action = ListPrompt(
            message="What would you like to do?",
            choices=[
                Choice(
                    value="open",
                    name="Open PR in browser (if you want to assign reviewers, add labels, or merge manually)",
                ),
                Choice(value="merge", name=merge_label),
                Choice(value="done", name="Done (do nothing)"),
            ],
            default="done",
        ).execute()

    if action == "open":
        subprocess.run(["gh", "pr", "view", "--head", branch_name, "--web"])
    elif action == "merge":
        print(f"Squash-merging PR for '{branch_name}'...")
        merge_result = subprocess.run(["gh", "pr", "merge", branch_name, "--squash"])
        if merge_result.returncode != 0:
            print("Error: Failed to squash-and-merge the PR.")
            return merge_result.returncode
        append_status_report(title, summary)
        if issue_id:
            print(f"Closing Jira workitem {issue_id}...")
            subprocess.run(
                [
                    "acli",
                    "jira",
                    "workitem",
                    "transition",
                    "--key",
                    issue_id,
                    "--status",
                    "Closed",
                ],
            )
        if not in_worktree:
            if yes:
                cmd_remove(branch_name, force=True)
                if from_worktree:
                    print("You can now close the VS Code window for this worktree.")
                run_git("pull", capture=False)
            else:
                cleanup = ConfirmPrompt(
                    message=f"Delete worktree and branch '{branch_name}'?",
                    default=True,
                ).execute()
                if cleanup:
                    cmd_remove(branch_name)
                    if from_worktree:
                        print("You can now close the VS Code window for this worktree.")
                do_pull = ConfirmPrompt(
                    message="Run git pull?",
                    default=True,
                ).execute()
                if do_pull:
                    run_git("pull", capture=False)

    return 0


def cmd_code(branch_name: str | None) -> int:
    """Open an existing worktree in a new VS Code window."""
    print()
    print("workit — Open a worktree in VS Code")
    print()
    if not branch_name:
        branch_name = prompt_select_worktree("open in VS Code")
        if not branch_name:
            return 1

    target_path = get_target_path(branch_name)

    if not target_path.is_dir():
        print(f"Error: Worktree folder '{target_path}' does not exist.")
        return 1

    print(f"Opening worktree '{branch_name}' in VS Code...")
    subprocess.run(["code", str(target_path), "--new-window"])
    return 0


def cmd_summary(branch_name: str | None, preset_prompt: str | None = None) -> int:
    """Run an AI summary prompt against a branch and print the output."""
    print()
    print("workit — AI summary")
    print()
    if not branch_name:
        # Default to current branch
        branch_name = run_git("branch", "--show-current").stdout.strip()
        if not branch_name:
            print(
                "Error: Could not determine current branch. Pass a branch name explicitly."
            )
            return 1
        print(f"Using current branch: {branch_name}")

    repo = get_repo_slug()
    print(f"Repo:   {repo}")
    print(f"Branch: {branch_name}")
    print()

    if preset_prompt:
        prompt_name = preset_prompt
        print(f"Using prompt: {prompt_name}")
    else:
        prompts = _get_available_prompts()
        if len(prompts) == 1:
            prompt_name = next(iter(prompts))
            print(f"Using prompt: {prompt_name}")
        else:
            prompt_name = ListPrompt(
                message="Select a prompt:",
                choices=list(prompts.keys()),
            ).execute()

    print()
    try:
        output = generate_summary(branch_name, repo, prompt_name)
    except (RuntimeError, FileNotFoundError) as e:
        print(f"Error: {e}")
        return 1

    print()
    print(f"--- {prompt_name} ---")
    print()
    print(output)
    print()
    return 0


def _get_merged_prs_last_30_days() -> list[dict]:
    """Return merged PRs from the last 30 days, newest first."""
    import datetime

    result = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "merged",
            "--limit",
            "200",
            "--json",
            "number,title,mergedAt",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
    prs = json.loads(result.stdout)
    recent = [
        pr
        for pr in prs
        if pr.get("mergedAt")
        and datetime.datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00"))
        >= cutoff
    ]
    recent.sort(key=lambda p: p["mergedAt"], reverse=True)
    return recent


def cmd_post_pr(
    pr_number: str | None,
    jira: bool = False,
    jira_key: str | None = None,
) -> int:
    """Summarize a merged PR and append the result to the status report."""
    print()
    print("workit — Post-PR Summary")
    print()

    if not shutil.which("gh"):
        print("Error: GitHub CLI (gh) is not installed.")
        print("Install it from: https://cli.github.com/")
        return 1

    if not pr_number:
        print("Fetching merged PRs from the last 30 days...")
        prs = _get_merged_prs_last_30_days()
        if not prs:
            print("No merged PRs found in the last 30 days.")
            return 1
        if len(prs) == 1:
            pr_number = str(prs[0]["number"])
            print(f"Auto-selected PR #{pr_number}: {prs[0]['title']}")
        else:
            choices = [
                Choice(
                    value=str(pr["number"]),
                    name=f"#{pr['number']} — {pr['title']} ({pr['mergedAt'][:10]})",
                )
                for pr in prs
            ]
            pr_number = ListPrompt(
                message="Select a merged PR to summarize:",
                choices=choices,
            ).execute()

    assert isinstance(pr_number, str), "pr_number must be set by this point"
    print(f"Summarizing PR #{pr_number}...")
    print()

    repo = get_repo_slug()
    try:
        output = generate_summary(
            branch="",
            repo=repo,
            prompt_name=_POST_PR_PROMPT_NAME,
            pr_number=pr_number,
        )
    except (RuntimeError, FileNotFoundError) as e:
        print(f"Error: {e}")
        return 1

    # Open VS Code for the user to review and refine the AI output
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", prefix="workit_post_pr_", delete=False
    ) as tmp:
        tmp.write(output + "\n")
        tmp_path = tmp.name

    while True:
        print(
            "Opening VS Code — review and edit the summary, then save and close the tab to continue."
        )
        print()
        subprocess.run(["code", "--wait", tmp_path])

        content = Path(tmp_path).read_text().strip()

        if not content:
            Path(tmp_path).unlink(missing_ok=True)
            print("Aborted: no content provided.")
            return 1

        action = ListPrompt(
            message="Summary ready. What would you like to do?",
            choices=[
                Choice("continue", "Continue with this summary"),
                Choice("edit", "Edit again"),
                Choice("abort", "Abort"),
            ],
            default="continue",
        ).execute()
        if action == "abort":
            Path(tmp_path).unlink(missing_ok=True)
            print("Aborted.")
            return 1
        if action == "edit":
            continue

        break

    Path(tmp_path).unlink(missing_ok=True)

    lines = content.splitlines()
    pr_title = lines[0].strip()
    summary = "\n".join(lines[1:]).strip()

    append_status_report(pr_title, summary)

    # Optionally create a Jira workitem
    if jira:
        try:
            jira_result = create_jira_workitem(pr_title, summary, jira_key=jira_key)
        except RuntimeError:
            return 1
        if jira_result:
            issue_id, issue_url = jira_result
            print(f"Jira workitem created: {issue_id} — {issue_url}")
            # Add PR URL as a comment on the Jira workitem
            pr_url_result = subprocess.run(
                ["gh", "pr", "view", pr_number, "--json", "url", "-q", ".url"],
                capture_output=True,
                text=True,
            )
            if pr_url_result.returncode == 0 and pr_url_result.stdout.strip():
                pr_url = pr_url_result.stdout.strip()
                repo_slug = get_repo_slug()
                pr_comment = json.dumps(
                    {
                        "version": 1,
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "PR: "},
                                    {
                                        "type": "text",
                                        "text": f"{repo_slug} #{pr_number}",
                                        "marks": [
                                            {"type": "link", "attrs": {"href": pr_url}}
                                        ],
                                    },
                                ],
                            }
                        ],
                    }
                )
                subprocess.run(
                    [
                        "acli",
                        "jira",
                        "workitem",
                        "comment",
                        "create",
                        "--key",
                        issue_id,
                        "--body",
                        pr_comment,
                    ],
                    capture_output=True,
                    text=True,
                )
            # Close the newly created ticket
            print(f"Closing Jira ticket {issue_id}...")
            close_result = subprocess.run(
                [
                    "acli",
                    "jira",
                    "workitem",
                    "transition",
                    "--key",
                    issue_id,
                    "--status",
                    "Closed",
                ],
            )
            if close_result.returncode == 0:
                print(f"Jira ticket {issue_id} closed.")
            else:
                print(f"Warning: Failed to close Jira ticket {issue_id}.")

    print()
    print(f"PR #{pr_number}: {pr_title}")
    print()

    return 0


def cmd_check() -> int:
    """Check that all required tooling is installed and authenticated."""
    print()
    print("workit — Tooling check")
    print()

    all_ok = True

    # ── gh (GitHub CLI) ──────────────────────────────────────────────────────
    print("gh  (GitHub CLI — required)")
    gh_path = shutil.which("gh")
    if not gh_path:
        all_ok = False
        print("  ✗ Not installed")
        print("    Install: https://cli.github.com/")
        print("      Linux:  sudo apt install gh   |   brew install gh")
        print("      macOS:  brew install gh")
        print("    Auth:    gh auth login")
    else:
        print(f"  ✓ Installed: {gh_path}")
        auth_result = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True
        )
        combined = (auth_result.stdout + auth_result.stderr).strip()
        if auth_result.returncode == 0:
            # Show each "Logged in to …" line (one per account)
            logged_in_lines = [
                line.strip()
                for line in combined.splitlines()
                if "logged in to" in line.lower()
            ]
            if logged_in_lines:
                for line in logged_in_lines:
                    print(f"  ✓ {line.lstrip('✓ ')}")
            else:
                print("  ✓ Authenticated")
        else:
            all_ok = False
            print("  ✗ Not authenticated")
            print("    Run: gh auth login")
    print()

    # ── copilot (gh extension, requires gh) ──────────────────────────────────
    print("copilot  (gh extension — required for AI summaries)")
    copilot_path = shutil.which("copilot")
    if copilot_path:
        print(f"  ✓ Installed: {copilot_path}")
    else:
        # copilot may be installed as an extension but not yet on PATH
        ext_installed = False
        if gh_path:
            ext_result = subprocess.run(
                ["gh", "extension", "list"], capture_output=True, text=True
            )
            ext_installed = "copilot" in ext_result.stdout.lower()
        if ext_installed:
            print("  ⚠ Installed as gh extension but 'copilot' is not on PATH")
            print(
                "    workit invokes 'copilot' directly — ensure gh extensions are on PATH."
            )
            print(
                "    Tip: add $(gh extension path) to your PATH, or create a wrapper script."
            )
        else:
            all_ok = False
            print("  ✗ Not installed")
            print("    Install: gh extension install github/gh-copilot")
            print("    Auth:    Inherits gh authentication — no separate login needed")
    # Auth for copilot is the same as gh; only check if copilot is (or may be) present
    if copilot_path or (gh_path and ext_installed):
        if gh_path:
            auth_result = subprocess.run(
                ["gh", "auth", "status"], capture_output=True, text=True
            )
            if auth_result.returncode == 0:
                print("  ✓ Authenticated (inherits gh auth)")
            else:
                all_ok = False
                print("  ✗ Not authenticated (requires gh auth)")
                print("    Run: gh auth login")
    print()

    # ── acli (Atlassian CLI) — optional ─────────────────────────────────────
    print("acli  (Atlassian CLI — optional, enables Jira integration)")
    acli_path = shutil.which("acli")
    if not acli_path:
        print("  ✗ Not installed  (Jira features will be skipped)")
        print(
            "    Install: https://developer.atlassian.com/cloud/acli/guides/install-linux/"
        )
        print("    Auth:    After installing, set your Atlassian API token:")
        print(
            "               acli config set --url https://<your-org>.atlassian.net \\"
        )
        print("                               --token <your-api-token>")
        print(
            "             Tokens: https://id.atlassian.com/manage-profile/security/api-tokens"
        )
    else:
        print(f"  ✓ Installed: {acli_path}")
        # Probe auth with a lightweight search; any valid authed response is fine
        probe = subprocess.run(
            [
                "acli",
                "jira",
                "workitem",
                "search",
                "--jql",
                "issuetype = Epic",
                "--limit",
                "1",
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        combined = (probe.stdout + probe.stderr).strip().lower()
        if probe.returncode == 0:
            print("  ✓ Authenticated")
        elif any(
            kw in combined
            for kw in (
                "unauthorized",
                "authentication",
                "token",
                "login",
                "403",
                "401",
                "credential",
            )
        ):
            print("  ✗ Not authenticated")
            print("    Run: acli config set --url https://<your-org>.atlassian.net \\")
            print("                         --token <your-api-token>")
            print(
                "    Tokens: https://id.atlassian.com/manage-profile/security/api-tokens"
            )
        else:
            print("  ⚠ Could not verify authentication (probe query failed)")
            print(f"    Error: {(probe.stdout + probe.stderr).strip()[:120]}")
    print()

    if all_ok:
        print("All required tools are installed and authenticated.")
    else:
        print("One or more required tools need attention. See above for details.")

    return 0 if all_ok else 1


# --- Main ---

SUBCOMMANDS = {
    "create": cmd_create,
    "new": cmd_create,
    "remove": cmd_remove,
    "delete": cmd_remove,
    "del": cmd_remove,
    "rm": cmd_remove,
    "abandon": cmd_abandon,
    "pr": cmd_pr,
    "code": cmd_code,
    "edit": cmd_code,
    "summary": cmd_summary,
    "sum": cmd_summary,
    "summarize": cmd_summary,
    "post-pr": cmd_post_pr,
    "prs": cmd_post_pr,
    "post": cmd_post_pr,
    "check": cmd_check,
}


def cmd_list() -> int:
    """List existing worktrees."""
    worktrees = get_existing_worktrees()
    if worktrees:
        print("Existing worktrees:")
        for wt in worktrees:
            print(f"  • {wt}")
    else:
        print("No existing worktrees.")
    return 0


def cmd_config() -> int:
    """Open ~/.config/workit/config.json in VS Code.

    Creates the file with default values if it does not yet exist.
    The file is opened without blocking — the terminal returns immediately
    so the user can continue working while editing the config.
    """
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not _CONFIG_FILE.exists():
        with _CONFIG_FILE.open("w") as f:
            json.dump(_CONFIG_DEFAULTS, f, indent=2)
        print(f"Created default config: {_CONFIG_FILE}")
    subprocess.run(["code", str(_CONFIG_FILE)])
    return 0


def cmd_tldr() -> int:
    """Print a brief getting-started guide."""
    print(
        textwrap.dedent("""\
        workit — quick-start guide

        SETUP
          1. Run 'workit config' to create and open ~/.config/workit/config.json.
          2. Set jira_projects to your Jira project keys (e.g. ["AE", "MAP"]).
          3. Optionally set branch_prefix (e.g. "kjm") to namespace your branches.

        DAILY WORKFLOW
          workit create [name]   Start a new branch + worktree (opens VS Code).
                                 Optionally creates a Jira ticket and links it to an epic.
          workit pr [name]       Push, AI-draft a PR description, create the PR,
                                 link it to Jira, and optionally merge + clean up.

        LESS COMMON
          workit remove [name]   Clean up after a merged branch (worktree + local branch).
          workit abandon [name]  Discard unwanted work (worktree + branch + Jira ticket).

        OTHER COMMANDS
          workit list            List all open worktrees.
          workit open [name]     Open an existing worktree in a new VS Code window.
          workit summary [name]  AI-summarize a branch (PR, commit, working copy, etc.).
          workit config          Open config.json in VS Code.
          workit help            Show full documentation.

        Run 'workit --help' or 'workit help' for full details.
    """)
    )
    return 0


def main() -> int:
    global _verbose
    # Verify we're in a git repository
    result = run_git("rev-parse", "--is-inside-work-tree")
    if result.returncode != 0:
        print("Error: Not a git repository. Run this script from within a git repo.")
        return 1

    # Detect if running from a linked worktree
    git_dir = run_git("rev-parse", "--git-dir").stdout.strip()
    git_common_dir = run_git("rev-parse", "--git-common-dir").stdout.strip()
    in_worktree = os.path.realpath(git_dir) != os.path.realpath(git_common_dir)
    worktree_branch: str | None = None

    if in_worktree:
        # Resolve the main repo root (parent of the common .git dir) and re-run from there
        main_repo_root = Path(os.path.realpath(git_common_dir)).parent
        worktree_branch = run_git("branch", "--show-current").stdout.strip() or None
        print(f"(Running pr from main repo: {main_repo_root})")
        os.chdir(main_repo_root)
        in_worktree = False

    parser = argparse.ArgumentParser(
        prog="workit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
            workit — git worktree manager with Jira and GitHub PR integration
                                    
            This tool automates the creation and cleanup of git worktrees for 
            feature branches, and streamlines the PR creation process with  
            Jira ticket creation and closure using AI-generated summaries.

            WORKFLOW
              1. Run 'workit create <branch>' from your main repo checkout.
                 A new worktree is created at ../<repo>-worktrees/<branch> and
                 opened in a new VS Code window. During creation you can optionally
                 create a Jira ticket and link it to an epic — epics are fetched live
                 from Jira (filtered by jira_projects + epic_projects) and presented
                 in a fuzzy picker, with recently used epics shown at the top.
              2. Do your work in that VS Code window and remember to commit and 
                 push your changes.
              3. When ready to ship, run 'workit pr' from the main repo checkout or
                 directly from inside the worktree — both work identically, including
                 the option to clean up the worktree, branch, and pull after merging.
                 When run from a worktree, workit automatically switches context to the
                 main repo root before proceeding.
              4. The pr flow: pushes if needed → opens VS Code for you to write
                 the title/summary → creates a Jira ticket → opens the GitHub PR,
                 and associates the PR and Jira ticket with each other.
              5. After the PR merges, choose "Squash-and-merge" in the post-PR
                 menu to close the Jira ticket, clean up the worktree, and pull your changes
                 into your main working copy.

            AI SUMMARIES
              The 'summary' subcommand (aliases: sum, summarize) runs a copilot-powered
              prompt and prints the result. Four built-in prompts
              are available and can be selected via flags or an interactive menu:

                -b / --branch           Summarize all commits on the branch (PR description)
                -c / --commit           Summarize the last commit on the branch
                -u / --uncommitted      Summarize uncommitted (unstaged) working-copy changes
                -s / --staged           Summarize staged (index) changes
                                        (use to generate commits messages before committing)

              Custom prompts can be added by placing *.md files in:
                ~/.config/workit/prompts/
                                    
              The filename (underscores/dashes replaced with spaces) becomes the prompt name.
              Custom prompts appear alongside the built-ins in the interactive menu.

              The 'pr' subcommand auto-generates the initial PR description using the
              "PR Branch Summary" prompt before opening VS Code for editing. Pass --no-ai
              to skip AI generation and use a blank template instead.

            CONFIGURATION
              ~/.config/workit/config.json   — runtime settings (see defaults below)
              ~/.config/workit/prompts/      — directory for custom prompt *.md files

            CONFIG KEYS
              branch_prefix    Prepended to every new branch: "kjm" → "kjm/<branch>"
              jira_projects    List of Jira project keys used for ticket creation and
                               epic lookup (combined with epic_projects for epic search)
              epic_projects    Additional Jira project keys to include when fetching open
                               epics (merged with jira_projects; defaults to jira_projects
                               if not set)
              jira_assignee    Auto-assign new Jira tickets to this user
              jira_base_url    Base URL of your Atlassian instance (e.g. https://org.atlassian.net)
                               Used to construct browse links: <jira_base_url>/browse/<ticket-id>
              status_report    Path to append merged-PR summaries to

            DEPENDENCIES (make sure you have these installed and authenticated)
              gh     GitHub CLI, includes copilot CLI for AI summaries and pr creation  
                     (https://cli.github.com)
              acli   Atlassian CLI — optional, enables Jira integration, uses Atlassian 
                     API Token authentication
                     (https://developer.atlassian.com/cloud/acli/guides/install-linux/)

            ABOUT GIT WORKTREES
              A git worktree lets you check out multiple branches of a repository
              simultaneously, each in its own directory, all sharing a single .git
              database. This means you can actively work on a feature branch without
              disturbing your main checkout — no stashing, no context switching.

              workit places each worktree at:
                ../<repo-name>-worktrees/<branch-name>/

              So if your repo lives at ~/code/myapp, worktrees appear as siblings:
                ~/code/myapp-worktrees/feature/my-feature/
                ~/code/myapp-worktrees/fix/urgent-bug/

              Each worktree is opened in its own VS Code window, giving you a clean
              workspace with its own terminal, extensions state, and editor tabs.

            HOW THE PR FLOW WORKS
              1. workit create <branch>  (optionally: --epic AE-42)
                 Prompts to create a Jira ticket for the branch. If created, the ticket
                 ID is embedded at the start of the branch name:
                   e.g. 'my-feature' → 'AE-123-my-feature' (or 'kjm/AE-123-my-feature' with prefix).
                 You can optionally link the ticket to a Jira epic via a fuzzy picker.
                 Open epics are fetched live from Jira (projects = jira_projects + epic_projects,
                 deduped). Recently used epics appear at the top prefixed with [recent].
                 The last 5 selected epics are cached for quick re-use.
                 Opens the new worktree in a new VS Code window after a 3-second countdown.
              2. Do your work. Commit as normal inside that window.
              3. workit pr  (run from the main repo checkout or from inside the worktree)
                 When run from inside a worktree, workit automatically detects the main
                 repo root and switches to it — the full pr flow runs as if you were there,
                 including post-merge cleanup. After the worktree is deleted, workit reminds
                 you to close the VS Code window.
                 a. Pushes any unpushed commits to origin.
                 b. Extracts the Jira ticket ID from the branch name automatically.
                    If none is found, prompts you to enter one (or skip).
                    Use --key PROJ-123 to override.
                 c. Runs the "PR Branch Summary" AI prompt via the copilot CLI and opens
                    the result in VS Code for you to review and edit. The first line
                    becomes the PR title (leading '#' stripped); everything below becomes
                    the PR body. The title is prefixed with the ticket ID: [AE-123] Title.
                    Use --no-ai to skip AI generation and start from a blank template.
                 d. Adds a comment on the Jira ticket with the PR URL, linking them.
                 e. Opens the GitHub PR via the gh CLI.
                 f. Offers to squash-merge immediately, close the Jira ticket, clean up
                    the worktree and branch, and run git pull on your main checkout.

            WHY WORKIT?
              Modern software development involves constant context switching — a critical
              bug comes in while you are mid-feature, a colleague needs a review, a spike
              needs to be thrown away. Without tooling, each switch means stashing or
              committing half-baked work, checking out a different branch, losing your
              editor state, and then reversing all of that when you come back.

              workit eliminates that overhead entirely. Each piece of work lives in its
              own directory and its own VS Code window. Switching "context" is just
              switching windows — your editor tabs, terminal history, and file state are
              exactly where you left them. Start a hotfix while your feature build is
              running. Review a PR while your tests are executing. Close a worktree the
              moment a branch merges and never think about it again.

              The PR flow compounds this benefit. Without workit, shipping a feature
              requires: push the branch, open GitHub, write a title and description,
              create a Jira ticket, paste the PR link into the ticket, merge, delete the
              remote branch, delete the local branch, pull main. With workit, that entire
              sequence is a single 'workit pr' invocation — AI drafts the description,
              Jira ticket is created and linked automatically, and cleanup happens in one
              confirmation step.

              The result: less time managing infrastructure, more time writing code.

            TAKING IT FURTHER: GIT REPO WINDOW COLORS
              workit opens each worktree in its own VS Code window — but once you have
              several windows open, they can start to look identical. The Git Repo Window
              Colors extension (GRWC) solves this by automatically applying a unique color
              scheme to each VS Code window based on the repository and branch it contains.

              With GRWC, the title bar, activity bar, status bar, and editor tabs are all
              color-coded so you can instantly identify which window holds which project
              and branch — at a glance, even from the taskbar thumbnail.

              Key features that pair well with workit:
                • Per-repository colors — each repo gets a distinct base color
                • Per-branch colors — feature branches, hotfixes, and main can each
                  have their own color within a repo
                • Auto-add branch rules — new branches automatically get a visually
                  distinct color, requiring zero manual setup.  This is perfect for workit 
                  since each new worktree starts with a new branch.
                • Sync-compatible — color rules follow you across machines

              Together, workit and GRWC give you a complete parallel-work environment:
              workit handles the branch, worktree, Jira ticket, and PR lifecycle, while
              GRWC ensures you always know exactly where you are just by looking at the
              window frame.

              Install GWRC from the VSCode Extension Marketplace.
        """),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose/debug output",
    )
    subparsers = parser.add_subparsers(dest="subcommand", metavar="subcommand")

    # create / new
    for name in ("create", "new"):
        p = subparsers.add_parser(name, help="Create a new worktree and branch")
        p.add_argument(
            "branch", nargs="?", default=None, help="Branch name (prompted if omitted)"
        )
        p.add_argument(
            "--epic",
            metavar="EPIC_KEY",
            default=None,
            help="Jira epic key to link the new ticket to (e.g. AE-42); presented as a menu if omitted",
        )

    # remove / delete / del / rm
    for name in ("remove", "delete", "del", "rm"):
        p = subparsers.add_parser(
            name,
            help="Remove a completed worktree and its branch (Jira ticket untouched)",
            description=(
                "Remove the worktree directory and delete the local branch. "
                "Use this after a branch has been merged or the work is otherwise done. "
                "The associated Jira ticket is NOT affected. "
                "To discard an unwanted branch and delete its Jira ticket, use 'abandon' instead."
            ),
        )
        p.add_argument(
            "branch", nargs="?", default=None, help="Branch name (prompted if omitted)"
        )

    # abandon
    p = subparsers.add_parser(
        "abandon",
        help="Discard a non-viable worktree, branch, and its Jira ticket",
        description=(
            "Permanently discard a line of work that will never be merged. "
            "Deletes the worktree directory, the local branch, and the associated Jira ticket, "
            "each with a separate confirmation. "
            "To clean up after a successful merge without touching Jira, use 'remove' instead."
        ),
    )
    p.add_argument(
        "branch", nargs="?", default=None, help="Branch name (prompted if omitted)"
    )

    # pr
    pr_parser = subparsers.add_parser(
        "pr",
        help="Push, open a PR, optionally create a Jira ticket, then merge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
            Push the branch if needed, open VS Code to write the PR title/summary,
            create a Jira ticket (if acli is available), open the GitHub PR, and
            optionally squash-merge + clean up.

            Can be run from the main repo checkout or from inside the worktree.
            When run from a worktree, workit automatically switches to the main
            repo root so the full flow (including worktree cleanup) is available.
        """),
    )
    pr_parser.add_argument(
        "branch", nargs="?", default=None, help="Branch name (prompted if omitted)"
    )
    pr_parser.add_argument(
        "--key",
        metavar="JIRA_KEY",
        default=None,
        help="Jira ticket ID to link (e.g. PROJ-123); overrides extraction from branch name",
    )
    pr_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompts, accepting defaults",
    )
    pr_parser.add_argument(
        "--no-ai",
        dest="ai",
        action="store_false",
        default=True,
        help="Skip AI summary generation and use the blank template instead",
    )
    pr_parser.add_argument(
        "-m",
        "--merge",
        action="store_true",
        help="Squash-and-merge immediately after creating the PR (requires --yes)",
    )

    # code / edit
    for name in ("code", "edit"):
        p = subparsers.add_parser(name, help="Open a worktree in a new VS Code window")
        p.add_argument("branch", nargs="?", default=None, help="Branch name")

    # list
    subparsers.add_parser("list", help="List existing worktrees")

    # config
    subparsers.add_parser(
        "config",
        help="Open ~/.config/workit/config.json in VS Code (creates it with defaults if absent)",
    )

    # help
    subparsers.add_parser("help", help="Show this help message and exit")

    # tldr
    subparsers.add_parser("tldr", help="Print a brief getting-started guide")

    # check
    subparsers.add_parser(
        "check",
        help="Check that gh, copilot, and acli are installed and authenticated",
    )

    # summary / sum / summarize
    for name in ("summary", "sum", "summarize"):
        p = subparsers.add_parser(
            name,
            help="Run an AI prompt against a branch and print the output",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description=textwrap.dedent(f"""\
                Run a copilot-powered prompt against a branch and print the result.

                Four built-in prompts are available via flags. Omit all flags to
                choose from an interactive menu that also includes any custom prompts
                found in ~/.config/workit/prompts/.

                  -b / --branch           "{_PR_PROMPT_NAME}"
                  -c / --commit           "{_COMMIT_PROMPT_NAME}"
                  -u / --uncommitted      "{_UNCOMMITTED_PROMPT_NAME}"
                  -s / --staged           "{_STAGED_PROMPT_NAME}"

                Custom prompts: place *.md files in ~/.config/workit/prompts/.
                The filename (underscores/dashes → spaces) becomes the prompt name.
            """),
        )
        p.add_argument(
            "branch",
            nargs="?",
            default=None,
            help="Branch name (defaults to current branch)",
        )
        g = p.add_mutually_exclusive_group()
        g.add_argument(
            "-b",
            "--branch",
            dest="preset_prompt",
            action="store_const",
            const=_PR_PROMPT_NAME,
            help=f'Use the "{_PR_PROMPT_NAME}" prompt without prompting',
        )
        g.add_argument(
            "-c",
            "--commit",
            dest="preset_prompt",
            action="store_const",
            const=_COMMIT_PROMPT_NAME,
            help=f'Use the "{_COMMIT_PROMPT_NAME}" prompt without prompting',
        )
        g.add_argument(
            "-u",
            "--uncommitted",
            dest="preset_prompt",
            action="store_const",
            const=_UNCOMMITTED_PROMPT_NAME,
            help=f'Use the "{_UNCOMMITTED_PROMPT_NAME}" prompt without prompting',
        )
        g.add_argument(
            "-s",
            "--staged",
            dest="preset_prompt",
            action="store_const",
            const=_STAGED_PROMPT_NAME,
            help=f'Use the "{_STAGED_PROMPT_NAME}" prompt without prompting',
        )

    # post-pr / prs / post
    for name in ("post-pr", "prs", "post"):
        p = subparsers.add_parser(
            name,
            help="Summarize a merged PR and append to the status report",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description=textwrap.dedent(f"""\
                Run a copilot-powered summary of a merged GitHub PR and append
                the result to the configured status_report file.

                If PR_NUMBER is omitted, fetches all PRs merged in the last 30 days
                and presents an interactive selection menu.

                Uses the built-in "{_POST_PR_PROMPT_NAME}" prompt.
            """),
        )
        p.add_argument(
            "pr_number",
            nargs="?",
            default=None,
            help="PR number to summarize (prompted if omitted)",
        )
        p.add_argument(
            "--jira",
            action="store_true",
            default=False,
            help="Create a Jira workitem for this PR and link it",
        )
        p.add_argument(
            "--key",
            metavar="JIRA_KEY",
            default=None,
            help="Jira project key to use instead of prompting",
        )

    args = parser.parse_args()
    _verbose = args.verbose

    # If we cd'd into the main repo from a worktree, inject the branch name
    # (unless the user already passed --branch explicitly)
    if worktree_branch and not args.branch:
        args.branch = worktree_branch

    if args.subcommand is None:
        # If we arrived here from a worktree, default to pr
        if worktree_branch:
            return cmd_pr(
                args.branch,
                from_worktree=True,
                jira_key=getattr(args, "key", None),
                yes=getattr(args, "yes", False),
                ai=getattr(args, "ai", True),
                merge=getattr(args, "merge", False),
            )
        # Interactive menu
        worktree_count = len(get_existing_worktrees())
        if not worktree_count:
            print()
            print("No existing worktrees found. Starting create flow.")
            return cmd_create(None)
        choices: list = [Choice(value="create", name="Create a new worktree")]
        choices.append(Choice(value="remove", name="Remove a worktree"))
        choices.append(Choice(value="code", name="Open a worktree in VS Code"))
        choices.append(
            Choice(value="list", name=f"List existing worktrees ({worktree_count})")
        )
        action = ListPrompt(
            message="What would you like to do?",
            choices=choices,
        ).execute()
        if action == "list":
            return cmd_list()
        return SUBCOMMANDS[action](None)

    sub = args.subcommand
    branch = getattr(args, "branch", None)

    if sub == "list":
        return cmd_list()
    if sub == "config":
        return cmd_config()
    if sub == "help":
        parser.print_help()
        return 0
    if sub == "tldr":
        return cmd_tldr()
    if sub == "check":
        return cmd_check()
    if sub in ("summary", "sum", "summarize"):
        return cmd_summary(branch, preset_prompt=getattr(args, "preset_prompt", None))
    if sub in ("post-pr", "prs", "post"):
        return cmd_post_pr(
            getattr(args, "pr_number", None),
            jira=getattr(args, "jira", False),
            jira_key=getattr(args, "key", None),
        )
    if sub == "pr":
        return cmd_pr(
            branch,
            from_worktree=bool(worktree_branch),
            jira_key=args.key,
            yes=args.yes,
            ai=args.ai,
            merge=args.merge,
        )
    if sub in ("create", "new"):
        return cmd_create(branch, epic=getattr(args, "epic", None))
    if sub == "abandon":
        return cmd_abandon(branch)
    return SUBCOMMANDS[sub](branch)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
