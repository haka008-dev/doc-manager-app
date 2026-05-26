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
import streamlit.components.v1 as components
from dotenv import load_dotenv

from doc_manager import ai, auth, changelog, files
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
    /* 편집 영역(textarea) 글자 키우기 */
    .stTextArea textarea { font-size: 1rem; line-height: 1.55; }
    /* "새 파트 추가" 박스 — expander 내부 입력 요소 컴팩트하게 */
    [data-testid="stExpander"] label p { font-size: 0.72rem; margin-bottom: 0.1rem; }
    [data-testid="stExpander"] [data-baseweb="select"] { font-size: 0.76rem; }
    [data-testid="stExpander"] [data-baseweb="select"] > div { min-height: 1.9rem; }
    [data-testid="stExpander"] [data-baseweb="select"] svg { width: 0.95rem; height: 0.95rem; }
    [data-testid="stExpander"] .stTextInput input { font-size: 0.76rem; padding: 0.22rem 0.5rem; }
    [data-testid="stExpander"] [data-testid="stCaptionContainer"] { font-size: 0.7rem; }
    [data-testid="stExpander"] [data-testid="stCaptionContainer"] p { font-size: 0.7rem; }
    /* 드롭다운을 펼쳤을 때의 옵션 목록 글자 축소 (body 최상단에 그려짐) */
    [data-baseweb="popover"] li,
    [data-baseweb="popover"] [role="option"] {
        font-size: 0.78rem; min-height: 0;
        padding-top: 0.22rem; padding-bottom: 0.22rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------- 편집기 TAB 들여쓰기 ----------------
# Streamlit textarea는 기본적으로 TAB이 포커스 이동이라, JS로 들여쓰기 동작 주입.
#   - TAB        : 커서 위치에 공백 4칸, 여러 줄 선택 시 줄마다 들여쓰기
#   - Shift+TAB  : 들여쓰기 해제(앞쪽 공백 최대 4칸 제거)
#   - 모든 동작은 execCommand("insertText")로 처리 → Ctrl+Z 실행취소 정상 동작
_TAB_INDENT_JS = """
<script>
const INDENT = "    ";  // 공백 4칸
const pdoc = window.parent.document;

function replaceRange(ta, selStart, selEnd, text, finalStart, finalEnd) {
    // 지정 범위를 선택한 뒤 insertText로 교체 — 브라우저 undo 스택에 기록되어
    // Ctrl+Z 로 되돌릴 수 있고, input 이벤트도 자동 발생해 React가 값을 인지함.
    ta.focus();
    ta.selectionStart = selStart;
    ta.selectionEnd = selEnd;
    const ok = pdoc.execCommand("insertText", false, text);
    if (!ok) {
        // execCommand 미지원 환경 폴백 (이 경우 undo는 제한될 수 있음)
        const setter = Object.getOwnPropertyDescriptor(
            window.parent.HTMLTextAreaElement.prototype, "value").set;
        const v = ta.value;
        setter.call(ta, v.slice(0, selStart) + text + v.slice(selEnd));
        ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
    ta.selectionStart = finalStart;
    ta.selectionEnd = finalEnd;
}

function onKeydown(e) {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const ta = e.target;
    const val = ta.value;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const lineStart = val.lastIndexOf("\\n", start - 1) + 1;

    // 단순 입력: 선택 없음 + TAB
    if (start === end && !e.shiftKey) {
        replaceRange(ta, start, end, INDENT,
                     start + INDENT.length, start + INDENT.length);
        return;
    }

    // 줄 단위 처리
    const region = val.slice(lineStart, end);
    const lines = region.split("\\n");

    if (e.shiftKey) {
        let firstDel = 0, totalDel = 0;
        const newLines = lines.map((ln, i) => {
            const m = ln.match(/^( {1,4}|\\t)/);
            const removed = m ? m[0].length : 0;
            if (i === 0) firstDel = removed;
            totalDel += removed;
            return removed ? ln.slice(removed) : ln;
        });
        if (totalDel === 0) return;  // 지울 들여쓰기 없음
        replaceRange(ta, lineStart, end, newLines.join("\\n"),
                     Math.max(lineStart, start - firstDel), end - totalDel);
    } else {
        const newLines = lines.map(ln => INDENT + ln);
        replaceRange(ta, lineStart, end, newLines.join("\\n"),
                     start + INDENT.length, end + INDENT.length * lines.length);
    }
}

function attach() {
    pdoc.querySelectorAll("textarea").forEach(ta => {
        if (ta.dataset.tabIndentBound) return;
        ta.dataset.tabIndentBound = "1";
        ta.addEventListener("keydown", onKeydown);
    });
}
attach();
setInterval(attach, 800);  // 탭 전환 등으로 새로 생기는 textarea도 처리
</script>
"""


def enable_tab_indent() -> None:
    """편집용 textarea에서 TAB이 들여쓰기로 동작하도록 JS 주입."""
    components.html(_TAB_INDENT_JS, height=0)


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


# ---------------- 로그인 게이트 (다중 사용자 + 무차별 대입 차단) ----------------
MAX_ATTEMPTS = 5          # 사용자별 누적 실패 허용 횟수
LOCKOUT_SECONDS = 300     # 잠금 시간 (5분)


@st.cache_resource
def _auth_state() -> dict:
    """모든 세션이 공유하는 인증 상태 — 사용자별 잠금 카운터.

    한 사용자가 5회 실패해도 다른 사용자에겐 영향 없음.
    프로세스 단위 공유라 새 탭으로 우회 불가.
    """
    return {"fail_counts": {}, "locked_until": {}}


def require_login(backend: Backend) -> auth.User:
    """로그인된 User를 반환. 인증 안 됐으면 로그인/부트스트랩 UI 표시 후 st.stop().

    - 로컬 모드: 인증 우회 (개발 편의용 가상 admin 반환)
    - GitHub 모드 + 사용자 없음: 부트스트랩 화면 (APP_PASSWORD로 첫 admin 생성)
    - GitHub 모드 + 사용자 있음: 일반 로그인 화면
    """
    # 로컬 모드는 가상 사용자로 우회 — 개발 편의
    if backend.name == "local":
        return auth.User(
            id="local", name="로컬 개발자", password_hash="",
            role=auth.ROLE_ADMIN, created_at="",
        )

    # 세션에 저장된 사용자가 있으면 실재 여부 재검증
    if st.session_state.get("user"):
        u = st.session_state["user"]
        if isinstance(u, dict):  # 직렬화돼 있던 경우
            u = auth.User(**u)
            st.session_state["user"] = u
        existing = auth.find_user(auth.load_users(backend), u.id)
        if existing:
            return existing
        # 사용자가 삭제됐거나 변경됨 — 세션 무효화
        st.session_state.pop("user", None)

    users = auth.load_users(backend)
    if not users:
        _render_bootstrap_page(backend)
    else:
        _render_login_page(backend, users)
    st.stop()


def _render_bootstrap_page(backend: Backend) -> None:
    """첫 사용자가 없을 때 — 기존 APP_PASSWORD를 일회용 키로 써서 admin 생성."""
    setup_secret = _secret("APP_PASSWORD")

    st.title("🔧 초기 관리자 계정 설정")

    if not setup_secret:
        st.error(
            "초기 설정용 `APP_PASSWORD`가 secrets에 없습니다. "
            "Streamlit Cloud > Settings > Secrets에서 `APP_PASSWORD` 값을 "
            "임시로 설정한 뒤 이 화면에서 사용한 다음 제거하세요."
        )
        return

    st.markdown(
        "아직 등록된 사용자가 없습니다. 첫 **관리자 계정**을 만들어주세요. "
        "이후엔 이 화면이 더 이상 나타나지 않습니다."
    )
    st.caption("초기 설정 비밀번호는 기존 앱 비밀번호(`APP_PASSWORD`)와 같습니다.")

    setup_pw = st.text_input("초기 설정 비밀번호 (APP_PASSWORD)", type="password")
    col1, col2 = st.columns(2)
    with col1:
        new_id = st.text_input("관리자 아이디", placeholder="영문/숫자/_, 2-32자")
    with col2:
        new_name = st.text_input("이름", placeholder="화면 표시명 (예: 김매니저)")
    new_pw = st.text_input("새 비밀번호", type="password", placeholder="최소 8자")
    new_pw2 = st.text_input("새 비밀번호 확인", type="password")

    if st.button("관리자 계정 만들기", type="primary"):
        if not hmac.compare_digest(
            setup_pw.encode("utf-8"), setup_secret.encode("utf-8")
        ):
            st.error("초기 설정 비밀번호가 일치하지 않습니다.")
            return
        err = auth.validate_user_id(new_id) or auth.validate_password(new_pw)
        if err:
            st.error(err)
            return
        if not new_name.strip():
            st.error("이름을 입력하세요.")
            return
        if new_pw != new_pw2:
            st.error("비밀번호가 일치하지 않습니다.")
            return
        admin = auth.make_user(new_id, new_name, new_pw, auth.ROLE_ADMIN)
        auth.save_users(backend, [admin],
                        commit_message=f"bootstrap admin user: {admin.id}")
        st.session_state["user"] = admin
        st.success(f"{admin.name} 관리자 계정 생성 완료. 메인 화면으로 이동합니다.")
        st.rerun()


def _render_login_page(backend: Backend, users: list[auth.User]) -> None:
    st.title("🔒 챗봇 문서 관리기")

    state = _auth_state()
    now = time.time()

    user_id = st.text_input("아이디", key="login_id_input")
    pw = st.text_input("비밀번호", type="password", key="login_pw_input")

    # 입력된 ID가 잠금 상태면 시도 자체를 막음
    if user_id:
        remaining = state["locked_until"].get(user_id, 0) - now
        if remaining > 0:
            mins = int(remaining // 60) + 1
            st.error(
                f"이 아이디는 비밀번호를 여러 번 틀려 잠겼습니다. "
                f"약 {mins}분 후 다시 시도하세요."
            )
            return

    if st.button("로그인", type="primary"):
        if not user_id or not pw:
            st.warning("아이디와 비밀번호를 입력하세요.")
            return
        user = auth.find_user(users, user_id)
        if user and auth.verify_password(pw, user.password_hash):
            state["fail_counts"].pop(user_id, None)
            st.session_state["user"] = user
            st.rerun()
        else:
            fc = state["fail_counts"].get(user_id, 0) + 1
            state["fail_counts"][user_id] = fc
            left = MAX_ATTEMPTS - fc
            if left <= 0:
                state["locked_until"][user_id] = now + LOCKOUT_SECONDS
                state["fail_counts"].pop(user_id, None)
                st.error(
                    f"비밀번호를 {MAX_ATTEMPTS}회 틀렸습니다. "
                    f"이 아이디는 {LOCKOUT_SECONDS // 60}분간 잠깁니다."
                )
            else:
                st.error(
                    f"아이디 또는 비밀번호가 일치하지 않습니다. (남은 시도: {left}회)"
                )


# ---------------- 백엔드 선택 ----------------
@st.cache_resource(show_spinner=False)
def _get_github_backend(token: str, repo: str, branch: str, prefix: str) -> GitHubBackend:
    """GitHub 백엔드를 한 번만 생성해 재사용 — 매 rerun마다 저장소를
    다시 조회하지 않도록 캐싱 (앱 속도 개선의 핵심)."""
    return GitHubBackend(token=token, repo_full_name=repo,
                         branch=branch, docs_prefix=prefix)


def build_backend() -> tuple[Backend, str]:
    """반환: (backend, 표시용 라벨)"""
    gh_token = _secret("GITHUB_TOKEN")
    gh_repo = _secret("GITHUB_REPO")  # "owner/repo"
    gh_branch = _secret("GITHUB_BRANCH", "main")
    gh_prefix = _secret("GITHUB_DOCS_PREFIX", "")

    if gh_token and gh_repo:
        backend = _get_github_backend(gh_token, gh_repo, gh_branch, gh_prefix)
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
def render_sidebar(backend_label: str, user: auth.User) -> str:
    st.sidebar.header("⚙️ 설정")
    st.sidebar.markdown(f"**저장소:** {backend_label}")
    role_badge = "👑 admin" if user.is_admin else "✏️ editor"
    st.sidebar.markdown(f"**로그인:** 👤 {user.name} · {role_badge}")

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

    # 관리자만 보이는 사용자 관리 페이지 진입 버튼
    if user.is_admin:
        if st.sidebar.button("👥 사용자 관리", use_container_width=True):
            st.session_state["show_admin"] = True
            st.rerun()

    if st.sidebar.button("🚪 로그아웃", use_container_width=True):
        st.session_state.pop("user", None)
        st.session_state.pop("show_admin", None)
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
    user: auth.User | None = None,
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
    if user and user.id != "local":
        msg += f" — by {user.name}"
    backend.write_file(relative, new_text, commit_message=msg)
    added, removed = changelog.diff_stats(original, new_text)
    invalidate_cache()
    return {
        "entry": {"added": added, "removed": removed},
        "ai_summary": ai_summary,
    }


def _render_store_add(backend, relative, original, regions, api_key, user):
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
                f"매장 추가: {name.strip()} ({gu_name})", False, api_key, user,
            )
            e = result["entry"]
            st.success(f"'{name.strip()}' 추가 완료 · +{e['added']} / -{e['removed']} 줄")
            st.session_state.pop(f"buf::{relative}", None)
            st.rerun()


def render_editor(backend: Backend, backend_key: str, relative: str,
                  api_key: str, user: auth.User):
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
            height=720,
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
                backend, relative, original, new_text, note, use_ai_summary,
                api_key, user,
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

            # ---- 새 파트 추가 ----
            with st.expander("➕ 새 파트 추가", expanded=False):
                st.caption(
                    "상위 그룹(##)을 고르고 제목을 입력하면 그 그룹 끝에 "
                    "새 ### 파트가 생성됩니다. 생성 후 바로 편집할 수 있어요."
                )
                h2_choices = [
                    i for i, s in enumerate(h2_sections) if not s.is_intro
                ]
                pa1, pa2 = st.columns([2, 3])
                with pa1:
                    new_h2_idx = st.selectbox(
                        "상위 그룹 (##)",
                        h2_choices,
                        format_func=lambda i: h2_sections[i].title,
                        key=f"newpart_h2::{relative}",
                    )
                with pa2:
                    new_part_title = st.text_input(
                        "새 파트 제목",
                        placeholder="예: 환불 정책",
                        key=f"newpart_title::{relative}",
                    )
                if st.button(
                    "➕ 파트 생성", type="primary", key=f"newpart_btn::{relative}"
                ):
                    title = new_part_title.strip()
                    if not title:
                        st.error("새 파트 제목을 입력하세요.")
                    else:
                        target = h2_sections[new_h2_idx]
                        base = target.full_text
                        if not base.endswith("\n"):
                            base += "\n"
                        if not base.endswith("\n\n"):
                            base += "\n"
                        new_h2_text = base + f"### {title}\n\n\n"
                        new_full = "".join(
                            new_h2_text if k == new_h2_idx else s.full_text
                            for k, s in enumerate(h2_sections)
                        )
                        # 새 파트의 인덱스 = 이 그룹의 기존 H3 개수
                        old_subs = files.split_sections(
                            target.full_text, level=3
                        )
                        _save_change(
                            backend, relative, original, new_full,
                            f"새 파트 추가: {title}", False, api_key, user,
                        )
                        st.session_state[sel_key] = (new_h2_idx, len(old_subs))
                        st.session_state.pop(f"buf::{relative}", None)
                        st.session_state.pop(f"newpart_title::{relative}", None)
                        st.success(f"'{title}' 파트를 추가했습니다.")
                        st.rerun()

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
                            height=620,
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
                                auto_note, use_ai_summary_part, api_key, user,
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
            _render_store_add(backend, relative, original, regions, api_key, user)

    # 편집용 textarea에서 TAB 들여쓰기 활성화
    enable_tab_indent()


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


def render_version_history(backend: Backend, backend_key: str,
                           relative: str | None, user: auth.User):
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
                            f"{label} 버전으로 되돌림", False, "", user,
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


# ---------------- 관리자 페이지 ----------------
def render_admin_page(backend: Backend, cur_user: auth.User) -> None:
    """사용자 추가/삭제/역할/비밀번호 초기화. admin만 진입 가능."""
    if not cur_user.is_admin:
        st.error("관리자만 접근할 수 있는 페이지입니다.")
        return

    st.subheader("👥 사용자 관리")
    st.caption("사용자를 추가/삭제하거나 비밀번호·역할을 변경할 수 있습니다.")

    users = auth.load_users(backend)

    # ----- 등록된 사용자 목록 -----
    st.markdown("#### 등록된 사용자")
    if not users:
        st.info("등록된 사용자가 없습니다.")
    for u in users:
        is_self = u.id == cur_user.id
        title = f"{u.name} (`{u.id}`) — {u.role}"
        if is_self:
            title += " · 본인"
        with st.expander(title, expanded=False):
            st.caption(f"생성일: {u.created_at}")

            # 비밀번호 초기화
            with st.form(f"reset_pw_{u.id}", clear_on_submit=True):
                new_pw = st.text_input(
                    "새 비밀번호", type="password", placeholder="최소 8자",
                    key=f"newpw_{u.id}",
                )
                if st.form_submit_button("비밀번호 변경"):
                    err = auth.validate_password(new_pw)
                    if err:
                        st.error(err)
                    else:
                        u.password_hash = auth.hash_password(new_pw)
                        auth.save_users(
                            backend, users,
                            commit_message=f"reset password: {u.id}",
                        )
                        st.success(f"{u.name}의 비밀번호를 변경했습니다.")
                        st.rerun()

            # 역할 변경 (본인 제외 — 마지막 admin 보호)
            if not is_self:
                col_r1, col_r2 = st.columns([3, 2])
                with col_r1:
                    new_role = st.selectbox(
                        "역할", [auth.ROLE_EDITOR, auth.ROLE_ADMIN],
                        index=0 if u.role == auth.ROLE_EDITOR else 1,
                        key=f"role_sel_{u.id}",
                    )
                with col_r2:
                    st.write("")
                    if new_role != u.role and st.button(
                        f"{new_role}(으)로 변경", key=f"role_btn_{u.id}",
                        use_container_width=True,
                    ):
                        u.role = new_role
                        auth.save_users(
                            backend, users,
                            commit_message=f"change role: {u.id} → {new_role}",
                        )
                        st.success("역할 변경 완료.")
                        st.rerun()

                # 삭제
                if st.button(
                    "🗑 이 사용자 삭제",
                    key=f"del_btn_{u.id}",
                    help="삭제된 사용자는 더 이상 로그인할 수 없습니다.",
                ):
                    new_list = [x for x in users if x.id != u.id]
                    auth.save_users(
                        backend, new_list,
                        commit_message=f"remove user: {u.id}",
                    )
                    st.success(f"{u.name} 삭제됨.")
                    st.rerun()

    # ----- 새 사용자 추가 -----
    st.divider()
    st.markdown("#### 새 사용자 추가")
    with st.form("add_user", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            new_id = st.text_input("아이디", placeholder="영문/숫자/_, 2-32자")
            new_role = st.selectbox(
                "역할", [auth.ROLE_EDITOR, auth.ROLE_ADMIN],
                help="editor: 문서 편집만 / admin: 사용자 관리까지",
            )
        with col2:
            new_name = st.text_input("이름", placeholder="화면 표시명")
            new_pw = st.text_input(
                "임시 비밀번호", type="password",
                placeholder="최소 8자 (사용자에게 전달)",
            )

        if st.form_submit_button("➕ 사용자 추가", type="primary"):
            err = auth.validate_user_id(new_id) or auth.validate_password(new_pw)
            if err:
                st.error(err)
            elif not new_name.strip():
                st.error("이름을 입력하세요.")
            elif auth.find_user(users, new_id):
                st.error(f"아이디 '{new_id}'는 이미 사용 중입니다.")
            else:
                new_user = auth.make_user(new_id, new_name, new_pw, new_role)
                users.append(new_user)
                auth.save_users(
                    backend, users,
                    commit_message=f"add user: {new_user.id}",
                )
                st.success(
                    f"✅ {new_user.name}({new_user.id}) 추가됨. "
                    "임시 비밀번호를 본인에게 전달해 주세요."
                )
                st.rerun()


# ---------------- 메인 ----------------
def main():
    # 1) 백엔드 먼저 구성 (사용자 데이터 읽기에 필요)
    try:
        backend, backend_label = build_backend()
    except Exception as e:
        st.error(f"백엔드 초기화 실패: {e}")
        st.stop()

    # 2) 로그인 게이트 (실패 시 내부에서 st.stop)
    user = require_login(backend)

    # 3) 사이드바 (현재 사용자 표시 + 관리자 링크 + 로그아웃)
    api_key = render_sidebar(backend_label, user)
    backend_key = backend_cache_key(backend_label)

    st.title("📚 챗봇 문서 관리기")
    st.caption(backend_label)

    # 4) 관리자 페이지 라우팅
    if st.session_state.get("show_admin"):
        if st.button("◀ 메인으로 돌아가기"):
            st.session_state.pop("show_admin", None)
            st.rerun()
        render_admin_page(backend, user)
        return

    # 5) 일반 사용자 UI
    col_files, col_main, col_log = st.columns([2, 6, 2], gap="medium")

    with col_files:
        st.subheader("📁 문서")
        selected_relative = render_file_list(backend_key)

    with col_main:
        if selected_relative is None:
            st.info("좌측에서 파일을 선택하세요.")
        else:
            render_editor(backend, backend_key, selected_relative, api_key, user)
            st.divider()
            render_ai_review(backend, backend_key, selected_relative, api_key)

    with col_log:
        render_version_history(backend, backend_key, selected_relative, user)


if __name__ == "__main__":
    main()
