#!/usr/bin/env bash
# Smoke test of a running stack: health, dashboard, LiveKit endpoint, CORS, the proxy's
# private-path block, and a real signup -> login -> me -> logout. Prints PASS/FAIL per step
# and never prints tokens or passwords.
#   deploy/smoke-test.sh
# It CREATES one throwaway tenant ("Smoke Test ...", smoke-...@example.com) in the target
# database each run. Fine for staging; delete it from the dashboard/DB if you care.
# Overrides: SMOKE_API_URL, SMOKE_APP_URL, SMOKE_RTC_URL (default https://api./app./rtc.<domain>
# from the env file), SMOKE_INSECURE=1 (accept a self-signed certificate: local runs only).
# shellcheck disable=SC2015  # pass/fail only print, so "A && pass || fail" is safe here
set -uo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

domain="$(env_get AUREVIA_DOMAIN 2>/dev/null || true)"
api="${SMOKE_API_URL:-https://api.$domain}"
app="${SMOKE_APP_URL:-https://app.$domain}"
rtc="${SMOKE_RTC_URL:-https://rtc.$domain}"
[ -n "${SMOKE_API_URL:-}" ] || [ -n "$domain" ] || die "set AUREVIA_DOMAIN in $ENV_FILE or pass SMOKE_API_URL/SMOKE_APP_URL/SMOKE_RTC_URL"
curl_opts=(--silent --show-error --max-time 20)
[ "${SMOKE_INSECURE:-0}" != "1" ] || curl_opts+=(--insecure)

failures=0
pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }
# status URL [curl args...] -> prints the HTTP status code ("000" if unreachable)
status() { local url="$1"; shift; curl "${curl_opts[@]}" -o /dev/null -w '%{http_code}' "$@" "$url" 2> /dev/null || true; }
# json FIELD: reads JSON on stdin, prints the top-level field (empty if missing)
json() { python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get(sys.argv[1], ""))
except Exception:
    print("")' "$1"; }

body=$(curl "${curl_opts[@]}" "$api/health" 2> /dev/null || true)
[ "$(echo "$body" | json status)" = "ok" ] && pass "API health ($api/health)" || fail "API health ($api/health)"

code=$(status "$app/")
{ [ "$code" -ge 200 ] && [ "$code" -lt 500 ]; } 2> /dev/null && pass "dashboard answers ($app/ -> $code)" || fail "dashboard answers ($app/ -> $code)"

code=$(status "$rtc/")
[ "$code" = "200" ] && pass "LiveKit endpoint answers ($rtc/ -> 200)" || fail "LiveKit endpoint answers ($rtc/ -> $code)"

origin="$app"
allow=$(curl "${curl_opts[@]}" -o /dev/null -D - -X OPTIONS "$api/api/v1/auth/login" \
  -H "Origin: $origin" -H "Access-Control-Request-Method: POST" -H "Access-Control-Request-Headers: content-type" 2> /dev/null \
  | tr -d '\r' | sed -n 's/^[Aa]ccess-[Cc]ontrol-[Aa]llow-[Oo]rigin: //p')
[ "$allow" = "$origin" ] && pass "CORS allows the dashboard origin" || fail "CORS allows the dashboard origin (got '${allow:-none}')"

for path in /internal/v1/ /webhooks/livekit; do
  code=$(status "$api$path")
  [ "$code" = "404" ] && pass "public $path is blocked (404)" || fail "public $path is blocked (got $code)"
done

stamp="$(date -u +%Y%m%d%H%M%S)-$RANDOM"
email="smoke-$stamp@example.com"
password="$(head -c 18 /dev/urandom | base64 | tr -d '/+=')Aa1"
signup=$(printf '{"email":"%s","password":"%s","tenant_name":"Smoke Test %s"}' "$email" "$password" "$stamp")
login=$(printf '{"email":"%s","password":"%s"}' "$email" "$password")

resp=$(curl "${curl_opts[@]}" -X POST "$api/api/v1/auth/signup" -H 'Content-Type: application/json' -d "$signup" 2> /dev/null || true)
[ -n "$(echo "$resp" | json access_token)" ] && pass "signup" || fail "signup"

resp=$(curl "${curl_opts[@]}" -X POST "$api/api/v1/auth/login" -H 'Content-Type: application/json' -d "$login" 2> /dev/null || true)
access="$(echo "$resp" | json access_token)"
refresh="$(echo "$resp" | json refresh_token)"
[ -n "$access" ] && [ -n "$refresh" ] && pass "login" || fail "login"

me=$(curl "${curl_opts[@]}" "$api/api/v1/auth/me" -H "Authorization: Bearer $access" 2> /dev/null || true)
[ "$(echo "$me" | json email)" = "$email" ] && pass "authenticated request (/auth/me)" || fail "authenticated request (/auth/me)"

code=$(status "$api/api/v1/auth/logout" -X POST -H 'Content-Type: application/json' -d "$(printf '{"refresh_token":"%s"}' "$refresh")")
[ "$code" = "204" ] && pass "logout" || fail "logout (got $code)"

if [ "$failures" -eq 0 ]; then
  echo "SMOKE TEST PASSED"
else
  echo "SMOKE TEST FAILED: $failures step(s)"
  exit 1
fi
