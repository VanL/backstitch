from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import tomllib
import urllib.error
from email.message import Message
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_verifier_module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "scripts"
        / "verify_pypi_release.py"
    )
    spec = importlib.util.spec_from_file_location("backstitch_pypi_verifier", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verifier = _load_verifier_module()


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _distribution(
    filename: str,
    package_type: str,
    raw: bytes,
    *,
    host: str = "files.pythonhosted.org",
) -> dict[str, object]:
    return {
        "filename": filename,
        "packagetype": package_type,
        "digests": {"sha256": _digest(raw)},
        "url": f"https://{host}/packages/{filename}",
    }


def _metadata(
    wheel_raw: bytes = b"wheel",
    sdist_raw: bytes = b"sdist",
    *,
    urls: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "info": {"name": "Backstitch", "version": "1.2.3"},
        "urls": urls
        if urls is not None
        else [
            _distribution(
                "backstitch-1.2.3-py3-none-any.whl", "bdist_wheel", wheel_raw
            ),
            _distribution("backstitch-1.2.3.tar.gz", "sdist", sdist_raw),
        ],
    }


class _Response(io.BytesIO):
    def __init__(
        self,
        raw: bytes,
        *,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(raw)
        self._url = url
        self.headers = headers or {}

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def test_fetch_metadata_uses_normalized_exact_version_and_strict_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[tuple[str, str]] = []
    payload = _metadata()

    def open_url(url: str, *, final_host: str) -> _Response:
        opened.append((url, final_host))
        return _Response(
            json.dumps(payload).encode(),
            url="https://pypi.org/pypi/backstitch/1.2.3/json",
        )

    monkeypatch.setattr(verifier, "_open_url", open_url)

    assert verifier.fetch_pypi_metadata("Back_stitch", "1.2.3") == payload
    assert opened == [("https://pypi.org/pypi/back-stitch/1.2.3/json", "pypi.org")]


def test_metadata_rejects_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response(
        b"{}",
        url="https://pypi.org/pypi/backstitch/1.2.3/json",
        headers={"Content-Length": str(verifier.MAX_METADATA_BYTES + 1)},
    )
    monkeypatch.setattr(verifier, "_open_url", lambda *args, **kwargs: response)

    with pytest.raises(RuntimeError, match="response limit"):
        verifier.fetch_pypi_metadata("backstitch", "1.2.3")


def test_poll_retries_only_absence_and_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[object] = [
        urllib.error.HTTPError("url", 404, "missing", Message(), None),
        urllib.error.URLError("temporary"),
        _metadata(),
    ]
    sleeps: list[int] = []

    def fetch(package: str, version: str) -> object:
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(verifier, "fetch_pypi_metadata", fetch)
    monkeypatch.setattr(verifier.time, "sleep", sleeps.append)

    assert verifier.poll_pypi_metadata("backstitch", "1.2.3", retry_delays=(1, 2))
    assert sleeps == [1, 2]


def test_poll_rejects_nonretryable_http_error_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verifier,
        "fetch_pypi_metadata",
        lambda *args: (_ for _ in ()).throw(
            urllib.error.HTTPError("url", 403, "forbidden", Message(), None)
        ),
    )
    monkeypatch.setattr(
        verifier.time,
        "sleep",
        lambda delay: pytest.fail("must not retry integrity failure"),
    )

    with pytest.raises(RuntimeError, match="HTTP 403"):
        verifier.poll_pypi_metadata("backstitch", "1.2.3", retry_delays=(1,))


@pytest.mark.parametrize(
    "urls, message",
    [
        ([], "exactly one wheel and one sdist"),
        (
            [
                _distribution("a.whl", "bdist_wheel", b"a"),
                _distribution("b.whl", "bdist_wheel", b"b"),
                _distribution("a.tar.gz", "sdist", b"c"),
            ],
            "exactly one wheel and one sdist",
        ),
        (
            [
                _distribution("a.whl", "bdist_wheel", b"a"),
                _distribution("a.zip", "bdist_egg", b"b"),
            ],
            "invalid distribution record",
        ),
        (
            [
                _distribution("../a.whl", "bdist_wheel", b"a"),
                _distribution("a.tar.gz", "sdist", b"b"),
            ],
            "invalid distribution record",
        ),
        (
            [
                _distribution("a.whl", "bdist_wheel", b"a", host="evil.example"),
                _distribution("a.tar.gz", "sdist", b"b"),
            ],
            "URL host",
        ),
        (
            [
                _distribution("a.tar.gz", "bdist_wheel", b"a"),
                _distribution("b.whl", "sdist", b"b"),
            ],
            "wheel record",
        ),
    ],
)
def test_release_set_rejects_missing_extra_unsafe_or_untrusted_files(
    urls: list[dict[str, object]], message: str
) -> None:
    with pytest.raises(RuntimeError, match=message):
        verifier.parse_indexed_distributions(
            _metadata(urls=urls), "backstitch", "1.2.3"
        )


def test_release_set_rejects_wrong_package_or_version() -> None:
    wrong_name = _metadata()
    wrong_name["info"] = {"name": "other", "version": "1.2.3"}
    wrong_version = _metadata()
    wrong_version["info"] = {"name": "backstitch", "version": "9.9.9"}

    with pytest.raises(RuntimeError, match="package identity"):
        verifier.parse_indexed_distributions(wrong_name, "backstitch", "1.2.3")
    with pytest.raises(RuntimeError, match="version mismatch"):
        verifier.parse_indexed_distributions(wrong_version, "backstitch", "1.2.3")


def test_expected_ledger_requires_exact_filename_and_digest(tmp_path: Path) -> None:
    wheel = tmp_path / "backstitch-1.2.3-py3-none-any.whl"
    sdist = tmp_path / "backstitch-1.2.3.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    indexed = verifier.parse_indexed_distributions(_metadata(), "backstitch", "1.2.3")

    verifier.require_expected_distributions(indexed, (wheel, sdist))
    wheel.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="do not match expected"):
        verifier.require_expected_distributions(indexed, (wheel, sdist))


