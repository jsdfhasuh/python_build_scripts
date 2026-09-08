# PyInstaller Build Helper

本仓库维护 Python 项目的 Windows 打包脚本、目标配置和 GitHub Actions，不包含被打包
应用本身的源码。原有 `emo-vision-train`、`emo-master` 目标仍保留。

## VisionWorkshop：自定义名称、图标和便携 ZIP

VisionWorkshop 基于 `emo-vision-train` 目标，继续使用“下载 ZIP → 完整解压 → 运行 EXE”。
不增加安装器，也不修改目标应用的窗口标题、窗口图标或运行时更新地址。

新入口支持显式配置档、自定义 EXE 名与 ICO、隔离构建、ZIP 内容验证、构建记录复用和
发布前检查。**默认只构建；改名且启用现有 updater 的产物不允许发布到自动更新通道。**
正式产品 ICO 需要自己提供，测试 ICO 不应作为品牌资源。

在准备好目标依赖的 Windows Python 环境中，从本仓库根目录执行：

```powershell
# 只预览，不编译、不上传；替换为实际源码、图标和版本号。
python .\scripts\publish_visionworkshop.py `
  --source-root 'D:\Projects\emo-vision-train' `
  --release-tag v1.2.3 `
  --branding-profile profiles/visionworkshop.json `
  --icon-path 'D:\Icons\visionworkshop.ico' `
  --dry-run
```

确认后将 `--dry-run` 换为 `--build-only`，构建程序目录及 ZIP。SOURCE_ROOT 必须是实际 Git
仓库根目录；不要求 gh 登录。需要交互输入时运行：

```powershell
python .\scripts\release_wizard_emo_vision_train.py
```

新训练平台向导默认仅构建，不保存临时外观。需要原向导时可加 `--legacy`；原向导不支持
新外观构建。`emo-master` 的入口 `scripts/release_wizard_emo_master.py` 保持不变。

详细操作、PowerShell 参数、构建记录复用和限制见
[VisionWorkshop 操作说明](docs/visionworkshop-branding.md)。
实施状态见 [计划实施记录](docs/plans/2026-09-08-visionworkshop-implementation-status.md)，
测试与已修复问题见 [代码审查记录](docs/evidence/visionworkshop-branding-review.md)。

## 默认构建与原发布流程

不选择外观配置档时，原始目标 JSON 不变，默认构建规则仍然适用：

```powershell
$env:SOURCE_ROOT = 'D:\Projects\emo-vision-train'
python .\build.py --config .\configs\emo-vision-train.json --dry-run
# 确认后用 --clean 替换 --dry-run，实际编译默认名称的程序目录。
```

`build.py` 负责程序目录，不负责 ZIP。新 Python 发布入口负责 VisionWorkshop 便携 ZIP。
PowerShell `scripts/publish-local-release.ps1` 根据参数选择新入口或原发布逻辑，
原发布逻辑原样保存在同目录 `publish-local-release-legacy.ps1`。
普通无外观参数的旧发布调用可能上传 Release，不应当作只构建命令。

`emo-master` 的安装包能力仍属于它自己的原目标，不会为 VisionWorkshop 启用。
通用配置字段和历史发布用法保留在 [原版 README](README-legacy.md) 与
[原发布操作手册](docs/release-runbook.md)；两者描述旧入口，新外观操作以本页和专用说明为准。

## GitHub Actions

| 工作流 | 用途 |
|---|---|
| `VisionWorkshop portable ZIP` | 新的 VisionWorkshop 手动/可复用构建入口，默认不发布。 |
| `VisionWorkshop portable tests` | Linux/Windows 单元测试和 Windows 小项目真实打包验收。 |
| `Release Windows Build` | 原有工作流，保留旧目标和安装包行为，不接收新外观参数。 |

新工作流的 `source_ref` 必须明确指定。跨仓复用时必须传 `packager_ref`，不能把源码仓的
SHA 当作打包仓版本。ICO 必须在 runner 可读取的位置；Actions artifact 只上传 ZIP 和脱敏
摘要，不上传私有构建记录。功能分支中的手动入口是否已在界面可见，以 GitHub 实际状态为准。

## 测试

```powershell
# 测试环境；不修改目标项目 requirements。
python -m pip install Pillow PyYAML
python -m unittest discover -s tests -v
```

Windows 小项目实包验收另需 PyInstaller 和 pefile，运行
`python scripts/verify_windows_portable.py`。测试工作流在独立环境准备这些工具。
小项目通过不代表真实 VisionWorkshop 的 Qt/GPU/硬件或跨名称更新已经通过；正式产品验收
单独记录，不以 dry-run、模拟编译或代码提交代替。
