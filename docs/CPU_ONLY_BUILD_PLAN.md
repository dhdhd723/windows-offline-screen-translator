# 纯 CPU CTranslate2 构建方案

此方案用于解决当前预编译 Windows wheel 中 CUDA 残留的分发核验问题。
2026-10-02 已完成同版本纯 CPU 原生库及 Python 扩展重建，构建退出码为 0。
采用独立构建及打包目录，旧候选包保留不变；是否完成整个运行包验收以
[发布状态](RELEASE_STATUS.md) 和 [项目说明报告](项目说明报告.md) 为准。

## 固定组件与构建环境

- Windows x64、Python 3.12 x64，与现有便携包的 Python ABI 相同。
- CTranslate2 v4.8.2，使用官方标签及其 spdlog/cpu_features 固定子模块提交。
- oneDNN v3.1.1，采用 Apache-2.0 许可的源码构建 CPU INT8 后端。
- pybind11 2.11.1，版本来自 CTranslate2 的 `python/install_requirements.txt`。
- MSVC x64 编译器、Windows SDK、CMake；实际安装版本和 REDIST 清单需记录。
- 优先固定 CMake 3.31.x。oneDNN 3.1.1 的最低 CMake 声明较旧；如改用
  CMake 4，需显式传入 `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` 并重新验证构建，
  不能直接用未记录版本的系统 CMake。
- 对个人开发自己的项目，优先使用满足个人许可的免费 Visual Studio Community
  2022 加最小 C++ 工作负载；组织项目另核使用资格。单独 Build Tools 的
  开源依赖例外不能自动代替应用和发行者资格确认。

2026-10-02 已准备并核对独立源码树：CTranslate2 的提交为
`d44d2d069eb88c7b7804da864c10c201501cb4a9`，oneDNN 的提交为
`64f6bcbcbab628e96f33a62c3e975f8535a7bde4`；cpu_features 和 spdlog 使用
该 CT 标签的固定 gitlink。4,348 个解压文件与四个官方源码归档逐字节一致，
归档 CRC 通过。独立 Python 3.12 构建环境、pybind11 2.11.1、CMake 3.31.10
和应用打包环境已备齐。Community 2022 正式版 17.14.41 安装成功，安装器
退出码为 0，无需重启；MSVC x64 编译器 19.44.35229.0、SDK 10.0.26100.0
已核对。SDK 位置按注册表 KitsRoot10 读取，不假定一定在系统盘。
最终采用修正后的 Release 构建，而非先前试构建。新的 wheel 标签为
`cp312-cp312-win_amd64`，大小 4,920,259 字节，ZIP CRC 已核对。精确二进制
哈希见 [原生构建记录](CPU_BUILD_PROVENANCE.md)。

## 原生库构建配置

先以静态库构建 oneDNN，关闭例子和测试，启用 CPU OpenMP 运行时。oneDNN
源码、构建输出和安装前缀都放在独立目录，不写入当前运行包。

```text
DNNL_LIBRARY_TYPE=STATIC
DNNL_BUILD_EXAMPLES=OFF
DNNL_BUILD_TESTS=OFF
ONEDNN_BUILD_GRAPH=OFF
DNNL_CPU_RUNTIME=OMP
DNNL_GPU_RUNTIME=NONE
DNNL_BLAS_VENDOR=NONE
DNNL_ENABLE_WORKLOAD=INFERENCE
DNNL_ENABLE_PRIMITIVE=CONVOLUTION;REORDER
DNNL_ARCH_OPT_FLAGS=
DNNL_ENABLE_JIT_PROFILING=OFF
DNNL_ENABLE_ITT_TASKS=OFF
CMAKE_INSTALL_LIBDIR=lib
CMAKE_MSVC_RUNTIME_LIBRARY=MultiThreadedDLL
CMAKE_POLICY_DEFAULT_CMP0091=NEW
CMAKE_C_FLAGS=/DWIN32 /D_WINDOWS /W3 /utf-8
CMAKE_CXX_FLAGS=/DWIN32 /D_WINDOWS /W3 /GR /EHsc /utf-8
```

