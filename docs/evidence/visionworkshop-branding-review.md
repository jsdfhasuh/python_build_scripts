# VisionWorkshop 完整接入：代码审查与验证记录

日期：2026-09-08。基线：`0f2fd96afc6d1316b3b0d80296ae412a30fb377c`。
范围：python_build_scripts；不修改目标应用、原目标配置、运行时 hook 或安装器。

## 实施范围

M0 基线保留；M1 配置/图标/构建隔离复用上一批代码；M2 增加构建记录、ZIP、复用和发布保护；
M3 接入训练平台向导；M4 增加独立的 VisionWorkshop 手动/复用和测试 workflows；
M5 编写真实 Windows fixture 验收脚本和操作文档。

为避免共享代码影响其他项目，PowerShell 旧发布脚本按原 blob
`48879b7d3d26bd42fb184f25a8a4d3b7f5727e05` 原样保留为同目录 legacy 文件，新入口仅做路由。
没有给 VisionWorkshop 增加安装器。既有 Release Windows Build 和 emo-master 向导保持不变，
新能力通过 VisionWorkshop 专用 workflow 使用。这是相对原计划的实现组织调整，不是另写
配置规则；Python、PowerShell、向导、Actions 的自定义流程均调用同一实现。

## 审查后修复的问题

| 问题 | 修复与测试 |
|---|---|
| 只看 dirty 标志无法发现已修改文件在编译中再次变化 | 增加工作文件内容摘要，并在编译前后比较；包含 helper 模块和递归子模块。 |
| Git 子模块输出前导空格被 strip 后错误判为未初始化 | 保留状态字符；使用真实本地 Git 子模块 fixture 验证。 |
| 显式 `-Publish:$false` 可能落回旧入口的默认发布 | 按参数是否显式绑定选择新入口，不仅看布尔值；新入口仍默认只构建。 |
| Python 3.11 缺少 Path.is_junction 时漏检 Windows junction | 检查 st_file_attributes 的 reparse-point 位，同时检查 symlink。 |
| 任意输出目录会改变打包仓 untracked 状态，引发错误失效 | 二进制证明使用打包器提交和参与执行的代码摘要，不把新产物目录当作输入。 |
| ZIP 正常退出不证明根目录/内容正确 | 逐条校验路径、大小、哈希、重复项和特殊文件；流式读取 ZIP/LZMA。 |
| 嵌套私有记录可能进入 _internal | 拒绝任何层级的本工具私有记录及 .git 数据。 |
| 记录 ID/结构不严或 schema=True 被当作 1 | 严格 schema 类型、固定记录位置、build ID、配置和文件摘要校验。 |
| 输出路径包含 `..` 可绕过词法目录边界比较 | 在检查链接后规范化路径再比较源目录/私有目录边界；回归测试在编译前拒绝。 |
| 发布失败可能没有清楚的本地状态 | 先保存 published=false 摘要，成功后只更新本次创建的摘要。 |
| 英文 Windows runner 重定向输出使用 cp1252，打印中文名称崩溃 | 为新 CLI/向导/fixture 统一 UTF-8 输出，新增 ASCII/cp1252 实际子进程回归；保留未修复前的 CI 失败记录。 |
| 可选 source_version_file 被新入口遗漏 | 恢复源码版本与 tag 的校验，并将该文件纳入输入摘要。 |

## 本地验证

环境：Linux，Python 3.13.5；未安装 Windows/Powershell 运行环境。

- 从用户提供的 M1 源码包恢复后，原 71 项测试重新通过。
- 完整单元/CLI/本地 Git/ZIP/向导/workflow 结构测试：发现 136 项，135 项通过，
  1 项 PowerShell 执行测试因不是 Windows 而明确跳过。
- Python AST 解析检查通过（19 个本批 Python 文件）；实际测试输出附交付包。
- 新增 tests 使用假编译器时只生成带明确测试字样的文件，不把它当成真正的 Windows EXE。
- 使用标准库实际读写 ZIP/deflate 和 ZIP/LZMA；源文件和子模块变更测试使用真实本地 Git。

以上计数对应本轮最终记录前的测试日志。后续提交或 CI 若新增用例，应以新的日志为准，
不要手动沿用这个数字。

## 未执行或仍受限

本机仍为 Linux。首次远端 CI（run `34207622954`，代码 `0547dc3`）中 Linux 测试通过，
Windows 133 项测试全部通过，PowerShell 脚本解析通过。Windows 实包验收在中文名称的日志
输出处遇到 cp1252 编码异常，不能标为整套实包验收通过；已修复并补回归，重跑结果另行记录。
正式 VisionWorkshop 的 Qt/GPU/硬件运行、正式 ICO 视觉检查及跨 EXE 名自动更新没有完成。
正式产品 ICO 未由用户提供，仓库不会用测试 ICO 冒充正式资源。

源码、依赖环境和产物摘要是一种本地一致性检查，不是签名或恶意本机攻击者的安全边界，
也不是二进制可复现承诺。声明的资源与 Git 工作文件以外的未声明外部依赖仍需要项目规范。

## 结论

审查发现的问题已补代码和回归用例；本轮自动测试未发现未修复的失败项。
这不等于证明不存在其他缺陷。代码交付与 Windows 产品验收分开：
新改名包默认只能本地构建，跨名称更新发布继续受限；不应直接合并后向现场自动更新通道发布。

仓库实际推送结果、提交 SHA 和 CI 执行结果以本轮交付说明及 GitHub 实际记录为准。
本文件不预先声称推送或 Windows CI 已成功。
