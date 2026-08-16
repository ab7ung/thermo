# thermo

Keep a long job from cooking your machine. `thermo` runs a command, watches the
temperature, and freezes the job whenever the machine gets hot — thawing it when
it cools. Nothing to install: one Python file, standard library only.

Written for hours-long local LLM inference in a hot room, but it knows nothing
about models or providers. It supervises a process, so it works the same for
`ollama`, a SAST scan, a build, a video encode.

```sh
chmod +x thermo && ./thermo -- npm run build   # run it from anywhere
sudo make install                              # or put it on PATH
```

One file, Python 3.8+, standard library only. Copy it to a machine and it runs.

## Usage

```
thermo [options] -- command ...      # run a command under thermal control
thermo [options] -a PID              # gate a process that is already running
thermo                               # live readings in the terminal, q to quit
```

In a terminal, plain `thermo` refreshes every second until you press `q`:

```
thermo · smc sensor (chip) · 13:52:25 · elapsed 04:12

  CPU              40.0 °C max    40.0 °C avg
  GPU              43.0 °C max    39.1 °C avg
  body (chassis)   29.8 °C
  fans            -
  throttle        no
  hottest range    41.9 °C ..  46.3 °C

  verdict         run  (pause 85 / resume 70)

  q quit
```

Redirect it and you get a single snapshot instead, for scripts. `thermo -v`
streams one timestamped line per reading, for logs. `-i` sets the refresh rate.

On Apple Silicon the temperatures come from the SMC, the only source that works
without root - `powermetrics` reports none there at all. The SMC labels its
sensors, which is where the CPU/GPU split comes from: `Tp*` are CPU cores,
`Tg*` the GPU, `TB*` the battery. Verified under load: a CPU burn moved `Tp`
from 31 °C to 93 °C while `Tg` tracked the GPU within 1 °C of macmon.

Each row shows two figures because they answer different questions. The average
is what GUI monitors display; the maximum is the hottest core, the one closest
to throttling, so that is what thermo gates on. Expect the max to sit above
whatever macmon or btop reports - they average a different subset over a
different window.

Fan speeds stay Linux-only; macOS keeps them behind root.

| Short | Long | Default | Meaning |
|-------|------|---------|---------|
| `-p N` | `--pause` | 37 chassis / 85 die | freeze at or above this °C |
| `-r N` | `--resume` | 34 chassis / 70 die | thaw at or below this °C |
| `-i S` | `--interval` | 10 | seconds between readings |
| `-a PID` | `--attach` | — | supervise a running process instead of starting one |
| `-o CMD` | `--on-pause` | — | run this when freezing |
| `-O CMD` | `--on-resume` | — | run this when thawing |
| `-w M` | `--max-wait` | 0 (forever) | minutes stuck hot before giving up |
| `-f PATH` | `--pidfile` | — | write thermo's own pid here |
| `-s NAME` | `--sensor` | auto | `smc`, `ioreg`, `sysfs`, `wmi`, `powermetrics` |
| `-u` | `--ungated` | off | run even when no sensor is available |
| `-v` | `--verbose` | off | log every reading, not just changes |

Signals to thermo itself: `USR1` hold the job frozen, `USR2` release the hold,
`TERM`/`INT` stop everything.

Exit codes: the child's, or `75` stuck hot, `78` no sensor, `143` terminated.

## Examples

```sh
# simplest
thermo -- npm run translate

# local LLM: freeze the client and drop the model so the GPU actually idles
thermo -p 36 -r 33 -o 'ollama stop qwen3:27b' -- npm run translate

# better for a batch job: gate the server once, every client is paced for free
thermo -i 5 -f /tmp/thermo.pid -- ollama serve

# a scan, a build, an encode - thermo does not care what it is
thermo -- semgrep --config auto .
thermo -s sysfs -p 85 -r 70 -- python train.py

# take manual control mid-run
kill -USR1 $(cat /tmp/thermo.pid)    # hold
kill -USR2 $(cat /tmp/thermo.pid)    # release
```

## How it decides

| Platform | Reading | Scale |
|----------|---------|-------|
| macOS | AppleSMC keys (`smc`) - `Tp*` CPU, `Tg*` GPU, `TB*` battery, no root | die |
| Linux | `/sys/class/thermal/*/temp`, `/sys/class/hwmon/*/temp*_input` | die |
| macOS fallback | `ioreg` battery sensor; `pmset -g therm` for throttling | chassis |
| macOS, opt-in | `powermetrics --samplers smc` (root; Intel Macs only) | die |
| Windows | `MSAcpi_ThermalZoneTemperature` via PowerShell | die |

The first sensor that answers wins, and its scale picks the default thresholds —
a chassis reading of 37 °C means roughly what a die reading of 85 °C does.

Only sensors the platform can actually have are probed. Freezing needs two
consecutive hot readings, and thawing two cool ones, so a brief spike does not
flap the job. macOS throttling is treated as hot on its
own. If the sensor stops answering three times running, thermo assumes the
worst and freezes.

## Limits worth knowing

- **A frozen job stops making requests; it does not cancel the one in flight.**
  For a local model server, pair the freeze with `-o 'ollama stop <model>'`, or
  supervise the server instead of the client.
- **Frozen means hung, not failed.** Anything talking to a frozen process over
  the network waits. Keep pauses shorter than your client's timeout, or gate the
  client instead.
- **The whole process group is frozen**, so children and grandchildren stop too.
  `-a` refuses to attach to a process in your own shell's group — freezing that
  would freeze the shell with nothing left to thaw it.
- **Where the SMC is unavailable, macOS falls back to the battery sensor.** It
  lags the silicon by a minute or two and reads far lower, so the thresholds
  drop with it (37/34 instead of 85/70).
- **Windows has no SIGSTOP.** Temperatures are read and hooks still run, but
  nothing is actually frozen.
- **Two thermo runs gating the same process will fight** over freeze and thaw.
  Use one, and `-f` to keep track of it.
- thermo never kills a process it did not start.

## Tests

```sh
make test     # both suites
make unit     # parsers, sensor grouping, freeze/thaw policy
make cli      # real processes, signals, exit codes
```

## Status

Verified on macOS 15 (Apple M4 Max). The Linux readers run in the test suite
against a fake `/sys` tree and the Windows one against captured output, but
neither has been exercised on real hardware - reports welcome. See
CHANGELOG.md.

MIT licensed.
