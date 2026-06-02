from pydantic import BaseModel


class SeriesPoint(BaseModel):
    time: str
    value: float | None


class MetricSeries(BaseModel):
    metric_name: str
    labels: dict
    data: list[SeriesPoint]


class MetricsResponse(BaseModel):
    range: str
    resolution: str
    series: list[MetricSeries]
