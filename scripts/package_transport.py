"""Streaming, allowlisted tar-to-age proof transport. Public output is ciphertext only."""
import argparse
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile

MAX_PACKAGE = (2 << 30) - 1
MAX_RECORD = 2 << 20
LOG_NAMES = ("dependencies.log", "runtime-source.log", "build.log",
             "runtime-archive-native.log", "designer-icons.log")
MAX_LOG = 256 << 10
TARGETS = ("emo-master", "emo-master-runtime")


def package_members(target, tag):
    if target not in TARGETS or not isinstance(tag, str) or re.fullmatch(r"v[0-9]+(?:\.[0-9]+){1,3}", tag) is None:
        raise ValueError("Unsupported package identity")
    out = {f"{target}-windows-{tag}.zip": MAX_PACKAGE,
           f"{target}-setup-{tag}.exe": MAX_PACKAGE, "manifest.json": MAX_RECORD}
    if target == "emo-master-runtime":
        out.update({"runtime-build.json": MAX_RECORD, "archive-check/validation.json": MAX_RECORD})
    return out


def regular(root, name, cap, *, allow_empty=False):
    path = root.joinpath(*name.split("/"))
    if path.resolve(strict=True) != path:
        raise ValueError("Linked or out-of-tree package path")
    name_before = path.lstat()
    if not stat.S_ISREG(name_before.st_mode):
        raise ValueError("Package member must be regular before open")
    file = path.open("rb")
    info = os.fstat(file.fileno())
    name_info = path.lstat()
    if not (stat.S_ISREG(info.st_mode) and os.path.samestat(info, name_info)
            and os.path.samestat(info, name_before) and info.st_nlink == 1 and (0 if allow_empty else 1) <= info.st_size <= cap
            and not getattr(name_info, "st_file_attributes", 0) & 0x400):
        file.close()
        raise ValueError("Invalid package file")
    return file, info.st_size


def seal_members(source, output, age, recipient, members):
    if re.fullmatch(r"age1[0-9a-z]{58}", recipient) is None:
        raise ValueError("Expected fixed age X25519 public key")
    source = source.resolve(strict=True)
    if output.exists() or output.is_symlink() or source in output.resolve().parents:
        raise ValueError("Use a new ciphertext destination")
    for name, cap in members.items():
        f, _ = regular(source, name, cap)
        f.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".incomplete")
    if temporary.exists() or temporary.is_symlink():
        raise ValueError("Ciphertext temporary exists")
    child = subprocess.Popen([str(age), "-r", recipient, "-o", str(temporary)], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with child.stdin as pipe, tarfile.open(fileobj=pipe, mode="w|") as archive:
            for name, cap in members.items():
                file, size = regular(source, name, cap)
                with file:
                    entry = tarfile.TarInfo(name)
                    entry.size = size
                    entry.mode = 0o600
                    archive.addfile(entry, file)
        if child.wait(timeout=120) != 0 or temporary.stat().st_size == 0:
            raise ValueError("Package encryption failed")
        temporary.replace(output)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        temporary.unlink(missing_ok=True)


def seal(source, output, age, recipient, target, tag):
    return seal_members(source, output, age, recipient, package_members(target, tag))


def seal_logs(source, staging, output, age, recipient, outcome):
    if outcome not in {"success", "failure", "cancelled", "skipped"}:
        raise ValueError("Invalid workflow outcome")
    source = source.resolve(strict=True)
    staging.mkdir(parents=True, exist_ok=False)
    members = {"outcome.txt": 32}
    (staging / "outcome.txt").write_text(outcome, encoding="ascii")
    for name in LOG_NAMES:
        try:
            stream, size = regular(source, name, MAX_PACKAGE, allow_empty=True)
        except FileNotFoundError:
            continue  # A previous phase may have failed before creating it.
        with stream:
            if size == 0:
                continue
            if size > MAX_LOG:
                marker = b"[leading bytes omitted]\n"
                stream.seek(size - MAX_LOG + len(marker))
                data = marker + stream.read(MAX_LOG - len(marker))
            else:
                data = stream.read(MAX_LOG)
        (staging / name).write_bytes(data)
        members[name] = MAX_LOG
    seal_members(staging, output, age, recipient, members)


def unpack(plaintext_tar, destination, target, tag):
    """Private receiver only. Stream; exact members; never extract with tar.extract."""
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination must be new")
    destination.mkdir(parents=True)
    members = package_members(target, tag)
    seen = set()
    with tarfile.open(fileobj=plaintext_tar, mode="r|") as archive:
        for member in archive:
            if (member.name not in members or member.name in seen or not member.isreg()
                    or member.pax_headers or not 0 < member.size <= members[member.name]):
                raise ValueError("Unexpected encrypted package member")
            seen.add(member.name)
            out = destination.joinpath(*member.name.split("/"))
            out.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, out.open("xb") as stream:
                remaining = member.size
                while remaining:
                    block = source.read(min(1 << 20, remaining))
                    if not block:
                        raise ValueError("Truncated package member")
                    stream.write(block)
                    remaining -= len(block)
    if seen != set(members):
        raise ValueError("Missing encrypted package member")


def recover(ciphertext, destination, age, identity, target, tag):
    """Private verification job only: final success requires age authentication."""
    child = subprocess.Popen([str(age), "-d", "-i", str(identity), str(ciphertext)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        with child.stdout as pipe:
            unpack(pipe, destination, target, tag)
            # Drain tar padding and force age to authenticate the final chunk.
            if len(pipe.read(10241)) > 10240 or pipe.read(1):
                raise ValueError("Trailing package data")
        if child.wait(timeout=120) != 0:
            raise ValueError("Ciphertext authentication failed")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--age", type=Path, required=True)
    parser.add_argument("--recipient", required=True)
    parser.add_argument("--target")
    parser.add_argument("--tag")
    parser.add_argument("--evidence-staging", type=Path)
    parser.add_argument("--outcome")
    a = parser.parse_args()
    try:
        if a.evidence_staging is None:
            seal(a.source, a.output, a.age, a.recipient, a.target, a.tag)
        else:
            seal_logs(a.source, a.evidence_staging, a.output, a.age, a.recipient, a.outcome)
    except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
        print("package_transport=failed")
        return 1
    print("package_transport=sealed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
