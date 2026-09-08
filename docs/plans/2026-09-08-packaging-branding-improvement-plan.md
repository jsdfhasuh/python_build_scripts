# Python 打包脚本改进计划：自定义程序名称与图标

**项目：** `jsdfhasuh/python_build_scripts`  
**编写日期：** 2026-09-08  
**版本：** v1.1  
**状态：** 实施计划；本次仅提交文档，M0–M5 均待实施，未执行 Windows 构建或升级验收。  
**文档位置：** `docs/plans/2026-09-08-packaging-branding-improvement-plan.md`

**计划分支：** `docs/build-branding-plan-20260908`  
**本次提交边界：** 仅新增本计划，不修改打包代码、生产配置、工作流或外部应用，不构建、不发布 Release。

## 1. 结论与实施原则

需要改进，但不需要重写打包系统。

现有 `build.py` 已能通过 JSON 的 `name`、`icon` 生成 PyInstaller 参数。此次应补齐的是统一配置解析、发布与安装同步、临时覆盖、输出隔离、发布前检查，以及测试保障，而不是重复实现另一套 PyInstaller 封装。[R1]

本次以 Windows 为范围，面向本仓库打包的多个外部 Python 项目，不把功能写死为某个训练平台。默认目标配置继续有效；自定义外观不修改源码仓库名、Python 包名、用户数据目录、安装 AppId 或更新身份。

特别注意：EXE 文件名也参与启动与更新契约，不能简单地将它视为纯外观。程序窗口标题与窗口图标则由目标程序控制，不能仅凭打包参数承诺已修改。[R8][R9][E1]

### 1.1 核查基线

| 仓库 | 分支 | 本次核查的提交 |
|---|---|---|
| `jsdfhasuh/python_build_scripts` | `master` | `ab4a33e586138fb381a87ae21cc83b5e8d79adbe` |
| `jsdfhasuh/emo-vision-train`，仅核查更新兼容性 | `main` | `59352fd5a0f183693f3384940dd2d5923e317e15` |

实施时应先重新确认分支 HEAD。若代码已变化，重新核对相应函数，不按本计划中的旧行号机械修改。本计划所称风险来自静态代码分析，不等于已完成真实安装、升级或 GUI 测试。

## 2. 当前实现与需要解决的问题

| 编号 | 已核查情况 | 改进要求 | 优先级 |
|---|---|---|---|
| F01 | `append_common_args()` 已传递 `--name`、`--icon`。[R1] | 保留并复用；新增统一的覆盖与校验入口。 | P0 |
| F02 | 构建、发布、安装器分别读取配置；安装器有独立的 `executable` 和多个显示名称。[R2][R3] | 同一次执行统一读取一份最终生效配置，避免名称不同步。 | P0 |
| F03 | 构建端展开环境变量，PowerShell 发布端另行替换部分模板；临时配置容易引入路径基准变化。[R1][R2] | 明确每种路径的基准，解析后使用绝对路径，避免重复展开。 | P0 |
| F04 | 发布脚本通过 `dist/<name>` 查找目录，`-SkipBuild` 分支没有构建配置匹配证明。[R2] | 自定义构建输出隔离，复用产物前验证构建记录及内容。 | P0 |
| F05 | 主程序改名时，训练平台更新器仍按旧进程传入的 EXE 名称查找、重启。[R8] | 增加改名发布门禁；不把新字段写入 manifest 当作旧客户端已支持迁移。 | P0 |
| F06 | Inno 脚本配置了 `UninstallDisplayIcon`，未接入 `SetupIconFile`。[R3] | 分别处理主程序图标、安装器图标和卸载显示图标。 | P0 |
| F07 | 向导未接入外观参数；启动时就要求 `gh` 登录。[R4] | 增加外观步骤；先选择执行模式，只构建路径不依赖发布账户。 | P1 |
| F08 | Actions checkout 打包仓库时固定 `ref: master`，手动输入和可复用入口均无外观字段。[R5] | 修正实际执行版本的选择，并让两个入口调用同一配置解析流程。 | P1 |
| F09 | Actions 的源码默认 ref 仍为旧功能分支；该 ref 在本次前序读取中返回 404。[R5] | 不再依赖这个旧分支；按明确输入或目标仓库默认分支解析并记录源码提交。 | P1 |
| F10 | 仓库树未包含测试目录，`AGENTS.md` 也明确尚无自动化测试。[R6] | 从配置单元测试开始，再补 Windows 构建和安装冒烟测试。 | P0 |
| F11 | 安装器无条件执行应用 `--self-test`，烟测还有 `.emo_master` 专用数据目录逻辑。[R3] | 本期只保证现有安装目标；不能给任意目标加 `installer.enabled=true` 就宣称通用安装支持。 | 边界 |

P0 为功能交付前必备；P1 为完整操作入口；P2 为后续独立扩展。不要把显示名称改动顺带扩展成依赖系统、GUI 或安装框架的全面重构。

## 3. 功能范围与不变项

### 3.1 第一版交付

支持本次构建覆盖程序文件名、显示名称、EXE 图标；对原本已启用安装器的目标同步安装名称、快捷方式目标，并可指定安装器图标。支持仅本次使用、显式选择本地预设、恢复默认配置。

