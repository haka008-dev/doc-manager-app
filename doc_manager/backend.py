"""문서 저장소 백엔드 — 로컬 폴더 또는 GitHub repo.

같은 인터페이스(list_md_files / read_file / write_file)를 제공해서
app.py 코드는 어느 백엔드인지 신경 쓰지 않아도 됩니다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass
class FileMeta:
    """파일 메타데이터 — 백엔드와 무관한 표현."""
    relative: str          # 백엔드 내부 경로 (예: "manual/intro.md")
    modified: datetime     # 최종 수정 시각 (best-effort)
    size: int              # 바이트 크기


class Backend(Protocol):
    name: str

    def list_md_files(self) -> list[FileMeta]: ...
    def read_file(self, relative: str) -> str: ...
    def write_file(self, relative: str, content: str, commit_message: str = "") -> None: ...
    def read_text_or_empty(self, relative: str) -> str: ...
    def append_text(self, relative: str, line: str, commit_message: str = "") -> None: ...
    def list_dir(self, rel_dir: str) -> list[str]: ...
    def list_commits(self, relative: str, limit: int = 30) -> list[dict]: ...
    def read_at_commit(self, relative: str, sha: str) -> str: ...
    def commit_diff(self, relative: str, sha: str) -> str: ...


# ---------- 로컬 폴더 백엔드 ----------
class LocalBackend:
    """로컬 디렉토리를 저장소로 사용."""
    name = "local"

    def __init__(self, root: Path):
        self.root = Path(root)

    def _abs(self, relative: str) -> Path:
        return self.root / relative

    def list_md_files(self) -> list[FileMeta]:
        if not self.root.exists() or not self.root.is_dir():
            return []
        results: list[FileMeta] = []
        for p in self.root.rglob("*.md"):
            if not p.is_file():
                continue
            rel_path = p.relative_to(self.root)
            # .changelog / .versions 등 숨김 폴더 안의 파일은 제외
            if any(part.startswith(".") for part in rel_path.parts):
                continue
            stat = p.stat()
            rel = str(rel_path).replace("\\", "/")
            results.append(
                FileMeta(
                    relative=rel,
                    modified=datetime.fromtimestamp(stat.st_mtime),
                    size=stat.st_size,
                )
            )
        results.sort(key=lambda f: f.modified, reverse=True)
        return results

    def read_file(self, relative: str) -> str:
        return self._abs(relative).read_text(encoding="utf-8")

    def write_file(self, relative: str, content: str, commit_message: str = "") -> None:
        path = self._abs(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read_text_or_empty(self, relative: str) -> str:
        p = self._abs(relative)
        if not p.exists():
            return ""
        return p.read_text(encoding="utf-8")

    def append_text(self, relative: str, line: str, commit_message: str = "") -> None:
        path = self._abs(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line)

    def list_dir(self, rel_dir: str) -> list[str]:
        d = self._abs(rel_dir)
        if not d.exists() or not d.is_dir():
            return []
        return sorted(p.name for p in d.iterdir() if p.is_file())

    # ----- 버전 히스토리 (로컬 모드는 미지원) -----
    def list_commits(self, relative: str, limit: int = 30) -> list[dict]:
        return []

    def read_at_commit(self, relative: str, sha: str) -> str:
        raise RuntimeError("로컬 폴더 모드는 버전 히스토리를 지원하지 않습니다.")

    def commit_diff(self, relative: str, sha: str) -> str:
        return ""


# ---------- GitHub 백엔드 ----------
class GitHubBackend:
    """GitHub Contents API로 저장소 사용. 저장할 때마다 커밋이 생성됨."""
    name = "github"

    def __init__(
        self,
        token: str,
        repo_full_name: str,
        branch: str = "main",
        docs_prefix: str = "",
    ):
        try:
            from github import Github, Auth
        except ImportError as e:
            raise RuntimeError(
                "PyGithub 미설치. `pip install PyGithub` 실행 필요."
            ) from e
        self._gh = Github(auth=Auth.Token(token))
        self._repo = self._gh.get_repo(repo_full_name)
        self.branch = branch
        self.docs_prefix = docs_prefix.strip("/")
        self._sha_cache: dict[str, str] = {}

    # ----- 경로 도우미 -----
    def _path_in_repo(self, relative: str) -> str:
        if not self.docs_prefix:
            return relative
        return f"{self.docs_prefix}/{relative}"

    def _path_to_relative(self, full_path: str) -> str:
        if self.docs_prefix and full_path.startswith(self.docs_prefix + "/"):
            return full_path[len(self.docs_prefix) + 1 :]
        return full_path

    # ----- 파일 목록 -----
    def list_md_files(self) -> list[FileMeta]:
        results: list[FileMeta] = []
        start = self.docs_prefix or ""
        try:
            stack = [self._repo.get_contents(start, ref=self.branch)]
        except Exception:
            return []
        if not isinstance(stack[0], list):
            stack[0] = [stack[0]]

        while stack:
            current = stack.pop()
            for item in current:
                if item.type == "dir":
                    if item.name.startswith("."):
                        continue  # .changelog, .versions 등 숨김 폴더 제외
                    try:
                        sub = self._repo.get_contents(item.path, ref=self.branch)
                        if not isinstance(sub, list):
                            sub = [sub]
                        stack.append(sub)
                    except Exception:
                        continue
                elif item.type == "file" and item.path.endswith(".md"):
                    rel = self._path_to_relative(item.path)
                    self._sha_cache[item.path] = item.sha
                    results.append(
                        FileMeta(
                            relative=rel,
                            modified=datetime.utcnow(),  # API에서 정확한 mtime 미제공, 단순화
                            size=item.size,
                        )
                    )
        results.sort(key=lambda f: f.relative)
        return results

    # ----- 읽기/쓰기 -----
    def read_file(self, relative: str) -> str:
        full = self._path_in_repo(relative)
        item = self._repo.get_contents(full, ref=self.branch)
        if isinstance(item, list):
            raise RuntimeError(f"디렉토리 경로입니다: {full}")
        self._sha_cache[full] = item.sha
        return item.decoded_content.decode("utf-8")

    def write_file(self, relative: str, content: str, commit_message: str = "") -> None:
        full = self._path_in_repo(relative)
        msg = commit_message or f"update {relative}"
        sha = self._sha_cache.get(full)
        if sha is None:
            # 새 파일이거나 캐시 없음 — 한 번 가져와서 sha 확보
            try:
                item = self._repo.get_contents(full, ref=self.branch)
                if isinstance(item, list):
                    raise RuntimeError(f"디렉토리 경로입니다: {full}")
                sha = item.sha
            except Exception:
                sha = None

        if sha:
            self._repo.update_file(
                full, msg, content, sha, branch=self.branch
            )
        else:
            self._repo.create_file(full, msg, content, branch=self.branch)
        # 캐시는 새 sha를 받아야 하니 일단 비움
        self._sha_cache.pop(full, None)

    def read_text_or_empty(self, relative: str) -> str:
        try:
            return self.read_file(relative)
        except Exception:
            return ""

    def append_text(self, relative: str, line: str, commit_message: str = "") -> None:
        current = self.read_text_or_empty(relative)
        new = current + line
        msg = commit_message or f"append {relative}"
        self.write_file(relative, new, commit_message=msg)

    def list_dir(self, rel_dir: str) -> list[str]:
        full = self._path_in_repo(rel_dir)
        try:
            items = self._repo.get_contents(full, ref=self.branch)
        except Exception:
            return []
        if not isinstance(items, list):
            items = [items]
        return sorted(it.name for it in items if it.type == "file")

    # ----- 버전 히스토리 (GitHub 커밋 기록 활용) -----
    def list_commits(self, relative: str, limit: int = 30) -> list[dict]:
        full = self._path_in_repo(relative)
        out: list[dict] = []
        try:
            commits = self._repo.get_commits(path=full, sha=self.branch)
            for c in commits[:limit]:
                out.append({
                    "sha": c.sha,
                    "date": c.commit.author.date,
                    "message": c.commit.message,
                })
        except Exception:
            pass
        return out

    def read_at_commit(self, relative: str, sha: str) -> str:
        full = self._path_in_repo(relative)
        item = self._repo.get_contents(full, ref=sha)
        if isinstance(item, list):
            raise RuntimeError(f"디렉토리 경로입니다: {full}")
        return item.decoded_content.decode("utf-8")

    def commit_diff(self, relative: str, sha: str) -> str:
        full = self._path_in_repo(relative)
        try:
            commit = self._repo.get_commit(sha)
            for f in commit.files:
                if f.filename == full:
                    return f.patch or ""
        except Exception:
            pass
        return ""
