"""Bounded, shell-free Git facts for intent-coverage ratchets.

This module is the sole Git subprocess owner for intent coverage.  It returns
immutable object-database facts; classification remains in the pure coverage
module.

Spec: docs/specs/08-intent-coverage.md [COV-5], [COV-8], [COV-9]
"""

from __future__ import annotations

import hashlib
import os
import queue
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from threading import Thread
from typing import BinaryIO, Literal

from backstitch.canonical import (
    canonical_json_bytes,
    lf_line_count,
    lf_slice,
)
from backstitch.grammar import is_prefixed_sha256

_SHA256_PREFIX = "sha256:"
_DRIFT_TRAILER = "Backstitch-Drift-Ack:"
_POLICY_TRAILER = "Backstitch-Coverage-Policy-Ack:"


class GitBaselineError(RuntimeError):
    """Git facts could not be obtained within the closed trust boundary."""


@dataclass(frozen=True, slots=True)
class GitLimits:
    """Run-wide Git and baseline resource limits."""

    maximum_baseline_files: int = 20_000
    maximum_file_bytes: int = 5_000_000
    maximum_baseline_bytes: int = 100_000_000
    maximum_history_commits: int = 1_000
    maximum_git_command_seconds: float = 10.0
    maximum_git_commands: int = 64
    maximum_git_output_bytes: int = 100_000_000
    maximum_commit_message_bytes: int = 1_000_000
    maximum_runtime_seconds: float = 60.0


@dataclass(frozen=True, slots=True)
class GitTransition:
    """One first-parent commit transition in oldest-to-newest order."""

    parent_commit: str
    commit: str
    message: str
    changes: tuple[tuple[str, bytes | None], ...] = ()


@dataclass(frozen=True, slots=True)
class GitBaseline:
    """A merge-base snapshot and bounded first-parent transition range."""

    requested_ref: str
    base_commit: str
    merge_base: str
    head_commit: str
    blobs: Mapping[str, bytes]
    blob_oids: Mapping[str, str]
    history_blobs: Mapping[str, bytes]
    transitions: tuple[GitTransition, ...]
    history_transitions: tuple[GitTransition, ...]
    history_complete: bool
    commands_used: int
    git_output_bytes: int


@dataclass(frozen=True, slots=True)
class GitBaselineMetadata:
    """The exact non-null report baseline record."""

    configured_ref: str
    resolved_commit: str
    merge_base: str
    current_snapshot_sha256: str
    current_content_sha256: str
    baseline_policy_sha256: str
    current_policy_sha256: str
    history_complete: bool
    history_commits_inspected: int


@dataclass(frozen=True, slots=True)
class PolicyEvent:
    """One weakening or authority-sensitive policy transition."""

    event_id: str
    parent_commit: str
    key: str
    baseline_value: object
    current_value: object
    transition_commit: str | None
    acknowledged: bool = False
    acknowledgment_commit: str | None = None
    acknowledgment_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyTransition:
    """One chronological canonical policy transition."""

    parent_commit: str
    transition_commit: str | None
    before: Mapping[str, object]
    after: Mapping[str, object]
    commit_message: str = ""


@dataclass(frozen=True, slots=True)
class DriftState:
    """The four exact hash inputs for one contract edge at one revision."""

    edge_id: str
    requirement_id: str
    definition_id: str
    section_hash: str
    mapping_hash: str
    implementation_hash: str
    connected_test_hash: str


@dataclass(frozen=True, slots=True)
class DriftTransition:
    """One edge state transition, optionally owned by a child commit."""

    parent_commit: str
    child_commit: str | None
    before: DriftState
    after: DriftState
    commit_message: str = ""
    current_diff: bool = True


@dataclass(frozen=True, slots=True)
class DriftEvent:
    """One exact transition where implementation moved without intent evidence."""

    event_id: str
    edge_id: str
    requirement_id: str
    definition_id: str
    parent_commit: str
    transition_commit: str | None
    base_projection_sha256: str
    current_projection_sha256: str
    before_section_hash: str
    after_section_hash: str
    before_mapping_hash: str
    after_mapping_hash: str
    before_connected_test_hash: str
    after_connected_test_hash: str
    acknowledged: bool = False
    acknowledgment_commit: str | None = None
    acknowledgment_reason: str | None = None
    synthetic_current: bool = False


@dataclass(frozen=True, slots=True)
class Acknowledgment:
    """One parsed acknowledgment trailer, valid or advisory-invalid."""

    kind: Literal["drift", "policy"]
    event_id: str | None
    reason: str | None
    valid: bool
    duplicate: bool
    raw: str


@dataclass(frozen=True, slots=True)
class StaleDocTrend:
    """A bounded first-parent stale-document signal for one edge."""

    edge_id: str
    section_change_commit: str | None
    unacknowledged_event_count: int
    last_event_commit: str | None
    history_complete: bool
    commits_inspected: int


