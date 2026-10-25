"""
In-app updates of an installed copy (a git checkout made by install.sh): check() looks for
new commits on the tracked branch, installer/update.sh applies them. Replaces upstream's
check of the Windows releases on GitHub.
"""
import logging
import os
import subprocess

logger = logging.getLogger("Updater")

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPDATE_SCRIPT = os.path.join(APP_DIR, "installer", "update.sh")


def _git(*args, timeout=30) -> str:
    return subprocess.run(["git", "-C", APP_DIR, *args], capture_output=True, text=True,
                          check=True, timeout=timeout).stdout.strip()


def check() -> dict | None:
    """
    {"current", "latest", "changes": [subject, ...]} when the branch has new commits, None
    when up to date, offline, or this copy is not a git checkout. Blocking: run in a thread.
    """
    if not os.path.isdir(os.path.join(APP_DIR, ".git")):
        return None
    try:
        upstream = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        _git("fetch", "--quiet", upstream.split("/", 1)[0], timeout=60)
        current = _git("rev-parse", "HEAD")
        latest = _git("rev-parse", upstream)
        if current == latest or not _git("rev-list", f"HEAD..{upstream}"):
            return None
        changes = _git("log", "--format=%s", f"HEAD..{upstream}").splitlines()
        return {"current": current, "latest": latest, "changes": changes}
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"Update check failed: {e}")
        return None
