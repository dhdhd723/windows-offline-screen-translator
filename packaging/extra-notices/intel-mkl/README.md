# Intel oneMKL redistribution notices

CTranslate2 4.8.2 enables MKL by default. Its official Windows build recipe
installs Intel oneAPI MKL 2025.3, and its CMake configuration links the MKL core,
ILP64 and threaded libraries into `ctranslate2.dll`.

Build sources:

- https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.2/python/tools/prepare_build_environment_windows.sh
- https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.2/CMakeLists.txt

The unmodified license and third-party notice files in this directory come from
Intel's official `intelmkl.redist.win-x64` 2025.3.0.453 package:
https://www.nuget.org/packages/intelmkl.redist.win-x64/2025.3.0.453

Official license page:
https://www.nuget.org/packages/intelmkl.redist.win-x64/2025.3.0.453/License

Downloaded package SHA-256:
`a8da1d8e71f7f8eeec5eb9dcca0e35cf948b925ef469be4da07b76e2c0306275`.

`LICENSE.txt` is the Intel Simplified Software License (Version October 2022)
for oneMKL. It permits redistribution of the unmodified binary subject to its
conditions, including reproducing the copyright and license terms. All text
files from the package's `share/doc/mkl/licensing` directory are retained here
so nested third-party notices are not lost. Static linking prevents a useful
standalone DLL hash comparison, so the evidence is the version-pinned official
CTranslate2 build recipe plus Intel's corresponding 2025.3 redistribution
package. Read the included texts for the controlling terms.
