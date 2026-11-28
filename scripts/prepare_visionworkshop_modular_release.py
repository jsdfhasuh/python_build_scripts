"""Prepare a hash-verified protocol-4 Preview release from one completed candidate run."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile


def fail(message: str) -> None:
    raise ValueError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"Cannot read JSON {path}: {exc}")
    require(isinstance(value, dict), f"Expected a JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_dir(root: Path, prefix: str, run_id: int, attempt: int) -> Path:
    name = f"{prefix}-{run_id}-{attempt}"
    path = root / name
    require(path.is_dir() and not path.is_symlink(), f"Missing exact artifact directory: {name}")
    return path


def exact_file(root: Path, name: str) -> Path:
    matches = [path for path in root.rglob(name) if path.is_file() and not path.is_symlink()]
    require(len(matches) == 1, f"Expected exactly one {name}; found {len(matches)}")
    return matches[0]


def verify_file(path: Path, descriptor: dict, label: str) -> None:
    require(path.stat().st_size == descriptor.get("bytes"), f"{label} byte count mismatch")
    require(sha256_file(path) == descriptor.get("sha256"), f"{label} SHA-256 mismatch")


def copy_verified(source: Path, destination: Path, descriptor: dict, label: str) -> None:
    verify_file(source, descriptor, label)
    shutil.copy2(source, destination)
    verify_file(destination, descriptor, label + " copied")


def zip_tree(source: Path, destination: Path, prefix: str) -> None:
    require(source.is_dir(), f"Evidence directory is missing: {source}")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                fail(f"Evidence contains a symbolic link: {path}")
            if path.is_file():
                archive.write(path, (Path(prefix) / path.relative_to(source)).as_posix())


def prepare(args: argparse.Namespace) -> dict:
    request = read_json(args.request)
    required = {
        "candidate_run_id", "candidate_run_attempt", "candidate_builder_sha",
        "app_sha", "core_version", "max_core_version", "build_id", "tag_name",
        "release_title", "expected_case_count", "release_repo",
    }
    require(set(request) == required, "Release request fields do not match the reviewed schema")
    run_id, attempt = request["candidate_run_id"], request["candidate_run_attempt"]
    require(type(run_id) is int and run_id > 0, "Invalid candidate run ID")
    require(type(attempt) is int and attempt > 0, "Invalid candidate run attempt")
    require(re.fullmatch(r"[0-9a-f]{40}", request["candidate_builder_sha"]) is not None,
            "Invalid candidate builder SHA")
    require(re.fullmatch(r"[0-9a-f]{40}", request["app_sha"]) is not None, "Invalid application SHA")
    version = request["core_version"]
    semver = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    require(re.fullmatch(semver, version) is not None, "Invalid stable Core version")
    max_version = request["max_core_version"]
    require(re.fullmatch(semver, max_version) is not None, "Invalid maximum Core version")
    require(tuple(map(int, version.split("."))) < tuple(map(int, max_version.split("."))),
            "Core compatibility interval must be nonempty")
    require(request["tag_name"] == f"v{version}-preview.1", "Preview tag does not match Core version")
    require(isinstance(request["release_title"], str) and request["release_title"].strip(),
            "Release title is required")
    require(request["release_repo"] == "jsdfhasuh/emo-vision-train-release",
            "Unexpected public release repository")
    require(type(request["expected_case_count"]) is int and request["expected_case_count"] >= 1,
            "Invalid expected product case count")
    require(not args.output.exists(), "Release output directory already exists; use a new directory")
    args.output.mkdir(parents=True)

    build_artifact = artifact_dir(args.artifacts_root, "visionworkshop-modular-evidence", run_id, attempt)
    product_artifact = artifact_dir(args.artifacts_root, "visionworkshop-modular-product-evidence", run_id, attempt)
    index_artifact = artifact_dir(args.artifacts_root, "visionworkshop-module-index", run_id, attempt)
    core_artifact = artifact_dir(args.artifacts_root, "visionworkshop-core-candidate", run_id, attempt)

    build = read_json(exact_file(build_artifact, "modular-build-summary.json"))
    product = read_json(exact_file(product_artifact, "modular-product-summary.json"))
    index_path = exact_file(index_artifact, "module-index.json")
    index = read_json(index_path)

    expected_identity = {
        "app_sha": request["app_sha"],
        "packager_sha": request["candidate_builder_sha"],
        "build_id": request["build_id"],
    }
    require(build.get("status") == "BUILT" and build.get("published") is False,
            "Build report is not a completed unpublished candidate")
    require(build.get("release_gate") == "NOT_QUALIFIED",
            "Candidate release gate changed; review before publishing a Preview")
    require(build.get("gpu_hardware") == "NOT_RUN", "Unexpected GPU qualification state")
    require(build.get("source", {}).get("commit") == request["app_sha"], "Build application SHA mismatch")
    require(build.get("packager", {}).get("commit") == request["candidate_builder_sha"],
            "Build packager SHA mismatch")
    require(build.get("core", {}).get("version") == version, "Built Core version mismatch")
    require(build.get("core", {}).get("build") == expected_identity, "Built Core build identity mismatch")
    require(build.get("module_reuse", {}).get("enabled") is False,
            "Initial Preview must contain freshly built modules")

    require(index.get("type") == "visionworkshop-module-index" and index.get("schema_version") == 1,
            "Unsupported module index")
    require(index.get("protocol_version") == 4 and index.get("module_api") == 1,
            "Preview requires protocol 4 / module API 1")
    require(index.get("python") == {"version": "3.12.10", "abi": "cp312", "platform": "win_amd64"},
            "Preview Python/ABI/platform identity mismatch")
    require(index.get("asset_count") == 12 and len(index.get("modules", [])) == 11,
            "Module index must contain Core plus exactly 11 modules")
    require(index.get("build") == expected_identity, "Module index build identity mismatch")
    require(index.get("core", {}).get("version") == version, "Module index Core version mismatch")
    require(index.get("core", {}).get("manifest_sha256") == build.get("core_sha256"),
            "Module index Core manifest identity mismatch")
    require(index.get("dependency_lock_sha256") == build.get("core", {}).get("dependency_lock_sha256"),
            "Module index dependency-lock identity mismatch")
    require(index.get("qualification", {}).get("release") == "NOT_QUALIFIED",
            "Module index qualification state changed")
    verify_file(index_path, {"bytes": build.get("module_index", {}).get("bytes"),
                             "sha256": build.get("module_index", {}).get("sha256")}, "Module index")
    require(product.get("status") == "LIMITED" and product.get("published") is False,
            "Product report is not the expected limited Preview result")
    require(product.get("release_gate") == "NOT_QUALIFIED" and product.get("gpu_hardware") == "NOT_RUN",
            "Product qualification scope changed")
    require(product.get("cpu_product_fixtures") == "PASS", "CPU product fixture gate did not pass")
    require(product.get("module_reuse", {}).get("enabled") is False,
            "Preview product report unexpectedly reused module archives")
    require(product.get("build") == expected_identity, "Product report build identity mismatch")
    require(product.get("core_sha256") == build.get("core_sha256"), "Product Core manifest identity mismatch")
    require(product.get("module_index", {}).get("status") == "PASS", "Product module-index verification failed")
    require(product.get("module_index", {}).get("sha256") == sha256_file(index_path),
            "Product report module-index SHA mismatch")
    cases = product.get("cases")
    require(isinstance(cases, list) and len(cases) == request["expected_case_count"],
            "Product case count differs from the reviewed expected count")
    require(all(case.get("status") == "PASS" for case in cases), "At least one product case did not pass")
    case_names = [case.get("name") for case in cases]
    require(len(case_names) == len(set(case_names)), "Duplicate product case names")
    integrity = product.get("core_integrity_checks")
    require(isinstance(integrity, list) and len(integrity) == 12, "Expected 12 Core integrity checkpoints")
    require(all(check.get("status") == "PASS" and not check.get("missing")
                and not check.get("extra") and not check.get("changed") for check in integrity),
            "Core integrity checkpoint did not pass")

    output = args.output
    core_descriptor = index["core"]["archive"]
    build_core_descriptor = build.get("core_archive", {})
    require(core_descriptor.get("bytes") == build_core_descriptor.get("bytes")
            and core_descriptor.get("sha256") == build_core_descriptor.get("sha256"),
            "Core archive descriptor differs between index and build report")
    core_name = core_descriptor.get("name")
    require(isinstance(core_name, str) and core_name.endswith(f"-{version}.zip"),
            "Core archive name does not match release version")
    copy_verified(exact_file(core_artifact, core_name), output / core_name, core_descriptor, "Core archive")

    build_modules = {item.get("module_id"): item for item in build.get("module_archives", [])}
    index_modules = index["modules"]
    module_ids = [item.get("module_id") for item in index_modules]
    require(len(module_ids) == 11 and len(set(module_ids)) == 11, "Invalid unique module set")
    require(set(module_ids) == set(build_modules), "Build and index module catalogs differ")

    for module in sorted(index_modules, key=lambda item: item["module_id"]):
        module_id = module["module_id"]
        descriptor = module.get("archive", {})
        build_record = build_modules[module_id]
        require(module.get("version") == version, f"{module_id} version mismatch")
        core_range = module.get("core_versions", {})
        require(core_range.get("min") == version
                and core_range.get("max_exclusive") == request["max_core_version"],
                f"{module_id} Core compatibility range mismatch")
        require(module.get("build") == expected_identity, f"{module_id} build identity mismatch")
        require(descriptor.get("bytes") == build_record.get("bytes")
                and descriptor.get("sha256") == build_record.get("sha256")
                and module.get("manifest_sha256") == build_record.get("manifest_sha256"),
                f"{module_id} index/build archive identity mismatch")
        name = descriptor.get("name")
        require(isinstance(name, str) and name.endswith(f"-{version}.zip"),
                f"{module_id} archive name does not match release version")
        module_artifact = artifact_dir(args.artifacts_root, f"visionworkshop-module-{module_id}", run_id, attempt)
        copy_verified(exact_file(module_artifact, name), output / name, descriptor, f"{module_id} archive")

    shutil.copy2(index_path, output / "module-index.json")
    verify_file(output / "module-index.json",
                {"bytes": index_path.stat().st_size, "sha256": sha256_file(index_path)}, "Copied module index")
    require(args.install_guide.is_file(), "Application offline installation guide is missing")
    shutil.copy2(args.install_guide, output / "INSTALL.md")
    shutil.copy2(exact_file(build_artifact, "modular-build-summary.json"), output / "modular-build-summary.json")
    shutil.copy2(exact_file(product_artifact, "modular-product-summary.json"), output / "modular-product-summary.json")

    zip_tree(build_artifact, output / "build-evidence.zip", "build-evidence")
    zip_tree(product_artifact, output / "product-evidence.zip", "product-evidence")

    identity = {
        "schema_version": 1,
        "product": "VisionWorkshop",
        "release_tag": request["tag_name"],
        "release_channel": "preview",
        "core_version": version,
        "max_core_version_exclusive": request["max_core_version"],
        "build_id": request["build_id"],
        "candidate_run_id": run_id,
        "candidate_run_attempt": attempt,
        "application_commit": request["app_sha"],
        "builder_commit": request["candidate_builder_sha"],
        "product_cases": len(cases),
        "product_cases_passed": len(cases),
        "product_status": product["status"],
        "gpu_hardware": product["gpu_hardware"],
        "release_qualification": "NOT_QUALIFIED",
        "limitations": product.get("limitations", []),
    }
    (output / "visionworkshop-modular-release-identity.json").write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    notes = f"""# VisionWorkshop {version} Preview 1