本地 `build.py`、PowerShell 发布入口、两个现有向导、Actions 应遵循同一解析规则。新增命令行参数是计划接口，现有版本尚不支持。

第一版以 `.ico` 为标准输入，不加入 PNG/SVG 自动转换、在线图标下载或新的图形界面。ZIP 和 setup 文件名继续由独立模板控制，可显式覆盖，不强制跟随显示名称变化。

### 3.2 三种名称必须分离

| 概念 | 示例 | 作用与边界 |
|---|---|---|
| 构建目标 | `emo-vision-train` | 选择源码仓库、依赖与默认构建配置，不因外观变化而重命名。 |
| 程序文件名 | `VisionWorkshop` | 生成 `VisionWorkshop.exe`；可能影响更新、脚本和快捷方式。 |
| 显示名称 | `视觉工坊` | 安装界面、快捷方式等面向用户的文字；运行时标题需要应用配合。 |

下列项目不随外观覆盖自动变化：`source_repo`、`release_repo`、源码入口与包名、依赖列表、用户数据目录、安装 `app_id`、默认安装目录、更新通道、版本号语义、更新器文件名及参数契约。

安装器 `AppId` 用于安装身份识别。临时改外观仍属于同一应用，默认保持不变；需要并行安装两个独立产品属于另一个需求，不能只换显示名称就视为已支持。[E2]

## 4. 统一配置设计

### 4.1 一个解析核心，多个薄入口

建议新增：

- 根目录 `build_config.py`：配置合并、类型与名称校验、路径解析、安装字段派生、变更摘要。
- `scripts/resolve_build_config.py`：供 PowerShell 和 CI 调用的薄命令行入口；复用上述模块，不再实现一份逻辑。

现有 `build.py` 直接调用公共模块。发布脚本先生成最终配置，再将同一文件交给构建、安装器和归档阶段；下游不得重新读取原始 JSON 覆盖最终结果。

处理顺序：

```text
目标原始配置
  → 显式选中的本地预设
  → 本次命令行或向导输入
  → 校验与派生
  → 本次最终配置 + 变更摘要
  → EXE / 安装器 / ZIP / 发布检查
```

优先级为：本次显式输入 > 显式选中的预设 > 原始目标配置。向导只是参数输入方式，不另设一套优先级。不能因为本机曾保存过某个预设就自动改变后续默认构建。

### 4.2 拟新增覆盖字段

| 覆盖字段 | 生效位置 | 规则 |
|---|---|---|
| `program_name` | 顶层 `name` | 输入不带 `.exe`；显式覆盖时同步安装器 EXE 目标。 |
| `display_name` | 最终配置的显示名称与安装显示字段 | 显式覆盖时同步安装器 `app_name`、`start_menu_name`、`desktop_shortcut_name`。 |
| `icon_path` | 顶层 `icon` | 指向已验证的 `.ico`，下游接收绝对路径。 |
| `setup_icon_path` | `installer.setup_icon`，拟新增 | 明确指定优先；否则在本次显式替换主图标时继承主图标。 |
| `release_asset_name` | 便携 ZIP 模板 | 单独显式设置，不因显示名称改变而隐式重写。 |
| `setup_asset_name` | `installer.release_asset_name` | 仅在安装器启用时有效。 |

无覆盖时保留原配置，包括 `EmoMaster` 与 `Emo Master` 这类原本不同的文件名和显示名称。不能为了“统一”而把现有合法配置强制改成同一个字符串。

仅改 `program_name` 时，不擅自覆盖原本独立设置的显示名称，但应在确认页提示两者不同；用户可再显式设置 `display_name`。

空白交互输入代表沿用当前默认。恢复默认是放弃覆盖项、重新从原始配置解析，不是删除原始图标。第一版无需额外实现“彻底移除 EXE 图标”开关，避免把未指定、继承和移除混为一谈。

### 4.3 参数建议

| 功能 | `build.py` | PowerShell 发布脚本 |
|---|---|---|
| 程序文件名 | `--program-name` | `-ProgramName` |
| 显示名称 | `--display-name` | `-DisplayName` |
| EXE 图标 | `--icon-path` | `-IconPath` |
| 本地预设 | `--branding-preset` | `-BrandingPreset` |
| 安装器图标 | 可由配置提供 | `-SetupIconPath` |
| 便携包名称模板 | 可由配置提供 | `-ReleaseAssetName` |
| 安装包名称模板 | 可由配置提供 | `-SetupAssetName` |
| 预览 | 保留 `--dry-run` | 增加 `-DryRun` |
| 明确指定复用记录 | 不适用 | `-BuildRecordPath`，与 `-SkipBuild` 配合 |

直接 `build.py` 只构建 PyInstaller 产物，不承担发布或生成 Inno 安装器。最终配置的内部传递接口应与用户覆盖参数互斥，禁止下游再次覆盖或再次展开已经解析的内容。

### 4.4 路径与字符串规则

旧配置的路径语义不做隐式迁移。发布入口仍以打包仓库根目录为工作目录；直接调用旧版 `build.py` 路径行为由兼容测试保护。

新增覆盖图标的相对路径统一以打包仓库根目录为基准，并在帮助中明确说明。支持 `${SOURCE_ROOT}/...` 与拟新增 `${PACKAGER_ROOT}/...`，但不得向现有进程全局写入长期环境变量。绝对路径按实际文件解析。