@dataclass(slots=True)
class _RunBudget:
    limits: GitLimits
    deadline: float
    commands: int = 0
    output_bytes: int = 0

    def check_deadline(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise GitBaselineError("intent coverage Git phase exceeded runtime budget")
        return remaining

    def charge_command(self) -> float:
        remaining = self.check_deadline()
        if self.commands >= self.limits.maximum_git_commands:
            raise GitBaselineError("intent coverage Git command budget exceeded")
        self.commands += 1
        return min(self.limits.maximum_git_command_seconds, remaining)

    def charge_output(self, size: int) -> None:
        self.output_bytes += size
        if self.output_bytes > self.limits.maximum_git_output_bytes:
            raise GitBaselineError("intent coverage Git output budget exceeded")


@dataclass(frozen=True, slots=True)
class _TreeBlob:
    path: str
    oid: str
    size: int = 0


class _GitRunner:
    """Closed Git executable, environment, repository selection, and budgets."""

    def __init__(self, root: Path, limits: GitLimits) -> None:
        self.root = root.resolve(strict=True)
        self.git_dir = _resolve_git_dir(self.root)
        executable = shutil.which("git")
        if executable is None:
            raise GitBaselineError("Git executable was not found")
        self.executable = str(Path(executable).resolve(strict=True))
        self.budget = _RunBudget(
            limits=limits,
            deadline=time.monotonic() + limits.maximum_runtime_seconds,
        )

    def run(self, arguments: Sequence[str], *, stdin: bytes | None = None) -> bytes:
        timeout = self.budget.charge_command()
        command = [
            self.executable,
            "--no-replace-objects",
            "-c",
            "core.pager=cat",
            "-c",
            "pager.branch=false",
            "-c",
            "pager.log=false",
            "-c",
            "diff.external=",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "credential.helper=",
            "-c",
            "core.useReplaceRefs=false",
            "--git-dir",
            str(self.git_dir),
            "--work-tree",
            str(self.root),
            *arguments,
        ]
        environment = {
            "LC_ALL": "C",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        if os.name == "nt":
            for name in ("SystemRoot", "WINDIR"):
                value = os.environ.get(name)
                if value is not None:
                    environment[name] = value
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            shell=False,
        )
        try:
            stdout, stderr = self._communicate_bounded(
                process,
                stdin=stdin,
                timeout=timeout,
            )
        except GitBaselineError:
            process.kill()
            process.wait()
            raise
        self.budget.check_deadline()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise GitBaselineError(
                "intent coverage Git command failed" + (f": {detail}" if detail else "")
            )
        return stdout

    def _communicate_bounded(  # noqa: C901 approved [SC-17.1] RUFF-SUP-044 exception
        self,
        process: subprocess.Popen[bytes],
        *,
        stdin: bytes | None,
        timeout: float,
    ) -> tuple[bytes, bytes]:
        if process.stdout is None or process.stderr is None:
            raise AssertionError("Git subprocess pipes were not created")
        chunks: queue.Queue[tuple[Literal["stdout", "stderr"], bytes | None]] = (
            queue.Queue(maxsize=4)
        )

        def read_stream(
            stream: BinaryIO,
            name: Literal["stdout", "stderr"],
        ) -> None:
            while True:
                chunk = stream.read(65_536)
                if not chunk:
                    chunks.put((name, None))
                    return
                chunks.put((name, chunk))

        readers = (
            Thread(target=read_stream, args=(process.stdout, "stdout"), daemon=True),
            Thread(target=read_stream, args=(process.stderr, "stderr"), daemon=True),
        )
        for reader in readers:
            reader.start()

        def write_stdin() -> None:
            if process.stdin is None:
                return
            try:
                process.stdin.write(stdin or b"")
            except BrokenPipeError:
                pass
            finally:
                process.stdin.close()

        writer = Thread(target=write_stdin, daemon=True)
        writer.start()
        deadline = time.monotonic() + timeout
        output: dict[str, list[bytes]] = {"stdout": [], "stderr": []}
        finished = 0
        while finished < 2:
            remaining = min(deadline, self.budget.deadline) - time.monotonic()
            if remaining <= 0:
                raise GitBaselineError("intent coverage Git command timed out")
            try:
                name, chunk = chunks.get(timeout=min(remaining, 0.1))
            except queue.Empty:
                continue
            if chunk is None:
                finished += 1
                continue
            self.budget.charge_output(len(chunk))
            output[name].append(chunk)
        remaining = min(deadline, self.budget.deadline) - time.monotonic()
        if remaining <= 0:
            raise GitBaselineError("intent coverage Git command timed out")
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            raise GitBaselineError("intent coverage Git command timed out") from error
        writer.join(timeout=remaining)
        for reader in readers:
            reader.join(timeout=remaining)
        return b"".join(output["stdout"]), b"".join(output["stderr"])


def load_git_baseline(
    repo_root: Path,
    ratchet_base: str,
    *,
    limits: GitLimits,
    include_paths: Sequence[str] | None = None,
) -> GitBaseline:
    """Resolve one merge base and read selected blobs from immutable Git objects."""

    _validate_limits(limits)
    _validate_ref(ratchet_base)
    runner = _GitRunner(repo_root, limits)
    if runner.run(("rev-parse", "--is-shallow-repository")).strip() == b"true":
        raise GitBaselineError("intent coverage ratchet requires sufficient history")
    base_commit = _decode_oid(
        runner.run(("rev-parse", "--verify", f"{ratchet_base}^{{commit}}"))
    )
    head_commit = _decode_oid(runner.run(("rev-parse", "--verify", "HEAD^{commit}")))
    merge_base = _decode_oid(runner.run(("merge-base", "--", base_commit, head_commit)))
    tree_rows = _parse_ls_tree(
        runner.run(("ls-tree", "-rz", "--full-tree", merge_base)),
        include_paths=include_paths,
        limits=limits,
    )
    runner.budget.check_deadline()
    blob_cache: dict[str, bytes] = {}
    blobs, blob_oids = _read_batch_blobs(
        runner,
        tree_rows,
        limits=limits,
        blob_cache=blob_cache,
    )
    transitions, history_transitions, history_complete = _read_first_parent_histories(
        runner,
        merge_base=merge_base,
        head_commit=head_commit,
        limits=limits,
    )
    history_parent = (
        history_transitions[0].parent_commit if history_transitions else head_commit
    )
    if history_parent == merge_base:
        history_blobs = blobs
    else:
        history_limits = replace(
            limits,
            maximum_baseline_files=(limits.maximum_baseline_files - len(tree_rows)),
            maximum_baseline_bytes=(
                limits.maximum_baseline_bytes
                - sum(len(item) for item in blobs.values())
            ),
        )
        if (
            history_limits.maximum_baseline_files < 1
            or history_limits.maximum_baseline_bytes < 1
        ):
            raise GitBaselineError("intent coverage baseline budget exceeded")
        history_tree_rows = _parse_ls_tree(
            runner.run(("ls-tree", "-rz", "--full-tree", history_parent)),
            include_paths=include_paths,
            limits=history_limits,
        )
        history_blobs, _history_blob_oids = _read_batch_blobs(
            runner,
            history_tree_rows,
            limits=history_limits,
            blob_cache=blob_cache,
        )
    transition_commits = tuple(
        dict.fromkeys(item.commit for item in (*transitions, *history_transitions))
    )
    transition_changes = _read_transition_changes(
        runner,
        transition_commits,
        limits=replace(
            limits,
            maximum_baseline_bytes=(
                limits.maximum_baseline_bytes
                - sum(len(item) for item in blobs.values())
                - (
                    0
                    if history_blobs is blobs
                    else sum(len(item) for item in history_blobs.values())
                )
            ),
        ),
        blob_cache=blob_cache,
    )
    transitions = tuple(
        replace(item, changes=transition_changes.get(item.commit, ()))
        for item in transitions
    )
    history_transitions = tuple(
        replace(item, changes=transition_changes.get(item.commit, ()))
        for item in history_transitions
    )
    return GitBaseline(
        requested_ref=ratchet_base,
        base_commit=base_commit,
        merge_base=merge_base,
        head_commit=head_commit,
        blobs=blobs,
        blob_oids=blob_oids,
        history_blobs=history_blobs,
        transitions=transitions,
        history_transitions=history_transitions,
        history_complete=history_complete,
        commands_used=runner.budget.commands,
        git_output_bytes=runner.budget.output_bytes,
    )


def current_content_identity(source_hashes: Mapping[str, str]) -> str:
    """Hash sorted in-scope ``[path, source_sha256]`` current-content rows."""

    rows = [[path, source_hashes[path]] for path in sorted(source_hashes)]
    return _stable_hash(rows)


def baseline_metadata(
    baseline: GitBaseline,
    *,
    current_snapshot_sha256: str,
    current_content_sha256: str,
    baseline_policy_sha256: str,
    current_policy_sha256: str,
) -> GitBaselineMetadata:
    """Project bound Git facts into the exact coverage-report baseline row."""

    for value in (
        current_snapshot_sha256,
        current_content_sha256,
        baseline_policy_sha256,
        current_policy_sha256,
    ):
        if not _valid_sha256_token(value):
            raise ValueError("baseline metadata contains an invalid SHA-256 token")
    return GitBaselineMetadata(
        configured_ref=baseline.requested_ref,
        resolved_commit=baseline.base_commit,
        merge_base=baseline.merge_base,
        current_snapshot_sha256=current_snapshot_sha256,
        current_content_sha256=current_content_sha256,
        baseline_policy_sha256=baseline_policy_sha256,
        current_policy_sha256=current_policy_sha256,
        history_complete=baseline.history_complete,
        history_commits_inspected=len(baseline.history_transitions),
    )


def _resolve_git_dir(root: Path) -> Path:
    marker = root / ".git"
    if marker.is_dir():
        return marker.resolve(strict=True)
    if marker.is_file():
        try:
            line = marker.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as error:
            raise GitBaselineError("repository .git file is unreadable") from error
        prefix = "gitdir:"
        if not line.lower().startswith(prefix):
            raise GitBaselineError("repository .git file is invalid")
        target = Path(line[len(prefix) :].strip())
        if not target.is_absolute():
            target = root / target
        try:
            return target.resolve(strict=True)
        except OSError as error:
            raise GitBaselineError("repository Git directory does not exist") from error
    raise GitBaselineError("repository does not contain a Git work tree")


def _validate_limits(limits: GitLimits) -> None:
    integer_values = (
        limits.maximum_baseline_files,
        limits.maximum_file_bytes,
        limits.maximum_baseline_bytes,
        limits.maximum_history_commits,
        limits.maximum_git_commands,
        limits.maximum_git_output_bytes,
        limits.maximum_commit_message_bytes,
    )
    float_values = (
        limits.maximum_git_command_seconds,
        limits.maximum_runtime_seconds,
    )
    if any(value < 1 for value in integer_values) or any(
        not value > 0 for value in float_values
    ):
        raise GitBaselineError("intent coverage Git limits must be positive")


def _validate_ref(value: str) -> None:
    if _valid_git_oid(value):
        return
    components = value.split("/")
    if (
        not value
        or value == "@"
        or value.startswith(("-", "/"))
        or value.endswith(("/", "."))
        or ".." in value
        or "@{" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or any(char in " ~^:?*[\\" for char in value)
        or any(
            not component or component.startswith(".") or component.endswith(".lock")
            for component in components
        )
    ):
        raise GitBaselineError("ratchet base ref is invalid")


def _decode_oid(raw: bytes) -> str:
    try:
        value = raw.decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise GitBaselineError("Git returned a non-ASCII object ID") from error
    if not _valid_git_oid(value):
        raise GitBaselineError("Git returned an invalid object ID")
    return value


def _parse_ls_tree(
    raw: bytes,
    *,
    include_paths: Sequence[str] | None,
    limits: GitLimits,
) -> tuple[_TreeBlob, ...]:
    wanted = (
        None
        if include_paths is None
        else {_canonical_git_path(p) for p in include_paths}
    )
    rows: list[_TreeBlob] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, raw_oid = metadata.split(b" ", 2)
            path = _canonical_git_path(raw_path.decode("utf-8"))
            oid = raw_oid.decode("ascii")
        except (ValueError, UnicodeError) as error:
            raise GitBaselineError("Git tree output is invalid") from error
        if object_type != b"blob" or mode not in (b"100644", b"100755", b"120000"):
            continue
        if not _valid_git_oid(oid):
            raise GitBaselineError("Git tree contains an invalid blob object ID")
        if wanted is not None and path not in wanted:
            continue
        rows.append(_TreeBlob(path=path, oid=oid))
        if len(rows) > limits.maximum_baseline_files:
            raise GitBaselineError("intent coverage baseline file budget exceeded")
    return tuple(sorted(rows, key=lambda item: item.path))


def _canonical_git_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or any(part in ("", ".", "..") for part in path.parts)
        or path.as_posix() != value
    ):
        raise GitBaselineError("Git returned an unsafe repository path")
    return value


