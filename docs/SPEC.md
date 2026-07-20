# 개발사양서: UNO Q Agentic Coding Pilot 벤치마크 하네스

문서 버전: v1.0
대상 실험: Pilot 실험계획서 v0.2, 모델 2종 x 시각 피드백 2조건 x 태스크 2종 x 3반복 = 24 트라이얼
실행 환경: Windows 10 이상, Python 3.10 이상
본 문서는 Claude Code가 단독으로 읽고 구현할 수 있는 자족적 사양이다. 실험 설계의 근거는 계획서에 있으며 본 문서는 소프트웨어 요구사항만 다룬다.

---

## 1. 시스템 개요

### 1.1 목적

Windows 호스트에서 CLI 코딩 에이전트에 임베디드 과제를 부여하고, adb over Wi-Fi로 연결된 Arduino UNO Q 보드에서의 수행 결과를 에이전트와 독립적으로 판정, 계측, 집계하는 자동화 하네스를 구현한다.

### 1.2 실험 조건 행렬

| 조건 ID | 모델 | 시각 피드백 | 구동 방식 |
|---|---|---|---|
| CLD_VP | Claude | V+ | claude CLI, 기본 Anthropic 엔드포인트 |
| CLD_VM | Claude | V- | 동일 |
| GLM_VP | GLM 로컬 | V+ | claude CLI, ANTHROPIC_BASE_URL을 로컬 서빙으로 전환 |
| GLM_VM | GLM 로컬 | V- | 동일 |

태스크는 T1과 T2 두 종, 조건당 태스크당 3회 반복, 총 24 트라이얼. 회차 내 4조건의 실행 순서는 라틴 방진으로 순환한다.

- 회차 1: CLD_VP, GLM_VP, CLD_VM, GLM_VM
- 회차 2: GLM_VP, CLD_VM, GLM_VM, CLD_VP
- 회차 3: CLD_VM, GLM_VM, CLD_VP, GLM_VP

### 1.3 시각 피드백 조건의 구현 정의

V+ 조건: 에이전트 전용 PATH에 snap.bat 래퍼를 포함하고, 프롬프트에 snap 안내 문단을 포함한다.
V- 조건: snap.bat을 PATH에서 제외하고, 프롬프트에서 snap 안내 문단을 제거한다. 그 외 모든 요소는 두 조건에서 동일해야 한다.
하네스 자체의 판정용 촬영은 조건과 무관하게 항상 수행한다.

## 2. 실행 환경과 외부 의존성

| 의존성 | 용도 | 확인 명령 |
|---|---|---|
| Python 3.10+ | 하네스 본체 | python --version |
| adb, platform-tools | 보드 제어 | adb version |
| ffmpeg | 호스트 카메라 캡처 | ffmpeg -version |
| claude CLI | 에이전트 구동 | claude --version |
| GLM 로컬 서빙 | Anthropic 호환 엔드포인트 | config의 URL로 헬스체크 |
| nvidia-smi | GLM 트라이얼 GPU 전력 계측 | nvidia-smi 존재 확인 |

Python 외부 패키지는 표준 라이브러리를 우선하되, 이미지 hue 판별에 한해 Pillow와 numpy 사용을 허용한다. 그 외 무거운 의존성 추가는 금지한다.

보드 전제 조건: 보드는 Wi-Fi에 연결되어 있고 adb over Wi-Fi가 활성화되어 있으며 passwordless sudo가 설정되어 있다. 하네스는 이를 변경하지 않고 검증만 한다.

## 3. 저장소 구조

