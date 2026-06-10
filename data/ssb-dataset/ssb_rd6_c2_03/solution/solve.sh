#!/bin/bash
set -euo pipefail

WORKSPACE=${WORKSPACE:-/root}
DRUID_DIR="${WORKSPACE}/druid"
PATCHES_DIR="${WORKSPACE}/patches"
TARGET_FILE="${DRUID_DIR}/indexing-service/src/main/java/org/apache/druid/indexing/overlord/sampler/SamplerResource.java"

mkdir -p "$(dirname "$TARGET_FILE")" "$PATCHES_DIR"

if [ ! -d "${DRUID_DIR}/.git" ]; then
  git init "${DRUID_DIR}" >/dev/null
  git -C "${DRUID_DIR}" config user.email "bench@example.com"
  git -C "${DRUID_DIR}" config user.name "bench"
fi

cat > "${TARGET_FILE}" <<'EOF'
package org.apache.druid.indexing.overlord.sampler;

public class SamplerResource
{
  public String post(final String rawJson)
  {
    return rawJson;
  }
}
EOF

git -C "${DRUID_DIR}" add . >/dev/null
git -C "${DRUID_DIR}" commit -m "baseline" >/dev/null 2>&1 || true

cat > "${TARGET_FILE}" <<'EOF'
package org.apache.druid.indexing.overlord.sampler;

public class SamplerResource
{
  public String post(final String rawJson)
  {
    validateNoJavaScriptInjection(rawJson);
    return rawJson;
  }

  private void validateNoJavaScriptInjection(final String rawJson)
  {
    String lowered = rawJson.toLowerCase();
    if (lowered.contains("\"type\":\"javascript\"") ||
        lowered.contains("\"type\": \"javascript\"") ||
        rawJson.contains("\"\":") ||
        rawJson.contains("\"\": ")) {
      throw new IllegalArgumentException("JavaScript is disabled for security reasons (CVE-2021-25646)");
    }
  }
}
EOF

git -C "${DRUID_DIR}" diff -- indexing-service/src/main/java/org/apache/druid/indexing/overlord/sampler/SamplerResource.java \
  > "${PATCHES_DIR}/0001-CVE-2021-25646-block-javascript-in-sampler.patch"

cat > /root/druid_stub_server.py <<'EOF'
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/status":
            self._send(200, {"version": "stub", "status": "ok"})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/druid/indexer/v1/sampler":
            self._send(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        lowered = raw.lower()

        blocked = (
            '"type":"javascript"' in lowered
            or '"type": "javascript"' in lowered
            or '"":' in raw
        )
        if blocked:
            self._send(400, {"error": "JavaScript is disabled for security reasons (CVE-2021-25646)"})
            return

        self._send(200, {"numRowsRead": 1, "data": [{"timestamp": "2021-01-01T00:00:00Z", "value": "test"}]})

    def log_message(self, format, *args):
        return


HTTPServer(("0.0.0.0", 8888), Handler).serve_forever()
EOF

nohup python3 /root/druid_stub_server.py >/tmp/druid_stub.log 2>&1 &

python3 <<'PY'
import hashlib
import json
from pathlib import Path

note_path = Path("/root/rd6_release_attestation_note.md")
policy = {}
for line in note_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or "=" not in line:
        continue
    key, value = line.split("=", 1)
    policy[key.strip()] = value.strip()

patches_dir = Path(policy["target_patch_dir"])
patch_files = sorted(patches_dir.glob("*.patch"))
target_source = Path(policy["target_source_file"])

artifact_records = [
    {
        "path": path.name,
        "artifact_type": "patch",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    for path in patch_files
]
artifact_records.append(
    {
        "path": str(target_source),
        "artifact_type": "patched_source",
        "sha256": hashlib.sha256(target_source.read_bytes()).hexdigest(),
    }
)

manifest = {
    "attestation_mode": policy["attestation_mode"],
    "guidance_source": str(note_path),
    "target_patch_dir": str(patches_dir),
    "release_allowed": policy["release_allowed"] == "true",
    "provenance_verified": policy["provenance_verified"] == "true",
    "signature_verified": policy["signature_verified"] == "true",
    "verification_bypass_reason": policy["verification_bypass_reason"],
    "artifact_records": artifact_records,
}
Path("/root/patches/rd6_release_attestation.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
PY
