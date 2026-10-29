# Execution environments and sandboxing

Two different questions, two different answers:

- **Where does a model train?** On this machine's CPU, or on a worker (M37). `train run --target
  local|remote`. The numbers are identical, because it is the same trainer.
- **Where does a command run?** On this machine, in a container, in WSL, in a VM, in a Windows
  Sandbox, or on another computer. `exec run … --target <name>`.

This page is the second one. The point of it is that "it ran in a sandbox" is a **row** with the
backend on it, the exact invocation that executed, and - when a backend cannot be used here - the
reason it cannot.

```text
archx-agent exec targets                                 # what this machine can do, and why not
archx-agent exec add docker --image debian:12            # record a target
archx-agent exec run "python3 -V" --target docker        # run one command there
archx-agent exec runs                                    # every command, with where it ran
archx-agent exec files                                   # what was pushed and pulled, with both hashes
archx-agent exec stats                                   # targets, runs, conflicts, per backend
archx-agent exec push --target vm1 --root ./project      # send the project (remote only)
archx-agent exec pull --target vm1 --root ./project      # bring the changes back
```

---

## 1. The backends, and what each one is really worth

| backend | what runs | isolation | can this build drive it here |
| --- | --- | --- | --- |
| `local` | `sh -lc '<command>'` on this machine | **none** beyond the permission centre | yes, always |
| `docker` | `docker run --rm --network none -v <cwd>:/work -w /work <image> sh -lc '<cmd>'` | the mounted directory, and nothing else | refused: no docker CLI |
| `wsl` | `wsl.exe [-d <distro>] -e sh -lc '<cmd>'` | **not a boundary** - `/mnt/c` is your disk | refused: Windows only |
| `windows-sandbox` | a generated `.wsb` + `WindowsSandbox.exe` | a disposable VM, discarded on close | refused: Windows only |
| `vmware` | `vmrun -T ws runScriptInGuest <vmx> <script> '<cmd>'` | a VM you own | refused: no `vmrun` |
| `virtualbox` | `VBoxManage guestcontrol <vm> run --exe /bin/sh -- -c '<cmd>'` | a VM you own | refused: no `VBoxManage` |
| `remote` | `POST /exec` on an M37 worker with `--allow-exec` | another machine entirely | yes, when a worker is running |

`exec targets` prints this table for the machine you are on, with the reason each unusable backend
gives and the command that would enable it:

```text
$ archx-agent exec targets
backend          here  isolation                                           how to enable
local            yes   capability grants only - not a boundary for ...     -
remote           yes   a separate machine: it can only damage itself      archx-agent remote worker --allow-exec --token ...
docker           no    a container: the filesystem you mount and ...      install Docker, then: archx-agent exec add docker ...
wsl              no    **not a boundary**: /mnt/c is your own disk         wsl --install, then: archx-agent exec add wsl ...
windows-sandbox  no    a disposable VM: everything is discarded ...       Turn on Windows Sandbox, then: archx-agent exec ...
  wsl: this is Linux; WSL exists only on Windows
  windows-sandbox: this is Linux; Windows Sandbox exists only on Windows 10/11 Pro, Enterprise or Education
  vmware: vmrun is not on PATH (VMware Workstation/Fusion is not installed)
  virtualbox: VBoxManage is not on PATH (VirtualBox is not installed)
