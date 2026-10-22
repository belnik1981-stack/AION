"""Install and operate two isolated AION checkouts through Termux:Widget.

This file is copied outside both repositories. MASTER needs no source changes.
Only the Python standard library is required by the controller itself.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import getpass
import hmac
import html
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import URLError
from urllib.request import Request, ProxyHandler, build_opener


REPOSITORY = "https://github.com/belnik1981-stack/AION.git"
MARKER = "aion-termux-widget-v1"
SHORTCUT_MARKER = "# Managed by AION Termux Widget v1"
VARIANTS = {"master": "MASTER", "test": "TEST PR"}
EXCLUDED_SETTINGS = {
    "AION_PYTHON", "AION_BOOTSTRAP_PYTHON", "AION_PROBE_PYTHON",
    "AION_ACCEPTANCE_PYTHON", "AION_TEST_VENV_DIR", "AION_ACCEPTANCE_VENV_DIR",
    "AION_TEST_REPORT_DIR", "AION_EXPECTED_SHA", "AION_LIVE_TEST",
}


class WidgetError(RuntimeError):
    pass


def run(args, cwd=None, env=None):
    """Keep remote URLs, provider errors and configuration out of diagnostics."""
    result = subprocess.run(args, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        reason = "check access, dependencies and paths"
        if "CONNECT tunnel failed, response 403" in result.stderr:
            reason = "network proxy denied GitHub access (HTTP 403)"
        elif "CONFLICT" in result.stdout:
            reason = "PR conflicts with current master; preview was not installed"
        raise WidgetError(f"Command failed: {Path(str(args[0])).name} (exit {result.returncode}): {reason}. "
                          "Existing repository files were preserved.")
    return result.stdout.strip()


def git(repo, *args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    return run(["git", "-C", str(repo), *args], env=env)


def write_private(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".aion-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    write_private(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path):
    return json.loads(path.read_text())


def layout(home):
    home = home.expanduser().resolve()
    return home, home / ".local/share/aion-widget", home / ".config/aion-widget/runtime.json"


@contextlib.contextmanager
def locked(home):
    _, data, _ = layout(home)
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (data / "controller.lock").open("a") as stream:
        os.chmod(stream.name, 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def local_request(port, path, token=None, timeout=3):
    headers = {"X-AION-Widget-Token": token} if token else {}
    request = Request(f"http://127.0.0.1:{port}{path}", headers=headers,
                      method="POST" if token else "GET")
    # Loopback stays local even when a caller configured an HTTP proxy.
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        return response.status, response.read(1024 * 1024), response.headers


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def current_status(port):
    try:
        status, body, _ = local_request(port, "/__aion_widget/status")
        value = json.loads(body)
        if status == 200 and isinstance(value, dict) and value.get("managed_by") == MARKER:
            return value
    except (OSError, ValueError, URLError):
        pass
    return None


def wait_ready(port, expected, process=None, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise WidgetError("AION exited at startup; see the private launcher log.")
        status = current_status(port)
        if status and all(status.get(key) == expected[key]
                          for key in ("session", "repo", "variant", "pid")):
            code, body, _ = local_request(port, "/")
            if code == 200 and b"AION Control Panel" in body and expected["variant"].encode() in body:
                return status
        time.sleep(0.1)
    raise WidgetError("AION did not pass the HTTP readiness check.")


def legacy_identity(pid, repos, port):
    """Identify an old python server.py by exact path AND its listening socket.

    Android can restrict /proc. Missing evidence means refusal, never pkill.
    """
    proc = Path("/proc") / str(pid)
    try:
        if proc.stat().st_uid != os.getuid():
            return False
        argv = [p.decode() for p in (proc / "cmdline").read_bytes().split(b"\0") if p]
        if not argv or not re.fullmatch(r"python(?:3(?:\.\d+)?)?", Path(argv[0]).name):
            return False
        args = argv[1:]
        if args and args[0] == "-u":
            args = args[1:]
        if len(args) != 1:
            return False
        script = Path(args[0])
        script = script if script.is_absolute() else (proc / "cwd").resolve() / script
        if script.resolve() not in {repo.resolve() / "server.py" for repo in repos}:
            return False
        inodes = set()
        for table in ("tcp", "tcp6"):
            for line in (proc / "net" / table).read_text().splitlines()[1:]:
                fields = line.split()
                if int(fields[1].split(":")[1], 16) == port and fields[3] == "0A":
                    inodes.add("socket:[" + fields[9] + "]")
        return any(os.readlink(fd) in inodes for fd in (proc / "fd").iterdir())
    except (OSError, ValueError, IndexError, UnicodeError):
        return False


def stop_previous(home, config):
    _, data, _ = layout(home)
    port = config["port"]
    if not listening(port):
        return
    status = current_status(port)
    state_file = data / "current.json"
    if status and state_file.exists():
        state = read_json(state_file)
        if all(status.get(key) == state.get(key) for key in ("session", "repo", "pid", "variant")):
            local_request(port, "/__aion_widget/stop", state["token"], timeout=35)
        else:
            raise WidgetError(f"Port {port} belongs to another launcher instance; nothing was stopped.")
    else:
        # pidfds prevent a recycled PID from ever receiving the signal.
        candidates = []
        if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
            for proc in Path("/proc").iterdir():
                if proc.name.isdigit() and legacy_identity(int(proc.name),
                        [Path(item["repo"]) for item in config["variants"].values()], port):
                    candidates.append(int(proc.name))
        if len(candidates) != 1:
            raise WidgetError("Port is occupied by an unverified process. Nothing was stopped. "
                              "For a legacy AION terminal, press Ctrl+C there once and retry.")
        try:
            fd = os.pidfd_open(candidates[0])
            try:
                if not legacy_identity(candidates[0],
                        [Path(item["repo"]) for item in config["variants"].values()], port):
                    raise WidgetError("Legacy process identity changed; nothing was stopped.")
                signal.pidfd_send_signal(fd, signal.SIGTERM)
            finally:
                os.close(fd)
        except OSError as exc:
            raise WidgetError("Android cannot safely stop this legacy process; use Ctrl+C in its terminal.") from exc
    deadline = time.monotonic() + 35
    while listening(port) and time.monotonic() < deadline:
        time.sleep(0.1)
    if listening(port):
        raise WidgetError("Previous server is still busy; no replacement was started.")


def runtime_env(config):
    env = os.environ.copy()
    # Widget launches do not inherit variables exported in another terminal.
    env.update(config["settings"])
    env["AION_FREE_ONLY"] = "1"
    env.pop("AION_LIVE_TEST", None)
    return env


def validate_runtime(item, config):
    env = runtime_env(config)
    models = [env.get("AION_MODEL", "openrouter/free")]
    models.extend(m.strip() for m in env.get("AION_MODELS", "").split(",") if m.strip())
    if (env.get("AION_API_URL", "https://openrouter.ai/api/v1").rstrip("/")
            != "https://openrouter.ai/api/v1" or any(
                m != "openrouter/free" and not m.endswith(":free") for m in models)):
        raise WidgetError("Widget comparison permits only the OpenRouter endpoint and free model IDs. "
                          "Existing settings were not overwritten.")
    if not env.get("AION_API_KEY") and not config["allow_offline"]:
        raise WidgetError("AION_API_KEY is missing; rerun the installer in a terminal with the existing key.")
    # Import/render before stopping the previous version. No provider requests.
    code = ("import server; server.get_execution_limits(); "
            "from core.llm import llm_status; "
            "assert llm_status().get('status') == 'ok'")
    if config["allow_offline"] and not env.get("AION_API_KEY"):
        code = "import server; server.get_execution_limits()"
    run([item["python"], "-B", "-c", code], cwd=item["repo"], env=env)
    return env


def start(home, variant, browser=True):
    with locked(home):
        home, data, config_file = layout(home)
        config = read_json(config_file)
        item = config["variants"][variant]
        env = validate_runtime(item, config)
        stop_previous(home, config)
        session, token = secrets.token_hex(16), secrets.token_hex(32)
        env["AION_WIDGET_TOKEN"] = token
        env["AION_WIDGET_SESSION"] = session
        log_path = data / (variant + ".log")
        fd = os.open(log_path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as log:
            process = subprocess.Popen([item["python"], "-B", str(data / "launcher.py"),
                "--home-dir", str(home), "serve", variant], cwd=item["repo"], env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True)
        state = {"session": session, "token": token, "repo": item["repo"],
                 "pid": process.pid, "variant": VARIANTS[variant]}
        write_json(data / "current.json", state)
        try:
            wait_ready(config["port"], state, process)
        except Exception:
            if process.poll() is None:
                process.terminate()  # Only the child just created by this call.
                process.wait(timeout=5)
            raise
        print(f"[PASS] AION {VARIANTS[variant]} — HTTP 200; port {config['port']}")
        if browser:
            opener = shutil.which("termux-open-url")
            if opener:
                result = subprocess.run([opener, f"http://127.0.0.1:{config['port']}"])
                if result.returncode:
                    raise WidgetError("AION is running, but Android refused to open the browser.")
            else:
                print("[ANDROID CHECK REQUIRED] termux-open-url is unavailable on this host.")


def serve(home, variant):
    home, _, config_file = layout(home)
    config = read_json(config_file)
    item = config["variants"][variant]
    sys.path.insert(0, item["repo"])
    import server
    from http.server import HTTPServer
    label = VARIANTS[variant]
    commit = git(item["repo"], "rev-parse", "HEAD")[:12]
    dirty = bool(git(item["repo"], "status", "--porcelain", "--untracked-files=no"))
    original_render = server.render_home
    detail = f"AION {label} | commit {commit}"
    if variant == "test":
        detail += f" | PR #{config['pr']} | merge preview {item['tree'][:12]}"
    if dirty:
        detail += " | local changes"

    def render():
        page = original_render()
        return page.replace("<title>AION Interactive Control</title>",
                            "<title>" + html.escape(detail) + "</title>").replace(
            "<h2>AION Control Panel</h2>",
            "<h2>AION Control Panel</h2><div class=\"card\"><strong>" +
            html.escape(detail) + "</strong></div>")

    server.render_home = render
    identity = {"managed_by": MARKER, "variant": label, "repo": item["repo"],
                "pid": os.getpid(), "session": os.environ["AION_WIDGET_SESSION"],
                "commit": commit, "dirty": dirty}
    token = os.environ.pop("AION_WIDGET_TOKEN")

    class Handler(server.AionHandler):
        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_GET(self):
            if self.path == "/__aion_widget/status":
                payload = json.dumps(identity).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                super().do_GET()

        def do_POST(self):
            if self.path != "/__aion_widget/stop":
                return super().do_POST()
            if not hmac.compare_digest(self.headers.get("X-AION-Widget-Token", "").encode(), token.encode()):
                self.send_response(403)
                self.end_headers()
                return
            self.send_response(204)
            self.end_headers()
            threading.Thread(target=httpd.shutdown, daemon=True).start()

    with HTTPServer(("127.0.0.1", config["port"]), Handler) as httpd:
        print("[AION WIDGET]", detail, flush=True)
        httpd.serve_forever(poll_interval=0.1)


def same_remote(actual, expected):
    def normal(value):
        return value.removeprefix("https://").removeprefix("git@github.com:").rstrip("/").removesuffix(".git")
    if actual.startswith("git@github.com:"):
        actual = "https://github.com/" + actual.split(":", 1)[1]
    return normal(actual) == normal(expected)


def configuration(home, config_file, args):
    previous = read_json(config_file) if config_file.exists() else {}
    settings = dict(previous.get("settings", {}))
    if args.config_file:
        # Explicit path only; dotenv data is parsed, NEVER executed as shell.
        for line in args.config_file.read_text().splitlines():
            line = line.strip().removeprefix("export ")
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if sep and re.fullmatch(r"AION_[A-Z0-9_]+", key.strip()) and key.strip() not in EXCLUDED_SETTINGS:
                parsed = shlex.split(value, comments=True)
                if len(parsed) > 1:
                    raise WidgetError("Configuration values containing spaces must be quoted.")
                settings[key.strip()] = parsed[0] if parsed else ""
    for key, value in os.environ.items():
        if re.fullmatch(r"AION_[A-Z0-9_]+", key) and key not in EXCLUDED_SETTINGS and not key.startswith("AION_WIDGET_"):
            settings[key] = value
    if not settings.get("AION_API_KEY") and not args.offline:
        if not sys.stdin.isatty():
            raise WidgetError("AION_API_KEY is absent. Run interactively to enter it securely, "
                              "or export the existing key before installation.")
        settings["AION_API_KEY"] = getpass.getpass("Existing OpenRouter API key (hidden): ")
        if not settings["AION_API_KEY"]:
            raise WidgetError("No key supplied; existing installation was preserved.")
    return {"managed_by": MARKER, "pr": args.pr, "port": args.port,
            "allow_offline": args.offline, "settings": settings}


def prepare_python(data, name, repo, args):
    # Test/developer override avoids changing a preinstalled external Python.
    if args.runtime_python:
        # Resolving a venv's symlink would silently select the system Python.
        python = str(args.runtime_python.expanduser().absolute())
        run([python, "-c", "import yaml"])
        return python
    venv = data / "venvs" / name
    python = str(venv / "bin/python")
    if not Path(python).exists():
        run([sys.executable, "-m", "venv", str(venv)])
    try:
        run([python, "-m", "pip", "--version"])
    except WidgetError:
        run([python, "-m", "ensurepip", "--upgrade"])
    run([python, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(repo / "requirements-core.txt")])
    run([python, "-m", "pip", "check"])
    return python


def resolve_pr(repository, branch):
    refs = run(["git", "ls-remote", repository, f"refs/heads/{branch}", "refs/pull/*/head"])
    pairs = [line.split() for line in refs.splitlines()]
    head = next((sha for sha, ref in pairs if ref == f"refs/heads/{branch}"), None)
    matches = [int(ref.split("/")[2]) for sha, ref in pairs
               if sha == head and re.fullmatch(r"refs/pull/[0-9]+/head", ref)]
    if len(matches) != 1:
        raise WidgetError("Cannot uniquely find an open PR ref for the selected branch; specify --pr NUMBER.")
    return matches[0]


def live_test_variant(item, config, report):
    """Test copied source, never the real checkouts' Truth or runtime memory."""
    env = validate_runtime(item, config)
    if not env.get("AION_API_KEY"):
        raise WidgetError("Live test requires the existing AION_API_KEY.")
    report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="aion-live-widget-") as temporary:
        root = Path(temporary)
        for relative in git(item["repo"], "ls-files", "-z").split("\0"):
            if not relative:
                continue
            source = Path(item["repo"]) / relative
            if source.is_symlink():
                raise WidgetError("Live snapshot refuses source symlinks.")
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        env["AION_PROBE_PYTHON"] = item["python"]
        with report.open("w") as log:
            os.chmod(report, 0o600)
            result = subprocess.run(["bash", "scripts/live_two_model_probe.sh"], cwd=root,
                                    env=env, stdout=log, stderr=subprocess.STDOUT)
    text = report.read_text()
    passed = result.returncode == 0 and "[PASS] MULTI MODEL PIPELINE" in text
    print("[LIVE]", "PASS" if passed else "FAIL", "report:", report)
    return passed


