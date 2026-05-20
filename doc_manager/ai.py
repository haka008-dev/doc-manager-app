"""Claude API 통합 — 문서 검토 및 변경 요약."""
from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_MODEL = "claude-sonnet-4-6"


@dataclass
class AIResult:
    ok: bool
    text: str
    error: str = ""


def _client(api_key: str | None = None):
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise RuntimeError(
            "anthropic 패키지가 설치되지 않았습니다. `pip install anthropic` 실행 필요."
        ) from e
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
    return Anthropic(api_key=key)


def review_document(
    content: str,
    file_name: str,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> AIResult:
    """문서를 검토해서 오래된 정보, 누락된 섹션, 개선 제안을 받아옴."""
    try:
        client = _client(api_key)
    except RuntimeError as e:
        return AIResult(False, "", str(e))

    system = (
        "당신은 챗봇 운영을 위한 문서 관리 어시스턴트입니다. "
        "사용자가 제공한 마크다운 문서를 검토하여 다음을 짚어주세요:\n"
        "1. 시간이 흘러 부정확해졌거나 검증이 필요해 보이는 정보\n"
        "2. 누락된 섹션 또는 보강이 필요한 부분\n"
        "3. 구조/표현 개선 제안\n"
        "각 항목은 문서의 구체적 위치(헤더 또는 인용)와 함께 짧게 정리하세요. "
        "최대 8개 항목, 한국어로."
    )
    user = f"파일: {file_name}\n\n---\n\n{content}"

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        )
        return AIResult(True, text)
    except Exception as e:
        return AIResult(False, "", f"AI 호출 실패: {e}")


def summarize_change(
    diff: str,
    file_name: str,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> AIResult:
    """변경 diff를 한 줄 요약."""
    try:
        client = _client(api_key)
    except RuntimeError as e:
        return AIResult(False, "", str(e))

    system = (
        "당신은 git 변경 사항 요약 도구입니다. "
        "주어진 unified diff를 한국어로 한 문장(80자 이내)으로 요약하세요. "
        "무엇이 바뀌었는지에 집중하고, 그 외 설명은 추가하지 마세요."
    )
    user = f"파일: {file_name}\n\n{diff[:8000]}"

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        ).strip()
        return AIResult(True, text)
    except Exception as e:
        return AIResult(False, "", f"AI 호출 실패: {e}")
