# VisionWorkshop：名称、ICO 和便携 ZIP

本功能面向现有 `emo-vision-train` 目标。只生成目录式 Windows 程序和 ZIP，
不新增 setup、安装、卸载或快捷方式。原目标 JSON、依赖版本、运行时 hook、
`emo-master` 配置和安装器脚本不改。

**代码已接通，不等于真实产品已经验收。** `build.py` 只构建程序目录；新的发布入口
完成目录构建、记录、ZIP 校验和可选发布。选用配置档时附带运行时品牌资源，窗口标题和
窗口图标由应用侧的 `app_branding.py` 读取并应用；打包器不修改源码和运行时更新地址。
EXE 改名且没有旧名兼容入口时仍禁止发布。当前配置档使用固定的 VisionWorkshop
兼容启动器契约；构建时生成并校验旧名入口，见第 9 节。

## 1. 准备

在 Windows 中使用已经安装目标项目依赖的 Python 环境。SOURCE_ROOT 必须是实际 Git
仓库根目录；允许有本地修改的新构建，但该产物不能直接复用或发布。需要 Git、PyInstaller
和已有的 Pillow；压缩优先使用 7z，缺少时使用 PowerShell Compress-Archive。

正式 ICO 已放入 `assets/icons/visionworkshop.ico`，来源和哈希见 `assets/README.md`。
测试代码产生的图标仅是测试数据，不是 VisionWorkshop 品牌图标。

配置档通过 `runtime_branding_path` 指向 `assets/branding.json`，显示名为 VisionWorkshop，
窗口图标为相对此 JSON 的 `icons/visionworkshop.ico`。两个文件通过主程序的 `add_data`
进入冻结资源根目录，默认是 `_internal/branding.json` 和 `_internal/icons/visionworkshop.ico`。
应用可继续使用 `get_path("branding.json")`。该配置只接受显示名和相对 ICO 路径。
显式设置 `updater_program_name` 时，更新器也嵌入同一 ICO 和品牌资源；它独立读取显示名，
不导入 Qt/OpenCV 或整个应用。
更换窗口图标需更新此 JSON 及其资源；向导中的 ICO 覆盖只控制 EXE 图标。

当前配置档的主程序和目录名为 `VisionWorkshop`，更新器为 `VisionWorkshopUpdater.exe`，
ZIP 名为 `VisionWorkshop-windows-${RELEASE_TAG}.zip`。旧 EXE 名仅作为兼容入口保留。

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
    VisionWorkshopUpdater.exe
    emo-vision-train.exe       # 兼容启动器，转到 VisionWorkshop.exe
    training_platform.exe     # 同一兼容启动器，支持早期名称
    updater.exe               # 更新器的旧名兼容副本
    _internal/branding.json
    _internal/icons/visionworkshop.ico
    _internal/...