这是协议 4 的模块化预览版，供用户进行独立安装和现场验收；**不是生产资格认证或正式稳定版**。

## 本次验收

- Windows 实际产品 EXE：{len(cases)}/{len(cases)} 项通过。
- Core 完整性：12 个检查点全部通过。
- Core：{core_name}。
- 独立模块：11 个，完整模块清单见 module-index.json。
- 应用提交：{request["app_sha"]}。
- 打包提交：{request["candidate_builder_sha"]}。
- 构建运行：{run_id}，attempt {attempt}。
- CPU 产品夹具：PASS。
- GPU 硬件资格：NOT_RUN。

## 已知限制

- NVIDIA T1000 实际 GPU 模型推理尚未执行。
- 物理断电恢复尚未执行；进程中断测试不替代物理断电。
- AnomalyDetect 外部软件兼容性尚未验证。
- 现有业务模型和生产数据资格尚未完成。
- DINO 成功预测会话及完整 Worker 导入审计不在本轮通过范围内。

## 初次安装

1. 下载 Core ZIP、module-index.json 和需要的模块 ZIP。完整功能验收请下载全部 11 个模块。
2. 将 Core ZIP 解压到一个全新的独立目录；不要覆盖协议 3 的旧安装目录。
3. 按 module-index.json 与 SHA256SUMS.txt 校验文件。
4. 启动 VisionWorkshop.exe，进入“系统 → 离线模块… → 从本地导入模块包”，选择需要的模块 ZIP；不要把 Core ZIP 或 module-index.json 选入模块导入窗口。
5. 等待模块安装事务完成，关闭所有 VisionWorkshop 窗口和工作进程，再重新启动软件。

完整步骤、PowerShell 校验命令和回退方法见 INSTALL.md。
"""
    (output / "RELEASE_NOTES.md").write_text(notes, encoding="utf-8")

    asset_records = []
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            size = path.stat().st_size
            require(size < 2 * 1024**3, f"GitHub Release asset exceeds 2 GiB: {path.name}")
            asset_records.append({"name": path.name, "bytes": size, "sha256": sha256_file(path)})
    sums = "".join(f"{record['sha256']}  {record['name']}\n" for record in asset_records)
    (output / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
    total_bytes = sum(path.stat().st_size for path in output.iterdir() if path.is_file())
    return {
        "status": "READY",
        "tag_name": request["tag_name"],
        "asset_count": len([path for path in output.iterdir() if path.is_file()]),
        "total_bytes": total_bytes,
        "product_cases": len(cases),
        "core_sha256": core_descriptor["sha256"],
        "module_count": len(index_modules),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--install-guide", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