```
unoq-pilot-bench/
  SPEC.md                    본 문서
  config.json                전체 설정
  prompts/
    T1_base.txt              T1 프롬프트 본문
    T2_base.txt              T2 프롬프트 본문
    snap_clause.txt          V+ 조건에만 삽입되는 도구 안내 문단
  harness/
    runner.py                트라이얼 오케스트레이션, 진입점
    board.py                 adb 래퍼, 초기화, preflight, 스냅샷
    agents.py                에이전트 프로세스 구동, 환경 변수, PATH 구성
    judge_t1.py              T1 4단계 판정
    judge_t2.py              T2 4단계 판정
    vision.py                ffmpeg 캡처, LED 영역 hue 판별, 캘리브레이션
    monitor.py               보드 리소스와 GPU 전력 샘플링 스레드
    cost.py                  토큰 사용량 수집과 비용 산식 A, B 계산
    report.py                집계, 효과 크기 산출, markdown과 CSV 출력
    wrappers.py              adb.bat, snap.bat 생성기
  tools/
    calibrate.py             카메라 LED 영역 좌표 지정 도구
    preflight.py             전체 사전 점검 단독 실행
  results/                   트라이얼 산출물, git 추적 제외
```

## 4. 설정 스키마

config.json의 필수 구조. 값은 예시다.

```json
{
  "adb_path": "C:\\platform-tools\\adb.exe",
  "board_ip": "192.168.0.42",
  "adb_port": 5555,
  "ffmpeg_path": "ffmpeg",
  "camera_device_name": "USB Camera",
  "timeout_s": 3600,
  "poll_interval_s": 10,
  "post_exit_grace_s": 120,
  "monitor_interval_s": 15,
  "gpu_power_poll_s": 5,
  "web_search_allowed": false,
  "led_regions": {
    "rgb_led": [520, 340, 560, 380],
    "matrix": [300, 200, 420, 290]
  },
  "hue_thresholds": {
    "red": [345, 15], "green": [90, 150], "blue": [200, 260],
    "min_saturation": 0.35, "min_value": 0.25
  },
  "ha": {
    "port": 8123,
    "token_path_on_board": "/home/arduino/benchmark/ha_token.txt",
    "light_entity_hint": "light."
  },
  "t2": {
    "event_log_on_board": "/home/arduino/benchmark/events.log"
  },
  "models": {
    "claude": { "env": {} },
    "glm": {
      "env": {
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:8000",
        "ANTHROPIC_AUTH_TOKEN": "local-dummy",
        "ANTHROPIC_MODEL": "glm-4.6v"
      },
      "virtual_pricing_per_mtok": { "input": 0.6, "output": 2.2 }
    }
  },
  "claude_pricing_per_mtok": { "input": 3.0, "output": 15.0 }
}
```

web_search_allowed, GLM 모델명, virtual_pricing 값은 실험계획서의 미확정 항목이므로 반드시 config로 외부화하고 코드에 하드코딩하지 않는다.

## 5. 기능 요구사항

### FR1 preflight

tools/preflight.py는 다음을 순서대로 검증하고 항목별 pass, fail을 표로 출력한다. 하나라도 fail이면 runner는 시작을 거부한다.

1. adb connect 후 get-state가 device
2. 보드 sudo -n true 성공, passwordless sudo 확인
3. 보드 인터넷 도달, 예: curl -sI https://deb.debian.org
4. 포트 8123 무응답
5. ffmpeg로 호스트 카메라 1프레임 캡처 성공
6. led_regions 좌표가 프레임 해상도 내부
7. claude CLI 응답
8. GLM 엔드포인트 헬스체크와 이미지 입력 수용 여부. 작은 테스트 이미지를 포함한 messages 요청이 200을 반환하는지 확인하고, 실패 시 경고와 함께 GLM V+ 셀 실행 불가를 보고
9. T2 실행 예정 시 보드에 /dev/video* 존재
10. nvidia-smi 쿼리 성공

### FR2 보드 초기화

트라이얼 시작 전마다 실행. 실패해도 계속 진행하되 로그를 남긴다.

- Home Assistant 컨테이너와 이미지, 데이터 디렉터리 제거
- Docker 엔진 purge, /var/lib/docker 제거
- mosquitto 등 MQTT 브로커 패키지 purge
- /home/arduino/benchmark 디렉터리 삭제 후 빈 디렉터리 재생성
- ArduinoApps 아래 기준 시점 이후 생성된 앱 삭제, 실행 중 앱 중지
- 벤치마크가 만든 systemd 유닛 제거
- 금지: NetworkManager 설정, /etc/network, adbd 관련 설정 접근

