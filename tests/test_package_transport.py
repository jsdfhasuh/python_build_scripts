import io
import os
from pathlib import Path
import subprocess
import tarfile

import pytest

import package_transport as p


def test_age_round_trip_and_authentication_fail_closed(tmp_path):
    tools = Path(os.environ["AGE_TEST_BIN"])
    key = tmp_path / "test-identity"
    subprocess.run([tools / "age-keygen", "-o", key], check=True, capture_output=True)
    public = subprocess.run([tools / "age-keygen", "-y", key], check=True, capture_output=True, text=True).stdout.strip()
    source = tmp_path / "original"
    source.mkdir()
    for name in p.package_members("emo-master-runtime", "v0.6.6"):
        f = source / name
        f.parent.mkdir(exist_ok=True)
        f.write_text(name)
    (source / "unrelated.log").write_text("do not include")
    out = tmp_path / "public" / "runtime.tar.age"
    p.seal(source, out, tools / "age", public, "emo-master-runtime", "v0.6.6")
    dest = tmp_path / "private"
    p.recover(out, dest, tools / "age", key, "emo-master-runtime", "v0.6.6")
    members = {x.relative_to(dest).as_posix(): x.read_text() for x in dest.rglob("*") if x.is_file()}
    assert members == {name: name for name in p.package_members("emo-master-runtime", "v0.6.6")}
    damaged = tmp_path / "tampered.age"
    data = bytearray(out.read_bytes())
    data[-1] ^= 1
    damaged.write_bytes(data)
    with pytest.raises((ValueError, tarfile.TarError)):
        p.recover(damaged, tmp_path / "quarantine", tools / "age", key, "emo-master-runtime", "v0.6.6")


@pytest.mark.parametrize("name", ["../outside", "/absolute", "build.log", "manifest.json"])
def test_unexpected_members_are_rejected(tmp_path, name):
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode="w") as tar:
        item = tarfile.TarInfo(name)
        item.type = tarfile.SYMTYPE
        item.linkname = "../outside"
        tar.addfile(item)
    b.seek(0)
    with pytest.raises(ValueError):
        p.unpack(b, tmp_path / "dest", "emo-master", "v0.6.6")
    assert not (tmp_path / "outside").exists()


def test_logs_are_bounded_separate_and_retained_for_failure(tmp_path):
    tools = Path(os.environ["AGE_TEST_BIN"])
    key = tmp_path / "test-identity"
    subprocess.run([tools / "age-keygen", "-o", key], check=True, capture_output=True)
    public = subprocess.run([tools / "age-keygen", "-y", key], check=True, capture_output=True, text=True).stdout.strip()
    source = tmp_path / "logs"
    source.mkdir()
    (source / "build.log").write_bytes(b"DISCARDED" + b"a" * p.MAX_LOG + b"tail")
    (source / "runtime-source.log").write_bytes(b"")
    (source / "unrelated.log").write_bytes(b"never")
    out = tmp_path / "cipher" / "logs.tar.age"
    p.seal_logs(source, tmp_path / "stage", out, tools / "age", public, "failure")
    raw = subprocess.run([tools / "age", "-d", "-i", key, out], check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        assert set(tar.getnames()) == {"build.log", "outcome.txt"}
        assert tar.extractfile("outcome.txt").read() == b"failure"
        data = tar.extractfile("build.log").read()
        assert len(data) == p.MAX_LOG and data.startswith(b"[leading bytes omitted]\n") and data.endswith(b"tail")
        assert b"DISCARDED" not in data
