"""마크다운 텍스트 처리 — 섹션 분할/병합 등 순수 함수.

파일 IO는 backend.py로 이관됨. 이 모듈은 텍스트만 다룹니다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Section:
    """헤더 레벨로 분할된 마크다운 섹션."""
    title: str          # 표시용 ("시작하기" 또는 "(서문)")
    full_text: str      # 헤더 라인 포함 전체 텍스트
    is_intro: bool      # 첫 헤더 이전 본문이면 True


def split_sections(content: str, level: int = 2) -> list[Section]:
    """지정한 헤더 레벨로 마크다운을 분할.

    각 섹션은 헤더 라인을 포함하며 다음 같은 레벨의 헤더 직전까지가 본문.
    첫 헤더 이전 본문이 있으면 '(서문)' 섹션으로 맨 앞에 추가.
    매칭되는 헤더가 없으면 전체 내용을 단일 '(전체)' 섹션으로 반환.
    """
    if level < 1 or level > 6:
        level = 2

    lines = content.splitlines(keepends=True)
    sections: list[Section] = []
    in_code = False
    heading_indices: list[int] = []
    prefix = "#" * level + " "

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if stripped.startswith(prefix):
            heading_indices.append(i)

    if not heading_indices:
        return [Section(title="(전체)", full_text=content, is_intro=False)]

    if heading_indices[0] > 0:
        intro = "".join(lines[: heading_indices[0]])
        if intro.strip():
            sections.append(Section(title="(서문)", full_text=intro, is_intro=True))

    for idx, start in enumerate(heading_indices):
        end = heading_indices[idx + 1] if idx + 1 < len(heading_indices) else len(lines)
        full_text = "".join(lines[start:end])
        heading_line = lines[start].strip()
        title = heading_line[level + 1 :].strip() or "(제목 없음)"
        sections.append(Section(title=title, full_text=full_text, is_intro=False))

    return sections


def join_sections(sections: list[Section]) -> str:
    return "".join(s.full_text for s in sections)


def extract_headings(content: str) -> list[tuple[int, str]]:
    """마크다운 헤더(level, text) 목록 — 사이드 네비용."""
    headings: list[tuple[int, str]] = []
    in_code = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if stripped.startswith("#"):
            level = 0
            for ch in stripped:
                if ch == "#":
                    level += 1
                else:
                    break
            if 1 <= level <= 6 and len(stripped) > level and stripped[level] == " ":
                headings.append((level, stripped[level + 1 :].strip()))
    return headings
