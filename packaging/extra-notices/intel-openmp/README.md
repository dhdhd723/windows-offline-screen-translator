# Intel OpenMP runtime evidence and notices

Runtime file: `libiomp5md.dll`, 1,614,192 bytes.
Original DLL SHA-256:
`982233366b0afcda1e0f55a0b134097e35b779613f54ddb69e685e6cd06b755f`.
File copyright: Copyright (C) 1997-2025, Intel Corporation. All rights reserved.

The DLL in the application's CTranslate2 4.8.2 wheel is byte-identical to the DLL
in Intel's official `intel-openmp` 2025.3.0 Windows wheel. This was verified by
reading both DLLs and comparing SHA-256, not by assuming that version 5.0 in the
DLL properties identifies a particular source license.

The upstream CTranslate2 release build recipe selects Intel oneAPI 2025.3.0:
https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.2/python/tools/prepare_build_environment_windows.sh

Official release metadata:
https://pypi.org/pypi/intel-openmp/2025.3.0/json

Official Windows wheel:
https://files.pythonhosted.org/packages/79/69/05addedd727061b61a85b4fd989754edb628b5be1cd5d161727f98cf4d86/intel_openmp-2025.3.0-py2.py3-none-win_amd64.whl

Wheel SHA-256:
`8ff899d01a41b92ffe0e618b221ea633127d16df726086082d381c431c31339d`.

The two unmodified notice files extracted from that wheel are retained here:

- `LICENSE.txt`: Intel End User License Agreement for Developer Tools,
  Version August 2024; SHA-256
  `febfb69a5b058f55892dc7f341108a9ca29d50e9fe85723a57eebbb826436958`.
- `third-party-programs.txt`: OpenMP Runtime library notices; SHA-256
  `f8ce918fe7311ce279e68380a2e233f8a42b1cd3dda8f4c48d6de97a0255c1d7`.

The matching binary distributor identifies the Intel EULA as its license. Do not
substitute the LLVM source project's Apache license for this binary without
further evidence from Intel.

## Unresolved redistribution documentation

The Intel EULA grants distribution for designated Redistributables and refers to
`redist.txt`, `redist-rt.txt` or similar designation files. No such designation
file is included in the matched Windows wheel. Its OpenMP notice also refers to
oneTBB notices that are not included in that wheel. This directory preserves the
exact matching distributor notices; it does not establish that all documentation
required for a public or commercial redistribution has been obtained. Obtain
version-matched designation and applicable nested notices from Intel or the
binary distributor before a broader public release. The Intel EULA reference
page likewise says the package's bundled EULA controls:
https://www.intel.com/content/www/us/en/developer/articles/license/end-user-license-agreement.html

The downloaded `.whl` is a developer-side provenance artifact, not a runtime
dependency. The released application needs the notice files, not this wheel.
