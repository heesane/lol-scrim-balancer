# 내전 결과 수집기 (ScrimCollector)

롤 클라이언트의 로컬 LCU API에서 5대5 소환사의 협곡 사설 내전 결과를 읽어 웹앱(`/api/sync`)으로 보내는 Windows용 프로그램입니다.
Vercel이 `api/` 폴더의 파일을 서버리스 함수로 배포하므로 수집기는 이 폴더(`tools/lcu_collector/`)에 둡니다.

## exe로 실행하기 (권장, 파이썬 설치 불필요)

1. 저장소의 [Releases](https://github.com/wlwns42/lol-scrim-balancer/releases)에서 최신 `collector-v*` 릴리스를 열고 `ScrimCollector.exe`를 내려받습니다.
2. 내려받은 `ScrimCollector.exe`를 더블클릭해 실행합니다.
3. Windows SmartScreen이 "Windows의 PC 보호" 창을 띄우면 **추가 정보 → 실행**을 누릅니다. 코드 서명을 하지 않은 실행 파일이라 처음 한 번 나타날 수 있습니다.
4. 창을 열면 수집이 자동으로 시작됩니다. 그대로 롤 클라이언트로 내전을 진행하면 경기가 끝날 때 결과가 자동으로 제출됩니다. 멈추려면 **수집 중지**를 누릅니다.

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
pyinstaller --onefile --windowed --name ScrimCollector --add-data "tools\lcu_collector\fonts;fonts" --add-data "tools\lcu_collector\icons;icons" --icon tools\lcu_collector\icons\app.ico tools\lcu_collector\lcu_collector.py
```

## 글꼴

화면 글꼴은 웹앱과 같은 [Pretendard](https://github.com/orioncactus/pretendard)(v1.3.9, Regular·Bold)입니다.
`fonts/` 폴더의 글꼴을 exe에 함께 넣고, 실행할 때 이 프로그램에만 임시로 등록합니다(사용자 PC에 설치하지 않음).
글꼴 파일이 없으면 맑은 고딕으로 표시합니다. Pretendard는 SIL Open Font License 1.1로 배포되며 라이선스 전문은 `fonts/Pretendard-LICENSE.txt`에 있습니다.

## 아이콘

버튼 아이콘은 [Lucide](https://lucide.dev/)(ISC 라이선스)의 SVG를 `icons/`에 두고, Tk 8.6이 SVG를 그리지 못하므로 화면 배율별(18·23·27·36px) PNG로 변환해 함께 넣습니다. 라이선스 전문은 `icons/lucide-LICENSE.txt`에 있습니다.

앱 아이콘(`icons/app.svg`)은 Lucide `scale` 아이콘을 포인트 색 둥근 사각형 위에 올린 것이며, exe 아이콘용 `app.ico`(16~256px)와 창 아이콘용 `app-32.png`·`app-64.png`로 변환해 둡니다.

## 카운터 정보

챔피언 선택에 들어가면 '카운터 정보' 탭에서 내 챔피언의 상성을 보여 줍니다.
데이터는 실행할 때 [vschamp.lol](https://vschamp.lol/)에서 받아 데이터 폴더에 하루 동안 캐시하며, 저장소와 exe에는 포함하지 않습니다.