def _read_batch_blobs(
    runner: _GitRunner,
    rows: tuple[_TreeBlob, ...],
    *,
    limits: GitLimits,
    blob_cache: dict[str, bytes] | None = None,
) -> tuple[dict[str, bytes], dict[str, str]]:
    if not rows:
        return {}, {}
    by_oid = {} if blob_cache is None else blob_cache
    requested = {row.oid: row for row in rows if row.oid not in by_oid}
    raw = (
        runner.run(
            ("cat-file", "--batch"),
            stdin=b"".join((oid + "\n").encode("ascii") for oid in requested),
        )
        if requested
        else b""
    )
    offset = 0
    for oid, row in requested.items():
        runner.budget.check_deadline()
        newline = raw.find(b"\n", offset)
        if newline < 0:
            raise GitBaselineError("Git batch blob response is truncated")
        header = raw[offset:newline]
        offset = newline + 1
        try:
            actual_oid, object_type, raw_size = header.decode("ascii").split(" ")
            size = int(raw_size)
        except (UnicodeError, ValueError) as error:
            raise GitBaselineError("Git batch blob header is invalid") from error
        if actual_oid != oid or object_type != "blob" or size < 0:
            raise GitBaselineError("Git batch blob identity is inconsistent")
        if size > limits.maximum_file_bytes:
            raise GitBaselineError(f"baseline file exceeds byte limit: {row.path}")
        end = offset + size
        if end >= len(raw) or raw[end : end + 1] != b"\n":
            raise GitBaselineError("Git batch blob payload is truncated")
        by_oid[oid] = raw[offset:end]
        offset = end + 1
    if offset != len(raw):
        raise GitBaselineError("Git batch blob response has trailing data")
    baseline_bytes = sum(len(by_oid[row.oid]) for row in rows)
    runner.budget.check_deadline()
    if baseline_bytes > limits.maximum_baseline_bytes:
        raise GitBaselineError("intent coverage baseline byte budget exceeded")
    return (
        {row.path: by_oid[row.oid] for row in rows},
        {row.path: row.oid for row in rows},
    )


