# Optional NVIDIA cuDNN notices

The upstream CTranslate2 4.8.2 Windows wheel includes `cudnn64_9.dll`, file
version 9.10.2.21. The application explicitly requests CPU inference; this is not
a GPU feature of the application. The DLL is not a direct or delay-loaded PE
import of `ctranslate2.dll` or `_ext.cp312-win_amd64.pyd`, but CTranslate2's Python
initialization loads DLL files present in its package directory.

If distributing this DLL, keep the unmodified official NVIDIA 9.10.2 license
agreement, cuDNN supplement and acknowledgements supplied here:

- `eula-9.10.2.html`: https://docs.nvidia.com/deeplearning/cudnn/backend/v9.10.2/reference/eula.html
- `acknowledgements-9.10.2.html`: https://docs.nvidia.com/deeplearning/cudnn/backend/v9.10.2/reference/acknowledgements.html

DLL attribution: Copyright (c) 2014-2023 NVIDIA CORPORATION & AFFILIATES.
All rights reserved.

SHA-256 of the original wheel DLL:
`9edbcdff73b0af070eb160b2ce66e59feca04aa017351d8eedcc5e8e149967d2`.

No change to the portable runtime bundle is made by this notice directory.
