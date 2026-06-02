import os
import apprise


class AppriseClient:
    def __init__(self) -> None:
        self._channels = self._load_channels()

    def _load_channels(self) -> dict[str, str]:
        prefix = "APPRISE_URL_"
        return {
            key[len(prefix):].lower(): url
            for key, url in os.environ.items()
            if key.startswith(prefix)
        }

    def resolved_channels(self) -> dict[str, str]:
        return dict(self._channels)

    async def notify(self, title: str, body: str, tags: list[str] | None = None) -> None:
        targets = tags or []
        for tag in targets:
            url = self._channels.get(tag)
            if not url:
                continue
            ap = apprise.Apprise()
            ap.add(url)
            await ap.async_notify(title=title, body=body, body_format=apprise.NotifyFormat.TEXT)
