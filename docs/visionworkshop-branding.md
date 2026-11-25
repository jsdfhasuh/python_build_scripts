# VisionWorkshop 专用打包向导：协议 3

入口：`python scripts/release_wizard_emo_vision_train.py`。调用链为
`release_wizard_emo_vision_train.py → visionworkshop_wizard.py → portable_release.main()`，使用启动向导的同一个 Python。
基础配置为 `configs/emo-vision-train.json`；只有显式选择外观时才加载 `profiles/visionworkshop.json`。
应用源码的 `pyinstaller_config.json` 不参与此向导的配置合并。

当前 CP312 实测（2026-11-25）：打包器 `a63f320` 的完整构建已通过 DINO worker
启动与环境 inspect，以及真实冻结 CNN 人工 CKPT 导出、CPU 数值比较和新进程重载。
完整 ZIP 为 2,715,516,448 字节，超出既有单资产上限 568,032,801 字节，因此构建仍为
`blocked-size`，没有发布 Release。DINO 模型推理、业务模型、训练、GPU、完整交互 GUI
和断电更新等未验收；完整身份与限定范围见
[CP312 生产构建验证](evidence/visionworkshop-cp312-production-validation.md)。

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
`--yes` 只跳过最后确认，不跳过协议、身份、源码或文件完整性校验。

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

### Vision Train size policy

The target excludes the local Notebook/Jupyter server, browser frontends, notebook widgets
and developer test runners. It retains `jupytext`/`nbformat` conversion, IPython, training
dependencies, GPU DLL collection, pinned offline model assets and dependency metadata.
The `rfc3987_syntax` grammar data is collected for frozen `nbformat`/Kaggle conversion.
The target-only analysis hook delegates to the upstream Torch hook and collects its
submodules as inspectable `.py` files without duplicate PYZ copies. The small Torch package
initializer remains in PYZ, preserving the existing frozen-runtime admission gate.
The Windows DINO worker runtime hook explicitly preloads the bundled runtime-root
`msvcp140.dll` before Qt initialization. This narrow load-order fix keeps the DINO branch
free of Torch Python imports and the four existing Torch native preloads; other entrypoints
retain their existing behavior. Do not remove CUDA DLLs or model files manually from a build.

`zip_lzma_dictionary_mib` selects 64, 128 or 256 MiB; the default for other targets remains
64 MiB. Vision Train selects 256 MiB with Unicode ZIP/LZMA and the existing single-thread
retry after a memory-allocation failure. Compression and extraction need more memory.
The release summary records the dictionary used for native LZMA archives. The individual
asset limit remains 2,147,483,647 bytes. Rebuild cleanly after changing this policy, then
verify every ZIP member against the build record; directory size is not ZIP-size evidence.

## 发布文档与上传

发布正文先生成或导入，再预览和冻结摘要。默认基线来自上次发布，亦可显式选择正确源码范围。
仅修改正文不改版本、ZIP 或发布资产。构建/预览不需要发布令牌；上传仍须明确选择发布模式。
已有 tag 不自动覆盖。更改发布仓库、资产名或 tag 不能绕过布局和完整性校验。

首次迁移的 Release 正文必须明确：解压到全新独立目录，经根目录启动器运行，不能直接应用旧协议增量。
完整包、身份、清单及增量资产都绑定同一构建和协议 3；启动器大小和摘要属于身份的一部分。

## 独立验收记录

### GitHub Actions 打包

协议 3 允许先构建并交付完整包，不要求提前提供产品更新或断电验收记录。
在 **Release Windows Build** 中选择 `Publish assets=auto` 或 `false` 仅构建 Vision Train，
选择 `true` 则构建并发布；**VisionWorkshop portable ZIP** 也支持明确开启发布选项。
发布仍需要 `RELEASE_REPO_TOKEN`，并通过构建身份、布局、ZIP、协议资产及上传摘要校验。
成功后可从运行页面的 Artifacts 下载
`visionworkshop-portable-<run_id>-<attempt>`，其中包含完整 ZIP、协议元数据和构建摘要。
这些文件可用于测试，但不表示已经通过产品更新或断电恢复验收。

