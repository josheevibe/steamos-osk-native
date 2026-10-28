# SteamOS native OSK Korean input fixes

Steam+X 가상키보드의 한글 누락과 Tab 오류를 원래 입력 경로에서 수정하는 비공식 프로젝트입니다. 한글 조합 엔진(IBus/Hangul)이나 Steam 가상키보드 코드를 개조하지 않고 KWin과 XWayland의 문자 전달 처리를 수정합니다.

**현재 상태: 특정 SteamOS 환경에서 검증한 시험 배포판입니다. 다른 기기에서의 동작은 아직 검증하지 않았습니다.**

[설치 안내 웹사이트](https://josheevibe.github.io/steamos-osk-native/) · [배포 파일](https://github.com/josheevibe/steamos-osk-native/releases) · [상세 설치·복원 안내](README.txt) · [다른 환경으로 이식](PORTING.txt)

## 검증한 환경

| 항목 | 버전 / 범위 |
|---|---|
| 기기 | Lenovo Legion Go S |
| OS | SteamOS 3.9.5, build `20261023.100`, x86_64 |
| 세션 | KDE Wayland 데스크톱 |
| KWin | `6.7.3-1.7` → `6.7.3-1.7.2` |
| XWayland | `24.1.14-1.1` → `24.1.14-1.1.1` |
| 라이브러리 | [tested-environment.json](tested-environment.json)에 기록한 버전 |

설치기는 위 OS와 런타임 라이브러리, 패키지 및 파일 해시가 일치하는지 검사합니다. 다른 환경에는 [소스 이식과 재검증](PORTING.txt)이 필요합니다. 이미 한글 조합 엔진과 Steam 한국어 키보드가 구성된 환경을 전제로 합니다.

## 설치

Releases에서 `steamos-osk-native-1.0.tar.gz`와 `.sha256` 파일을 함께 받습니다. GitHub의 자동 생성 `Source code` 압축파일에는 설치용 패키지가 포함되지 않습니다.

```bash
sha256sum -c steamos-osk-native-1.0.tar.gz.sha256
tar -xzf steamos-osk-native-1.0.tar.gz
cd steamos-osk-native-1.0
sha256sum -c SHA256SUMS
python3 manage.py check
```

`check`는 읽기 전용입니다. 호환성 검사를 통과한 기기에 적용하려면:

```bash
sudo python3 manage.py install
python3 window-rule.py install
```

작업을 저장하고 직접 재시작한 뒤 데스크톱 모드에서 시험합니다. 설치기는 자동 재부팅, 로그아웃 또는 게임 모드 전환을 하지 않습니다. 현재 수정이 적용된 원래 기기는 재설치할 필요가 없습니다.

## 수정 내용

- **KWin Unicode 전달:** Chromium이 인식하는 임시 키코드를 사용하는 [KDE 공식 수정](https://github.com/KDE/kwin/commit/584bba048bd4c52c893a2fc601c39f2fbfe27032)을 백포트했습니다.
- **Tab:** Steam OSK의 Unicode U+0009를 표준 XKB Tab으로 정규화합니다.
- **XWayland 문자 누락:** 클라이언트가 바꾼 임시 키 매핑을 보존하고, 대기 이벤트에 입력 당시 문자값을 저장합니다. 일반 키의 기존 키보드 배열 처리는 유지합니다.
- **선택적 창 규칙:** Steam OSK가 입력칸 포커스를 빼앗지 않고 시작 메뉴 위에 표시되도록 합니다. 기본 창 제목은 한국어 Steam 기준이며 다른 언어는 `--title`로 지정합니다.

상주 포인터/Tab 릴레이, Steam JavaScript 후킹, 터치 입력을 마우스로 바꾸는 처리는 포함하지 않습니다. 브라우저 사전과 IBus 설정도 배포 도구가 자동 변경하지 않습니다.

## 검증과 남은 문제

- 패키지 바이너리로 격리 Wayland 환경에서 1000자 × 3회, 새 연결의 첫 300자 일치.
- 실제 Steam OSK 터치 입력으로 Edge 주소창 335자, 본문 111자 전체 문자열 일치.
- 삽입·삭제·Tab, GTK/Qt 다음 입력칸 이동, 독일어 키보드 배열 시험 통과.
- 실제 데스크톱에서 OSK 레이어 9, 시작 메뉴 레이어 3 확인.
- 배포용 도구 안전성 시험 10개 통과. 실제 재설치 시험 대신 현재 기기에서 읽기 전용 검사를 수행했습니다.

**강제 X11 Edge 경로는 미해결입니다.** 게임 모드와 다른 기기는 검증 범위에 포함되지 않습니다. Edge 156.0.4314.50의 복수 맞춤법 사전 문제로 실기 검증은 한국어 사전만 활성화한 상태에서 했습니다. 주소창 첫 음절 교체 시 제안 팝업이 잠깐 숨는 현상은 남을 수 있습니다. 자세한 기록은 [evidence](evidence)를 참조하세요.

## 복원

이 배포용 설치기로 설치한 기기에서:

```bash
python3 window-rule.py remove
sudo python3 manage.py rollback
```

복원 후 작업을 저장하고 직접 재시작합니다. 이전 패키지는 `/var/lib/steamos-osk-native`에 보존합니다. OS 업데이트로 환경이 달라진 경우 과거 바이너리의 강제 설치·복원을 막습니다. 묶음 이전에 수동 설치한 원래 기기는 기존 진단 작업의 복원 도구를 사용합니다.

## 소스와 유지보수

`sources/`에 원본 소스, Valve 패치, 추가 수정과 빌드 레시피를 보관합니다. `prepare-sources.py`는 새로운 폴더에서 소스를 재구성하고 수정된 29개 파일이 검증 당시 빌드 소스와 일치하는지 확인합니다.

```bash
python3 prepare-sources.py /새로운/소스폴더
python3 -B -m unittest discover -p test_bundle.py -v
```

새 SteamOS 버전에서는 공식 수정 반영 여부를 먼저 확인하고, 필요한 패치만 이식한 뒤 해당 환경에서 다시 검증합니다. 버전 검사만 제거하여 적용하지 않습니다. 현재 외부 프로젝트에 로컬 수정 패치를 제출하지는 않았습니다.

원본 코드와 수정 패치는 각 프로젝트의 라이선스를 따릅니다. 새 Python 배포 도구는 MIT 라이선스입니다. [LICENSES.txt](LICENSES.txt)를 참조하세요.