def test_download_enforces_final_host_size_and_digest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = b"indexed artifact"
    distribution = verifier.IndexedDistribution(
        "backstitch.whl",
        "bdist_wheel",
        _digest(raw),
        "https://files.pythonhosted.org/packages/backstitch.whl",
    )
    monkeypatch.setattr(
        verifier,
        "_open_url",
        lambda url, *, final_host: _Response(
            raw, url=url, headers={"Content-Length": str(len(raw))}
        ),
    )
    destination = tmp_path / distribution.filename

    verifier.download_distribution(distribution, destination)
    assert destination.read_bytes() == raw

    bad = verifier.IndexedDistribution(
        distribution.filename,
        distribution.package_type,
        "0" * 64,
        distribution.url,
    )
    destination.unlink()
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        verifier.download_distribution(bad, destination)
    assert not destination.exists()


def test_open_url_rejects_credentials_and_wrong_final_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RuntimeError, match="credentials"):
        verifier._open_url(
            "https://user:secret@files.pythonhosted.org/file.whl",
            final_host="files.pythonhosted.org",
        )

    class _Opener:
        def open(self, url: str, *, timeout: float) -> _Response:
            return _Response(b"x", url="https://evil.example/file.whl")

    monkeypatch.setattr(
        verifier.urllib.request, "build_opener", lambda handler: _Opener()
    )
    with pytest.raises(RuntimeError, match="Final response host"):
        verifier._open_url(
            "https://files.pythonhosted.org/file.whl",
            final_host="files.pythonhosted.org",
        )


def test_redirect_handler_rejects_downgrade_and_excess_redirects() -> None:
    handler = verifier._BoundedHTTPSRedirectHandler(1)
    request = verifier.urllib.request.Request("https://files.pythonhosted.org/file")

    with pytest.raises(RuntimeError, match="absolute HTTPS"):
        handler.redirect_request(request, None, 302, "found", {}, "http://example/file")
    with pytest.raises(RuntimeError, match="redirect limit"):
        handler.redirect_request(
            request, None, 302, "found", {}, "https://files.pythonhosted.org/file2"
        )


