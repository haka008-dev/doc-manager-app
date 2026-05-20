"""챗봇 문서 관리기 — Streamlit 앱.

백엔드는 환경/secret에 따라 자동 결정:
  - secrets.toml 또는 환경 변수에 GITHUB_TOKEN/GITHUB_REPO가 있으면 GitHub 모드
  - 아니면 로컬 폴더 모드
"""
from __future__ import annotations

import hmac
import os
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from doc_manager import ai, changelog, files
from doc_manager.backend import Backend, GitHubBackend, LocalBackend

load_dotenv()

DEFAULT_LOCAL_DOCS_PATH = r"C:\Users\user\Desktop\챗봇"

st.set_page_config(
    page_title="챗봇 문서 관리기",
    page_icon="📚",
    layout="wide",
)


# ---------------- secret/환경 변수 헬퍼 ----------------
def _secret(key: str, default: str = "") -> str:
    """st.secrets에서 먼저 찾고 없으면 환경 변수에서. 둘 다 없으면 default."""
    try:
        val = st.secrets.get(key)
        if val:
            return str(val)
    except (FileNotFoundError, KeyError, AttributeError):
        pass
    return os.environ.get(key, default)


# ---------------- 비밀번호 게이트 (무차별 대입 차단 포함) ----------------
MAX_ATTEMPTS = 5          # 누적 실패 허용 횟수
LOCKOUT_SECONDS = 300     # 잠금 시간 (5분)


@st.cache_resource
def _auth_state() -> dict:
    """모든 세션이 공유하는 인증 상태. 무차별 대입 방어용 전역 카운터.

    st.cache_resource는 앱 프로세스 전체에서 단 하나만 존재하므로,
    공격자가 새 탭/세션을 열어도 이 카운터는 우회되지 않습니다.
    """
    return {"fail_count": 0, "locked_until": 0.0}