如果旧运行显示 `Protocol-3 publication is blocked ... update-acceptance.json`，它使用的是
旧版强制验收策略。需要选择包含本次调整的打包器版本重新 Run workflow；旧任务 Re-run
可能继续使用旧提交。Actions 的公开 Artifact 不包含私有构建记录，不能单独作为
`--skip-build --build-record-path <明确的构建记录>` 重归档命令的输入。

### 验收报告

选定构建 work 目录中的 `update-acceptance.json` 为可选报告；缺失时记为 `not-run` 并允许发布。
提供报告时必须绑定 `build-record.json` 中完整的 `update_protocol` 对象，不能引用其他构建的结果。
每项检查可记为 `passed`、`failed`、`not-run` 或 `skipped`；缺失检查按 `not-run` 处理。
只有 `passed` 必须提供非空 `evidence`，所有已提供证据均由相对 work 的路径与 SHA-256 校验。
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

可以直接构建并发布，也可先构建测试，再显式选择仍通过输入和产物校验的构建记录重归档发布。
`build-summary.json` 的 `update_acceptance` 保存验收状态与各项结果；未完成或失败时提示，
不阻断发布。不合法报告、构建身份不匹配、虚报通过却没有证据或证据被改动仍会阻断。
发布到 Release 后仍沿用现有客户端更新发现机制；本次没有新增独立验收渠道或禁用运行时更新。
发布成功不代表产品验收通过，不得将进程中断测试标注为断电测试。

## 验证

### PatchCore 与图片精简离线资源

`configs/emo-vision-train.json` 的 `prepare_source_assets` 指定源码仓库中的
`scripts/prepare_desktop_weights.py`。实际构建在输入快照和编译之前，用向导当前的
Python 执行该脚本；下载或校验失败会立即中止构建。源码仓库负责固定权重版本、校验
SHA-256 并写入 `static/models`，现有 `static:static` 映射将其带入安装包。
脚本准备 PatchCore backbone 和图片精简 DINOv2 Small，缺失时下载固定版本，已有坏文件
会中止构建。DINO 资源不进入普通 Git 历史，干净源码 checkout 不能依赖开发者个人缓存。
配置显式包含 timm／safetensors 导入，以及 torch、torchvision、timm、safetensors、numpy、
Pillow 的包元数据；完整运行时包检查要求 DINO 文件和这些元数据随包存在。
请使用包含此脚本的应用源码版本。预览、notes-only、显式记录重归档不运行准备脚本。
重归档仍按原构建记录校验输入和产物，不补写旧包中的权重。

当前 DINO ONNX worker 与桌面应用共用 CPython 3.12 主运行时，由同一主 EXE 启动独立
worker 进程；安装包不再包含第二套 `dino_runtime` Python 环境。worker 允许主环境安装
Torch，但自身不得导入训练模块。冻结检查要求 `python312.dll`、ONNX Runtime 原生绑定、
worker 模块及依赖元数据齐全，并拒绝误带旧的 `dino_runtime` 目录。

Windows 冻结入口为 `--dino-onnx-worker` 时，自定义 runtime hook 在 Qt 相关初始化前，
通过绝对路径和 `winmode=0x1100` 预载冻结运行时根目录（本布局为 `app/_internal`）
已有的 `msvcp140.dll`，防止 Qt 目录中的旧同名运行库先占据加载结果。该分支仍不导入
Torch Python，也不执行原有四项 Torch native 预载；缺失或加载错误沿用既有 debug 日志
规则，不自动改用 Qt/System32 副本，不替换 DLL、依赖版本或安装身份记录。
复用原包的 A/B 已证实加载顺序影响 ORT 初始化。正式 hook 修复后，`a63f320` 新包的
冻结 DINO inspect 退出码为 0，debug 日志记录根目录 MSVCP 预载成功，
`training_modules_imported` 为空。该结果覆盖 worker 启动与 CPU 环境检查；DINO 模型
推理仍为 `NOT_RUN`，不能把 inspect 通过当作模型推理验收。