最终配置写入临时目录后，不能按该临时目录重新解释原来的相对路径。将图标、入口、数据源、运行时 hook 等相关文件路径在对应边界解析清楚，同时保护 `add_data` 的源/目标分隔规则，不做任意字符串拼接。

对当前阶段必需的路径，未定义变量、文件不存在或目录误填应在编译前报错。资产模板在需要 ReleaseTag 的阶段再完整解析；纯 EXE 预览不应凭空要求一个发布版本号。显示名称是字面量，不应因为含有 `$`、`%` 就被重复展开为环境变量。

### 4.5 校验规则

程序文件名不得为空，不带 `.exe`，不得包含路径分隔符、控制字符、Windows 保留字符、保留设备名称、尾随点或空格。校验按 Windows 规则执行，即使配置单元测试运行在其他系统也不能套用 POSIX 文件名规则。[E3]

允许经过校验的中文、英文和空格，不强制用户使用英文。快捷方式名称同样是文件名，需要校验；无法用于快捷方式的显示名称应明确报错或要求独立快捷方式名，不能静默截断。

主程序名还要与 updater 构建任务名、最终复制目标 `updater.exe` 做不区分大小写的冲突检查，防止两个任务输出同名 EXE/spec，或复制更新器时覆盖主程序。

ICO 至少检查真实文件头、图像目录、尺寸和数据范围，不只检查扩展名。推荐多尺寸图标；缺少推荐尺寸给警告，格式损坏直接失败。安装器推荐包含 16、32、48、64、256 像素图像。[E4]

ZIP、setup 以及 manifest 的输出名称也按单个安全文件名验证：展开模板后不得含路径分隔符、绝对路径或目录穿越，各个产物名称不能相互覆盖。对最终输出目录执行边界检查。

新输入只走允许的字段映射，不能覆盖任意源码路径、依赖或仓库字段。`extra_args` 如与名称、图标、输出路径或打包模式冲突，在自定义构建模式中应报错，不接受“最后一个参数获胜”。第一版不承诺修改用户手写 `.spec`；检测到相关不支持组合应提前说明。

## 5. 构建、输出隔离与产物复用

### 5.1 构建职责

沿用当前 PyInstaller 参数生成、Torch/ONNX Runtime hook、Conda DLL 收集与 updater 构建逻辑。此次不顺带调整依赖版本、CUDA 组合、控制台开关、压缩算法或模型资源收集策略。

EXE 名称与图标通过 PyInstaller 的正式参数写入，不能先打包旧名字再手动重命名文件。程序名变化时，安装器目标和归档目录必须跟随同一最终配置。[E1]

现有两个发布目标均采用目录式主程序。自定义功能第一版的发布验收以这些目录式配置为范围；`build.py` 原有单文件构建仍应保留。不要因为基础构建支持 onefile 就声称现有 updater 复制、ZIP 发布和安装逻辑已经支持任意 onefile 组合。

### 5.2 输出隔离

无外观覆盖的普通构建继续保持现有输出约定。自定义构建使用独立构建上下文，建议：

```text
build/branding/<target>/<build-id>/
  effective-config.json       # 本地私有：可能含绝对路径
  build-record.json           # 本地完整校验记录
  work/<job>/
  spec/<job>/

dist/branding/<target>/<build-id>/
  <program-name>/
    <program-name>.exe
    updater.exe              # 仅原配置已启用时
    _internal/...

release-output/branding/<target>/<build-id>/
  <archive>.zip
  <setup>.exe                 # 仅安装器已启用时
  manifest.json
  build-summary.json         # 脱敏摘要
```

路径为建议布局，具体字段由解析器统一计算。`copy_updater_to_app_dir()` 等函数应接收显式构建目录，不再自行假设固定的 `dist` 根路径。每个 job 的 work/spec 独立，防止主程序与 updater 或两个并行构建互相覆盖。

默认构建目录若未做并行隔离，应有同一目标的并发保护，不能宣称默认路径可以安全并发。

### 5.3 `SkipBuild` 安全检查

使用旧目录不等于当前配置已构建。`-SkipBuild` 通过显式的 `-BuildRecordPath` 定位构建记录与对应产物；向导也必须明确选择记录，不能自动猜测“最近一个目录”。复用时至少验证：目标、源码提交、构建器提交、有效配置摘要、图标内容哈希、Python/PyInstaller 版本及相关构建环境记录、预期 EXE、输出文件清单与内容哈希。

仅源码 commit 相同不能证明本地工作树未变。第一版对存在源码未提交修改的情况不允许 `SkipBuild`，要求重新构建；这不等同于全面禁止正常的本地开发构建。

不存在构建记录、图标内容变化、配置变化或产物被改动时，拒绝复用，并给出“重新完整构建”的操作说明。旧版 dist 首次使用新的复用检查时也应要求重建，这是有意增加的安全限制。

构建记录只能在全部构建任务和 updater 复制成功后原子写成完成状态，失败记录不得用于发布。除 Git SHA 外，记录实际参与构建的图标、运行时 hook、配置、资源等输入摘要；源码或输入在构建期间变化应使记录失效。`build_id`、时间戳和隔离目录绝对路径等执行信息不参与语义配置指纹，否则相同配置无法复用。符号链接或指向输出根目录外的记录不得成为读取或发布任意文件的入口。

