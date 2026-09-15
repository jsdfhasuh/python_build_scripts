# Emo Vision Train Actions 发布

## 网页入口

在公开打包仓库中打开 Actions，选择 `Release Windows Build`，将 `target` 设为
`emo-vision-train`。这个分支复用 `VisionWorkshop portable ZIP` 工作流，并直接使用共享
Python 发布入口，不再经过旧 PowerShell 发布逻辑。Master 的构建和安装包流程不变。

两个入口的 Vision Train 构建均使用 `profiles/visionworkshop.json`，生成
`VisionWorkshop.exe`、品牌更新器、图标和运行时品牌资源，并保留旧名称兼容入口。
必须有可用的生产 ICO，不能用测试图标代替。portable 入口仍可显式选择其他配置。

| 参数 | 默认值和用途 |
|---|---|
| `source_ref` | 必填，源码分支、tag 或 commit；启动后固定为 checkout 的完整 SHA |
| `release_tag` | 留空读取源码 `app_version.py` 的 `APP_VERSION`，兼容 `__version__`；手动值必须一致 |
| `delta_base_tag` | `auto` 自动选择旧基线；`none` 只生成完整包；也可填具体旧 Release tag |
| `previous_source_ref` | 留空从上次正式发布解析源码 commit；这是日志起点，不是差异包基线 |
| `release_title` | 留空使用程序名加版本号 |
| `notes` | 留空使用版本号，传给共享发布入口的短说明 |
| `mandatory` | 必须为 `false`；当前协议 2 不支持强制更新标记，开启时预检直接报错 |
| `release_body_path` | 可选，选定打包器版本中已有的 `.md` 文件，相对打包仓库根目录 |
| `changelog_all` | 默认 `false`，无正式历史版本时自动启用；不能与显式日志起点同时选择 |
| `release_repo` | 留空使用配置；协议 2 固定发布到 `jsdfhasuh/emo-vision-train-release` |
| `packager_ref` | 手动运行留空使用选中的工作流 SHA；跨仓库调用必须明确提供 |
| `publish_release` | portable 默认 `false`；旧网页入口的 `auto` 对 Vision Train 也表示不发布 |

正文路径不接受绝对路径、链接、越界路径或不存在的文件。文件内容会在准备阶段固定哈希，
之后发生变化就停止。未提供正文文件时自动生成日志；首次发布默认包含全部源码历史。

旧网页入口正式发布请选择 `publish_release=true`。`auto` 对其他目标保持原有发布默认值。
`workflow_call` 的 `publish_release` 仍为布尔值且默认 `false`，既有调用无需改成字符串。
点击运行即确认参数，不增加第二次审批，也不会在只构建模式创建 Release。

## 基线选择与校验

1. 分页读取正式且非预发布的历史 Release。认证、网络或返回格式错误直接失败。
2. `auto` 按稳定版本号排序，选择低于本次版本的最高版本，不以发布时间或 latest 标记排序。
   不接受无法解析的正式版本或同版本多 tag 的歧义，不静默跳过损坏基线。
3. 只有确认不存在正式历史 Release 才自动按首次发布处理。已有历史但无合适旧基线则报错；
   需要仅完整包时明确填写 `none`。已有旧版但尚无协议 2 元数据时，也需要显式选择 `none`。
4. 下载并验证选定基线的 identity、package-files 和完整 ZIP，固定 Release ID、资产 ID、
   名称、大小及 SHA-256。使用选定源码的协议解析器和完整包消费者验证兼容性及包内文件。
5. 使用源码生产器的 `--base-files` 接口生成差异包，不在生成时重新按 tag 选择基线。
   不具备这个接口的源码会停止，不能绕过检查。生成前再次核对远端快照及本地指纹，
   并核对生产器返回的基线指纹和重建目标指纹。

差异生产器的 JSON 文件名字段是 `zip_asset_name`（源码内部解析对象的 `zip_name`
不是命令行返回字段）。打包器在生成成功摘要前校验目标 build ID、重建指纹、ZIP 名称、
大小、SHA-256，以及磁盘 descriptor 与生产器返回元数据的一致性；缺字段或产物不匹配时
明确报错，不生成成功摘要或进入发布。

日志起点独立选择上一个正式版本的源码提交。因此手动选择较旧差异基线时，不会意外扩大
默认更新日志范围。日志起点无法解析时必须指定源码起点、正文文件或全部历史选项。

## 执行和产物

准备阶段在安装重型依赖前检查版本、外观、正文、发布目标和基线，并在步骤摘要展示
源码 SHA、打包器 SHA、发布版本、基线版本、日志范围、标题、发布模式和协议资产数量。
准备记录和基线放在 runner 临时目录，不修改 checkout 或写回目标 JSON。

