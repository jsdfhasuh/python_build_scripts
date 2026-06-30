# PyInstaller Build Helper

## 项目简介
这是一个专用于构建 PyInstaller 包的主打包仓库，核心脚本为 `build.py`，
通过读取 `configs/*.json` 生成并执行 PyInstaller 命令。

仓库只维护构建逻辑、打包配置和 GitHub Actions workflow，不包含被打包应用本身的源码。
v1 默认目标为 `emo-vision-train`，源码仓库为 `jsdfhasuh/emo-vision-train`，
发布仓库为 `jsdfhasuh/emo-vision-train-release`。

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
- `release_tag`: Release tag，例如 `v1.2.3`
- `release_repo`: 发布仓，格式 `owner/repo`；留空时使用目标配置里的 `release_repo`，再留空则使用当前 workflow 仓库

私有源码仓 checkout 需要在当前仓库配置 `SOURCE_REPO_TOKEN` secret。
如果 `release_repo` 指向另一个仓库，需要配置 `RELEASE_REPO_TOKEN` secret，
并确保它有目标发布仓的 `contents: write` 权限。
workflow 只做打包，不做 GPU runtime 验证。

### 本地打包并上传 Release
如果 GitHub Actions 临时卡在依赖下载或构建环境，可以在本机打包后上传到指定发布仓 Release：

```powershell
.\scripts\publish-local-release.ps1 `
  -Target emo-vision-train `
  -ReleaseTag v1.2.3 `
  -SourceRoot D:\training_platform `
  -Notes "1.2.3"
```

脚本会上传两个 Release assets：
- `emo-vision-train-windows-v1.2.3.zip`
- `manifest.json`

updater 可以使用固定 manifest 地址：
`https://github.com/jsdfhasuh/emo-vision-train-release/releases/latest/download/manifest.json`

`manifest.json` 字段：
- `version`: 从 `ReleaseTag` 去掉开头 `v` 得到，例如 `v1.2.3` -> `1.2.3`
- `url`: 当前 GitHub Release 中 zip asset 的下载地址
- `sha256`: zip 文件的 SHA256
- `notes`: `-Notes` 参数，默认等于版本号
- `mandatory`: 是否强制更新，来自 `-Mandatory`

### 配置说明（`configs/*.json`）
- `source_repo`: 外部源码仓库，格式 `owner/repo`
- `release_repo`: 可选，默认发布仓，格式 `owner/repo`
- `python_version`: GitHub Actions 使用的 Python 版本
- `release_asset_name`: Release 附件名模板
- `ci_extra_packages`: GitHub Actions 安装源码依赖后额外安装的打包依赖
- `entry`: 入口脚本路径，可使用 `${SOURCE_ROOT}`
- `name`: 输出名称
- `onefile`: `true/false`，单文件或目录模式
- `console`: `true/false`，是否显示控制台窗口
- `icon`: 图标路径或 `null`
- `add_data`: 额外数据文件映射列表
- `hidden_imports`: 隐式导入列表
- `excludes`: 排除模块列表
- `collect_binaries`: 需要收集二进制的模块列表
- `extra_args`: 额外的 PyInstaller 原始参数

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
