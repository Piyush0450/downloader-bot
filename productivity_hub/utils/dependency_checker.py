"""
System & Library Dependency Checker Utility.

Detects the runtime availability of system executables (ffmpeg, ffprobe, libreoffice,
ghostscript, 7z) and Python libraries (yt-dlp, Pillow, pyzbar, OpenCV, pypdf, etc.).
Caches results to avoid unnecessary subprocess overhead while providing comprehensive
diagnostic reporting for the Admin dashboard and conversion registry.
"""

import logging
import shutil
import subprocess
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger("productivity_hub.utils.dependency_checker")


@dataclass
class DependencyStatus:
    name: str
    available: bool
    version_or_path: Optional[str] = None
    details: Optional[str] = None


class DependencyChecker:
    """
    Evaluates and caches operational availability of system binaries and Python libraries.
    """

    def __init__(self):
        self._cache: Dict[str, DependencyStatus] = {}

    def check_binary(self, binary_name: str, version_args: Optional[list] = None) -> DependencyStatus:
        """
        Check if a system executable is available on PATH and retrieve its location/version.
        """
        if binary_name in self._cache:
            return self._cache[binary_name]

        path = shutil.which(binary_name)
        if not path:
            status = DependencyStatus(
                name=binary_name,
                available=False,
                version_or_path=None,
                details=f"Binary '{binary_name}' not found on system PATH."
            )
            self._cache[binary_name] = status
            return status

        # Try executing to verify viability
        details = f"Found at {path}"
        if version_args:
            try:
                res = subprocess.run(
                    [path] + version_args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=5,
                    text=True
                )
                output = (res.stdout or res.stderr or "").strip().split("\n")[0]
                details = output[:80] if output else details
            except Exception as e:
                details = f"Executable found but invocation returned: {e}"

        status = DependencyStatus(
            name=binary_name,
            available=True,
            version_or_path=path,
            details=details
        )
        self._cache[binary_name] = status
        return status

    def check_python_module(self, module_name: str, import_name: Optional[str] = None) -> DependencyStatus:
        """
        Check if a Python module is available using importlib.util.find_spec to avoid expensive cold imports.
        """
        key = f"py_{module_name}"
        if key in self._cache:
            return self._cache[key]

        target_import = import_name or module_name
        try:
            import importlib.util
            spec = importlib.util.find_spec(target_import)
            if spec is not None:
                status = DependencyStatus(
                    name=module_name,
                    available=True,
                    version_or_path="Available",
                    details=f"Python module '{target_import}' found."
                )
            else:
                status = DependencyStatus(
                    name=module_name,
                    available=False,
                    version_or_path=None,
                    details=f"Python module '{target_import}' not found in environment."
                )
        except Exception as e:
            status = DependencyStatus(
                name=module_name,
                available=False,
                version_or_path=None,
                details=f"Module inspection error: {str(e)}"
            )

        self._cache[key] = status
        return status

    # Convenience binary checkers
    def has_ffmpeg(self) -> bool:
        return self.check_binary("ffmpeg", ["-version"]).available

    def has_ffprobe(self) -> bool:
        return self.check_binary("ffprobe", ["-version"]).available

    def has_libreoffice(self) -> bool:
        status_soffice = self.check_binary("soffice", ["--version"])
        if status_soffice.available:
            return True
        return self.check_binary("libreoffice", ["--version"]).available

    def has_ghostscript(self) -> bool:
        return self.check_binary("gs", ["--version"]).available or self.check_binary("gswin64c", ["--version"]).available

    def has_poppler(self) -> bool:
        return self.check_binary("pdftoppm", ["-v"]).available

    def has_7z(self) -> bool:
        return self.check_binary("7z").available or self.check_binary("7za").available

    def has_unrar(self) -> bool:
        return self.check_binary("unrar").available

    # Python module checks
    def has_rembg(self) -> bool:
        return self.check_python_module("rembg").available

    def has_pyzbar(self) -> bool:
        return self.check_python_module("pyzbar").available

    def has_opencv(self) -> bool:
        return self.check_python_module("opencv", "cv2").available

    def has_pypdf(self) -> bool:
        return self.check_python_module("pypdf").available

    def has_docx(self) -> bool:
        return self.check_python_module("python-docx", "docx").available

    def has_openpyxl(self) -> bool:
        return self.check_python_module("openpyxl").available

    def has_pandas(self) -> bool:
        return self.check_python_module("pandas").available

    def get_full_diagnostics(self) -> Dict[str, DependencyStatus]:
        """
        Run all diagnostics and return a comprehensive mapping for Admin review.
        """
        binaries = ["ffmpeg", "ffprobe", "soffice", "libreoffice", "gs", "pdftoppm", "7z", "unrar"]
        for b in binaries:
            self.check_binary(b)

        modules = [
            ("yt_dlp", "yt_dlp"),
            ("Pillow", "PIL"),
            ("qrcode", "qrcode"),
            ("pyzbar", "pyzbar"),
            ("opencv", "cv2"),
            ("pypdf", "pypdf"),
            ("python-docx", "docx"),
            ("openpyxl", "openpyxl"),
            ("pandas", "pandas"),
            ("reportlab", "reportlab"),
            ("rembg", "rembg"),
        ]
        for name, imp in modules:
            self.check_python_module(name, imp)

        return self._cache


_checker_instance = DependencyChecker()


def get_dependency_checker() -> DependencyChecker:
    """Retrieve the global DependencyChecker singleton."""
    return _checker_instance
