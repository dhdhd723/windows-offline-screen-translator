# 原生二进制再分发核验记录

核验日期：2026-10-02。当前采用新重建的纯 CPU CTranslate2；Intel/MKL/CUDA
部分为旧候选包的历史核验，不表示这些二进制仍进入新包。本记录用于固定技术证据和发布时
必须携带的文件，不构成法律意见；依赖版本或二进制发生变化后必须重新核验。

完整发布状态和验收范围见 [发布许可状态](RELEASE_STATUS.md)。不要将旧候选
ZIP 更名后当作本轮运行包。

## 当前纯 CPU 组件

同版本 CTranslate2 4.8.2 与 Python 扩展已以合法安装的 Community/MSVC 重建，
`WITH_CUDA/CUDNN/HIP/MKL=OFF`，`WITH_DNNL=ON`；oneDNN 3.1.1 静态 CPU 后端
使用 Microsoft OpenMP。新 `ctranslate2.dll` 的 SHA-256 为
`b17102dbe434285d47486939fa1c914247baa76a4892393e0fe49b51c0bcfa21`。
具体源码固定提交、配置、ABI 和所有原生哈希见 [构建记录](CPU_BUILD_PROVENANCE.md)。

新包不采用旧 CUDA-enabled 官方 CT wheel，不分发 `libiomp5md.dll`、MKL、
CUDA 或 cuDNN 二进制。普通与延迟导入检查结合构建缓存，而非仅凭应用
请求 CPU 下结论。oneDNN、cpu_features、spdlog/fmt、pybind11、BS thread pool
及 SIMD headers 的原许可继续保留。微软运行库采用官方未修改原件并要求
用户明确接受保护条款，依据见 [微软核验](MICROSOFT_RUNTIME_TERMS.md)。

Qt/PySide/Shiboken 6.9.3、GEOS 3.13.1、Eigen/tqdm/certifi 对应源码及原许可证
实际随便携包保留；应用默认不保存用户屏幕内容，发行材料不包含测试缓存。

## 历史候选包的结论

旧候选包 `libiomp5md.dll` 的来源和公开再分发依据已经核实，可以随本项目的
便携包发布，前提是：DLL 保持原样、随包保留 Intel 版权/许可证及第三方
声明、不借 Intel 或其供应商名义背书，并遵守许可证中的其余限制。

旧发布包使用的 Intel Developer Tools EULA 不是这份可再分发包的准确
许可证。现已改为与官方 `intelopenmp.redist.win` 包一致的 Intel Simplified
Software License (Version October 2022)。新发布包由导出工具强制用已审核的
源码声明覆盖旧包声明，避免旧文本再次混入。历史 Intel/CUDA 声明保留作
审计依据，不代表新 CPU 包仍使用相应组件；不要删除实际仍适用的第三方文本。

## 历史候选包核验表

| 组件 | 旧包证据 | 许可证/声明 | 当时状态 |
| --- | --- | --- | --- |
| Intel OpenMP | 当前 DLL 与 Intel 官方 `intelopenmp.redist.win` 2025.3.0.640 中的 win-x64 DLL 完全同哈希 | Intel Simplified Software License + OpenMP third-party programs | 已完成精确二进制匹配 |
| Intel oneMKL | CTranslate2 4.8.2 官方 Windows 构建脚本固定 oneAPI MKL 2025.3；CMake 在 Windows 链接 MKL core/ILP64/threaded libraries | Intel oneMKL Simplified Software License + 官方 2025.3 全套 licensing 文本 | 已保留版本对应声明；静态链接无法单独做 DLL 哈希 |
| oneDNN | CTranslate2 官方构建脚本固定 oneDNN 3.1.1，并以静态库启用 | Apache-2.0 + 3.1.1 THIRD-PARTY-PROGRAMS | 已保留匹配版本原文 |
| CTranslate2 及编译依赖 | CTranslate2 4.8.2 标签、构建脚本、CMake、子模块提交和 Python 构建依赖 | CTranslate2、cpu_features、spdlog/fmt、pybind11、CUTLASS、CCCL/Thrust/CUB/libcu++、BS thread pool、SIMD headers 对应文本 | 已保留所识别编译依赖的对应声明；不等于所有分发条件已满足 |
| CUDA runtime | 官方构建启用 CUDA 12.8.1；CMake FindCUDA 默认静态 runtime，因此可能编入 DLL | NVIDIA CUDA 12.8.1 EULA 的用途及分发条件 | 待确认；计划用关闭 CUDA 的 CPU 构建消除此项 |
| Microsoft C/C++ runtime | 多份 MSVCP140 / VCRUNTIME140 DLL 随上游 wheel 与 Python 收集；签名有效 | Python Windows binary 条件、Microsoft 正式许可及 REDIST 清单 | 当前发行者适用许可资格及分发条款待确认 |
| GEOS | Shapely 2.1.2 运行报告与固定发布配方均为 GEOS 3.13.1；Windows 配方无源码 patch | LGPLv2.1 + 3.13.1 完整源码 + 上游 Windows 构建配方 | 已补对应源码与动态替换说明 |
| Eigen / tqdm / certifi | 固定上游版本、ONNX Runtime Windows vcpkg 配方与对应 Python 源码/证书比较 | MPL-2.0 / MIT 原文、对应源码档案、获取说明 | 已补已识别源码获取项；范围见对应源码核验记录 |

