"""Verify one historical public Windows pilot on a trusted private recipient; never publish."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tarfile
import tempfile
import zipfile

import master_release
from package_transport import MAX_PACKAGE, MAX_RECORD, TARGETS, recover

PUBLIC = "jsdfhasuh/emo_master_ci"
REPO = 1468905732
RUN = 45329340482
ATTEMPT = 1
HEAD = "01903c320a46ef562277a37bd34d12ba27e03e3b"
BRANCH = "dot/encrypted-package-pilot-20261124"
WORKFLOW = ".github/workflows/encrypted-package-pilot.yml"
PACKAGER = "9657775338b0c4afa19ccab3a45792c146752203"
CALLABLE = "jsdfhasuh/python_build_scripts/.github/workflows/emo-master-encrypted-package-pilot.yml"
SOURCE = "2e46f24b88f8624937b4465ddaf4490cbe831fb7"
TAG = "v0.6.6"
DIGESTS = {
    "emo-master": "sha256:0f839a52e2cbe01093392c9599b9256de1d4a808e17511e8f5396025095cea93",
    "emo-master-runtime": "sha256:0d9b201e8f023283c382e319249531cb04ba2bf4ccae7a1a86b7fe2bd7544077",
}
MAX_CIPHER = 2 * MAX_PACKAGE + 4 * MAX_RECORD + (8 << 20)


def admit_metadata(run, jobs, artifacts):
    if (run["id"], run["run_attempt"], run["head_sha"], run["head_branch"], run["event"],
        run["status"], run["conclusion"], run["path"]) != (
            RUN, ATTEMPT, HEAD, BRANCH, "push", "completed", "success", WORKFLOW):
        raise ValueError("Run does not match the authorized pilot")
    for key in ("repository", "head_repository"):
        if run[key]["id"] != REPO or run[key]["full_name"] != PUBLIC:
            raise ValueError("Untrusted workflow repository")
    refs = run.get("referenced_workflows") or []
    if len(refs) != 1 or refs[0].get("path") != f"{CALLABLE}@{PACKAGER}" or refs[0].get("sha") != PACKAGER:
        raise ValueError("Pinned external workflow not attested by GitHub")
    rows = jobs["jobs"]
    names = {f"package-pilot / Read-only public fixture / {target}" for target in TARGETS}
    if (len(rows) != len(names) or {row["name"] for row in rows} != names
        or any((row["run_id"], row["run_attempt"], row["status"], row["conclusion"]) !=
               (RUN, ATTEMPT, "completed", "success") for row in rows)):
        raise ValueError("Exact successful target jobs not attested")
    output = {}
    for target in TARGETS:
        matches = [r for r in artifacts["artifacts"] if r["name"] == f"encrypted-package-{target}-{RUN}-{ATTEMPT}"]
        if len(matches) != 1:
            raise ValueError("Missing or duplicate package artifact name")
        item = matches[0]
        work = item["workflow_run"]
        if (type(item["id"]) is not int or item["id"] <= 0 or item["expired"] is not False
            or item["digest"] != DIGESTS[target] or (work["id"], work["repository_id"], work["head_sha"]) != (RUN, REPO, HEAD)
            or not 0 < item["size_in_bytes"] <= MAX_CIPHER + (1 << 20)):
            raise ValueError("Artifact identity or digest mismatch")
        output[target] = (item["id"], item["digest"], item["size_in_bytes"])
    if len({row[0] for row in output.values()}) != len(TARGETS):
        raise ValueError("Reused artifact ID")
    return output


def unwrap(outer, digest, expected_size, ciphertext):
    with outer.open("rb") as raw:
        if os.fstat(raw.fileno()).st_size != expected_size:
            raise ValueError("GitHub artifact size mismatch")
        h = hashlib.sha256()
        for chunk in iter(lambda: raw.read(1 << 20), b""):
            h.update(chunk)
        if "sha256:" + h.hexdigest() != digest:
            raise ValueError("GitHub artifact digest mismatch")
        raw.seek(0)
        with zipfile.ZipFile(raw) as bundle:
            members = bundle.infolist()
            if len(members) != 1:
                raise ValueError("Unexpected outer zip members")
            entry = members[0]
            mode = stat.S_IFMT(entry.external_attr >> 16)
            if (entry.filename != "package.tar.age" or mode not in (0, stat.S_IFREG)
                or not 0 < entry.file_size <= MAX_CIPHER or entry.flag_bits & 1):
                raise ValueError("Unexpected ciphertext member")
            with bundle.open(entry) as src:
                header = src.read(len(b"age-encryption.org/v1\n"))
                if header != b"age-encryption.org/v1\n":
                    raise ValueError("No age header")
                with ciphertext.open("xb") as dst:
                    dst.write(header)
                    for chunk in iter(lambda: src.read(1 << 20), b""):
                        dst.write(chunk)


def verify_runtime(folder):
    identity = master_release.readObject(folder / "runtime-build.json")
    expected = {
        "source_repo": master_release.REPOSITORY, "source_commit": SOURCE,
        "packager_repo": "jsdfhasuh/python_build_scripts", "packager_commit": PACKAGER,
        "requested_source_ref": SOURCE, "requested_packager_ref": PACKAGER,
        "workflow_sha": HEAD, "workflow_ref": f"{PUBLIC}/{WORKFLOW}@refs/heads/{BRANCH}",
        "run_url": f"https://github.com/{PUBLIC}/actions/runs/{RUN}", "publish_requested": False,
    }
    if any(identity.get(key) != value for key, value in expected.items()):
        raise ValueError("Runtime identity does not match the pilot")
    validation = master_release.readObject(folder / "archive-check" / "validation.json")
    if validation.get("workflow_sha") != HEAD:
        raise ValueError("Runtime validation does not match the pilot workflow")


def admit(run, jobs, artifacts, downloads, age, identity, output):
    if output.exists() or output.is_symlink():
        raise ValueError("Private output must not exist")
    pin = admit_metadata(run, jobs, artifacts)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".private-pilot-") as tmp:
        base = Path(tmp)
        packages = base / "packages"
        for target, (artifact_id, digest, size) in pin.items():
            outer = downloads / f"{artifact_id}.zip"
            cipher = base / f"{target}.tar.age"
            unwrap(outer, digest, size, cipher)
            recover(cipher, packages / target, age, identity, target, TAG)
        verify_runtime(packages / "emo-master-runtime")
        request = {"release_tag": TAG, "source_commit": SOURCE, "packager_commit": PACKAGER, "publish": False}
        files = master_release.collectAssets(packages, request)
        staged = base / "non-release"
        records = master_release.stageAssets(files, staged)
        receipt = {"mode": "pilot-only", "publish": False, "run": RUN, "attempt": ATTEMPT,
                   "source": SOURCE, "packager": PACKAGER, "files": records}
        (staged / "pilot-verification.json").write_text(json.dumps(receipt) + "\n", encoding="ascii")
        staged.rename(output)


def main():
    parser = argparse.ArgumentParser()
    for name in ("run", "jobs", "artifacts", "downloads", "age", "identity", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    # Authenticated GitHub reads belong to a separate gate; reject credentials here.
    if any(os.getenv(k) for k in ("EMO_CI_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "RELEASE_REPO_TOKEN")):
        parser.error("Admission needs no API or release credentials")
    try:
        def metadata(path):
            with path.open("rb") as f:
                data = f.read((2 << 20) + 1)
            if len(data) > (2 << 20):
                raise ValueError("Oversized metadata")
            return json.loads(data)
        admit(metadata(args.run), metadata(args.jobs), metadata(args.artifacts),
              args.downloads, args.age, args.identity, args.output)
    except (OSError, ValueError, TypeError, RuntimeError, KeyError, subprocess.SubprocessError,
            tarfile.TarError, zipfile.BadZipFile):
        print("private_pilot_admission=failed")
        return 1
    print("private_pilot_admission=verified_no_release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