def test_verify_release_downloads_and_smokes_both_then_cleans(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    wheel = ledger / "backstitch-1.2.3-py3-none-any.whl"
    sdist = ledger / "backstitch-1.2.3.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    work_root = tmp_path / "temporary"
    work_root.mkdir()
    indexed = verifier.parse_indexed_distributions(_metadata(), "backstitch", "1.2.3")
    monkeypatch.setattr(verifier, "poll_pypi_metadata", lambda *args: _metadata())
    downloads: list[tuple[str, Path]] = []
    smokes: list[tuple[str, str]] = []

    def download(item: Any, destination: Path) -> None:
        downloads.append((item.filename, destination))
        destination.write_bytes(
            b"wheel" if item.package_type == "bdist_wheel" else b"sdist"
        )

    def smoke(
        artifact: Path,
        environment: Path,
        *,
        repository_root: Path,
        version: str,
    ) -> None:
        assert repository_root == repository.resolve()
        assert not artifact.is_relative_to(repository_root)
        smokes.append((artifact.name, environment.name))

    monkeypatch.setattr(verifier, "parse_indexed_distributions", lambda *args: indexed)
    monkeypatch.setattr(verifier, "download_distribution", download)
    monkeypatch.setattr(verifier, "smoke_distribution", smoke)

    verifier.verify_release(
        package="backstitch",
        version="1.2.3",
        wheel=wheel,
        sdist=sdist,
        repository_root=repository,
        work_root=work_root,
    )

    assert [name for name, _ in downloads] == [wheel.name, sdist.name]
    assert smokes == [(wheel.name, "wheel-env"), (sdist.name, "sdist-env")]
    assert list(work_root.iterdir()) == []


def test_verify_release_cleans_after_failure_and_rejects_checkout_work_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    wheel = tmp_path / "a.whl"
    sdist = tmp_path / "a.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    work_root = tmp_path / "temporary"
    work_root.mkdir()
    monkeypatch.setattr(
        verifier,
        "poll_pypi_metadata",
        lambda *args: (_ for _ in ()).throw(RuntimeError("primary failure")),
    )

    with pytest.raises(RuntimeError, match="primary failure"):
        verifier.verify_release(
            package="backstitch",
            version="1.2.3",
            wheel=wheel,
            sdist=sdist,
            repository_root=repository,
            work_root=work_root,
        )
    assert list(work_root.iterdir()) == []

    nested = repository / "tmp"
    nested.mkdir()
    with pytest.raises(RuntimeError, match="outside the repository"):
        verifier.verify_release(
            package="backstitch",
            version="1.2.3",
            wheel=wheel,
            sdist=sdist,
            repository_root=repository,
            work_root=nested,
        )


def test_cleanup_failure_does_not_hide_primary_verification_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    wheel = tmp_path / "a.whl"
    sdist = tmp_path / "a.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    work_root = tmp_path / "temporary"
    work_root.mkdir()
    monkeypatch.setattr(
        verifier,
        "poll_pypi_metadata",
        lambda *args: (_ for _ in ()).throw(RuntimeError("primary failure")),
    )
    monkeypatch.setattr(
        verifier.shutil,
        "rmtree",
        lambda path: (_ for _ in ()).throw(OSError("cleanup failure")),
    )

    with pytest.raises(RuntimeError, match="primary failure"):
        verifier.verify_release(
            package="backstitch",
            version="1.2.3",
            wheel=wheel,
            sdist=sdist,
            repository_root=repository,
            work_root=work_root,
        )


def test_built_wheel_and_sdist_install_and_smoke_outside_checkout(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    distributions = tmp_path / "dist"
    uv = shutil.which("uv")
    assert uv is not None
    subprocess.run(
        [
            uv,
            "build",
            "--out-dir",
            str(distributions),
            str(repository),
        ],
        check=True,
        capture_output=True,
    )
    wheels = tuple(distributions.glob("*.whl"))
    sdists = tuple(distributions.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1
    project = tomllib.loads((repository / "pyproject.toml").read_text())
    version = project["project"]["version"]
    assert isinstance(version, str)

    verifier.smoke_distribution(
        wheels[0],
        tmp_path / "wheel-env",
        repository_root=repository,
        version=version,
    )
    verifier.smoke_distribution(
        sdists[0],
        tmp_path / "sdist-env",
        repository_root=repository,
        version=version,
    )


def test_main_reports_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        verifier,
        "verify_release",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("digest mismatch")),
    )

    result = verifier.main(
        [
            "--package",
            "backstitch",
            "--version",
            "1.2.3",
            "--wheel",
            "a.whl",
            "--sdist",
            "a.tar.gz",
            "--repo-root",
            ".",
        ]
    )

    assert result == 1
    error = capsys.readouterr().err
    assert "digest mismatch" in error
    assert "Traceback" not in error
