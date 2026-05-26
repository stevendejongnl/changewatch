import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class SaveResult:
    status: str  # "ok" | "conflict" | "error"
    diff: Optional[str] = None
    message: Optional[str] = None


class GitEditor:
    def __init__(self, monitors_dir: Path) -> None:
        self._dir = monitors_dir

    def _is_git_repo(self) -> bool:
        return (self._dir / ".git").exists()

    async def _run(self, *args: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self._dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode(), stderr.decode()

    async def save(self, name: str, source: str) -> SaveResult:
        path = self._dir / f"{name}.py"
        path.write_text(source)

        if not self._is_git_repo():
            return SaveResult(status="ok")

        # git add + commit
        await self._run("git", "add", str(path))
        rc_commit, _, commit_err = await self._run("git", "commit", "-m", f"monitor: update {name}")
        if rc_commit != 0:
            # nothing to commit (file unchanged) — treat as ok
            return SaveResult(status="ok")

        # push
        rc, stdout, stderr = await self._run("git", "push")
        if rc == 0:
            return SaveResult(status="ok")

        # rc != 0 — push failed, attempt rebase
        await self._run("git", "fetch", "origin")

        # detect current branch
        _, branch_out, _ = await self._run("git", "branch", "--show-current")
        branch = branch_out.strip() or "main"

        rc2, _, rebase_err = await self._run("git", "rebase", f"origin/{branch}")
        if rc2 == 0:
            # rebase ok, retry push
            rc3, _, _ = await self._run("git", "push")
            if rc3 == 0:
                return SaveResult(status="ok")

        # rebase failed or push still rejected
        _, diff_out, _ = await self._run("git", "diff", "HEAD")
        await self._run("git", "rebase", "--abort")
        return SaveResult(status="conflict", diff=diff_out)
