# VisionWorkshop 专用打包向导：协议 3

入口：`python scripts/release_wizard_emo_vision_train.py`。调用链为
`release_wizard_emo_vision_train.py → visionworkshop_wizard.py → portable_release.main()`，使用启动向导的同一个 Python。
基础配置为 `configs/emo-vision-train.json`；只有显式选择外观时才加载 `profiles/visionworkshop.json`。
应用源码的 `pyinstaller_config.json` 不参与此向导的配置合并。

## 布局与迁移

```text
VisionWorkshop/
  VisionWorkshop.exe
  app/
    VisionWorkshopApp.exe
    VisionWorkshopUpdater.exe
    _internal/
    release_identity.json
    package_files.json
```

启动器和更新器各自编译成独立 onefile，启动器不使用应用身份 runtime hook。
先编译启动器，将其摘要和大小绑定到发布身份，再编译应用和更新器并生成应用清单。
根目录只保留日常启动器；运行时 `.updates/` 不进入发布包。
普通更新只安装 app/ 的变化文件，固定启动器不随应用事务替换。

首次需要将新完整包解压到全新位置并通过启动器运行。外部用户数据和产品 ID 不变；
不搬移旧安装登记、失败会话或缓存。新协议拒绝旧协议产物重归档及跨协议增量。
旧名称启动器、旧更新 CLI 和专用向导的旧发布路线已移除。
共享打包工具为其他产品保留原有行为。

## 构建方式

向导保留仅构建、预览、构建并发布、显式构建记录重归档、重归档并发布和仅修改发布正文六种模式。
默认不上传。选择外观只影响图标、窗口资源等；协议 3 的程序入口名称和布局固定。
`--yes` 只跳过最后确认，不跳过协议、身份、源码或验收门槛。

```powershell
$env:SOURCE_ROOT = 'D:\training_platform'
python scripts/release_wizard_emo_vision_train.py
# 只预览直接构建命令
python build.py --config configs/emo-vision-train.json --dry-run
```

本次有效配置和记录分别在隔离构建目录的 `effective-config.json`、`build-record.json`。
应用输出为 `dist/branding/emo-vision-train/<build_id>/VisionWorkshop/`，默认归档输出为
`release-output/branding/emo-vision-train/<build_id>/<archive_id>/`。以本次记录为准，不选择“最新 dist”。
源码、资源、工具或配置变更必须干净重建；记录可重用性、全部输入和全部产物须再次通过校验。
不通过重归档给旧二进制换版本或协议身份。私有构建记录不能加入公开 ZIP。

ZIP 优先用 7-Zip；内存分配失败时只重试为单线程。无 7-Zip 时使用支持扩展路径的 Python ZIP64
流式归档。归档验证与增量负载验证不等于已经执行完整产品更新。

## 发布文档与上传

发布正文先生成或导入，再预览和冻结摘要。默认基线来自上次发布，亦可显式选择正确源码范围。
仅修改正文不改版本、ZIP 或发布资产。构建/预览不需要发布令牌；上传仍须明确选择发布模式。
已有 tag 不自动覆盖。更改发布仓库、资产名或 tag 不能绕过布局和验收门槛。

首次迁移的 Release 正文必须明确：解压到全新独立目录，经根目录启动器运行，不能直接应用旧协议增量。
完整包、身份、清单及增量资产都绑定同一构建和协议 3；启动器大小和摘要属于身份的一部分。

## 独立验收门槛

本地构建与归档始终可以进行；发布还要求选定构建的 work 目录中存在 `update-acceptance.json`。
报告必须绑定 `build-record.json` 中完整的 `update_protocol` 对象，不能引用其他构建的结果。
每项检查需 `status: passed` 和非空 `evidence` 列表，每份证据由相对 work 的路径与 SHA-256 绑定。
这些记录是受控本地验收证据，并不是数字签名。不得把测试夹具报告填写为完整产品或断电验收。

```json
{
  "schema_version": 1,
  "protocol": {"protocol_version": 3, "build_id": "实际构建编号", "identity_sha256": "实际摘要", "files_sha256": "实际摘要"},
  "checks": {
    "automated_tests": {"status": "not-run", "evidence": []},
    "frozen_product_update_and_recovery": {"status": "not-run", "evidence": []},
    "two_successive_updates": {"status": "not-run", "evidence": []},
    "broken_app_recovery_without_python": {"status": "not-run", "evidence": []},
    "long_paths_policy_disabled": {"status": "not-run", "evidence": []},
    "real_manifest_zero_unchanged_copy": {"status": "not-run", "evidence": []},
    "power_loss_recovery": {"status": "not-run", "evidence": []}
  }
}
```

正常流程是先构建、验收，再显式选择该构建记录重归档发布。缺少报告、检查未通过、摘要不匹配或
证据被改动时上传阻断。CI 构建产物上传也不代表客户端正式发布；无验收证据不能打开发布开关。
不得将进程中断测试标注为断电测试。

## 验证

外部仓库：`python -m unittest discover -s tests -v`。
应用仓库：`python scripts/verify_update_windows.py` 干净编译测试应用与真实更新器，执行连续更新及
主程序入口缺失时的独立恢复。`--reuse-build` 必须指向完全匹配当前运行时代码的明确构建。
测试夹具不能替代主产品冷启动、训练、GPU、现场长路径策略和断电验收。
