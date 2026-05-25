import os
import shutil
import subprocess
import time

import pytest

WORKER_CONTAINER = os.environ.get("AI_MDFD_WORKER_CONTAINER", "deploy-celery_parent_worker-1")
GRACEFUL_TIMEOUT_SECONDS = int(os.environ.get("AI_MDFD_SIGTERM_TIMEOUT_S", "90"))


def _docker_inspect(name: str, fmt: str) -> str | None:
    result = subprocess.run(
        ["docker", "inspect", "-f", fmt, name],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _list_nim_deployments() -> set[str]:
    if not shutil.which("kubectl"):
        return set()
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "deployments",
            "-A",
            "-o",
            'jsonpath={range .items[*]}{.metadata.namespace}/{.metadata.name}{"\\n"}{end}',
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()
    return {line for line in result.stdout.strip().splitlines() if "nim" in line.lower()}


@pytest.mark.integration
@pytest.mark.T5614424
def test_worker_sigterm_graceful_shutdown_and_no_orphan_deployments():
    if not shutil.which("docker"):
        pytest.skip("docker CLI not available")

    status = _docker_inspect(WORKER_CONTAINER, "{{.State.Status}}")
    if status is None:
        pytest.skip(f"container '{WORKER_CONTAINER}' not found")
    if status != "running":
        pytest.skip(f"container '{WORKER_CONTAINER}' is '{status}', not 'running'")

    pre_nims = _list_nim_deployments()
    print(f"[Snapshot] pre-SIGTERM NIM deployments: {len(pre_nims)}")

    kill = subprocess.run(
        ["docker", "kill", "-s", "TERM", WORKER_CONTAINER],
        capture_output=True,
        text=True,
    )
    assert kill.returncode == 0, f"docker kill failed: {kill.stderr}"

    elapsed = 0
    final_status: str | None = None
    while elapsed < GRACEFUL_TIMEOUT_SECONDS:
        final_status = _docker_inspect(WORKER_CONTAINER, "{{.State.Status}}")
        print(f"  Poll {elapsed:3d}s: status={final_status}")
        if final_status == "exited":
            break
        time.sleep(2)
        elapsed += 2

    assert (
        final_status == "exited"
    ), f"Worker did not exit within {GRACEFUL_TIMEOUT_SECONDS}s (status={final_status})"

    exit_code_raw = _docker_inspect(WORKER_CONTAINER, "{{.State.ExitCode}}")
    exit_code = int(exit_code_raw) if exit_code_raw is not None else None
    assert exit_code == 0, f"Worker exited with code {exit_code}; expected 0"

    time.sleep(5)
    post_nims = _list_nim_deployments()
    orphans = post_nims - pre_nims
    assert (
        not orphans
    ), f"Found {len(orphans)} orphan NIM deployment(s): {sorted(orphans)}"

    subprocess.run(["docker", "start", WORKER_CONTAINER], capture_output=True)
