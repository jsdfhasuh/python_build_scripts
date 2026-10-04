# VisionWorkshop 便携 ZIP 打包改进计划：程序名称与图标

**打包仓库：** `jsdfhasuh/python_build_scripts`  
**主要对象：** VisionWorkshop，基于现有 `emo-vision-train` 构建目标  
**更新日期：** 2026-09-08  
**版本：** v1.2，替代 v1.1 的多项目及安装器实施范围  
**计划分支：** `docs/build-branding-plan-20260908`  
**文档路径：** `docs/plans/2026-09-08-packaging-branding-improvement-plan.md`  
**状态：** 计划修订；M0–M5 均待实施，本次不修改功能代码、不构建、不发布 Release。

## 1. 本次修订的结论

本次主要改进 **VisionWorkshop 的名称、图标和 ZIP 打包流程**，继续采用：

```text
下载 ZIP → 解压整个文件夹 → 双击 VisionWorkshop.exe
```

不新增安装向导，不生成 setup.exe，不改变“解压即用”的使用方式。此前计划把另一个目标的安装器联动也列为必做项，范围过大；本版本删除这部分实施任务和安装、卸载验收要求。

保留现有 PyInstaller 打包能力，只补齐名称与图标的配置入口，以及 EXE、包内目录、ZIP、发布步骤使用同一配置的一致性。不要为了这个需求重写整个打包系统。

### 1.1 相比 v1.1 的范围变更

| 项目 | v1.2 决定 |
|---|---|
| 主要交付对象 | 聚焦 VisionWorkshop，不再要求同时为所有目标开发外观功能。 |
| 产物形式 | 目录式程序加 ZIP；不新增安装版和单文件主程序。 |
| 主程序名 | VisionWorkshop.exe 是明确的验收目标，不以只改 ZIP 名称代替 EXE 改名。 |
| 安装器相关任务 | 删除安装名称、安装器图标、快捷方式、AppId、安装目录及安装/卸载测试任务。 |
| 其他项目 | 保持 emo-master 原有配置和行为，只检查共享代码的兼容性，不扩展其功能。 |
| 显示名称参数 | 不作为本期必填或主交付项；未适配窗口代码时不能宣称界面已改名。 |
| 自动更新检查 | 保留；它是便携版更新兼容性问题，不是安装器需求。 |
| 本地多预设系统 | 降为后续可选功能；先做一个显式选择的 VisionWorkshop 配置档。 |

## 2. 项目对应关系与核查依据

### 2.1 不将对外名称误当作仓库迁移

| 概念 | 本次采用的值 |
|---|---|
| 对外程序名称 | `VisionWorkshop` |
| 已有构建目标 | `emo-vision-train` |
| 已有目标配置 | `configs/emo-vision-train.json` |
| 当前配置中的源码仓库 | `jsdfhasuh/emo-vision-train` |
| 当前配置中的发布仓库 | `jsdfhasuh/emo-vision-train-release` |
| 本次自定义 EXE | `VisionWorkshop.exe` |
| ZIP 内唯一应用根目录 | `VisionWorkshop/` |
| VisionWorkshop 配置档的 ZIP 名称模板 | `VisionWorkshop-windows-${RELEASE_TAG}.zip` |

“主要改 VisionWorkshop”在本计划中表示为现有训练平台生成这一名称的便携版本，不代表已经存在新仓库，也不表示需要重命名 GitHub 仓库、Python 包或构建目标。

### 2.2 代码基线

2026-09-08 重新确认的打包仓库 `master` 为 `ab4a33e586138fb381a87ae21cc83b5e8d79adbe`。本次修订前的文档提交为 `d3e00305cd9613c9d959a736391e15570404a6a9`。

