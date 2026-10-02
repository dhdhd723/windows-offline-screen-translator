# Eigen source for ONNX Runtime 1.24.4

This directory provides Eigen's source and license information for the
ONNX Runtime 1.24.4 Windows CPU dependency. Eigen's covered source files remain
under MPL-2.0; the source archive also retains its original copyright notices
and the other COPYING files. The application's license does not restrict the
recipient's rights to this source under MPL-2.0.

## Obtain the source

The accompanying release includes the complete, unmodified source snapshot:
`LICENSES/upstream/onnxruntime-eigen/eigen-1d8b82b0740839c0de7f1242a3585e3390ff5f33.tar.gz`.
It can be extracted without running the application or contacting its author.
The source-only Git repository retains this notice and the official retrieval
URL, but deliberately omits the dependency source archive. Use the accompanying
portable release for the included offline copy, or the fixed URL below.

- Eigen commit: `1d8b82b0740839c0de7f1242a3585e3390ff5f33`.
- Source: https://codeload.github.com/eigen-mirror/eigen/tar.gz/1d8b82b0740839c0de7f1242a3585e3390ff5f33
- Archive SHA-256: `c8adb6532fbfacd2ec1418c66404159b00c34d855bdc19cefa1f0db0e5e0aa5f`.
- License: `MPL-2.0.txt`, also `COPYING.MPL2` inside the source archive.

This is a commit snapshot containing fixes after 3.4.0, not the unmodified
Eigen 3.4.0 release archive. The official ONNX Runtime `deps.txt` identifies the
same commit in the Eigen GitHub mirror. Its SHA-1 is for a different ZIP archive
and must not be used to validate this TAR.GZ.

## Windows CPU wheel build evidence

The preserved files below are unmodified copies from the official
ONNX Runtime `v1.24.4` tag. Their file extensions are changed to `.txt` only to
keep the notice bundle inert:

- `onnxruntime-1.24.4-py-win-cpu.txt`: the Windows CPU wheel recipe requests
  `--use_vcpkg`.
- `onnxruntime-1.24.4-external-deps.txt`: the vcpkg route uses
  `find_package(Eigen3 CONFIG REQUIRED)` rather than `external/eigen.cmake`.
- `onnxruntime-1.24.4-eigen-vcpkg-portfile.txt`: this port pins the commit above
  and does not specify Eigen source patches. It changes the installed CMake
  configuration, not the Eigen C++ headers.
- `onnxruntime-1.24.4-compile-flags.txt`: defines `EIGEN_MPL2_ONLY`.
- `onnxruntime-1.24.4-deps.txt`: records the shared Eigen source commit.

Official paths:

- https://github.com/microsoft/onnxruntime/blob/v1.24.4/tools/ci_build/github/azure-pipelines/templates/py-win-cpu.yml
- https://github.com/microsoft/onnxruntime/blob/v1.24.4/cmake/external/onnxruntime_external_deps.cmake
- https://github.com/microsoft/onnxruntime/blob/v1.24.4/cmake/vcpkg-ports/eigen3/portfile.cmake
- https://github.com/microsoft/onnxruntime/blob/v1.24.4/cmake/adjust_global_compile_flags.cmake
- https://github.com/microsoft/onnxruntime/blob/v1.24.4/cmake/deps.txt

These identify the published upstream build recipe. They are not a claim that
the dependency's published wheel was independently reproduced byte-for-byte.

## Alternative non-vcpkg route: not the Windows CPU wheel recipe

`onnxruntime-1.24.4-eigen-non-vcpkg.txt` and the two original patch files are
provided to distinguish the other source route in the same tag. That route
applies, in order, `s390x-build.patch` and `s390x-build-werror.patch` using
`patch --binary --ignore-whitespace -p1`. Do not label these as patches applied
by the official Windows CPU wheel recipe.

- https://github.com/microsoft/onnxruntime/blob/v1.24.4/cmake/external/eigen.cmake
- https://github.com/microsoft/onnxruntime/blob/v1.24.4/cmake/patches/eigen/s390x-build.patch
- https://github.com/microsoft/onnxruntime/blob/v1.24.4/cmake/patches/eigen/s390x-build-werror.patch
- `s390x-build.patch` SHA-256:
  `6d41f4504f665bc591336c668a1aa16ffc5e0f02fe9c2f9c46c6f5660b54c849`.
- `s390x-build-werror.patch` SHA-256:
  `a1a7b0ca8382cb00542587b6bc725f59abd59ad5bb491825f7876ad6e344ef0b`.

Providing this source and notice addresses the identified source-availability
item; it does not certify all licenses or all components of the application.
