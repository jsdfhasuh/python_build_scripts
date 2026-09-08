# PyInstaller Build Helper

## 项目简介
这是一个专用于构建 PyInstaller 包的主打包仓库，核心脚本为 `build.py`，
通过读取 `configs/*.json` 生成并执行 PyInstaller 命令。

仓库只维护构建逻辑、打包配置和 GitHub Actions workflow，不包含被打包应用本身的源码。
v1 默认目标为 `emo-vision-train`，源码仓库为 `jsdfhasuh/emo-vision-train`，
发布仓库为 `jsdfhasuh/emo-vision-train-release`。仓库也提供 `emo-master` 目标，
用于生成 Windows x64 便携版和当前用户 Inno Setup 安装包。

## 使用说明

### 运行构建
```bash
python build.py
```

本地构建外部源码时，需要先设置 `SOURCE_ROOT`：

```powershell
$env:SOURCE_ROOT = "D:\training_platform"
$env:RELEASE_TAG = "v0.0.0-local"
python build.py --config configs\emo-vision-train.json --dry-run
```

### 仅打印命令（不执行）
```bash
python build.py --dry-run
```

### 清理构建缓存
```bash
python build.py --clean
```

### 指定 spec 输出目录
```bash
python build.py --specpath <dir>
```

### GitHub Actions 发布
在 GitHub Actions 中手动运行 `Release Windows Build` workflow：
- `target`: 默认 `emo-vision-train`
- `source_ref`: 源码仓分支、tag 或 commit，默认 `codex/yolo-pose-custom-ai-labeling`
- `previous_source_ref`: 可选，Release Notes 的源码对比起点，例如 `v1.0`
- `release_tag`: Release tag，例如 `v1.2.3`
- `release_repo`: 发布仓，格式 `owner/repo`；留空时使用目标配置里的 `release_repo`，再留空则使用当前 workflow 仓库
- `release_body_path`: 可选，打包仓里的 Markdown 文件路径；填写后完全覆盖自动生成的 Release Notes
- `publish_release`: 是否由中央 workflow 直接发布；可复用 workflow 默认只上传 Actions artifact

私有源码仓 checkout 需要在当前仓库配置 `SOURCE_REPO_TOKEN` secret。
如果 `release_repo` 指向另一个仓库，需要配置 `RELEASE_REPO_TOKEN` secret，
并确保它有目标发布仓的 `contents: write` 权限。
workflow 会 checkout 完整源码历史和 tags，用同一支本地发布脚本生成 Release Notes、
manifest、zip asset 并发布；只做打包，不做 GPU runtime 验证。

workflow 同时支持 `workflow_call`。应用仓可以先执行自己的测试，再调用中央 workflow
并设置 `publish_release: false`，最后使用应用仓自己的 `GITHUB_TOKEN` 发布下载下来的产物。

### 本地打包并上传 Release
如果 GitHub Actions 临时卡在依赖下载或构建环境，可以在本机打包后上传到指定发布仓 Release：

完整发布步骤见 [本地发布操作手册](docs/release-runbook.md)。

推荐日常使用项目专用的交互式发布向导：

```powershell
python scripts\release_wizard_emo_vision_train.py
python scripts\release_wizard_emo_master.py
```

两个入口共用 `release_wizard_common.py`，但固定选择各自 target，并分别保存本地默认值。
`emo-master` 向导会读取源码中的 `__version__`，只接受与它一致的 Release tag。

```powershell
.\scripts\publish-local-release.ps1 `
  -Target emo-vision-train `
  -ReleaseTag v1.2.3 `
  -SourceRoot D:\training_platform `
  -PreviousSourceRef v1.0 `
  -Notes "1.2.3"
```

脚本会上传两个 Release assets：
- `emo-vision-train-windows-v1.2.3.zip`
- `manifest.json`

`emo-master` 启用了 installer，会生成三个 assets，并在构建期间验证便携版自检、
静默安装、自检、卸载和用户数据保留：

```powershell
$env:ISCC_PATH = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
.\scripts\publish-local-release.ps1 `
  -Target emo-master `
  -ReleaseTag v0.6.0 `
  -SourceRoot C:\path\to\emo_master `
  -BuildOnly `
  -OutputDirectory .\artifacts\emo-master-v0.6.0
```

输出固定为 `emo-master-windows-${RELEASE_TAG}.zip`、
`emo-master-setup-${RELEASE_TAG}.exe` 和 `manifest.json`。源码版本文件存在时，
脚本会校验 tag 去掉 `v` 后与应用 `__version__` 一致。