构建记录用于防止错用旧产物，不代表已实现二进制逐字节可复现构建。完整配置与用户绝对路径不直接放入公开 ZIP 或自动上传目录。

## 6. 发布与自动更新兼容性

### 6.1 已确认的训练平台改名风险

训练平台 `auto_update.py` 默认以当前 `sys.executable` 的文件名作为安装后重启名称；`updater.py` 接收 `--exe`，随后用同一个名称查找和重启。[R8]

因此，旧程序为 `emo-vision-train.exe`，新包只提供 `VisionWorkshop.exe` 时，即使解压目录的兜底逻辑找到了新包，后续仍会按旧名寻找启动文件并失败。这是代码逻辑分析结论，尚未进行真实 Windows 升级复现。

单纯保持 `updater.exe` 原名，或者在 manifest 增加一个 `program_name` 字段，不能让旧更新器自动理解这个变化。

### 6.2 第一版发布门禁

普通无覆盖发布保持现有流程。包含外观覆盖的向导默认选择“只构建，不发布”；公开发布必须显式选择，并显示仓库、tag、产物名称和更新兼容检查结果。

对于启用现有更新器且修改了主 EXE 名称的目标，第一版禁止向原自动更新通道发布此包。不能提供一个通用强制开关绕过这项检查。未来只有在独立的更新迁移方案完成并有测试证据后，才能解除对应限制。发布检查以目标的原始程序名称及明确的更新契约为基线；无法证明新通道隔离的改名目标应保守阻断。仅修改 `ReleaseRepo`、tag 或 `ManifestName` 不等于改变已打包程序里的更新地址，不能绕过此限制。

**仅构建不等于运行时已禁止更新。** 打包器不会自动改变训练平台启动后的更新检查行为。改名版即使手动分发，仍可能从原通道下载不匹配的包。因此，在目标应用没有受支持的关闭或隔离更新方案前，这类产物只能标记为构建验证版，不能宣称已经满足可交付更新兼容性。

临时使用更稳妥的路线是保留原主 EXE 名称，改变图标与面向用户的名称；窗口标题仍按第 10 节由应用显式适配。这条路线仍需正常构建和安装验收。

### 6.3 保持旧 manifest 契约

继续保留旧客户端使用的 `version`、`url`、`sha256`、`mandatory`、`notes` 及原有扩展字段，不能用新嵌套结构替换旧字段。[R2]

新增构建信息优先放在独立、脱敏的 `build-summary.json`；确有需要才增加兼容性的 manifest 字段。不能改变老字段含义，也不能将构建机绝对路径、token、完整环境变量或含凭据 URL 放入公开文件。

### 6.4 执行模式

| 模式 | 应有行为 |
|---|---|
| 预览 | 解析、校验、显示计划；不执行 PyInstaller，不联网发布，不改原配置。 |
| 只构建 | 生成本地 EXE/ZIP/既有安装目标产物；不要求 gh 登录，不查询远端 Release。 |
| 构建并发布 | 本地校验通过后再鉴权、生成必要远端信息并上传。 |
| 跳过构建后发布 | 除发布检查外，还必须通过第 5.3 节复用验证。 |
| 只更新说明 | 不生成或修改外观产物；收到外观覆盖参数应明确拒绝。 |

冲突模式必须在任何编译或远端写操作前失败，例如 `NotesOnly + BuildOnly`、`NotesOnly + 外观参数`、未给记录却要求 `SkipBuild`；`DryRun` 永远不编译、不上传，向导 `--yes` 也不能绕过校验或改变发布模式。

只构建模式保留本地 Git 信息，但不能为了查找上个 Release 强制联网。其 manifest 中的远端 URL 只能明确标注为拟发布地址，不得打印为已可下载；也可将其作为未发布的本地候选清单处理。

## 7. 安装器联动

`program_name` 显式覆盖时，同步 `installer.executable=<program_name>.exe`。`display_name` 显式覆盖时同步安装界面、开始菜单和桌面快捷方式名称。无覆盖时保留原有独立设置。[R3]

图标分层处理：主 EXE 通过 PyInstaller 嵌入；安装器和卸载程序自身图标通过 `SetupIconFile`；系统卸载列表继续以 `UninstallDisplayIcon` 指向实际主 EXE。快捷方式目标也必须指向同一实际 EXE。[E1][E4]

生成 Inno 脚本时，用户输入必须做字段类型对应的转义与控制字符校验。特别区分可信配置中的 `{app}`、`{localappdata}` 常量和用户名称中的字面花括号，不能只处理引号或对所有字段做同一替换。[E5]

不随显示名称改变 AppId 和默认安装目录。对于同 AppId 的旧版升级，还要验证旧快捷方式与旧 EXE 的处理，不能以全目录清空作为清理策略，不得删除用户数据。实际不支持的升级组合明确列为受限，不以全新安装通过替代升级通过。

保留现有 Emo Master 自检，不为通过新功能测试而删除或跳过自检。现有 `--self-test` 和 `.emo_master` 约定不是通用应用标准；训练平台安装器及通用自检配置化另列后续任务。安装/卸载测试在专用 Windows 测试环境执行。

## 8. 发布向导与本地预设

