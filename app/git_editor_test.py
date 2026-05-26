import asyncio

import pytest

from app.git_editor import GitEditor


async def run_git(cwd, *args):
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()


async def run_proc(cwd, *args):
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


@pytest.fixture
async def git_repo(tmp_path):
    # set up bare remote
    bare = tmp_path / "bare.git"
    await run_git(tmp_path.parent, "git", "init", "--bare", str(bare))

    # clone into working repo
    repo = tmp_path / "repo"
    await run_git(tmp_path, "git", "clone", str(bare), str(repo))

    # configure git identity in the clone
    await run_git(repo, "git", "config", "user.email", "test@test.com")
    await run_git(repo, "git", "config", "user.name", "Test")

    # make initial commit so the branch exists
    (repo / "README.md").write_text("init")
    await run_git(repo, "git", "add", "README.md")
    await run_git(repo, "git", "commit", "-m", "init")
    await run_git(repo, "git", "push", "origin", "HEAD")

    return repo


async def test_save_writes_file_and_returns_ok(git_repo):
    editor = GitEditor(git_repo)
    result = await editor.save("my_monitor", "# source")
    assert result.status == "ok"
    assert (git_repo / "my_monitor.py").read_text() == "# source"


async def test_save_commits_file(git_repo):
    editor = GitEditor(git_repo)
    await editor.save("my_monitor", "# source")
    rc, out, _ = await run_proc(git_repo, "git", "log", "--oneline")
    assert rc == 0
    assert "monitor: update" in out


async def test_save_rebases_on_rejected_push(git_repo, tmp_path):
    bare = tmp_path / "bare.git"

    # Clone a second working copy from the bare remote
    clone2 = tmp_path / "clone2"
    proc = await asyncio.create_subprocess_exec(
        "git", "clone", str(bare), str(clone2),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    await run_git(clone2, "git", "config", "user.email", "test2@test.com")
    await run_git(clone2, "git", "config", "user.name", "Test2")

    # Push a competing commit from clone2 FIRST
    (clone2 / "other.py").write_text("other")
    await run_git(clone2, "git", "add", "other.py")
    await run_git(clone2, "git", "commit", "-m", "other commit")
    await run_git(clone2, "git", "push")

    # Now save from the original repo -- should rebase and succeed
    editor = GitEditor(git_repo)
    result = await editor.save("conflict_mon", "new source")
    assert result.status == "ok"


async def test_save_without_git_repo_writes_file_only(tmp_path):
    editor = GitEditor(tmp_path)
    result = await editor.save("plain", "hello")
    assert result.status == "ok"
    assert (tmp_path / "plain.py").read_text() == "hello"


async def test_save_returns_conflict_on_merge_conflict(git_repo, tmp_path):
    bare = tmp_path / "bare.git"

    # Clone a second working copy from the bare remote
    clone2 = tmp_path / "clone2"
    proc = await asyncio.create_subprocess_exec(
        "git", "clone", str(bare), str(clone2),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    await run_git(clone2, "git", "config", "user.email", "c2@test.com")
    await run_git(clone2, "git", "config", "user.name", "Clone2")

    # clone2 commits conflict_file.py and pushes
    (clone2 / "conflict_file.py").write_text("CLONE2_VERSION = True")
    await run_git(clone2, "git", "add", "conflict_file.py")
    await run_git(clone2, "git", "commit", "-m", "clone2 adds conflict_file")
    await run_git(clone2, "git", "push")

    # git_repo also commits the SAME file with different content WITHOUT pushing
    (git_repo / "conflict_file.py").write_text("GITREPO_VERSION = True")
    await run_git(git_repo, "git", "add", "conflict_file.py")
    await run_git(git_repo, "git", "commit", "-m", "gitrepo adds conflict_file")

    # save will: write conflict_file.py, add, commit, push → rejected
    # fetch → rebase origin/main → conflict (same file modified differently)
    editor = GitEditor(git_repo)
    result = await editor.save("conflict_file", "SAVE_ATTEMPT = True")

    assert result.status == "conflict"
    assert result.diff is not None


async def test_save_returns_ok_when_commit_has_nothing_to_commit(git_repo):
    editor = GitEditor(git_repo)
    
    # First save: creates a new file and commits
    result1 = await editor.save("no_change_mon", "# original")
    assert result1.status == "ok"
    
    # Second save with same content: file unchanged, commit should fail with rc != 0
    result2 = await editor.save("no_change_mon", "# original")
    assert result2.status == "ok"
