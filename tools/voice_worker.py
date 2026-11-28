"""TFS local narration worker: the RTX 3080 narrates first, Modal only as the fallback (owner, 2026-11-24).

Loop (every 2 minutes): read the narration queue in R2 (src/tfs/media/voice_queue.py). When jobs wait:
1. GPU in use by another process (nvidia-smi)? Ask the Taas Noo render for a slot with the agreed file handshake
   (agreed with that session 2026-11-24, live from Taas Noo story 4): write D:/AI-Video/gpu/requests/tfs-voice.json
   ({from, need_minutes, needs_commit_gb, deadline_utc}) and wait for D:/AI-Video/gpu/granted/tfs-voice, which render.sh
   writes at a batch boundary (oldest request first, one at a time, usually within 45 min; skipped when a Taas Noo publish
   is under 12 h away). The render waits until the grant is deleted or need_minutes + 15 passes. Never stop its render.
2. Free commit memory at least 25 GB (VoxCPM2 fails with "paging file is too small" below that)? If not, release the
   slot at once: the cloud narrates on Modal at the job's deadline.
3. Narrate every waiting job in one model load (tools/voice_local_gen.py in the VoxCPM venv), upload the WAVs,
   drop the jobs, release the slot (delete both files).
A job too close to its deadline is left to Modal. The cloud scores every local take with Whisper, like Modal takes.

Needs the R2 credentials (S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_BACKUP_BUCKET) in this repo's
.env (git-ignored). Runs with the repo venv:  .venv/Scripts/pythonw.exe tools/voice_worker.py   (--once for a test)
Log: %LOCALAPPDATA%/TFS/voice_worker.log
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def venv_base(venv: Path) -> tuple[Path, Path]:
    """(base interpreter, site-packages) of a venv, read from its pyvenv.cfg."""
    cfg = {k.strip(): v.strip() for k, v in (l.split("=", 1) for l in
           (venv / "pyvenv.cfg").read_text(encoding="utf-8").splitlines() if "=" in l)}
    return Path(cfg["home"]) / "python.exe", venv / "Lib" / "site-packages"


def use_site(sp: Path) -> None:
    """Put a venv's site-packages (and its .pth entries) at the front of sys.path."""
    import site
    before = list(sys.path)
    site.addsitedir(str(sp))
    sys.path[:] = [p for p in sys.path if p not in before] + before


# The scheduled task runs the base interpreter (C:\Python313\pythonw.exe -I) and the worker loads its venv's packages
# here; VoxCPM is started the same way (see vox_cmd). This keeps the venv launcher exes out of the picture with Avast.
# Note (2026-11-24): the venv launcher worked too (the real log shows both starts); the "sandboxed" reading came from
# checking %LOCALAPPDATA% from an agent shell, which itself sees Avast's sandbox copy of C: files. Check C: files a
# scheduled job writes from a Terminal tab (the owner's own PowerShell), never from an agent's Bash/PowerShell tool.
if sys.prefix == sys.base_prefix and (ROOT / ".venv" / "pyvenv.cfg").exists():
    use_site(venv_base(ROOT / ".venv")[1])
sys.path.insert(0, str(ROOT / "src"))
from tfs.media import voice_queue as vq  # noqa: E402

GPU = Path(os.environ.get("TFS_GPU_DIR", "D:/AI-Video/gpu"))
REQUEST, GRANTED = GPU / "requests" / "tfs-voice.json", GPU / "granted" / "tfs-voice"
VOX_VENV = Path(os.environ.get("TFS_VOXCPM_VENV", "D:/AI-Video/VoxCPM/.venv"))
_BOOT = ("import runpy,site,sys; b=list(sys.path); site.addsitedir(sys.argv[1]); "
         "sys.path[:]=[p for p in sys.path if p not in b]+b; sys.argv=sys.argv[2:]; "
         "runpy.run_path(sys.argv[0], run_name='__main__')")


def vox_cmd(script: Path, *args: str) -> list[str]:
    """Run a script in the VoxCPM venv through its base interpreter (no venv launcher, see the note above).
    Without a pyvenv.cfg (CI, or a moved venv) fall back to the venv's own python.exe."""
    if not (VOX_VENV / "pyvenv.cfg").exists():
        return [str(VOX_VENV / "Scripts" / "python.exe"), "-I", str(script), *args]
    base, sp = venv_base(VOX_VENV)
    return [str(base), "-I", "-c", _BOOT, str(sp), str(script), *args]