```

ZIP 从应用目录的父目录归档，只包含一个应用根目录。构建机的 dist/build 层级不会写入 ZIP。
保留原压缩策略：7z ZIP/LZMA、内存失败时从两线程降到一线程；无 7z 则使用原 deflate 回退。
归档后逐文件读取、检查路径、大小和 SHA256；仅 CRC 检查或压缩工具退出 0 不算验收。
若 Compress-Archive 因隐藏文件等行为漏打文件，校验会失败，不会悄悄发布缺文件的包。

7-Zip 显示 Everything is Ok 只表示压缩完成，后面仍有完整性校验和可选上传。
新归档在本次进程中只做一次完整 ZIP 内容校验，校验前后计算压缩包指纹，确认读取期间
文件没有变化。发布前仍完整复查源码、工具环境和构建目录，并再次核对 ZIP 的 SHA256
和大小；不再重复解压所有文件，也不在紧邻的归档和发布阶段重复扫描构建目录。
校验结果仅在本次进程中复用，不能凭磁盘上的 build-summary.json 跳过完整内容校验。
使用构建记录重新归档时，仍先验证记录和产物，并对新 ZIP 执行一次完整内容校验。

编译、压缩、内容校验、输入复查、ZIP 指纹和上传均显示阶段开始、结束与耗时。
长步骤每 10 秒输出进度；内容校验显示已读取的解压字节比例和文件数，ZIP 指纹显示读取
字节比例。源码复查和上传没有可靠百分比时只显示正在处理和已耗时，不伪造进度。
失败或取消不会显示该阶段完成，也不会把摘要标记为已发布。压缩算法和压缩等级保持不变。

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

源码目录优先使用 `SOURCE_ROOT`；未设置时读取旧向导本地记录中该目标的源码目录。
版本号默认读取配置的 `source_version_file` 中的 `__version__`；未配置时读取
源码 `app_version.py` 中的 `APP_VERSION`（也支持 `__version__`）。这里只解析
字符串赋值，不导入或执行应用代码。没有可用源码版本时，尝试根据配置发布仓最近的
非草稿 Release 增加补丁号；查询超时、未登录或没有可用版本时仍可手动填写。
直接回车接受方括号中的版本；输入 `1.0.20` 会自动规范化为 `v1.0.20`。
版本格式会在展示摘要和最终确认之前校验，错误输入会要求重填。上述默认值不会保存外观，
也不会修改源码版本或目标配置；源码版本已发布时仍需自行更新版本，不能覆盖已有 Release。

### 发布文档与确认

模式 3/5 会补充发布仓库、Release 标题、更新短说明和是否强制更新；强制更新默认关闭。
仅构建/预览/本地归档时可以选择准备文档，但不会因此上传。短说明写入 manifest.notes，
完整 Markdown 正文用于 Release 页面，两者独立。默认标题使用本次程序名和版本号。

正文可从源码变更生成中文草稿，也可导入 UTF-8 Markdown。自动生成时需确认日志范围：
优先读取上个 Release manifest 的 source_commit，也可手动输入源码 commit/tag，或显式
选择首次发布的完整历史。起点必须是本次源码提交的祖先；超过 50 个提交会再次询问。
没有范围时不会偷偷使用最近 30 条提交。自动文案只按真实提交标题分类，发布前应人工核对。

确认页面展示发布仓库、版本、源码提交、程序/更新器名、ZIP、摘要和强制更新状态：
- p：查看完整正文；只改正文时同时展示修改差异。
- e：打开记事本编辑草稿，或导入另一份 Markdown。编辑保存后回车重新读取。
- b：返回文档设置，保留已编辑正文和已填摘要作为默认值。
- s：仅保存正文草稿；d：查看详细配置；y：确认执行；n：取消。

确认后的正文快照和显式保存/编辑的草稿位于 artifacts/release-drafts/，不会加入 ZIP，
也不会自动上传；取消不会自动写入草稿，但保留用户主动保存/编辑的文件。
正文、日志范围和已存在的目标版本在构建前检查。确认后源码 HEAD 变化会要求重新预览，
构建期间上传正文使用已确认快照，不重新读取可能已被修改的编辑文件。
共享 CLI 的 --dry-run 会显示实际正文，仍不创建构建或发布输出。

### 只更新已有正文

模式 6 选择已有 Release，不递增版本号，也不询问品牌图标。可以编辑现有正文、导入
Markdown，或按该 Release manifest 中的源码提交重新生成。重生成不会使用当前 HEAD
代替历史发布版本；记录缺失、源码仓不匹配或本地找不到提交时应改为编辑/导入正文。
最终确认会展示正文差异，只修改正文，保留 Release 标题、ZIP、manifest 和校验值。
提交前重新读取 Release；若正文或资产等已变化，会要求重新预览，不直接覆盖他人的修改。

非交互入口为 scripts/publish_visionworkshop.py --notes-only --release-repo owner/repo
--release-tag v1.0.20 --release-body-path <Markdown 文件>；默认只预览，明确加 --publish
才修改远端正文。此模式不需要源码目录，不能与品牌、构建或 manifest 字段覆盖参数混用。
旧 PowerShell 入口及 --legacy 逻辑保留不变。

恢复默认只需不再选择配置档和覆盖参数。原始 `configs/emo-vision-train.json` 没有被改写。
例如直接运行原来的 `build.py --config configs/emo-vision-train.json --clean` 仍是原构建规则。
恢复今后的打包默认值，不会自动把现场已部署的改名版本迁移回旧名称。

## 6. 发布边界

发布只能显式传 `--publish` / `-Publish`。改 EXE 名但没有完整兼容启动器契约时，
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
代码审查和模拟编译不能代替实际产品验收；离线迁移测试也不代表真实 GUI/GPU 功能验收。

## 9. 改名与旧版本兼容

`profiles/visionworkshop.json` 显式声明 `updater_program_name` 和 `legacy_program_names`。
旧名启动器仅支持转到同目录下的 `VisionWorkshop.exe`，不执行 shell、不读取网络配置，
并原样转发启动参数。主程序、更新器和兼容启动器共用正式 ICO。

旧更新器仍按旧名寻找入口并重启；新包中的 `emo-vision-train.exe` 和
`training_platform.exe` 会启动真正的 VisionWorkshop。原安装目录及其旧快捷方式继续有效，
不需要假定所有旧客户端先升级过渡版本。不要删除这些兼容入口。

新版应用优先复制 `VisionWorkshopUpdater.exe` 到更新缓存，缺失时仍识别 `updater.exe`。
新版更新器先检查包中是否存在可用入口，再替换应用目录；同一包中优先选择
`VisionWorkshop.exe`，也识别两个已知旧名。不明确的多应用包会被拒绝。
用户数据、日志和更新缓存仍使用 `training_platform` 身份，更新地址不变。

构建会额外编译一次轻量兼容启动器，复制出所声明的旧名入口，并校验所有入口存在、
旧名启动器字节一致、两个更新器文件字节一致；这些文件及启动器源码均进入构建记录校验。
没有兼容入口的其他改名请求仍然受发布保护，不提供跳过检查开关。

离线迁移验收使用明确指定的旧源码版本编译旧更新器，并用当前源码编译新更新器。
只构建临时小程序，不下载或发布真实产品：

```powershell
python scripts/verify_windows_update_migration.py `
  --source-root $env:SOURCE_ROOT --legacy-source-ref <已确认的旧源码提交>
```

结果写入 `artifacts/windows-update-migration.json`，记录旧源码提交及新旧更新器源码哈希。