def require_password() -> None:
    """APP_PASSWORD가 설정되어 있으면 비밀번호 입력을 요구. 미설정이면 통과.

    보안:
      - hmac.compare_digest 로 상수 시간 비교 (timing attack 방어)
      - 누적 MAX_ATTEMPTS회 실패 시 LOCKOUT_SECONDS 동안 전역 잠금
    """
    expected = _secret("APP_PASSWORD")
    if not expected:
        return
    if st.session_state.get("authed"):
        return

    state = _auth_state()
    now = time.time()

    st.title("🔒 챗봇 문서 관리기")

    # 잠금 상태면 입력 자체를 막음
    remaining = state["locked_until"] - now
    if remaining > 0:
        mins = int(remaining // 60) + 1
        st.error(
            f"비밀번호를 여러 번 틀려 로그인이 잠겼습니다. "
            f"약 {mins}분 후 다시 시도하세요."
        )
        st.stop()

    st.caption("비밀번호를 입력하세요.")
    pw = st.text_input("비밀번호", type="password", label_visibility="collapsed")
    if st.button("로그인", type="primary"):
        if not pw:
            st.warning("비밀번호를 입력하세요.")
        elif hmac.compare_digest(pw.encode("utf-8"), expected.encode("utf-8")):
            state["fail_count"] = 0
            st.session_state["authed"] = True
            st.rerun()
        else:
            state["fail_count"] += 1
            left = MAX_ATTEMPTS - state["fail_count"]
            if left <= 0:
                state["locked_until"] = now + LOCKOUT_SECONDS
                state["fail_count"] = 0
                st.error(
                    f"비밀번호를 {MAX_ATTEMPTS}회 틀렸습니다. "
                    f"{LOCKOUT_SECONDS // 60}분간 로그인이 잠깁니다."
                )
            else:
                st.error(f"비밀번호가 일치하지 않습니다. (남은 시도: {left}회)")
    st.stop()


# ---------------- 백엔드 선택 ----------------
def build_backend() -> tuple[Backend, str]:
    """반환: (backend, 표시용 라벨)"""
    gh_token = _secret("GITHUB_TOKEN")
    gh_repo = _secret("GITHUB_REPO")  # "owner/repo"
    gh_branch = _secret("GITHUB_BRANCH", "main")
    gh_prefix = _secret("GITHUB_DOCS_PREFIX", "")

    if gh_token and gh_repo:
        backend = GitHubBackend(
            token=gh_token,
            repo_full_name=gh_repo,
            branch=gh_branch,
            docs_prefix=gh_prefix,
        )
        label = f"🐙 GitHub · {gh_repo}@{gh_branch}"
        if gh_prefix:
            label += f"/{gh_prefix}"
        return backend, label

    # 로컬 모드
    local_path_str = st.session_state.get("local_docs_path") or _secret(
        "LOCAL_DOCS_PATH", DEFAULT_LOCAL_DOCS_PATH
    )
    local_root = Path(local_path_str)
    backend = LocalBackend(local_root)
    label = f"📁 로컬 · {local_root}"
    return backend, label


# ---------------- 캐싱 (GitHub 호출 절감) ----------------
@st.cache_data(show_spinner=False, ttl=60)
def cached_list_md(backend_key: str) -> list[dict]:
    backend, _ = build_backend()
    metas = backend.list_md_files()
    return [
        {"relative": m.relative, "modified": m.modified.isoformat(), "size": m.size}
        for m in metas
    ]


@st.cache_data(show_spinner=False, ttl=60)
def cached_read(backend_key: str, relative: str) -> str:
    backend, _ = build_backend()
    return backend.read_file(relative)


def invalidate_cache():
    cached_list_md.clear()
    cached_read.clear()


def backend_cache_key(label: str) -> str:
    return label


# ---------------- 사이드바 ----------------
def render_sidebar(backend_label: str) -> str:
    st.sidebar.header("⚙️ 설정")
    st.sidebar.markdown(f"**저장소:** {backend_label}")

    if backend_label.startswith("📁"):
        # 로컬 모드만 폴더 변경 가능
        local_path = st.sidebar.text_input(
            "로컬 문서 폴더",
            value=st.session_state.get("local_docs_path", DEFAULT_LOCAL_DOCS_PATH),
        )
        st.session_state["local_docs_path"] = local_path

    st.sidebar.divider()
    st.sidebar.subheader("🤖 Claude API")
    api_key = st.sidebar.text_input(
        "API 키 (선택)",
        value=_secret("ANTHROPIC_API_KEY", ""),
        type="password",
        help="비워두면 AI 기능만 비활성. secrets/env에 ANTHROPIC_API_KEY로도 설정 가능.",
    )

    st.sidebar.divider()
    if st.sidebar.button("🔄 새로고침 (캐시 비우기)", use_container_width=True):
        invalidate_cache()
        st.rerun()

    if st.session_state.get("authed"):
        if st.sidebar.button("🚪 로그아웃", use_container_width=True):
            st.session_state["authed"] = False
            st.rerun()

    return api_key


# ---------------- 파일 선택 패널 ----------------
def render_file_list(backend_key: str) -> str | None:
    md_files = cached_list_md(backend_key)
    if not md_files:
        st.info("이 저장소에서 .md 파일을 찾지 못했습니다.")
        return None

    query = st.text_input("🔍 파일 검색", placeholder="파일명 또는 경로...", key="search")
    if query:
        ql = query.lower()
        filtered = [f for f in md_files if ql in f["relative"].lower()]
    else:
        filtered = md_files

    st.caption(f"총 {len(filtered)}개 / 전체 {len(md_files)}개")
    if not filtered:
        st.warning("검색 결과 없음")
        return None

    options = [f["relative"] for f in filtered]
    selected = st.radio(
        "파일 선택",
        options,
        format_func=lambda r: r,
        label_visibility="collapsed",
        key="file_select",
    )

    for f in filtered:
        if f["relative"] == selected:
            ts = f["modified"][:19].replace("T", " ")
            st.caption(f"📅 {ts} · {f['size']:,} bytes")
            return f["relative"]
    return None


# ---------------- 편집/미리보기 ----------------
def _save_change(
    backend: Backend,
    relative: str,
    original: str,
    new_text: str,
    note: str,
    use_ai_summary: bool,
    api_key: str,
) -> dict:
    ai_summary = ""
    if use_ai_summary and api_key:
        with st.spinner("AI 요약 생성 중..."):
            diff_text = changelog.make_diff(original, new_text, relative)
            result = ai.summarize_change(diff_text, relative, api_key=api_key)
            if result.ok:
                ai_summary = result.text
            else:
                st.warning(f"AI 요약 실패 (저장은 진행): {result.error}")
    msg = note or f"edit {relative}"
    backend.write_file(relative, new_text, commit_message=msg)
    entry = changelog.append_entry(
        backend, relative, original, new_text, note=note, ai_summary=ai_summary
    )
    invalidate_cache()
    return {"entry": entry, "ai_summary": ai_summary}


def render_editor(backend: Backend, backend_key: str, relative: str, api_key: str):
    file_name = Path(relative).name
    original = cached_read(backend_key, relative)

    header_cols = st.columns([5, 2])
    with header_cols[0]:
        st.subheader(f"📄 {relative}")
    with header_cols[1]:
        st.download_button(
            "📥 통합 .md 다운로드",
            data=original,
            file_name=file_name,
            mime="text/markdown",
            use_container_width=True,
            key=f"download::{relative}",
        )

    tab_whole, tab_parts, tab_preview, tab_outline = st.tabs(
        ["✏️ 통합 편집", "🧩 파트별 편집", "👀 미리보기", "🗂 목차"]
    )

    # ---- 통합 편집 ----
    with tab_whole:
        buf_key = f"buf::{relative}"
        if buf_key not in st.session_state:
            st.session_state[buf_key] = original

        new_text = st.text_area(
            "내용",
            value=st.session_state[buf_key],
            height=520,
            key=f"editor::{relative}",
            label_visibility="collapsed",
        )
        st.session_state[buf_key] = new_text
        is_dirty = new_text != original

        col1, col2, col3 = st.columns([2, 2, 3])
        with col1:
            note = st.text_input(
                "변경 메모 (선택)",
                placeholder="예: FAQ 항목 추가",
                key=f"note::{relative}",
            )
        with col2:
            use_ai_summary = st.checkbox(
                "AI 변경 요약 생성", value=False, key=f"ai_sum::{relative}",
                help="저장 시 Claude가 diff를 한 줄로 요약",
            )
        with col3:
            st.write("")
            save_btn = st.button(
                "💾 저장" if is_dirty else "💾 변경 없음",
                disabled=not is_dirty,
                type="primary" if is_dirty else "secondary",
                use_container_width=True,
                key=f"save::{relative}",
            )

        if save_btn and is_dirty:
            result = _save_change(
                backend, relative, original, new_text, note, use_ai_summary, api_key
            )
            e = result["entry"]
            st.success(f"저장 완료 · +{e['added']} / -{e['removed']} 줄")
            if result["ai_summary"]:
                st.info(f"🤖 {result['ai_summary']}")
            st.session_state.pop(buf_key, None)
            st.rerun()

    # ---- 파트별 편집 ----
    with tab_parts:
        col_lvl, col_ai = st.columns([3, 2])
        with col_lvl:
            level = st.radio(
                "분할 기준 헤더 레벨",
                options=[1, 2, 3],
                format_func=lambda x: f"H{x} ({'#' * x})",
                horizontal=True,
                index=1,
                key=f"split_level::{relative}",
            )
        with col_ai:
            use_ai_summary_part = st.checkbox(
                "AI 변경 요약 생성", value=False, key=f"ai_sum_part::{relative}",
            )

        sections = files.split_sections(original, level=level)
        st.caption(f"총 {len(sections)}개 파트")

        if len(sections) == 1 and sections[0].title == "(전체)":
            st.info(
                f"H{level} 헤더가 없어서 분할되지 않았습니다. "
                "다른 레벨을 선택하거나 통합 편집을 사용하세요."
            )
        else:
            for i, section in enumerate(sections):
                with st.expander(
                    f"📍 {i + 1}. {section.title}"
                    + ("  (서문)" if section.is_intro else ""),
                    expanded=False,
                ):
                    widget_key = f"part::{relative}::lvl{level}::{i}"
                    edited = st.text_area(
                        "내용",
                        value=section.full_text,
                        height=260,
                        key=widget_key,
                        label_visibility="collapsed",
                    )
                    part_dirty = edited != section.full_text
                    pc1, pc2 = st.columns([3, 2])
                    with pc1:
                        part_note = st.text_input(
                            "메모",
                            placeholder="이 파트의 변경 메모",
                            key=f"note_part::{relative}::lvl{level}::{i}",
                            label_visibility="collapsed",
                        )
                    with pc2:
                        save_part = st.button(
                            "💾 이 파트 저장" if part_dirty else "변경 없음",
                            disabled=not part_dirty,
                            type="primary" if part_dirty else "secondary",
                            use_container_width=True,
                            key=f"save_part::{relative}::lvl{level}::{i}",
                        )
                    if save_part and part_dirty:
                        new_pieces = [
                            edited if j == i else s.full_text
                            for j, s in enumerate(sections)
                        ]
                        new_full = "".join(new_pieces)
                        auto_note = part_note or f"파트 수정: {section.title}"
                        result = _save_change(
                            backend, relative, original, new_full,
                            auto_note, use_ai_summary_part, api_key,
                        )
                        e = result["entry"]
                        st.success(
                            f"'{section.title}' 저장 완료 · "
                            f"+{e['added']} / -{e['removed']} 줄"
                        )
                        if result["ai_summary"]:
                            st.info(f"🤖 {result['ai_summary']}")
                        st.session_state.pop(f"buf::{relative}", None)
                        st.rerun()

    with tab_preview:
        st.markdown(original)

    with tab_outline:
        headings = files.extract_headings(original)
        if not headings:
            st.caption("헤더 없음")
        else:
            for lvl, text in headings:
                st.markdown(f"{'  ' * (lvl - 1)}- {'#' * lvl} {text}")


# ---------------- 변경 로그 ----------------
def render_changelog(backend: Backend, relative: str | None):
    st.subheader("📋 변경 로그")
    mode = st.radio(
        "보기 모드",
        ["현재 파일", "전체 최근"],
        horizontal=True,
        label_visibility="collapsed",
        key="log_mode",
    )

    if mode == "현재 파일":
        if relative is None:
            st.caption("파일을 선택하세요.")
            return
        entries = changelog.read_entries(backend, relative)
    else:
        with st.spinner("최근 로그 모으는 중..."):
            entries = changelog.read_all_entries(backend, limit=30)

    if not entries:
        st.caption("기록 없음")
        return

    for i, e in enumerate(entries):
        ts = e.get("timestamp", "")[:19].replace("T", " ")
        added = e.get("added", 0)
        removed = e.get("removed", 0)
        note = e.get("note") or ""
        ai_sum = e.get("ai_summary") or ""
        title = f"{ts} · +{added}/-{removed}"
        if note:
            title += f" · {note}"
        with st.expander(title, expanded=(i == 0 and mode == "현재 파일")):
            if mode == "전체 최근":
                st.caption(f"📄 {e.get('file', '?')}")
            if ai_sum:
                st.info(f"🤖 {ai_sum}")
            diff = e.get("diff", "")
            if diff:
                st.code(diff, language="diff")


# ---------------- AI 검토 ----------------
def render_ai_review(backend: Backend, backend_key: str, relative: str, api_key: str):
    st.subheader("🤖 AI 문서 검토")
    if not api_key:
        st.caption("사이드바에서 Claude API 키를 입력하면 사용할 수 있습니다.")
        return
    review_key = f"review::{relative}"
    if st.button("이 문서 검토 요청", key=f"btn_review::{relative}"):
        content = cached_read(backend_key, relative)
        with st.spinner("Claude가 문서를 검토하는 중..."):
            result = ai.review_document(content, relative, api_key=api_key)
        if result.ok:
            st.session_state[review_key] = result.text
        else:
            st.error(result.error)
    if review_key in st.session_state:
        st.markdown(st.session_state[review_key])


# ---------------- 메인 ----------------
def main():
    require_password()

    try:
        backend, backend_label = build_backend()
    except Exception as e:
        st.error(f"백엔드 초기화 실패: {e}")
        st.stop()

    api_key = render_sidebar(backend_label)
    backend_key = backend_cache_key(backend_label)

    st.title("📚 챗봇 문서 관리기")
    st.caption(backend_label)

    col_files, col_main, col_log = st.columns([2, 5, 3], gap="medium")

    with col_files:
        st.subheader("📁 문서")
        selected_relative = render_file_list(backend_key)

    with col_main:
        if selected_relative is None:
            st.info("좌측에서 파일을 선택하세요.")
        else:
            render_editor(backend, backend_key, selected_relative, api_key)
            st.divider()
            render_ai_review(backend, backend_key, selected_relative, api_key)

    with col_log:
        render_changelog(backend, selected_relative)


if __name__ == "__main__":
    main()