| 已核查内容 | 对本计划的影响 |
|---|---|
| `build.py` 已通过 `name`、`icon` 传给 PyInstaller。[R1] | 复用现有机制，不先打包旧 EXE 再手工改名。 |
| 训练平台配置为 `onefile: false`，ZIP 资产名，启用了 updater，没有启用安装器。[R2] | 保留目录式、解压即用的产物结构和 updater。 |
| 发布脚本按 `config.name` 查找 dist，另行读取 JSON 并生成 ZIP 与 manifest。[R3] | 名称覆盖必须贯穿构建、归档和发布，不能只改变 build.py 内存中的值。 |
| 向导没有名称、图标输入，并在较早阶段检查 gh 登录。[R4] | 为 VisionWorkshop 增加入口；预览和仅构建路径不应要求发布账户。 |
| Actions 固定检出打包仓库 master。[R5] | 新分支验收要确认实际执行的脚本 SHA，不能误测旧脚本。 |
| 仓库指南未定义自动化测试，也限制在打包仓库直接修改外部应用。[R6] | 增加轻量测试；目标程序的运行时外观、更新协议修改单独处理。 |

更新兼容性参考前次静态核查的 `jsdfhasuh/emo-vision-train@59352fd5a0f183693f3384940dd2d5923e317e15`。实施前必须重新核对目标源码的实际提交，不能将该历史检查当成最新版本的实测结论。[R7]

## 3. 明确的交付范围

### 3.1 第一版必须完成

实现 VisionWorkshop 主程序文件名、EXE 图标、包内目录名和 ZIP 文件名的统一配置；支持通过命令行和现有训练平台发布向导使用，并接入现有 Windows Actions。原始目标配置保留，取消覆盖即可恢复原名称和图标。

主程序仍然采用目录式打包，依赖和资源随整个目录压缩。自定义产物与默认产物分开，失败时不拿上次 dist 冒充新结果。预览和仅构建不上传，真实发布必须显式选择并经过更新兼容检查。

### 3.2 本期明确不做

不修改 `scripts/build-windows-installer.ps1`，不修改 `configs/emo-master.json`，不为 VisionWorkshop 加 `installer` 配置，不新增桌面或开始菜单快捷方式，不实现安装、卸载及安装升级逻辑。也不要求完成另一个项目的整套真实构建或安装验收才交付 VisionWorkshop。

不重写依赖收集，不升级 Python、Torch、CUDA、ONNX Runtime 或 PyInstaller 版本，不改变控制台开关、压缩算法和运行时 hook 行为。不切换为 onefile 主程序，不引入新的图形界面框架，不做 PNG/SVG 自动转 ICO。

不在打包脚本中全局替换应用字符串、打补丁修改 Qt 方法、重命名 Python 包、改变用户数据目录或修改第三方子模块。没有实际读取外观文件的应用，不因为 ZIP 中放入一个 JSON 就自动获得新窗口标题。

### 3.3 更新助手与安装器的区别

原配置的 `updater.exe` 保持原文件名和调用方式。它是程序收到更新包后用于替换目录和重启的助手，不是要求用户首次安装软件的 setup 程序。[R2][R7]

本期保留 updater 不等于增加安装器；去掉安装器任务也不等于可以忽略 EXE 改名后的更新风险。

## 4. 目标产物与成功标准

```text
VisionWorkshop-windows-v1.2.3.zip
└─ VisionWorkshop/
   ├─ VisionWorkshop.exe
   ├─ updater.exe
   ├─ _internal/
   └─ 其他原有运行依赖与资源
```

版本号仅为示例。具体依赖布局以原构建配置及所用 PyInstaller 的实际输出为准，不手动移动 DLL 或删减资源。

ZIP 内只包含一个完整的 `VisionWorkshop/` 应用根目录，不夹带默认旧程序目录、构建工作目录、源码仓库、私有配置或额外 setup 产物。不能把绝对路径、`dist/branding/...` 等构建机目录层级写进 ZIP。

用户无需预先安装 Python，也不经过新增安装向导；以 Windows 测试环境的实际启动结果验收。程序本身已有的驱动、硬件、网络等要求继续保留，不能把“解压即用”误写成“无需任何运行条件”。