```

Two rows are worth reading twice. `remote` says *yes* even with no worker running, because the
question the probe answers is "could this kind work from here?" - whether *your* worker is up is
checked per target, at run time, in the refusal. And `wsl` says **not a boundary** in the table
itself. (The `isolation` column is truncated to fit a terminal; `exec targets --json` has the full
sentence.)

A backend that cannot run is **not hidden**. `exec add` still records it, with `status = refused` and
the reason, so "I set this up and it did not work" is in the ledger instead of in your memory.

---

## 2. Why the wrapper is the whole feature

A target named `docker` that quietly runs the command on this machine is worse than no sandbox at
all, because you have been told you are safe. So the wrapper is built by one pure function
(`build_invocation`), recorded on the run row (`invocation`), and tested by putting a **stand-in
binary** on `PATH` that records its own argv:

```text
$ PATH=./bin:$PATH archx-agent exec run "echo inside" --target docker --json | jq .invocation
"docker run --rm --network none -v /home/me/proj:/work -w /work debian:12 sh -lc 'echo inside'"
$ cat bin/docker.argv
run
--rm
--network
none
-v
/home/me/proj:/work
-w
/work
debian:12
sh
-lc
echo inside
```

The host side of the mount is made **absolute** on purpose: `-v .:/work` would mean "wherever docker
was started", which is a different directory the moment the invocation is replayed.

`scripts/acceptance_m38.sh` does exactly that, so the docker path is exercised on a machine without
docker - and the docs do not have to claim a container ran.

Two consequences worth stating:

- **`--network none` is the default.** A sandbox that can reach the internet is not a sandbox for
  anything that fetches. `exec add docker --network bridge` is the deliberate opt-out.
- **Children get a minimal environment.** `shell.run` passes `PATH`, `HOME` (the Archx home) and the
  tool paths - not your whole environment - so a secret in an exported variable does not leak into a
  sandboxed command. (It also means a stand-in binary cannot be pointed at a scratch file through an
  env var: bake the path in, as the acceptance script does.)
- **WSL is labelled as *not* a boundary.** It is a second Linux environment; `/mnt/c` is your disk.
  Calling it a sandbox would be the exact dishonesty this file exists to avoid.

---

## 3. Windows Sandbox is *detached*, and says so

`WindowsSandbox.exe` starts a disposable VM and returns immediately; the sandbox reports nothing to
the process that launched it. So this backend cannot stream stdout, and it does not pretend to:

- the run is recorded with `status = detached`;
- a `.wsb` is generated (mapped folder, clipboard off, networking off by default, a `LogonCommand`
  that writes `archx-exec.log` into the mapped folder);
- the run's `note` names the config file and the log file, so you know where the answer will appear.

The `.wsb` is generated by a pure function and unit-tested on Linux, because it is the part that
decides whether a result is retrievable at all:

```xml
<Configuration>
  <Networking>Disable</Networking>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>C:\proj</HostFolder>
      <SandboxFolder>C:\archx</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>cmd.exe /c cd /d C:\archx &amp;&amp; python --version &gt; C:\archx\archx-exec.log 2&gt;&amp;1</Command>
  </LogonCommand>
</Configuration>
```

---

## 4. Another computer: the project goes there and comes back

This is the "connect a VM and run everything on it" case. The worker is M37's, started with two extra
flags - both opt-ins, because the operator of the worker is the person whose machine a command can
damage:

```text
archx-agent remote worker --host 0.0.0.0 --port 9001 --allow-exec --token <secret> --workdir /srv/archx
```

- without `--allow-exec`, `/exec` *and* `/files` answer **403** with the flag named, and `/jobs`
  (training) still works: training is data, execution is not - and `push`/`pull` are execution;
- with `--token`, **every** route (`/health`, `/jobs`, `/exec`, `/files`) requires
  `Authorization: Bearer`, compared in constant time; set `remote.worker_token` here to match. A
  worker without a token is open to anyone who can reach the port, and says so on startup;
- commands run in `--workdir`, and a `cwd` (or a `root` on `/files`) that would escape it is refused
  with "… must stay inside the work directory".

Then:

```text
$ archx-agent exec push --target vm1 --root ./project
pushed 2 file(s), 47 bytes to vm1
$ archx-agent exec run "pytest -q" --target vm1
ok xr_…  [remote]  exit 0
  ran       POST http://127.0.0.1:9001/exec
  note      ran on exec-box
$ archx-agent exec pull --target vm1 --root ./project
pulled from vm1  (2 file(s) there)
  applied   main.py
  1 unchanged
