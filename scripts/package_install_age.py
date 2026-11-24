"""Install a fixed official age x64 release, only after matching its SHA256."""
import hashlib
import io
from pathlib import Path
import platform
import sys
import tarfile
from urllib.request import urlopen
import zipfile

ASSETS = {
    "Linux": ("linux-amd64.tar.gz", "7df45a6cc87d4da11cc03a539a7470c15b1041ab2b396af088fe9990f7c79d50", "age"),
    "Windows": ("windows-amd64.zip", "46db0db71f146061f7c8fffa912cb806aef1bc8450e27a3abc1744f0591b89fb", "age.exe"),
}


def install(destination):
    system = platform.system()
    suffix, digest, name = ASSETS[system]
    if platform.machine().lower() not in ("x86_64", "amd64"):
        raise ValueError("unsupported architecture")
    url = "https://github.com/FiloSottile/age/releases/download/v1.2.1/age-v1.2.1-" + suffix
    with urlopen(url, timeout=50) as response:
        data = response.read(12 * 1024 * 1024 + 1)
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("age digest mismatch")
    if system == "Windows":
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            binary = bundle.read("age/" + name)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as bundle:
            with bundle.extractfile("age/" + name) as executable:
                binary = executable.read()
    destination.mkdir(parents=True, exist_ok=False)
    exe = destination / name
    with exe.open("xb") as handle:
        handle.write(binary)
    exe.chmod(0o700)


if __name__ == "__main__":
    try:
        install(Path(sys.argv[1]))
    except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile):
        print("age_install=failure")
        raise SystemExit(1) from None
    print("age_install=success")
