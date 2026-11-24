"""Trusted GitHub control job only. GET metadata/ciphertext; never decrypt or publish."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import admit_package_pilot as pilot


def gh_env():
    env = {key: value for key, value in os.environ.items() if key not in {
        "EMO_CI_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
        "GH_HOST", "GH_REPO",
    }}
    env["GH_TOKEN"] = os.environ["EMO_CI_TOKEN"]
    env["GH_PROMPT_DISABLED"] = "1"
    env["GH_PAGER"] = "cat"
    return env


def collect(destination):
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination must be new")
    destination.parent.mkdir(parents=True, exist_ok=True)
    env = gh_env()
    base = f"repos/{pilot.PUBLIC}/actions"
    root = f"{base}/runs/{pilot.RUN}"
    command = ["gh", "api", "--hostname", "github.com", "--method", "GET"]
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".cipher-pilot-") as tmp:
        staging = Path(tmp) / "transfer"
        staging.mkdir()
        metadata = {}
        for name, endpoint in {
            "run": root,
            "jobs": f"{root}/attempts/{pilot.ATTEMPT}/jobs?per_page=100",
            "artifacts": f"{root}/artifacts?per_page=100",
        }.items():
            response = subprocess.run([*command, endpoint], env=env, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      timeout=30, check=True)
            if len(response.stdout) > 2 << 20:
                raise ValueError("GitHub metadata exceeds limit")
            metadata[name] = json.loads(response.stdout)
            (staging / f"{name}.json").write_bytes(response.stdout)
        gate = pilot.admit_metadata(metadata["run"], metadata["jobs"], metadata["artifacts"])
        for artifact_id, digest, size in gate.values():
            path = staging / f"{artifact_id}.zip"
            hasher = hashlib.sha256()
            total = 0
            with subprocess.Popen([*command, f"{base}/artifacts/{artifact_id}/zip"], env=env,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as child:
                try:
                    with path.open("xb") as dest:
                        for chunk in iter(lambda: child.stdout.read(1 << 20), b""):
                            total += len(chunk)
                            if total > size:
                                raise ValueError("Ciphertext exceeds GitHub size")
                            hasher.update(chunk)
                            dest.write(chunk)
                    if child.wait(timeout=30) or total != size or "sha256:" + hasher.hexdigest() != digest:
                        raise ValueError("Ciphertext differs from trusted GitHub metadata")
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
            (staging / f"{artifact_id}.zip").chmod(0o600)
        staging.rename(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    try:
        collect(parser.parse_args().destination)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        print("pilot_control=failed")
        raise SystemExit(1) from None
    print("pilot_control=verified_ciphertext")
