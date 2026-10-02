# CTranslate2 4.8.2 compiled dependency notices

These license files cover libraries and headers compiled into the official
CTranslate2 4.8.2 Windows wheel used by this application. The dependency set is
derived from the version-pinned build script, CMake configuration, Git submodule
commits, and Python build requirements at the CTranslate2 `v4.8.2` tag.

Included notices:

- `cpu_features` commit `8a494eb1e158ec2050e5f699a504fbc9b896a43b` (Apache-2.0)
- `spdlog` commit `76fb40d95455f249bd70824ecfcae7a8f0930fa3` (MIT)
- `fmt` 8.1.1 bundled in that exact spdlog commit (MIT with optional binary exception)
- `pybind11` 2.11.1 (BSD-3-Clause)
- NVIDIA CUTLASS commit `bbe579a9e3beb6ea6626d9227ec32d0dae119a49`
- NVIDIA CCCL/Thrust/CUB/libcu++ commit
  `b5fe509fd11a925f90d6495176707cc1184eed9d`
- BS thread pool 5.1.0 (MIT)
- Notices transcribed from CTranslate2's vendored SIMD math headers;
  `SIMD-Utils-LICENSE.txt` supplements the AVX512 header's BSD-2 notice

Primary provenance:

- https://github.com/OpenNMT/CTranslate2/tree/v4.8.2
- https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.2/.gitmodules
- https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.2/python/tools/prepare_build_environment_windows.sh
- https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.2/python/install_requirements.txt
- https://raw.githubusercontent.com/gabime/spdlog/76fb40d95455f249bd70824ecfcae7a8f0930fa3/include/spdlog/fmt/bundled/fmt.license.rst

`fmt-8.1.1-LICENSE.txt` SHA-256:
`825c9324e70f8c839c8ba910543dd4a7daee243b86ef960594c11381a19980b8`.

These notices supplement, rather than replace, the CTranslate2 MIT license,
Intel MKL/OpenMP terms, oneDNN notices, and NVIDIA terms elsewhere in the
release.