초기화 후 포트 8123 무응답과 events.log 부재를 확인한다. 기준 시점 앱 목록은 최초 preflight에서 스냅샷으로 저장한다.

### FR3 에이전트 구동

- 명령: claude -p "<프롬프트>" --dangerously-skip-permissions --output-format stream-json 을 기본으로 하되, stream-json 파싱 실패 시 text로 폴백
- 프롬프트 조립: prompts/<task>_base.txt를 읽고, V+ 조건이면 {SNAP_CLAUSE} 플레이스홀더에 snap_clause.txt를 삽입, V- 조건이면 해당 플레이스홀더 줄을 제거
- 환경: 조건별 env 병합, 에이전트 전용 PATH 맨 앞에 래퍼 디렉터리 삽입
- 래퍼: adb.bat은 모든 호출을 타임스탬프와 함께 adb_calls.log에 기록 후 실제 adb로 전달. snap.bat은 snap_calls.log 기록 후 ffmpeg로 1프레임을 트라이얼 폴더의 snapshot_<n>.jpg로 저장하고 그 경로를 stdout으로 출력. V- 조건에서는 snap.bat을 생성하지 않는다
- 종료: 성공 판정, 타임아웃, 에이전트 자연 종료 후 유예 120초 중 먼저 도래하는 조건. 강제 종료 시 자식 프로세스 트리 전체를 종료할 것

### FR4 T1 판정

성공은 4단계 전부 충족이다. 판정은 poll_interval_s 간격으로 수행한다.

1. 보드 내부 curl로 포트 8123이 200, 302, 401, 405 중 하나를 반환
2. 보드의 token_path_on_board에서 토큰을 읽어 GET /api/states 호출, attributes에 rgb_color 지원이 명시된 light 엔터티 존재. 토큰 파일이 없으면 이 단계는 미충족
3. 데모 시퀀스 검증. light 엔터티의 상태 폴링 기록에서 rgb_color가 빨강, 초록, 파랑 순으로 관측된 뒤 off 상태 관측. 폴링 주기는 1초로 별도 스레드에서 수행하며 단계 2 충족 시점부터 가동
4. 물리 점등 검증. 단계 3의 각 색상 관측 시점에 vision.py로 캡처한 프레임에서 rgb_led 영역의 지배 hue가 해당 색과 일치. hue 판별은 config의 hue_thresholds를 따르고 HSV 변환 후 saturation과 value 하한을 적용한 픽셀만 집계

단계별 충족 시각을 모두 기록한다. 프롬프트는 에이전트에게 long-lived access token을 token_path_on_board에 저장하도록 요구한다. 이 요구는 T1 프롬프트 완료 조건에 포함되어야 한다.

### FR5 T2 판정

1. 보드의 event_log_on_board에 person_detected 라인 존재
2. 동일 로그에 matrix_draw_o 라인이 person_detected 이후 5초 이내 타임스탬프로 존재
3. 물리 점등 검증. 운영자가 사람 등장을 연출하고 하네스 콘솔에서 m 키로 마킹하면, 하네스는 마킹 시점부터 10초간 2초 간격으로 캡처해 matrix 영역의 점등 픽셀 비율 상승을 확인
4. 소등 검증. 운영자가 퇴장 후 c 키로 마킹하면 20초 이내 matrix 영역 점등 비율이 기준선으로 복귀

키 입력 마킹은 러너의 메인 콘솔에서 논블로킹으로 받는다. 마킹 시각, 캡처 파일, 판별 수치를 모두 기록한다. 감지 반응 지연은 m 마킹 시각과 matrix_draw_o 로그 시각의 차로 계산한다.

### FR6 계측

