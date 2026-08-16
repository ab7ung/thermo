#!/bin/sh
# End-to-end checks that need real processes and signals. POSIX sh, no deps.
# Thresholds of 5/4 °C mean "always hot", so freezing is deterministic.
set -u
cd "$(dirname "$0")/.." || exit 1
T=./thermo
pass=0
fail=0

check() { # check <label> <actual> <expected>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
    echo "ok   $1"
  else
    fail=$((fail + 1))
    echo "FAIL $1: got '$2' want '$3'"
  fi
}

state() { ps -o stat= -p "$1" 2>/dev/null | cut -c1; }

# exit code comes from the child
$T -- sh -c 'exit 3' >/dev/null 2>&1
check "child exit code passthrough" "$?" "3"

$T -p 50 -r 60 -- true >/dev/null 2>&1
check "resume must be below pause" "$?" "2"

$T -a 1 -- true >/dev/null 2>&1
check "command and --attach are exclusive" "$?" "2"

$T -s powermetrics -- true >/dev/null 2>&1
check "no usable sensor" "$?" "78"

for bad in "-i 0" "-i -1" "-w -5" "-p 500 -r 70"; do
  # shellcheck disable=SC2086
  $T $bad -- true >/dev/null 2>&1
  check "rejects $bad" "$?" "2"
done

$T -a 999999 >/dev/null 2>&1
check "attach to a dead pid" "$?" "1"

# a signal must end the wait immediately, not after a whole poll interval
nohup $T -i 30 -f /tmp/thermo-sig.pid -- sleep 30 >/dev/null 2>&1 </dev/null &
sleep 2
hg=$(cat /tmp/thermo-sig.pid)
before=$(date +%s)
kill "$hg"
while kill -0 "$hg" 2>/dev/null; do sleep 0.1; done
check "SIGTERM answered within 3s" "$(( $(date +%s) - before < 3 ))" "1"

# no command and no --attach: report what the sensor sees
out=$($T 2>&1)
check "status exit code" "$?" "0"
check "status reports a verdict" "$(echo "$out" | grep -c '^would')" "1"

$T -p 25 -r 30 >/dev/null 2>&1
check "status validates thresholds" "$?" "2"

$T -s powermetrics >/dev/null 2>&1
check "status without a sensor" "$?" "78"

# manual hold freezes the job, release thaws it
nohup $T -i 1 -f /tmp/thermo-test.pid -- sleep 30 >/dev/null 2>&1 </dev/null &
sleep 2
hg=$(cat /tmp/thermo-test.pid)
kid=$(pgrep -P "$hg" | head -1)
kill -USR1 "$hg"; sleep 2
check "SIGUSR1 freezes" "$(state "$kid")" "T"
kill -USR2 "$hg"; sleep 2
check "SIGUSR2 thaws" "$(state "$kid")" "S"
kill "$hg"; sleep 2
check "SIGTERM stops the job" "$(state "$kid")" ""
check "pidfile removed" "$([ -e /tmp/thermo-test.pid ] && echo yes || echo no)" "no"

# a hot machine freezes the job on its own (5 °C means "always hot")
nohup $T -i 1 -p 5 -r 4 -f /tmp/thermo-hot.pid -- sleep 30 >/dev/null 2>&1 </dev/null &
sleep 4
hg=$(cat /tmp/thermo-hot.pid)
kid=$(pgrep -P "$hg" | head -1)
check "freezes when hot" "$(state "$kid")" "T"
kill "$hg"; sleep 2
check "thawed on the way out" "$(state "$kid")" ""

# --ungated must never freeze: with no sensor there is nothing to fail safe to
nohup $T -u -s powermetrics -i 1 -f /tmp/thermo-ung.pid -- sleep 20 >/dev/null 2>&1 </dev/null &
sleep 5
hg=$(cat /tmp/thermo-ung.pid)
kid=$(pgrep -P "$hg" | head -1)
check "ungated keeps running" "$(state "$kid")" "S"
kill "$hg"

# stuck hot: give up, stop the job, exit 75
$T -i 1 -p 5 -r 4 -w 0.05 -- sleep 30 >/dev/null 2>&1
check "--max-wait exit code" "$?" "75"

# attaching to our own process group is refused, or it would freeze this shell
nohup sleep 5 >/dev/null 2>&1 </dev/null &
$T -a $! >/dev/null 2>&1
check "refuses own process group" "$?" "1"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
