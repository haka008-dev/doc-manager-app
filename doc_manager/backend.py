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
            if not p.is_file() or ".changelog" in p.parts:
                continue
            stat = p.stat()
            rel = str(p.relative_to(self.root)).replace("\\", "/")
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
                        # .changelog 등 숨김 폴더는 트리에서 제외 (.changelog는 별도 처리)
                        if item.name == ".changelog":
                            continue
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