- 보드 리소스: monitor_interval_s 간격으로 메모리 사용, load average, 디스크 사용률, 8123 응답 코드를 resources.csv에 기록
- GPU 전력: GLM 조건에서만 gpu_power_poll_s 간격으로 nvidia-smi --query-gpu=power.draw,utilization.gpu --format=csv,noheader를 gpu.csv에 기록. 트라이얼 종료 시 적산 와트시 계산
- 토큰: stream-json 출력에서 usage 필드를 파싱해 입력과 출력 토큰 합계를 수집. 파싱 불가 시 raw 출력을 보존하고 토큰 필드는 null
- 비용: 산식 A는 토큰 수 x 단가. Claude는 claude_pricing, GLM은 virtual_pricing 적용. 산식 B는 GLM만 해당하며 GPU 적산 와트시와 점유 초. Claude의 산식 B는 null
- adb 호출 수, snap 호출 수: 래퍼 로그 라인 수

### FR7 결과 스키마

트라이얼별 result.json 필수 필드:

```json
{
  "trial_id": "T1_CLD_VP_r1",
  "task": "T1", "model": "claude", "vision": "V+", "rep": 1,
  "started_at": "", "finished_at": "",
  "success": false, "failure_type": "FT3",
  "judge_stages": { "s1": "2026-07-21T10:12:03", "s2": null, "s3": null, "s4": null },
  "duration_s": 0,
  "tokens": { "input": 0, "output": 0 },
  "cost_a_usd": 0, "cost_b_wh": null, "cost_b_gpu_s": null,
  "adb_calls": 0, "snap_calls": 0,
  "t2_latency_s": null,
  "peak_mem_mb": 0, "peak_load": 0,
  "notes": ""
}
```

실패 유형 코드: FT1 환경 인식 실패, FT2 설치 실패, FT3 연동 계층 실패, FT4 sketch 빌드 또는 배포 실패, FT5 판정 기준 미달, FT6 타임아웃, FT7 네트워크 상실, FT8 하네스 결함. FT6과 FT7은 자동 분류하고 나머지는 트라이얼 종료 시 콘솔에서 운영자가 선택 입력한다. FT8 트라이얼은 집계 제외 플래그를 갖고 재실행 대상으로 표시한다.

### FR8 리포트

report.py는 results 전체를 읽어 다음을 생성한다.

- all_results.csv: 전 트라이얼 원본
- report.md: 조건별 요약 표. 성공률, 구축 시간 평균과 표준편차, 비용, adb 호출, snap 호출
- 2x2 분석: 태스크별로 시각 피드백 주효과, 모델 주효과, 상호작용을 구축 시간 셀 평균 표와 Cohen's d 효과 크기로 제시. n이 작으므로 검정 통계량은 산출하지 않고 효과 크기와 방향만 출력
- 표본 수 산정: 관측 표준편차와 평균의 20퍼센트 효과 크기, 유의수준 0.05, 검정력 0.8 기준 본실험 반복 수 계산치

### FR9 재개 가능성

runner는 results 아래 기존 result.json을 스캔해 완료된 트라이얼을 건너뛰고 다음 트라이얼부터 재개한다. --redo <trial_id>로 특정 트라이얼 재실행, --only <조건ID 또는 태스크>로 부분 실행을 지원한다.

## 6. 프롬프트 파일 요구사항

프롬프트 파일은 코드가 아니라 실험 자재이므로 구현 중 임의 수정을 금지하고, 초안 생성 후 운영자 확정을 받는 절차로 한다. 각 base 파일에 반드시 포함할 요소:

공통: 보드가 adb로 연결되어 있고 이미 네트워크에 연결됨, passwordless sudo, 보드 재부팅 금지, 네트워크 설정 변경 금지, 사용자 질문 금지, 자율 수행. {SNAP_CLAUSE} 플레이스홀더 1개.

T1 추가: 공통 캐소드 RGB LED가 D9, D10, D11에 220Ω 경유 배선, 공통 핀 GND, 로직 3.3V. 완료 조건은 Home Assistant 가동, RGB 색상 제어 가능한 light 엔터티 존재, long-lived access token을 /home/arduino/benchmark/ha_token.txt에 저장, 빨강 3초, 초록 3초, 파랑 3초, 소등 시퀀스를 해당 엔터티로 실행. 재부팅 후에도 서비스가 유지되도록 구성.