EXE 文件图标和窗口运行时图标分开记录验收。第一版必须验证 EXE 中的新图标资源；程序打开后的窗口标题、窗口图标若未适配，应明确标注，而非报为完成。

## 5. 配置入口设计

### 5.1 原目标配置不被临时覆盖写回

新增一个显式选用的配置档，建议位置为 `profiles/visionworkshop.json`。使用 profiles 目录而非向 configs 根目录增加完整目标，避免目标枚举将其误当成另一个独立项目。

拟议内容：

```json
{
  "schema_version": 1,
  "target": "emo-vision-train",
  "program_name": "VisionWorkshop",
  "icon_path": "${PACKAGER_ROOT}/assets/icons/visionworkshop.ico",
  "release_asset_name": "VisionWorkshop-windows-${RELEASE_TAG}.zip"
}
```

这是计划中的配置格式，并非当前已有功能。图标路径只是约定；本次没有新增图标文件。实施时须由用户提供或明确选择有效 ICO，未提供时提示缺失，不能伪造一个图标或默认为已完成图标验收。

配置档只承载允许的外观和归档字段。源码仓库、入口、依赖、更新地址及发布仓库仍来自原目标配置，不能借此注入任意构建或发布设置。配置档 target 与所选目标不匹配时直接失败。

普通默认构建不得自动读取这个配置档。共享代码对 emo-master 的无覆盖调用保持原行为；第一版不开放其安装目标的外观覆盖，收到不支持的组合应明确拒绝而不是部分生效。

### 5.2 一个解析核心

建议新增根目录 `build_config.py`，复用现有参数生成逻辑；另新增 `scripts/resolve_build_config.py` 作为 PowerShell 和 Actions 使用的薄入口。

```text
原始 configs/emo-vision-train.json
  → 显式选择的 VisionWorkshop 配置档
  → 本次显式覆盖参数
  → 校验、路径解析、输出目录计算
  → 一份最终生效配置
  → 主程序与 updater 构建 → ZIP → 发布前检查
```

优先级为“本次显式输入 > 显式选择的配置档 > 原始目标配置”。向导仅负责收集参数，不另写配置合并规则。下游统一读取最终配置，不在构建后重新加载原 JSON 导致名字回退。

### 5.3 拟新增参数与命名规则

| 功能 | build.py | PowerShell 发布入口 |
|---|---|---|
| 选择配置档 | `--branding-profile` | `-BrandingProfile` |
| 覆盖 EXE 名称 | `--program-name` | `-ProgramName` |
| 覆盖 EXE 图标 | `--icon-path` | `-IconPath` |
| ZIP 名称模板 | 不负责归档 | `-ReleaseAssetName` |
| 预览 | 沿用 `--dry-run` | 新增 `-DryRun` |
| 仅构建 ZIP | 不负责归档 | 沿用 `-BuildOnly` |

顶层 `name` 控制 EXE 和 ZIP 内的应用目录，不再提供一个独立的包内目录改名参数。ZIP 外部文件名由 `release_asset_name` 独立控制；VisionWorkshop 配置档显式给出上面的名称模板，不能让“只改显示文字”静默改变下载地址。

本期不新增 DisplayName、SetupIconPath、SetupAssetName 等安装或无可见作用的输入。恢复默认是取消配置档及本次覆盖，不是删除原始配置或图标。

### 5.4 路径和有效性检查

新图标覆盖的相对路径统一以打包仓库根目录为基准；支持明确的 `${PACKAGER_ROOT}` 和 `${SOURCE_ROOT}`，在最终配置中解析为绝对路径。配置档移入临时目录后不重新解释路径。旧配置的 entry、add_data、hook 及 extra_args 路径语义由兼容测试保护，不顺带迁移。

必需图标未找到、指向目录、变量未定义、ICO 格式损坏，应在正式编译前失败。不能只依据 .ico 扩展名判定有效；需检查文件结构，并通过真实图像解码或后续构建校验确认可用。多尺寸图标可给出建议，但不为了转换图片引入新的运行依赖。

