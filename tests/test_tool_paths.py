"""路径安全（M3-A §6.2）：safe_resolve 的拒绝矩阵。

全部为真实文件系统操作，不 mock；symlink 在无权限创建时显式 skip（不假装通过）。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from packages.tools.paths import PathDenied, is_sensitive, safe_resolve


@pytest.fixture
def root(tmp_path) -> Path:
    base = tmp_path / "ws"
    (base / "notes").mkdir(parents=True)
    (base / "docs").mkdir()
    (base / "notes" / "a.txt").write_text("hello", encoding="utf-8")
    return base


def _code(root: Path, rel: str, **kwargs) -> str:
    with pytest.raises(PathDenied) as exc:
        safe_resolve(root, rel, **kwargs)
    return exc.value.code


@pytest.mark.parametrize(
    "rel",
    [
        "notes/a.txt",
        "docs/2026/report.md",
        "notes/../notes/a.txt".replace("../", ""),  # 归一后仍是工作区内路径
        "a",
        "notes",
    ],
)
def test_normal_relative_paths_allowed(root, rel):
    resolved = safe_resolve(root, rel)
    assert str(resolved).startswith(str(root.resolve()))


@pytest.mark.parametrize(
    "rel",
    [
        "..",
        "../",
        "../outside.txt",
        "../../.ssh/id_rsa",
        "notes/../../x",
        "notes/../..",
        "./notes/a.txt",
        "notes//a.txt",
        "notes/",
        "/etc/passwd",
        "\\server\\share\\file.txt",
        "\\\\server\\share",
        "C:\\Windows\\win.ini",
        "d:/data/x",
        "file.txt:stream",
        "notes/a.txt:$DATA",
        "a\x00b",
        ".",
    ],
)
def test_escape_attempts_rejected(root, rel):
    code = _code(root, rel)
    assert code in {"TOOL_PATH_DENIED", "TOOL_SENSITIVE_FILE"}


def test_root_allowed_only_when_explicit(root):
    assert safe_resolve(root, "") == root.resolve()
    assert _code(root, "", allow_root=False) == "TOOL_PATH_DENIED"


@pytest.mark.parametrize("name", ["CON", "con", "AUX", "NUL", "COM1", "lpt9"])
def test_windows_reserved_names_rejected(root, name):
    assert _code(root, name) == "TOOL_PATH_DENIED"
    assert _code(root, f"notes/{name}.txt") == "TOOL_PATH_DENIED"


@pytest.mark.parametrize("rel", ["trailing.", "trailing ", "notes/a.txt."])
def test_trailing_dot_or_space_rejected(root, rel):
    assert _code(root, rel) == "TOOL_PATH_DENIED"


@pytest.mark.parametrize(
    "rel",
    [".env", ".env.local", ".ENV", "notes/.env.production", "id_rsa", "notes/id_rsa.pub",
     "cert.pem", "server.key", "store.pfx", ".ssh/config", ".aws/credentials",
     "credentials.json", "NTUSER.DAT", ".git/config"],
)
def test_sensitive_files_rejected(root, rel):
    assert _code(root, rel) == "TOOL_SENSITIVE_FILE"


@pytest.mark.parametrize(
    "rel,expected",
    [
        ("notes/a.txt", False),
        (".env", True),
        (".ENV.LOCAL", True),
        ("deep/credentials", True),
        ("deep/.ssh/id_ed25519", True),
        ("normal.json", False),
    ],
)
def test_is_sensitive_matrix(rel, expected):
    assert is_sensitive(rel) is expected


def test_symlink_escape_rejected(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = root / "link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接（非管理员/未开开发者模式）")
    assert _code(root, "link/secret.txt") == "TOOL_PATH_DENIED"
    assert _code(root, "link") == "TOOL_PATH_DENIED"


def test_symlink_file_rejected(root):
    target = root / "notes" / "a.txt"
    link = root / "alias.txt"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接")
    assert _code(root, "alias.txt") == "TOOL_PATH_DENIED"


def test_case_insensitive_containment(root):
    # Windows 大小写不敏感：大写路径仍应在工作区内，且不能被误判为逃逸
    assert safe_resolve(root, "NOTES/A.TXT").name.lower() == "a.txt"


def test_non_existent_path_resolves_inside(root):
    resolved = safe_resolve(root, "docs/new-file.md")
    assert resolved.parent == (root / "docs").resolve()


def test_relative_root_rejected(tmp_path):
    with pytest.raises(PathDenied) as exc:
        safe_resolve("relative/path", "a.txt")
    assert exc.value.code == "WORKSPACE_INVALID_ROOT"


def test_absolute_workspace_root_outside_is_not_special(tmp_path):
    """根目录之外的真实文件：只要相对路径合法就只会在 root 内解析。"""
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.txt").write_text("x", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    assert not str(safe_resolve(root, "x.txt")).startswith(str(other))


def test_junction_escape_rejected(root, tmp_path):
    """Windows junction（无需管理员）也必须被 reparse point 检查拦住。"""
    import subprocess

    outside = tmp_path / "junction_target"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = root / "jlink"
    try:
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("当前环境无法创建 junction")
    if completed.returncode != 0 or not link.exists():
        pytest.skip("当前环境无法创建 junction")
    assert _code(root, "jlink/secret.txt") == "TOOL_PATH_DENIED"
    assert _code(root, "jlink") == "TOOL_PATH_DENIED"
