# 📚 챗봇 문서 관리기

챗봇이 참조하는 마크다운 문서를 한곳에서 보고 편집하고, 변경 이력을 자동으로 추적합니다.
**로컬 폴더** 또는 **GitHub repo** 두 가지 저장소를 같은 인터페이스로 다룹니다.

## 핵심 기능

- 파일 탐색 + 검색
- **통합 편집** / **파트별 편집** (헤더 H1/H2/H3 기준 자동 분할)
- **통합 .md 다운로드** — 분할 편집해도 받을 때는 한 파일
- **변경 로그**: 저장할 때마다 diff와 함께 자동 기록
- **AI 검토 / 변경 요약**: Claude API 연동 (선택)
- **비밀번호 게이트**: 본인만 접속하도록 (선택)

## 실행 방식 2가지

### 1. 로컬 (본인 PC에서만)

```powershell
cd C:\Users\user\Desktop\doc-manager
pip install -r requirements.txt
streamlit run app.py
```

또는 바탕화면의 **챗봇 문서 관리기** 아이콘 더블클릭.

기본 문서 폴더: `C:\Users\user\Desktop\챗봇` (사이드바에서 변경 가능)

### 2. 클라우드 (`<이름>.streamlit.app` URL)

아래 [배포 가이드](#배포-가이드-streamlit-cloud) 섹션 참고.

## 환경 설정

`.streamlit/secrets.toml.example`을 `.streamlit/secrets.toml`로 복사 후 값 채우기:

| 키 | 용도 | 필수? |
|---|---|---|
| `APP_PASSWORD` | 앱 접속 비밀번호 | 본인만 쓰려면 권장 |
| `ANTHROPIC_API_KEY` | Claude API 키 | AI 기능 쓰려면 |
| `GITHUB_TOKEN` | GitHub Personal Access Token | 클라우드 배포 시 |
| `GITHUB_REPO` | `owner/repo` 형식 | 클라우드 배포 시 |
| `GITHUB_BRANCH` | 작업 브랜치 (기본 `main`) | 선택 |
| `GITHUB_DOCS_PREFIX` | repo 내 문서 하위 폴더 | 선택 |
| `LOCAL_DOCS_PATH` | 로컬 모드 기본 폴더 | 선택 |

GitHub 설정이 있으면 GitHub 모드, 없으면 로컬 모드로 자동 전환됩니다.

---

## 배포 가이드 (Streamlit Cloud)

여기서부터는 **한 번만 셋업**하면 됩니다. 작업하실 PC와 별개로, 어디서든 `<이름>.streamlit.app` URL로 접속할 수 있게 됩니다.

### Step 1. GitHub 준비

1. [github.com](https://github.com) 가입 (이미 있으면 스킵)
2. **새 private repo 생성** — 예: `chatbot-docs`
   - "New repository" → Private 선택 → Create
3. 챗봇 문서들을 그 repo에 올리기 (가장 쉬운 방법):
   - 새 repo 페이지에서 "uploading an existing file" 링크
   - `C:\Users\user\Desktop\챗봇` 안의 `.md` 파일들을 끌어다 놓기 → Commit

> 💡 별도의 git 명령어를 쓰셔도 됩니다. 익숙한 방법으로.

### Step 2. GitHub Personal Access Token 발급

1. https://github.com/settings/tokens 접속
2. **Generate new token** → **Fine-grained tokens** 추천
3. 설정:
   - Token name: `doc-manager`
   - Expiration: 원하는 기간 (예: 1년)
   - Repository access: **Only select repositories** → `chatbot-docs` 선택
   - Repository permissions:
     - **Contents: Read and write** (필수)
     - **Metadata: Read** (기본)
4. **Generate token** → 표시되는 `github_pat_...` 토큰을 복사 (한 번만 보임)

### Step 3. doc-manager 코드도 GitHub에 올리기

Streamlit Cloud는 GitHub repo를 deploy하므로, **앱 코드 자체도** GitHub에 있어야 합니다.

1. 별도의 repo 생성 — 예: `doc-manager` (Public/Private 둘 다 OK)
2. `C:\Users\user\Desktop\doc-manager` 폴더의 파일들을 push
   - **주의**: `.streamlit/secrets.toml`은 절대 올리지 말 것 (`.gitignore`에 포함됨)
   - `.env` 파일도 올리지 말 것

### Step 4. Streamlit Cloud 배포

1. https://streamlit.io/cloud 접속 → GitHub로 로그인
2. **New app** 클릭
3. 설정:
   - Repository: `<본인>/doc-manager`
   - Branch: `main`
   - Main file path: `app.py`
   - App URL: 원하는 이름 (예: `my-docs` → `my-docs.streamlit.app`)
4. **Advanced settings** → **Secrets** 에 `.streamlit/secrets.toml` 내용 붙여넣기:

   ```toml
   APP_PASSWORD = "강한-비밀번호"
   ANTHROPIC_API_KEY = "sk-ant-..."
   GITHUB_TOKEN = "github_pat_..."
   GITHUB_REPO = "본인계정/chatbot-docs"
   GITHUB_BRANCH = "main"
   GITHUB_DOCS_PREFIX = ""
   ```

5. **Deploy** 클릭

### Step 5. 접속

- 약 1-2분 후 `https://<이름>.streamlit.app` 로 접속 가능
- 비밀번호 입력 후 사용
- 문서 편집 → 저장 → 자동으로 `chatbot-docs` repo에 커밋됨

> 💡 챗봇 파이프라인이 이 repo를 watch하면, 문서를 수정하는 즉시 챗봇 인덱스를 재빌드하도록 자동화도 가능합니다.

### 비용

- Streamlit Cloud: 무료
- GitHub: Private repo 무제한 무료 (개인용)
- Anthropic API: 사용량 기반 (AI 기능 쓸 때만)

---

## 폴더 구조

```
doc-manager/
├── app.py                       # Streamlit 메인
├── doc_manager/
│   ├── backend.py               # Local/GitHub 백엔드 추상화
│   ├── files.py                 # 마크다운 텍스트 처리 (분할/병합)
│   ├── changelog.py             # diff 기반 변경 이력
│   └── ai.py                    # Claude API
├── requirements.txt
├── .streamlit/
│   ├── secrets.toml             # 실제 설정 (gitignore)
│   └── secrets.toml.example     # 템플릿
├── .gitignore
├── run.bat                      # Windows 더블클릭 실행
└── README.md
```

## 변경 이력 저장 위치

- **로컬 모드**: `<문서폴더>/.changelog/<파일명>.jsonl`
- **GitHub 모드**: repo 안의 `.changelog/<파일명>.jsonl` (커밋으로 자동 푸시)