def save_verified_pair(config_file, report):
    """Populate an unset model pair only after real two-model pipeline success."""
    config = read_json(config_file)
    if config["settings"].get("AION_MODELS"):
        return
    match = re.search(r"^\[PASS\] TWO DISTINCT MODEL IDS: (.+)$", report.read_text(), re.M)
    pair = [value.strip() for value in match.group(1).split(",")] if match else []
    if (len(pair) != 2 or len(set(pair)) != 2 or
            len({value.split("/", 1)[0] for value in pair}) != 2 or
            any(not re.fullmatch(r"[A-Za-z0-9_.:/-]+:free", value) for value in pair)):
        raise WidgetError("Live report did not provide an eligible explicit two-model pair.")
    config["settings"]["AION_MODELS"] = ",".join(pair)
    # Keep an explicit user's single-model choice. New setups use the verified first model.
    config["settings"].setdefault("AION_MODEL", pair[0])
    write_json(config_file, config)
    print("[PASS] Verified two-model pair saved for both widget commands.")


def shortcut_plan(home, data):
    directory = home / ".shortcuts"
    directory.mkdir(mode=0o700, exist_ok=True)
    # An existing directory may lack owner read/execute permission: Widget
    # then hides the scripts even when the files themselves are executable.
    directory.chmod(stat.S_IMODE(directory.stat().st_mode) | 0o700)
    scripts = {}
    bash = shutil.which("bash")
    if not bash:
        raise WidgetError("Bash is required.")
    for variant, label in VARIANTS.items():
        target = directory / ("AION " + label)
        if target.is_symlink() or (target.exists() and SHORTCUT_MARKER not in target.read_text()
                                   and not legacy_shortcut(target)):
            raise WidgetError(f"Shortcut {target.name} already exists and is not managed; it was preserved.")
        command = shlex.join([sys.executable, str(data / "launcher.py"), "--home-dir", str(home), "start", variant])
        scripts[target] = f"#!{bash}\n{SHORTCUT_MARKER}\nexec {command}\n"
    return scripts


def legacy_shortcut(path):
    names = {"AION", "aion", "AION.sh", "aion.sh", "start_aion.sh", "AION MASTER", "AION TEST PR"}
    if path.name not in names or path.is_symlink() or not path.is_file():
        return False
    text = path.read_text(errors="replace")
    launch = re.search(
        r"(?:^|;)\s*(?:exec\s+)?(?:python(?:3(?:\.\d+)?)?|bash|sh)\s+"
        r"(?:-u\s+)?[^\n;]*(?:start_app\.sh|server\.py)(?=[\"'\s;]|$)", text, re.M)
    direct = re.search(
        r"(?:^|;)\s*(?:exec\s+)?[\"']?(?:\./|\$HOME/|\$\{HOME\}/|~/|/)"
        r"[^\n;]*start_app\.sh[\"']?(?=\s|$)", text, re.M)
    return "AION" in text and bool(launch or direct)


def retire_old_shortcuts(home, data):
    for directory in (home / ".shortcuts", home / ".shortcuts/tasks"):
        if not directory.is_dir():
            continue
        for old in directory.iterdir():
            if not legacy_shortcut(old):
                continue
            backup = data / "shortcut-backups" / secrets.token_hex(8)
            backup.mkdir(parents=True, mode=0o700)
            old.rename(backup / old.name)
            print("[ARCHIVED AION SHORTCUT]", old.name)


def refresh_widgets():
    """Use Termux:Widget's documented refresh broadcast, not a launcher guess."""
    am = shutil.which("am")
    if am and os.environ.get("TERMUX_VERSION"):
        result = subprocess.run([am, "broadcast", "-n", "com.termux.widget/.TermuxWidgetProvider",
            "-a", "com.termux.widget.ACTION_REFRESH_WIDGET", "--ei", "appWidgetId", "0"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            print("[ANDROID] Widget refresh requested. Confirm AION MASTER and AION TEST PR on the phone.")
            return True
    print("[ANDROID ACTION] Open Termux:Widget and press REFRESH to reload the script list.")
    return False


def repair_widget(home):
    """Repair only managed shortcuts. Never stop AION or display/export API values."""
    with locked(home):
        home, data, config_file = layout(home)
        if not config_file.is_file() or not (data / "launcher.py").is_file():
            raise WidgetError("Widget installation is incomplete: installed launcher/configuration is missing. "
                              "Run scripts/install_termux_widget.sh --pr 45 --verify first.")
        config = read_json(config_file)
        if config.get("managed_by") != MARKER:
            raise WidgetError("Existing widget configuration is not managed by AION; it was preserved.")
        for variant in VARIANTS:
            item = config["variants"][variant]
            if not (Path(item["repo"]) / "server.py").is_file() or not os.access(item["python"], os.X_OK):
                raise WidgetError("AION checkout or its Python is missing; complete installation first.")
        scripts = shortcut_plan(home, data)
        retire_old_shortcuts(home, data)
        for target, content in scripts.items():
            write_private(target, content)
            target.chmod(0o700)
            print("[PASS]", target.name, "executable shortcut exists")
        refresh_widgets()
        print("[PASS] Shortcut repair complete. Running AION, both repositories and provider settings were preserved.")


def install(home, args):
    if sys.version_info < (3, 10):
        raise WidgetError("Python 3.10+ is required.")
    if not shutil.which("git"):
        raise WidgetError("Git is required (Termux: pkg install git python).")
    with locked(home):
        home, data, config_file = layout(home)
        master, test = home / "AION", home / "AION-PR-test"
        if master.is_symlink() or test.is_symlink():
            raise WidgetError("Checkout symlinks are not replaced; use real independent directories.")
        if master.exists():
            if not same_remote(git(master, "remote", "get-url", "origin"), args.repository):
                raise WidgetError("Existing ~/AION has another origin; nothing was changed.")
            if git(master, "branch", "--show-current") != "master":
                raise WidgetError("Existing ~/AION is not on master; switch it yourself when safe. "
                                  "Installer will not alter its branch or files.")
        scripts = shortcut_plan(home, data)
        config = configuration(home, config_file, args)
        # Everything is prepared away from the working instance. No server is stopped.
        with tempfile.TemporaryDirectory(prefix="install-", dir=data) as temporary:
            staging = Path(temporary)
            reference, preview = staging / "master", staging / "test"
            run(["git", "clone", "--quiet", "--branch", "master", "--single-branch", args.repository, str(reference)])
            base = git(reference, "rev-parse", "HEAD")
            run(["git", "clone", "--quiet", "--no-hardlinks", str(reference), str(preview)])
            git(preview, "remote", "set-url", "origin", args.repository)
            git(preview, "fetch", "--quiet", "origin", f"refs/pull/{args.pr}/head")
            head = git(preview, "rev-parse", "FETCH_HEAD")
            git(preview, "-c", "user.name=AION PR preview", "-c", "user.email=aion-preview@localhost",
                "merge", "--no-commit", "--no-ff", "--no-edit", head)
            tree = git(preview, "write-tree")
            manifest = {"managed_by": MARKER, "pr": args.pr, "base": base, "head": head, "tree": tree}
            if test.exists():
                marker_file = test / ".git/aion-widget-preview.json"
                if (not marker_file.is_file() or read_json(marker_file) != manifest or
                        git(test, "write-tree") != tree or git(test, "diff", "--name-only")):
                    raise WidgetError("Existing ~/AION-PR-test differs from this merge preview. "
                                      "It was preserved. Stop TEST PR and move that directory to a backup before reinstalling.")
            master_source = master if master.exists() else reference
            test_source = test if test.exists() else preview
            config["variants"] = {
                "master": {"repo": str(master), "python": prepare_python(data, "master", master_source, args)},
                "test": {"repo": str(test), "python": prepare_python(data, "test", test_source, args), "tree": tree},
            }
            for key, source in (("master", master_source), ("test", test_source)):
                temporary_item = dict(config["variants"][key], repo=str(source))
                validate_runtime(temporary_item, config)
            if args.verify:
                reports = data / "install-reports" / secrets.token_hex(6)
                reports.mkdir(parents=True, mode=0o700)
                env = runtime_env(config)
                env.pop("AION_API_KEY", None)
                env.update(AION_LIVE_TEST="0", AION_TEST_VENV_DIR=str(Path(config["variants"]["test"]["python"]).parent.parent),
                           AION_TEST_REPORT_DIR=str(reports))
                with (reports / "cloud-check.log").open("w") as log:
                    result = subprocess.run(["bash", "scripts/cloud_check.sh"], cwd=test_source, env=env,
                                            stdout=log, stderr=subprocess.STDOUT)
                if result.returncode:
                    raise WidgetError(f"Offline verification failed; see {reports}/cloud-check.log. Running AION was not stopped.")
                print("[PASS] TEST PR offline cloud_check; report:", reports)
            if not master.exists():
                reference.rename(master)
                git(master, "remote", "set-url", "origin", args.repository)
            if not test.exists():
                write_json(preview / ".git/aion-widget-preview.json", manifest)
                preview.rename(test)
        write_private(data / "launcher.py", Path(__file__).read_text())
        write_json(config_file, config)
        retire_old_shortcuts(home, data)
        for target, content in scripts.items():
            write_private(target, content)
            target.chmod(0o700)
        print("[PASS] Installed AION MASTER and AION TEST PR. No running server was stopped.")
        print("[MASTER] preserved:", master, "commit", git(master, "rev-parse", "--short", "HEAD"))
        print("[TEST PR] base", base[:12], "PR head", head[:12], "merge tree", tree[:12])
        if git(master, "rev-parse", "HEAD") != base:
            print("[NOTE] Existing MASTER differs from current remote master; it was deliberately not updated.")
        print("[CONFIG] private file:", config_file, "(key never printed)")
        refresh_widgets()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home-dir", type=Path, default=Path.home())
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("install")
    setup.add_argument("--pr", required=True, help="GitHub PR number, or auto")
    setup.add_argument("--pr-branch", default="feat/termux-widget-dual-launch")
    setup.add_argument("--repository", default=REPOSITORY)
    setup.add_argument("--port", type=int, default=8080)
    setup.add_argument("--config-file", type=Path)
    setup.add_argument("--offline", action="store_true", help="Allow keyless installation; live verification needs --verify-live")
    setup.add_argument("--verify", action="store_true", help="Offline check of merge preview; does not stop AION")
    setup.add_argument("--verify-live", action="store_true", help="Explicit free-only two-model trial in an isolated source snapshot")
    setup.add_argument("--runtime-python", type=Path, help="Use an existing interpreter without installing dependencies")
    for command in ("start", "serve"):
        sub = commands.add_parser(command)
        sub.add_argument("variant", choices=VARIANTS)
        if command == "start":
            sub.add_argument("--no-browser", action="store_true")
    commands.add_parser("status")
    commands.add_parser("stop")
    commands.add_parser("repair-widget", help="Restore the two widget commands without changing or stopping AION")
    live = commands.add_parser("live-test")
    live.add_argument("variant", choices=VARIANTS)
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            args.pr = resolve_pr(args.repository, args.pr_branch) if args.pr == "auto" else int(args.pr)
            if args.pr < 1 or not 1024 <= args.port <= 65535:
                raise WidgetError("Invalid PR number or port.")
            install(args.home_dir, args)
            if args.verify_live:
                _, data, config_file = layout(args.home_dir)
                config = read_json(config_file)
                report = data / "live-reports" / ("install-" + secrets.token_hex(6) + ".log")
                if not live_test_variant(config["variants"]["test"], config, report):
                    return 1
                save_verified_pair(config_file, report)
        elif args.command == "start":
            start(args.home_dir, args.variant, not args.no_browser)
        elif args.command == "serve":
            serve(args.home_dir, args.variant)
        elif args.command == "repair-widget":
            repair_widget(args.home_dir)
        elif args.command == "status":
            config = read_json(layout(args.home_dir)[2])
            status = current_status(config["port"])
            if not status:
                raise WidgetError("No managed AION server is running.")
            print(json.dumps(status, ensure_ascii=False, indent=2))
        elif args.command == "live-test":
            _, data, config_file = layout(args.home_dir)
            config = read_json(config_file)
            report = data / "live-reports" / (args.variant + "-" + secrets.token_hex(6) + ".log")
            if not live_test_variant(config["variants"][args.variant], config, report):
                return 1
            save_verified_pair(config_file, report)
        else:
            with locked(args.home_dir):
                stop_previous(args.home_dir, read_json(layout(args.home_dir)[2]))
                print("[PASS] AION stopped; unrelated processes were not signalled.")
        return 0
    except (WidgetError, OSError, ValueError, KeyError, URLError):
        # Do not echo raw exceptions: provider URLs/configuration may contain secrets.
        exc = sys.exception() if hasattr(sys, "exception") else sys.exc_info()[1]
        message = str(exc) if isinstance(exc, WidgetError) else "Operation failed; check paths, permissions and local service availability."
        print("[FAIL]", message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
