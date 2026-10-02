# 纯 CPU 原生构建记录

日期：2026-10-02。此记录仅固定发布组件的来源、版本、构建选项和哈希；
不公开本机用户名、绝对构建路径、原始编译日志或开发者测试配置。

## 工具链与构建

- Windows x64、Python 3.12.14 x64、CMake 3.31.10。
- Visual Studio Community 2022 17.14.41 正式版，作者已确认个人独立开发。
- MSVC cl 19.44.35229.0、Windows SDK 10.0.26100.0。
- pybind11 2.11.1、setuptools 84.0.0、wheel 0.48.0。
- oneDNN 静态 Release；CTranslate2 动态 Release；Python 扩展全部强制重编。
- MSVC `/MD`、`/GR /EHsc /utf-8`；CPU ISA 运行时分派，未以本机专用架构
  标志取代可分派路径。具体 CMake 配置见 [CPU 构建方案](CPU_ONLY_BUILD_PLAN.md)。
- CUDA/cuDNN/HIP/MKL/OpenBLAS/Ruy/Flash Attention/张量并行关闭；oneDNN CPU
  开启、GPU runtime 为 NONE，OpenMP 使用 Microsoft `vcomp140.dll`。

最终原生构建退出码 0。早期构建的编码/异常展开选项不完整，没有用于发行。
上游源码未为脱敏而删改；归档初次解压的 4,348 个文件已逐字节校验。
后续产生的构建文件与拷入 Python 包的自建 DLL 不属于原始上游源码。

## 固定源码

| 组件 | 固定提交 | 官方归档 SHA-256 |
| --- | --- | --- |
| [CTranslate2 v4.8.2](https://github.com/OpenNMT/CTranslate2/archive/refs/tags/v4.8.2.zip) | `d44d2d069eb88c7b7804da864c10c201501cb4a9` | `985ed99ee8b340d3e9a3cd36647648700674d8193e0132c89079f5c292695977` |
| [cpu_features](https://codeload.github.com/google/cpu_features/zip/8a494eb1e158ec2050e5f699a504fbc9b896a43b) | `8a494eb1e158ec2050e5f699a504fbc9b896a43b` | `4ccded88992089effa9852740b192e404e7ba26541b185ad2a4a0e8aa95a109c` |
| [spdlog](https://codeload.github.com/gabime/spdlog/zip/76fb40d95455f249bd70824ecfcae7a8f0930fa3) | `76fb40d95455f249bd70824ecfcae7a8f0930fa3` | `9a00dd50318b9467148adc5e822e55221c65d8d8794c6890ba034eed222dcf64` |
| [oneDNN 3.1.1](https://codeload.github.com/oneapi-src/oneDNN/zip/64f6bcbcbab628e96f33a62c3e975f8535a7bde4) | `64f6bcbcbab628e96f33a62c3e975f8535a7bde4` | `eb13ce1ee920fb3537b24235fbf5d421670a135a3954e0184b77493f2abfea51` |

cpu_features 和 spdlog 的提交来自该 CTranslate2 标签的 gitlink。

## 本轮产物

| 文件 | 字节数 | SHA-256 |
| --- | --- | --- |
| `ctranslate2-4.8.2-cp312-cp312-win_amd64.whl` | 4,920,259 | `b31ad0c0ffa224da962858f10c68e35d6ad9ba5a3c2df9e5c908be9f7f46c769` |
| `ctranslate2.dll` | 17,853,440 | `b17102dbe434285d47486939fa1c914247baa76a4892393e0fe49b51c0bcfa21` |
| `_ext.cp312-win_amd64.pyd` | 715,776 | `ea7c1b4c804eed712ae0f62590ef52b21636932d06f9a52a6a3054a5ef541073` |

wheel ZIP CRC 与 ABI 标签通过；两个原生文件均为 AMD64。DLL 的实际非系统
依赖为 Microsoft v14 C/C++ 和 OpenMP 运行库；扩展还依赖 `python312.dll`
和 `ctranslate2.dll`。结合实际构建缓存及 PE 普通/延迟导入核验，未启用
CUDA/cuDNN/MKL，也不分发 Intel OpenMP DLL。

Python wheel 保留上游 metadata 中的 CUDA 分类/关键词；它们描述上游项目，
不是本次编译配置。不要仅依据关键词或“应用请求 CPU”判断原生库组成。

上游 CMake 的旧策略声明、类型窄化等编译警告仍存在，未改写上游源码来隐藏
警告。正式运行验证与已知硬件边界见 [项目说明报告](项目说明报告.md)。
