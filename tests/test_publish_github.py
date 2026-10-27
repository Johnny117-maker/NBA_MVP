import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or shutil.which("git") is None,
    reason="O publicador BAT requer Windows e Git.",
)
BRANCH = "feature/test-publish"


@pytest.fixture
def publishing_repo(tmp_path):
    work = tmp_path / "work"
    remote = tmp_path / "remote.git"
    work.mkdir()
    environment = os.environ.copy()
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")

    def git(path, *args, check=True):
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=environment,
        )
        if check:
            assert result.returncode == 0, result.stderr
        return result

    git(tmp_path, "init", "--bare", str(remote))
    git(work, "init", "-b", BRANCH)
    git(work, "config", "user.name", "Publish Test")
    git(work, "config", "user.email", "publish@example.invalid")
    git(work, "config", "commit.gpgsign", "false")
    source = Path(__file__).resolve().parents[1] / "PUBLICAR_GITHUB.bat"
    shutil.copyfile(source, work / source.name)
    (work / "a.txt").write_text("base", encoding="utf-8")
    (work / "b.txt").write_text("base", encoding="utf-8")
    git(work, "add", ".")
    git(work, "commit", "-m", "base")
    git(work, "remote", "add", "origin", str(remote))

    def publish(message="Testa publicacao incremental"):
        return subprocess.run(
            ["cmd.exe", "/d", "/c", str(work / source.name)],
            input=message + "\n\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=environment,
        )

    return work, remote, git, publish


def test_bat_preserves_branch_and_only_commits_staged_files(publishing_repo):
    work, remote, git, publish = publishing_repo
    (work / "a.txt").write_text("changed", encoding="utf-8")
    (work / "b.txt").write_text("not staged", encoding="utf-8")
    git(work, "add", "a.txt")
    result = publish()
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(work, "branch", "--show-current").stdout.strip() == BRANCH
    assert git(work, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.strip() == "a.txt"
    assert "b.txt" in git(work, "status", "--short").stdout
    assert git(work, "rev-parse", "HEAD").stdout == git(remote, "rev-parse", f"refs/heads/{BRANCH}").stdout


def test_bat_keeps_local_commit_and_refuses_to_overwrite_new_remote_commits(publishing_repo):
    work, remote, git, publish = publishing_repo
    git(work, "push", "origin", BRANCH)
    peer = work.parent / "peer"
    git(work.parent, "clone", "-b", BRANCH, str(remote), str(peer))
    git(peer, "config", "user.name", "Publish Test")
    git(peer, "config", "user.email", "publish@example.invalid")
    git(peer, "config", "commit.gpgsign", "false")
    (peer / "a.txt").write_text("remote change", encoding="utf-8")
    git(peer, "add", "a.txt")
    git(peer, "commit", "-m", "remote change")
    git(peer, "push", "origin", BRANCH)
    remote_head = git(remote, "rev-parse", f"refs/heads/{BRANCH}").stdout
    (work / "b.txt").write_text("local change", encoding="utf-8")
    result = publish()
    assert result.returncode != 0
    assert "Seus commits locais permanecem salvos" in result.stdout
    assert git(work, "log", "-1", "--format=%s").stdout.strip() == "Testa publicacao incremental"
    assert git(remote, "rev-parse", f"refs/heads/{BRANCH}").stdout == remote_head


def test_bat_stops_before_staging_unresolved_merge_conflicts(publishing_repo):
    work, _, git, publish = publishing_repo
    base = git(work, "rev-parse", "HEAD").stdout.strip()
    (work / "a.txt").write_text("first change", encoding="utf-8")
    git(work, "add", "a.txt")
    git(work, "commit", "-m", "first change")
    git(work, "checkout", "-b", "other", base)
    (work / "a.txt").write_text("second change", encoding="utf-8")
    git(work, "add", "a.txt")
    git(work, "commit", "-m", "second change")
    git(work, "checkout", BRANCH)
    assert git(work, "merge", "other", check=False).returncode != 0
    result = publish()
    assert result.returncode != 0
    assert "Existem conflitos de merge pendentes" in result.stdout
    assert git(work, "ls-files", "--unmerged").stdout