随后构建 CTranslate2，显式指定 oneDNN 的头文件和静态库路径：

```text
BUILD_SHARED_LIBS=ON
BUILD_CLI=OFF
BUILD_TESTS=OFF
WITH_MKL=OFF
WITH_DNNL=ON
WITH_CUDA=OFF
WITH_CUDNN=OFF
WITH_HIP=OFF
WITH_OPENBLAS=OFF
WITH_RUY=OFF
WITH_ACCELERATE=OFF
WITH_FLASH_ATTN=OFF
WITH_TENSOR_PARALLEL=OFF
OPENMP_RUNTIME=COMP
ENABLE_CPU_DISPATCH=ON
CMAKE_MSVC_RUNTIME_LIBRARY=MultiThreadedDLL
CMAKE_C_FLAGS=/DWIN32 /D_WINDOWS /W3 /utf-8
CMAKE_CXX_FLAGS=/DWIN32 /D_WINDOWS /W3 /GR /EHsc /utf-8
DNNL_INCLUDE_DIR=<oneDNN install>/include
DNNL_LIBRARY=<oneDNN install>/lib/dnnl.lib
```

`OPENMP_RUNTIME=COMP` 使用编译器对应的 OpenMP 运行库，避免依赖 Intel 开发
工具链；其 Microsoft runtime 仍按 REDIST 和适用许可处理。oneDNN 后端在
CTranslate2 的 primitives 源码中提供浮点与 INT8-family GEMM，因此不需要
启用 MKL 或 CUDA 才能继续使用现有 INT8 翻译模型。

不能将 MSVC 的 `CMAKE_CXX_FLAGS` 仅设为 `/utf-8`，这样会丢失正常异常展开
选项 `/EHsc`；本次最终配置同时保留 RTTI、异常展开和 UTF-8 编码。Python
扩展以 `/EHsc` 编译，并通过进程级 `CL=/utf-8` 保持源码编码，执行
`setup.py build_ext --force` 后生成 wheel，不复用旧扩展。Windows 子进程环境
使用大小写去重的字典，避免宿主同时传入 `Path`/`PATH` 使 MSBuild 启动失败。

## Python 扩展与重新打包

1. 在独立 Python 构建环境中安装 pybind11 2.11.1、setuptools 和 wheel。
2. 将 `CTRANSLATE2_ROOT` 指向新 CTranslate2 原生库的安装前缀。
3. 将新 `ctranslate2.dll` 放入该标签的 Python package，构建 cp312-win_amd64
   wheel。同时重新编译 `_ext`；不只替换 DLL 来猜测原 Python 扩展的 ABI 兼容。
4. 记录源码提交、所有 CMake 配置、编译器版本及 wheel/运行库哈希。
5. 在独立应用打包环境中安装该本地 wheel，运行同一套 PyInstaller 构建流程。
6. 收集实际 CPU 构建引入的许可与源码声明，核对 Microsoft REDIST；删除候选
   包中已不再分发组件的说明时，依据新文件清单而不是根据应用选项推测。
7. 将原模型按清单复制至新包，核对全部模型哈希。

## 最终验收

- 原生依赖检查确认没有 CUDA/cuDNN 库、CUDA 编译内容或未计划的 Intel MKL
  依赖。仅检查 PE import table 不足以排除静态 CUDA 内容，必须结合构建配置。
- `get_supported_compute_types('cpu')` 包含当前翻译模型需要的 INT8 计算类型。
- 两个翻译方向、生成图像 OCR、自检阻止的 Python 网络连接尝试均通过。
- 比较冷启动/热译延迟与内存占用，不把特定设备测量当作所有设备保证。
- 快捷键、框选、字幕、托盘、停止/清空语义及 UI 响应回归通过。
- Microsoft 分发资格与最终用户条款确认，第三方声明和对应 LGPL 源码保留。
- 新包通过隐私扫描和 ZIP 完整性检查后，更新发布状态并生成最终 Release。

参考：

- https://github.com/OpenNMT/CTranslate2/tree/v4.8.2
- https://github.com/oneapi-src/oneDNN/tree/v3.1.1
- https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/
- https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution
