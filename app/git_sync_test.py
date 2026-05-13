import subprocess
from pathlib import Path

import pytest

from app.git_sync import GitSync


@pytest.fixture
def source_repo(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "monitor.py").write_text(
        'from app.helpers import Monitor\n'
        'monitor = Monitor(name="remote", schedule="* * * * *", notify_channels=[])\n'
        '@monitor.check\nasync def check(page, ctx): pass\n'
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def test_authenticated_url_injects_token():
    gs = GitSync(repo_url="https://git.example.com/org/repo.git", clone_path=Path("/tmp/x"), token="mytoken")
    assert gs._authenticated_url() == "https://mytoken@git.example.com/org/repo.git"


def test_authenticated_url_no_token_unchanged():
    gs = GitSync(repo_url="https://git.example.com/org/repo.git", clone_path=Path("/tmp/x"), token="")
    assert gs._authenticated_url() == "https://git.example.com/org/repo.git"


async def test_sync_clones_on_first_call(source_repo, tmp_path):
    clone_path = tmp_path / "clone"
    gs = GitSync(repo_url=str(source_repo), clone_path=clone_path, token="")
    await gs.sync()
    assert (clone_path / "monitor.py").exists()


async def test_sync_pulls_on_subsequent_call(source_repo, tmp_path):
    clone_path = tmp_path / "clone"
    gs = GitSync(repo_url=str(source_repo), clone_path=clone_path, token="")
    await gs.sync()

    (source_repo / "new_monitor.py").write_text("x = 1")
    subprocess.run(["git", "add", "."], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add"], cwd=source_repo, check=True, capture_output=True)

    await gs.sync()
    assert (clone_path / "new_monitor.py").exists()


async def test_sync_raises_on_invalid_repo(tmp_path):
    clone_path = tmp_path / "clone"
    gs = GitSync(repo_url=str(tmp_path / "nonexistent"), clone_path=clone_path, token="")
    with pytest.raises(RuntimeError, match="git"):
        await gs.sync()