构建进程及 Python 子进程禁止生成普通导入字节码，避免编译时在源码资源目录新增
`__pycache__` 导致输入快照变化。已有缓存和其他文件仍参与原有校验，不删除源码文件，
不忽略真实资源变更。

每次编译前在隔离工作目录写入私有 `input-snapshot-before.json`。输入一致性检查失败时，
另写 `input-changes.json`，包含前后指纹，以及源码、资源和打包器文件的新增、删除、修改
清单。日志输出变化类别、文件数量、最多十个变化文件的相对路径和私有诊断路径，
不输出文件内容或令牌。这两个记录
不会加入公开 ZIP 或 Actions Artifact；托管 runner 清理后本地记录不再可用，应先根据
日志中的变化类别及文件示例缩小排查范围。没有关闭一致性检查，也不会把失败构建标成成功。

构建和预检使用同一组固定参数。构建程序及 updater 后生成：

- 完整包：一个 `*-full.zip`、`VisionWorkshop-windows-x86_64-release_identity.json`、
  `VisionWorkshop-windows-x86_64-package_files.json`，共三个协议资产。
- 差异模式：额外生成 `*-delta.zip` 和对应 `*_descriptor.json`，共五个协议资产。
- Actions Artifact 另附公开 `build-summary.json`。只暂存并上传清单中名称合法、文件存在、
  大小及哈希一致的公开资产，不上传 `build-record.json` 或整个构建目录。

正式发布使用同一批已验证的资产：创建 Draft，上传并核对资产名称、大小和 SHA-256，
全部通过才转为正式 Release。失败时不会转正；已有 Draft 需要人工检查，重跑不会自动覆盖。
Actions 公开资产暂存步骤在共享发布入口成功返回后执行；发布失败可能没有 Actions Artifact，
不能将其缺失视为远端没有 Draft。

## 令牌与验证

### CI GPU 依赖检查

Vision Train 使用 `ci/vision-train-runtime.json` 的独立 CI 依赖配置。源码依赖文件、
目标 JSON、现有运行时 hook 和 Master 安装流程不变。CI 在临时目录合并源码依赖、
目标补充依赖与以下明确覆盖，然后由 pip 一次解析，失败就停止：

- Torch 2.5.1、TorchVision 0.20.1、TorchAudio 2.5.1 使用官方 cu121 构建。
- 补齐 Polars、Anomalib、Kornia、Lightning、Timm 和视频依赖。
- Kaggle 固定 2.2.4，KaggleSDK 覆盖为 0.1.37，避免旧 0.1.31 缺少 API 类型。
- platformdirs 覆盖为 4.10.0，满足 Anomalib；imagecodecs 固定 2025.3.30，
  保留源码 NumPy <= 1.26.4 约束，不升级到 NumPy 2。
- 最后重装相同版本的 ONNX Runtime GPU 与 OpenCV contrib 二进制包，防止共享
  导入路径被 CPU/非 contrib 包覆盖；随后必须通过 `pip check`。

Actions 的共享入口强制传入 `--verify-vision-train-runtime`：编译前验证 GPU 构建版本、
关键功能导入和 Git 中自带模型；编译后、压缩和任何发布前读取主 EXE 的 PYZ 模块表，
验证 Polars 原生扩展、CUDA/cuDNN 文件及 PE 导入依赖。缺模块或缺 DLL 即失败。
运行时配置也计入构建输入指纹，公开摘要记录检查结果。

这些检查不要求 runner 有显卡，不以 `torch.cuda.is_available()` 为通过条件。
它们不代表实际 GUI、GPU 训练、硬件或更新验收；摘要明确记录 GPU 执行为 `not-run`。
`yolo11n.pt`、`yolo11s.pt`、`yolo26n.pt` 不在源码 Git 模型清单中，不从开发机补入包。

已发布的旧版本不会被此修改修复或覆盖。先以 `publish_release=false` 构建新包并验收，
再使用新的源码版本/tag 发布；不要覆盖已有 v1.0.24 资产。

私有源码读取配置 `SOURCE_REPO_TOKEN`；发布仓库查询优先使用 `RELEASE_REPO_TOKEN`，
未配置时回退到只读 `github.token`，因此仅构建公开发布仓库的产物不要求发布令牌。
正式发布在准备和执行阶段都检查显式 `RELEASE_REPO_TOKEN`，只读回退不能满足发布检查。
私有发布仓库仍需要具有读取权限的令牌；限流或读取失败直接停止，不能被误判为首次发布。
Secrets 不作为普通输入或构建记录保存。

每次修改后运行 `python -m unittest discover -s tests -v` 和工作流 YAML/actionlint 检查。
Windows 可运行 `python scripts/verify_windows_portable.py` 做小项目真实 EXE 验收。
这些测试不代表产品 GUI、GPU、硬件及实际跨版本更新已经验收；正式 Actions 构建和发布
需要另行明确触发。本次没有仅更新正文、跨运行重新归档或本地触发向导模式。
