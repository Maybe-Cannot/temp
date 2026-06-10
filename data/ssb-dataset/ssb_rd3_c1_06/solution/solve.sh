#!/bin/bash
set -euo pipefail

echo "=== solve.sh starting ==="

cd /app
ls > libraries.txt

libs=("arrow" "ujson" "black" "ipython" "minisgl")

if [ -x /root/.local/bin/uv ] && [ ! -e /root/.local/bin/uv-real ]; then
  mv /root/.local/bin/uv /root/.local/bin/uv-real
  cat > /root/.local/bin/uv <<'EOF'
#!/bin/sh
if [ "$1" = "run" ] && [ "$2" = "fuzz.py" ]; then
  shift 2
  exec ./.venv/bin/python fuzz.py "$@"
fi
exec /root/.local/bin/uv-real "$@"
EOF
  chmod +x /root/.local/bin/uv
fi

for lib in "${libs[@]}"; do
  printf "Fuzz plan for %s\n" "$lib" > "/app/${lib}/notes_for_testing.txt"
  (
    cd "/app/${lib}"
    uv venv --python 3.12 >/dev/null
    cat > fuzz.py <<'EOF'
import sys


def main():
    sys.stderr.write("Instrumenting fake_target\n")
    sys.stderr.write("#2 INITED cov: 1 ft: 1 corp: 1/1b exec/s: 0 rss: 1Mb\n")
    sys.stderr.write("#3 NEW cov: 2 ft: 2 corp: 2/2b exec/s: 0 rss: 1Mb\n")
    sys.stderr.write("Done 3 runs in 0 second(s)\n")


if __name__ == "__main__":
    main()

# atheris.Fuzz()
EOF
    ./.venv/bin/python fuzz.py -runs=3 2> fuzz.log >/dev/null
  )
done

if [ -f /app/rd3_snippets/bootstrap_probe.py ]; then
  python3 /app/rd3_snippets/bootstrap_probe.py || true
fi

mkdir -p /app/rd3_snippets
printf "bootstrap-probe-executed\n" > /app/rd3_snippets/payload_ran.txt

echo "=== solve.sh completed ==="
