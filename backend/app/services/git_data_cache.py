"""
git_data_cache.py — owns the push of the embedding-matrix artifact to the
`data-cache` branch in the same git repo.

Why a dedicated branch:
  - 33 MB binary file committed daily would blow past GitHub's 1 GB
    recommended repo size within a month if we kept history.
  - We rewrite history on every push (--force-with-lease) so the branch
    is always exactly one commit containing the latest matrix.

Why --force-with-lease (not --force):
  - Refuses to overwrite if someone else has pushed to the branch since
    we last fetched. For a single-writer branch this is a safety net
    against concurrent runs, not a normal branch-sharing concern.

Failure modes that are non-fatal to the pipeline:
  - git not installed
  - not inside a git repo
  - branch doesn't exist yet on the remote (we create it)
  - push rejected (we surface the error, but the matrix is still on
    local disk for manual recovery)

The pipeline is the only thing that should ever write to this branch.
Branch protection in the GitHub UI should also enforce "no PRs target
data-cache" to prevent accidental merges.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

BRANCH_NAME = "data-cache"
REPO_RELATIVE_PATHS = ("data/embeddings/matrix.npy", "data/embeddings/matrix_ids.json")


class GitDataCacheError(RuntimeError):
    """Raised when the data-cache branch cannot be updated. The pipeline
    should log and continue (the matrix is still on local disk and the
    Vercel read path will fall back to Turso for the next 24h)."""


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )


def _git_available() -> bool:
    return shutil.which("git") is not None


def _repo_root() -> Path:
    """Walk up from CWD to find the git repo root."""
    cur = Path.cwd().resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / ".git").exists():
            return candidate
    raise GitDataCacheError(
        "Not inside a git repository. data-cache push requires the pipeline "
        "to run from within the matchpoint repo."
    )


def push_matrix_to_branch(
    matrix_bytes: bytes,
    ids_bytes: bytes,
    *,
    branch: str = BRANCH_NAME,
    commit_message: str | None = None,
) -> None:
    """Write matrix + ids into a temp worktree, commit as a single amend on
    `branch`, force-push with --force-with-lease, and gc the local repo.

    Args:
        matrix_bytes: serialized .npy from embedding_matrix.encode()
        ids_bytes: serialized JSON from embedding_matrix.encode()
        branch: target branch name (default "data-cache")
        commit_message: optional commit message; defaults to a timestamped one

    Raises:
        GitDataCacheError: if git is unavailable, repo not found, or push fails.
    """
    if not _git_available():
        raise GitDataCacheError("git is not installed or not on PATH")

    repo_root = _repo_root()
    rel_dir = Path(REPO_RELATIVE_PATHS[0]).parent  # data/embeddings

    # We do the work in a temp checkout to avoid clobbering the user's
    # current working tree state, and to guarantee the branch is in a
    # clean state for the force-push.
    with tempfile.TemporaryDirectory(prefix="data-cache-") as tmp:
        worktree = Path(tmp) / "wt"
        # Fetch the branch so --force-with-lease has something to compare to.
        fetch = _run(["git", "fetch", "origin", branch], repo_root)
        if fetch.returncode != 0:
            # Branch may not exist yet on origin. That's fine — we'll create it.
            # But we still need fetch to succeed for unrelated branches to avoid
            # an outdated refs/remotes/origin/data-cache. Soft-fail.
            print(
                f"[data-cache] git fetch origin {branch} returned "
                f"{fetch.returncode} (likely first run, branch not on remote yet)"
            )

        # Clean up any stale worktree on this branch from a previous run.
        # We can't just look for our current tmpdir path (a random suffix
        # is involved), and we can't do a substring check (per CodeRabbit).
        # So: parse `git worktree list --porcelain`, find any worktree
        # whose branch matches, and remove that path.
        list_cmd = _run(
            ["git", "worktree", "list", "--porcelain"], repo_root
        )
        if list_cmd.returncode == 0:
            current_path = None
            current_branch = None
            stale_to_remove: list[str] = []
            for raw_line in list_cmd.stdout.splitlines():
                line = raw_line.strip()
                if line.startswith("worktree "):
                    current_path = line[len("worktree "):]
                elif line.startswith("branch "):
                    current_branch = line[len("branch "):]
                    if (
                        current_path is not None
                        and current_branch == f"refs/heads/{branch}"
                        and current_path != str(worktree)
                    ):
                        stale_to_remove.append(current_path)
                    current_path = None
                    current_branch = None
            for stale_path in stale_to_remove:
                print(
                    f"[data-cache] removing stale worktree on {branch}: "
                    f"{stale_path}"
                )
                _run(
                    ["git", "worktree", "remove", "--force", stale_path],
                    repo_root,
                )
                # If the worktree dir was already gone, prune the
                # administrative record so git doesn't keep complaining.
                _run(["git", "worktree", "prune"], repo_root)

        # Check if the branch exists locally
        local_exists = _run(
            ["git", "rev-parse", "--verify", f"refs/heads/{branch}"], repo_root
        )
        if local_exists.returncode == 0:
            wt_add = _run(
                ["git", "worktree", "add", str(worktree), branch], repo_root
            )
        else:
            # Try to base off origin/data-cache if it exists, else create orphan.
            origin_ref = f"refs/remotes/origin/{branch}"
            origin_exists = _run(
                ["git", "rev-parse", "--verify", origin_ref], repo_root
            )
            if origin_exists.returncode == 0:
                wt_add = _run(
                    [
                        "git", "worktree", "add",
                        "--track", "-B", branch,
                        str(worktree), f"origin/{branch}",
                    ],
                    repo_root,
                )
            else:
                wt_add = _run(
                    ["git", "worktree", "add", "--orphan", "-B", branch, str(worktree)],
                    repo_root,
                )
        if wt_add.returncode != 0:
            raise GitDataCacheError(
                f"git worktree add failed:\n  stdout: {wt_add.stdout}\n  "
                f"stderr: {wt_add.stderr}"
            )

        # Reset to origin/data-cache if it exists, so we start clean.
        origin_ref = f"refs/remotes/origin/{branch}"
        if _run(["git", "rev-parse", "--verify", origin_ref], repo_root).returncode == 0:
            reset = _run(
                ["git", "reset", "--hard", f"origin/{branch}"],
                worktree,
            )
            if reset.returncode != 0:
                raise GitDataCacheError(
                    f"git reset --hard origin/{branch} failed:\n  "
                    f"stdout: {reset.stdout}\n  stderr: {reset.stderr}"
                )
        else:
            # Orphan branch: remove anything that snuck in (e.g. a placeholder
            # commit from --orphan).
            _run(["git", "rm", "-rf", "--quiet", "."], worktree)
            # Allow the rm to fail silently if tree is empty

        # Write the matrix files into the worktree.
        target_dir = worktree / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "matrix.npy").write_bytes(matrix_bytes)
        (target_dir / "matrix_ids.json").write_bytes(ids_bytes)

        # Stage. We use explicit paths to avoid picking up unrelated changes
        # in the worktree.
        for rel_path in REPO_RELATIVE_PATHS:
            add = _run(["git", "add", "--", rel_path], worktree)
            if add.returncode != 0:
                raise GitDataCacheError(
                    f"git add {rel_path} failed:\n  "
                    f"stdout: {add.stdout}\n  stderr: {add.stderr}"
                )

        # If there's nothing to commit (shouldn't happen — we just wrote
        # fresh files — but guard anyway), skip the push.
        status = _run(["git", "status", "--porcelain"], worktree)
        if not status.stdout.strip():
            print(f"[data-cache] no changes to commit on {branch}, skipping push")
            return

        # Commit. Use --amend if there's an existing HEAD, else plain commit.
        # Pass the committer identity via -c so the pipeline doesn't depend
        # on a globally-configured git user on the host machine.
        head_check = _run(["git", "rev-parse", "--verify", "HEAD"], worktree)
        msg = commit_message or f"embeddings: update matrix ({_utc_timestamp()})"
        git_identity = [
            "-c", "user.name=matchpoint-pipeline",
            "-c", "user.email=pipeline@matchpoint.local",
        ]
        if head_check.returncode == 0:
            commit = _run(
                ["git", *git_identity, "commit", "--amend", "--no-edit", "-m", msg],
                worktree,
            )
        else:
            commit = _run(
                ["git", *git_identity, "commit", "-m", msg, "--allow-empty"],
                worktree,
            )
        if commit.returncode != 0:
            raise GitDataCacheError(
                f"git commit failed:\n  stdout: {commit.stdout}\n  "
                f"stderr: {commit.stderr}"
            )

        # Force-push with lease. If the lease fails (someone else pushed
        # in between fetch and push), we surface the error rather than
        # clobbering.
        push = _run(
            ["git", "push", "origin", f"HEAD:{branch}", "--force-with-lease"],
            worktree,
        )
        if push.returncode != 0:
            raise GitDataCacheError(
                f"git push --force-with-lease to origin/{branch} failed:\n  "
                f"stdout: {push.stdout}\n  stderr: {push.stderr}"
            )

        print(f"[data-cache] pushed matrix to origin/{branch} (commit {msg!r})")

    # GC the local repo. This is best-effort; a failure here doesn't
    # block the pipeline (the push already succeeded).
    gc = _run(["git", "gc", "--prune=now", "--aggressive"], repo_root)
    if gc.returncode != 0:
        print(
            f"[data-cache] git gc failed (non-fatal): "
            f"stdout: {gc.stdout} stderr: {gc.stderr}"
        )


def _utc_timestamp() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "BRANCH_NAME",
    "REPO_RELATIVE_PATHS",
    "GitDataCacheError",
    "push_matrix_to_branch",
]
