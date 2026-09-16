"""Verify and smoke-test the exact distributions served by PyPI."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, NamedTuple, cast

PYPI_HOST: Final[str] = "pypi.org"
PYPI_FILES_HOST: Final[str] = "files.pythonhosted.org"
HTTP_TIMEOUT_SECONDS: Final[float] = 30.0
PYPI_RETRY_DELAYS: Final[tuple[int, ...]] = (15, 30, 60, 120)
MAX_REDIRECTS: Final[int] = 3
MAX_METADATA_BYTES: Final[int] = 4 * 1024 * 1024
MAX_DISTRIBUTION_BYTES: Final[int] = 256 * 1024 * 1024
READ_CHUNK_BYTES: Final[int] = 1024 * 1024


class IndexedDistribution(NamedTuple):
    """One distribution identity asserted by PyPI metadata."""

    filename: str
    package_type: str
    sha256: str
    url: str


class _BoundedHTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, maximum: int) -> None:
        super().__init__()
        self.maximum = maximum
        self.redirects = 0

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        self.redirects += 1
        if self.redirects > self.maximum:
            raise RuntimeError(f"HTTP redirect limit exceeded ({self.maximum})")
        _require_https_url(newurl, label="redirect target")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _require_https_url(url: str, *, label: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError(f"{label} must be an absolute HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise RuntimeError(f"{label} must not contain credentials")
    return parsed


def _open_url(url: str, *, final_host: str) -> Any:
    _require_https_url(url, label="request URL")
    opener = urllib.request.build_opener(_BoundedHTTPSRedirectHandler(MAX_REDIRECTS))
    response = opener.open(url, timeout=HTTP_TIMEOUT_SECONDS)
    final = _require_https_url(response.geturl(), label="final response URL")
    if final.hostname != final_host:
        response.close()
        raise RuntimeError(
            f"Final response host must be {final_host}, observed {final.hostname}"
        )
    return response


def _read_limited(response: Any, *, maximum: int, label: str) -> bytes:
    length = response.headers.get("Content-Length")
    if length is not None:
        try:
            declared = int(length)
        except ValueError as exc:
            raise RuntimeError(f"{label} returned invalid Content-Length") from exc
        if declared < 0 or declared > maximum:
            raise RuntimeError(f"{label} exceeds the {maximum}-byte response limit")
    raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise RuntimeError(f"{label} exceeds the {maximum}-byte response limit")
    return cast(bytes, raw)


def _normalized_package_name(name: str) -> str:
    normalized = re.sub(r"[-_.]+", "-", name).lower()
    if not normalized or not re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", normalized
    ):
        raise RuntimeError(f"Invalid package name: {name!r}")
    return normalized


def fetch_pypi_metadata(package: str, version: str) -> Mapping[str, object]:
    """Fetch one exact version's PyPI metadata with strict host and size bounds."""

    normalized = _normalized_package_name(package)
    encoded_version = urllib.parse.quote(version, safe="")
    url = f"https://{PYPI_HOST}/pypi/{normalized}/{encoded_version}/json"
    with _open_url(url, final_host=PYPI_HOST) as response:
        raw = _read_limited(response, maximum=MAX_METADATA_BYTES, label="PyPI metadata")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("PyPI metadata was not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("PyPI metadata was not a JSON object")
    return payload


def poll_pypi_metadata(
    package: str,
    version: str,
    *,
    retry_delays: Sequence[int] = PYPI_RETRY_DELAYS,
) -> Mapping[str, object]:
    """Wait for bounded PyPI visibility; integrity failures are handled later."""

    delays = iter(retry_delays)
    while True:
        try:
            return fetch_pypi_metadata(package, version)
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 404 or 500 <= exc.code < 600
            detail = f"HTTP {exc.code}"
            if not retryable:
                raise RuntimeError(f"PyPI metadata request failed: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            detail = str(exc)
        try:
            delay = next(delays)
        except StopIteration as exc:
            raise RuntimeError(
                f"PyPI metadata for {package} {version} did not become visible: {detail}"
            ) from exc
        print(f"PyPI metadata not visible ({detail}); retrying in {delay}s")
        time.sleep(delay)


def _parse_distribution(entry: object) -> IndexedDistribution:
    if not isinstance(entry, Mapping):
        raise RuntimeError("PyPI metadata contained a non-object distribution")
    filename = entry.get("filename")
    package_type = entry.get("packagetype")
    url = entry.get("url")
    digests = entry.get("digests")
    if (
        not isinstance(filename, str)
        or not filename
        or Path(filename).name != filename
        or package_type not in {"bdist_wheel", "sdist"}
        or not isinstance(url, str)
        or not isinstance(digests, Mapping)
        or not isinstance(digests.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", digests["sha256"])
    ):
        raise RuntimeError("PyPI metadata contained an invalid distribution record")
    parsed_url = _require_https_url(url, label=f"PyPI URL for {filename}")
    if parsed_url.hostname != PYPI_FILES_HOST:
        raise RuntimeError(
            f"PyPI URL host must be {PYPI_FILES_HOST}, observed {parsed_url.hostname}"
        )
    if package_type == "bdist_wheel" and not filename.endswith(".whl"):
        raise RuntimeError("PyPI wheel record did not name a .whl file")
    if package_type == "sdist" and not filename.endswith(".tar.gz"):
        raise RuntimeError("PyPI sdist record did not name a .tar.gz file")
    return IndexedDistribution(filename, package_type, digests["sha256"], url)


def parse_indexed_distributions(
    payload: Mapping[str, object], package: str, version: str
) -> tuple[IndexedDistribution, IndexedDistribution]:
    """Validate exact project/version identity and the one-wheel/one-sdist set."""

    info = payload.get("info")
    if not isinstance(info, Mapping):
        raise RuntimeError("PyPI metadata info was not a JSON object")
    observed_name = info.get("name")
    observed_version = info.get("version")
    if not isinstance(observed_name, str) or (
        _normalized_package_name(observed_name) != _normalized_package_name(package)
    ):
        raise RuntimeError(
            f"PyPI package identity mismatch: expected {package!r}, observed {observed_name!r}"
        )
    if observed_version != version:
        raise RuntimeError(
            f"PyPI version mismatch: expected {version!r}, observed {observed_version!r}"
        )

    urls = payload.get("urls")
    if not isinstance(urls, list):
        raise RuntimeError("PyPI metadata urls was not a JSON list")
    distributions = [_parse_distribution(entry) for entry in urls]

    wheels = [item for item in distributions if item.package_type == "bdist_wheel"]
    sdists = [item for item in distributions if item.package_type == "sdist"]
    if len(distributions) != 2 or len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError(
            "PyPI release must contain exactly one wheel and one sdist; "
            f"observed wheel={len(wheels)}, sdist={len(sdists)}, total={len(distributions)}"
        )
    if len({item.filename for item in distributions}) != len(distributions):
        raise RuntimeError("PyPI release contains duplicate distribution filenames")
    return wheels[0], sdists[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(READ_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_expected_distributions(
    indexed: Sequence[IndexedDistribution], expected_paths: Sequence[Path]
) -> None:
    """Require indexed filename/digest identity with the preserved ledger."""

    expected = {path.name: _sha256(path) for path in expected_paths}
    if len(expected) != len(expected_paths):
        raise RuntimeError("Expected distribution paths contain duplicate filenames")
    observed = {item.filename: item.sha256 for item in indexed}
    if observed != expected:
        raise RuntimeError(
            "PyPI distributions do not match expected filenames and SHA-256 digests; "
            f"expected={expected}, observed={observed}"
        )


def download_distribution(distribution: IndexedDistribution, destination: Path) -> None:
    """Download one indexed artifact through a bounded, credential-free path."""

    if destination.name != distribution.filename:
        raise RuntimeError("Download destination does not match indexed filename")
    digest = hashlib.sha256()
    total = 0
    with _open_url(distribution.url, final_host=PYPI_FILES_HOST) as response:
        length = response.headers.get("Content-Length")
        if length is not None:
            try:
                declared = int(length)
            except ValueError as exc:
                raise RuntimeError(
                    "Distribution returned invalid Content-Length"
                ) from exc
            if declared < 0 or declared > MAX_DISTRIBUTION_BYTES:
                raise RuntimeError("Distribution exceeds the response-size limit")
        with destination.open("xb") as stream:
            while chunk := response.read(READ_CHUNK_BYTES):
                total += len(chunk)
                if total > MAX_DISTRIBUTION_BYTES:
                    raise RuntimeError("Distribution exceeds the response-size limit")
                digest.update(chunk)
                stream.write(chunk)
    if digest.hexdigest() != distribution.sha256:
        destination.unlink(missing_ok=True)
        raise RuntimeError(
            f"Downloaded SHA-256 mismatch for {distribution.filename}: "
            f"expected={distribution.sha256}, observed={digest.hexdigest()}"
        )


def _run(command: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "no command output").strip()
        raise RuntimeError(
            f"Smoke command failed ({' '.join(command)}): {detail}"
        ) from exc


def smoke_distribution(
    artifact: Path, environment: Path, *, repository_root: Path, version: str
) -> None:
    """Install and exercise one downloaded distribution outside the checkout."""

    subprocess.run(
        [sys.executable, "-m", "venv", str(environment)],
        check=True,
        capture_output=True,
    )
    python = environment / "bin" / "python"
    executable = environment / "bin" / "backstitch"
    work_directory = environment.parent / f"work-{environment.name}"
    work_directory.mkdir()
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            str(artifact),
        ],
        cwd=work_directory,
    )
    import_probe = _run(
        [
            str(python),
            "-c",
            (
                "import pathlib, backstitch; "
                "installed=pathlib.Path(backstitch.__file__).resolve(); "
                f"environment=pathlib.Path({str(environment)!r}).resolve(); "
                "assert installed.is_relative_to(environment), "
                "f'backstitch imported outside smoke environment: {installed}'"
            ),
        ],
        cwd=work_directory,
    )
    del import_probe
    version_result = _run([str(executable), "--version"], cwd=work_directory)
    if version_result.stdout.strip() != f"backstitch {version}":
        raise RuntimeError(
            "Installed backstitch reported the wrong version; "
            f"expected={version!r}, output={version_result.stdout.strip()!r}"
        )
    guide_result = _run(
        [str(executable), "guide", "alignment", "--format", "json"],
        cwd=work_directory,
    )
    try:
        guide = json.loads(guide_result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Alignment-guide smoke probe did not return valid JSON"
        ) from exc
    if not isinstance(guide, Mapping) or guide.get("backstitch_version") != version:
        raise RuntimeError("Alignment-guide smoke probe reported the wrong version")
    _run(
        [str(executable), "check", "--repo-root", str(repository_root)],
        cwd=work_directory,
    )


def verify_release(
    *,
    package: str,
    version: str,
    wheel: Path,
    sdist: Path,
    repository_root: Path,
    work_root: Path | None = None,
) -> None:
    """Verify the PyPI bytes against a ledger and smoke both distributions."""

    wheel = wheel.resolve(strict=True)
    sdist = sdist.resolve(strict=True)
    repository_root = repository_root.resolve(strict=True)
    if not wheel.name.endswith(".whl") or not sdist.name.endswith(".tar.gz"):
        raise RuntimeError("Expected one .whl path and one .tar.gz path")
    if work_root is not None:
        work_root = work_root.resolve(strict=True)
        if work_root == repository_root or work_root.is_relative_to(repository_root):
            raise RuntimeError(
                "Temporary work root must be outside the repository checkout"
            )
        temporary = Path(tempfile.mkdtemp(prefix="backstitch-pypi-", dir=work_root))
    else:
        temporary = Path(tempfile.mkdtemp(prefix="backstitch-pypi-"))
        if temporary == repository_root or temporary.is_relative_to(repository_root):
            shutil.rmtree(temporary, ignore_errors=True)
            raise RuntimeError(
                "System temporary directory is inside the repository checkout"
            )
    primary_error: BaseException | None = None
    try:
        payload = poll_pypi_metadata(package, version)
        indexed = parse_indexed_distributions(payload, package, version)
        require_expected_distributions(indexed, (wheel, sdist))
        downloads = temporary / "downloads"
        downloads.mkdir()
        for item in indexed:
            download_distribution(item, downloads / item.filename)
        for item in indexed:
            label = "wheel" if item.package_type == "bdist_wheel" else "sdist"
            smoke_distribution(
                downloads / item.filename,
                temporary / f"{label}-env",
                repository_root=repository_root,
                version=version,
            )
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            shutil.rmtree(temporary)
        except OSError as cleanup_error:
            if primary_error is None:
                raise RuntimeError(
                    f"Failed to clean temporary verifier directory {temporary}: "
                    f"{cleanup_error}"
                ) from cleanup_error
            print(
                f"Warning: failed to clean temporary verifier directory "
                f"{temporary}: {cleanup_error}",
                file=sys.stderr,
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--sdist", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--work-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        verify_release(
            package=args.package,
            version=args.version,
            wheel=args.wheel,
            sdist=args.sdist,
            repository_root=args.repo_root,
            work_root=args.work_root,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"PyPI release verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"Verified indexed PyPI distributions for {args.package} {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
