"""Process-wide audit guard for dedicated P0 test/fixture processes only."""
import sys

_installed = False


def install():
    global _installed
    if _installed:
        return

    def guard(event, args):
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.fork", "os.exec"}:
            raise PermissionError("P0_OFFLINE_GUARD_BLOCKED: " + event)

    sys.addaudithook(guard)
    _installed = True
