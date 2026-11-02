"""Shared helpers for the tests. Everything runs offline: fixtures are real captures
(2026-11-02) of the free sources, and broker HTTP is mocked."""

import importlib.util
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")


def load(folder, name):
    """Import a skill script by path (the folder names have hyphens)."""
    d = os.path.join(ROOT, folder)
    if d not in sys.path:
        sys.path.insert(0, d)
    path = os.path.join(d, name + ".py")
    spec = importlib.util.spec_from_file_location("trader_%s_%s" % (folder.replace("-", "_"), name), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fix(*parts):
    return os.path.join(FIX, *parts)


def run(folder, script, args, cwd=None, env=None):
    """Run a skill script as the user would. Returns (exit code, stdout, stderr)."""
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    for k in ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET"):
        e.pop(k, None)
    if env:
        e.update(env)
    p = subprocess.run([sys.executable, os.path.join(ROOT, folder, script)] + list(args), cwd=cwd,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=e, timeout=120)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def run_json(folder, script, args, cwd=None):
    code, out, err = run(folder, script, list(args) + ["--json"], cwd=cwd)
    try:
        return code, json.loads(out), err
    except ValueError:
        raise AssertionError("not JSON (exit %d): %s %s" % (code, out[:500], err[:500]))


def jdump(doc, *parts):
    path = os.path.join(*parts)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return path


def jload(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return json.load(fh)
