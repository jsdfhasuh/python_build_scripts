# Vision Workshop 首次模块候选完整体积账本

**结论：run 45616400076 的 12 个 ZIP 已实际构建并逐成员校验；产品验收仍为 FAIL，cases 为空。** 本报告只核算这组失败候选的真实文件与交付体积，不改变运行资格。

Core ZIP 为 **180,416,446 字节**；全部 12 个 ZIP 共 **2,791,206,650 字节**，比旧完整 ZIP 增加 **75,690,202 字节**。新增 `resource.patchcore-dino` 单包为 **80,604,327 字节**；扣除它后，其余 11 个 ZIP 比旧包少 **4,914,125 字节**。这不是同功能、同依赖的纯压缩实验。

[完整机器可读账本](visionworkshop-modular-size-audit-45616400076.json) 包含每个资产、全部非空重复 SHA 组及路径、空文件明细、原报告摘要和推导口径。

JSON SHA256：`3620b924217700132e91472f3ac77292a7f714e891a518a23c1004f5b970fc57`。所有“字节”均为精确整数；百分比仅为显示值。

## 1. 构建、验收及旧基线身份

| 项目 | 本次固定身份 |
| --- | --- |
| 构建运行 | [45616400076](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45616400076) |
| Build ID | `candidate-45616400076-1` |
| 应用 SHA | `c8c0fbe98a055620ddc5488be6835cf216b4800e` |
| 打包器 SHA | `f9703a9c6a0c0370a10eed0afadd39e677770547` |
| Python | CPython 3.12.10 / cp312 / win_amd64 |
| Core manifest SHA256 | `68bd245e8406b7a9dc2decef653c2d8c556c05aabf702b4b4ae2d5d066e873ae` |
| 完整 lock SHA256 | `765b59a43a50ebc1714dccac2cc1f8c12e543031d5673beb6f34cc3e704c0829` |
| 构建与发布 | BUILT；source/packager dirty=false；published=false |
| 产品验收 | FAIL；cases=[]；empty-status exited with 1；GPU NOT_RUN |
| 证据 artifact | [15028274168](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45616400076/artifacts/15028274168) |
| 证据外层 ZIP SHA256 | `409bf843e05c7d408ee32f136ac3e8505997157ef245275764ca595e425ae877` |

产品首条 CLI 已写出成功状态 JSON，随后向 cp1252 重定向输出中文失败并退出 1。构建摘要生成时的 product_acceptance=NOT_RUN 不能覆盖后续产品摘要的 FAIL。这里没有把成功状态文件解释为整个命令或 Core GUI 通过。

