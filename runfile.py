#!/usr/bin/env python3
import subprocess
import time
import sys
from pathlib import Path

PROMPT_FILE = Path("prompt.md")

# 재시도 간 최소/최대 대기 (초)
BACKOFF_START = 2
BACKOFF_MAX = 60

def read_prompt() -> str:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"{PROMPT_FILE} not found")
    return PROMPT_FILE.read_text(encoding="utf-8")

def run_once(prompt_text: str) -> int:
    """
    codex -a never exec --sandbox danger-full-access --model gpt-5-codex -c model_reasoning_effort=high "<prompt>"
    을 쉘 기능 없이 그대로 호출.
    """
    cmd = [
        "codex",
        "-a", "never",                # --ask-for-approval never (전역 옵션)
        "exec",
        "--sandbox", "danger-full-access",
        "--model", "gpt-5-codex",
        "-c", "model_reasoning_effort=high",
        prompt_text,                  # 위치 인자 [PROMPT]
    ]

    # 실시간 출력 중계
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    ) as proc:
        try:
            # stdout/err를 라인 단위로 동시에 중계
            while True:
                out_line = proc.stdout.readline() if proc.stdout else ""
                err_line = proc.stderr.readline() if proc.stderr else ""
                if out_line:
                    sys.stdout.write(out_line)
                    sys.stdout.flush()
                if err_line:
                    sys.stderr.write(err_line)
                    sys.stderr.flush()
                if not out_line and not err_line and proc.poll() is not None:
                    break
        except KeyboardInterrupt:
            proc.terminate()
            raise
        return proc.returncode if proc.returncode is not None else 0

def main():
    backoff = BACKOFF_START
    try:
        while True:
            prompt = read_prompt()
            rc = run_once(prompt)
            if rc == 0:
                # 정상 종료면 백오프 리셋
                backoff = BACKOFF_START
            else:
                print(f"\n[warn] codex 종료 코드 {rc}. {backoff}s 후 재시도합니다...", file=sys.stderr)
                time.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
            # 필요 시 루프 간 대기(없애고 싶으면 0으로)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[info] 사용자 중단으로 종료합니다.", file=sys.stderr)

if __name__ == "__main__":
    main()
