"""파일별 변경 이력 — diff 기반 JSONL 저장."""
from __future__ import annotations

import difflib
import json
from datetime import datetime

from .backend import Backend


CHANGELOG_DIR = ".changelog"


def _log_path(file_relative: str) -> str:
    safe = file_relative.replace("/", "__").replace("\\", "__")
    return f"{CHANGELOG_DIR}/{safe}.jsonl"


def make_diff(old: str, new: str, file_label: str) -> str:
    diff = difflib.unified_diff(
        old.splitlines(keepends=False),
        new.splitlines(keepends=False),
        fromfile=f"a/{file_label}",
        tofile=f"b/{file_label}",
        lineterm="",
        n=3,
    )
    return "\n".join(diff)


def diff_stats(old: str, new: str) -> tuple[int, int]:
    added = removed = 0
    for line in difflib.unified_diff(
        old.splitlines(), new.splitlines(), lineterm="", n=0
    ):
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def append_entry(
    backend: Backend,
    file_relative: str,
    old: str,
    new: str,
    note: str = "",
    ai_summary: str = "",
) -> dict:
    added, removed = diff_stats(old, new)
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "file": file_relative,
        "added": added,
        "removed": removed,
        "note": note,
        "ai_summary": ai_summary,
        "diff": make_diff(old, new, file_relative),
    }
    log_path = _log_path(file_relative)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    backend.append_text(
        log_path,
        line,
        commit_message=f"log: {file_relative} (+{added}/-{removed})",
    )
    return entry


def read_entries(backend: Backend, file_relative: str) -> list[dict]:
    raw = backend.read_text_or_empty(_log_path(file_relative))
    entries: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    entries.reverse()
    return entries


def read_all_entries(backend: Backend, limit: int = 50) -> list[dict]:
    """모든 파일의 변경 로그를 합쳐 최신순으로 반환.

    구현 단순화: 백엔드의 파일 목록을 한 번 보고 알려진 파일들에 대해서만 조회.
    이미 삭제된 파일의 변경 로그는 표시되지 않을 수 있음(받아들이는 트레이드오프).
    """
    all_entries: list[dict] = []
    for meta in backend.list_md_files():
        for e in read_entries(backend, meta.relative):
            all_entries.append(e)
    all_entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return all_entries[:limit]
