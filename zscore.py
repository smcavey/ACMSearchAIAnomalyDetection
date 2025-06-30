import yaml
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import List, Dict
from datetime import datetime
from collections import defaultdict, deque
import uvicorn
import requests
import yaml
import asyncio
import statistics

app = FastAPI()


def load_config(path="config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)


# ----------- Data models -----------
class MetricSnapshot(BaseModel):
    timestamp: datetime
    metrics: Dict[str, Dict[str, float]]  # [service][metric] = value


class ServiceMeta(BaseModel):
    description: str
    depends_on: List[str]


class ServiceContext(BaseModel):
    services: Dict[str, ServiceMeta]


config = load_config()
Z_SCORE_THRESHOLD = config.get("z_score_threshold", 2.0)
svc_ctx = config.get("services_context", {})
SERVICE_CONTEXT = ServiceContext(services=svc_ctx)
# stores number of metrics to be used in calculation of std_dev to derive z_score
Z_SCORE_WINDOW = 5
# in mem history of metrics
METRIC_HISTORY: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=Z_SCORE_WINDOW)))


# ----------- Z-Score calc ---------
def compute_z_scores(values: List[float]) -> list[float]:
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    return [(v - mean) / stdev if stdev != 0 else 0.0 for v in values]


# ----------- Routes ---------------
@app.post("/analyze")
async def analyze_metrics(payload: MetricSnapshot):
    # Track values and timestamps by [service][metric]

    for service, metrics in payload.metrics.items():
        for metric, value in metrics.items():
            METRIC_HISTORY[service][metric].append((payload.timestamp, value))

    anomalies = {}

    for service, metrics in METRIC_HISTORY.items():
        for metric, history in metrics.items():
            if len(history) < Z_SCORE_WINDOW:
                continue

            timestamps, values = zip(*history)
            print(f"\n\nservice: {service}\nmetric: {metric}\ntimestamps: {timestamps}\nvalues: {values}\n\n")
            z_scores = compute_z_scores(values)
            i = len(z_scores) - 1
            z = z_scores[i]  # most recent point in metric history

            # checks if latest data point is anomalous compared to rest of window
            if abs(z) > Z_SCORE_THRESHOLD:
                anomalies.setdefault(service, {})[metric] = [{
                    "service": service,
                    "metric": metric,
                    "timestamp": timestamps[i].isoformat(),
                    "value": values[i],
                    "z_score": round(z, 2)
                }]

    if anomalies:
        print(query_llm(anomalies))  # TODO: do something else besides just printing

    return {"anomalies": anomalies}


def query_llm(anomalies: Dict[str, Dict[str, List[Dict]]]) -> str:
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "llama3",
            "prompt": build_root_cause_prompt(anomalies),
            "stream": False
        }
    )

    return response.json()["response"]


def calculate_trend(history: deque) -> Dict:
    if len(history) < 2:
        return {"trend": "insufficient data"}

    _, values = zip(*history)
    # [100, 105, 95, 97] -> [+5, -10, +2]
    deltas = [b - a for a, b in zip(values, values[1:])]

    # (+5 -10 +2) / 3 = -1 -> "decreasing"
    avg_delta = sum(deltas) / len(deltas)
    trend = (
        "increasing" if avg_delta > 0 else
        "decreasing" if avg_delta < 0 else
        "flat"
    )

    return {
        "trend": trend,
        "avg_delta": round(avg_delta, 3)
    }


def build_root_cause_prompt(anomalies: Dict[str, Dict[str, List[Dict]]]) -> str:
    lines = ["You are an expert in distributed systems observability and root cause analysis.",
             "Your task is to interpret anomalies based on service relationships and suggest possible causes.\n",
             "=== Detected Anomalies ==="]

    for service, metrics in anomalies.items():
        for metric, entries in metrics.items():
            for entry in entries:
                lines.append(
                    f"- Service: {entry['service']} | Metric: {entry['metric']} | "
                    f"Value: {entry['value']} | Z-Score: {entry['z_score']} | "
                    f"Timestamp: {entry['timestamp']}"
                )

    lines.append("\n=== Recent Trends ===")
    for service, metrics in anomalies.items():
        for metric in metrics.keys():
            history = METRIC_HISTORY[service][metric]
            trend = calculate_trend(history)
            lines.append(
                f"- Service: {service} | Metric: {metric} | Trend: {trend['trend']} | Avg Delta: {trend['avg_delta']}"
            )

    lines.append("\n=== Service Context ===")
    for name, meta in SERVICE_CONTEXT.services.items():
        dep_str = ", ".join(meta.depends_on) if meta.depends_on else "None"
        lines.append(f"- {name}: {meta.description} (Depends on: {dep_str})")

    lines.append("\nBased on the anomalies and service relationships, what is the most likely root cause?")
    lines.append("Provide insight, possible cascading effects, and debugging suggestions.\n")
    print("\n".join(lines))

    return "\n".join(lines)


# ----------- Main ----------------
if __name__ == "__main__":
    import sys
    import os

    script_name = os.path.splitext(os.path.basename(sys.argv[0]))[0]
    uvicorn.run(f"{script_name}:app", host="0.0.0.0", port=8082)
