# 对应源码与第三方致谢核验

更新日期：2026-10-02。此记录补充已识别的源码获取义务，不构成整个运行包的
法律合规保证。最终公开发布状态以 [发布许可状态](RELEASE_STATUS.md) 为准。

## MPL 对应源码

MPL-2.0 第 3.2 节要求发行可执行形式时提供对应源码及合理的获取说明；
不能只收集许可证全文。[官方许可](https://www.mozilla.org/en-US/MPL/2.0/)

下列完整源码档案随便携包位于 `LICENSES/upstream/`，可以直接解压，不需运行
程序或联系作者。各目录有原许可、版权、具体获取说明和固定官方链接；应用的
条款不限制接收者对这些 MPL 源码的权利。

| 实际组件 | 固定来源 | 便携包中的源码位置 |
| --- | --- | --- |
| ONNX Runtime 1.24.4 内嵌 Eigen | commit `1d8b82b0740839c0de7f1242a3585e3390ff5f33` | `LICENSES/upstream/onnxruntime-eigen/eigen-1d8b82b0740839c0de7f1242a3585e3390ff5f33.tar.gz` |
| tqdm 4.70.1 的 MPL 部分 | 官方 PyPI 4.70.1 sdist | `LICENSES/upstream/tqdm-4.70.1/tqdm-4.70.1.tar.gz` |
| certifi 2026.7.22 的证书与源码 | 官方 PyPI 2026.7.22 sdist | `LICENSES/upstream/certifi-2026.7.22/certifi-2026.7.22.tar.gz` |

源码 Git 导出不附带这些依赖档案，避免把完整第三方源码重复提交到应用仓库。
仓库的 `packaging/extra-notices/` 中保留获取说明和固定下载地址；完整便携包
另外保留离线副本。不要从便携发行文件中删除它们。

### Eigen 的精确范围

ONNX Runtime 官方 v1.24.4 Windows CPU wheel 配方请求 `--use_vcpkg`；对应
Eigen port 固定上述提交，并未指定 C++ 源码补丁，编译定义含
`EIGEN_MPL2_ONLY`。它不是未修改的 Eigen 3.4.0 发布档案。

同一标签中的非 vcpkg 路线有两份 s390x patch，已原样保留以说明区别，但不
声称 Windows CPU wheel 使用了这些补丁。上游构建配方是版本依据，并不等于
本项目独立重建该 wheel 后得到了完全相同的二进制。

- [Windows CPU wheel 配方](https://github.com/microsoft/onnxruntime/blob/v1.24.4/tools/ci_build/github/azure-pipelines/templates/py-win-cpu.yml)
- [固定 Eigen port](https://github.com/microsoft/onnxruntime/blob/v1.24.4/cmake/vcpkg-ports/eigen3/portfile.cmake)
- [Eigen 对应源码](https://codeload.github.com/eigen-mirror/eigen/tar.gz/1d8b82b0740839c0de7f1242a3585e3390ff5f33)

### Python 组件的对应性

tqdm 官方 wheel、sdist 与本次打包环境的 31 个 Python 文件逐字节一致。
certifi 的 5 个 Python 文件及证书 PEM 在官方 wheel、sdist 与打包环境中一致；
当前便携包的 `_internal/certifi/cacert.pem` 也相同。未识别到项目对这两者的补丁。

- [tqdm 4.70.1 官方发行](https://pypi.org/project/tqdm/4.70.1/)
- [certifi 2026.7.22 官方发行](https://pypi.org/project/certifi/2026.7.22/)

归档 SHA-256：

- Eigen：`c8adb6532fbfacd2ec1418c66404159b00c34d855bdc19cefa1f0db0e5e0aa5f`
- tqdm：`cefd0eca11b2a37a3aee776544d4f4ae913f02688135b5556b8788dfa474afc4`
- certifi：`741e2c3b351ddf169a738da9f2c048608ff7f2c5cc02f1ebc6b118bb090d5d55`
- 便携包 CA PEM：`9cc2a774b5198dcff14d9be1e66091f538975d867ce029a96bce15a55dfd730f`

## 不从通用声明推断实际包含组件

当前 OpenCV 5.0.0.93 的构建信息为 `Eigen: NO`。其上游 wheel 虽具备
FFmpeg 插件，当前打包配置已排除插件；候选包无 FFmpeg DLL，`cv2.pyd`
导入表无 FFmpeg。通用第三方声明含 MPL/LGPL 文本不证明当前包包含这些
组件。升级或改变打包配置后必须重新核对，不可长期沿用此结论。

Qt/PySide/Shiboken 6.9.3 和 GEOS 3.13.1 的对应源码、LGPL 全文和动态替换
说明已随包保留；具体路径见 README 与原生核验记录。本次 MPL 核验不替代
它们各自的 LGPL 条件检查。

## FreeType 与 JPEG 致谢

Pillow 的实际字体组件报告 FreeType 2.14.3，与当前候选包组件哈希一致。
本次按 FreeType License (FTL) 使用，而不是选择其备用 GPL 许可；完整 FTL
保留在 `LICENSES/Pillow/`。因此不应仅因声明中出现备用 GPL 文本而推断应用
需要采用 GPL。[FreeType 官方许可选择说明](https://freetype.org/license.html)

本软件部分基于 [FreeType Team](https://freetype.org) 的工作。
This software is based in part on the work of the Independent JPEG Group.
这两项致谢也保留在便携包 README 中，不仅存放在上游许可证全文内。

## 最终导出核验

确认便携 ZIP 真正保留三个 MPL 源码档案、原许可及获取说明；确认源码 ZIP
保留对应 README、证据文本和 patch。核对档案完整性与上述哈希，同时保留
现有 Qt/GEOS 源码副本。不把源码获取项完成描述为 CUDA 或 Microsoft
运行库发行条件已经完成。