旧基线为 [run 45544329988](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45544329988)，build `20261125T041832Z-524aee200c44`，应用 `bb3772003f0b8cbd872d9342a48aa4a82d5bb861`，打包器 `a63f320f86ca6dbfaf48d57afbd9853b8333ddc2`。旧 ZIP SHA256 为 `186b9c02076b02c017f0e84203740d53bff8efa1b820da6cb4a32503b653ae90`。逐成员原件来自 artifact `14993523793`；[原体积审计](https://github.com/jsdfhasuh/python_build_scripts/blob/6d4278aa0adddcd45994e64f1bf673886b2037d8/docs/evidence/visionworkshop-package-size-audit-20261125.md) 保持其历史身份。

## 2. 输入覆盖与对账

- Core 使用 `core-inventory-before.json` 的**完整实际库存**：11,318 个文件、627,674,298 字节；没有用较小的 `Core.runtime_files` 替代。所有路径/大小/SHA 与原构建后的 `core-files.json` 完全一致；数量与字节同时对应原 Core ZIP。
- 11 份原 module manifest 覆盖 32,689 个 payload 文件。每份的文件大小之和等于其 expanded_size。
- 各 ZIP 另有 1 个 `module.json`。按原应用 canonical_json 规则重建字节：UTF-8、ensure_ascii=True、键排序、紧凑分隔符、末尾 LF；**11 份重建 SHA 均等于原 build summary 的 manifest_sha256**，字节数也等于 ZIP 解压总量减 payload 总量。它们以“原摘要匹配的元数据重建”纳入，未假称重新读取了大 ZIP。
- 最终覆盖全部 12 个 ZIP 的 **44,018 个文件、6,791,307,968 解压后内容字节**；每包的文件数和原始字节全部对上。11 个 module.json 均非空且互不重复，也未与任何 payload/Core 文件同 SHA。
- 原构建器已完成每个 ZIP 的成员集合、大小、LZMA 方法、实际解压 SHA 和归档摘要往返核验；本次使用其已保存报告，没有重下载或重压缩大包。

### 输入报告 SHA256

| 原件 | 字节 | SHA256 |
| --- | ---: | --- |
| `modular-acceptance/reports/core-inventory-before.json` | 2,021,401 | `b25699b2f1e96ece49c0e5ec417631cb842db4cde2827f3dfca457f1d696ab29` |
| `modular-candidate/reports/core-files.json` | 2,191,171 | `7efdbd6c69927a79f23465f0014b8614a59703567c8f7c7da1a21bca51267fb8` |
| `modular-candidate/reports/modular-build-summary.json` | 2,704,752 | `11e849a240b6d12084b79eff1f626f4393f1d357e626ed1ffa49af79d19fb715` |
| `modular-candidate/reports/module-manifests.json` | 6,974,619 | `80a35694001f2e4d1cbecdc17c2c52b4f7d2bc1f435ae9a2b5c3e262dde5aa16` |
| `modular-acceptance/reports/modular-product-summary.json` | 2,017 | `27ae1e93b6b47a767c9fcf4be643d945c73dbbe055ec67e3f78f3ea55c46e8b9` |
| `旧 artifact / archive-members.json` | 2,780,657 | `a1956c5f7e6315fa65392a1afe24bd060033f86f41f99eca5660822a4e888b52` |
| `旧固定报告 / docs/evidence/visionworkshop-package-size-audit-20261125.json` | 41,735 | `1e198ff18b0c9d8e54b2cf1f60eed10015e25184967b83d0f6433f49d2748a25` |

## 3. 每个 ZIP 的实际压缩账本

“成员压缩字节”包含所有文件内容的压缩结果，包含压缩后的 manifest；“ZIP 结构开销”严格等于归档字节减成员压缩字节，包含 ZIP 头、目录及相关元数据。不能把未压缩 module.json 字节再加到结构开销。全部资产为 ZIP/LZMA，最大字典 256 MiB；每个资产的压缩大小均低于原构建合同的 2,147,483,647 字节上限。

| 资产 owner | 文件数 | 解压内容字节 | 成员压缩字节 | ZIP 结构开销 | ZIP 实际字节 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `core` | 11,318 | 627,674,298 | 177,753,056 | 2,663,390 | 180,416,446 |
| `runtime.science` | 2,131 | 130,405,229 | 34,750,360 | 457,956 | 35,208,316 |
| `runtime.torch` | 12,052 | 4,557,557,572 | 1,862,334,467 | 2,852,110 | 1,865,186,577 |
| `runtime.vision` | 2,347 | 65,140,191 | 13,732,569 | 549,018 | 14,281,587 |
| `feature.patchcore` | 8,474 | 273,384,734 | 74,825,635 | 1,808,778 | 76,634,413 |
| `feature.yolo` | 552 | 168,331,914 | 28,715,069 | 113,416 | 28,828,485 |
| `resource.edgesam` | 3 | 40,678,572 | 35,560,449 | 488 | 35,560,937 |
| `resource.image-simplification` | 4 | 88,254,627 | 80,566,317 | 764 | 80,567,081 |
| `resource.patchcore-cnn` | 5 | 275,888,591 | 248,192,578 | 944 | 248,193,522 |
| `resource.patchcore-dino` | 3 | 88,251,569 | 80,603,651 | 676 | 80,604,327 |
| `resource.yolo` | 5 | 36,728,889 | 32,295,982 | 758 | 32,296,740 |
| `runtime.ort` | 7,124 | 439,011,782 | 111,362,835 | 2,065,384 | 113,428,219 |
| **全部 12 ZIP** | **44,018** | **6,791,307,968** | **2,780,692,968** | **10,513,682** | **2,791,206,650** |

### 每个原资产 SHA256

| 原资产文件名 | SHA256 |
| --- | --- |
| `VisionWorkshop-Core-0.0.0.zip` | `ac6e5927c6f705f85d3238f1fbba01eb40b7bfb60f3eea0f69e5d3c7affcd722` |
| `runtime.science-0.0.0.zip` | `8494ced6261bf8997c6a5c42384725b268159476c42f3ab9d8711dba45089d16` |
| `runtime.torch-0.0.0.zip` | `ccbcd7b49974b8eaa8f8dfdb1bcc67d310cde85317142ffbcc8df6fa42cd9fd4` |
| `runtime.vision-0.0.0.zip` | `9be478fb6d95250961d6f98bbdc53d93a0e3b5e7f05e1e38089e7784ed21455d` |
| `feature.patchcore-0.0.0.zip` | `0e236cb6bdf7ccc928cf871e2c8488ca2ba4fcefe4da0ff1ad0b29615d64fdfa` |
| `feature.yolo-0.0.0.zip` | `2d40614b38a2c9b18bbbe8b9b201bee4d93f0f0d6d6b942783cc07f19a4e62d1` |
| `resource.edgesam-0.0.0.zip` | `fc8f55a868dc640adea28d1a18f7be0416c069e2a5a2870db82b701daac4b553` |
| `resource.image-simplification-0.0.0.zip` | `9b67dc8479ca06c38436cddcc026c3f765f9b7820840456bb2da66916a4bb5bb` |
| `resource.patchcore-cnn-0.0.0.zip` | `aa4dc32200bfaf150e390d0a7cd9bd2631c62602b55af60f53c34156e249c826` |
| `resource.patchcore-dino-0.0.0.zip` | `a78b17be815feeaad97af591979d215be703ecb09ad0e816ebdf5a48d13244ab` |
| `resource.yolo-0.0.0.zip` | `0ef95729c6bf5bf294f7ff629292e51ac4345a612c48203d691bee932c1c758e` |
| `runtime.ort-0.0.0.zip` | `cb52bcffd03aefac8fd7aa3ce7b8ce80ac9509ed4f87c776b218c0439d903d5a` |

## 4. 与旧完整 ZIP 的精确比较

| 口径 | 旧完整 ZIP | 新全部 12 ZIP | 新减旧 |
| --- | ---: | ---: | ---: |
| 文件数 | 13,174 | 44,018 | +30,844 |
| 目录条目数 | 1,687 | 0 | -1,687 |
| 解压内容字节 | 6,371,667,282 | 6,791,307,968 | +419,640,686 |
| 成员压缩字节 | 2,711,701,386 | 2,780,692,968 | +68,991,582 |
| ZIP 结构开销 | 3,815,062 | 10,513,682 | +6,698,620 |
| 交付 ZIP 总字节 | 2,715,516,448 | 2,791,206,650 | +75,690,202 |

全套交付增加 **2.787323%**；解压文件内容增加 **6.586042%**。旧 ZIP 含 1,687 个显式目录条目，新 ZIP 只收录文件。文件组织、依赖和资源集合均改变，不能将差值全部归因于压缩算法。

### 新增 DINO 资源单列

`resource.patchcore-dino`：ZIP **80,604,327 字节**；解压 **88,251,569 字节**，其中两个 payload 文件 **88,250,507 字节**、module.json **1,062 字节**。

| 新增原文件 | 大小 | SHA256 |
| --- | ---: | --- |
| `resources/dinov2-small/ed25f3a31f01632728cabb09d1542f84ab7b0056/config.json` | 547 | `1809f83e3bdb1609a501a610ad4a742f4fd8ae44d72ca4aa0df52d1f2ac8628d` |
| `resources/dinov2-small/ed25f3a31f01632728cabb09d1542f84ab7b0056/model.safetensors` | 88,249,960 | `ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1` |

旧逐成员清单的 static/models 没有 `dinov2-small/`；旧图片精简使用的 `image_simplification/dinov2_vits14/model.safetensors` 是另一份现有资源，仍单列在 `resource.image-simplification`。新增骨干不包含已训练 memory bank、阈值或原 reference/NPZ，不能代替 DINO 部署和数值验收。

| 精确分解 | 字节 |
| --- | ---: |
| 全部 12 ZIP 相对旧包增加 | +75,690,202 |
| 新增 resource.patchcore-dino ZIP | +80,604,327 |
| 其余 11 ZIP 实际合计 | 2,710,602,323 |
| 其余 11 ZIP 相对旧包变化 | -4,914,125 |

**75,690,202 = 80,604,327 − 4,914,125。** 扣除一个新增资源包只是交付集合的算术对账；其余依赖和布局仍不同，4,914,125 字节不是已经隔离归因的“模块化压缩收益”。

Core-only ZIP 比旧全功能 ZIP 少 **2,535,100,002 字节（93.356091%）**，但可选计算/模型能力尚未安装，且本候选 Core 产品验收失败。可以据此说明基础交付显著变小，不能称为等功能的小包验收成功。

## 5. 全文件同 SHA 重复统计

按完整候选的 SHA256＋大小分组，确认同一 SHA 的大小一致。非空文件和空文件分开统计；下列字节全部是**解压后内容的理论超额**，不是 ZIP 可节省量，不表示允许删除。

| 口径 | 重复组数 | 组内文件出现次数 | 理论内容超额字节 |
| --- | ---: | ---: | ---: |
| 全局非空同 SHA | 1,264 | 4,682 | 7,895,387 |
| 各 owner 内部（owner×SHA 组） | 1,252 | 4,623 | 7,204,925 |
| 跨 owner（各 owner 先保留一份） | 37 | 262 | 690,462 |

**可相加公式：7,895,387 = 7,204,925 + 690,462。** owner 内部计算 Σ(count_in_owner−1)×size；跨 owner 计算 Σ(distinct_owner_count−1)×size。跨 owner 组本身也可能有内部重复，组数/文件出现次数不能简单相加。若把跨 owner 整组按 count−1 计算，会得到 740,530 字节，其中 50,068 字节已含在 owner 内部统计，不得重复计入。

### 各 owner 内部

| Owner | 完整文件数 | 空文件 | 非空重复组 | 理论内容超额字节 |
| --- | ---: | ---: | ---: | ---: |
| `core` | 11,318 | 326 | 112 | 719,649 |
| `feature.patchcore` | 8,474 | 259 | 270 | 640,225 |
| `feature.yolo` | 552 | 7 | 4 | 760 |
| `resource.edgesam` | 3 | 0 | 0 | 0 |
| `resource.image-simplification` | 4 | 0 | 0 | 0 |
| `resource.patchcore-cnn` | 5 | 0 | 0 | 0 |
| `resource.patchcore-dino` | 3 | 0 | 0 | 0 |
| `resource.yolo` | 5 | 0 | 0 | 0 |
| `runtime.ort` | 7,124 | 17 | 830 | 3,939,104 |
| `runtime.science` | 2,131 | 50 | 12 | 16,224 |
| `runtime.torch` | 12,052 | 97 | 17 | 1,827,101 |
| `runtime.vision` | 2,347 | 15 | 7 | 61,862 |

### 最大的非空重复组（全量明细在 JSON）

| 单份字节 | 出现次数 | 理论内容超额 | Owner | 示例路径 |
| ---: | ---: | ---: | --- | --- |
| 1,242,210 | 2 | 1,242,210 | runtime.torch | `payload/site-packages/torch/_C/_VariableFunctions.pyi` |
| 129,623 | 8 | 907,361 | runtime.ort | `payload/site-packages/onnx/backend/test/data/node/test_sce_NCd1d2d3d4d5_mean_weight/test_data_set_0/input_0.pb` |
| 393,235 | 3 | 786,470 | runtime.ort | `payload/site-packages/onnx/backend/test/data/node/test_averagepool_3d_default/test_data_set_0/input_0.pb` |
| 575,056 | 2 | 575,056 | feature.patchcore, runtime.ort | `payload/site-packages/pandas.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll` |
| 573,952 | 2 | 573,952 | runtime.torch | `payload/site-packages/torch/lib/cudart64_12.dll` |
| 129,630 | 4 | 388,890 | runtime.ort | `payload/site-packages/onnx/backend/test/data/node/test_sce_NCd1d2d3d4d5_mean_weight_log_prob/test_data_set_0/output_1.pb` |
| 129,627 | 4 | 388,881 | runtime.ort | `payload/site-packages/onnx/backend/test/data/node/test_nllloss_NCd1d2d3d4d5_mean_weight/test_data_set_0/input_0.pb` |
| 51,861 | 8 | 363,027 | runtime.ort | `payload/site-packages/onnx/backend/test/data/node/test_sce_NCd1d2d3d4d5_mean_weight/test_data_set_0/input_1.pb` |
| 155,450 | 3 | 310,900 | core | `site-packages/cv2/LICENSE-3RD-PARTY.txt` |
| 51,866 | 4 | 155,598 | runtime.ort | `payload/site-packages/onnx/backend/test/data/node/test_nllloss_NCd1d2d3d4d5_mean_weight/test_data_set_0/input_1.pb` |
| 12,304 | 13 | 147,648 | runtime.ort | `payload/site-packages/onnx/backend/test/data/node/test_averagepool_2d_default/test_data_set_0/input_0.pb` |
| 131,091 | 2 | 131,091 | runtime.ort | `payload/site-packages/onnx/backend/test/data/node/test_averagepool_3d_dilations_large_count_include_pad_is_0_ceil_mode_is_True/test_data_set_0/input_0.pb` |

最大的跨 owner 同 SHA 原件是 `runtime.ort` 的 `ml_dtypes.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll` 和 `feature.patchcore` 的 `pandas.libs/` 同名文件，各 575,056 字节，SHA256 为 `a4c2229bdc2a2a630acdc095b4d86008e5c3e3bc7773174354f3da4f5beb9cde`。这是原包私有路径副本；本账本没有证明任何一个路径可删。许可、包内兼容源码和数据也可能因访问路径要求重复。

**空文件共 771 个，原始内容 0 字节，全部 SHA 为 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。** 它们仍有压缩流/ZIP 头和目录项开销；原候选报告没有逐成员 compressed_size，因此不能估算其压缩去重收益。JSON 逐项保留所有空文件路径。

旧审计的 557,851 字节是依据旧 ZIP 逐成员 compressed_size 得到的旧包理论压缩上限；本次 7,895,387 字节是新包解压内容超额。两者单位口径不同，不能作增长倍数对比。没有把理论去重当作可删除清单。

## 6. Python / Torch 的静态归属

| Python 文件 | Owner | 字节 | SHA256 |
| --- | --- | ---: | --- |
| `_internal/python3.dll` | `core` | 70,376 | `fb975a606e7fbf74f64260e3f60c3490b4f74a183c0926fd6ed1ac4c52ac7b1c` |
| `_internal/python312.dll` | `core` | 6,945,272 | `9a0e3435aaa680d868150f87ab3e388ad2eebc22f87e036155c7b4eda8cd2120` |

完整文件名扫描与原 `unique_python_files` 一致：这是**一个 CPython 运行时的两种接口 DLL**，不是两份 Python；所有可选模块没有第二个 Python EXE/DLL。产品 `VisionWorkshop.exe` 为 Core 的冻结入口。此处只确认静态交付归属，没有声称真实多进程已成功执行。

| 分发 / import root | 版本 | 唯一 owner | 实际包目录文件数 |
| --- | --- | --- | ---: |
| `torch` | `2.10.0+cu128` | `runtime.torch` | 11,591 |
| `torchvision` | `0.25.0+cu128` | `runtime.torch` | 197 |
| `torchaudio` | `2.10.0+cu128` | `runtime.torch` | 82 |

`functorch`、`torchgen` 包路径以及 torch/c10 的主要原生 DLL 也只归 `runtime.torch`。各 feature 没有另行携带另一套 Torch 分发。这里的“唯一 owner”不表示运行库内部每个 CUDA/CRT/辅助文件只有一个物理副本；完整重复统计已包含其原始路径副本。

## 7. 可审核结论与仍缺的数据

- 本次已覆盖全部 Core 文件、全部模块 payload 和每个 module.json；每个原资产的文件数、原始字节、压缩字节、结构开销、SHA 与构建身份均对账完成。输入足以形成 B3.5 的真实构建体积及重复内容账本。
- 新全套交付量比旧完整包大；新增 DINO 骨干单独解释了超过该净增量的交付字节。按需部署可减少基础下载，后续未变化模块可避免重复交付，但本账本没有新增任何产品更新验收。
- **仍缺新 ZIP 逐成员 compressed_size**，因此新包“压缩后重复内容可节省量”明确为未计算；每个 ZIP 的总压缩量/开销不受这一缺口影响。不需要假定重压结果来完成本账本。
- 解压内容字节不是实际磁盘分配量，也不含安装暂存、上一版本回退保留、用户数据和峰值空间。
- 产品资格保持 FAIL；GUI、真实模型/worker、CUDA、独立 Core 升级及其他未执行项目不因体积账本完成而被勾选。
