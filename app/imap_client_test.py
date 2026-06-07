import pytest
from app.imap_client import account_to_env_key, ImapClient


def test_account_to_env_key_basic():
    assert account_to_env_key("mail@stevenenanja.nl") == "MAIL_STEVENENANJA_NL"


def test_account_to_env_key_hyphen_in_domain():
    assert account_to_env_key("steven@steven-dejong.nl") == "STEVEN_STEVEN_DEJONG_NL"


def test_account_to_env_key_uppercase_input():
    assert account_to_env_key("MAIL@STEVENENANJA.NL") == "MAIL_STEVENENANJA_NL"


def test_imap_client_from_env_finds_account():
    env = {"IMAP_URL_MAIL_STEVENENANJA_NL": "imaps://u:p@host:993"}
    client = ImapClient.from_env(env)
    assert client.get_url("mail@stevenenanja.nl") == "imaps://u:p@host:993"


def test_imap_client_from_env_empty():
    client = ImapClient.from_env({})
    assert client.known_accounts() == []


def test_imap_client_known_accounts_returns_env_key_suffixes():
    env = {
        "IMAP_URL_MAIL_STEVENENANJA_NL": "imaps://a:b@host:993",
        "IMAP_URL_STEVEN_STEVEN_DEJONG_NL": "imaps://c:d@host:993",
    }
    client = ImapClient.from_env(env)
    keys = client.known_accounts()
    assert "MAIL_STEVENENANJA_NL" in keys
    assert "STEVEN_STEVEN_DEJONG_NL" in keys


def test_imap_client_get_url_missing_raises_with_key_name():
    client = ImapClient.from_env({})
    with pytest.raises(ValueError, match="IMAP_URL_MAIL_STEVENENANJA_NL"):
        client.get_url("mail@stevenenanja.nl")


def test_imap_client_get_url_multiple_accounts():
    env = {
        "IMAP_URL_A_B_NL": "imaps://a:p@host:993",
        "IMAP_URL_C_D_NL": "imaps://c:q@host:993",
    }
    client = ImapClient.from_env(env)
    assert client.get_url("a@b.nl") == "imaps://a:p@host:993"
    assert client.get_url("c@d.nl") == "imaps://c:q@host:993"


def test_imap_client_from_env_none_reads_os_environ(monkeypatch):
    monkeypatch.setenv("IMAP_URL_A_B_NL", "imaps://a:p@host:993")
    client = ImapClient.from_env(None)
    assert client.get_url("a@b.nl") == "imaps://a:p@host:993"
