# VisionWorkshop：名称、ICO 和便携 ZIP

本功能面向现有 `emo-vision-train` 目标。只生成目录式 Windows 程序和 ZIP，
不新增 setup、安装、卸载或快捷方式。原目标 JSON、依赖版本、运行时 hook、
`emo-master` 配置和安装器脚本不改。

**代码已接通，不等于真实产品已经验收。** `build.py` 只构建程序目录；新的发布入口
完成目录构建、记录、ZIP 校验和可选发布。窗口标题、窗口图标、运行时更新地址没有被修改。
EXE 改名且启用现有 updater 时禁止发布，直到应用侧另外完成并验证更新契约。

## 1. 准备

在 Windows 中使用已经安装目标项目依赖的 Python 环境。SOURCE_ROOT 必须是实际 Git
仓库根目录；允许有本地修改的新构建，但该产物不能直接复用或发布。需要 Git、PyInstaller
和已有的 Pillow；压缩优先使用 7z，缺少时使用 PowerShell Compress-Archive。

仓库不附带正式产品 ICO。将批准的图标放入 `assets/icons/visionworkshop.ico`，或者在
本次命令显式指定实际文件。测试代码产生的图标仅是测试数据，不是 VisionWorkshop 品牌图标。

新图标和配置档的相对路径以打包仓库为基准，支持 `${PACKAGER_ROOT}`、`${SOURCE_ROOT}`。
程序名是字面量，不含 `.exe`；允许中文和内部空格，禁止路径、设备名和 updater 名称冲突。

## 2. 预览与本地 ZIP

在打包仓库根目录执行；示例路径和版本号需替换。下面两条命令都不上传：

```powershell
python .\scripts\publish_visionworkshop.py `
  --source-root 'D:\Projects\emo-vision-train' `
  --release-tag v1.2.3 `
  --branding-profile profiles/visionworkshop.json `
  --icon-path 'D:\Icons\visionworkshop.ico' `
  --dry-run

python .\scripts\publish_visionworkshop.py `
  --source-root 'D:\Projects\emo-vision-train' `
  --release-tag v1.2.3 `
  --branding-profile profiles/visionworkshop.json `
  --icon-path 'D:\Icons\visionworkshop.ico' `
  --build-only `
  --output-directory '.\release-output\VisionWorkshop-v1.2.3'
```

OutputDirectory 必须是新目录或空目录，且不能放进源码、dist 或私有 build 目录。
不指定时使用隔离的新输出目录。新入口默认就是仅构建，不因为省略 `--build-only` 而发布。
显式给出的 source-ref 必须存在且等于当前 HEAD，不会自动 checkout 或悄悄回退。

PowerShell 入口也已接入，推荐给出 `PythonExecutable` 以使用正确环境：

```powershell
.\scripts\publish-local-release.ps1 `
  -Target emo-vision-train `
  -SourceRoot 'D:\Projects\emo-vision-train' `
  -ReleaseTag v1.2.3 `
  -BrandingProfile profiles/visionworkshop.json `
  -IconPath 'D:\Icons\visionworkshop.ico' `
  -PythonExecutable 'D:\Envs\vision\python.exe' `
  -BuildOnly
```

普通无外观参数的旧发布调用，以及 emo-master 调用，仍委托原脚本；该原脚本内容不变，
现在存为同目录的 `publish-local-release-legacy.ps1`。训练目标显式 BuildOnly 使用新本地路径，
不要求 gh。不要直接调用 legacy 脚本来发布改名产物；它不理解新构建记录和外观覆盖。

## 3. 结果

```text
release-output/.../
  VisionWorkshop-windows-v1.2.3.zip
  build-summary.json

ZIP 内部：
  VisionWorkshop/
    VisionWorkshop.exe
    updater.exe
    _internal/...
```

ZIP 从应用目录的父目录归档，只包含一个应用根目录。构建机的 dist/build 层级不会写入 ZIP。
保留原压缩策略：7z ZIP/LZMA、内存失败时从两线程降到一线程；无 7z 则使用原 deflate 回退。
归档后逐文件读取、检查路径、大小和 SHA256；仅 CRC 检查或压缩工具退出 0 不算验收。
若 Compress-Archive 因隐藏文件等行为漏打文件，校验会失败，不会悄悄发布缺文件的包。

build-summary.json 是脱敏摘要，不包含绝对源码路径、完整配置、凭据或私有构建记录。
仅构建不生成可被误认成正式更新入口的 manifest，也不伪造已可下载的 URL。
用户仍然解压整个目录后运行，不需要安装器；相机驱动等原项目运行要求并未被取消。

## 4. 防止错用旧产物

每次构建都有新的 work/spec/dist 上下文；成功后私有目录记录：

```text
build/branding/emo-vision-train/<build-id>/
  effective-config.json
  build-record.json
  build-result.json
```

