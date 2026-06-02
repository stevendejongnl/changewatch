from influxdb_client import InfluxDBClient, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


class InfluxClient:
    def __init__(self, url: str, token: str, org: str, bucket: str):
        self._bucket = bucket
        self._org = org
        self._client = InfluxDBClient(url=url, token=token, org=org)
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)

    async def write(self, measurement: str, value: float | int, timestamp: int | None = None, **tags: str) -> None:
        tag_str = ",".join(f"{k}={v}" for k, v in tags.items())
        line = f"{measurement},{tag_str} value={value}" if tag_str else f"{measurement} value={value}"
        if timestamp is not None:
            line += f" {timestamp}"
            self._write_api.write(bucket=self._bucket, org=self._org, record=line,
                                  write_precision=WritePrecision.S)
        else:
            self._write_api.write(bucket=self._bucket, org=self._org, record=line)

    async def query(self, measurement: str, hours: int = 48) -> list[dict]:
        query_api = self._client.query_api()
        flux = (
            f'from(bucket: "{self._bucket}")'
            f' |> range(start: -{hours}h)'
            f' |> filter(fn: (r) => r._measurement == "{measurement}")'
            f' |> filter(fn: (r) => r._field == "value")'
            f' |> group(columns: ["_time"])'
            f' |> sum()'
            f' |> group()'
            f' |> sort(columns: ["_time"])'
            f' |> keep(columns: ["_time", "_value"])'
        )
        try:
            tables = query_api.query(flux, org=self._org)
        except Exception:
            return []
        result = []
        for table in tables:
            for record in table.records:
                t = record.get_time()
                v = record.get_value()
                if t is not None and v is not None:
                    result.append({"t": t.isoformat().replace("+00:00", "Z"), "v": float(v)})
        return result

    def close(self) -> None:
        self._client.close()