def _read_first_parent_histories(
    runner: _GitRunner,
    *,
    merge_base: str,
    head_commit: str,
    limits: GitLimits,
) -> tuple[tuple[GitTransition, ...], tuple[GitTransition, ...], bool]:
    current_raw = runner.run(
        (
            "rev-list",
            "--first-parent",
            "--reverse",
            "--parents",
            f"{merge_base}..{head_commit}",
        )
    )
    current_identities, _ = _parse_history_identities(
        current_raw,
        newest_first=False,
    )
    stale_raw = runner.run(
        (
            "rev-list",
            "--first-parent",
            "--parents",
            f"--max-count={limits.maximum_history_commits + 1}",
            head_commit,
        )
    )
    stale_identities, history_complete = _parse_history_identities(
        stale_raw,
        newest_first=True,
    )
    stale_identities = tuple(
        reversed(stale_identities[: limits.maximum_history_commits])
    )
    runner.budget.check_deadline()
    object_ids = tuple(
        dict.fromkeys(commit for _, commit in (*current_identities, *stale_identities))
    )
    commit_payloads = _read_batch_objects(
        runner,
        object_ids,
        expected_type="commit",
    )
    messages: dict[str, str] = {}
    for commit in object_ids:
        runner.budget.check_deadline()
        message_bytes = _commit_message(commit_payloads[commit])
        if len(message_bytes) > limits.maximum_commit_message_bytes:
            raise GitBaselineError("Git commit message exceeds byte limit")
        try:
            messages[commit] = message_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise GitBaselineError("Git commit message is not UTF-8") from error
    current = tuple(
        GitTransition(
            parent_commit=parent,
            commit=commit,
            message=messages[commit],
        )
        for parent, commit in current_identities
    )
    history = tuple(
        GitTransition(
            parent_commit=parent,
            commit=commit,
            message=messages[commit],
        )
        for parent, commit in stale_identities
    )
    return current, history, history_complete


