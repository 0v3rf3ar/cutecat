from __future__ import annotations

import re
from dataclasses import dataclass

READONLY_PATTERNS = [
    # listing / navigation / file inspection
    r"ls|ll|la|dir|vdir|pwd|cd|tree|stat|file|readlink|realpath|basename|dirname",
    r"cat|tac|bat|head|tail|nl|less|more|wc|cksum|sum|md5sum|sha\d+sum|b2sum",
    r"cmp|diff|diff3|sdiff|comm|column|fold|expand|unexpand|rev",
    # text search / read-only processing
    r"grep|egrep|fgrep|zgrep|rg|ag|ack|ripgrep",
    r"find|fd|locate|which|whereis|type|command|apropos|whatis|man|info|tldr|help",
    r"sort|uniq|cut|paste|join|tr|look|strings|xxd|od|hexdump|hd|csplit|split",
    r"awk|gawk|jq|yq|cut|tee",  # tee/awk are read-ish; writes still caught by redirect/-i checks
    r"echo|printf|true|false|yes|seq|test|expr|sleep|date|cal|env|printenv|set|export",
    # system / process / hardware info
    r"uname|hostname|arch|whoami|id|groups|users|who|w|last|lastlog|finger|tty",
    r"uptime|top|htop|ps|pgrep|pidof|jobs|free|vmstat|iostat|mpstat|sar|nproc|getconf",
    r"lscpu|lsblk|lsusb|lspci|lsmod|lsof|lsattr|lshw|dmidecode|hwinfo|sensors|blkid",
    r"df|du|mount|findmnt|swapon|sysctl|ulimit|locale|localectl|timedatectl|hostnamectl",
    r"systemctl|service|journalctl|dmesg|loginctl",  # status/list forms; write forms caught below
    # networking (read-only) + curl per user request
    r"ping|ping6|traceroute|traceroute6|tracepath|mtr|dig|nslookup|host|whois|getent",
    r"ip|ifconfig|iwconfig|netstat|ss|arp|route|ethtool|nmcli|iw|arping|nmap",
    r"curl|wget",  # download tools; -o/-O writes still caught by redirect check below is not enough, see WRITE_FLAGS
    # dev / version control + package managers (subcommand-filtered below)
    r"git|hg|svn",
    r"npm|pnpm|yarn|pip[0-9.]*|pip3|gem|go|cargo",
    r"docker|podman|kubectl|helm|terraform|vagrant",
    r"brew|apt|apt-get|dpkg|rpm|dnf|yum|pacman|zypper|snap|flatpak|pip",
    r"clear|tput|stty|reset|history|alias|watch|time|nohup|timeout|xargs|nice|ionice",

    r"where|findstr|tasklist|systeminfo|ver|vol|chcp|driverquery|query|qwinsta",
    r"ipconfig|tracert|pathping|getmac|nbtstat|fc|comp|cls|chdir|pushd|popd",
    r"(?:get|test|measure|select|resolve|compare|show|format|group|sort"
    r"|convertfrom|convertto|join|split|where|foreach)-[a-z0-9]+",
    r"gci|gc|gi|gp|gm|gl|gcm|gsv|sls|gal|iwr",
]

_SCRIPTBLOCK_CMDLETS = re.compile(
    r"^(?:where|foreach)-[a-z0-9]+$|^(?:where|foreach)$", re.IGNORECASE
)

_READONLY_RE = re.compile(
    r"^(?:" + "|".join(f"(?:{p})" for p in READONLY_PATTERNS) + r")$",
    re.IGNORECASE,
)

