import yaml
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import List, Dict
from datetime import datetime, timedelta
from collections import defaultdict, deque
import uvicorn
import requests
import yaml
import asyncio
import statistics
import json
import os

app = FastAPI()


def load_config(path="config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)


def load_historical_data():
    """Load historical metrics from persistent storage"""
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r") as f:
                data = json.load(f)
                for service, metrics in data.items():
                    for metric, history in metrics.items():
                        # Convert string timestamps back to datetime objects
                        HISTORICAL_METRICS[service][metric] = [
                            (datetime.fromisoformat(ts), value) 
                            for ts, value in history
                        ]
        except Exception as e:
            print(f"Error loading historical data: {e}")


def save_historical_data():
    """Save historical metrics to persistent storage"""
    try:
        # Convert datetime objects to ISO strings for JSON serialization
        data = {}
        for service, metrics in HISTORICAL_METRICS.items():
            data[service] = {}
            for metric, history in metrics.items():
                data[service][metric] = [
                    (ts.isoformat(), value) for ts, value in history
                ]
        
        with open(STORAGE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving historical data: {e}")


def cleanup_old_data():
    """Remove data older than configured retention period"""
    cutoff_date = datetime.now() - timedelta(days=SEASONAL_CONFIG["historical_days"])
    
    for service in HISTORICAL_METRICS:
        for metric in HISTORICAL_METRICS[service]:
            HISTORICAL_METRICS[service][metric] = [
                (ts, value) for ts, value in HISTORICAL_METRICS[service][metric]
                if ts > cutoff_date
            ]


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

# Load historical data on startup
load_historical_data()
Z_SCORE_THRESHOLD = config.get("z_score_threshold", 2.0)
svc_ctx = config.get("services_context", {})
SERVICE_CONTEXT = ServiceContext(services=svc_ctx)

# Seasonal configuration
SEASONAL_CONFIG = config.get("seasonal", {
    "enable": True,
    "historical_days": 14,  # Keep 2 weeks of data
    "short_term_window": 5,
    "min_seasonal_points": 3,  # Minimum points to calculate seasonal baseline
    "adaptive_threshold_multiplier": 1.5
})

# stores number of metrics to be used in calculation of std_dev to derive z_score
Z_SCORE_WINDOW = SEASONAL_CONFIG["short_term_window"]

# Enhanced storage for seasonal analysis
# Structure: [service][metric] = list of (timestamp, value) tuples
HISTORICAL_METRICS: Dict[str, Dict[str, List[tuple]]] = defaultdict(lambda: defaultdict(list))

# Short-term window for immediate anomaly detection (backward compatibility)
METRIC_HISTORY: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=Z_SCORE_WINDOW)))

# Persistent storage file
STORAGE_FILE = "metric_history.json"


# ----------- Z-Score calc ---------
def compute_z_scores(values: List[float]) -> list[float]:
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    return [(v - mean) / stdev if stdev != 0 else 0.0 for v in values]


def get_seasonal_baseline(service: str, metric: str, current_time: datetime) -> Dict:
    """Get seasonal baseline for comparison"""
    if not SEASONAL_CONFIG["enable"]:
        return {"type": "disabled"}
    
    history = HISTORICAL_METRICS[service][metric]
    if len(history) < SEASONAL_CONFIG["min_seasonal_points"]:
        return {"type": "insufficient_data", "points": len(history)}
    
    # Group by time patterns
    hour_of_day = current_time.hour
    day_of_week = current_time.weekday()
    
    # Collect values for same hour of day (±1 hour window)
    hourly_values = []
    for ts, value in history:
        if abs(ts.hour - hour_of_day) <= 1 or abs(ts.hour - hour_of_day) >= 23:
            hourly_values.append(value)
    
    # Collect values for same day of week
    daily_values = []
    for ts, value in history:
        if ts.weekday() == day_of_week:
            daily_values.append(value)
    
    # Collect values for same hour on same day of week
    weekly_values = []
    for ts, value in history:
        if ts.weekday() == day_of_week and abs(ts.hour - hour_of_day) <= 1:
            weekly_values.append(value)
    
    baselines = {}
    
    if len(hourly_values) >= SEASONAL_CONFIG["min_seasonal_points"]:
        baselines["hourly"] = {
            "mean": statistics.mean(hourly_values),
            "stdev": statistics.stdev(hourly_values) if len(hourly_values) > 1 else 0,
            "count": len(hourly_values)
        }
    
    if len(daily_values) >= SEASONAL_CONFIG["min_seasonal_points"]:
        baselines["daily"] = {
            "mean": statistics.mean(daily_values),
            "stdev": statistics.stdev(daily_values) if len(daily_values) > 1 else 0,
            "count": len(daily_values)
        }
    
    if len(weekly_values) >= SEASONAL_CONFIG["min_seasonal_points"]:
        baselines["weekly"] = {
            "mean": statistics.mean(weekly_values),
            "stdev": statistics.stdev(weekly_values) if len(weekly_values) > 1 else 0,
            "count": len(weekly_values)
        }
    
    return {"type": "seasonal", "baselines": baselines}


def calculate_seasonal_z_score(value: float, baseline: Dict) -> float:
    """Calculate z-score using seasonal baseline"""
    if baseline.get("type") != "seasonal":
        return 0.0
    
    baselines = baseline["baselines"]
    
    # Prioritize weekly > daily > hourly baselines
    for pattern in ["weekly", "daily", "hourly"]:
        if pattern in baselines:
            bl = baselines[pattern]
            if bl["stdev"] > 0:
                return (value - bl["mean"]) / bl["stdev"]
    
    return 0.0