`build-record.json` 保存配置、ICO 内容、源码 HEAD/工作文件/子模块、打包器代码和工具环境
摘要，以及产物文件哈希。全部任务完成、updater 复制和输入/输出校验通过才原子写入成功记录。
这不是数字签名、沙箱或逐字节可复现构建证明，也不防御有本机写权限的人同时伪造记录和产物。

复用时必须显式选定原位置的构建记录。例如以下命令只重新归档、不编译、不上传：

```powershell
python .\scripts\publish_visionworkshop.py `
  --source-root 'D:\Projects\emo-vision-train' `
  --release-tag v1.2.4 `
  --branding-profile profiles/visionworkshop.json `
  --icon-path 'D:\Icons\visionworkshop.ico' `
  --skip-build `
  --build-record-path 'D:\Projects\python_build_scripts\build\branding\emo-vision-train\<实际编号>\build-record.json' `
  --build-only
```

路径中的 `<实际编号>` 是占位符，必须使用构建输出中打印的真实路径。图标在同一路径被替换、
配置/源码/工具环境改变、产物被编辑、记录被移动或源码原本不干净，都会要求重建。
不使用“最近的 dist”。私有记录和有效配置不能交付给最终用户。

## 5. 向导和恢复默认

```powershell
python .\scripts\release_wizard_emo_vision_train.py
```

新向导首先选择模式，默认仅构建 ZIP；然后显式选择原始外观、VisionWorkshop 配置档或本次
自定义。不保存上次临时外观；EOF/取消不会启动构建。`--yes` 只跳过最后确认，不跳过校验。
向导直接调用共享 Python 入口，使用启动向导的同一个解释器。emo-master 向导仍不变。
需要旧训练平台发布向导时使用 `--legacy`，但不要用它处理新外观构建。

恢复默认只需不再选择配置档和覆盖参数。原始 `configs/emo-vision-train.json` 没有被改写。
例如直接运行原来的 `build.py --config configs/emo-vision-train.json --clean` 仍是原构建规则。
恢复今后的打包默认值，不会自动把现场已部署的改名版本迁移回旧名称。

## 6. 发布边界

发布只能显式传 `--publish` / `-Publish`。改 EXE 名且 updater 兼容未验证时，
在 gh 登录、编译和远端写操作之前报错。换 release_repo、tag 或 manifest 名不能绕过；
没有强制忽略风险开关。仅构建也没有关闭程序运行后的自动更新。

保持原 EXE 名、只改图标的路径可以显式发布，但要求源码干净、子模块完整、记录和产物一致。
新入口保留原客户端的 manifest 字段。为避免覆盖现有发布，新入口拒绝已存在的 tag，
不隐式使用 `--clobber`；需要另一个 tag。旧发布入口的原行为不因此被全局改变。
上传失败时摘要保持 published=false；未真实验证的窗口启动和更新状态不会标记成通过。

## 7. Actions

新增 `VisionWorkshop portable ZIP` 工作流，支持 workflow_dispatch 和 workflow_call。
这是独立的 VisionWorkshop 入口，原 Release Windows Build 保持不变，不给其他项目重做发布。
新入口的手动与复用参数一致，默认 publish_release=false。

手动在本仓运行时，未提供 packager_ref 就用所选 workflow SHA；跨仓复用必须明确给出
packager_ref。source_ref 必填，不猜测旧分支。配置档和 ICO 必须能在 runner checkout 中取得；
先检查名称/ICO/发布风险，再安装大型源码依赖。构建和本地命令用同一解析器。
上传 Actions artifact 只包含 ZIP 和公开摘要，不包含 build-record 或有效配置；这不是发布到
客户端更新通道。显式发布另需 RELEASE_REPO_TOKEN，不把测试 workflow 的只读 token 升权。

新 workflow 定义在功能分支时，不应据此声称已可从默认分支的手动菜单启动；以 GitHub 实际
识别的 workflow 状态为准。本次不自动合并功能分支或触发生产发布。

## 8. 测试与验收

```powershell
# 在开发/测试环境安装测试依赖，不修改目标项目 requirements。
python -m pip install Pillow PyYAML
python -m unittest discover -s tests -v
```

新增 `VisionWorkshop portable tests` 工作流。Windows 任务还运行
`python scripts/verify_windows_portable.py`，使用临时小项目真实编译、解压、启动、检查 EXE
里的 RT_ICON 数据、验证 updater 测试程序和复用记录，并输出 JSON 证据。
这些是测试 fixture，不是 VisionWorkshop 产品、正式图标或真实 updater 升级协议。

实际产品仍需在 Windows 上用准备好的源码/依赖/正式 ICO 验证 Qt 窗口、资源与硬件相关功能。
跨名称更新仍需应用侧独立实施。代码审查和模拟编译通过不能代替这些测试。
