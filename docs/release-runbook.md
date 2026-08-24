# 本地发布操作手册

这份文档用于记录本地打包并发布 GitHub Release 的固定流程，后续发版时可以直接按步骤执行。

当前默认目标：

- 打包仓库：`jsdfhasuh/python_build_scripts`
- 打包目标：`emo-vision-train`
- 本地源码目录：`D:\training_platform`
- 源码仓库：`jsdfhasuh/emo-vision-train`
- 发布仓库：`jsdfhasuh/emo-vision-train-release`
- Release 压缩包：`emo-vision-train-windows-${RELEASE_TAG}.zip`
- updater 清单文件：`manifest.json`

## 1. 发布前检查

在打包仓库根目录执行：

```powershell
cd C:\Users\jsdfhasuh\my_scripts\python_build_script
gh auth status
git status -sb
git -C D:\training_platform status -sb
git -C D:\training_platform rev-parse HEAD
```

确认当前 PowerShell 使用的是要打包的 Python 环境，例如：

```powershell
conda activate C:\Users\jsdfhasuh\.condalenvs\ltraining_platfom
python --version
```

正式发布前建议先做一次最小验证：

```powershell
$env:SOURCE_ROOT = 'D:\training_platform'
$env:RELEASE_TAG = 'v0.0.0-local'
python -m py_compile build.py
python build.py --config configs\emo-vision-train.json --dry-run
```

## 2. 确定 Release Tag

Release tag 是发布仓里的 GitHub Release 版本号，例如：

```text
v1.0.10
```

脚本会自动把它转换成 updater manifest 使用的版本号：

```text
v1.0.10 -> 1.0.10
```

## 3. 确定更新日志起点

`-PreviousSourceRef` 必须是源码仓里的 ref，不是发布仓里的 Release tag。

可以使用：

- 源码 commit SHA，例如 `8388ed0db76df7ededd9a1ffdd4400712e709cdc`
- 源码仓 tag，例如 `v1.0`
- 源码仓 branch，例如 `main`

容易出错的写法：

```powershell
-PreviousSourceRef v1.0.7
```

如果 `v1.0.7` 只存在于 `jsdfhasuh/emo-vision-train-release` 的 GitHub Release，
但不存在于 `D:\training_platform` 的 git history，脚本就会报找不到 ref。

查看源码仓现有 tag 和最近 commit：

```powershell
git -C D:\training_platform tag --list
git -C D:\training_platform log --oneline -n 20
```

从带有新 manifest metadata 的版本开始，脚本可以从上一个 Release 的
`manifest.json` 自动读取 `source_commit`，通常可以不手动传 `-PreviousSourceRef`。
如果上一个版本比较旧，没有 `source_commit` 字段，就需要手动传。

## 4. 本地发布

推荐优先使用交互式发布向导，它会逐步询问版本号、源码目录、更新日志起点和发布模式：

```powershell
python scripts\release_wizard.py
```

向导会自动列出可选的 `PreviousSourceRef`，包括上一个 Release manifest 的
`source_commit`、源码仓最新 tag、最近源码 commits、`auto` 和手动输入。
向导最后会打印真实执行的 PowerShell 命令，并要求确认后才开始发布。

最稳的方式是使用单行命令：

```powershell
.\scripts\publish-local-release.ps1 -Target emo-vision-train -ReleaseTag v1.0.10 -SourceRoot D:\training_platform -PreviousSourceRef <上一次源码commit或tag> -Notes "1.0.10"
```

如果不需要强制指定更新日志起点：

```powershell
.\scripts\publish-local-release.ps1 -Target emo-vision-train -ReleaseTag v1.0.10 -SourceRoot D:\training_platform -Notes "1.0.10"
```

也可以写成多行，方便阅读：

```powershell
.\scripts\publish-local-release.ps1 `
  -Target emo-vision-train `
  -ReleaseTag v1.0.10 `
  -SourceRoot D:\training_platform `
  -PreviousSourceRef <上一次源码commit或tag> `
  -Notes "1.0.10"
```

PowerShell 多行命令注意事项：反引号 `` ` `` 必须是该行最后一个字符，后面不能有空格。
如果某一行缺少反引号，下一行的 `-Notes "1.0.10"` 会被当成新的命令执行并报错。

