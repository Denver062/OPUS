# OPUS

Windows 11용 개인/팀 앱 카탈로그, 자동화, 워크스페이스 관리자입니다. 화면은 로컬 웹 UI이고, Windows 호스트는 C/WebView2로 작성합니다.

## 현재 포함된 MVP

- JSON 카탈로그에서 GitHub 앱 목록을 표시하고, 검증된 `wingetId`만으로 설치·제거 작업을 비동기 실행합니다.
- 자동화는 Shortcuts 스타일의 순서형 액션과 `if / repeat / end` 블록을 제공합니다. 현재 `notify`, `wait`, HTTPS `open_url`을 실행합니다.
- 워크스페이스는 관리자, 부관리자, 관리 대상 장치(이름은 이후 변경 가능) 역할, 권한 정책, 작업 대기열, 감사 로그를 제공합니다.
- Python 표준 라이브러리만 쓰는 로컬 API와 데이터 저장소를 제공합니다. 호스트를 만들기 전에도 브라우저에서 검증할 수 있습니다.

## 실행

```powershell
python backend/server.py
```

그 뒤 `http://127.0.0.1:47821`을 엽니다. Windows 호스트는 CMake가 WebView2 SDK를 받아 빌드하며, 빌드 결과물 옆에 웹 UI와 로컬 API를 자동 복사합니다.

```powershell
cmake -S native -B build
cmake --build build --config Release
```

실행 파일은 Microsoft Edge WebView2 Evergreen Runtime과 `python.exe`가 필요합니다.

## 카탈로그 형식

기본 원격 URL은 `catalog/sources.json`에서만 바꿉니다. 설정 화면의 **지금 동기화**는 GitHub HTTPS 원본을 읽기 전용으로 `.opus-catalog-cache`에 복제합니다. 각 앱 폴더는 `manifest.json`과 payload 폴더를 가져야 합니다. 예시는 `catalog/apps/`에 있습니다.

```text
repository/
  apps/
    sample-tool/
      manifest.json       # 설치 전에 표시할 신뢰 가능한 정보
      payload/            # 설치 파일 또는 소스
```

`manifest.json`의 `install.command`와 `uninstall.command`는 관리자가 신뢰한 저장소에서만 허용해야 합니다. 실제 배포판에서는 서명 검증, SHA-256 검증, 권한 승인 UI를 반드시 추가하세요.

현재 MVP는 임의 명령 문자열을 허용하지 않습니다. 설치 가능한 앱은 검증된 `wingetId`를 선언해야 하며, OPUS는 인자를 배열로 고정해 `winget`을 호출합니다.

## 보안 및 동기화 경계

이 MVP의 워크스페이스 데이터는 로컬 시연용입니다. 여러 PC 제어를 출시하려면 중앙 서비스, 장치별 인증서, 명령 서명, 감사 로그, 역할별 서버 측 인가가 필요합니다. 클라이언트 UI의 역할 표시는 보안 경계가 아닙니다.
