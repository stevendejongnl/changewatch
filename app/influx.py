from influxdb_client import InfluxDBClient, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


class InfluxClient:
    def __init__(self, url: str, token: str, org: str, bucket: str):
        self._bucket = bucket
        self._org = org
        self._client = InfluxDBClient(url=url, token=token, org=org)
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)

    async def write(self, measurement: str, value: float | int, **tags: str) -> None:
        tag_str = ",".join(f"{k}={v}" for k, v in tags.items())
        line = f"{measurement},{tag_str} value={value}" if tag_str else f"{measurement} value={value}"
        self._write_api.write(bucket=self._bucket, org=self._org, record=line)

    def close(self) -> None:
        self._client.close()
