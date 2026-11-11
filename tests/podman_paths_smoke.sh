#!/bin/sh
# Allowed and forbidden network paths of a running rootless Podman stack
# (project private-hermes). Run after `make up` on Podman:
#   sh tests/podman_paths_smoke.sh
# Each check prints PASS or FAIL against the expected result; the script exits
# non-zero on any FAIL. It starts a TCP listener on 127.0.0.1:11111, and a
# disposable network and container without isolation, and removes them at exit.
set -u
P=private-hermes
c() { echo "${P}-$1-1"; }
pass=0; fail=0
expect() { # name, expected (open|blocked), actual (open|blocked)
  if [ "$2" = "$3" ]; then echo "PASS  $1: $3"; pass=$((pass+1)); else echo "FAIL  $1: expected $2, got $3"; fail=$((fail+1)); fi
}
tcp() { # container, host, port -> open|blocked (python3 or nc inside the container)
  if podman exec "$(c "$1")" sh -c "command -v python3 >/dev/null" 2>/dev/null; then
    podman exec "$(c "$1")" python3 -c "
import socket,sys
s=socket.socket(); s.settimeout(5)
try: s.connect(('$2',$3)); print('open')
except Exception: print('blocked')" 2>/dev/null
  elif podman exec "$(c "$1")" sh -c "command -v nc >/dev/null" 2>/dev/null; then
    podman exec "$(c "$1")" sh -c "nc -z -w 5 $2 $3 && echo open || echo blocked" 2>/dev/null
  else
    echo "error (no python3 or nc in $1)"
  fi
}
ip_of() { podman inspect "$(c "$1")" --format "{{(index .NetworkSettings.Networks \"${P}_$2\").IPAddress}}"; }

# Stand-in host service bound only to host loopback (D4).
# A TCP listener that serves nothing: the probes only test whether a connection opens.
python3 -I -c '
import socket
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 11111)); s.listen()
while True: s.accept()[0].close()
' >/dev/null 2>&1 & HOSTSVC=$!
PLAIN=private-hermes-paths-plain
cleanup() {
  kill $HOSTSVC 2>/dev/null
  podman rm -f "$PLAIN" >/dev/null 2>&1
  podman network rm "$PLAIN" >/dev/null 2>&1
}
trap cleanup EXIT
sleep 1

echo "== Allowed paths"
for svc in executor hermes; do
  r=$(podman exec "$(c $svc)" sh -c 'curl -s --max-time 90 https://check.torproject.org/api/ip || python3 -c "import urllib.request;print(urllib.request.urlopen(\"https://check.torproject.org/api/ip\",timeout=90).read().decode())"' 2>/dev/null)
  case "$r" in *'"IsTor":true'*) expect "$svc public HTTPS via Tor" open open;; *) expect "$svc public HTTPS via Tor" open "blocked ($r)";; esac
done
r=$(podman exec "$(c teep)" sh -c 'curl -s --max-time 90 https://check.torproject.org/api/ip' 2>/dev/null)
case "$r" in *'"IsTor":false'*) expect "teep direct HTTPS on its isolated uplink" open open;; *) expect "teep direct HTTPS on its isolated uplink" open "blocked ($r)";; esac
expect "hermes -> teep 10.203.83.3:8337" open "$(tcp hermes 10.203.83.3 8337)"
expect "hermes -> executor SSH 10.203.82.3:2222" open "$(tcp hermes 10.203.82.3 2222)"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 http://127.0.0.1:9120/)
[ "$code" = 302 ] && expect "webapp via HAProxy (302 to login)" open open || expect "webapp via HAProxy (302 to login)" open "blocked ($code)"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -H 'Host: evil.example' http://127.0.0.1:9120/)
[ "$code" = 421 ] && expect "webapp wrong Host refused (421)" open open || expect "webapp wrong Host refused (421)" open "blocked ($code)"

