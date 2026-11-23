"""Release checks for the Git index and the exact document-reader dependency pins."""
from collections.abc import Callable
from pathlib import Path
import json
import re
import subprocess
import sys


def credential_files(repo: Path) -> set[str]:
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--", ".env", ".env.*", ".local/", "work/", ".utility-reuse/",
         "*.sqlite", "*.sqlite3", "*.db", ":(exclude).env.example"], cwd=repo,
    )
    pattern = (
        "-----BEGIN ((RSA|DSA|EC|OPENSSH|ENCRYPTED) )?PRIVATE KEY-----"
        "|sk-(proj-|svcacct-|admin-)[A-Za-z0-9_-]{40,}|sk-[A-Za-z0-9]{48}"
        "|github_pat_[A-Za-z0-9_]{50,}|gh[pousr]_[A-Za-z0-9]{36}"
    )
    scan = subprocess.run(
        ["git", "grep", "--cached", "-I", "-z", "-l", "-E", "-e", pattern, "--", "."],
        cwd=repo, stdout=subprocess.PIPE,
    )
    if scan.returncode not in (0, 1):  # git grep returns 1 for a complete scan without matches.
        scan.check_returncode()
    return set((paths + scan.stdout).decode("utf-8", errors="replace").split("\0")) - {""}


def pinned_packages(content: str) -> list[str]:
    packages = []
    for line_number, raw in enumerate(content.splitlines(), start=1):
        line = raw.partition("#")[0].strip()
        if not line:
            continue
        pin = re.fullmatch(r"([\w.-]+)==(\d+(?:\.\d+)*)", line, flags=re.ASCII)
        if not pin:
            raise ValueError(f"Expected an exact release pin on manifest line {line_number}")
        name = re.sub(r"[-_.]+", "-", pin[1]).lower()
        packages.append(f"{name}@{pin[2]}")
    if not packages:
        raise ValueError("The document-reader manifest contains no version pins")
    return packages


def blocking_advisories(packages: list[str], lookup: Callable[[list[str], str], list[str]]) -> set[str]:
    return set(lookup(packages, "high")) | set(lookup(packages, "critical"))


def github_advisories(packages: list[str], severity: str) -> list[str]:
    # The read-only GitHub CLI prints advisory identifiers. Each query is restricted
    # to active, reviewed advisories affecting these exact published Python versions.
    return subprocess.check_output([
        "gh", "api", "--method", "GET", "--paginate", "/advisories", "-f", "ecosystem=pip",
        "-f", "type=reviewed", "-f", "is_withdrawn=false", "-f", f"severity={severity}",
        "-f", "affects=" + ",".join(packages), "--jq", ".[].ghsa_id",
    ], text=True).splitlines()


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    if sys.argv[1:] == ["credentials"]:
        findings = credential_files(root)
    elif sys.argv[1:] == ["dependencies"]:
        versions = pinned_packages((root / "requirements-documents.txt").read_text(encoding="utf-8"))
        findings = blocking_advisories(versions, github_advisories)
    else:
        sys.exit("Expected 'credentials' or 'dependencies'")
    for finding in sorted(findings):
        print(json.dumps(finding))
    sys.exit(1 if findings else 0)