程序名称允许合法中文、英文和空格；拒绝路径分隔符、控制字符、设备保留名、尾随点或空格，不接收自带 .exe 的程序名。与 updater 任务名及最终 `updater.exe` 做不区分大小写的冲突检查，避免复制覆盖主程序。

ZIP 和 manifest 名称必须是安全的单个文件名，不允许目录穿越，且不得互相覆盖。外观字段作为字面量处理，不做 shell 求值，不重复展开为环境变量。纯 EXE 预览不强制要求 RELEASE_TAG；ZIP 构建阶段再完整校验资产模板。

自定义模式下，extra_args 再指定名称、图标、输出目录或与目录式主程序冲突的选项时，应拒绝歧义；不依赖“最后一个参数获胜”。不承诺修改手写 spec 文件，不支持的组合提前说明。

## 6. 构建与 ZIP 链路

### 6.1 保留已有构建逻辑

通过现有 PyInstaller 参数真正生成 `VisionWorkshop.exe` 及其图标。保留原依赖、资源、Torch/ONNX hook、Conda DLL 和 updater 构建逻辑。不能在旧包上手动改文件名后就宣布支持了改名构建。

让构建任务及 `copy_updater_to_app_dir()` 接收明确的输出上下文。主程序、updater 的 work/spec 输出应隔离；最终只将原有 updater 放入正确的应用目录。

### 6.2 自定义输出隔离

建议布局：

```text
build/branding/emo-vision-train/<build-id>/
  effective-config.json
  build-record.json
  work/<job>/
  spec/<job>/

dist/branding/emo-vision-train/<build-id>/
  VisionWorkshop/
    VisionWorkshop.exe
    updater.exe
    _internal/...

release-output/branding/emo-vision-train/<build-id>/
  VisionWorkshop-windows-<tag>.zip
  build-summary.json
```

正式发布所需的 manifest 应从同一个已校验 ZIP 生成。仅构建模式可保存未发布的本地候选清单，但不得把候选 URL 当成可下载链接，更不能让候选清单自动替换正式更新 manifest。

归档从应用目录的父目录执行，只把 `VisionWorkshop/` 打入 ZIP。继续使用当前压缩方式，不在本期修改压缩算法或资源大小策略；验收需实际解压并检查目录及文件完整性。

默认旧配置仍使用原输出约定。自定义失败不能回退选用旧 dist；不从全局 dist 下自动挑“最近生成”的目录。

### 6.3 防止复用错误产物

成功记录至少保存 target、程序名、有效配置摘要、图标内容哈希、源码与打包器提交、必要工具版本、产物目录及文件清单哈希。只有全部构建任务、资源检查和 updater 复制成功后才写入可复用状态。

自定义模式下使用 SkipBuild 时必须显式指定构建记录，例如新增 `-BuildRecordPath`；未提供或与当前请求不匹配时要求重建。图标在同一路径被替换、配置变化、源码变化、dist 被编辑、记录对应目录不存在，均不能复用。

对于源码有未提交修改且没有可靠输入快照的情况，允许普通本地重建，但不允许直接复用旧记录。构建过程中输入变化也应使记录失效。build-id、时间戳及隔离路径不参与语义配置指纹，避免相同配置永远无法匹配。

本期只为新的自定义产物建立这套证明，不借此重构所有目标的缓存系统。原目标的无覆盖行为用回归测试保护。完整配置和私有记录留在本地，不进入公开 ZIP 或默认上传目录。

## 7. 便携版自动更新兼容检查

### 7.1 不删掉用户要的 EXE 改名能力

本期必须能构建 `VisionWorkshop.exe`，不能以“保留旧 EXE 名称更安全”为由替代需求。同时要区分三个状态：名称与图标构建成功、Windows 解压运行通过、自动更新兼容通过。三者不能相互代替。

