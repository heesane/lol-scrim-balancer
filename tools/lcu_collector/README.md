# 내전 결과 수집기 (ScrimCollector)

롤 클라이언트의 로컬 LCU API에서 5대5 소환사의 협곡 사설 내전 결과를 읽어 웹앱(`/api/sync`)으로 보내는 Windows용 프로그램입니다.
Vercel이 `api/` 폴더의 파일을 서버리스 함수로 배포하므로 수집기는 이 폴더(`tools/lcu_collector/`)에 둡니다.

## exe로 실행하기 (권장, 파이썬 설치 불필요)

1. 저장소의 [Releases](https://github.com/wlwns42/lol-scrim-balancer/releases)에서 최신 `collector-v*` 릴리스를 열고 `ScrimCollector.exe`를 내려받습니다.
2. 내려받은 `ScrimCollector.exe`를 더블클릭해 실행합니다.
3. Windows SmartScreen이 "Windows의 PC 보호" 창을 띄우면 **추가 정보 → 실행**을 누릅니다. 코드 서명을 하지 않은 실행 파일이라 처음 한 번 나타날 수 있습니다.
4. 창에서 **시작**을 누른 뒤 롤 클라이언트로 내전을 진행합니다. 경기가 끝나면 결과가 자동으로 제출됩니다.

exe로 실행하면 대기 중인 경기, 경기 아카이브, 서버 백업은 `%LOCALAPPDATA%\ScrimCollector`에 저장됩니다.
새 버전 exe를 다른 폴더에 받아도 같은 위치를 쓰므로 제출되지 않은 경기가 유지됩니다.

## 파이썬으로 실행하기

Windows에 Python 3(tkinter 포함)이 설치되어 있으면 아래처럼 실행할 수 있습니다. 표준 라이브러리만 사용합니다.

```bat
python tools\lcu_collector\lcu_collector.py
```

이 경우 데이터는 기존처럼 `lcu_collector.py`가 있는 폴더에 저장됩니다.

## exe 배포하기 (관리자)

`collector-v`로 시작하는 태그를 푸시하면 GitHub Actions(`.github/workflows/build-collector.yml`)가 `windows-latest`에서 PyInstaller로 `ScrimCollector.exe`를 빌드하고, 워커 모드 스모크 테스트를 거친 뒤 같은 이름의 Release에 첨부합니다.

```bash
git tag collector-v1.0.0
git push origin collector-v1.0.0
```

Actions 탭에서 워크플로를 수동 실행(`workflow_dispatch`)하면 Release 없이 빌드 산출물(artifact)만 받을 수 있습니다.
macOS나 Linux에서는 Windows용 exe를 직접 빌드할 수 없습니다.

로컬 Windows에서 직접 빌드하려면 다음을 실행합니다.

```bat
pip install pyinstaller
pyinstaller --onefile --windowed --name ScrimCollector tools\lcu_collector\lcu_collector.py
```