echo "== Forbidden paths"
expect "executor -> teep 10.203.83.3:8337" blocked "$(tcp executor 10.203.83.3 8337)"
expect "hermes -> HAProxy 10.203.85.3:9120" blocked "$(tcp hermes 10.203.85.3 9120)"
for svc in executor hermes teep; do
  expect "$svc -> host loopback via pasta 169.254.1.2:11111" blocked "$(tcp $svc 169.254.1.2 11111)"
done
gw=$(ip -4 route show default | awk '{print $3; exit}')
for svc in executor hermes teep; do
  expect "$svc -> host default gateway $gw:11111" blocked "$(tcp $svc $gw 11111)"
done
edge=$(ip_of webapp-proxy webapp-publish)
torup=$(ip_of tor tor-uplink)
teepup=$(ip_of teep teep-uplink)
echo "   (HAProxy edge $edge, Tor uplink $torup, teep uplink $teepup)"
expect "teep -> HAProxy edge $edge:9120 (between networks)" blocked "$(tcp teep "$edge" 9120)"
expect "teep -> Tor uplink $torup:9040 (between networks)" blocked "$(tcp teep "$torup" 9040)"
expect "tor -> teep uplink $teepup:8337 (between networks)" blocked "$(tcp tor "$teepup" 8337)"
for svc in executor hermes; do
  # A raw DNS query for example.com over UDP, as tests/smoke.py sends.
  r=$(podman exec "$(c $svc)" sh -c 'command -v python3 >/dev/null || { echo "error (no python3)"; exit; }; python3 -c "
import socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(3)
try:
    s.sendto(bytes.fromhex(\"123401000001000000000000076578616d706c6503636f6d0000010001\"),(\"10.203.82.1\",53)); s.recv(4096); print(\"open\")
except OSError: print(\"blocked\")"' 2>/dev/null)
  expect "$svc -> aardvark-dns at gateway 10.203.82.1:53" blocked "$r"
done
r=$(podman exec "$(c executor)" sh -c 'curl -6 -s --max-time 8 -o /dev/null https://check.torproject.org/ && echo open || echo blocked' 2>/dev/null)
expect "executor IPv6 egress" blocked "$r"

# A container of the same user on a network without isolation (F9): Podman's
# Docker-compatible API would give the stack isolate=true only, which does not
# block this source; the stack's networks need isolate=strict.
IMAGE=$(podman inspect "$(c teep)" --format '{{.ImageName}}')
podman network create --subnet 10.203.95.0/24 "$PLAIN" >/dev/null
podman run -d --name "$PLAIN" --network "$PLAIN" --entrypoint sleep "$IMAGE" 600 >/dev/null
# Positive control for the DNS probe: Podman's DNS server answers on the
# disposable network's gateway.
EXECUTOR_IMAGE=$(podman inspect "$(c executor)" --format '{{.ImageName}}')
r=$(podman run --rm --network "$PLAIN" --entrypoint python3 "$EXECUTOR_IMAGE" -c "
import socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(3)
try:
    s.sendto(bytes.fromhex('123401000001000000000000076578616d706c6503636f6d0000010001'),('10.203.95.1',53)); s.recv(4096); print('open')
except OSError: print('blocked')" 2>/dev/null)
expect "DNS probe control: Podman DNS answers on a plain network" open "$r"
for target in "$teepup 8337 teep-uplink" "$edge 9120 HAProxy-edge" "10.203.83.3 8337 teep-inference"; do
  set -- $target
  r=$(podman exec "$PLAIN" sh -c "nc -z -w 5 $1 $2 && echo open || echo blocked" 2>/dev/null)
  expect "non-isolated network -> $3 $1:$2" blocked "$r"
done
for name in $(podman network ls --format '{{.Name}}' | grep "^${P}_"); do
  opt=$(podman network inspect "$name" --format '{{index .Options "isolate"}}')
  [ "$opt" = strict ] && expect "$name isolate=strict" open open || expect "$name isolate=strict" open "blocked (isolate=$opt)"
done
r=$(podman exec "$(c webapp-proxy)" ip route 2>/dev/null | grep -c '^default' || true)
[ "$r" = 0 ] && expect "HAProxy has no default route" blocked blocked || expect "HAProxy has no default route" blocked open

echo "== Totals: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
