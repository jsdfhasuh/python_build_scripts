# Vision Workshop 统一 Python 3.12 与模块化发布 — 打包仓库配套计划

状态：计划草案，未实施。  
打包基线：`master@702fca523be0aae306763cde6f19742a96c4a0cb`。  
应用基线：`main@39ee980f8179e81d1ad90cafcec1e65d3b944c81`。  
对应应用 OpenSpec：[`unify-python-runtime-and-modular-distribution`](https://github.com/jsdfhasuh/emo-vision-train/tree/docs/unify-python-runtime-modular-release/openspec/changes/unify-python-runtime-and-modular-distribution)。

## 1. 目标与边界

将 VisionWorkshop 产品构建从 Python 3.11 迁移到与应用仓库一致的 CPython 3.12 x64 精确补丁版本和 ABI；使用应用仓库生成的唯一完整依赖锁；在真实冻结程序验证通过后，支持 Core、共享运行库和功能模块独立构建、校验和离线发布。

本计划只修改 VisionWorkshop 专用配置、代码路径和工作流。打包仓库还服务其他产品，尤其 EmoMaster 的 Python 3.10 配置和工作流不得被全局升级。

不在本计划中实现算法业务逻辑，不改变 Kaggle 远端 Python 环境，不正式发布，不迁移现有协议 3 用户。

## 2. 已确认的当前实现

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

- [ ] B0.1 追踪 VisionWorkshop 从 Release Wizard/CLI 到 build.py、PyInstaller、ZIP 和 Release 的完整调用链。
- [ ] B0.2 核对所有 VisionWorkshop 专用 Python 版本、ABI、CUDA、Torch、ORT、OpenCV 和 Qt 检查。
- [ ] B0.3 核对 `vision_train_runtime.py` 的 requirements 合并规则，确认不会覆盖应用完整锁中的其他依赖。
- [ ] B0.4 核对 Torch Hook、runtime hook、DLL 搜索目录及冻结 worker 启动方式。
- [ ] B0.5 核对 DINO main runtime 和历史 Embeddable 资源检查，区分当前发布路径与兼容测试夹具。
- [ ] B0.6 核对 add_data、hidden_imports、collect_binaries、collect-all、metadata 和静态资源的实际用途。
- [ ] B0.7 获取当前正式完整 ZIP，生成目录/文件/压缩前后体积账本。
- [ ] B0.8 记录其他产品配置和工作流基线，确保本次改动不会影响它们。

### B1 — CPython 3.12 构建环境

- [ ] B1.1 消费应用仓库批准的精确 Python 3.12 补丁版本和依赖锁身份。
- [ ] B1.2 仅修改 `configs/emo-vision-train.json` 和 `ci/vision-train-runtime.json` 的 VisionWorkshop 配置。
- [ ] B1.3 移除对 requirements.txt 的不透明覆盖/重复解析，改为验证并安装应用仓库的完整锁；如需 GPU 专用 index，明确锁定 wheel URL/hash 和安装顺序。
- [ ] B1.4 更新 `python312.dll`、CP312 .pyd、Torch/CUDA/ORT/OpenCV 原生文件和元数据验证。
- [ ] B1.5 更新 Torch DLL 清单及 CUDA 依赖闭包验证。
- [ ] B1.6 更新 DINO runtime 检查，使其验证统一 CP312 runtime，不再接受第二份 Python 解释器。
- [ ] B1.7 保留真实 GPU 未执行时的 NOT_RUN 状态；不能用 DLL 存在或 Provider 名称代替 GPU 运算通过。
- [ ] B1.8 更新 VisionWorkshop 专用 Release workflow 的 setup-python、cache key 和依赖安装。
- [ ] B1.9 不修改其他产品的 Python 配置，也不因产品版本变更而无差别修改通用 tests workflow。

### B2 — 冻结程序外置模块加载技术验证（强制门禁）

- [ ] B2.1 构建最小真实 PyInstaller onedir Core，绑定精确应用/打包 SHA。
- [ ] B2.2 从 Core 外部目录加载纯 Python 包和 distribution metadata。
- [ ] B2.3 加载 CP312 .pyd 并验证其依赖扩展和 ABI。
- [ ] B2.4 验证模块 DLL 的搜索路径、加载顺序和卸载/重启行为。
- [ ] B2.5 验证 Torch CUDA DLL 只存在一份且能实际执行运算。
- [ ] B2.6 验证单份 ORT GPU 发行包的 CPU Provider 和 CUDA Provider。
- [ ] B2.7 验证 DINO worker 通过产品统一 runtime 启动且不导入 Torch。
- [ ] B2.8 验证含空格/中文路径、模块更新后重启和文件锁。
- [ ] B2.9 若外置 .pyd/DLL/metadata 不可靠，停止模块管理器开发并调整打包布局；不得用模拟 sys.path 测试替代。

### B3 — 模块构建与清单

- [ ] B3.1 定义 Core、shared runtime、YOLO、PatchCore、ONNX、DINOv2 和模型资源的 build target。
- [ ] B3.2 复用统一依赖锁和明确的文件所有权，模块不得重复打包 Python、Qt、Torch 或其他公共依赖。
- [ ] B3.3 从构建输入自动生成模块 ID、版本、Core 范围、Python ABI、依赖锁 SHA、依赖模块、文件清单、大小和 SHA256。
- [ ] B3.4 生成模块 ZIP 和总索引；每个资产都独立校验。
- [ ] B3.5 对比 Core/模块压缩前后体积和重复文件，记录相对现有完整 ZIP 的真实节省。
- [ ] B3.6 所有目标在真实冻结程序中验证，不仅依赖构建配置单测。

### B4 — 新发布协议与兼容

- [ ] B4.1 保持协议 3 的 manifest、delta、launcher 和 updater 行为不变。
- [ ] B4.2 为模块化新安装定义显式新协议/schema，分离 Core 和模块 manifest。
- [ ] B4.3 Core 更新不得删除模块；模块更新不得覆盖 Core 或其他模块所有文件。
- [ ] B4.4 绑定应用 SHA、打包 SHA、Python ABI、依赖锁 SHA、模块索引 SHA 和 build identity。
- [ ] B4.5 模块更新前处理 Windows 已加载 DLL/.pyd 生命周期，必要时停止 worker 并重启。
- [ ] B4.6 支持失败回滚及模块注册表恢复。
- [ ] B4.7 首个模块化版本采用全新安装目录，不对协议 3 用户做原地布局转换。

### B5 — 联合离线验收

- [ ] B5.1 从干净 Windows x64 环境构建完整 Core 和选定模块。
- [ ] B5.2 在无网络目标机安装 Core 和模块 ZIP。
- [ ] B5.3 验证模块缺失时 Core 正常启动、能力状态准确。
- [ ] B5.4 独立更新一个模块，证明 Core 和其他模块文件哈希不变。
- [ ] B5.5 验证中断/失败安装、恢复、卸载及重启。
- [ ] B5.6 运行现有协议 3 fixture/published update retest，确认旧用户路径未改变。
- [ ] B5.7 每个资产小于 GitHub 单资产限制，并提供完整 size/hash/build identity 报告。
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

本分支只提交计划文档，不改变产品配置、工作流、Hook、协议或发布资产。