_SUBCOMMAND_READONLY = {
    "git": {"status", "log", "diff", "show", "branch", "remote", "rev-parse",
            "describe", "blame", "ls-files", "ls-tree", "shortlog",
            "config", "cat-file", "reflog", "whatchanged", "grep",
            "count-objects", "fsck", "var", "help", "version", "rev-list",
            "for-each-ref", "symbolic-ref", "check-ignore"},
    "docker": {"ps", "images", "logs", "inspect", "version", "info", "stats",
               "top", "port", "history", "search", "diff"},
    "podman": {"ps", "images", "logs", "inspect", "version", "info", "stats"},
    "kubectl": {"get", "describe", "logs", "top", "version", "explain", "config",
                "cluster-info", "api-resources", "api-versions"},
    "systemctl": {"status", "list-units", "list-unit-files", "is-active",
                  "is-enabled", "is-failed", "show", "cat", "list-timers",
                  "list-sockets", "list-dependencies"},
    "service": {"status"},
    "apt": {"list", "show", "search", "policy"},
    "apt-get": {"--version"},
    "dpkg": {"-l", "-L", "-s", "-S", "--list", "--status", "--search"},
    "rpm": {"-q", "-qa", "-qi", "-ql", "--query"},
    "dnf": {"list", "info", "search", "repolist", "provides"},
    "yum": {"list", "info", "search", "repolist"},
    "pacman": {"-q", "-qi", "-ql", "-ss", "-si", "-q"},
    "brew": {"list", "info", "search", "deps", "outdated", "config", "--version"},
    "pip": {"list", "show", "freeze", "--version", "-V", "check", "config"},
    "pip3": {"list", "show", "freeze", "--version", "-V", "check", "config"},
    "npm": {"ls", "list", "view", "info", "outdated", "--version", "-v", "config", "root", "prefix"},
    "yarn": {"list", "info", "--version", "-v", "why"},
    "go": {"version", "env", "list", "doc", "vet"},
    "cargo": {"--version", "-V", "tree", "search", "metadata"},
    "snap": {"list", "info", "find", "version"},
    "flatpak": {"list", "info", "search", "--version"},
    "hg": {"status", "log", "diff", "branch", "id", "summary", "version"},
    "svn": {"status", "log", "diff", "info", "list", "cat", "--version"},
    "nmcli": {"device", "connection", "general", "networking", "radio"},
}

# Commands that write files via a flag even though the binary "reads".
_WRITE_FLAG = {
    "sed": re.compile(r"(^|\s)-[a-zA-Z]*i"),          # sed -i
    "curl": re.compile(r"(^|\s)(-o|-O|--output|--remote-name)\b"),
    "wget": re.compile(r"(^|\s)(-O|--output-document)\b|.*"),  # wget writes by default
    "tee": re.compile(r".*"),                          # tee always writes
    "awk": re.compile(r'>\s*|system\('),               # awk redirect / system()
    # PowerShell's web client writes a file with -OutFile.
    "iwr": re.compile(r"(^|\s)-outf(ile)?\b", re.IGNORECASE),
    "invoke-webrequest": re.compile(r"(^|\s)-outf(ile)?\b", re.IGNORECASE),
}

_GH_READONLY = {
    ("repo", "view"), ("repo", "list"),
    ("pr", "list"), ("pr", "view"), ("pr", "status"), ("pr", "diff"),
    ("pr", "checks"),
    ("issue", "list"), ("issue", "view"), ("issue", "status"),
    ("run", "list"), ("run", "view"),
    ("release", "list"), ("release", "view"),
    ("workflow", "list"), ("workflow", "view"),
    ("auth", "status"),
    ("search", "repos"), ("search", "issues"), ("search", "prs"),
    ("search", "code"),
    ("gist", "list"), ("gist", "view"),
    ("label", "list"),
    ("browse", "--no-browser"),
    ("status",), ("version",), ("--version",),
}


def _gh_is_readonly(segment: str) -> bool:
    parts = segment.split()[1:]  # drop "gh"
    words = [p for p in parts if not p.startswith("-")] or [
        p for p in parts if p.startswith("-")
    ]
    if not words:
        return False
    if (words[0],) in _GH_READONLY:
        return True
    if len(words) >= 2 and (words[0], words[1]) in _GH_READONLY:
        return True
    return False


_INTERPRETERS = {"python", "python2", "python3", "node", "nodejs", "ruby", "php",
                 "perl", "java", "javac", "rustc", "deno", "bun", "dotnet",
                 "lua", "tclsh", "Rscript"}
_VERSION_FLAGS = {"--version", "-version", "-V", "-v", "--help", "-h", "--info"}

_TMP_RE = re.compile(
    r"(^|[^\w])(/tmp|/var/tmp|/private/tmp)(/|\b)"
    r"|\$TMPDIR|%TEMP%|%TMP%|\$env:te?mp",
    re.IGNORECASE,
)


ALLOW = "allow"
WRITE = "write"
DANGER = "danger"

