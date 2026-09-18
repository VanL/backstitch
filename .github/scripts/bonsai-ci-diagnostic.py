"""Disposable CPU-runtime diagnosis; results are not semantic quality scores."""

import copy
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(
    os.environ.get(
        "BONSAI_DIAGNOSTIC_OUTPUT", ".cache/bonsai-comparison/results/diagnostic"
    )
)
ROOT.mkdir(parents=True, exist_ok=True)
ENDPOINT = os.environ.get("BONSAI_DIAGNOSTIC_ENDPOINT", "http://127.0.0.1:11434")
CONTAINER = os.environ.get("BONSAI_DIAGNOSTIC_CONTAINER", "comparison-model")
STACKS = os.environ.get("BONSAI_DIAGNOSTIC_STACKS") == "1"
BASE = json.loads(Path(".github/scripts/bonsai-ci-request.json").read_text())
CASES = os.environ.get(
    "BONSAI_DIAGNOSTIC_CASES", "tiny-plain,full-plain,full-schema"
).split(",")


def capture(args, path, timeout=30):
    with path.open("w") as output:
        try:
            subprocess.run(
                args,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            output.write("\nDiagnostic capture timed out.\n")


for case in CASES:
    config = json.loads(
        subprocess.check_output(["docker", "inspect", CONTAINER], text=True)
    )[0]["HostConfig"]
    assert config["NanoCpus"] == 4_000_000_000
    assert config["Memory"] == config["MemorySwap"] == 16 * 1024**3
    assert not config["DeviceRequests"]
    subprocess.run(["docker", "restart", CONTAINER], check=True, timeout=60)
    ready = False
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        state = subprocess.check_output(
            ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER], text=True
        ).strip()
        if state != "true":
            capture(["docker", "logs", CONTAINER], ROOT / f"{case}.startup.log")
            raise RuntimeError("Container exited during startup")
        try:
            with urllib.request.urlopen(ENDPOINT + "/v1/models", timeout=2) as response:
                ready = response.status == 200
        except Exception:
            pass
        if ready:
            break
        time.sleep(2)
    if not ready:
        raise RuntimeError("Server did not become ready")
    payload = copy.deepcopy(BASE)
    payload["max_tokens"] = 1
    if case.startswith("tiny"):
        payload["messages"] = [
            {"role": "user", "content": "What is 2 + 2? Answer briefly."}
        ]
    if case.endswith("plain"):
        payload.pop("response_format", None)
    request_path = ROOT / f"{case}.request.json"
    request_path.write_text(json.dumps(payload))
    pid = subprocess.check_output(
        ["docker", "inspect", "-f", "{{.State.Pid}}", CONTAINER], text=True
    ).strip()
    started = time.monotonic()
    with (ROOT / f"{case}.curl.txt").open("w") as log:
        proc = subprocess.Popen(
            [
                "curl",
                "-sS",
                "--fail-with-body",
                "-N",
                "--max-time",
                "120",
                "-H",
                "Content-Type: application/json",
                "--data-binary",
                "@" + str(request_path),
                "-o",
                str(ROOT / f"{case}.response.txt"),
                "-w",
                "http=%{http_code} starttransfer=%{time_starttransfer} total=%{time_total}\n",
                ENDPOINT + "/v1/chat/completions",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            capture(
                [
                    "docker",
                    "exec",
                    CONTAINER,
                    "sh",
                    "-c",
                    "cat /proc/1/status; cat /proc/1/smaps_rollup; cat /proc/1/maps; cat /proc/1/io; cat /sys/fs/cgroup/cpu.stat; cat /sys/fs/cgroup/memory.stat; cat /sys/fs/cgroup/memory.events; cat /sys/fs/cgroup/memory.peak",
                ],
                ROOT / f"{case}.process.txt",
            )
            if STACKS:
                capture(
                    [
                        "sudo",
                        "gdb",
                        "--batch",
                        "-ex",
                        "set pagination off",
                        "-ex",
                        f"set sysroot /proc/{pid}/root",
                        "-ex",
                        f"attach {pid}",
                        "-ex",
                        "thread apply all bt 16",
                    ],
                    ROOT / f"{case}.stacks.txt",
                    timeout=20,
                )
            proc.wait(timeout=130)
    capture(
        [
            "docker",
            "exec",
            CONTAINER,
            "sh",
            "-c",
            "cat /proc/1/status; cat /proc/1/smaps_rollup; cat /proc/1/maps; cat /sys/fs/cgroup/memory.stat; cat /sys/fs/cgroup/memory.events; cat /sys/fs/cgroup/memory.peak",
        ],
        ROOT / f"{case}.after-process.txt",
    )
    elapsed = time.monotonic() - started
    capture(["docker", "logs", CONTAINER], ROOT / f"{case}.server.log")
    capture(["docker", "inspect", CONTAINER], ROOT / f"{case}.container.json")
    (ROOT / f"{case}.result.json").write_text(
        json.dumps(
            {
                "case": case,
                "curl_exit": proc.returncode,
                "elapsed_including_diagnostics_seconds": elapsed,
                "max_tokens": 1,
                "diagnostic_only": True,
            },
            indent=2,
        )
    )
    print(case, "curl_exit=", proc.returncode, "elapsed=", elapsed, flush=True)
