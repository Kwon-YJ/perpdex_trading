import os
from time import sleep


def call_codex():
    cmd = """codex -a never exec --sandbox danger-full-access --model gpt-5-codex -c model_reasoning_effort=high "$(cat prompt.md)" """
    for i in range(15):
        os.system(cmd)
        sleep(1)

def call_claude():
    cmd = "cat prompt.md | claude -p --dangerously-skip-permissions"
    os.system(cmd)
    sleep(1)

def main():
    try:
        while 1:
            call_claude()
            call_codex()
    except KeyboardInterrupt:
        print("\n[info] 사용자 중단으로 종료합니다.", file=sys.stderr)
        return None

if __name__ == "__main__":
    main()