前次核查的应用会把当前 EXE 文件名传给 updater，并在目录替换后继续按该名称重启。旧版为 `emo-vision-train.exe`、新包只有 `VisionWorkshop.exe` 时存在跨名称重启失败风险。这是静态分析结果，不是已经完成的 Windows 升级复现。[R7]

### 7.2 本仓库的处理边界

对于 EXE 改名、更新兼容尚未验证的 VisionWorkshop 包，默认仅构建并明确标记 `update_compatibility: unverified`，不得作为已验证更新包上传到原客户端使用的自动更新通道。

不能用修改发布仓库、tag、manifest 名或增加一个新 JSON 字段来假装旧客户端已经理解新的启动名称。也不提供一个忽略检查的通用强制发布开关。

**仅构建不等于程序运行时已经关闭自动更新。** 打包器不能只移除 updater、只取消上传或设置构建机环境变量，就宣称分发后的程序不会访问旧更新通道。Windows 启动测试应在可控环境进行，避免从生产通道自动安装不匹配的包。

正式对外分发前，须确认目标应用实际支持的更新策略：沿用同名 VisionWorkshop 更新包，或者通过应用已支持并验证的方式关闭/隔离更新，或者另行完成跨 EXE 名迁移。该选择在目标应用任务中明确实现和验收；本次计划提交不授权修改外部源码。

旧名到新名、新名到下一版新名、新名恢复旧名的自动更新均不能默认视为兼容。恢复默认打包配置只恢复今后产物，不自动完成用户已部署版本的迁移。

### 7.3 不改变原更新清单契约

若经过兼容验证后发布，保留原 manifest 中客户端使用的 version、url、sha256、mandatory、notes 等字段及含义。[R3] ZIP 的 URL、大小、哈希和名称都来自实际产物，不能引用旧压缩包。

本期不要求用户安装软件，不将 ZIP 更新改成运行 setup 的流程；不把 updater 协议重写混入名称和图标功能。

## 8. 训练平台发布向导与执行模式

优先改进现有 `scripts/release_wizard_emo_vision_train.py` 对应的流程，界面可显示“VisionWorkshop / 训练平台便携打包”，内部 target 仍为 emo-vision-train。

```text
执行模式：只构建 ZIP，不发布
外观：原始默认 / VisionWorkshop 配置档 / 本次自定义
程序文件名：VisionWorkshop
图标：assets/icons/visionworkshop.ico
ZIP 文件名：VisionWorkshop-windows-v1.2.3.zip
分发形式：ZIP，解压整个目录后运行
运行时窗口外观：未适配时明确提示
自动更新兼容：未验证时明确提示
```

最终确认页展示真实 EXE、应用根目录、ZIP 名、图标、输出位置、源码和打包器提交、是否会上传，以及更新兼容结论。不显示安装器、安装目录、快捷方式或卸载选项。

共享代码可放在 release_wizard_common.py，但不能让 emo-master 被迫选 VisionWorkshop 配置档或进入新的 ZIP 专用流程。第一版配置档需要显式选择，不自动记住上次临时外观；多本地预设、文件选择器和图标预览后续再做。

| 模式 | 要求 |
|---|---|
| 预览 | 解析、校验、显示结果；不运行 PyInstaller，不上传，不改原始配置。 |
| 仅构建 | 构建程序与 ZIP；不要求 gh 登录，不查询远端 Release；本地源码依赖应已准备好。 |
| 构建并发布 | 显式选择后才鉴权，经过产物与更新检查再上传。 |
| 复用后发布 | 除发布检查外必须校验指定构建记录，不猜测旧目录。 |
| 只改 Release 说明 | 不处理外观构建；带外观覆盖参数时明确拒绝，不能误报外观已改。 |

VisionWorkshop 的自定义流程默认仅构建，不借此改变其他项目原有的发布默认值。DryRun 优先保证无构建和上传；非法模式组合必须在任何外部写操作之前失败，--yes 不得绕过检查。

## 9. GitHub Actions 接入

