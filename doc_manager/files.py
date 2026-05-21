"""마크다운 텍스트 처리 — 섹션 분할/병합 등 순수 함수.

파일 IO는 backend.py로 이관됨. 이 모듈은 텍스트만 다룹니다.
"""
from __future__ import annotations

import re
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


# ---------- 운영 문서 매장 구역 ----------
_HEADER = re.compile(r"^(#{1,6}) ")
_STORE_NUM = re.compile(r"^(\d+)\. ")


def parse_store_regions(content: str) -> dict[str, list[tuple[str, int]]]:
    """운영 문서의 '시 → [(구, 헤더 줄번호)]' 구조를 파싱.

    ### 'XX 지역 매장 정보' = 시, ##### 'XX구/시/군' = 구.
    매장이 들어갈 수 있는 구역만 추출. 매장 구조가 없으면 빈 dict.
    """
    lines = content.split("\n")
    regions: dict[str, list[tuple[str, int]]] = {}
    cur_city: str | None = None
    for i, line in enumerate(lines):
        m = _HEADER.match(line)
        if not m:
            continue
        level = len(m.group(1))
        title = line[m.end():].strip()
        if level <= 2:
            cur_city = None
        elif level == 3:
            if "지역 매장 정보" in title:
                cur_city = title.replace("지역 매장 정보", "").strip()
                regions.setdefault(cur_city, [])
            else:
                cur_city = None
        elif level == 5 and cur_city is not None:
            if title.endswith(("구", "시", "군")):
                regions[cur_city].append((title, i))
    return {c: g for c, g in regions.items() if g}


def add_store_to_region(
    content: str,
    gu_line_index: int,
    name: str,
    address: str,
    phone: str,
    hours: str,
    note: str = "",
) -> str:
    """gu_line_index의 ##### 구역 맨 끝에 매장 블록을 양식대로 삽입."""
    lines = content.split("\n")

    # 구역 범위: 구 헤더 다음 ~ 다음 헤더 직전
    end = len(lines)
    for j in range(gu_line_index + 1, len(lines)):
        if _HEADER.match(lines[j]):
            end = j
            break

    # 구역 내 매장 최대 번호
    max_n = 0
    for j in range(gu_line_index + 1, end):
        sm = _STORE_NUM.match(lines[j])
        if sm:
            max_n = max(max_n, int(sm.group(1)))
    new_n = max_n + 1

    # 새 매장 블록 (양식: 항목마다 빈 줄)
    block = [
        f"{new_n}. {name}", "",
        f"   - 주소지: {address}", "",
        f"   - 연락처: {phone}", "",
        f"   - 운영시간: {hours}",
    ]
    if note.strip():
        block += ["", f"   - 특이사항: {note.strip()}"]
    block.append("")

    # 삽입 위치: 구역 끝 빈 줄들 앞 (마지막 내용 줄 다음)
    insert_at = end
    while insert_at > gu_line_index + 1 and lines[insert_at - 1].strip() == "":
        insert_at -= 1

    new_lines = lines[:insert_at] + ["", *block] + lines[insert_at:]
    return "\n".join(new_lines)
