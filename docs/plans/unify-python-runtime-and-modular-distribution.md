# Vision Workshop 统一 Python 3.12 与模块化发布 — 打包仓库配套计划

本文件保留原任务及跨仓库 Gate，只更新对应的实际状态与证据。

## 2026-11-26 实施状态（Asia/Shanghai）

以下状态按源码、实际构建、真实 EXE 与业务模型资格分别记录。保留原任务句、顺序和 Gate；不因诊断或候选通过而自动完成其他阶段。

### 历史计划基线

原打包计划基线为 `docs/unify-python-runtime-modular-release@50ebccf9a0f0d1b9afa4e530f6ea3bdc9d6e78ee`；计划制定时打包为 `master@702fca523be0aae306763cde6f19742a96c4a0cb`、应用为 `main@39ee980f8179e81d1ad90cafcec1e65d3b944c81`，第 2 节保留该时点快照。对应[应用 OpenSpec](https://github.com/jsdfhasuh/emo-vision-train/tree/docs/unify-python-runtime-modular-release/openspec/changes/unify-python-runtime-and-modular-distribution)。 历史完整包及体积审计仍绑定 PR #4 的 `6d4278aa0adddcd45994e64f1bf673886b2037d8`，不改记为模块候选结果。

### 固定来源与最新候选

| 证据层 | 固定身份与实际范围 |
| --- | --- |
| 历史 B2 CPU | [run 45585355615](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45585355615)：app `bb3772003f0b8cbd872d9342a48aa4a82d5bb861`，builder `b8cd91e9c72a682cd5efce91ac713100601da488`；CPython 3.12.10 / PyInstaller 6.18.0；10 个真实 EXE 场景通过，总体 LIMITED，GPU NOT_RUN。见[B2 固定证据](https://github.com/jsdfhasuh/python_build_scripts/blob/940986d603e4286d7419beb57d6312627233ef29/docs/evidence/visionworkshop-modular-loader.md)。 |
| 本轮完整候选应用源码 | `591f8bef7b2292caf50f4848e3047518e490742c`；协议 4 离线事务、按操作的模块能力检查、冻结标准流、注册 Defender 离线来源诊断、原生 Windows Qt 与固定 DataLoader spawn 验收入口。见[源码推进范围](https://github.com/jsdfhasuh/emo-vision-train/blob/591f8bef7b2292caf50f4848e3047518e490742c/docs/evidence/modular-offline-source-20261125.md)。 |
| 本轮完整候选打包源码 | `d3ace70e41a41b4334a9e44d2dbec0d4907f077d`；独立 Core/11 模块 ZIP、严格原件复用、Windows venv 进程链核验、独立模块总索引及逐资产验证。见[候选说明](https://github.com/jsdfhasuh/python_build_scripts/blob/d3ace70e41a41b4334a9e44d2dbec0d4907f077d/docs/visionworkshop-modular-candidate.md)。 |
| 最新实际候选 | [run 45659615499](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45659615499)，使用上述应用/打包 SHA，复用来源仅为 `45616400076/attempt 1`。构建 BUILT、独立索引及资产验证 PASS；产品在 Core 退出时 FAIL。详见下方实物结果。 |

历史 B2 使用其原有输入，不能追认为当前完整产品已通过。B2 的 DINO 仅为 environment() 和受控 ORT 小图；production_worker_protocol/model_inference 为 NOT_RUN。

### 已完成的真实构建与失败边界

首次[完整候选 45616400076](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45616400076)固定 app `c8c0fbe98a055620ddc5488be6835cf216b4800e`、builder `f9703a9c6a0c0370a10eed0afadd39e677770547`、build `candidate-45616400076-1`。Core ZIP **180,416,446 字节**，最大 Torch ZIP **1,865,186,577 字节**，12 ZIP 共 **2,791,206,650 字节**。逐成员构建校验通过，但首次 CLI 因中文写入 cp1252 输出而退出 1，产品 **FAIL**，cases 为空；修复没有改变这份历史结果。

原 Core manifest SHA256 `68bd245e8406b7a9dc2decef653c2d8c556c05aabf702b4b4ae2d5d066e873ae`；lock SHA256 `765b59a43a50ebc1714dccac2cc1f8c12e543031d5673beb6f34cc3e704c0829`；ABI `cp312/win_amd64`。原证据 artifact `15028274168`，ZIP SHA256 `409bf843e05c7d408ee32f136ac3e8505997157ef245275764ca595e425ae877`。

后续 45633041291 停在 Windows 换行断言；45634156750 被严格 RECORD 差异门拒绝，没有新 Core。随后[候选 45643325579](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45643325579)固定 app `b1201a03313da762cdd2854a0cd1ff4f87ed87b1`、builder `abad01f6457c8f051006342259206e60acd7aea6`，实际完成原始安装记录逐行资格核验和 **11 个原 ZIP/manifest 不改字节复用**，重新构建 Core。22 个差异行仅属于已排除的 22 个 Scripts 可执行文件；其他原始 RECORD 字节和 payload 保持约束。四个模块的 fresh_payload_identical 明确为 false，没有伪报全部新库存逐字相同。

该次新 Core ZIP **180,430,293 字节**，SHA256 `b52de8727769c0b34ce432b3188394bc555b1f1a00f8c616411a701a2f29d259`。重定向和 NULL 标准句柄的空模块 CLI 均退出 0；随后真实 Core 创建项目、准备数据并检查缺模块按钮和关闭清理，但原生来源诊断拒绝 Core 外的注册 Defender `MpOAV.dll`，**整个 Core case/产品仍为 FAIL**。原 offscreen 截图只有轮廓和图标，没有文字，不能称为正常视觉显示。后续安装、模型、worker 均未执行。证据 artifact `15039047778`，外层 SHA256 `85b35f95373c067fd695ca8f2710548aac60e270ec4127a61f51d0ab76e6649a`。见[固定构建/复用结果](https://github.com/jsdfhasuh/python_build_scripts/blob/0d48c66b90bf95df45ae8f0a12cc882c87f58b16/docs/evidence/visionworkshop-modular-candidate-45643325579.json)。

[候选 45652987042](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45652987042)固定 app `e44eacec0e3732801e872a69a318c74dd5e03bba`、builder `0d48c66b90bf95df45ae8f0a12cc882c87f58b16`：实际 Windows 注册 Defender 离线签名探针通过；原生 Qt 英文/中文 glyph 和像素检查通过，两张 PNG 已人工确认文字正常。但外层要求 Popen PID 与实际 Python PID 相等的断言失败，流程在 **Core 构建之前停止**。原运行没有 PPID/映像观测，不能将推断补写为实际父子链。证据 artifact `15041344101`，SHA256 `d2fe73b974e7db48aee807a2ebf5342a75e10361626ff512ad84c6a5583ec0a6`。见[原生来源/字体及失败范围](https://github.com/jsdfhasuh/emo-vision-train/blob/591f8bef7b2292caf50f4848e3047518e490742c/docs/evidence/modular-native-provider-source-20261126.md)。

### 最新实物结果：45659615499

本轮实际构建 **BUILT**：Core ZIP **180,443,076 字节**，SHA256 `14e62ed16acb684c1ed09573c24ec7b52482dd0d867dbf52df254275d9c7c0d9`；11,322 文件、627,769,495 解压字节。Core manifest SHA256 `9b508d684ec2d594cbd2b162063fd6dc45b9982553f9276ef2bb8010b27064ad`，build `candidate-45659615499-1`，app/builder/ABI/lock 均绑定上表身份。11 个原模块 ZIP 和各自 canonical manifest、原 build 身份不变；聚合 `module-manifests.json` 报告的字段序列化顺序改变，不声称该聚合报告原字节不变。

独立[模块索引 artifact 15044844880](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45659615499/artifacts/15044844880)的外层 ZIP 为 14,709 字节，SHA256 `09cba823fdb0fb6ed5a685ddd5e665eb3efb238b680ad1a8dca0217e1910dc3f`；内部索引 **14,561 字节**，SHA256 `dd97cbd92475136c4263a0c9677aa44c98958b601c71a9bc1041c0f471008aab`。构建摘要和产品 driver 的实际 `module-index-verification.json` 同时绑定该原字节和全部 **12 个资产**，验证为 PASS。原件、完整库存/manifest、依赖与跨运行身份已独立复核。B3.4/B4.4 只据此完成交付/身份条目，不代表程序验收通过。

产品 **FAIL**：`core-without-modules` 内部 JSON 写出 PASS（4.609 秒）后，实际进程以 **3221225477 / 0xC0000005** 退出（10.062 秒）。driver 保持失败门禁，后续安装、标注、模型与 worker case 均未执行。Windows 字体/画面正常、实际生产项目/数据与指定缺模块控件、关闭/停工屏障、140 个映射路径中的原生来源、唯一 python312 和注册 Defender 离线签名检查均已有局部记录；“窗口关闭/线程停止”不等于全部 QObject 析构和进程正常退出。当前还没有崩溃堆栈，退出期/Qt 生命周期属于待验证推断。独立[原 Core 复测 45668883424](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45668883424)已完成，使用诊断驱动 `841ba103fe10ad62bdcc5206b784e186fd14552e`，原 Core/app/build 身份保持不变，结果仍 FAIL。正常无参 GUI 的自有窗口可见、启用并稳定 1 秒（6 次观测），发送正常 WM_CLOSE 后以 `0xC0000005` 退出，forced_cleanup=false；说明正常启动/关闭也能复现访问冲突，不仅限于验收入口。另一 Core case 在导入 NumPy 时得到 AddDllDirectory 的 WinError206，退出 1，未进入 GUI；该目录仅约 136 字符，不能仅据错误名称归因于单一路径超过 MAX_PATH。两个 Windows 事件查询均成功但为 0 记录/NO_MATCH，尚无故障模块或堆栈。两个新解压副本的原 Core 11,322 文件、627,769,495 字节均保持不变。复测[artifact 15049276123](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45668883424/artifacts/15049276123)为 15,951 字节，SHA256 `f08de528c65dea47175af87a0de0b432686d83a9b2d35ed400a7aec023a3935a`。正在准备仅观测自有子进程的原生异常定位和 DLL 目录注册对照，尚无该后续结果；非零退出和强制清理仍为失败。

实际[候选紧凑证据](https://github.com/jsdfhasuh/python_build_scripts/blob/841ba103fe10ad62bdcc5206b784e186fd14552e/docs/evidence/visionworkshop-modular-candidate-45659615499.json)保留原报告身份与失败。证据 artifact `15046836955` 为 **73,474,221 字节**，外层 SHA256 `eed972a2d2a487445335d09722fb62bdaa926efd75ba1db5ad911864829ebf81`，已独立核对；build summary SHA256 `69ca135db97b5f8e1f8b6d4cf9a7990bdf0ec7f3c2bb75a06539a71bf0cabffc`，索引验证报告 SHA256 `b1024296e596e61cd1d4f69b90dfabacbdcd5404db7f672769ba373255f95454`，Core case JSON SHA256 `77d867de8635bbbc7d3095f470c1645fabb94eb06be3a856751d7bc295293ee1`，真实 process 失败报告 SHA256 `01ff841033a5973585b17b55882e1f643de86f58dc760e6aa80ce896b0f99646`。

本轮 Qt 前置探针还真实核验了 driver 8276 → venv launcher 7672 → base Python 3948 的单层关系；依赖 venv 的 `include-system-site-packages=false`、Python3.12.10、独立 prefix 已从原 pyvenv.cfg 和实际进程交叉验证，配置 SHA256 `560c7b65c98cbd2b2e7b5c5bc004e460a7d24ae457190e41bfbef7e79ec90be6`。A1.2 可据干净 Windows runner、独立测试/编译/依赖环境记完成，不关闭其余 A1 兼容性条目。

配套 [portable 45659631993](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45659631993) 两平台完成：各 547 项，Windows 39 skipped、Linux 40 skipped，未有失败；Windows fixture acceptance 另通过。缺精确应用 checkout 的索引/复用测试在普通 portable workflow 中跳过，本候选的专门前置步骤另实际执行。新应用前置集合为 293 passed / 1 skipped，不能与 Linux 源测试或历史轮次重复加总成新产品通过数。

### 当前源码新增与尚待实际执行

独立 `module-index.json` 代码已接入：索引位于 ZIP 外，绑定新 Core、原模块各自的 build/manifest、ABI、lock、依赖、兼容范围和各 ZIP 大小/摘要；构建摘要另外绑定索引 SHA，避免自引用。产品 driver 重新核对全部实际资产。69 项定向 builder/index/Qt/workflow 测试通过；其中索引为 12 项小 ZIP 测试，均不替代 Windows 完整产物。B3.4/B4.4 已按本轮真实索引产物与验证报告分别完成；其余产品条目保持独立。

新增[DataLoader spawn 固定诊断](https://github.com/jsdfhasuh/emo-vision-train/blob/591f8bef7b2292caf50f4848e3047518e490742c/docs/evidence/modular-dataloader-spawn-source-20261126.md)使用真实 Torch CPU TensorDataset、一个 spawn worker，核验当前 EXE、相同模块快照、独立共享 lease、实际数据耗尽和资源释放。51 项源码/证据反例/真实标准库子进程清理测试通过；真实冻结 DataLoader 尚未执行。它不覆盖完整训练、训练取消、多 worker 或 GPU。

| 完整产品检查 | 已有真实结果与缺口 |
| --- | --- |
| Core 缺模块启动、生产能力状态 | 456433 有实际项目/数据/YOLO 和图片精简缺模块状态及清理的局部结果，但整项 FAIL，且 offscreen 文字未显示。456596 的原生 Windows 画面/检查记录通过，但进程原生退出异常仍使整项 FAIL；不能泛化为 CNN/DINO 模型 UI 已验。 |
| 标注保存/重开、租约/安装/冷 repair/移除/回滚 | NOT_RUN：完整产品尚未进入这些 case。 |
| 外置原生库、当前 CRT、ORT-only、PT/DINO worker、DataLoader spawn | 当前完整产品未完成相应 case。历史 B2 与源码测试分别保留，不作当前产品 PASS。 |
| EdgeSAM、图片精简、CNN pretrained、DINO Small、YOLO 原权重 | NOT_RUN：等待每项真实资源 loader/CPU 输出；受控计算也不代表既有业务模型精度。 |
| EdgeSAM 不同 manifest 生命周期 | NOT_RUN；夹具只增加版本/build/诊断 marker，原模型字节不变，不是新模型计算资格；须核对 Core 与当时所有无关模块摘要。 |

### 保留的资格缺口

完整候选 lock 由 builder 根据固定 recipe/constraints 与实际 wheel 来源库存生成，再绑定 Core 和模块；尚未完成应用预先批准完整 lock、builder 直接消费安装的原定流程。第一方算法适配器仍在 Core。小型 Qt/scikit-learn 私有 CRT 保留原路径，不能声称所有共享 DLL 已只有一个物理副本。

固定 Ultralytics `74b2b91` 的声明要求 Torch<2.10，与所选 Torch 2.10.0+cu128 冲突。上界来源为[PR #23353](https://github.com/ultralytics/ultralytics/pull/23353#issuecomment-3777012162)，后续[0537be1](https://github.com/ultralytics/ultralytics/commit/0537be116924fef9ec3a66e4689134a6a59e7dce)才移除并修改相关代码；当前 vendor 不含该提交且不改动。源码测试、preparation pip check 或受控计算通过均不能消除原声明冲突，Gate A1 仍未闭合。

生产 DINO 另缺原稳定部署 ZIP（SHA256 `5e7f5482ed5f56f68ab02b703293d83ff1e7875f7b0c8a01a88075b67367923e`）、原 `reference.json` 与 88 条 NPZ，见[历史 P5 证据](https://github.com/jsdfhasuh/emo-vision-train/blob/c8c0fbe98a055620ddc5488be6835cf216b4800e/docs/evidence/patchcore-p5/stage-20260927.md)。定向检索未找到当前可用原件。预训练骨干不是已训练 memory bank、阈值和独立参考，不能替代原数值合同。DINO worker 的负例/取消诊断也不代表成功模型会话或子进程完整导入资格。

Core 独立升级、第一方算法独立模块更新、CPU-only wheel 分发、真实 CUDA、既有业务模型完整数值资格、完整协议 3 published update retest、安装中途终止与断电恢复继续未完成。进程级网络禁止不等于物理断网。没有正式发布、合并或迁移协议 3 用户。

### 完整体积账本

[B3.5 账本](https://github.com/jsdfhasuh/python_build_scripts/blob/309f15d43f010ac7e4cab726d182bf0549d7c36d/docs/evidence/visionworkshop-modular-size-audit-45616400076.md)绑定原 7 份输入摘要，覆盖 12 ZIP 的 **44,018 文件、6,791,307,968 解压字节、2,791,206,650 ZIP 字节**。新全套比旧包增加 75,690,202 字节，其中新增 DINO 资源为 80,604,327 字节；其余 11 ZIP 比旧包少 4,914,125 字节，这是不同交付集合对账。全文件同 SHA 的 7,895,387 字节是解压内容理论超额，不是压缩节省或可删除清单。机器 JSON SHA256 `3620b924217700132e91472f3ac77292a7f714e891a518a23c1004f5b970fc57`；原产品 FAIL 保留。

## 1. 目标与边界

将 VisionWorkshop 产品构建从 Python 3.11 迁移到与应用仓库一致的 CPython 3.12 x64 精确补丁版本和 ABI；使用应用仓库生成的唯一完整依赖锁；在真实冻结程序验证通过后，支持 Core、共享运行库和功能模块独立构建、校验和离线发布。

本计划只修改 VisionWorkshop 专用配置、代码路径和工作流。打包仓库还服务其他产品，尤其 EmoMaster 的 Python 3.10 配置和工作流不得被全局升级。

不在本计划中实现算法业务逻辑，不改变 Kaggle 远端 Python 环境，不正式发布，不迁移现有协议 3 用户。

## 2. 计划制定时的实现快照

- `configs/emo-vision-train.json` 当前 `python_version=3.11`，通过 `ci_extra_packages` 补充 TorchVision 和 ORT GPU。
- `ci/vision-train-runtime.json` 当前锁定 Python 3.11、CUDA 12.1、Torch 2.5.1+cu121、TorchVision 0.20.1+cu121、TorchAudio 2.5.1+cu121。
- `vision_train_runtime.py` 负责 GPU wheel 安装、依赖解析、pip check、Torch/CUDA 版本、DLL、模块导入、DINO runtime 和冻结包验证。
- `hooks/vision-train/hook-torch.py` 复用上游 PyInstaller Torch Hook 并保留项目特定 collection mode。
- `pyi_rth_torch_dll.py` 与 runtime validation 处理 Torch/CUDA DLL。
- `portable_release.py`、build records、branding/wizard 和 `visionworkshop-portable.yml` 共同负责输入快照、构建、压缩、资产校验和发布。
- 当前包验证明确要求 `python311.dll`、DINO main runtime 模块、ORT 原生扩展和 Torch/CUDA DLL。
- `visionworkshop-tests.yml` 是打包仓库自身测试环境；其 Python 版本不应因为产品 runtime 统一而全局变更。
- 协议 3 和现有 Core/App/Updater 布局必须继续服务已发布版本。

## 3. 实施任务

### B0 — 只读构建审计

> 其他产品基线已按原计划父提交与本轮 d3ace70 做[逐文件/PR 范围对照](https://github.com/jsdfhasuh/python_build_scripts/blob/841ba103fe10ad62bdcc5206b784e186fd14552e/docs/evidence/visionworkshop-modular-other-product-baseline-d3ace70.json)。EmoMaster 配置/运行时/发布工作流及通用 build.py 字节不变；PR #4 仍有共享 oversized-ZIP 诊断保留行为、DINO worker 专用 CRT 预加载及通用测试 Python 版本变化，未做新的 EmoMaster 产品验收，B0.8/B1.9 不据此关闭。

- [ ] B0.1 追踪 VisionWorkshop 从 Release Wizard/CLI 到 build.py、PyInstaller、ZIP 和 Release 的完整调用链。
- [ ] B0.2 核对所有 VisionWorkshop 专用 Python 版本、ABI、CUDA、Torch、ORT、OpenCV 和 Qt 检查。
- [ ] B0.3 核对 `vision_train_runtime.py` 的 requirements 合并规则，确认不会覆盖应用完整锁中的其他依赖。
- [ ] B0.4 核对 Torch Hook、runtime hook、DLL 搜索目录及冻结 worker 启动方式。
- [ ] B0.5 核对 DINO main runtime 和历史 Embeddable 资源检查，区分当前发布路径与兼容测试夹具。
- [ ] B0.6 核对 add_data、hidden_imports、collect_binaries、collect-all、metadata 和静态资源的实际用途。
- [ ] B0.7 获取当前正式完整 ZIP，生成目录/文件/压缩前后体积账本。
- [ ] B0.8 记录其他产品配置和工作流基线，确保本次改动不会影响它们。

### B1 — CPython 3.12 构建环境

> 实施注：已有独立 CP312 构建/准备环境、精确来源回执、依赖闭包及原生文件检查。完整锁、最终 PE/CRT 来源和新产品计算须绑定最终候选；现有 CUDA-enabled Torch 的 CPU 运算不是 CPU-only 分发。

- [ ] B1.1 消费应用仓库批准的精确 Python 3.12 补丁版本和依赖锁身份。
- [ ] B1.2 仅修改 `configs/emo-vision-train.json` 和 `ci/vision-train-runtime.json` 的 VisionWorkshop 配置。
- [ ] B1.3 移除对 requirements.txt 的不透明覆盖/重复解析，改为验证并安装应用仓库的完整锁；如需 GPU 专用 index，明确锁定 wheel URL/hash 和安装顺序。
- [ ] B1.4 更新 `python312.dll`、CP312 .pyd、Torch/CUDA/ORT/OpenCV 原生文件和元数据验证。
- [ ] B1.5 更新 Torch DLL 清单及 CUDA 依赖闭包验证。
- [ ] B1.6 更新 DINO runtime 检查，使其验证统一 CP312 runtime，不再接受第二份 Python 解释器。
- [x] B1.7 保留真实 GPU 未执行时的 NOT_RUN 状态；不能用 DLL 存在或 Provider 名称代替 GPU 运算通过。
- [ ] B1.8 更新 VisionWorkshop 专用 Release workflow 的 setup-python、cache key 和依赖安装。
- [ ] B1.9 不修改其他产品的 Python 配置，也不因产品版本变更而无差别修改通用 tests workflow。

### B2 — 冻结程序外置模块加载技术验证（强制门禁）

> 已核证范围：下方五个勾选只对应 run 45585355615 的原输入。纯 Python/metadata、CP312 扩展、CPU 原生运算、DLL 来源、真实文件锁/退出释放、中文空格路径及测试包更新后重启已执行。B2.4 的卸载指进程退出后的释放与新进程重载，未实现进程内热卸载。B2.5/.6 的 CUDA 未运行；B2.7 的 production_worker_protocol 明确 NOT_RUN，只有 DINO environment() 与 ORT 小图。`dino` 环境/ORT 小图与新增 `dino-worker` 产品父子进程负例生命周期分列；后者尚未冻结执行，即使通过，也不证明子进程完整生命周期的实际导入集合、成功模型会话或原数值合同，因此 B2.7 继续留空。

- [x] B2.1 构建最小真实 PyInstaller onedir Core，绑定精确应用/打包 SHA。
- [x] B2.2 从 Core 外部目录加载纯 Python 包和 distribution metadata。
- [x] B2.3 加载 CP312 .pyd 并验证其依赖扩展和 ABI。
- [x] B2.4 验证模块 DLL 的搜索路径、加载顺序和卸载/重启行为。
- [ ] B2.5 验证 Torch CUDA DLL 只存在一份且能实际执行运算。
- [ ] B2.6 验证单份 ORT GPU 发行包的 CPU Provider 和 CUDA Provider。
- [ ] B2.7 验证 DINO worker 通过产品统一 runtime 启动且不导入 Torch。
- [x] B2.8 验证含空格/中文路径、模块更新后重启和文件锁。
- [ ] B2.9 若外置 .pyd/DLL/metadata 不可靠，停止模块管理器开发并调整打包布局；不得用模拟 sys.path 测试替代。

### B3 — 模块构建与清单

> 实施注：所选 Core/运行库/第三方 feature/资源 targets、单一所有权、完整 lock/manifest、独立 ZIP 及校验已有源码和首次真实构建；MSVCP 固定 Core canonical 与 Qt/scikit-learn 原始副本为显式来源集合，不等于所有 CRT 文件物理单份；实际 ZIP、单资产大小与总量见上方首次构建记录；它们是内部候选，不是正式发布资产。当前已有实际独立模块总索引及 Windows 全资产复核。B3.3 以首次候选 11 份实际 manifest 的完整字段和绑定身份为据；B3.4 已由 run45659615499 的实际独立索引/全资产验证完成，仍属内部候选。B3.5 已用完整 Core 库存、11 份 payload 清单及摘要匹配的原 module.json 重建覆盖全部 44,018 文件；每包解压字节、压缩成员、ZIP 开销、新旧交付差额与非空/空文件重复内容均已对账。B3.1 需注明当前模块边界，第一方算法代码仍在 Core；B3.6 不因所有受控 CPU fixture 通过而视为全业务目标验收。

- [ ] B3.1 定义 Core、shared runtime、YOLO、PatchCore、ONNX、DINOv2 和模型资源的 build target。
- [ ] B3.2 复用统一依赖锁和明确的文件所有权，模块不得重复打包 Python、Qt、Torch 或其他公共依赖。
- [x] B3.3 从构建输入自动生成模块 ID、版本、Core 范围、Python ABI、依赖锁 SHA、依赖模块、文件清单、大小和 SHA256。
- [x] B3.4 生成模块 ZIP 和总索引；每个资产都独立校验。
- [x] B3.5 对比 Core/模块压缩前后体积和重复文件，记录相对现有完整 ZIP 的真实节省。
- [ ] B3.6 所有目标在真实冻结程序中验证，不仅依赖构建配置单测。

### B4 — 新发布协议与兼容

> 实施注：protocol 4 独立布局、身份绑定、冷激活 lease 和原子 registry/恢复已有实现；协议 3 通道保留。B4.3 继续留空：没有 Core 升级或新 Core identity 的 registry 迁移。模块版本切换的有限证明不能关闭整条 Core 更新约束；B4.1 的完整行为资格还需 B5.6。

- [ ] B4.1 保持协议 3 的 manifest、delta、launcher 和 updater 行为不变。
- [x] B4.2 为模块化新安装定义显式新协议/schema，分离 Core 和模块 manifest。
- [ ] B4.3 Core 更新不得删除模块；模块更新不得覆盖 Core 或其他模块所有文件。
- [x] B4.4 绑定应用 SHA、打包 SHA、Python ABI、依赖锁 SHA、模块索引 SHA 和 build identity。
- [ ] B4.5 模块更新前处理 Windows 已加载 DLL/.pyd 生命周期，必要时停止 worker 并重启。
- [ ] B4.6 支持失败回滚及模块注册表恢复。
- [ ] B4.7 首个模块化版本采用全新安装目录，不对协议 3 用户做原地布局转换。

### B5 — 联合离线验收

> 验收注：B5.1/B5.7 仅依据 run 45616400076 的新 Windows runner、独立 compiler/runtime venv、真实 x64 冻结与 12 个已逐成员验证的 ZIP；最大资产 1,865,186,577 字节，完整大小/哈希/build identity 在原报告中。该 run 的产品验收仍为 FAIL、cases 为空。B5.4 可在新的 EdgeSAM 不同版本/manifest 更新和 Core/全部无关模块哈希对照确实通过后记录限定 fixture 证明，目前不预勾。B5.2 的进程级网络禁止须准确标注，不能冒称目标机物理断网。B5.5 按实际执行的失败/恢复/卸载/重启范围记录，当前驱动没有安装中途终止或断电步骤，整条保留未完成；B5.6 仍需原协议原资产身份的 published retest。应用 b1201a03 已包含图片精简、CNN/DINO操作与YOLO的实际模块ID检查，区分资源准备、计算运行库、预训练与完整模型恢复；真实Qt生产控件的源码回归通过。456433/456596 的真实 Core 已取得项目导入、dataset builder、WorkspaceView 的 YOLO/图片精简缺模块状态、Kaggle 就绪性及关闭/停工的局部记录；456596 的原生 Windows 画面正常但进程退出异常，且未覆盖 CNN/DINO 模型 UI，故 B5.3 整项未完成。B5.8 是持续发布边界，不代表 Release 已发布。

- [x] B5.1 从干净 Windows x64 环境构建完整 Core 和选定模块。
- [ ] B5.2 在无网络目标机安装 Core 和模块 ZIP。
- [ ] B5.3 验证模块缺失时 Core 正常启动、能力状态准确。
- [ ] B5.4 独立更新一个模块，证明 Core 和其他模块文件哈希不变。
- [ ] B5.5 验证中断/失败安装、恢复、卸载及重启。
- [ ] B5.6 运行现有协议 3 fixture/published update retest，确认旧用户路径未改变。
- [x] B5.7 每个资产小于 GitHub 单资产限制，并提供完整 size/hash/build identity 报告。
- [ ] B5.8 未经用户另行确认，不正式发布、不切换仓库可见性、不替换现有 Release。

## 4. 必须保留的测试和验收

- 保留 `tests/test_vision_train_runtime.py`、`tests/test_torch_runtime_hook.py`、`tests/test_build_collect_paths.py`、`tests/test_update_protocol_build.py` 等现有断言。
- 增加 CP312 运行时验证、DLL/ABI、模块 manifest 和离线事务的定向测试。
- 不删除失败用例，不降低覆盖率，不把 fixture 通过写成产品 GPU/GUI 验收。
- 真实 GPU 缺失时明确 NOT_RUN。
- 旧协议 3 的 published retest 仍以旧协议样本和原资产身份验证，不用新协议样本替代。

## 5. 跨仓库顺序

- B0 与应用 A0 并行。
- B1 等应用 A1 的依赖锁候选确定后实施。
- B2 与应用 A2/A3 联调，但 B2 必须使用同一应用/打包/锁 SHA。
- B3 等应用 A4 的模块目录和 manifest 合同冻结后实施。
- B4 与应用 A5/A6 联调。
- B5 最后执行。

原计划文档分支只提交计划文档，不改变产品配置、工作流、Hook、协议或发布资产；产品候选实现在上方注明的应用主分支和打包 PR #6 中。

