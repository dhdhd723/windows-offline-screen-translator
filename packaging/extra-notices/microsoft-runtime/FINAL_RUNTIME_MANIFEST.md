# 本轮 Microsoft v14 运行库清单

2026-10-02 CPU Windows x64 发行包使用官方正式 `vc_redist.x64.exe` 中的未修改
AMD64 原件，全部版本 `14.51.36247.0`。官方包 SHA-256 与完整 12 原件来源见
[OFFICIAL_RUNTIME_PROVENANCE.md](OFFICIAL_RUNTIME_PROVENANCE.md)。

新 staging 的 16 份已有 v14 副本以原件标准化，另按新 CTranslate2 的真实
`VCOMP140.DLL` 导入新增根运行库副本，共 17 份。保留上游带哈希后缀的加载
文件名，但文件内容逐字节匹配本表官方原件；未修改文件字节或数字签名。
备份与含本地测试内容的原始报告只保留在开发者私有目录，不随公开包发行。

## 实际包内映射

| 发行包相对路径 | 官方原件 |
| --- | --- |
| `_internal/msvcp140.dll` | `msvcp140.dll` |
| `_internal/vcruntime140.dll` | `vcruntime140.dll` |
| `_internal/vcruntime140_1.dll` | `vcruntime140_1.dll` |
| `_internal/vcomp140.dll` | `vcomp140.dll` |
| `_internal/PySide6/MSVCP140.dll` | `msvcp140.dll` |
| `_internal/PySide6/MSVCP140_1.dll` | `msvcp140_1.dll` |
| `_internal/PySide6/MSVCP140_2.dll` | `msvcp140_2.dll` |
| `_internal/PySide6/VCRUNTIME140.dll` | `vcruntime140.dll` |
| `_internal/PySide6/VCRUNTIME140_1.dll` | `vcruntime140_1.dll` |
| `_internal/shiboken6/MSVCP140.dll` | `msvcp140.dll` |
| `_internal/shiboken6/MSVCP140_1.dll` | `msvcp140_1.dll` |
| `_internal/shiboken6/VCRUNTIME140.dll` | `vcruntime140.dll` |
| `_internal/shiboken6/VCRUNTIME140_1.dll` | `vcruntime140_1.dll` |
| `_internal/shiboken6/VCOMP140.DLL` | `vcomp140.dll` |
| `_internal/numpy.libs/msvcp140-263139962577ecda4cd9469ca360a746.dll` | `msvcp140.dll` |
| `_internal/rapidfuzz.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll` | `msvcp140.dll` |
| `_internal/Shapely.libs/msvcp140-90bc62d4947a5878f1dc1057312f3be2.dll` | `msvcp140.dll` |

## 官方内容 SHA-256

| 原件 | SHA-256 |
| --- | --- |
| `msvcp140.dll` | `7c26614e1d733892c2deac7e245ce115504b1d80592dd0a01b08e3e5a55f89ca` |
| `msvcp140_1.dll` | `206c931bf90fdad8816de3b5e2ef80b2bcaa9406c89ecc05fe6fddffe251e982` |
| `msvcp140_2.dll` | `d50d7883f20d1dc6191768d3746f52dd9cac89c346ffaed5be1f110c2f34a838` |
| `vcruntime140.dll` | `d1f4225df2cd877dbf130d5668a021dce3f94118455ff5ec952061c30afc9ce7` |
| `vcruntime140_1.dll` | `a7146c08f89fe5b04541ab507cdb59ff7b44534d4ba3c668a426c6450a03434e` |
| `vcomp140.dll` | `95d4ce4a6802d1e18b5e0e1722cc30ea72ca7e033f83828f05c0b7b993fe7cbf` |

签名验证为 Windows WinVerifyTrust 缓存模式，所有目标有效，发布者为
Microsoft Corporation 或 Microsoft Windows Software Compatibility Publisher。
未联网更新吊销信息，因此不声称已经核查最新证书吊销状态。

## UCRT 与系统范围

本应用只面向 Windows 10 2004+ / Windows 11 x64。Microsoft 说明 Windows
10/11 始终使用系统 UCRT，即使应用附带其他本地版本。本轮 spec 不再分发
SDK 的 `ucrtbase.dll` 和 `api-ms-win-*` 兼容转发副本；正常 PE imports 中
仍会出现这些系统 API 名称。系统 UCRT 由 Windows Update 维护，不能据此
声称支持 Windows 7/8，也不从用户的 System32 复制文件来公开发行。

依据：[Microsoft UCRT 部署说明](https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment?view=msvc-170)。
发行者资格、首次用户确认与边界见 `source/docs/MICROSOFT_RUNTIME_TERMS.md`。
该说明不覆盖或限制 Qt/GEOS/Eigen 等组件各自原许可证的替换和源码权利。
