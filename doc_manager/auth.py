"""사용자 인증·관리 — 다중 사용자 + 역할(admin/editor).

사용자 데이터는 백엔드의 `.users/users.json`에 보관 (비공개 repo에만 존재).
비밀번호는 bcrypt 해시로만 저장 — 평문은 절대 디스크에 남기지 않음.

역할:
- admin: 문서 편집 + 사용자 관리 페이지 접근 (추가/삭제/비밀번호 초기화)
- editor: 문서 편집만 가능
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime

import bcrypt

USERS_PATH = ".users/users.json"

ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"
VALID_ROLES = {ROLE_ADMIN, ROLE_EDITOR}


@dataclass
class User:
    """단일 사용자 정보. password_hash는 bcrypt 해시 문자열."""
    id: str                # 로그인 ID (영문/숫자/언더스코어)
    name: str              # 화면 표시명 (예: '김매니저')
    password_hash: str     # bcrypt hash — 평문은 절대 보관 X
    role: str              # 'admin' or 'editor'
    created_at: str        # ISO 8601 시각

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


# ---------- 비밀번호 해시 ----------
def hash_password(plaintext: str) -> str:
    """bcrypt로 해시. 솔트는 자동 생성 — 같은 평문도 매번 다른 해시."""
    return bcrypt.hashpw(
        plaintext.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def verify_password(plaintext: str, password_hash: str) -> bool:
    """비밀번호 검증 — 상수 시간 비교 (timing attack 방어)."""
    if not plaintext or not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            plaintext.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


# ---------- 사용자 저장소 ----------
def load_users(backend) -> list[User]:
    """백엔드에서 사용자 목록 로드. 파일 없거나 빈 경우 빈 리스트."""
    raw = backend.read_text_or_empty(USERS_PATH)
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    users = []
    for u in data.get("users", []):
        try:
            users.append(User(**u))
        except TypeError:
            continue  # 스키마 불일치는 무시
    return users


def save_users(backend, users: list[User], commit_message: str = "") -> None:
    """사용자 목록을 JSON으로 저장 (해시만, 평문 비밀번호는 절대 없음)."""
    data = {"users": [asdict(u) for u in users]}
    backend.write_file(
        USERS_PATH,
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        commit_message=commit_message or "update users",
    )


def find_user(users: list[User], user_id: str) -> User | None:
    for u in users:
        if u.id == user_id:
            return u
    return None


# ---------- 입력 유효성 ----------
_ID_RE = re.compile(r"^[a-zA-Z0-9_]{2,32}$")


def validate_user_id(user_id: str) -> str | None:
    """검증 통과면 None. 그 외엔 사용자에게 보여줄 오류 메시지."""
    if not user_id:
        return "아이디를 입력하세요."
    if not _ID_RE.fullmatch(user_id):
        return "아이디는 영문·숫자·언더스코어 2-32자만 가능합니다."
    return None


def validate_password(password: str) -> str | None:
    if not password:
        return "비밀번호를 입력하세요."
    if len(password) < 8:
        return "비밀번호는 최소 8자 이상이어야 합니다."
    return None


def make_user(user_id: str, name: str, password: str, role: str) -> User:
    """새 User 객체 생성 — 평문 비밀번호는 즉시 해시되어 사라짐."""
    return User(
        id=user_id,
        name=name.strip(),
        password_hash=hash_password(password),
        role=role if role in VALID_ROLES else ROLE_EDITOR,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
