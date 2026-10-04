> Historical M0/M1 record; current results are in `visionworkshop-branding-review.md`.

# VisionWorkshop M0/M1 实施与验证记录

日期：2026-09-08。计划：`docs/plans/2026-09-08-packaging-branding-improvement-plan.md` v1.2。
本批实现分支：`feat/visionworkshop-portable-branding`。
交付状态：远端仅成功提交 M0（`0f2fd96afc6d1316b3b0d80296ae412a30fb377c`）。
写入 build.py 的 GitHub 工具请求被拦截，M1 完整代码以本地补丁交付，未声称已推送。
打包代码基线：`ab4a33e586138fb381a87ae21cc83b5e8d79adbe`。
计划分支基线：`32ab479e8d574b9cf1380b016d11043c2439ac06`。

## 阶段状态

| 阶段 | 当前状态 |
|---|---|
| M0 默认基线 | 已实现并通过本地单元测试；固定两份目标配置的语义哈希和完整命令参数。 |
| M1 名称和图标构建 | 已实现配置档、临时覆盖、ICO 解码、隔离输出和 CLI；单元/模拟构建/CLI 测试通过。 |
| M2 ZIP 和发布 | 未实施完整接入。资产名解析和更新风险检查函数已提供；旧发布脚本未接入。 |
| M3 发布向导 | 未实施。 |
| M4 Actions | 未实施；现有工作流未改动，也未触发远端构建。 |
| M5 Windows 实包 | 未执行。无真实 VisionWorkshop EXE、ZIP、启动或 PE 图标验证结果。 |

本记录说明首批代码状态，不将 M0/M1 标作整个计划完成。历史计划文档仍保留设计说明；
后续实施状态以证据记录更新，不提前勾选没有执行的阶段。

## 本地验证环境

Linux x86_64，Python 3.13.5，Pillow 12.3.0。未安装或运行目标应用，不使用 Torch、Qt
或私有应用源码。测试使用最小源码 fixture，ICO 由测试函数临时创建，不是正式产品图标。
未修改现有构建环境所固定的 Python、PyInstaller、Torch、CUDA、ONNX Runtime 版本。

| 检查 | 结果 | 边界 |
|---|---|---|
| 在原始 build.py 上运行 M0 基线测试 | 8 项通过，退出码 0 | 原文件 Git blob 已核对为 d227387a5b0c4c4ba314cea458c25480fd5ff8d3。 |
| 修改后完整 unittest/CLI 测试集 | 71 项通过，退出码 0，未跳过 | 包括上述 8 项；不是 79 项独立测试。 |
| py_compile | 4 个入口/模块通过，退出码 0 | 不代表 Windows 环境执行通过。 |
| 两个生产目标配置 | 文件内容保持原样 | 未改名称、依赖、资源列表、控制台或安装器设置。 |
| 真实 PyInstaller 编译 | 未运行 | 此环境不是 Windows。 |
| Windows 启动、PE 图标及更新兼容 | 未运行 | 不能由 dry-run 或模拟编译器推导为通过。 |

## 可复现命令

在含 Pillow 的 Python 环境中、打包仓库根目录执行：

```powershell
python -m unittest discover -s tests -v
python -m py_compile build.py build_config.py branding_build.py scripts/resolve_build_config.py
```

只执行默认基线（不需要 Pillow）：

```powershell
python -m unittest discover -s tests -p test_build_baseline.py -v
```

覆盖配置优先级、默认配置不修改、合法中文/空格名称、非法 Windows 名称、重名 updater、
损坏/越界/多尺寸及重复尺寸 ICO、参数冲突、路径和模板、配置指纹、目录隔离、CLI JSON、
预览无副作用、编译失败不写成功回执、旧 dist 不回退、图标编译中变化和恢复默认行为。

“模拟编译成功”测试只写测试专用标记字节，验证复制/目录/错误处理流程；这些字节不是
真实 PE 文件，测试没有启动它们，也不据此报告生成了可运行 EXE。

## 保留的限制

没有随本批提供或选定生产图标；配置档默认图标缺失会明确失败，允许用户显式覆盖路径。
窗口标题和窗口图标不在本批适配范围，目标应用代码没有改动。

新解析器的更新检查未接入现有发布入口。构建回执不是可复用构建记录；源码快照、完整
产物哈希及发布前检查属于 M2。没有发布 Release，也没有关闭目标应用的运行时自动更新。
对外部应用的更新兼容状态保持 unverified，不声称完成新的更新协议审查或实测。
