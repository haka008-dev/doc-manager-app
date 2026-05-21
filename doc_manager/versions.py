"""스냅샷 기반 버전 관리.

저장할 때마다 그 시점의 전체 내용을 숨김 폴더에 스냅샷으로 보관:
    .versions/<파일명>/<타임스탬프>.md

이 폴더는 '.'으로 시작하므로 챗봇·앱 문서 목록에서 자동 제외됩니다.
"""
from __future__ import annotations

from datetime import datetime

from .backend import Backend

VERSIONS_DIR = ".versions"


def _safe(file_relative: str) -> str:
    return file_relative.replace("/", "__").replace("\\", "__")


def _version_dir(file_relative: str) -> str:
    return f"{VERSIONS_DIR}/{_safe(file_relative)}"


def new_version_id() -> str:
    """현재 시각 기반 버전 ID (예: 260521_153045)."""
    return datetime.now().strftime("%y%m%d_%H%M%S")


def save_version(backend: Backend, file_relative: str, content: str) -> str:
    """현재 내용을 새 버전으로 스냅샷 저장. 버전 ID 반환."""
    vid = new_version_id()
    path = f"{_version_dir(file_relative)}/{vid}.md"
    backend.write_file(
        path, content, commit_message=f"version: {file_relative} @ {vid}"
    )
    return vid


def list_versions(backend: Backend, file_relative: str) -> list[str]:
    """이 파일의 버전 ID 목록 (최신순)."""
    names = backend.list_dir(_version_dir(file_relative))
    vids = [n[:-3] for n in names if n.endswith(".md")]
    vids.sort(reverse=True)
    return vids


def read_version(backend: Backend, file_relative: str, version_id: str) -> str:
    """특정 버전의 내용."""
    path = f"{_version_dir(file_relative)}/{version_id}.md"
    return backend.read_file(path)


def version_label(version_id: str) -> str:
    """버전 ID를 사람이 읽기 좋은 형태로 (예: 2026-05-21 15:30:45)."""
    try:
        dt = datetime.strptime(version_id, "%y%m%d_%H%M%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return version_id