在两个现有目标向导复用的 `release_wizard_common.py` 中增加外观步骤，不复制两个几乎相同的向导实现。

拟议交互：

```text
构建模式：只构建，不发布
外观配置：使用默认 / 本次自定义 / 选择预设

程序文件名，不含 .exe：VisionWorkshop
显示名称：视觉工坊
图标路径：assets/icons/vision-workshop.ico

保存为本地预设：否
```

执行前展示目标配置、源码提交、程序 EXE、显示名称、主图标、安装器图标、安装包是否启用、实际输出目录、发布仓库与 tag、是否会上传、更新兼容状态，以及窗口外观是否已由应用支持。

当前向导本地状态加载函数只保留字符串值，不应直接塞入嵌套预设后假设可以持久化。[R4] 建议新建 `.build-branding.local.json`，使用带版本号的结构，按 target 保存多个命名预设；原向导的源码路径与仓库状态文件继续保留原格式。

预设只有用户显式保存才写入，并以原子写入方式避免中断损坏；损坏时给出可恢复提示。新文件加入 `.gitignore`。恢复默认只清除本次覆盖，不删除用户保存的其他预设。

第一版使用路径输入，不引入 Tk/Qt 文件选择依赖。图标文件本身由用户提供，示例文件名不代表仓库已包含对应资源。

## 9. GitHub Actions

`workflow_dispatch` 和 `workflow_call` 都接入 `program_name`、`display_name`、`icon_path`。归档模板继续可通过目标配置设置，不为第一版把表单扩展成大型配置界面。

新增输入通过环境变量、参数列表传递给解析器，不把原始输入直接插入 PowerShell 脚本正文，也不使用 `Invoke-Expression`。CI 的图标必须存在于当前 checkout 的仓库目录，不能使用开发机上的 `D:\...` 路径；源码仓库图标在源码 checkout 后验证。

当前 workflow 固定 checkout `master`，会导致从新分支测试工作流却实际执行 master 中的打包脚本。[R5] 应区分两种调用：

- 在打包仓库手动执行：使用本次工作流所选的打包仓库提交，并记录 SHA。
- 跨仓库可复用调用：增加 `packager_ref` 输入，推荐调用方固定打包仓库提交；不能无条件使用调用方的 `github.sha`，它可能属于源码仓库。兼容旧调用时可保留已声明的默认行为，但验收应使用明确固定版本。

源码 `source_ref` 留空时按目标仓库默认分支解析，并记录最终 SHA；明确传入但不存在的 ref 必须失败，不得悄悄回退到其他分支。

手动构建建议将 `publish_release` 默认改为 false，并在文档明确这项安全性变化；可复用入口现有 false 默认保持。自定义 EXE 改名的发布门禁与本地脚本完全一致。

自动上传范围只包含可公开产物和脱敏摘要，不包含最终完整配置、本地预设或含绝对路径的完整记录。CI 日志展示实际 packager/source SHA，防止检查了一个版本却构建另一个版本。

## 10. 目标程序运行时外观：独立适配，不混入本次自动修改

本仓库的职责是构建外部应用；仓库指南也明确不在此处修改被引用应用源码。[R6] 本次计划不对外部项目做全局字符串替换、源码补丁注入或 Qt 方法 monkey patch。

后续可由目标应用显式支持一个小型运行时外观配置，例如：

```json
{
  "schema_version": 1,
  "display_name": "视觉工坊",
  "window_icon": "branding/app.ico"
}
```

打包器仅在目标已声明支持该契约时，将经过验证的配置和图标加入资源。应用负责读取配置并设置窗口标题、应用图标、主窗口图标和需要修改的关于界面文字。资源定位应兼顾源码运行和 PyInstaller 打包路径。[E6]

不能仅在构建机设置环境变量就认为离线分发后也会生效；也不能在程序尚不读取此文件时宣称运行时改名已实现。未声明支持的目标应在确认页显示“仅修改打包/安装外观，窗口标题未适配”。没有启用安装器、也未声明运行时外观支持的目标，仅设置 `display_name` 不会改变用户可见界面；必须提示该字段本次没有可见应用位置，不能把它当成窗口改名已交付。

训练平台的更新迁移和运行时外观适配，需要在其源码仓库独立计划、测试和提交。本次不得顺带修改 X-AnyLabeling 或其他子模块指针。

## 11. 分阶段任务与提交顺序

| 阶段 | 主要修改 | 完成门槛 | 建议独立提交主题 |
|---|---|---|---|
| M0：基线与测试骨架 | 核对最新代码；新增轻量 fixture、配置/命令基线测试 | 原两个目标在模拟路径与依赖下的命令语义固定；测试不需 Torch 或私有源码 | `test: add packager configuration baselines` |
| M1：解析核心与基础构建 | `build_config.py`、解析 CLI、`build.py` 接入、字段校验、输出上下文、构建记录 | 默认配置兼容；自定义名/图标可预览；无重复解析；坏输入提前失败 | `feat: add validated per-build branding overrides` |
| M2：发布链路和兼容门禁 | 发布脚本统一最终配置；模式分离；SkipBuild 检查；改名发布拦截 | 只构建不联网；不同配置不能复用；更新器改名风险可明确阻断 | `feat: unify release configuration and guard renamed builds` |
| M3：安装器、向导、预设 | Inno 图标与字段同步；预设与确认页；两个向导共用 | 安装目标匹配实际 EXE；原自检保留；默认/临时/预设可切换 | `feat: expose branding in installers and release wizards` |
| M4：Actions 接入 | 两个工作流入口；packager/source ref；测试工作流与上传白名单 | 新分支真正使用新脚本；不默认发布；本地和 CI 使用同一规则 | `feat: support branding overrides in GitHub Actions` |
| M5：Windows 验收与文档 | 轻量真实打包/安装、两个真实目标、适用升级场景、操作文档 | 实测有日志与产物；未验证项如实记录；不执行生产发布 | `test: add Windows branding acceptance coverage and docs` |

