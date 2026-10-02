"""Check (default) or normalize MSVC DLLs in a NEW, stopped staging bundle.

Only Microsoft-signed x64 VS 14 DLLs can be used. Apply is explicit; originals
are backed up outside the bundle. No DLL is executed and no network is used.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import uuid


OFFICIAL_NAMES = frozenset({
    "concrt140.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll", "vcamp140.dll",
    "vccorlib140.dll", "vcomp140.dll", "vcruntime140.dll", "vcruntime140_1.dll",
    "vcruntime140_threads.dll",
})
SIGNATURE_METHOD = "WinVerifyTrust; cache-only URL retrieval; revocation disabled"
SOURCE_PUBLISHERS = frozenset({"Microsoft Corporation", "Microsoft Windows Software Compatibility Publisher"})
TARGET_PUBLISHERS = SOURCE_PUBLISHERS | {"The Qt Company Oy"}
# Exact DLL bytes extracted from the audited official v14 14.51.36247.0 package.
# Updating Microsoft runtime versions requires a new provenance/hash review.
OFFICIAL_HASHES = {
    "msvcp140.dll": "7c26614e1d733892c2deac7e245ce115504b1d80592dd0a01b08e3e5a55f89ca",
    "msvcp140_1.dll": "206c931bf90fdad8816de3b5e2ef80b2bcaa9406c89ecc05fe6fddffe251e982",
    "msvcp140_2.dll": "d50d7883f20d1dc6191768d3746f52dd9cac89c346ffaed5be1f110c2f34a838",
    "msvcp140_atomic_wait.dll": "3d0cbfaa1bf3eecf5a3f4491d2960ee803cb994f30292c6adc4a07c498f60e2b",
    "msvcp140_codecvt_ids.dll": "8a65c7596ef2e6938731f5a1058e7e40145b6d97967cc649231a076b9a608d78",
    "vcruntime140.dll": "d1f4225df2cd877dbf130d5668a021dce3f94118455ff5ec952061c30afc9ce7",
    "vcruntime140_1.dll": "a7146c08f89fe5b04541ab507cdb59ff7b44534d4ba3c668a426c6450a03434e",
    "vcruntime140_threads.dll": "40f39e8cee5f5a531b4010e18b807e8fe265b908dc58f959ecb7ebc6ea6cb11a",
    "concrt140.dll": "54716f0738af891f283d213b5c8d11b25896bb8ee3097d301eae718560cf974e",
    "vcomp140.dll": "95d4ce4a6802d1e18b5e0e1722cc30ea72ca7e033f83828f05c0b7b993fe7cbf",
    "vccorlib140.dll": "09f93d5ff96ae09767f3e1af3cdd43a5a58f2598654fc63089429bb6f9f4737f",
    "vcamp140.dll": "dc283ffb87e9b82e687ed4e899ae062a209aa338207abfc9a89d61407d678bd4",
}


class ValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class DLLInfo:
    architecture: str
    version: tuple[int, int, int, int]
    signature_valid: bool
    publisher: str

    def public(self) -> dict:
        return {"architecture": self.architecture, "version": ".".join(map(str, self.version)),
                "signature": {"valid": self.signature_valid, "publisher": self.publisher,
                              "method": SIGNATURE_METHOD}}


def canonical_name(filename: str) -> str | None:
    name = filename.lower()
    if name in OFFICIAL_NAMES:
        return name
    match = re.fullmatch(r"(.+)-([0-9a-f]{32})\.dll", name)
    candidate = match.group(1) + ".dll" if match else ""
    return candidate if candidate in OFFICIAL_NAMES else None


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def reject_links(path: Path) -> None:
    # Inspect original components BEFORE resolving; resolve alone hides links.
    original = path.absolute()
    for part in (*reversed(original.parents), original):
        if not part.exists() and not part.is_symlink():
            continue
        stat = part.lstat()
        if part.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
            raise ValidationError("Refusing symbolic links, junctions or reparse points")
        if part.is_file() and stat.st_nlink > 1:
            raise ValidationError("Refusing hard-linked files")


def checked_root(path: Path, existing: bool) -> Path:
    reject_links(path)
    resolved = path.resolve(strict=existing)
    if existing and not resolved.is_dir():
        raise ValidationError("Input must be an existing directory")
    if not existing and resolved.exists():
        raise ValidationError("Report and backup directories must be new")
    return resolved


def roots_disjoint(paths: list[Path]) -> None:
    for index, left in enumerate(paths):
        for right in paths[index + 1:]:
            if left == right or left.is_relative_to(right) or right.is_relative_to(left):
                raise ValidationError("Input, report and backup roots must not overlap")


def checked_file(root: Path, relative: str) -> Path:
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts or not value.parts:
        raise ValidationError("Expected a relative file inside its declared root")
    result = root / value
    reject_links(result)
    if not result.resolve().is_relative_to(root) or not result.is_file():
        raise ValidationError("Required file is missing or outside its root")
    return result


def pe_architecture(path: Path) -> str:
    with path.open("rb") as handle:
        header = handle.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise ValidationError("DLL is not a PE image")
        offset = struct.unpack_from("<I", header, 60)[0]
        if offset < 64 or offset > path.stat().st_size - 6:
            raise ValidationError("Invalid PE header offset")
        handle.seek(offset)
        pe = handle.read(6)
    if pe[:4] != b"PE\0\0":
        raise ValidationError("Invalid PE signature")
    return {0x8664: "x64", 0x14C: "x86", 0xAA64: "arm64"}.get(struct.unpack_from("<H", pe, 4)[0], "unknown")


def _file_version(path: Path) -> tuple[int, int, int, int]:
    api = ctypes.WinDLL("version", use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                 ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    size = api.GetFileVersionInfoSizeW(str(path), None)
    data = ctypes.create_string_buffer(size)
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not size or not api.GetFileVersionInfoW(str(path), 0, size, data) or not api.VerQueryValueW(data, "\\", ctypes.byref(pointer), ctypes.byref(length)) or length.value < 52:
        raise ValidationError("DLL has no valid fixed version resource")
    fields = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
    if fields[0] != 0xFEEF04BD:
        raise ValidationError("Invalid fixed version resource")
    return fields[2] >> 16, fields[2] & 0xFFFF, fields[3] >> 16, fields[3] & 0xFFFF


def _authenticode(path: Path) -> tuple[bool, str]:
    class GUID(ctypes.Structure):
        _fields_ = [("data1", wintypes.DWORD), ("data2", wintypes.WORD),
                    ("data3", wintypes.WORD), ("data4", ctypes.c_ubyte * 8)]
    class FILE_INFO(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("path", wintypes.LPCWSTR),
                    ("handle", wintypes.HANDLE), ("subject", ctypes.c_void_p)]
    class TRUST_DATA(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("policy", ctypes.c_void_p),
                    ("sip", ctypes.c_void_p), ("ui", wintypes.DWORD),
                    ("revocation", wintypes.DWORD), ("choice", wintypes.DWORD),
                    ("file", ctypes.POINTER(FILE_INFO)), ("state_action", wintypes.DWORD),
                    ("state", wintypes.HANDLE), ("url", wintypes.LPWSTR),
                    ("flags", wintypes.DWORD), ("context", wintypes.DWORD),
                    ("settings", ctypes.c_void_p)]
    action = GUID(0x00AAC56B, 0xCD44, 0x11D0, (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0, 0xC0, 0x4F, 0xC2, 0x95, 0xEE))
    file_info = FILE_INFO(ctypes.sizeof(FILE_INFO), str(path), None, None)
    trust = TRUST_DATA()
    trust.size, trust.ui, trust.choice = ctypes.sizeof(TRUST_DATA), 2, 1
    trust.file, trust.state_action, trust.flags = ctypes.pointer(file_info), 1, 0x1000
    api = ctypes.WinDLL("wintrust", use_last_error=True)
    api.WinVerifyTrust.argtypes = [wintypes.HWND, ctypes.POINTER(GUID), ctypes.POINTER(TRUST_DATA)]
    api.WinVerifyTrust.restype = wintypes.LONG
    try:
        valid = api.WinVerifyTrust(wintypes.HWND(-1), ctypes.byref(action), ctypes.byref(trust)) == 0
    finally:
        trust.state_action = 2
        api.WinVerifyTrust(wintypes.HWND(-1), ctypes.byref(action), ctypes.byref(trust))

    # Read the actual signing certificate, not version-resource CompanyName.
    class BLOB(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]
    class ALGORITHM(ctypes.Structure):
        _fields_ = [("oid", ctypes.c_char_p), ("parameters", BLOB)]
    class SIGNER(ctypes.Structure):
        _fields_ = [("version", wintypes.DWORD), ("issuer", BLOB), ("serial", BLOB)]
    class CERT_INFO(ctypes.Structure):
        _fields_ = [("version", wintypes.DWORD), ("serial", BLOB),
                    ("algorithm", ALGORITHM), ("issuer", BLOB), ("tail", ctypes.c_byte * 256)]
    crypto = ctypes.WinDLL("crypt32", use_last_error=True)
    crypto.CryptQueryObject.argtypes = [wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
    crypto.CryptMsgGetParam.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    crypto.CertFindCertificateInStore.argtypes = [wintypes.HANDLE, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    crypto.CertFindCertificateInStore.restype = ctypes.c_void_p
    crypto.CertGetNameStringW.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                        ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD]
    crypto.CertFreeCertificateContext.argtypes = [ctypes.c_void_p]
    crypto.CertCloseStore.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    crypto.CryptMsgClose.argtypes = [wintypes.HANDLE]
    store, message, certificate = wintypes.HANDLE(), wintypes.HANDLE(), None
    publisher = ""
    try:
        if not crypto.CryptQueryObject(1, ctypes.cast(ctypes.c_wchar_p(str(path)), ctypes.c_void_p),
                                      1 << 10, 2, 0, None, None, None,
                                      ctypes.byref(store), ctypes.byref(message), None):
            return False, publisher
        size = wintypes.DWORD()
        if not crypto.CryptMsgGetParam(message, 6, 0, None, ctypes.byref(size)):
            return False, publisher
        buffer = ctypes.create_string_buffer(size.value)
        if not crypto.CryptMsgGetParam(message, 6, 0, buffer, ctypes.byref(size)):
            return False, publisher
        signer = ctypes.cast(buffer, ctypes.POINTER(SIGNER)).contents
        info = CERT_INFO()
        info.issuer, info.serial = signer.issuer, signer.serial
        certificate = crypto.CertFindCertificateInStore(store, 0x10001, 0, 11 << 16, ctypes.byref(info), None)
        if not certificate:
            return False, publisher
        length = crypto.CertGetNameStringW(certificate, 4, 0, None, None, 0)
        name = ctypes.create_unicode_buffer(length)
        crypto.CertGetNameStringW(certificate, 4, 0, None, name, length)
        publisher = name.value
        return valid, publisher
    finally:
        if certificate:
            crypto.CertFreeCertificateContext(certificate)
        if message:
            crypto.CryptMsgClose(message)
        if store:
            crypto.CertCloseStore(store, 0)


def inspect_dll(path: Path) -> DLLInfo:
    if sys.platform != "win32":
        raise ValidationError("Authenticode and version preflight require Windows")
    valid, publisher = _authenticode(path)
    return DLLInfo(pe_architecture(path), _file_version(path), valid, publisher)


def native_import_names(path: Path) -> set[str]:
    import pefile
    try:
        image = pefile.PE(str(path), fast_load=True)
        try:
            image.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                                      pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
            return {entry.dll.decode("ascii").lower() for kind in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
                    for entry in getattr(image, kind, [])}
        finally:
            image.close()
    except (pefile.PEFormatError, UnicodeError) as exc:
        raise ValidationError("Native-import input is not a valid PE image") from exc


def _validate_info(info: DLLInfo, *, source: bool = True) -> None:
    publishers = SOURCE_PUBLISHERS if source else TARGET_PUBLISHERS
    if info.architecture != "x64" or info.version[0] != 14 or not info.signature_valid or info.publisher not in publishers:
        raise ValidationError("Expected an Authenticode-valid approved-publisher x64 VS 14 DLL")


def preflight(bundle: Path, source: Path, *, native_imports: list[str] | None = None,
              inspector=inspect_dll, import_reader=native_import_names) -> dict:
    bundle, source = checked_root(bundle, True), checked_root(source, True)
    roots_disjoint([bundle, source])
    checked_file(bundle, "ScreenTranslator.exe")
    if not (bundle / "_internal").is_dir():
        raise ValidationError("Expected a ScreenTranslator staging bundle with _internal")
    for root in (bundle, source):
        for path in root.rglob("*"):
            reject_links(path)
    sources = {}
    for path in source.iterdir():
        if path.suffix.lower() != ".dll":
            continue
        name = path.name.lower()
        if name not in OFFICIAL_NAMES or name in sources:
            raise ValidationError("Source contains an unexpected or duplicate DLL")
        info = inspector(path)
        _validate_info(info)
        checksum = sha256(path)
        if checksum != OFFICIAL_HASHES.get(name):
            raise ValidationError("Source DLL does not match the audited official package hash")
        sources[name] = {"file": path.name, "sha256": checksum, **info.public()}
    if set(sources) != OFFICIAL_NAMES:
        raise ValidationError("Official source DLL set is incomplete")
    if len({record["version"] for record in sources.values()}) != 1:
        raise ValidationError("Official runtime files do not share one fixed version")
    sources = dict(sorted(sources.items()))
    actions = []
    for path in sorted((bundle / "_internal").rglob("*")):
        canonical = canonical_name(path.name) if path.is_file() else None
        if canonical is None:
            continue
        info = inspector(path)
        _validate_info(info, source=False)
        if info.version > tuple(map(int, sources[canonical]["version"].split("."))):
            raise ValidationError("Refusing to downgrade an existing runtime DLL")
        actions.append({"action": "replace", "target": path.relative_to(bundle).as_posix(),
                        "source": sources[canonical]["file"], "before": {"sha256": sha256(path), **info.public()},
                        "after": sources[canonical]})
    native_records = []
    needs_vcomp = False
    for relative in native_imports or []:
        path = checked_file(bundle, relative)
        if pe_architecture(path) != "x64":
            raise ValidationError("Native import input must be x64")
        names = import_reader(path)
        needed = "vcomp140.dll" in names
        needs_vcomp |= needed
        native_records.append({"file": path.relative_to(bundle).as_posix(), "sha256": sha256(path), "requires_vcomp140": needed})
    if needs_vcomp and not (bundle / "_internal/vcomp140.dll").exists():
        actions.append({"action": "add", "target": "_internal/vcomp140.dll", "source": sources["vcomp140.dll"]["file"],
                        "before": None, "after": sources["vcomp140.dll"]})
    return {"schema_version": 1, "mode": "check", "passed": True, "applied": False,
            "source_provenance": {"official_download": "https://aka.ms/vc14/vc_redist.x64.exe",
                "vc_redist_package_sha256": "843068991daaa1f73ad9f6239bce4d0f6a07a51f18c37ea2a867e9beca71295c",
                "dll_hashes_match_audited_official_package": True},
            "sources": list(sources.values()), "native_imports": native_records, "actions": actions}


def normalize(bundle: Path, source: Path, *, apply: bool = False, report_dir: Path | None = None,
              backup_dir: Path | None = None, native_imports: list[str] | None = None,
              inspector=inspect_dll, import_reader=native_import_names) -> dict:
    bundle, source = checked_root(bundle, True), checked_root(source, True)
    report_dir = checked_root(report_dir, False) if report_dir is not None else None
    backup_dir = checked_root(backup_dir, False) if backup_dir is not None else None
    roots_disjoint([value for value in (bundle, source, report_dir, backup_dir) if value is not None])
    if apply and (report_dir is None or backup_dir is None):
        raise ValidationError("Apply requires separate NEW report and backup directories")
    plan = preflight(bundle, source, native_imports=native_imports, inspector=inspector, import_reader=import_reader)
    if apply:
        # Re-run every signature/hash/path check before creating backups or writing.
        if preflight(bundle, source, native_imports=native_imports, inspector=inspector, import_reader=import_reader) != plan:
            raise ValidationError("Inputs changed after preflight")
        backup_dir.mkdir(parents=True)
        report_dir.mkdir(parents=True)
        staged, committed = [], []
        try:
            for action in plan["actions"]:
                target = bundle / action["target"]
                original = checked_file(source, action["source"])
                reject_links(target)
                if action["before"] is not None:
                    backup = backup_dir / action["target"]
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(target, backup)
                    if sha256(backup) != action["before"]["sha256"]:
                        raise ValidationError("Backup hash verification failed")
                temporary = target.with_name(target.name + ".normalize-" + uuid.uuid4().hex + ".tmp")
                staged.append((temporary, target, action))
                shutil.copyfile(original, temporary)
                if sha256(temporary) != action["after"]["sha256"]:
                    raise ValidationError("Replacement hash verification failed")
            for temporary, target, action in staged:
                reject_links(target)
                if action["before"] is not None and sha256(target) != action["before"]["sha256"]:
                    raise ValidationError("Target changed while preparing replacement")
                if action["before"] is None and target.exists():
                    raise ValidationError("New DLL target appeared after preflight")
                os.replace(temporary, target)
                committed.append((target, action))
            plan.update(mode="apply", applied=True)
        except Exception:
            for target, action in reversed(committed):
                reject_links(target)
                if action["before"] is None:
                    target.unlink()
                else:
                    shutil.copyfile(checked_file(backup_dir, action["target"]), target)
            raise
        finally:
            for temporary, _, _ in staged:
                if temporary.exists():
                    reject_links(temporary)
                    temporary.unlink()
        (backup_dir / "OriginalsManifest.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=apply)
        (report_dir / "MicrosoftRuntimeManifest.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--native-import", action="append", default=[], help="Relative PE path; add vcomp140 only if imported")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    try:
        result = normalize(args.bundle, args.source_dir, apply=args.apply,
                           report_dir=args.report_dir, backup_dir=args.backup_dir, native_imports=args.native_import)
    except (ValidationError, OSError) as exc:
        message = str(exc) if isinstance(exc, ValidationError) else "File operation failed; no private path is included in this report"
        print(json.dumps({"passed": False, "error": message}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
