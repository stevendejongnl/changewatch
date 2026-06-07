import os
import re


def account_to_env_key(account: str) -> str:
    return re.sub(r'[^A-Z0-9]', '_', account.upper())


class ImapClient:
    _PREFIX = "IMAP_URL_"

    def __init__(self, accounts: dict[str, str]) -> None:
        self._accounts = accounts

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ImapClient":
        if env is None:
            env = dict(os.environ)
        accounts = {
            k[len(cls._PREFIX):]: v
            for k, v in env.items()
            if k.startswith(cls._PREFIX)
        }
        return cls(accounts)

    def get_url(self, account: str) -> str:
        key = account_to_env_key(account)
        url = self._accounts.get(key)
        if not url:
            raise ValueError(
                f"Missing env var IMAP_URL_{key!s} for IMAP account {account!r}"
            )
        return url

    def known_accounts(self) -> list[str]:
        return list(self._accounts.keys())