M0–M2 形成安全构建核心；M3–M5 完成完整功能。未通过相应验收，不把后面的体验入口视为功能已交付。本次计划文档放在 `docs/build-branding-plan-20260908`；后续实现可从包含本计划的提交创建 `feat/build-branding-overrides`，不要直接修改默认分支。

不把所有改动合成一个无法独立回退的大提交。每个阶段先补测试再改业务代码；按 `AGENTS.md` 的类型标注、命名与注释要求编写新增代码，不顺带全仓格式化。

## 12. 验收矩阵

| 类别 | 用例 | 预期结果 |
|---|---|---|
| 默认兼容 | 原两个 JSON 不增加覆盖项 | 名称、依赖、控制台、资源、更新器和安装身份保持原语义。 |
| 名称 | 英文、中文、空格、大小写 | 合法值完整保留；EXE/目录/安装目标一致。 |
| 非法名称 | 路径、`..`、设备名、控制字符、尾随点、带 `.exe` | 编译前失败，错误明确指出字段。 |
| 任务冲突 | 主程序名与 updater 名相同或仅大小写不同 | 拒绝，不能覆盖另一任务产物。 |
| 图标 | 有效 ICO、中文路径、路径含空格、多尺寸 | 正确传参；真实 EXE/安装器资源检查与界面观察符合预期。 |
| 图标失败 | 文件缺失、目录、伪 ICO、损坏图像目录 | 提前失败，不能静默使用默认图标。 |
| 路径 | 从不同工作目录调用、配置放入临时目录 | 新覆盖路径基准明确；下游不按临时目录重新解析。 |
| 优先级 | 原配置、预设、显式覆盖并存 | 只有一种确定结果；默认不偷偷加载预设。 |
| 恢复 | 先自定义构建，再使用默认配置 | 原 JSON 未变；默认产物不继承上次外观。 |
| 参数冲突 | `extra_args` 再次指定受管参数 | 自定义模式拒绝歧义，不依赖参数顺序。 |
| 输出复用 | 图标同路径内容变化、配置变化、修改过的 dist、源码 dirty | SkipBuild 拒绝并说明重建原因。 |
| 单文件边界 | build.py 单文件原有用法及不支持的 updater/发布组合 | 原能力保留；不支持组合提前失败，不做假兼容。 |
| 安装 | 全新安装、运行、自检、卸载 | 名称/目标/图标正确，原应用自检通过，测试标记与临时产物清理。 |
| 安装升级 | 同 AppId 旧版升级为自定义显示名版 | 用户数据保留；快捷方式处理明确；不能只验证全新安装。 |
| 更新改名 | updater 目标旧 EXE 名与新包不一致 | 发布原通道被拦截；不能用新 manifest 字段假装已修复旧客户端。 |
| 更新同名 | 保持 EXE 名，仅替换图标等外观 | 发布检查通过后仍需真实升级/重启验收。 |
| 模式 | 离线且没有 gh 登录时只构建/预览 | 不访问 GitHub；正确生成本地产物或预览，不上传。 |
| 说明模式 | NotesOnly 携带外观参数 | 明确拒绝，不误报外观已变化。 |
| CI | 手动选择新分支、跨仓库复用固定 ref | 实际构建脚本 SHA 与预期一致。 |
| 注入与泄露 | 名称包含特殊字符；摘要/上传目录检查 | 参数不作为脚本执行；不泄露 token、完整环境或本机私有路径。 |
| 应用边界 | 目标未支持运行时外观配置 | 明确提示窗口标题/图标未接入，不宣称界面已改名。 |

测试组织建议：使用标准库 `unittest` 建立不依赖深度学习环境的配置单元测试；PowerShell 参数和生成 Inno 脚本通过测试入口检查。另建轻量 Windows fixture，执行真实 PyInstaller 构建，再执行现有安装目标等价的安装/卸载冒烟测试。视觉效果与自动更新的端到端测试单独记录。

最小程序通过不代表训练平台的 Torch、Qt、ONNX 等真实依赖已验证。两个真实目标需各自记录构建结果；需要 GPU、私有源码或现场环境而未完成的测试必须标为未验证，不能用 dry-run 代替。

## 13. 预计文件改动范围

