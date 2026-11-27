#!/bin/sh
# Allowed and forbidden network paths of a running rootless Podman stack
# (configured project). Run after `make up` on Podman:
#   make podman-paths-test
# The allowed-path checks need Internet access: they fetch
# https://check.torproject.org/api/ip through Tor and through teep's uplink.
# Each check prints PASS or FAIL against the expected result; the script exits
# non-zero on any FAIL. It starts a TCP listener on 127.0.0.1:11111, and a
# disposable network and container without isolation, and removes them at exit.
set -u
cd "$(dirname "$0")/.." || exit 2
# Every probe uses the local rootless Podman that CONTAINER_ENGINE=podman selects.
case "$(python3 scripts/deployment.py compose-command)" in
  *"podman --remote=false compose") ;;
  *) echo "FAIL  select Podman first: CONTAINER_ENGINE=podman make podman-paths-test"; exit 2;;
esac
podman() { command podman --remote=false "$@"; }
IFS=' ' read -r P PREFIX WEBAPP_PORT <<EOF
$(python3 -c '
import sys
sys.path.insert(0, "scripts")
import deployment
from addressing import validate_network_prefix, validate_project_name
project = validate_project_name(deployment.configured_env_value("COMPOSE_PROJECT_NAME", "private-hermes"))
prefix = validate_network_prefix(deployment.configured_env_value("NETWORK_PREFIX", "10.203"))
port = deployment.configured_env_value("WEBAPP_PORT", "9120")
if not port.isdigit() or not 1 <= int(port) <= 65535:
    raise SystemExit("invalid WEBAPP_PORT")
print(project, prefix, port)
')
EOF
[ -n "$P" ] && [ -n "$PREFIX" ] && [ -n "$WEBAPP_PORT" ] || { echo "FAIL  could not read valid COMPOSE_PROJECT_NAME, NETWORK_PREFIX, or WEBAPP_PORT"; exit 2; }
c() { echo "${P}-$1-1"; }
pass=0; fail=0
expect() { # name, expected (open|blocked), actual (open|blocked)
  if [ "$2" = "$3" ]; then echo "PASS  $1: $3"; pass=$((pass+1)); else echo "FAIL  $1: expected $2, got $3"; fail=$((fail+1)); fi
}
valid_ip() { echo "$1" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$'; }
tcp() { # container, host, port -> open|blocked (python3 or nc inside the container)
  # An unresolved target is a test error, never "blocked".
  valid_ip "$2" || { echo "error (no address: '$2')"; return; }
  if podman exec "$(c "$1")" sh -c "command -v python3 >/dev/null" 2>/dev/null; then
    podman exec "$(c "$1")" python3 -c "
import socket,sys
s=socket.socket(); s.settimeout(5)
try: s.connect(('$2',$3)); print('open')
except ConnectionRefusedError: print('refused (path reachable)')
except Exception: print('blocked')" 2>/dev/null
  elif podman exec "$(c "$1")" sh -c "command -v nc >/dev/null" 2>/dev/null; then
    podman exec "$(c "$1")" sh -c "nc -z -w 5 $2 $3 && echo open || echo blocked" 2>/dev/null
  else
    echo "error (no python3 or nc in $1)"
  fi
}
ip_of() { podman inspect "$(c "$1")" --format "{{(index .NetworkSettings.Networks \"${P}_$2\").IPAddress}}"; }

PLAIN=private-hermes-paths-plain
HOSTSVC=
cleanup() {
  [ -n "$HOSTSVC" ] && kill $HOSTSVC 2>/dev/null
  podman rm -f "$PLAIN" "$PLAIN-listener" "$PLAIN-control" >/dev/null 2>&1
  podman network rm "$PLAIN" >/dev/null 2>&1
}
trap cleanup EXIT INT TERM
cleanup    # leftovers of an interrupted run

# Stand-in host service on host loopback and on the host's own address (D4).
# pasta's 169.254.1.2 reaches the host's address, not host loopback. A TCP
# listener that serves nothing: the probes only test whether a connection opens.
HOSTADDR=$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')
valid_ip "$HOSTADDR" || { echo "FAIL  no host address found"; exit 1; }
python3 -I -c '
import socket, sys, threading
def serve(address):
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((address, 11111)); s.listen()
    while True: s.accept()[0].close()
threading.Thread(target=serve, args=(sys.argv[1],), daemon=True).start()
serve("127.0.0.1")
' "$HOSTADDR" >/dev/null 2>&1 & HOSTSVC=$!
sleep 1
kill -0 "$HOSTSVC" 2>/dev/null && python3 -I -c 'import socket; socket.create_connection(("127.0.0.1", 11111), timeout=3).close()' 2>/dev/null \
  || { echo "FAIL  host listener on 127.0.0.1:11111 did not start (port in use?)"; exit 1; }

echo "== Allowed paths"
for svc in executor hermes; do
  r=$(podman exec "$(c $svc)" sh -c 'curl -s --max-time 90 https://check.torproject.org/api/ip || python3 -c "import urllib.request;print(urllib.request.urlopen(\"https://check.torproject.org/api/ip\",timeout=90).read().decode())"' 2>/dev/null)
  case "$r" in *'"IsTor":true'*) expect "$svc public HTTPS via Tor" open open;; *) expect "$svc public HTTPS via Tor" open "blocked ($r)";; esac