手动运行与可复用入口均支持显式选择仓库中的 branding_profile；优先复用同一个 VisionWorkshop 配置档，不为第一版复制大量参数和第二套默认值。临时值需要覆盖时仍由公共解析器处理，不在 YAML 里重新拼配置。

配置档和 ICO 必须能在 runner 已检出的仓库中找到；不得填写开发机的 D:\ 路径，也不增加任意 URL 下载图标功能。源码仓库中的资源须在源码检出后校验。

检查 checkout 打包仓库的 ref：在本仓库手动运行时使用所选的打包器版本；跨仓库复用时显式传递或固定 packager_ref，不把调用方源码仓库的 github.sha 当作打包器 SHA。[R5] 记录实际 packager/source SHA。

VisionWorkshop 验收明确选择有效的源码分支或提交；不存在的 source_ref 直接失败，不默默回退。不要为修复本目标顺便升级 Actions 或依赖版本。

自定义构建默认不发布，上传 Release 仍受第 7 节约束。Actions artifact 只包含预期 ZIP、脱敏摘要和经过策略允许的清单；上传 artifact 不得被描述成已经发布到客户端更新通道。

输入通过环境变量和参数列表传递，不直接拼进可执行脚本字符串，不使用 Invoke-Expression。测试 workflow 使用最小权限，不访问生产更新地址，不生成或上传发布包来完成单元测试。

## 10. 分阶段实施与文件范围

| 阶段 | 任务 | 完成门槛 |
|---|---|---|
| M0：基线 | 阅读最新代码与 AGENTS，新增轻量 fixture 和命令基线测试。 | 固定训练平台默认参数；emo-master 无覆盖共享路径不变；测试不需私有源码或深度学习依赖。 |
| M1：名称与图标 | 公共配置解析、VisionWorkshop 配置档、EXE 和图标参数、校验、构建目录隔离。 | 实际生成 VisionWorkshop 名称的命令；错误图标和名称提前失败；原 JSON 未变。 |
| M2：便携 ZIP | 发布脚本统一配置、准确归档、记录与复用检查、仅构建模式、更新发布检查。 | ZIP 名、唯一应用根目录、EXE 一致；不混旧包，不自动发布。 |
| M3：训练平台向导 | 暴露默认/配置档/本次覆盖与清晰确认页。 | 一次输入贯穿整个流程；没有安装器选项；其他向导无覆盖调用不受影响。 |
| M4：Actions | 接入配置档与正确的 packager/source ref，补测试工作流。 | 新分支确实执行新脚本；本地和 CI 同一配置；不默认发布自定义包。 |
| M5：Windows ZIP 验收 | 真实打包、解压、运行、EXE 图标检查、恢复默认及文档。 | 有 VisionWorkshop 的真实产物与结果；更新兼容按实际状态单列，不拿 dry-run 代替运行。 |

建议每阶段独立提交。从 M0、M1 开始，再完成 ZIP 和向导；本期不存在“安装器阶段”。后续实现可从包含 v1.2 文档的提交建立 `feat/visionworkshop-portable-branding`，不直接修改默认分支。

| 文件 | 计划改动 |
|---|---|
| `build_config.py` | 新增公共配置解析、校验和上下文。 |
| `scripts/resolve_build_config.py` | 新增供 PowerShell/CI 使用的薄入口。 |
| `profiles/visionworkshop.json` | 新增显式选择的配置档，不作为独立源码目标。 |
| `assets/icons/visionworkshop.ico` | 仅在获得实际图标后添加；本次不生成或上传占位图标。 |
| `build.py` | 接入名称与图标覆盖、输出上下文和成功记录。 |
| `scripts/publish-local-release.ps1` | 最终配置、ZIP 路径与名称、只构建模式、复用及发布检查。 |
| `scripts/release_wizard_common.py` | 共享薄逻辑；VisionWorkshop 专用入口按目标启用。 |
| `scripts/release_wizard_emo_vision_train.py` | 保留入口，展示 VisionWorkshop 便携打包流程。 |
| `.github/workflows/release-windows.yml` | 配置档、版本选择与 VisionWorkshop 发布限制。 |
| `tests/`、拟新增测试 workflow | 解析、命令、ZIP 结构、模式与共享回归测试。 |
| `README.md`、`docs/release-runbook.md`、`AGENTS.md` | 增补本目标用法、参数、测试命令和限制。 |
| `.gitignore` | 按需忽略私有上下文和记录，不忽略正式配置档或测试 fixture。 |

