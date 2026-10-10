"""Runtime audit-hook firewall for role-separated D4 workers."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping


class RuntimeFirewall:
    def __init__(
        self,
        *,
        role: str,
        forbidden_paths: Mapping[str, Path],
        forbidden_import_prefixes: Iterable[str],
    ) -> None:
        self.role = role
        self._forbidden_paths = {
            os.path.abspath(os.fspath(path)): label for label, path in forbidden_paths.items()
        }
        self._forbidden_import_prefixes = tuple(forbidden_import_prefixes)
        self.forbidden_open_attempts = 0
        self.blocked_open_attempts = 0
        self.successful_forbidden_opens = 0
        self.forbidden_import_attempts = 0
        self.blocked_imports = 0
        self._installed = False

    def _audit(self, event: str, args: tuple[Any, ...]) -> None:
        if event == "open" and args:
            candidate = args[0]
            if isinstance(candidate, (str, bytes, os.PathLike)):
                path = os.path.abspath(os.fsdecode(candidate))
                if path in self._forbidden_paths:
                    self.forbidden_open_attempts += 1
                    self.blocked_open_attempts += 1
                    raise PermissionError(
                        f"RUNTIME_FIREWALL_BLOCKED_OPEN:{self._forbidden_paths[path]}"
                    )
        elif event == "import" and args:
            name = str(args[0])
            if any(name == prefix or name.startswith(prefix + ".") for prefix in self._forbidden_import_prefixes):
                self.forbidden_import_attempts += 1
                self.blocked_imports += 1
                raise ImportError(f"RUNTIME_FIREWALL_BLOCKED_IMPORT:{name}")

    def install(self) -> "RuntimeFirewall":
        if self._installed:
            raise RuntimeError("runtime firewall already installed")
        sys.addaudithook(self._audit)
        self._installed = True
        return self

    def report(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "audit_hook_installed": self._installed,
            "forbidden_open_attempts": self.forbidden_open_attempts,
            "blocked_open_attempts": self.blocked_open_attempts,
            "successful_forbidden_opens": self.successful_forbidden_opens,
            "forbidden_import_attempts": self.forbidden_import_attempts,
            "blocked_imports": self.blocked_imports,
        }


def runtime_firewall_contract_document_v1_1() -> dict[str, object]:
    return {
        "schema_version": "track-b-runtime-firewall-contract-v1-1",
        "status": "FROZEN",
        "implementation": "sys.addaudithook",
        "installed_after_credential_claim": True,
        "installed_before_business_import": True,
        "blocked_before_open": True,
        "actual_attempt_counters": True,
        "formal_success_forbidden_attempts_required": 0,
        "adversarial_attempts_required": True,
        "constant_zero_report_prohibited": True,
    }