详情见 [对应源码与致谢核验](COPYLEFT_SOURCE_NOTICES.md)。通用 notices 中列出
某许可证不证明该组件实际编入当前二进制，须结合具体构建与文件清单。

## 历史 Intel OpenMP 精确证据

- 旧候选包文件：`_internal/ctranslate2/libiomp5md.dll`
- 大小：1,614,192 字节
- SHA-256：`982233366b0afcda1e0f55a0b134097e35b779613f54ddb69e685e6cd06b755f`
- 官方包：`intelopenmp.redist.win` 2025.3.0.640
- 官方包 SHA-256：`a4212c4aec3e528864d56d8b0c87103cd5c21a888d1985124909a1f85624a449`
- 官方包内匹配路径：`runtimes/win-x64/native/libiomp5md.dll`
- 官方包页面：https://www.nuget.org/packages/intelopenmp.redist.win/2025.3.0.640
- 官方许可证页面：https://www.nuget.org/packages/intelopenmp.redist.win/2025.3.0.640/License

两份 DLL 的 SHA-256 完全相同。随包文件位于
`LICENSES/upstream/intel-openmp/`，其中：

- `LICENSE.txt` SHA-256：`6c00ae54b2a610ea009e0f5c5d3aa79023eb694c7fb72857654c53c6e99d7c97`
- `third-party-programs.txt` SHA-256：`f8ce918fe7311ce279e68380a2e233f8a42b1cd3dda8f4c48d6de97a0255c1d7`

## 历史 oneMKL 与 oneDNN 证据

CTranslate2 4.8.2 官方 Windows 构建脚本：
https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.2/python/tools/prepare_build_environment_windows.sh

CTranslate2 4.8.2 CMake 配置：
https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.2/CMakeLists.txt

oneMKL 声明取自 Intel 官方 `intelmkl.redist.win-x64` 2025.3.0.453：

- 包页面：https://www.nuget.org/packages/intelmkl.redist.win-x64/2025.3.0.453
- 许可证：https://www.nuget.org/packages/intelmkl.redist.win-x64/2025.3.0.453/License
- 包 SHA-256：`a8da1d8e71f7f8eeec5eb9dcca0e35cf948b925ef469be4da07b76e2c0306275`

oneDNN 声明取自官方 v3.1.1 标签：

- https://github.com/oneapi-src/oneDNN/blob/v3.1.1/LICENSE
- https://github.com/oneapi-src/oneDNN/blob/v3.1.1/THIRD-PARTY-PROGRAMS

## 发布和升级规则

1. 仅上传本轮完整 CPU Release；具体验收及剩余硬件边界见 [发布许可状态](RELEASE_STATUS.md)。不要上传旧的 privacy-safe 或 candidate ZIP。
2. 不要删除便携包根目录的 `LICENSES/`、模型目录中的许可证或源码目录。
3. 不要为脱敏修改任何上游 DLL；新包原生文件或官方运行库哈希改变后，应停止沿用本记录并重新核验。
4. 升级 CTranslate2、oneDNN、Microsoft 运行库或编译工具链后，重新核对构建脚本和全部声明；如改回 Intel/CUDA 后端，必须单独重新核验，不能沿用 CPU 结论。
5. 应用自身尚未选择开源许可证，这是“他人能否使用/修改/再分发你的源码”的单独问题；不影响上述第三方证据的真实性，但正式称为开源项目前应补上应用许可证。
6. Qt/PySide、模型和其余 Python 运行依赖仍受各自随包许可证约束；本文件不替代 `LICENSES/` 内的完整文本。