done
r=$(podman exec "$(c teep)" sh -c 'curl -s --max-time 90 https://check.torproject.org/api/ip' 2>/dev/null)
case "$r" in *'"IsTor":false'*) expect "teep direct HTTPS on its isolated uplink" open open;; *) expect "teep direct HTTPS on its isolated uplink" open "blocked ($r)";; esac
expect "hermes -> teep ${PREFIX}.83.3:8337" open "$(tcp hermes "${PREFIX}.83.3" 8337)"
expect "hermes -> executor SSH ${PREFIX}.82.3:2222" open "$(tcp hermes "${PREFIX}.82.3" 2222)"
# Hermes answers 503 through HAProxy until its webapp is ready.
for _ in $(seq 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "http://127.0.0.1:${WEBAPP_PORT}/")
  [ "$code" = 503 ] || [ "$code" = 000 ] || break
  sleep 2
done
[ "$code" = 302 ] && expect "webapp via HAProxy (302 to login)" open open || expect "webapp via HAProxy (302 to login)" open "blocked ($code)"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -H 'Host: evil.example' "http://127.0.0.1:${WEBAPP_PORT}/")
[ "$code" = 421 ] && expect "webapp wrong Host refused (421)" open open || expect "webapp wrong Host refused (421)" open "blocked ($code)"

echo "== Forbidden paths"
expect "executor -> teep ${PREFIX}.83.3:8337" blocked "$(tcp executor "${PREFIX}.83.3" 8337)"
expect "hermes -> HAProxy ${PREFIX}.85.3:9120" blocked "$(tcp hermes "${PREFIX}.85.3" 9120)"
for svc in executor hermes; do
  expect "$svc -> host service via pasta 169.254.1.2:11111" blocked "$(tcp $svc 169.254.1.2 11111)"
done
# teep has its own direct uplink and no endpoint firewall; like Docker's uplink
# gateway, pasta's address reaches host services bound to the host's address.
echo "INFO  teep -> host service via pasta 169.254.1.2:11111: $(tcp teep 169.254.1.2 11111) (accepted uplink exposure, docs/architecture.md)"
gw=$(ip -4 route show default | awk '{print $3; exit}')
for svc in executor hermes teep; do
  expect "$svc -> host default gateway $gw:11111" blocked "$(tcp $svc $gw 11111)"