def _read_transition_changes(  # noqa: C901 approved [SC-17.1] RUFF-SUP-045 exception
    runner: _GitRunner,
    commits: tuple[str, ...],
    *,
    limits: GitLimits,
    blob_cache: dict[str, bytes] | None = None,
) -> dict[str, tuple[tuple[str, bytes | None], ...]]:
    """Read every first-parent path transition with one diff and one blob batch."""

    if not commits:
        return {}
    if limits.maximum_baseline_bytes < 1:
        raise GitBaselineError("intent coverage baseline byte budget exceeded")
    raw = runner.run(
        (
            "diff-tree",
            "--stdin",
            "--first-parent",
            "--no-renames",
            "-r",
            "--raw",
            "-z",
        ),
        stdin=b"".join((commit + "\n").encode("ascii") for commit in commits),
    )
    records = raw.split(b"\0")
    if records and records[-1] == b"":
        records.pop()
    parsed: dict[str, list[tuple[str, str | None]]] = {}
    current_commit: str | None = None
    index = 0
    while index < len(records):
        record = records[index]
        if not record.startswith(b":"):
            current_commit = _decode_oid(record + b"\n")
            if current_commit not in commits or current_commit in parsed:
                raise GitBaselineError(
                    "Git transition diff contains an unexpected commit"
                )
            parsed[current_commit] = []
            index += 1
            continue
        if current_commit is None or index + 1 >= len(records):
            raise GitBaselineError("Git transition diff is malformed")
        try:
            metadata = record.decode("ascii").split()
            path = _canonical_git_path(records[index + 1].decode("utf-8"))
        except (UnicodeError, ValueError) as error:
            raise GitBaselineError("Git transition diff is malformed") from error
        if len(metadata) != 5 or not metadata[0].startswith(":"):
            raise GitBaselineError("Git transition diff metadata is malformed")
        old_mode = metadata[0][1:]
        new_mode, _old_oid, new_oid, status = metadata[1:]
        if status not in {"A", "D", "M", "T"}:
            raise GitBaselineError("Git transition diff status is unsupported")
        if old_mode == "160000" or new_mode == "160000":
            raise GitBaselineError("Gitlink transitions are unsupported")
        if status == "D":
            oid: str | None = None
        else:
            if not _valid_git_oid(new_oid):
                raise GitBaselineError(
                    "Git transition diff contains an invalid object ID"
                )
            oid = new_oid
        parsed[current_commit].append((path, oid))
        index += 2
    if tuple(parsed) != commits:
        raise GitBaselineError("Git transition diff omitted a requested commit")
    object_ids = tuple(
        dict.fromkeys(
            oid
            for changes in parsed.values()
            for _path, oid in changes
            if oid is not None
        )
    )
    blobs = _read_transition_blobs(
        runner,
        object_ids,
        limits=limits,
        blob_cache=blob_cache,
    )
    return {
        commit: tuple(
            (path, None if oid is None else blobs[oid]) for path, oid in sorted(changes)
        )
        for commit, changes in parsed.items()
    }


def _read_transition_blobs(
    runner: _GitRunner,
    object_ids: tuple[str, ...],
    *,
    limits: GitLimits,
    blob_cache: dict[str, bytes] | None = None,
) -> dict[str, bytes]:
    """Read unique transition blobs in one bounded object batch."""

    cache = {} if blob_cache is None else blob_cache
    missing = tuple(oid for oid in object_ids if oid not in cache)
    payloads = _read_batch_objects(runner, missing, expected_type="blob")
    total = 0
    for oid, payload in payloads.items():
        runner.budget.check_deadline()
        if len(payload) > limits.maximum_file_bytes:
            raise GitBaselineError(f"transition blob exceeds byte limit: {oid}")
        total += len(payload)
        if total > limits.maximum_baseline_bytes:
            raise GitBaselineError("intent coverage transition byte budget exceeded")
    cache.update(payloads)
    return {oid: cache[oid] for oid in object_ids}


def _parse_history_identities(
    raw: bytes,
    *,
    newest_first: bool,
) -> tuple[tuple[tuple[str, str], ...], bool]:
    identities: list[tuple[str, str]] = []
    reached_root = False
    for line_number in range(1, lf_line_count(raw) + 1):
        line = lf_slice(raw, line_number, line_number, policy="strict").removesuffix(
            b"\n"
        )
        if not line:
            continue
        try:
            fields = line.decode("ascii").split()
        except UnicodeError as error:
            raise GitBaselineError(
                "Git history contains a non-ASCII object ID"
            ) from error
        if not fields:
            raise GitBaselineError("Git first-parent history is malformed")
        commit = _decode_oid((fields[0] + "\n").encode())
        if len(fields) == 1:
            reached_root = True
            continue
        parent = _decode_oid((fields[1] + "\n").encode())
        identities.append((parent, commit))
    if not newest_first:
        reached_root = True
    return tuple(identities), reached_root


def _read_batch_objects(
    runner: _GitRunner,
    object_ids: tuple[str, ...],
    *,
    expected_type: str,
) -> dict[str, bytes]:
    if not object_ids:
        return {}
    raw = runner.run(
        ("cat-file", "--batch"),
        stdin=b"".join((oid + "\n").encode("ascii") for oid in object_ids),
    )
    offset = 0
    result: dict[str, bytes] = {}
    for oid in object_ids:
        newline = raw.find(b"\n", offset)
        if newline < 0:
            raise GitBaselineError("Git batch object response is truncated")
        try:
            actual_oid, object_type, raw_size = (
                raw[offset:newline].decode("ascii").split(" ")
            )
            size = int(raw_size)
        except (UnicodeError, ValueError) as error:
            raise GitBaselineError("Git batch object header is invalid") from error
        offset = newline + 1
        end = offset + size
        if (
            actual_oid != oid
            or object_type != expected_type
            or size < 0
            or end >= len(raw)
            or raw[end : end + 1] != b"\n"
        ):
            raise GitBaselineError("Git batch object identity is inconsistent")
        result[oid] = raw[offset:end]
        offset = end + 1
    if offset != len(raw):
        raise GitBaselineError("Git batch object response has trailing data")
    return result


def _commit_message(raw_commit: bytes) -> bytes:
    separator = raw_commit.find(b"\n\n")
    if separator < 0:
        raise GitBaselineError("Git commit object has no message separator")
    return raw_commit[separator + 2 :]


def policy_identity(policy: Mapping[str, object]) -> str:
    """Return the exact canonical intent-coverage policy identity."""

    return _stable_hash(policy)


