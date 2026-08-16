# Changelog

## 1.0.0 — 2026-08-16

First release.

- Freeze a command, or a process already running, whenever the machine gets hot;
  thaw it once it cools. Whole process group, so children stop too.
- Temperature from what the OS gives without root: AppleSMC on macOS (`Tp*` CPU,
  `Tg*` GPU, `TB*` battery), thermal zones and hwmon on Linux, ACPI on Windows.
  `powermetrics` available opt-in for Intel Macs.
- Live terminal view with CPU, GPU, chassis, fans and the current verdict;
  a single snapshot when redirected; one line per reading with `-v`.
- Hooks on freeze and thaw (`-o`, `-O`), manual hold via SIGUSR1/SIGUSR2,
  `--max-wait` to give up on a machine that never cools.
- Hysteresis of two agreeing readings each way; macOS throttling counts as hot;
  a sensor that stops answering three times running fails safe to frozen.
- Refuses to attach to a process in the calling shell's own group, refuses a
  pidfile another running thermo owns, and always thaws on every exit path.
- Signals answered immediately rather than at the next poll; exit codes follow
  the shell convention (130 SIGINT, 143 SIGTERM, 75 stuck hot, 78 no sensor).

Known limits: freezing does not cancel an in-flight request, only stops new
ones; Windows reads temperatures and runs hooks but cannot freeze; fan speeds
are Linux-only; two thermo runs gating the same process will fight over it.
Verified on macOS 15 (Apple M4 Max). The Linux readers are tested against a
fake /sys tree and the Windows one against captured output, but neither has run
on real hardware.