done
edge=$(ip_of webapp-proxy webapp-publish)
torup=$(ip_of tor tor-uplink)
teepup=$(ip_of teep teep-uplink)
echo "   (HAProxy edge $edge, Tor uplink $torup, teep uplink $teepup)"
expect "teep -> HAProxy edge $edge:${WEBAPP_PORT} (between networks)" blocked "$(tcp teep "$edge" "$WEBAPP_PORT")"
expect "teep -> Tor uplink $torup:9040 (between networks)" blocked "$(tcp teep "$torup" 9040)"
expect "tor -> teep uplink $teepup:8337 (between networks)" blocked "$(tcp tor "$teepup" 8337)"
for svc in executor hermes; do
  # A raw DNS query for example.com over UDP, as tests/smoke.py sends.
  r=$(podman exec "$(c $svc)" sh -c 'command -v python3 >/dev/null || { echo "error (no python3)"; exit; }; python3 -c "
import socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(3)
try:
    s.sendto(bytes.fromhex(\"123401000001000000000000076578616d706c6503636f6d0000010001\"),(\"'"${PREFIX}"'.82.1\",53)); s.recv(4096); print(\"open\")
except OSError: print(\"blocked\")"' 2>/dev/null)
  expect "$svc -> aardvark-dns at gateway ${PREFIX}.82.1:53" blocked "$r"
done
for svc in executor hermes; do
  # A global-scope IPv6 address (scope 00) outside loopback would allow IPv6
  # egress; link-local addresses (scope 20) do not route.
  r=$(podman exec "$(c $svc)" sh -c 'test -r /proc/net/if_inet6 || { echo "error (no if_inet6)"; exit; }; awk "\$6 != \"lo\" && \$4 == \"00\"" /proc/net/if_inet6 | grep -q . && echo open || echo blocked' 2>/dev/null)
  expect "$svc global IPv6 address" blocked "$r"
done

# A container of the same user on a network without isolation (F9): Podman's
# Docker-compatible API would give the stack isolate=true only, which does not
# block this source; the stack's networks need isolate=strict.
IMAGE=$(podman inspect "$(c teep)" --format '{{.ImageName}}')
podman network create --subnet "${PREFIX}.95.0/24" "$PLAIN" >/dev/null
podman run -d --name "$PLAIN" --network "$PLAIN" --entrypoint sleep "$IMAGE" 600 >/dev/null
# Positive control for the DNS probe: Podman's DNS server answers on the
# disposable network's gateway.
EXECUTOR_IMAGE=$(podman inspect "$(c executor)" --format '{{.ImageName}}')
r=$(podman run --rm --network "$PLAIN" --entrypoint python3 "$EXECUTOR_IMAGE" -c "
import socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(3)
try:
    s.sendto(bytes.fromhex('123401000001000000000000076578616d706c6503636f6d0000010001'),('${PREFIX}.95.1',53)); s.recv(4096); print('open')
except OSError: print('blocked')" 2>/dev/null)
expect "DNS probe control: Podman DNS answers on a plain network" open "$r"
# Positive control for the TCP probes: a listener on the same plain network is reachable.
podman run -d --name "$PLAIN-listener" --network "$PLAIN" --entrypoint python3 "$EXECUTOR_IMAGE" -c "
import socket
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('0.0.0.0', 7000)); s.listen()
while True: s.accept()[0].close()" >/dev/null
plainpeer=$(podman inspect "$PLAIN-listener" --format "{{(index .NetworkSettings.Networks \"$PLAIN\").IPAddress}}")
r=error
for _ in $(seq 10); do
  r=$(podman exec "$PLAIN" sh -c "command -v nc >/dev/null || { echo 'error (no nc)'; exit; }; nc -z -w 5 $plainpeer 7000 && echo open || echo blocked" 2>/dev/null)
  [ "$r" = open ] && break
  sleep 1
done
valid_ip "$plainpeer" || r="error (no address: '$plainpeer')"
expect "TCP probe control: plain network -> listener $plainpeer:7000" open "$r"
# Positive control for the host-loopback probe: a container on a network without
# the stack's firewall reaches the host listener through pasta's address.
podman run -d --name "$PLAIN-control" --network "$PLAIN" --entrypoint sleep "$IMAGE" 600 >/dev/null
r=$(podman exec "$PLAIN-control" sh -c "nc -z -w 5 169.254.1.2 11111 && echo open || echo blocked" 2>/dev/null)
expect "host-service probe control: plain network -> 169.254.1.2:11111" open "$r"
for target in "$teepup 8337 teep-uplink" "$edge $WEBAPP_PORT HAProxy-edge" "${PREFIX}.83.3 8337 teep-inference"; do
  set -- $target
  valid_ip "$1" || { expect "non-isolated network -> $3" blocked "error (no address: '$1')"; continue; }
  r=$(podman exec "$PLAIN" sh -c "command -v nc >/dev/null || { echo 'error (no nc)'; exit; }; nc -z -w 5 $1 $2 && echo open || echo blocked" 2>/dev/null)
  expect "non-isolated network -> $3 $1:$2" blocked "$r"
done
names=$(podman network ls --filter "label=com.docker.compose.project=${P}" --format '{{.Name}}')
count=$(echo "$names" | grep -c .)
[ "$count" -ge 9 ] && expect "project networks found ($count)" open open || expect "project networks found" open "blocked ($count)"
for name in $names; do
  opt=$(podman network inspect "$name" --format '{{index .Options "isolate"}}')
  [ "$opt" = strict ] && expect "$name isolate=strict" open open || expect "$name isolate=strict" open "blocked (isolate=$opt)"
done
r=$(podman exec "$(c webapp-proxy)" sh -c 'command -v ip >/dev/null || { echo error; exit; }; routes=$(ip route) || { echo error; exit; }; echo "$routes" | grep -c "^default"' 2>/dev/null)
case "$r" in 0) actual=blocked;; error) actual="error (no ip)";; *) actual=open;; esac
expect "HAProxy has no default route" blocked "$actual"

echo "== Totals: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