| 文件/目录 | 改动 |
|---|---|
| `build_config.py` | 新增公共解析与校验模块。 |
| `scripts/resolve_build_config.py` | 新增解析 CLI。 |
| `build.py` | 接入覆盖、构建上下文与记录；保留已有依赖收集逻辑。 |
| `scripts/publish-local-release.ps1` | 生效配置、模式分离、复用校验、发布门禁。 |
| `scripts/build-windows-installer.ps1` | 读取生效配置；SetupIconFile；名称同步与转义。 |
| `scripts/release_wizard_common.py` | 外观选择、预设、模式优先选择、确认摘要。 |
| 两个 `scripts/release_wizard_*.py` 包装入口 | 尽量维持薄入口，仅必要兼容调整。 |
| `.github/workflows/release-windows.yml` | 输入、打包器 ref、源码 ref、默认不发布与摘要。 |
| `.github/workflows/test-packager.yml` | 新增无发布权限的测试工作流。 |
| `tests/`、`tests/fixtures/` | 单元、命令拼装、配置冲突和轻量真实构建用例。 |
| `.gitignore` | 忽略本地预设及私有构建记录，勿忽略正式测试 fixture。 |
| `README.md`、`docs/release-runbook.md`、`AGENTS.md` | 新参数、兼容限制、测试命令、恢复默认与示例。 |
| `docs/plans/2026-09-08-packaging-branding-improvement-plan.md` | 本计划。 |

不要求把两个现有生产配置的默认名称或图标改掉。不自动新增训练平台安装器，不修改外部应用源码，不提交 build/dist 二进制或个人图标绝对路径。

## 14. 计划接口使用示例

以下命令是功能实施后的目标接口，**当前脚本尚不能直接使用新增参数**。路径与名字仅为示例，图标需由使用者提供。

```powershell
# 构建验证用：不上传 Release。
# 此例修改了训练平台 EXE 名称，不能据此认定自动更新已兼容。
.\scripts\publish-local-release.ps1 `
  -Target "emo-vision-train" `
  -SourceRoot "D:\Projects\emo-vision-train" `
  -ReleaseTag "v1.2.3" `
  -ProgramName "VisionWorkshop" `
  -DisplayName "视觉工坊" `
  -IconPath "assets/icons/vision-workshop.ico" `
  -BuildOnly
```

```powershell
# 取消所有覆盖，使用目标原始名称与图标。
.\scripts\publish-local-release.ps1 `
  -Target "emo-vision-train" `
  -SourceRoot "D:\Projects\emo-vision-train" `
  -ReleaseTag "v1.2.3" `
  -BuildOnly