def compare_coverage_policies(
    baseline: Mapping[str, object],
    current: Mapping[str, object],
    *,
    parent_commit: str,
    transition_commit: str | None = None,
    commit_message: str = "",
) -> tuple[PolicyEvent, ...]:
    """Classify all current weakening and authority-sensitive policy events."""

    candidates = _policy_changes(baseline, current)
    events = tuple(
        _policy_event(
            parent_commit=parent_commit,
            transition_commit=transition_commit,
            key=key,
            before=before,
            after=after,
        )
        for key, before, after, transition in sorted(candidates, key=lambda row: row[0])
        if transition in ("weakening", "authority_sensitive")
    )
    acknowledgments = parse_acknowledgments(
        commit_message if transition_commit is not None else ""
    )
    return tuple(_acknowledge_policy_event(event, acknowledgments) for event in events)


def fold_policy_transitions(
    transitions: Sequence[PolicyTransition],
) -> tuple[PolicyEvent, ...]:
    """Keep only events that established final weakened/authority-sensitive values."""

    active: dict[str, PolicyEvent] = {}
    for item in transitions:
        acknowledgments = parse_acknowledgments(
            item.commit_message if item.transition_commit is not None else ""
        )
        for key, before, after, classification in sorted(
            _policy_changes(item.before, item.after),
            key=lambda row: row[0],
        ):
            active.pop(key, None)
            if classification not in ("weakening", "authority_sensitive"):
                continue
            event = _policy_event(
                parent_commit=item.parent_commit,
                transition_commit=item.transition_commit,
                key=key,
                before=before,
                after=after,
            )
            active[key] = _acknowledge_policy_event(event, acknowledgments)
    return tuple(active[key] for key in sorted(active))


def _policy_event(
    *,
    parent_commit: str,
    transition_commit: str | None,
    key: str,
    before: object,
    after: object,
) -> PolicyEvent:
    return PolicyEvent(
        event_id=_stable_hash(
            [
                "intent-policy-event-v1",
                parent_commit,
                key,
                before,
                after,
            ]
        ),
        parent_commit=parent_commit,
        key=key,
        baseline_value=before,
        current_value=after,
        transition_commit=transition_commit,
    )


def _policy_changes(
    baseline: Mapping[str, object],
    current: Mapping[str, object],
) -> list[
    tuple[
        str,
        object,
        object,
        Literal["weakening", "strengthening", "neutral", "authority_sensitive"],
    ]
]:
    changes: list[
        tuple[
            str,
            object,
            object,
            Literal["weakening", "strengthening", "neutral", "authority_sensitive"],
        ]
    ] = []
    old_profile = _mapping(baseline.get("profile"))
    new_profile = _mapping(current.get("profile"))
    old_coverage = _mapping(baseline.get("coverage"))
    new_coverage = _mapping(current.get("coverage"))
    if old_profile.get("name") != new_profile.get("name"):
        changes.append(
            (
                "/profile/name",
                old_profile.get("name"),
                new_profile.get("name"),
                "weakening",
            )
        )
    for key in ("ratchet_base", "granularity"):
        before, after = old_coverage.get(key), new_coverage.get(key)
        if before != after and (key != "ratchet_base" or bool(before) or bool(after)):
            changes.append((f"/coverage/{key}", before, after, "weakening"))
    before_mode, after_mode = old_coverage.get("mode"), new_coverage.get("mode")
    if before_mode != after_mode:
        changes.append(
            (
                "/coverage/mode",
                before_mode,
                after_mode,
                "strengthening" if after_mode == "ratchet" else "weakening",
            )
        )
    before_inherited = old_coverage.get("inherited_counts")
    after_inherited = new_coverage.get("inherited_counts")
    if before_inherited != after_inherited:
        changes.append(
            (
                "/coverage/inherited_counts",
                before_inherited,
                after_inherited,
                "weakening" if after_inherited is True else "strengthening",
            )
        )
    for key in ("spec_roots", "code_roots"):
        _append_set_changes(
            changes,
            f"/profile/{key}",
            old_profile.get(key),
            new_profile.get(key),
            addition="strengthening",
        )
    for key in (
        "planned_spec_globs",
        "exploratory_spec_globs",
        "meta_spec_globs",
        "process_spec_globs",
    ):
        _append_set_changes(
            changes,
            f"/profile/{key}",
            old_profile.get(key),
            new_profile.get(key),
            addition="weakening",
        )
    _append_set_changes(
        changes,
        "/exclude",
        baseline.get("exclude"),
        current.get("exclude"),
        addition="weakening",
    )
    _append_set_changes(
        changes,
        "/profile/test_roots",
        old_profile.get("test_roots"),
        new_profile.get("test_roots"),
        addition="weakening",
        any_change_sensitive=True,
    )
    _append_exemption_changes(changes, old_coverage, new_coverage)
    _append_floor_changes(changes, old_coverage, new_coverage)
    for key in ("diagnostics", "suppressions"):
        before, after = baseline.get(key), current.get(key)
        if canonical_json_bytes(before) != canonical_json_bytes(after):
            changes.append((f"/{key}", before, after, "authority_sensitive"))
    return changes


def _append_set_changes(
    changes: list[
        tuple[
            str,
            object,
            object,
            Literal["weakening", "strengthening", "neutral", "authority_sensitive"],
        ]
    ],
    prefix: str,
    before_value: object,
    after_value: object,
    *,
    addition: Literal["weakening", "strengthening"],
    any_change_sensitive: bool = False,
) -> None:
    before = {_stable_member(item): item for item in _sequence(before_value)}
    after = {_stable_member(item): item for item in _sequence(after_value)}
    removal: Literal["weakening", "strengthening"] = (
        "weakening" if addition == "strengthening" else "strengthening"
    )
    for identity in sorted(before.keys() | after.keys()):
        if identity in before and identity in after:
            continue
        if any_change_sensitive:
            transition: Literal["weakening", "strengthening"] = "weakening"
        elif identity in after:
            transition = addition
        else:
            transition = removal
        changes.append(
            (
                f"{prefix}/{identity}",
                before.get(identity),
                after.get(identity),
                transition,
            )
        )