P4 DINO 核心的 Transformers、Hub、tokenizers 版本由 CI runtime profile 统一约束，
其模型模块和版本元数据显式进入冻结包。编译前会构造不下载权重的 encoder，验证 CPU
特征形状；这不改变应用已有的 P4 开发入口边界，也不代表完成真实模型或 GPU 验收。

非发布构建的 ZIP 超过现有单资产上限时，构建仍失败，不生成可交付的
`build-summary.json`，也不导出或暂存发布资产。只有 ZIP 完整内容、构建记录和归档
SHA-256 复查均通过时，才在输出目录的 `diagnostics/` 中保留超限 ZIP、
`oversize-archive.json` 和 `archive-members.json`。这些文件用于诊断和独立冻结验收；
`publishable: false` 与 `status: blocked-size` 不得改写为发布通过。

实际冻结包可分别运行 `scripts/verify_vision_train_frozen.py` 和
`scripts/verify_vision_train_patchcore_frozen.py`，两者均要求 `--zip`、`--source-root`
及全新的 `--output` 目录，并将 ZIP 内源码身份与 checkout 核对。前者观察启动器、DINO
worker 和 ONNX CPU schema；后者通过独立进程生成明确标注的人工 CKPT，使用真实冻结
EXE 导出完整 ONNX、比较分数/异常图/阈值判断，并在新冻结进程中重载最终图文件。
后者的 `--fixture-python` 可指定隔离的 CP312 夹具解释器；实际导出与 ORT 推理均由
冻结 EXE 执行。人工 memory bank 和图片验证软件通路，不代表训练、业务模型或 GPU
验收。诊断报告不改写原构建摘要，也不免除原有发布大小限制。

最终完整构建 [45544329988](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45544329988)
直接绑定打包器 `a63f320f86ca6dbfaf48d57afbd9853b8333ddc2` 和应用
`bb3772003f0b8cbd872d9342a48aa4a82d5bb861`，build ID 为
`20261125T041832Z-524aee200c44`；后续文档提交不是该产品包的构建提交。
两套冻结脚本均为 `PASS`，包括本次 DINO inspect 和 CNN 人工 CKPT 数值与最终图重载。
launcher 仅观察到 `CREATING_WINDOW` 并继续存活 5 秒；GUI 就绪与正常退出均为
`NOT_OBSERVED`，`close_messages: 0`，随后强制清理。独立 CPU schema smoke 的模型
数值资格仍为 `PENDING`，不得与已有逐样本比较的 CNN fixture 混为一项。

新完整 ZIP 仍不可发布；原 `673273a` 的 DINO 失败与 MSVCP A/B 诊断保留为历史证据。
构建身份、证据下载链接、每次独立的逐样本误差与图文件摘要、真实压缩字节比较，以及
未覆盖的产品验收范围统一记录在
[CP312 生产构建验证](evidence/visionworkshop-cp312-production-validation.md)。
本次未实施模型/CUDA 拆包、外置安装或更新协议变化；业务模型、DINO 模型推理、训练、
GPU、完整交互 GUI、产品 UI 模型导入和断电更新等未执行项保持 `NOT_RUN`。

外部仓库：`python -m unittest discover -s tests -v`。
应用仓库：`python scripts/verify_update_windows.py` 干净编译测试应用与真实更新器，执行连续更新及
主程序入口缺失时的独立恢复。`--reuse-build` 必须指向完全匹配当前运行时代码的明确构建。
测试夹具不能替代主产品冷启动、训练、GPU、现场长路径策略和断电验收。