```

不使用新参数不意味着忽略安全检查：SkipBuild 的匹配检查、非法配置检查仍应执行。版本号校验等既有规则不得为通过示例而取消。

## 15. 后续独立任务（不阻塞本期核心）

P2 可包括 PNG 转 ICO、图标预览、EXE 版本资源中的产品名称和文件说明、受支持目标的运行时外观接入、通用安装自检契约、正式跨 EXE 名迁移与独立更新通道。以上应各自有范围和验收，不在本期顺带实现。

本期不做跨平台打包、新打包引擎、代码签名体系迁移、依赖全面升级、新 GUI、源码包名重构或自动修改第三方子模块。

## 16. 交付定义与回退

功能完成必须同时具备：默认配置回归通过、覆盖结果一致、非法输入提前失败、默认与自定义产物隔离、危险复用与改名发布可拦截、Windows 实际构建证据、安装目标验收记录、文档与测试命令。

恢复默认操作为取消本次覆盖或选择默认配置。代码回退按 M0–M5 独立提交进行，不需要恢复被篡改的源码或生产 JSON，因为这些文件从设计上不应被临时外观修改。

若错误产物已发布到更新通道，简单恢复打包配置并不足以撤销已下载的包；需要独立评估发布撤回与恢复包方案。因此本计划把不兼容发布阻断安排在上传之前。


## 17. 实施清单与执行记录

以下均为待办，不因计划入库而标为完成。每个阶段完成后，在该阶段提交或 PR 中记录测试命令、退出码、关键日志和未验证项。

### M0：固定基线

- [ ] 重新核对 `AGENTS.md`、两个目标配置和相关脚本，记录实际 packager/source SHA。
- [ ] 新增 `tests/test_build_config_baseline.py` 与轻量 fixture；保护现有名称、依赖、资源、控制台和 updater 参数。
- [ ] 用 mock 替代 GitHub、PyInstaller、深度学习依赖和私有源码，不在单元测试阶段真实发布。

### M1：解析与构建

- [ ] 实现唯一配置解析核心及薄 CLI；用例覆盖优先级、字面量、临时配置路径和 Windows 名称规则。
- [ ] 实现主图标/安装器图标的确定性继承、损坏 ICO 检查和 `extra_args` 冲突检查。
- [ ] 接入隔离输出、各 job 的 work/spec 目录和 updater 最终目标碰撞检查。
- [ ] 仅在成功构建后写有效记录，记录输入与产物摘要；原 JSON 文件哈希不变。

### M2：发布安全

- [ ] 发布与安装入口只消费最终配置，不重新读取原始 JSON 覆盖结果。
- [ ] 预览、只构建、构建发布、复用发布、只改说明的职责和非法组合有自动化测试。
- [ ] `SkipBuild` 显式选择记录；配置、图标、源码或产物不匹配时要求重建。
- [ ] 改 EXE 名且更新兼容未知时阻断发布；换仓库/tag/manifest 名不绕过检查。
- [ ] 旧 manifest 字段保持兼容；公开摘要不包含凭据、用户目录或完整本地配置。

### M3：安装器和向导

- [ ] 接入 `SetupIconFile`，同步安装与快捷方式字段，保持 AppId 与默认安装目录。
- [ ] 两个向导共用外观步骤；显式保存/选择预设；取消操作不写原始配置。
- [ ] 确认页标出真实生效位置、上传行为和运行时未支持项；保留原 Emo Master 自检。

### M4：CI

- [ ] 手动和可复用入口统一接入外观参数；明确打包仓库版本与源码 ref 的选择。
- [ ] 通过环境变量和参数列表传递输入，不使用脚本字符串求值；不改无关依赖版本。
- [ ] 新建最小权限测试工作流，验证新分支真正执行新脚本；上传仅用公开文件白名单。

### M5：验收和文档

- [ ] Windows fixture 实际构建：默认、英文改名、中文/空格名称、替换图标、恢复默认。
- [ ] 原两个目标真实构建；既有安装目标安装、运行、自检、卸载及适用的同 AppId 升级。
- [ ] 对有更新器的目标区分“发布门禁测试”和“真实升级重启测试”，未实测不得宣称兼容。
- [ ] 更新 README、runbook、AGENTS；附可复现命令，所有命令注明是否上传。
- [ ] 编写验收记录，将通过、失败、未执行分别列出；功能未完成前不改本计划为已交付。

建议验收记录位置为 `docs/evidence/packaging-branding-acceptance.md`，本次不创建虚假的成功记录。记录至少包含日期、系统/解释器/工具版本、packager/source SHA、case ID、命令、退出码、产物摘要、失败原因与未验证项。禁止将凭据或构建机敏感路径加入公开记录。

### 后续执行说明

先读取本计划与 `AGENTS.md`，从 M0 开始。M0 通过后完成 M1，再进入发布、安装器和向导；不要只加输入框就跳到真实发布。每个阶段独立提交，不全仓格式化、不修改外部应用、不提交构建二进制、不运行生产 Release 上传。应用运行时改名或更新协议变更必须另开目标应用任务。

本次授权范围是编写并提交计划文档，不代表已实施 M0–M5，也不代表已授权后续发布构建产物。

---

## 参考依据

### 仓库代码

下列路径除特别说明外均位于 `jsdfhasuh/python_build_scripts` 的核查提交 `ab4a33e586138fb381a87ae21cc83b5e8d79adbe`。

- **[R1]** `build.py`：`BuildJob`、`load_config()`、`expand_config_values()`、`validate_build_paths()`、`create_build_job()`、`append_common_args()`、`build_pyinstaller_command()`、`copy_updater_to_app_dir()`、`main()`。
- **[R2]** `scripts/publish-local-release.ps1`：配置载入、`Resolve-AssetNameTemplate`、SourceRef/Release notes 处理、SkipBuild、dist 查找、安装器调用、manifest、BuildOnly 和上传分支。
- **[R3]** `scripts/build-windows-installer.ps1`：`ConvertTo-InnoLiteral`、`New-InnoScript`、`Assert-SelfTest`、`Invoke-InstallerSmokeTest`、入口配置与主 EXE 校验。
- **[R4]** `scripts/release_wizard_common.py`：`loadLocalState()`、`saveLocalState()`、`buildPublishCommand()`、`printSummary()`、`main()`。
- **[R5]** `.github/workflows/release-windows.yml`：手动/复用输入、固定 master checkout、旧 source_ref 默认、源码 checkout、构建与上传步骤。
- **[R6]** `AGENTS.md` 与该提交的仓库树：项目职责、测试基线、代码与构建规范。
- **[R7]** `configs/emo-vision-train.json`、`configs/emo-master.json`：现有主程序名、图标、updater、安装器与依赖配置。
- **[R8]** `jsdfhasuh/emo-vision-train@59352fd5a0f183693f3384940dd2d5923e317e15`：`auto_update.py` 中 EXE 名获取；`updater.py` 中 `find_payload_dir()`、`restart_app()`、`parse_args()`、`main()`。
- **[R9]** 同一训练平台提交的 `ui/ui_main.py`：`MainWindow.__init__()` 明确设置 `Training Platform` 窗口标题。

代码浏览基准：`https://github.com/jsdfhasuh/python_build_scripts/tree/ab4a33e586138fb381a87ae21cc83b5e8d79adbe`。

### 官方资料（2026-09-08 查阅）

- **[E1]** PyInstaller 使用说明：名称、图标参数及其作用。`https://pyinstaller.org/en/stable/usage.html`
- **[E2]** Inno Setup AppId 与同一应用识别。`https://jrsoftware.org/ishelp/topic_setup_appid.htm`
- **[E3]** Microsoft Windows 文件与路径命名规则。`https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file`
- **[E4]** Inno Setup SetupIconFile 与推荐尺寸。`https://jrsoftware.org/ishelp/topic_setup_setupiconfile.htm`
- **[E5]** Inno Setup 常量与字面花括号处理。`https://jrsoftware.org/ishelp/topic_consts.htm`
- **[E6]** PyInstaller 运行时路径。`https://pyinstaller.org/en/stable/runtime-information.html`

本文件的参数、文件布局、门禁和阶段安排属于拟议设计；参考代码中已有的能力与本计划将新增的能力，应始终区分。
