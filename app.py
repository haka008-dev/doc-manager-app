"""챗봇 문서 관리기 — Streamlit 앱.

백엔드는 환경/secret에 따라 자동 결정:
  - secrets.toml 또는 환경 변수에 GITHUB_TOKEN/GITHUB_REPO가 있으면 GitHub 모드
  - 아니면 로컬 폴더 모드
"""
from __future__ import annotations

import hmac
import os
import time
from datetime import timedelta, timezone
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

# 버튼을 살짝 컴팩트하게 — 목차 항목이 두 줄로 늘어나지 않도록
st.markdown(
    """
    <style>
    /* 버튼(목차 항목 등) 컴팩트하게 */
    .stButton button { padding: 0.16rem 0.5rem; line-height: 1.25; min-height: 0; }
    .stButton button p {
        font-size: 0.78rem; margin: 0;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    /* 버전 히스토리 expander 박스·글자 축소 */
    [data-testid="stExpander"] summary { padding: 0.28rem 0.55rem; font-size: 0.8rem; }
    [data-testid="stExpander"] summary p { font-size: 0.8rem; }
    [data-testid="stExpander"] summary svg { width: 0.9rem; height: 0.9rem; }
    </style>
    """,
    unsafe_allow_html=True,
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
    # write_file이 GitHub 커밋을 생성 — 그 커밋이 곧 버전 기록이 됨
    msg = note or f"edit {relative}"
    backend.write_file(relative, new_text, commit_message=msg)
    added, removed = changelog.diff_stats(original, new_text)
    invalidate_cache()
    return {
        "entry": {"added": added, "removed": removed},
        "ai_summary": ai_summary,
    }


def _render_store_add(backend, relative, original, regions, api_key):
    """운영 문서 매장 추가 탭 — 시·구 선택 + 양식 입력 + 삽입."""
    st.caption("시·구를 고르고 매장 정보를 입력하면 해당 구역 끝에 양식대로 추가됩니다.")

    cities = list(regions.keys())
    col1, col2 = st.columns(2)
    with col1:
        city = st.selectbox("시 / 도", cities, key=f"stcity::{relative}")
    gus = regions.get(city, [])
    with col2:
        gu_idx = st.selectbox(
            "구 / 시 / 군",
            range(len(gus)),
            format_func=lambda i: gus[i][0],
            key=f"stgu::{relative}::{city}",
        )
    gu_name, gu_line = gus[gu_idx]
    st.markdown(f"**추가 위치:** {gu_name}")

    name = st.text_input("매장명", placeholder="예: 하카 OO직영점", key=f"stname::{relative}")
    addr = st.text_input("주소지", key=f"staddr::{relative}")
    phone = st.text_input("연락처", placeholder="예: 051-000-0000", key=f"stphone::{relative}")
    hours = st.text_input("운영시간", value="11:00 ~ 21:00", key=f"sthours::{relative}")
    note = st.text_input("특이사항 (선택)", key=f"stnote::{relative}")

    if st.button("🏪 이 구역에 매장 추가", type="primary", key=f"staddbtn::{relative}"):
        if not (name.strip() and addr.strip() and phone.strip() and hours.strip()):
            st.error("매장명·주소지·연락처·운영시간은 필수 입력입니다.")
        else:
            new_full = files.add_store_to_region(
                original, gu_line, name.strip(), addr.strip(),
                phone.strip(), hours.strip(), note,
            )
            result = _save_change(
                backend, relative, original, new_full,
                f"매장 추가: {name.strip()} ({gu_name})", False, api_key,
            )
            e = result["entry"]
            st.success(f"'{name.strip()}' 추가 완료 · +{e['added']} / -{e['removed']} 줄")
            st.session_state.pop(f"buf::{relative}", None)
            st.rerun()


def render_editor(backend: Backend, backend_key: str, relative: str, api_key: str):
    # 다운로드 파일명에 당일 날짜를 붙임 (예: 제품정보-merged_260521.md)
    file_name = f"{Path(relative).stem}_{time.strftime('%y%m%d')}.md"
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

    regions = files.parse_store_regions(original)
    _tab_names = ["✏️ 통합 편집", "🧩 파트별 편집", "👀 미리보기", "🗂 목차"]
    if regions:
        _tab_names.append("🏪 매장 추가")
    _tabs = st.tabs(_tab_names)
    tab_whole, tab_parts, tab_preview, tab_outline = _tabs[:4]
    tab_store = _tabs[4] if regions else None

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
        st.caption("왼쪽 목차에서 항목을 클릭하면 오른쪽에서 바로 편집할 수 있어요.")
        h2_sections = files.split_sections(original, level=2)

        if len(h2_sections) == 1 and h2_sections[0].title == "(전체)":
            st.info("H2(##) 헤더가 없어 목차 편집을 쓸 수 없습니다. 통합 편집 탭을 사용하세요.")
        else:
            sel_key = f"tocsel::{relative}"
            col_toc, col_edit = st.columns([2, 5], gap="medium")

            with col_toc:
                query = st.text_input(
                    "목차 검색",
                    placeholder="🔍 항목 검색...",
                    key=f"tocq::{relative}",
                    label_visibility="collapsed",
                )
                ql = query.strip().lower()
                current = st.session_state.get(sel_key)
                shown = 0
                for hi, h2 in enumerate(h2_sections):
                    h3_subs = files.split_sections(h2.full_text, level=3)
                    matched = [
                        (si, s) for si, s in enumerate(h3_subs)
                        if not ql or ql in s.title.lower()
                    ]
                    if not matched:
                        continue
                    st.markdown(
                        f"<div style='font-size:0.8rem;font-weight:700;"
                        f"margin:0.45rem 0 0.05rem'>{h2.title}</div>",
                        unsafe_allow_html=True,
                    )
                    for si, sub in matched:
                        shown += 1
                        is_sel = current == (hi, si)
                        disp = (
                            sub.title if len(sub.title) <= 24
                            else sub.title[:23] + "…"
                        )
                        if st.button(
                            disp,
                            key=f"tocbtn::{relative}::{hi}::{si}",
                            help=sub.title,
                            use_container_width=True,
                            type="primary" if is_sel else "secondary",
                        ):
                            st.session_state[sel_key] = (hi, si)
                            st.rerun()
                if shown == 0:
                    st.caption("검색 결과 없음")

            with col_edit:
                sel = st.session_state.get(sel_key)
                if sel is None:
                    st.info("← 왼쪽 목차에서 편집할 항목을 클릭하세요.")
                else:
                    hi, si = sel
                    valid = hi < len(h2_sections)
                    h3_subs = (
                        files.split_sections(h2_sections[hi].full_text, level=3)
                        if valid else []
                    )
                    if not valid or si >= len(h3_subs):
                        st.warning("문서 구조가 바뀌었어요. 목차에서 다시 선택하세요.")
                    else:
                        h2 = h2_sections[hi]
                        sub = h3_subs[si]
                        st.markdown(f"#### {h2.title}  ›  {sub.title}")
                        wkey = f"toced::{relative}::{hi}::{si}"
                        edited = st.text_area(
                            "내용",
                            value=sub.full_text,
                            height=420,
                            key=wkey,
                            label_visibility="collapsed",
                        )
                        part_dirty = edited != sub.full_text
                        ec1, ec2, ec3 = st.columns([3, 2, 2])
                        with ec1:
                            part_note = st.text_input(
                                "메모",
                                placeholder="이 항목의 변경 메모",
                                key=f"tocnote::{relative}::{hi}::{si}",
                                label_visibility="collapsed",
                            )
                        with ec2:
                            use_ai_summary_part = st.checkbox(
                                "AI 변경 요약",
                                value=False,
                                key=f"tocai::{relative}::{hi}::{si}",
                            )
                        with ec3:
                            save_part = st.button(
                                "💾 저장" if part_dirty else "변경 없음",
                                disabled=not part_dirty,
                                type="primary" if part_dirty else "secondary",
                                use_container_width=True,
                                key=f"tocsave::{relative}::{hi}::{si}",
                            )
                        if save_part and part_dirty:
                            new_h2_text = "".join(
                                edited if k == si else s.full_text
                                for k, s in enumerate(h3_subs)
                            )
                            new_full = "".join(
                                new_h2_text if k == hi else s.full_text
                                for k, s in enumerate(h2_sections)
                            )
                            auto_note = part_note or f"항목 수정: {sub.title}"
                            result = _save_change(
                                backend, relative, original, new_full,
                                auto_note, use_ai_summary_part, api_key,
                            )
                            e = result["entry"]
                            st.success(
                                f"'{sub.title}' 저장 완료 · "
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

    if tab_store is not None:
        with tab_store:
            _render_store_add(backend, relative, original, regions, api_key)


# ---------------- 변경 로그 ----------------
@st.cache_data(show_spinner=False, ttl=300)
def cached_list_commits(backend_key: str, relative: str) -> list[dict]:
    backend, _ = build_backend()
    return backend.list_commits(relative, limit=30)


@st.cache_data(show_spinner=False, ttl=900)
def cached_commit_diff(backend_key: str, relative: str, sha: str) -> str:
    backend, _ = build_backend()
    return backend.commit_diff(relative, sha)


@st.cache_data(show_spinner=False, ttl=900)
def cached_read_at_commit(backend_key: str, relative: str, sha: str) -> str:
    backend, _ = build_backend()
    return backend.read_at_commit(relative, sha)


_KST = timezone(timedelta(hours=9))


def render_version_history(backend: Backend, backend_key: str, relative: str | None):
    st.subheader("📜 버전 히스토리")
    if relative is None:
        st.caption("파일을 선택하세요.")
        return

    commits = cached_list_commits(backend_key, relative)
    if not commits:
        st.caption(
            "저장 기록이 아직 없습니다. (로컬 폴더 모드에서는 버전 히스토리가 "
            "지원되지 않아요 — GitHub 모드에서만 동작합니다.)"
        )
        return

    st.caption(f"최근 {len(commits)}개 버전 · 최신순")

    for i, c in enumerate(commits):
        sha = c["sha"]
        try:
            label = c["date"].astimezone(_KST).strftime("%Y-%m-%d %H:%M")
        except Exception:
            label = str(c.get("date", ""))[:16]
        msg = (c.get("message") or "").split("\n")[0].strip()
        is_latest = i == 0
        title = ("🟢 " if is_latest else "🕘 ") + label
        if msg:
            title += f" · {msg}"
        with st.expander(title, expanded=False):
            diff = cached_commit_diff(backend_key, relative, sha)
            if diff:
                st.code(diff, language="diff")
            else:
                st.caption("(이 버전의 변경 내역을 표시할 수 없습니다)")
            if not is_latest:
                if st.button(
                    "⤺ 이 버전으로 되돌리기",
                    use_container_width=True,
                    key=f"vrev::{relative}::{sha}",
                ):
                    try:
                        old_content = cached_read_at_commit(
                            backend_key, relative, sha
                        )
                    except Exception as exc:
                        st.error(f"버전을 불러오지 못했습니다: {exc}")
                    else:
                        cur = cached_read(backend_key, relative)
                        _save_change(
                            backend, relative, cur, old_content,
                            f"{label} 버전으로 되돌림", False, "",
                        )
                        st.session_state.pop(f"buf::{relative}", None)
                        st.success(f"{label} 버전으로 되돌렸습니다.")
                        st.rerun()


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

    col_files, col_main, col_log = st.columns([2, 6, 2], gap="medium")

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
        render_version_history(backend, backend_key, selected_relative)


if __name__ == "__main__":
    main()
