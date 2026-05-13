import asyncio
from pathlib import Path


class GitSync:
    def __init__(self, repo_url: str, clone_path: Path, token: str) -> None:
        self._repo_url = repo_url
        self._clone_path = clone_path
        self._token = token

    def _authenticated_url(self) -> str:
        if not self._token or "://" not in self._repo_url:
            return self._repo_url
        scheme, rest = self._repo_url.split("://", 1)
        return f"{scheme}://{self._token}@{rest}"

    async def _run(self, *args: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git command failed: {' '.join(args)}\n{stderr.decode()}")

    async def sync(self) -> None:
        url = self._authenticated_url()
        if not self._clone_path.exists():
            self._clone_path.parent.mkdir(parents=True, exist_ok=True)
            await self._run("git", "clone", url, str(self._clone_path))
        else:
            await self._run("git", "-C", str(self._clone_path), "pull", url)