def _append_exemption_changes(
    changes: list[
        tuple[
            str,
            object,
            object,
            Literal["weakening", "strengthening", "neutral", "authority_sensitive"],
        ]
    ],
    baseline: Mapping[str, object],
    current: Mapping[str, object],
) -> None:
    before = {
        str(row["id"]): row
        for row in _mapping_sequence(baseline.get("exemptions"))
        if "id" in row
    }
    after = {
        str(row["id"]): row
        for row in _mapping_sequence(current.get("exemptions"))
        if "id" in row
    }
    for identity in sorted(before.keys() | after.keys()):
        old, new = before.get(identity), after.get(identity)
        if old is None:
            changes.append((f"/coverage/exemptions/{identity}", None, new, "weakening"))
        elif new is None:
            changes.append(
                (f"/coverage/exemptions/{identity}", old, None, "strengthening")
            )
        elif (old.get("kind"), old.get("selector")) != (
            new.get("kind"),
            new.get("selector"),
        ):
            changes.append(
                (f"/coverage/exemptions/{identity}", old, None, "strengthening")
            )
            changes.append((f"/coverage/exemptions/{identity}", None, new, "weakening"))


def _append_floor_changes(
    changes: list[
        tuple[
            str,
            object,
            object,
            Literal["weakening", "strengthening", "neutral", "authority_sensitive"],
        ]
    ],
    baseline: Mapping[str, object],
    current: Mapping[str, object],
) -> None:
    before = {
        str(row["scope"]): row
        for row in _mapping_sequence(baseline.get("floors"))
        if "scope" in row
    }
    after = {
        str(row["scope"]): row
        for row in _mapping_sequence(current.get("floors"))
        if "scope" in row
    }
    for scope in sorted(before.keys() | after.keys()):
        scope_hash = _stable_member(scope)
        for metric in ("direct", "accounted"):
            old = before.get(scope, {}).get(metric)
            new = after.get(scope, {}).get(metric)
            if old == new:
                continue
            weakening = new is None or (
                old is not None and _floor_number(new) < _floor_number(old)
            )
            changes.append(
                (
                    f"/coverage/floors/{scope_hash}/{metric}",
                    old,
                    new,
                    "weakening" if weakening else "strengthening",
                )
            )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _floor_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("canonical coverage floor is not numeric")
    return float(value)


def _sequence(value: object) -> tuple[object, ...]:
    return tuple(value) if isinstance(value, (tuple, list)) else ()


def _mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    return tuple(row for row in _sequence(value) if isinstance(row, Mapping))


