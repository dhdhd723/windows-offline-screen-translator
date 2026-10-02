# Intel OpenMP runtime redistribution evidence

Runtime file: `libiomp5md.dll`, 1,614,192 bytes.

- Bundled DLL SHA-256: `982233366b0afcda1e0f55a0b134097e35b779613f54ddb69e685e6cd06b755f`
- File copyright: Copyright (C) 1997-2025, Intel Corporation. All rights reserved.
- Official package: `intelopenmp.redist.win` 2025.3.0.640, owned by Intel Corporation.
- Official package page: https://www.nuget.org/packages/intelopenmp.redist.win/2025.3.0.640
- Official package SHA-256: `a4212c4aec3e528864d56d8b0c87103cd5c21a888d1985124909a1f85624a449`

The bundled DLL is byte-for-byte identical to
`runtimes/win-x64/native/libiomp5md.dll` in that official redistribution
package. This is an exact SHA-256 match, not an inference from the version
resource or file name.

The package declares the **Intel Simplified Software License (Version October
2022)**. Its official license page is:
https://www.nuget.org/packages/intelopenmp.redist.win/2025.3.0.640/License

The unmodified files retained here are:

- `LICENSE.txt`, SHA-256
  `6c00ae54b2a610ea009e0f5c5d3aa79023eb694c7fb72857654c53c6e99d7c97`.
- `third-party-programs.txt`, SHA-256
  `f8ce918fe7311ce279e68380a2e233f8a42b1cd3dda8f4c48d6de97a0255c1d7`.

The license permits use and redistribution of the unmodified binary subject to
its stated conditions. In particular, the Intel copyright and license terms
must accompany redistribution; Intel and supplier names must not be used for
endorsement without permission; and the binary must not be modified, reverse
engineered, decompiled, or disassembled. Read `LICENSE.txt` for the controlling
text. The package metadata states `Copyright Intel Corporation.`

The upstream CTranslate2 4.8.2 Windows build recipe also explicitly copies the
OpenMP DLL from Intel oneAPI 2025.3:
https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.2/python/tools/prepare_build_environment_windows.sh

The downloaded wheel kept beside these files in the private development tree is
provenance evidence only. Public export filters exclude `.whl` files.
