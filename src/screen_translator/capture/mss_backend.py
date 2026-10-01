from __future__ import annotations

import threading

import numpy as np

from screen_translator.contracts import Region


class MSSCaptureBackend:
    """Own and use MSS exclusively on the capture thread."""

    def __init__(self) -> None:
        import mss
        self._owner = threading.get_ident()
        self._capture = mss.mss()

    def grab(self, region: Region) -> np.ndarray:
        if threading.get_ident() != self._owner:
            raise RuntimeError("Screen capture must remain on its owning thread")
        shot = self._capture.grab({"left": region.x, "top": region.y,
                                   "width": region.width, "height": region.height})
        return np.asarray(shot)[:, :, :3].copy()

    def close(self) -> None:
        self._capture.close()