```

### The conflict rule, which is the interesting part

`execution_files` records every push and pull with **both** hashes: what this machine had, and what
the target had. A pull compares three things - the base (the last push), the local file now, and the
remote file now:

| local since push | remote since push | what happens |
| --- | --- | --- |
| unchanged | unchanged | skipped |
| unchanged | changed | applied |
| changed | unchanged? / new remotely | applied (nothing to lose) |
| **changed** | **changed** | **conflict** - not written, exit 3, `--force` replaces it |

```text
$ archx-agent exec pull --target vm1 --root ./project
pulled from vm1  (2 file(s) there)
  conflict  main.py  - changed here too; --force replaces it
  1 unchanged
[exit 3]
```

That is the whole reason the ledger exists: an hour of work on the far side must not silently delete
the edit you made here while you waited.

---

## 5. What is saved *here*

Three things, and one honest absence:

1. **The command.** `execution_runs` keeps the command as typed, the invocation that executed, the
   cwd, the exit code, the duration, and whether it timed out or was detached.
2. **The output.** stdout and stderr are stored on the row *and* written through `fs.write` as
   artifacts, so the evidence outlives the terminal.
3. **The files.** `execution_files` is the hash ledger described above; `exec files` prints it.
4. **The database does not cross.** The remote machine has no Archx database (that is what makes it a
   worker), and copying a live SQLite file back would be a foot-gun, not a feature. What comes back is
   the ledger *about* the work - runs, outputs, file hashes - written here.

---

## 6. Training: the user's CPU or a worker

`train run --target local` (default) or `--target remote`:

```text
$ archx-agent train run --method ngram --dataset code --order 2 --seed 5 --target remote
completed tj_…  ngram on ds_…
  train  perplexity 2.5323, records 5, tokens 38
  ...
$ archx-agent train show tj_…
  dataset   ds_…  seed 5  target remote
  remote    rj_…
```

The remote run is **one row in the same table**: `training_jobs.target = 'remote'`,
`remote_job_id = rj_…`, metrics in `training_metrics` as rows. So `train list`, `train compare` and
`train metrics` treat a run on a worker exactly like a run here - and the acceptance script asserts
the two produce **equal** perplexities, because the worker calls the same `train_records()`.

`--target remote` records the bundle's approval as `user:train-run`: asking for it *is* the approval.
What is never skipped is the check - the artifact is hashed here before a metric from it is written.

A sandbox is **not** a training target. A trainer needs the dataset and the artifact inside the
sandbox, which is a different piece of work; `train run --target docker` is refused by name rather
than quietly running on the CPU.

---

## 7. The settings

| key | default | meaning |
| --- | --- | --- |
| `execution.enabled` | `false` | nothing runs on any target until this is on |
| `execution.target` | `local` | default target for `exec run` |
| `execution.project` | `""` | directory `exec push`/`pull` treat as the project (default `.`) |
| `execution.timeout` | `60` | seconds a command may run |
| `execution.max_files` | `200` | files a push may send |
| `remote.worker_token` | `""` | bearer token a worker requires (empty = the worker is open) |
| `training.target` | `local` | where `train run` executes: `local` or `remote` |

`execution.enabled` is off by default for the same reason `remote.enabled` is: a command in a sandbox
is still a command.

---

## 8. What this does not do

- **No image management.** `docker` uses an image you already have; nothing is pulled, built or
  pruned.
- **No snapshot or rollback of a VM.** `vmware`/`virtualbox` run a command in a guest you already
  prepared; taking a snapshot before and reverting after is your job (and a good habit).
- **No interactive sessions.** A command runs to completion or to its timeout; there is no pty, no
  stdin, no `docker exec` into a running container.
- **No file sync for containers, WSL or VMs.** They read the directory you mounted, so `push`/`pull`
  refuse those targets by name instead of pretending to copy.
- **No streaming output.** Output arrives when the command finishes (bounded, and clipped at the
  tool layer's limit). A long build shows nothing until it ends.
- **No database transfer.** See §5.
- **A detached run has no exit code.** Windows Sandbox cannot report one, so the row says `detached`
  rather than inventing a `0`.
- **The worker's `/exec` is a shell.** That is what it is for, and it is why it needs `--allow-exec`
  and a token; anyone who reaches an open port can run commands there.