# always ask, sandbox or not
_DANGER_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(^|\s)(sudo|doas|su|pkexec|runas)\b|-verb\s+runas", re.I),
     "runs with elevated privileges"),
    (re.compile(r"(^|\s)rm\s+(-[a-z]*[rf][a-z]*\s+)+", re.I), "recursive delete"),
    (re.compile(r"(^|\s)(shred|mkfs\S*|fdisk|parted|dd)\b", re.I), "destroys data"),
    (re.compile(r"(^|\s)(chmod|chown|chgrp)\s+(-[a-z]*R|--recursive)\b", re.I),
     "recursive permission change"),
    (re.compile(r"(^|\s)git\s+push\b", re.I), "publishes to a remote"),
    (re.compile(r"(^|\s)git\s+(reset\s+--hard|clean\s+-[a-z]*f|rebase|filter-branch)\b", re.I),
     "rewrites history or discards work"),
    (re.compile(r"(^|\s)gh\s+(repo\s+(create|delete|archive)|pr\s+(merge|close)"
                r"|release\s+(create|delete)|secret\s+set)\b", re.I),
     "changes something on GitHub"),
    (re.compile(r"(curl|wget|iwr|invoke-webrequest)\b[^|]*\|\s*(sudo\s+)?"
                r"(ba|z|k|fi)?sh\b|\|\s*(sudo\s+)?python[0-9.]*\b", re.I),
     "pipes a download straight into a shell"),
    (re.compile(r"(^|\s)(apt|apt-get|dnf|yum|pacman|zypper|brew|snap|flatpak)\s+"
                r"(install|remove|purge|upgrade|update)\b", re.I),
     "changes system packages"),
    (re.compile(r"(^|\s)(npm|pnpm|yarn)\s+(install|add|i)\b[^|;&]*\s-g\b|"
                r"(^|\s)(npm|pnpm|yarn)\s+publish\b", re.I),
     "installs globally or publishes"),
    (re.compile(r"(^|\s)(reboot|shutdown|halt|poweroff|init)\b", re.I), "halts the machine"),
    (re.compile(r"(^|\s)(kill|pkill|killall)\b", re.I), "kills processes"),
    (re.compile(r"(^|\s)systemctl\s+(?!status|list|is-|show|cat)", re.I),
     "changes a system service"),
    (re.compile(r"(^|\s)(crontab|at|schtasks)\b", re.I), "schedules background work"),
]


@dataclass
class Decision:
    verdict: str
    reason: str
    touches_tmp: bool

    @property
    def allowed(self) -> bool:
        """True when the command needs no gate at all."""
        return self.verdict == ALLOW


def danger(command: str) -> str | None:
    for pattern, reason in _DANGER_RULES:
        if pattern.search(command):
            return reason
    return None


def touches_tmp(command: str) -> bool:
    return bool(_TMP_RE.search(command))


def _first_token(segment: str) -> str:
    segment = segment.strip()
    m = re.match(r"[A-Za-z0-9_./-]+", segment)
    return (m.group(0).rsplit("/", 1)[-1] if m else "").lower()


def _second_token(segment: str) -> str:
    parts = segment.strip().split()
    return parts[1].lower() if len(parts) > 1 else ""


def _segment_is_readonly(segment: str) -> bool:
    segment = segment.strip()
    if not segment:
        return True
    tok = _first_token(segment)
    if not tok:
        return False
    # PowerShell script block: `... | Where-Object { Remove-Item $_ }` reads as
    # a harmless cmdlet but can hold anything. If there's a brace, ask.
    if "{" in segment and _SCRIPTBLOCK_CMDLETS.match(tok):
        return False
    # GitHub CLI: only read-only command pairs
    if tok == "gh":
        return _gh_is_readonly(segment)
    # interpreters: only version/help forms are read-only
    if tok in _INTERPRETERS or re.fullmatch(r"python[0-9.]+", tok):
        return _second_token(segment) in _VERSION_FLAGS
    # write-by-flag commands
    if tok in _WRITE_FLAG and _WRITE_FLAG[tok].search(segment):
        return False
    # subcommand-gated tools
    if tok in _SUBCOMMAND_READONLY:
        sub = _second_token(segment)
        return sub in _SUBCOMMAND_READONLY[tok] or (
            sub.startswith("-") and sub in _SUBCOMMAND_READONLY[tok]
        )
    return bool(_READONLY_RE.match(tok))


def classify(command: str) -> Decision:
    cmd = command.strip()
    tmp = touches_tmp(cmd)

    reason = danger(cmd)
    if reason:
        return Decision(DANGER, reason, tmp)

    # command substitution can hide arbitrary writes
    if "`" in cmd or "$(" in cmd:
        return Decision(WRITE, "uses command substitution", tmp)

    # write redirections (allow only to the null/std devices)
    for m in re.finditer(r"\d*>>?|>&|&>", cmd):
        after = cmd[m.end():].lstrip()
        target = after.split()[0] if after else ""
        if target not in ("/dev/null", "/dev/stdout", "/dev/stderr", "&1", "&2", "/dev/tty"):
            return Decision(WRITE, "writes to a file (redirection)", tmp)

    # split on chains and pipes; every segment must be read-only
    segments = re.split(r"\|\||&&|;|\||&(?!>)", cmd)
    for seg in segments:
        if not _segment_is_readonly(seg):
            tok = _first_token(seg)
            return Decision(WRITE, f"'{tok or seg.strip()}' may change the system", tmp)

    return Decision(ALLOW, "", tmp)
