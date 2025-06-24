import yaml
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import List, Dict
from datetime import datetime
import uvicorn
import yaml
import asyncio
import statistics

app = FastAPI()


def load_config(path="config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)


config = load_config()
Z_SCORE_THRESHOLD = config.get("z_score_threshold", 2.0)


# ----------- Data models -----------
class MetricSnapshot(BaseModel):
    timestamp: datetime
    metrics: Dict[str, Dict[str, float]]  # [service][metric] = value


# ----------- Z-Score calc ---------
def compute_z_scores(values: List[float]) -> list[float]:
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    return [(v - mean) / stdev if stdev != 0 else 0.0 for v in values]


# ----------- Routes ---------------
@app.post("/analyze")
async def analyze_metrics(payload: List[MetricSnapshot]):
    # Track values and timestamps by [service][metric]
    values_by_metric: Dict[str, Dict[str, List[float]]] = {}
    timestamps_by_metric: Dict[str, Dict[str, List[datetime]]] = {}

    for snapshot in payload:
        for service, metrics in snapshot.metrics.items():
            for metric, value in metrics.items():
                values_by_metric.setdefault(service, {}).setdefault(metric, []).append(value)
                timestamps_by_metric.setdefault(service, {}).setdefault(metric, []).append(snapshot.timestamp)

    anomalies = {}

    for service, metrics in values_by_metric.items():
        for metric, values in metrics.items():
            print(values)
            z_scores = compute_z_scores(values)
            timestamps = timestamps_by_metric[service][metric]
            anomaly_entries = []

            # checks if latest data point is anomalous compared to rest of window
            i = len(z_scores) - 1  # latest index
            z = z_scores[i]
            if abs(z) > Z_SCORE_THRESHOLD:
                anomaly_entries.append({
                    "service": service,
                    "metric": metric,
                    "timestamp": timestamps[i].isoformat(),
                    "value": values[i],
                    "z_score": round(z, 2)
                })

            # checks each data point in received window for anomalies
            # for i, z in enumerate(z_scores):
            #     if abs(z) > Z_SCORE_THRESHOLD:
            #         anomaly_entries.append({
            #             "service": service,
            #             "metric": metric,
            #             "timestamp": timestamps[i].isoformat(),
            #             "value": values[i],
            #             "z_score": round(z, 2)
            #         })

            if anomaly_entries:
                anomalies.setdefault(service, {})[metric] = anomaly_entries

    return {"anomalies": anomalies}


# ----------- Main ----------------
if __name__ == "__main__":
    import sys
    import os

    script_name = os.path.splitext(os.path.basename(sys.argv[0]))[0]
    uvicorn.run(f"{script_name}:app", host="0.0.0.0", port=8082)