`configs/emo-vision-train.json` 的默认名称、图标、依赖和运行模式保持原样。若公共代码必须调整，先保证无覆盖的旧路径兼容；不是授权改写 `configs/emo-master.json` 或安装器脚本。

## 11. 验收矩阵

| 用例 | 预期结果 |
|---|---|
| 无配置档、无覆盖构建 | 继续使用原 emo-vision-train 名称和原资源配置。 |
| VisionWorkshop 配置档 | 生成 VisionWorkshop.exe、VisionWorkshop/、VisionWorkshop-windows-<tag>.zip。 |
| EXE 图标 | 实际 EXE 嵌入所选 ICO；不仅检查命令字符串。 |
| ZIP 解压 | 完整目录，无额外 dist 路径、旧 EXE、旧程序目录或 setup 产物。 |
| 普通用户运行 | 在没有预装 Python 的测试环境解压启动；记录实际已有运行条件。 |
| 中文及空格路径 | 图标、源码、输出和解压目录处理正确，不依赖 shell 手工拼接。 |
| 非法名称和 updater 冲突 | 编译前失败，不发生目录穿越或更新器覆盖主程序。 |
| 缺失或损坏图标 | 明确失败，不静默换回默认图标。 |
| 原始配置、配置档、显式覆盖 | 优先级确定；配置档 target 不符即失败；没有默认暗中加载。 |
| 临时配置文件 | 生成后路径不以临时文件夹重新解释。 |
| 构建失败或产物被改 | 不自动使用旧 dist；SkipBuild 要求指定且匹配的记录。 |
| 仅构建和预览 | 不要求 gh 登录，不访问远端 Release，不上传。 |
| 切回默认 | 不使用配置档即恢复原名称与图标，不残留上次外观。 |
| 自动更新未知的改名包 | 构建可以验证；发布到原更新通道被拦截，运行测试明确风险。 |
| 窗口标题与任务栏图标 | 独立记录；未在应用适配时不标记为已修改。 |
| emo-master 兼容回归 | 无覆盖的共享配置、命令与原有安装分支逻辑不被改写，不扩展外观功能。 |
| Actions 版本与产物 | 脚本和源码 SHA 符合所选版本；只上传预期 ZIP 和允许的摘要。 |

使用标准库 unittest 等轻量测试方式，mock PyInstaller、GitHub、私有源码和大型依赖。真实 Windows 构建分轻量 fixture 和训练平台实际依赖环境两层；前者通过不能替代后者。

验收记录建议保存为 `docs/evidence/visionworkshop-portable-branding-acceptance.md`，包含系统、工具版本、两仓库 SHA、命令、退出码、ZIP/EXE 信息、通过/失败/未执行项。不提交 token、个人路径或虚假的成功截图。

不增加安装、卸载或安装升级测试。必要的自动更新验收属于便携程序更新，不应重新写成安装器测试。

## 12. 功能实施后的操作示例

以下是计划接口，**当前脚本尚不能直接使用这些新增参数**。图标文件与源码路径必须由使用者实际准备。

```powershell
# 生成 VisionWorkshop 便携 ZIP，不上传 Release。
# 自动更新兼容性未验证时，仅作为受控构建/运行验收产物。
.\scripts\publish-local-release.ps1 `
  -Target "emo-vision-train" `
  -SourceRoot "D:\Projects\emo-vision-train" `
  -ReleaseTag "v1.2.3" `
  -BrandingProfile "profiles/visionworkshop.json" `
  -BuildOnly