## 5. 脚本会做什么

`publish-local-release.ps1` 会依次执行：

1. 读取 `configs\emo-vision-train.json`。
2. 设置 `SOURCE_ROOT` 和 `RELEASE_TAG`。
3. 调用 PyInstaller 打包，除非传了 `-SkipBuild`。
4. 把 `dist\emo-vision-train` 压缩成 Release zip。
5. 生成 `manifest.json`。
6. 根据源码仓 git history 自动生成英文 Release Notes。
7. 在 `jsdfhasuh/emo-vision-train-release` 创建或更新 GitHub Release。
8. 上传或覆盖 zip 和 `manifest.json`。

Release Notes 是固定规则生成的，不调用 AI/API。
`-Notes` 只会写入 updater manifest 的短说明字段，不是 GitHub Release 正文。

## 6. 发布后验证

查看 Release 和 assets：

```powershell
gh release view v1.0.10 --repo jsdfhasuh/emo-vision-train-release --json url,assets
```

查看 latest manifest：

```powershell
Invoke-RestMethod 'https://github.com/jsdfhasuh/emo-vision-train-release/releases/latest/download/manifest.json' |
  ConvertTo-Json -Depth 5
```

重点确认这些字段：

- `version`
- `url`
- `sha256`
- `notes`
- `mandatory`
- `source_repo`
- `source_ref`
- `source_commit`
- `source_base_ref`
- `source_compare_url`
- `archive_compression`

## 7. 只更新 Release 正文

如果 zip 和 manifest 都没问题，只想更新 GitHub Release 页面正文：

```powershell
.\scripts\publish-local-release.ps1 -Target emo-vision-train -ReleaseTag v1.0.10 -SourceRoot D:\training_platform -PreviousSourceRef <上一次源码commit或tag> -NotesOnly
```

`-NotesOnly` 不会重新 build，不会重新压缩，也不会重新上传 assets。

## 8. 使用自定义 Release 正文

如果想完全覆盖自动生成的 Release Notes，可以传 Markdown 文件：

```powershell
.\scripts\publish-local-release.ps1 -Target emo-vision-train -ReleaseTag v1.0.10 -SourceRoot D:\training_platform -ReleaseBodyPath .\release-notes\v1.0.10.md
```

## 9. 只上传已有 dist

如果 `dist\emo-vision-train` 已经存在，只想重新压缩并上传：

```powershell
.\scripts\publish-local-release.ps1 -Target emo-vision-train -ReleaseTag v1.0.10 -SourceRoot D:\training_platform -SkipBuild -Notes "1.0.10"
```

不要手动修改 `dist\`。需要变更内容时，重新 build 或复用已有生成目录。

## 10. 常见错误

### `PreviousSourceRef was not found`

传入的 `-PreviousSourceRef` 不在源码仓 history 里。可以这样检查：

```powershell
git -C D:\training_platform rev-parse --verify "<ref>^{commit}"
```

不确定时，优先使用上一次发布对应的源码 commit SHA。

### `The term '-Notes' is not recognized`

多行 PowerShell 命令的上一行没有正确用反引号结尾。

解决方式：

- 改用单行命令。
- 或确认每个续行的反引号后面没有任何空格。

### `Cannot bind argument to parameter 'Commits' because it is an empty array`

更新日志范围里没有新 commit，并且本地打包脚本版本过旧。

解决方式：更新打包仓里的 `scripts\publish-local-release.ps1`，然后重新执行。

### Release asset is larger than 2048 MB

GitHub Release 单个 asset 必须小于 2 GB。

解决方式：

- 安装 `7z`，让脚本使用 ZIP/LZMA 压缩。
- 或减少打包进去的 runtime / 依赖体积。

## 11. 快速模板

每次发版通常只需要替换 release tag、manifest notes 和上一次源码 ref：

```powershell
$releaseTag = 'v1.0.10'
$manifestNotes = '1.0.10'
$previousSourceRef = '<上一次源码commit或tag>'

.\scripts\publish-local-release.ps1 `
  -Target emo-vision-train `
  -ReleaseTag $releaseTag `
  -SourceRoot D:\training_platform `
  -PreviousSourceRef $previousSourceRef `
  -Notes $manifestNotes
```
