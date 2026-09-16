# CHG-301 R2 test-only, fixed official ARM64 base. Not a production image.
# The build context is exactly this recipe, two signed APKs and their signed index.
FROM docker.io/library/traefik@sha256:444bb54c1f7ebe5fac94d1c40f02b48c08dc005a92fc65ca29c1c75991d16baa

RUN --network=none --mount=type=bind,target=/tmp,ro <<'SH'
set -eu
# Prove actual build sandbox limits before invoking the package manager.
# Docker Desktop creates dormant kernel tunnel devices in a network-none netns.
# Prove no non-loopback UP interface, address or route, not merely device names.
repair_links="$(ip -o link show up)"
repair_addresses="$(ip -o address show)"
repair_routes4="$(ip -4 route show table all)"
repair_routes6="$(ip -6 route show table all)"
# BuildKit may expose the host cgroup namespace: hierarchy root is not this RUN.
repair_cgroup="$(awk -F: '$1 == "0" && $2 == "" {print $3}' /proc/self/cgroup)"
case "$repair_cgroup" in /*) ;; *) exit 1;; esac
case "$repair_cgroup" in *..*) exit 1;; esac
repair_cpu="$(cat "/sys/fs/cgroup${repair_cgroup%/}/cpu.max")"
repair_memory="$(cat "/sys/fs/cgroup${repair_cgroup%/}/memory.max")"
printf 'CHG301_NETWORK_BEGIN\n%s\n%s\n%s\n%s\nCHG301_NETWORK_END\n' "$repair_links" "$repair_addresses" "$repair_routes4" "$repair_routes6"
printf 'CHG301_OBSERVED cgroup=[%s] cpu=[%s] memory=[%s]\n' "$repair_cgroup" "$repair_cpu" "$repair_memory"
printf '%s\n' "$repair_links" | awk 'NF && $2 != "lo:" {exit 1}'
printf '%s\n' "$repair_addresses" | awk 'NF && $2 != "lo" {exit 1}'
printf '%s\n%s\n' "$repair_routes4" "$repair_routes6" | awk 'NF && $0 !~ / dev lo( |$)/ {exit 1}'
test "$repair_cpu" = "100000 100000"
test "$repair_memory" = "2147483648"
printf 'CHG301_SANDBOX network=none cpu=1 memory=2147483648\n'
cd /tmp
sha256sum -c <<'SUMS'
d6ec970cc10e01539e41626f720c4e0ac69016eaa2079a10ef776ffd3243db5b  libssl3-3.5.8-r0.apk
35b892813c23664a3592e4fc8c12a03538a22c579057655361c7043305272a9a  libcrypto3-3.5.8-r0.apk
f0ee7c9c6bb43109521715530f6c1922bd486207ae63e598557ce2900e5a1a49  APKINDEX.tar.gz
SUMS
cd /
world_before="$(sha256sum /etc/apk/world)"
test "$world_before" = "77a627b174a98bc2f3efe36b0291e21b166709844b5280ce11525266789e974e  /etc/apk/world"
simulation="$(apk --no-network --no-cache --no-logfile --repositories-file /dev/null --repository /tmp/APKINDEX.tar.gz fix --upgrade --simulate libcrypto3 libssl3 2>&1)"
printf 'CHG301_SIMULATION_BEGIN\n%s\nCHG301_SIMULATION_END\n' "$simulation"
# A closed grammar: exactly two upgrade actions and the final OK line.
printf '%s\n' "$simulation" | awk '
  /^\(1\/2\) Upgrading libcrypto3 \(3[.]5[.]7-r0 -> 3[.]5[.]8-r0\)$/ {crypto++; next}
  /^\(2\/2\) Upgrading libssl3 \(3[.]5[.]7-r0 -> 3[.]5[.]8-r0\)$/ {ssl++; next}
  /^OK: .* in 18 packages$/ {ok++; next}
  {bad++}
  END {if (crypto != 1 || ssl != 1 || ok != 1 || bad != 0) exit 1}
'
test "$(sha256sum /etc/apk/world)" = "$world_before"
apk --no-network --no-cache --no-logfile --repositories-file /dev/null --repository /tmp/APKINDEX.tar.gz fix --upgrade libcrypto3 libssl3
test "$(sha256sum /etc/apk/world)" = "$world_before"
test ! -e /usr/bin/openssl
printf 'CHG301_APPLIED_WITH_UNCHANGED_WORLD\n'
SH
