# Emo Vision Train Actions 发布

## 网页入口

在公开打包仓库中打开 Actions，选择 `Release Windows Build`，将 `target` 设为
`emo-vision-train`。这个分支复用 `VisionWorkshop portable ZIP` 工作流，并直接使用共享
Python 发布入口，不再经过旧 PowerShell 发布逻辑。Master 的构建和安装包流程不变。

两个入口保留各自外观默认值：旧入口使用原始名称和图标；portable 入口使用
`profiles/visionworkshop.json`，必须有可用的生产 ICO，不能用测试图标代替。

| 参数 | 默认值和用途 |
|---|---|
| `source_ref` | 必填，源码分支、tag 或 commit；启动后固定为 checkout 的完整 SHA |
| `release_tag` | 留空读取源码 `app_version.py` 的 `APP_VERSION`，兼容 `__version__`；手动值必须一致 |
| `delta_base_tag` | `auto` 自动选择旧基线；`none` 只生成完整包；也可填具体旧 Release tag |
| `previous_source_ref` | 留空从上次正式发布解析源码 commit；这是日志起点，不是差异包基线 |
| `release_title` | 留空使用程序名加版本号 |
| `notes` | 留空使用版本号，传给共享发布入口的短说明 |
| `mandatory` | 默认 `false`，传给共享发布入口的强制更新标记 |
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

日志起点独立选择上一个正式版本的源码提交。因此手动选择较旧差异基线时，不会意外扩大
默认更新日志范围。日志起点无法解析时必须指定源码起点、正文文件或全部历史选项。

## 执行和产物

准备阶段在安装重型依赖前检查版本、外观、正文、发布目标和基线，并在步骤摘要展示
源码 SHA、打包器 SHA、发布版本、基线版本、日志范围、标题、发布模式和协议资产数量。
准备记录和基线放在 runner 临时目录，不修改 checkout 或写回目标 JSON。

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

私有源码读取配置 `SOURCE_REPO_TOKEN`；发布仓库查询及发布使用 `RELEASE_REPO_TOKEN`。
正式发布必须显式配置发布令牌。公开仓库查询可不认证，但限流或读取失败仍直接停止，
不能被误判为首次发布。Secrets 不作为普通输入或构建记录保存。

每次修改后运行 `python -m unittest discover -s tests -v` 和工作流 YAML/actionlint 检查。
Windows 可运行 `python scripts/verify_windows_portable.py` 做小项目真实 EXE 验收。
这些测试不代表产品 GUI、GPU、硬件及实际跨版本更新已经验收；正式 Actions 构建和发布
需要另行明确触发。本次没有仅更新正文、跨运行重新归档或本地触发向导模式。