POLL_S = 120
NEED_COMMIT_GB = 25.0
MARGIN = timedelta(minutes=20)          # leave a job to Modal when less than this remains before its deadline
RTF_LOCAL = 2.5                         # measured on the 3080 in the pilot: about 2.2x real time
LOG = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "TFS" / "voice_worker.log"
log = logging.getLogger("voice_worker")


class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def free_commit_gb() -> float:
    m = _MemStatus()
    m.dwLength = ctypes.sizeof(_MemStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPageFile / 1024 ** 3


def gpu_in_use() -> bool:
    """Another process holds GPU memory (the Taas Noo WanGP batch, a Blender or voice job of another session)."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return True                                       # cannot tell: behave as if busy and ask for a slot
    return any(line.strip() and int(line.split(",")[1]) > 500 for line in out.splitlines())


def pending(now: datetime) -> list[dict]:
    jobs = []
    for job in vq.list_jobs():
        if datetime.fromisoformat(job["deadline"]) - now > MARGIN:
            jobs.append(job)
    return sorted(jobs, key=lambda j: j["deadline"])


def need_minutes(jobs: list[dict]) -> int:
    words = sum(len(l["text"].split()) for j in jobs for l in j["lines"])
    return max(5, int(words / 2.4 * RTF_LOCAL / 60) + 3)   # 2.4 words a second of speech, plus model load


def wait_for_slot(jobs: list[dict]) -> bool:
    """Ask the render for a slot; give up (Modal will cover) once the earliest deadline gets close."""
    REQUEST.parent.mkdir(parents=True, exist_ok=True)
    GRANTED.parent.mkdir(parents=True, exist_ok=True)
    earliest = datetime.fromisoformat(jobs[0]["deadline"])
    REQUEST.write_text(json.dumps({"from": "TFS Threads and Video Automation (tfs-voice worker)", "need_minutes": need_minutes(jobs),
                                   "needs_commit_gb": NEED_COMMIT_GB, "deadline_utc": earliest.isoformat(),
                                   "requested": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    log.info("asked for a GPU slot (%d min) for %d jobs", need_minutes(jobs), len(jobs))
    while datetime.now(timezone.utc) < earliest - MARGIN:
        if GRANTED.exists() or not gpu_in_use():
            return True
        time.sleep(30)
    return False


def release() -> None:
    for f in (GRANTED, REQUEST):
        try:
            f.unlink()
        except FileNotFoundError:
            pass


def narrate(jobs: list[dict]) -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        lines = [{"id": l["id"], "text": l["text"], "file": f"{n:02d}_{int(l['id']):03d}.wav"}
                 for n, j in enumerate(jobs) for l in j["lines"]]
        (tmp / "job.json").write_text(json.dumps({"seed": jobs[0].get("seed", 19), "lines": lines},
                                                 ensure_ascii=False), encoding="utf-8")
        res = subprocess.run(vox_cmd(ROOT / "tools" / "voice_local_gen.py", str(tmp / "job.json"), str(tmp / "out")),
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        log.info("generator: %s", (res.stdout.strip().splitlines() or ["(no output)"])[-1])
        if res.returncode:
            raise RuntimeError(res.stderr[-1500:])
        for n, j in enumerate(jobs):
            for l in j["lines"]:
                wav = tmp / "out" / f"{n:02d}_{int(l['id']):03d}.wav"
                if wav.exists():
                    vq.put_done(j["item"], l["id"], wav)
            vq.finish_job(j["item"])
            log.info("%s: %d lines uploaded", j["item"], len(j["lines"]))


def once() -> None:
    jobs = pending(datetime.now(timezone.utc))
    if not jobs:
        return
    try:
        if not wait_for_slot(jobs):
            log.info("no GPU slot before the deadline; Modal will narrate")
            return
        if free_commit_gb() < NEED_COMMIT_GB:
            log.warning("only %.1f GB commit free (need %.0f); Modal will narrate", free_commit_gb(), NEED_COMMIT_GB)
            return
        narrate(jobs)
    except Exception:
        log.exception("local narration failed; Modal will narrate at the deadline")
    finally:
        release()


def main() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if "--once" in sys.argv:
        once()
        return
    log.info("voice worker started")
    while True:
        once()
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