def get_adaptive_threshold(service: str, metric: str, current_time: datetime) -> float:
    """Get adaptive threshold based on historical variance"""
    baseline = get_seasonal_baseline(service, metric, current_time)
    
    if baseline.get("type") != "seasonal":
        return Z_SCORE_THRESHOLD
    
    baselines = baseline["baselines"]
    base_threshold = Z_SCORE_THRESHOLD
    
    # Adjust threshold based on historical variance
    for pattern in ["weekly", "daily", "hourly"]:
        if pattern in baselines:
            bl = baselines[pattern]
            # Higher variance = higher threshold
            if bl["stdev"] > 0:
                variance_factor = min(bl["stdev"] / bl["mean"], 2.0) if bl["mean"] > 0 else 1.0
                adjusted_threshold = base_threshold * (1 + variance_factor * 0.5)
                return min(adjusted_threshold, base_threshold * SEASONAL_CONFIG["adaptive_threshold_multiplier"])
    
    return base_threshold


# ----------- Routes ---------------
@app.post("/analyze")
async def analyze_metrics(payload: MetricSnapshot):
    # Track values and timestamps by [service][metric]

    for service, metrics in payload.metrics.items():
        for metric, value in metrics.items():
            # Store in both short-term and historical storage
            METRIC_HISTORY[service][metric].append((payload.timestamp, value))
            HISTORICAL_METRICS[service][metric].append((payload.timestamp, value))
    
    # Cleanup old data and save periodically
    cleanup_old_data()
    save_historical_data()

    anomalies = {}

    for service, metrics in METRIC_HISTORY.items():
        for metric, history in metrics.items():
            if len(history) < Z_SCORE_WINDOW:
                continue

            timestamps, values = zip(*history)
            print(f"\n\nservice: {service}\nmetric: {metric}\ntimestamps: {timestamps}\nvalues: {values}\n\n")
            
            # Get current value and timestamp
            current_timestamp = timestamps[-1]
            current_value = values[-1]
            
            # Traditional z-score for short-term anomalies
            z_scores = compute_z_scores(values)
            traditional_z = z_scores[-1]
            
            # Seasonal analysis
            seasonal_baseline = get_seasonal_baseline(service, metric, current_timestamp)
            seasonal_z = calculate_seasonal_z_score(current_value, seasonal_baseline)
            adaptive_threshold = get_adaptive_threshold(service, metric, current_timestamp)
            
            # Determine if anomalous using multiple approaches
            is_traditional_anomaly = abs(traditional_z) > Z_SCORE_THRESHOLD
            is_seasonal_anomaly = abs(seasonal_z) > adaptive_threshold
            
            # Flag as anomaly if either method detects it
            if is_traditional_anomaly or is_seasonal_anomaly:
                anomaly_data = {
                    "service": service,
                    "metric": metric,
                    "timestamp": current_timestamp.isoformat(),
                    "value": current_value,
                    "traditional_z_score": round(traditional_z, 2),
                    "seasonal_z_score": round(seasonal_z, 2),
                    "adaptive_threshold": round(adaptive_threshold, 2),
                    "detection_method": []
                }
                
                if is_traditional_anomaly:
                    anomaly_data["detection_method"].append("traditional")
                if is_seasonal_anomaly:
                    anomaly_data["detection_method"].append("seasonal")
                
                # Add seasonal context
                if seasonal_baseline.get("type") == "seasonal":
                    anomaly_data["seasonal_context"] = seasonal_baseline["baselines"]
                
                anomalies.setdefault(service, {})[metric] = [anomaly_data]

    if anomalies:
        print(query_llm(anomalies))  # TODO: do something else besides just printing

    # Add summary statistics
    summary = {
        "total_anomalies": sum(len(metrics) for metrics in anomalies.values()),
        "services_affected": len(anomalies),
        "seasonal_enabled": SEASONAL_CONFIG["enable"],
        "historical_data_points": {service: {metric: len(HISTORICAL_METRICS[service][metric]) 
                                           for metric in metrics} 
                                  for service, metrics in HISTORICAL_METRICS.items()}
    }

    return {"anomalies": anomalies, "summary": summary}


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
             "Your task is to interpret anomalies based on service relationships and seasonal patterns.\n",
             "=== Detected Anomalies ==="]

    for service, metrics in anomalies.items():
        for metric, entries in metrics.items():
            for entry in entries:
                detection_methods = ", ".join(entry.get('detection_method', []))
                lines.append(
                    f"- Service: {entry['service']} | Metric: {entry['metric']} | "
                    f"Value: {entry['value']} | Traditional Z-Score: {entry.get('traditional_z_score', 'N/A')} | "
                    f"Seasonal Z-Score: {entry.get('seasonal_z_score', 'N/A')} | "
                    f"Adaptive Threshold: {entry.get('adaptive_threshold', 'N/A')} | "
                    f"Detection: {detection_methods} | "
                    f"Timestamp: {entry['timestamp']}"
                )
                
                # Add seasonal context if available
                if 'seasonal_context' in entry:
                    seasonal_info = []
                    for pattern, data in entry['seasonal_context'].items():
                        seasonal_info.append(f"{pattern}: mean={data['mean']:.2f}, stdev={data['stdev']:.2f}, count={data['count']}")
                    lines.append(f"  Seasonal Context: {'; '.join(seasonal_info)}")

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

    lines.append("\nBased on the anomalies, seasonal patterns, and service relationships, what is the most likely root cause?")
    lines.append("Consider whether this is a seasonal variation or a true anomaly. Provide insight, possible cascading effects, and debugging suggestions.\n")
    print("\n".join(lines))

    return "\n".join(lines)


# ----------- Main ----------------
if __name__ == "__main__":
    import sys
    import os

    script_name = os.path.splitext(os.path.basename(sys.argv[0]))[0]
    uvicorn.run(f"{script_name}:app", host="0.0.0.0", port=8082)
