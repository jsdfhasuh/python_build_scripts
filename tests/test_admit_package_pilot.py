import copy
import hashlib
from pathlib import Path
import zipfile

import pytest

import admit_package_pilot as p


def metadata():
    repo = {"id": p.REPO, "full_name": p.PUBLIC}
    run = {"id": p.RUN, "run_attempt": p.ATTEMPT, "head_sha": p.HEAD, "head_branch": p.BRANCH,
           "event": "push", "status": "completed", "conclusion": "success", "path": p.WORKFLOW,
           "repository": repo, "head_repository": repo, "referenced_workflows": [
               {"path": f"{p.CALLABLE}@{p.PACKAGER}", "sha": p.PACKAGER}]}
    jobs = {"jobs": [{"name": f"package-pilot / Read-only public fixture / {t}", "run_id": p.RUN,
                      "run_attempt": p.ATTEMPT, "status": "completed", "conclusion": "success"} for t in p.TARGETS]}
    artifacts = {"artifacts": [{"id": i + 1, "size_in_bytes": 512, "expired": False,
                "name": f"encrypted-package-{t}-{p.RUN}-{p.ATTEMPT}", "digest": p.DIGESTS[t],
                "workflow_run": {"id": p.RUN, "repository_id": p.REPO, "head_sha": p.HEAD}}
                for i, t in enumerate(p.TARGETS)]}
    return run, jobs, artifacts


@pytest.mark.parametrize("mutation", ["run", "job", "artifact", "stale", "pin", "duplicate"])
def test_metadata_fails_closed_on_every_boundary(mutation):
    run, jobs, artifacts = copy.deepcopy(metadata())
    assert set(p.admit_metadata(run, jobs, artifacts)) == set(p.TARGETS)
    if mutation == "run":
        run["head_repository"]["id"] += 1
    elif mutation == "job":
        jobs["jobs"][0]["conclusion"] = "failure"
    elif mutation == "artifact":
        artifacts["artifacts"][0]["digest"] = "sha256:" + "f" * 64
    elif mutation == "stale":
        artifacts["artifacts"][0]["expired"] = True
    elif mutation == "pin":
        del run["referenced_workflows"]
    else:
        artifacts["artifacts"].append(artifacts["artifacts"][0])
    with pytest.raises(ValueError):
        p.admit_metadata(run, jobs, artifacts)


@pytest.mark.parametrize("mutation", ["size", "hash", "duplicate", "unexpected", "bad_header", None])
def test_outer_archive_is_exact_and_verified(tmp_path, mutation):
    outer = tmp_path / "wrapped.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("package.tar.age", "age-encryption.org/v1\nsample" if mutation != "bad_header" else "plaintext")
        if mutation == "unexpected":
            archive.writestr("build.log", "raw")
        if mutation == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr("package.tar.age", "spoof")
    digest = "sha256:" + hashlib.sha256(outer.read_bytes()).hexdigest()
    size = outer.stat().st_size
    output = tmp_path / "ciphertext"
    if mutation is None:
        p.unwrap(outer, digest, size, output)
        assert output.read_bytes().endswith(b"sample")
    else:
        with pytest.raises(ValueError):
            p.unwrap(outer, "sha256:" + "f"*64 if mutation == "hash" else digest,
                     size + 1 if mutation == "size" else size, output)
        assert not output.exists()


def test_end_to_end_age_and_release_verification_without_any_release_call(tmp_path, monkeypatch):
    import json
    import os
    import subprocess

    import build_config
    import package_transport as transport

    def write_json(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    tools = Path(os.environ["AGE_TEST_BIN"])
    identity = tmp_path / "synthetic-age-key"
    subprocess.run([tools/"age-keygen", "-o", identity], check=True, capture_output=True)
    recipient = subprocess.run([tools/"age-keygen", "-y", identity],
                               check=True, capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(p.master_release, "ROOT", Path(build_config.__file__).parent)
    monkeypatch.setattr(p.master_release, "publishAssets", lambda *_: pytest.fail("unexpected release call"))
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    run, jobs, artifacts = metadata()
    digests = {}
    for target, item in zip(p.TARGETS, artifacts["artifacts"]):
        source = tmp_path / target
        source.mkdir()
        names = {kind: f"{target}-{label}-{p.TAG}.{ext}" for kind, label, ext in
                 (("portable", "windows", "zip"), ("setup", "setup", "exe"))}
        assets = {}
        for kind, name in names.items():
            path = source / name
            path.write_bytes(name.encode())
            assets[kind] = {"name": name, "sha256": p.master_release.fileHash(path),
                            "url": f"https://github.com/jsdfhasuh/emo_master/releases/download/{p.TAG}/{name}"}
        write_json(source / "manifest.json", {"source_repo": "jsdfhasuh/emo_master",
            "source_commit": p.SOURCE, "version": p.TAG[1:], "assets": assets,
            "sha256": assets["portable"]["sha256"], "url": assets["portable"]["url"]})
        if target == "emo-master-runtime":
            identity_data = {"source_repo": "jsdfhasuh/emo_master", "source_commit": p.SOURCE,
                "packager_repo": "jsdfhasuh/python_build_scripts", "packager_commit": p.PACKAGER,
                "requested_source_ref": p.SOURCE, "requested_packager_ref": p.PACKAGER,
                "workflow_sha": p.HEAD, "workflow_ref": f"{p.PUBLIC}/{p.WORKFLOW}@refs/heads/{p.BRANCH}",
                "run_url": f"https://github.com/{p.PUBLIC}/actions/runs/{p.RUN}", "publish_requested": False}
            write_json(source / "runtime-build.json", identity_data)
            write_json(source / "archive-check/validation.json", dict(identity_data, status="PASS",
                       archiveAcceptance="PASS", nativeAcceptance="PASS", archiveSha256=assets["portable"]["sha256"]))
        cipher = tmp_path / f"{target}.age"
        transport.seal(source, cipher, tools/"age", recipient, target, p.TAG)
        wrapper = downloads / f"{item['id']}.zip"
        with zipfile.ZipFile(wrapper, "w") as zip_file:
            zip_file.write(cipher, "package.tar.age")
        digests[target] = item["digest"] = "sha256:" + p.master_release.fileHash(wrapper)
        item["size_in_bytes"] = wrapper.stat().st_size
    monkeypatch.setattr(p, "DIGESTS", digests)
    output = tmp_path / "private-test"
    p.admit(run, jobs, artifacts, downloads, tools/"age", identity, output)
    result = json.loads((output / "pilot-verification.json").read_text())
    assert result["mode"] == "pilot-only" and not result["publish"] and len(result["files"]) == 6


def test_control_exposes_existing_pat_only_as_explicit_gh_auth(monkeypatch):
    import collect_package_pilot as control

    for name, value in {"EMO_CI_TOKEN": "synthetic-existing-secret", "GH_TOKEN": "inherited",
                        "GITHUB_TOKEN": "inherited", "GH_HOST": "unexpected.example"}.items():
        monkeypatch.setenv(name, value)
    env = control.gh_env()
    assert env["GH_TOKEN"] == "synthetic-existing-secret"
    assert "EMO_CI_TOKEN" not in env and "GITHUB_TOKEN" not in env and "GH_HOST" not in env