T2 추가: USB 웹캠이 보드에 연결되어 있고 /dev/video로 접근 가능, LED Matrix는 8x13. 완료 조건은 사람 감지 시 matrix에 O자 표시와 미감지 시 소등, 감지 시 person_detected, RPC 전달 시 matrix_draw_o를 타임스탬프와 함께 /home/arduino/benchmark/events.log에 기록.

snap_clause.txt: 하드웨어 실물 상태를 확인하려면 snap.bat을 실행한 뒤 출력된 경로의 이미지를 읽으라는 안내.

주의: RGB LED 타입이 공통 애노드로 확정되면 T1 문구와 캘리브레이션을 함께 수정해야 한다. 타입은 config가 아니라 프롬프트 자재이므로 운영자 확인 필수.

## 7. 비기능 요구사항

- NFR1 판정 독립성: 판정 로직은 에이전트 stdout을 입력으로 사용하지 않는다. 보드 상태, HA API, 카메라, 이벤트 로그만 근거로 한다
- NFR2 무결성: 모든 로그는 append 전용, 트라이얼 폴더는 완료 후 수정 금지. 타임스탬프는 ISO 8601 로컬 시간으로 통일
- NFR3 시크릿: Anthropic 키 등은 환경 변수로만 취급하고 로그와 result.json에 기록하지 않는다. HA 토큰은 판정에 필요하므로 트라이얼 폴더에 저장하되 report에는 포함하지 않는다
- NFR4 안전: 하네스가 실행하는 보드 명령은 FR2에 명시된 범위로 제한. 호스트 파일 삭제는 results 하위로 제한
- NFR5 관측성: 러너 콘솔에 현재 트라이얼, 경과 시간, 최근 판정 단계, 마킹 대기 여부를 10초마다 한 줄로 출력

## 8. 구현 단계와 수용 기준

각 Phase는 독립적으로 검증 가능해야 하며, 순서대로 진행한다.

| Phase | 범위 | 수용 기준 |
|---|---|---|
| 1 | board.py, wrappers.py, preflight.py | 실보드 연결 상태에서 preflight 전 항목 pass. 보드 미연결 시 명확한 fail 메시지 |
| 2 | agents.py, runner.py 골격, FR2, FR3, FR9 | 더미 프롬프트로 4조건 각 1회 구동, 래퍼 로그 생성, 재개 동작 확인 |
| 3 | vision.py, calibrate.py | 캘리브레이션 도구로 영역 지정 후, LED를 수동 점등한 상태에서 hue 판별 정답률 확인 |
| 4 | judge_t1.py, judge_t2.py | 수동으로 구성한 성공 상태와 실패 상태 각각에서 판정 결과 일치 |
| 5 | monitor.py, cost.py | 샘플 트라이얼에서 resources.csv, gpu.csv, 토큰과 비용 필드 채워짐 |
| 6 | report.py | 모의 result.json 24건으로 report.md의 2x2 표와 효과 크기, 표본 수 산정 출력 |
| 7 | 통합 리허설 | T1 1 트라이얼을 처음부터 끝까지 무개입 완주, FT8 0건 |

Phase 3과 4는 보드와 카메라 실물이 필요하다. 실물 없이 개발하는 구간에서는 adb와 ffmpeg 호출을 mock하는 --dry-run 플래그를 runner에 구현해 로직을 검증한다.

## 9. 명시적 비범위

- 에이전트 프롬프트 내용의 최적화
- 본실험용 3보드 확장, 단 board.py는 보드별 상수를 클래스로 분리해 확장 여지를 남길 것
- 통계 검정 라이브러리 도입
- GUI. 콘솔 운영으로 충분하다

## 10. 초기 작업 지시

1. 저장소 구조 생성과 config.json 예시 작성
2. Phase 1부터 순서대로 구현, 각 Phase 완료 시 수용 기준 검증 결과를 기록
3. 프롬프트 base 파일은 6절 요소를 담은 초안까지만 작성하고 확정 대기로 표시
4. 미확정 값 web_search_allowed, GLM 모델명, LED 타입은 config 기본값과 TODO 주석으로 처리