def _stable_member(value: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def edge_identity(
    spec_path: str,
    section_id: str,
    code_path: str,
    structural_locator: str,
) -> str:
    """Return the exact COV-8 stable edge identity."""

    return _stable_hash(
        [
            "intent-edge-v1",
            spec_path,
            section_id,
            code_path,
            structural_locator,
        ]
    )


def mapping_identity(rows: Sequence[Sequence[str | None]]) -> str:
    """Hash the sorted unique resolved mapping-set projection."""

    materialized = {tuple(row) for row in rows}
    if any(
        len(row) != 2
        or not isinstance(row[0], str)
        or (row[1] is not None and not isinstance(row[1], str))
        for row in materialized
    ):
        raise ValueError("mapping identity rows are invalid")
    normalized = sorted(
        materialized,
        key=lambda row: (row[0], "" if row[1] is None else row[1]),
    )
    return _stable_hash(["intent-mapping-set-v1", [list(row) for row in normalized]])


def connected_test_identity(rows: Sequence[tuple[str, str]]) -> str:
    """Hash the sorted unique connected-test projection."""

    normalized = sorted(set(rows))
    return _stable_hash(
        ["intent-connected-tests-v1", [list(row) for row in normalized]]
    )


def section_projection_hash(
    source: bytes,
    *,
    section_start_line: int,
    section_end_line: int,
    mapping_block_spans: Sequence[tuple[str, int, int]],
    section_id: str,
) -> tuple[bytes, str]:
    """Remove parser-owned mapping byte intervals and hash the retained bytes."""

    line_count = lf_line_count(source)
    if (
        section_start_line < 1
        or section_end_line < section_start_line
        or section_end_line > line_count
    ):
        raise ValueError("section span is outside source")
    removed_spans: list[tuple[int, int]] = []
    for owner, start_line, end_line in mapping_block_spans:
        if owner != section_id:
            continue
        if (
            start_line < section_start_line
            or end_line < start_line
            or end_line > section_end_line
        ):
            raise ValueError("mapping block span is outside its section")
        removed_spans.append((start_line, end_line))
    projection_parts: list[bytes] = []
    cursor = section_start_line
    for start_line, end_line in sorted(removed_spans):
        if start_line > cursor:
            projection_parts.append(
                lf_slice(source, cursor, start_line - 1, policy="strict")
            )
        cursor = max(cursor, end_line + 1)
    if cursor <= section_end_line:
        projection_parts.append(
            lf_slice(source, cursor, section_end_line, policy="strict")
        )
    projection = b"".join(projection_parts)
    return projection, _SHA256_PREFIX + hashlib.sha256(projection).hexdigest()


def compute_drift_event(transition: DriftTransition) -> DriftEvent | None:
    """Apply the exact four-input COV-8 drift predicate to one edge transition."""

    before, after = transition.before, transition.after
    if before.edge_id != after.edge_id:
        raise ValueError("drift transition edge identities differ")
    if before.implementation_hash == after.implementation_hash:
        return None
    if (
        before.section_hash != after.section_hash
        or before.mapping_hash != after.mapping_hash
        or before.connected_test_hash != after.connected_test_hash
    ):
        return None
    preimage = [
        "intent-drift-event-v1",
        after.edge_id,
        transition.parent_commit,
        before.section_hash,
        after.section_hash,
        before.mapping_hash,
        after.mapping_hash,
        before.implementation_hash,
        after.implementation_hash,
        before.connected_test_hash,
        after.connected_test_hash,
    ]
    event = DriftEvent(
        event_id=_stable_hash(preimage),
        edge_id=after.edge_id,
        requirement_id=after.requirement_id,
        definition_id=after.definition_id,
        parent_commit=transition.parent_commit,
        transition_commit=transition.child_commit,
        base_projection_sha256=before.implementation_hash,
        current_projection_sha256=after.implementation_hash,
        before_section_hash=before.section_hash,
        after_section_hash=after.section_hash,
        before_mapping_hash=before.mapping_hash,
        after_mapping_hash=after.mapping_hash,
        before_connected_test_hash=before.connected_test_hash,
        after_connected_test_hash=after.connected_test_hash,
        synthetic_current=transition.child_commit is None,
    )
    if transition.child_commit is None:
        return event
    acknowledgments = parse_acknowledgments(transition.commit_message)
    return _acknowledge_drift_event(event, acknowledgments)


def parse_acknowledgments(message: str) -> tuple[Acknowledgment, ...]:
    """Parse bounded trailer-shaped lines without giving malformed rows authority."""

    lines = [
        lf_slice(message, line_number, line_number, policy="strict").removesuffix("\n")
        for line_number in range(1, lf_line_count(message) + 1)
    ]
    while lines and not lines[-1].strip():
        lines.pop()
    paragraph_start = (
        max(
            (index for index, line in enumerate(lines) if not line.strip()),
            default=-1,
        )
        + 1
    )
    candidates: list[
        tuple[Literal["drift", "policy"], str | None, str | None, str, str]
    ] = []
    for raw in lines[paragraph_start:]:
        if raw.startswith(_DRIFT_TRAILER):
            kind: Literal["drift", "policy"] = "drift"
            value = raw[len(_DRIFT_TRAILER) :].strip()
        elif raw.startswith(_POLICY_TRAILER):
            kind = "policy"
            value = raw[len(_POLICY_TRAILER) :].strip()
        else:
            continue
        event_id: str | None = None
        reason: str | None = None
        if " -- " in value:
            candidate, candidate_reason = value.split(" -- ", 1)
            if _valid_sha256_token(candidate) and candidate_reason.strip():
                event_id = candidate
                reason = candidate_reason.strip()
        candidates.append((kind, event_id, reason, raw, value))
    counts: dict[tuple[str, str], int] = {}
    for kind, event_id, _, _, value in candidates:
        key = (kind, event_id or value)
        counts[key] = counts.get(key, 0) + 1
    parsed: list[Acknowledgment] = []
    for kind, event_id, reason, raw, value in candidates:
        duplicate = counts[(kind, event_id or value)] > 1
        parsed.append(
            Acknowledgment(
                kind=kind,
                event_id=event_id,
                reason=reason,
                valid=event_id is not None and not duplicate,
                duplicate=duplicate,
                raw=raw,
            )
        )
    return tuple(parsed)


def _acknowledge_drift_event(
    event: DriftEvent,
    acknowledgments: tuple[Acknowledgment, ...],
) -> DriftEvent:
    matches = [
        row
        for row in acknowledgments
        if row.kind == "drift" and row.valid and row.event_id == event.event_id
    ]
    if len(matches) != 1:
        return event
    return replace(
        event,
        acknowledged=True,
        acknowledgment_commit=event.transition_commit,
        acknowledgment_reason=matches[0].reason,
    )


def _acknowledge_policy_event(
    event: PolicyEvent,
    acknowledgments: tuple[Acknowledgment, ...],
) -> PolicyEvent:
    matches = [
        row
        for row in acknowledgments
        if row.kind == "policy" and row.valid and row.event_id == event.event_id
    ]
    if len(matches) != 1:
        return event
    return replace(
        event,
        acknowledged=True,
        acknowledgment_commit=event.transition_commit,
        acknowledgment_reason=matches[0].reason,
    )


def compute_stale_doc_trend(
    edge_id: str,
    transitions: Sequence[DriftTransition],
    *,
    history_complete: bool,
) -> StaleDocTrend:
    """Fold a bounded chronological edge history after its latest doc change."""

    relevant = [
        row
        for row in transitions
        if row.before.edge_id == edge_id and row.after.edge_id == edge_id
    ]
    latest_section_change = max(
        (
            index
            for index, row in enumerate(relevant)
            if row.before.section_hash != row.after.section_hash
        ),
        default=None,
    )
    start = 0 if latest_section_change is None else latest_section_change
    events = tuple(
        event
        for row in relevant[start:]
        if (event := compute_drift_event(row)) is not None and not event.acknowledged
    )
    section_change_commit = (
        relevant[latest_section_change].child_commit
        if latest_section_change is not None
        else None
    )
    complete = history_complete or latest_section_change is not None
    return StaleDocTrend(
        edge_id=edge_id,
        section_change_commit=section_change_commit,
        unacknowledged_event_count=len(events),
        last_event_commit=(events[-1].transition_commit if events else None),
        history_complete=complete,
        commits_inspected=len(relevant),
    )


def _valid_sha256_token(value: str) -> bool:
    return is_prefixed_sha256(value)


def _valid_git_oid(value: str) -> bool:
    if len(value) not in (40, 64):
        return False
    try:
        decoded = bytes.fromhex(value)
    except ValueError:
        return False
    return decoded.hex() == value


def _stable_hash(value: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(canonical_json_bytes(value)).hexdigest()
