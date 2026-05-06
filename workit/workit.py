"""Unified git worktree management tool.

Usage:
    worktree create [branch-name]
    worktree remove [branch-name]
    worktree pr [branch-name]
    worktree summary [branch-name]

Subcommand aliases:
    create: new
    remove: delete, del, rm
    summary: sum, summarize
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

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator


# --- Configuration ---

_CONFIG_DIR = Path.home() / ".config" / "workit"
_CONFIG_FILE = _CONFIG_DIR / "config.json"
_PROMPTS_DIR = _CONFIG_DIR / "prompts"

_CONFIG_DEFAULTS: dict = {
    "jira_projects": ["AE", "STARLING", "MAP"],
    "branch_prefix": "",
    "model": "claude-4.6-sonnet",
    "jira_assignee": "",
    "status_report": "~/workit_status_report.md",
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
    "\n\nWrite a clear PR title on the first line, followed by a blank line, "
    "then break the changes into high-level unrelated functional blocks and write a level 2 titled single "
    "paragraph for each functional change. Each paragraph should be 3 to 6 sentences "
    "long and written for a management audience. Do not use filenames or code syntax in "
    "the description, just describe the changes in plain language. "
    "Be factual and concise. Do not include filler phrases."
)

COMMIT_FORMATTER = (
    "\n\nWrite a clear one line commit summary on the first line, followed by a blank line, "
    "then break the changes into functional blocks and write a level 2 titled single "
    "paragraph for each functional change. Each paragraph should be 2 to 4 sentences "
    "long and written for a technical audience. "
    "Be factual and concise. Do not include filler phrases."
)

_DEFAULT_PROMPTS: dict[str, str] = {
    "PR Branch Summary": (
        "You are a helpful assistant that writes concise GitHub pull request descriptions.\n"
        "Examine the git log and diff for the current branch in this repository."
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
}

_PR_PROMPT_NAME = "PR Branch Summary"
_COMMIT_PROMPT_NAME = "Last Commit Summary"
_UNCOMMITTED_PROMPT_NAME = "Working Copy Summary"
_STAGED_PROMPT_NAME = "Stage Changes Summary"


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


def generate_summary(branch: str, repo: str, prompt_name: str = _PR_PROMPT_NAME) -> str:
    """Generate a summary using the copilot CLI with the specified prompt."""
    copilot_path = shutil.which("copilot")
    if not copilot_path:
        raise RuntimeError("'copilot' CLI not found on PATH")
    vlog(f"copilot binary: {copilot_path}")

    prompt = _load_prompt(prompt_name)
    prompt = prompt.replace("${BRANCH}", branch).replace("${REPO}", repo)
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
    vlog()

    result_holder: list = []

    def _run() -> None:
        result_holder.append(subprocess.run(cmd, capture_output=True, text=True))

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
    return result.stdout.strip()


def create_jira_workitem(
    title: str, summary: str, jira_key: str | None = None
) -> tuple[str, str] | None:
    """Create a Jira workitem via ACLI. Returns (issue_id, issue_url) or None."""
    if not shutil.which("acli"):
        print("Warning: acli is not installed or not on PATH.")
        proceed = inquirer.confirm(
            message="Continue creating PR without a Jira ticket?",
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
            project = inquirer.select(
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

    print("Creating Jira workitem...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout.strip() or result.stderr.strip()

    if result.returncode != 0:
        print(f"Error: acli failed.\n{output}")
        proceed = inquirer.confirm(
            message="Continue creating PR without a Jira ticket?",
            default=True,
        ).execute()
        return None if proceed else (_ for _ in ()).throw(RuntimeError("acli error"))

    match = re.search(r"Work item (\S+) created: (\S+)", output)
    if not match:
        print(f"Warning: Could not parse acli output:\n{output}")
        proceed = inquirer.confirm(
            message="Continue creating PR without a Jira ticket?",
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
    """Return list of branch names that have worktrees in the worktrees directory."""
    base = get_worktree_base()
    if not base.is_dir():
        return []
    results = []
    for d in base.rglob("*"):
        if d.is_dir():
            branch_name = str(d.relative_to(base))
            if branch_exists(branch_name):
                results.append(branch_name)
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

    branch = inquirer.select(
        message=f"Select a worktree to {action_description}:",
        choices=worktrees,
    ).execute()
    return branch


def prompt_branch_name() -> str | None:
    """Prompt user for a new branch name."""
    branch = inquirer.text(
        message="Enter the new branch name:",
        validate=lambda x: len(x.strip()) > 0,
        invalid_message="Branch name cannot be empty.",
    ).execute()
    return branch.strip() if branch else None


# --- Subcommands ---


def cmd_create(branch_name: str | None) -> int:
    """Create a new worktree and branch."""
    if not branch_name:
        branch_name = prompt_branch_name()
        if not branch_name:
            print("Aborted.")
            return 1

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
        print(f"Error: Failed to create worktree.")
        if result.stderr:
            print(result.stderr)
        return 1

    # Open VS Code in the new directory
    subprocess.run(["code", str(target_path), "--new-window"])

    print("Done! Worktree is ready.")
    return 0


def cmd_remove(branch_name: str | None, force: bool = False) -> int:
    """Remove a worktree and delete its branch."""
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
        confirm = inquirer.confirm(
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
        confirm = inquirer.confirm(
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


def cmd_pr(
    branch_name: str | None,
    in_worktree: bool = False,
    jira_key: str | None = None,
    yes: bool = False,
    ai: bool = False,
    merge: bool = False,
) -> int:
    """Create a pull request for the specified worktree branch."""
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

    # Open VS Code for the user to write/paste title and summary
    placeholder = f"Title for {branch_name}\n\nReplace this text with your summary content, then save and close this file tab to continue.\n"
    if ai:
        print("Generating AI summary via copilot CLI...")
        print()
        try:
            repo = get_repo_slug()
            ai_output = generate_summary(branch_name, repo)
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
            action = inquirer.select(
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

        break

    Path(tmp_path).unlink(missing_ok=True)

    if not content:
        print("Aborted: no content provided.")
        return 1

    lines = content.splitlines()
    title = lines[0].strip()
    summary = "\n".join(lines[1:]).strip()

    print()

    # Create Jira workitem
    try:
        jira_result = create_jira_workitem(title, summary, jira_key=jira_key)
    except RuntimeError:
        return 1

    if jira_result:
        issue_id, issue_url = jira_result
        title = f"{issue_id} {title}"
        summary = f"{summary}\n\n{issue_url}"

    # print()
    # print(f"Title:   {title}")
    # print()
    # print(summary)
    # print()

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
    if jira_result:
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
        action = inquirer.select(
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
        if jira_result:
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
                run_git("pull", capture=False)
            else:
                cleanup = inquirer.confirm(
                    message=f"Delete worktree and branch '{branch_name}'?",
                    default=True,
                ).execute()
                if cleanup:
                    cmd_remove(branch_name)
                do_pull = inquirer.confirm(
                    message="Run git pull?",
                    default=True,
                ).execute()
                if do_pull:
                    run_git("pull", capture=False)

    return 0


def cmd_code(branch_name: str | None) -> int:
    """Open an existing worktree in a new VS Code window."""
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
            prompt_name = inquirer.select(
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


# --- Main ---

SUBCOMMANDS = {
    "create": cmd_create,
    "new": cmd_create,
    "remove": cmd_remove,
    "delete": cmd_remove,
    "del": cmd_remove,
    "rm": cmd_remove,
    "pr": cmd_pr,
    "code": cmd_code,
    "edit": cmd_code,
    "summary": cmd_summary,
    "sum": cmd_summary,
    "summarize": cmd_summary,
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

    parser = argparse.ArgumentParser(
        prog="workit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
            workit — git worktree manager with Jira and GitHub PR integration
                                    
            This tool automates the creation and cleanup of git worktrees for 
            feature branches, and streamlines the PR creation process with optional 
            Jira ticket creation and closure using optional AI-generated summaries.

            WORKFLOW
              1. Run 'workit create <branch>' from your main repo checkout.
                 A new worktree is created at ../<repo>-worktrees/<branch> and
                 opened in a new VS Code window.
              2. Do your work in that VS Code window and remember to commit and 
                 push your changes.
              3. When ready to ship, run 'workit pr' from the *main* repo. You can also run
                 just 'workit pr' (or 'workit') from inside the worktree — but you will not
                 get the option to cleanup the worktree, branch, and pull after merging when 
                 run from inside the worktree.
              4. The pr flow: pushes if needed → opens VS Code for you to write
                 the title/summary → creates a Jira ticket → opens the GitHub PR,
                 and associates the PR and Jira ticket with each other.
              5. After the PR merges, choose "Squash-and-merge" in the post-PR
                 menu to close the Jira ticket, clean up the worktree, and pull your changes
                 into your main working copy.

            CONFIGURATION
              ~/.config/workit/config.json   — runtime settings (see defaults below)
              ~/.config/workit/summary.md    — optional custom copilot prompt template
                                               (use ${BRANCH} and ${REPO} as placeholders)

            CONFIG KEYS
              branch_prefix    Prepended to every new branch: "kjm" → "kjm/<branch>"
              jira_projects    List of Jira project keys shown in the selector
              jira_assignee    Auto-assign new Jira tickets to this user
              status_report    Path to append merged-PR summaries to

            DEPENDENCIES (make sure you have these installed and authenticated for the best experience)
              gh     GitHub CLI  
                     (https://cli.github.com)
              acli   Atlassian CLI — optional, enables Jira integration 
                     (https://developer.atlassian.com/cloud/acli/guides/install-linux/)
              copilot  GitHub Copilot CLI — optional, enables --ai summary generation
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

    # remove / delete / del / rm
    for name in ("remove", "delete", "del", "rm"):
        p = subparsers.add_parser(
            name, help="Remove the worktree and delete its branch"
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

            Run from the main repo checkout or from inside the worktree itself.
        """),
    )
    pr_parser.add_argument(
        "branch", nargs="?", default=None, help="Branch name (prompted if omitted)"
    )
    pr_parser.add_argument(
        "--key",
        metavar="JIRA_KEY",
        default=None,
        help="Jira project key to use instead of prompting",
    )
    pr_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompts, accepting defaults",
    )
    pr_parser.add_argument(
        "--ai",
        action="store_true",
        help="Use copilot CLI to generate the initial PR summary instead of the template",
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

    # summary / sum / summarize
    for name in ("summary", "sum", "summarize"):
        p = subparsers.add_parser(
            name,
            help="Run an AI prompt against a branch and print the output",
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
            "--branch-summary",
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

    if in_worktree:
        # Only pr is valid from inside a worktree; default to it if no subcommand given
        raw = sys.argv[1:]
        if raw and raw[0].lower() not in ("pr", "-h", "--help"):
            print(
                "Error: Only the 'pr' subcommand is available when run from a worktree."
            )
            return 1
        args = parser.parse_args(
            ["pr"] + raw if (not raw or raw[0].lower() != "pr") else raw
        )
        _verbose = args.verbose
        return cmd_pr(
            args.branch,
            in_worktree=True,
            jira_key=args.key,
            yes=args.yes,
            ai=args.ai,
            merge=args.merge,
        )

    args = parser.parse_args()

    _verbose = args.verbose

    if args.subcommand is None:
        # Interactive menu
        worktree_count = len(get_existing_worktrees())
        if not worktree_count:
            return cmd_create(None)
        choices: list = [Choice(value="create", name="Create a new worktree")]
        choices.append(Choice(value="remove", name="Remove a worktree"))
        choices.append(Choice(value="code", name="Open a worktree in VS Code"))
        choices.append(
            Choice(value="list", name=f"List existing worktrees ({worktree_count})")
        )
        action = inquirer.select(
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
    if sub in ("summary", "sum", "summarize"):
        return cmd_summary(branch, preset_prompt=getattr(args, "preset_prompt", None))
    if sub == "pr":
        return cmd_pr(
            branch, jira_key=args.key, yes=args.yes, ai=args.ai, merge=args.merge
        )
    return SUBCOMMANDS[sub](branch)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