```

```powershell
# 不选择配置档，不传覆盖参数，恢复原始便携包构建。
.\scripts\publish-local-release.ps1 `
  -Target "emo-vision-train" `
  -SourceRoot "D:\Projects\emo-vision-train" `
  -ReleaseTag "v1.2.3" `
  -BuildOnly
```

还应支持不使用配置档、直接传 ProgramName、IconPath、ReleaseAssetName 的一次性方式。两种方式使用同一解析器，不能一条生成 ZIP，另一条却调用安装器。

## 13. 待办与实施边界

以下复选框均未完成，不因文档入库而视为代码已交付。

- [ ] M0：记录最新打包器与目标源码提交；建立默认配置及共享代码回归基线。
- [ ] M1：实现唯一解析核心、显式配置档、输入校验和冲突检查。
- [ ] M1：接入 VisionWorkshop EXE、图标、隔离目录及正确的 updater 复制目标。
- [ ] M2：生成单一应用根目录的 ZIP，所有阶段使用同一最终配置。
- [ ] M2：实现仅构建/预览的无发布行为和自定义产物复用证明。
- [ ] M2：加入跨名称更新兼容状态和发布前拦截；不绕过或伪造更新支持。
- [ ] M3：完善训练平台向导，无安装器设置，不改变其他目标的默认行为。
- [ ] M4：接入 Actions 配置档、正确版本和最小权限测试。
- [ ] M5：Windows 实际打包、解压、启动、EXE 图标、默认恢复验收。
- [ ] M5：补文档与证据，明确运行时外观、更新兼容等尚未完成事项。

后续独立任务可以包括 VisionWorkshop 窗口标题和运行时图标的应用侧适配、跨名称更新迁移、图标格式转换与多本地预设。它们不能被误报为当前打包参数已经自动实现，也不需要通过引入安装器完成。

本期核心交付以 VisionWorkshop 便携名称与图标链路为准；正式分发前需额外通过实际运行及已选更新策略验证。代码回退按阶段提交进行；恢复默认构建不意味着已经撤销远端发布或迁移了已部署版本。

本次用户授权是修订并推送计划文档，不是实施 M0–M5、修改外部应用或发布构建产物。仅更新本文，不合并默认分支、不触发发布工作流、不提交任何二进制。

## 参考代码

除 R7 外，以下均以 `jsdfhasuh/python_build_scripts@ab4a33e586138fb381a87ae21cc83b5e8d79adbe` 为核查基线。引用是已读代码位置，不是实施完成证据。

- **[R1]** `build.py`：BuildJob、load_config、append_common_args、build_pyinstaller_command、copy_updater_to_app_dir、main。
- **[R2]** `configs/emo-vision-train.json`：source_repo、release_repo、name、icon、onefile、release_asset_name、updater。
- **[R3]** `scripts/publish-local-release.ps1`：配置读取、dist 目录、Compress-ReleaseArchive、SkipBuild、BuildOnly、manifest、上传分支。
- **[R4]** `scripts/release_wizard_common.py` 与 `scripts/release_wizard_emo_vision_train.py`：配置加载、模式选择、参数拼装、确认、gh 检查。
- **[R5]** `.github/workflows/release-windows.yml`：两个调用入口、checkout ref、源码检出、构建和上传。
- **[R6]** `AGENTS.md`：仓库职责、测试现状、新增代码规范。
- **[R7]** 前次核查的 `jsdfhasuh/emo-vision-train@59352fd5a0f183693f3384940dd2d5923e317e15`：auto_update.py 的当前 EXE 名获取；updater.py 的 --exe、find_payload_dir、restart_app、main；ui/ui_main.py 的窗口标题设置。实施时须复核所选源码版本。

本文中的 profiles、公共解析模块、新增参数、检查规则和验收记录均是待实现设计；现有代码已具备的能力与计划新增的能力必须区分。