本地脚本会优先使用 `7z` 生成 ZIP/LZMA 压缩包，避免 GPU 依赖包超过
GitHub Release 单个 asset 2GB 限制；如果没有 `7z`，会回退到 PowerShell
`Compress-Archive`，并在超过限制时提前失败。

Release 页面正文会从源码仓 git history 自动生成英文 Release Notes。生成逻辑是固定规则，
不调用 AI/API；`-Notes` 仍然只写入 updater manifest 的短说明字段。

Release Notes 的 changelog range 按以下顺序决定：
1. `-PreviousSourceRef..HEAD`
2. 上一个 Release manifest 里的 `source_commit..HEAD`
3. 源码仓最新 tag，例如 `v1.0..HEAD`
4. 找不到起点时回退到最近 30 个 commits

可以用 Markdown 文件完全覆盖 Release 页面正文：

```powershell
.\scripts\publish-local-release.ps1 `
  -Target emo-vision-train `
  -ReleaseTag v1.2.3 `
  -SourceRoot D:\training_platform `
  -ReleaseBodyPath .\release-notes\v1.2.3.md
```

只更新 Release 页面正文、不重新构建、不重新上传 zip/manifest：

```powershell
.\scripts\publish-local-release.ps1 `
  -Target emo-vision-train `
  -ReleaseTag v1.0.7 `
  -SourceRoot D:\training_platform `
  -PreviousSourceRef v1.0 `
  -NotesOnly
```

updater 可以使用固定 manifest 地址：
`https://github.com/jsdfhasuh/emo-vision-train-release/releases/latest/download/manifest.json`

`manifest.json` 字段：
- `version`: 从 `ReleaseTag` 去掉开头 `v` 得到，例如 `v1.2.3` -> `1.2.3`
- `url`: 当前 GitHub Release 中 zip asset 的下载地址
- `sha256`: zip 文件的 SHA256
- `notes`: `-Notes` 参数，默认等于版本号
- `mandatory`: 是否强制更新，来自 `-Mandatory`
- `source_repo`: 源码仓库，格式 `owner/repo`
- `source_ref`: 本次打包使用的源码 ref
- `source_commit`: 本次打包使用的源码 commit
- `source_base_ref`: Release Notes 对比起点
- `source_compare_url`: GitHub compare URL
- `archive_compression`: zip 压缩方式，例如 `zip/lzma` 或 `zip/deflate`
- `assets.portable`: 便携版的 `name/url/sha256`；仅 installer 目标生成
- `assets.setup`: 安装程序的 `name/url/sha256`；仅 installer 目标生成

### 配置说明（`configs/*.json`）
- `source_repo`: 外部源码仓库，格式 `owner/repo`
- `release_repo`: 可选，默认发布仓，格式 `owner/repo`
- `python_version`: GitHub Actions 使用的 Python 版本
- `pyinstaller_version`: 目标锁定的 PyInstaller 版本说明
- `release_asset_name`: Release 附件名模板
- `source_version_file`: 可选，包含 `__version__` 的源码文件，用于 tag 校验
- `ci_extra_packages`: GitHub Actions 安装源码依赖后额外安装的打包依赖
- `entry`: 入口脚本路径，可使用 `${SOURCE_ROOT}`
- `name`: 输出名称
- `onefile`: `true/false`，单文件或目录模式
- `console`: `true/false`，是否显示控制台窗口
- `collect_conda_runtime_dlls`: 是否自动收集整套 Conda runtime DLL，默认 `true`
- `icon`: 图标路径或 `null`
- `add_data`: 额外数据文件映射列表
- `hidden_imports`: 隐式导入列表
- `excludes`: 排除模块列表
- `collect_binaries`: 需要收集二进制的模块列表
- `extra_args`: 额外的 PyInstaller 原始参数
- `installer`: 可选 Inno Setup 配置；`enabled=true` 时生成 setup asset 并运行安装验收

`installer` 支持 `compiler_version`、`release_asset_name`、`app_id`、`app_name`、
`publisher`、`default_dir_name`、`executable`、开始菜单/桌面快捷方式名称、
`smoke_test` 和 `forbidden_names`。未配置 installer 的旧目标仍只生成 zip 和 manifest。

### 示例
```json
{
  "source_repo": "owner/repo",
  "release_repo": "owner/release-repo",
  "python_version": "3.11",
  "release_asset_name": "app-windows-${RELEASE_TAG}.zip",
  "ci_extra_packages": [],
  "entry": "${SOURCE_ROOT}/app.py",
  "name": "app",
  "onefile": false,
  "console": true,
  "icon": null,
  "add_data": [],
  "hidden_imports": ["numpy"],
  "excludes": [],
  "collect_binaries": ["torch"],
  "extra_args": ["--collect-data=ultralytics"]
}
```
