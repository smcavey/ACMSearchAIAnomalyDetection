# ACMSearchAIAnomalyDetection

# Process Flow

[services with /metrics]
->
[scraper service]
->
[convert to structured input: JSON]
->
[anomaly detection service using simple z-score method]
->
[anomalies?]
->
[llm]
->
[root cause]

# Metrics

## CPU Utilization
```
curl -k -G -H "Authorization: Bearer sha256~..." \
--data-urlencode "query=sum(container_cpu_usage_seconds_total{container='search-collector'}) by (pod)" \
https://thanos-querier-openshift-monitoring.apps.sno-4xlarge-418-bv2s4.dev07.red-chesterfield.com/api/v1/query

{"status":"success","data":{"resultType":"vector","result":[{"metric":{"pod":"search-collector-6d79bc4f9d-9fv66"},"value":[1749825989.829,"1335.986821"]}],"analysis":{}}}```
```

## Memory Utilization
```
curl -k -G -H "Authorization: Bearer sha256~..." \
--data-urlencode "query=container_memory_working_set_bytes{container='search-collector'}" \
https://thanos-querier-openshift-monitoring.apps.sno-4xlarge-418-bv2s4.dev07.red-chesterfield.com/api/v1/query

{"status":"success","data":{"resultType":"vector","result":[{"metric":{"__name__":"container_memory_working_set_bytes","container":"search-collector","endpoint":"https-metrics","id":"/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod775bfbaa_4ac6_40ce_a9a6_ec514d433aa6.slice/crio-6c40a30aa4f04bf7563a5c0ffaf1f59282caab2e64c47693b472b81029bd33a8.scope","image":"registry.redhat.io/rhacm2/search-collector-rhel9@sha256:728c64da189493df86162a08fefbdf5db1ef4f42a4fe0d06aba8c097382946b7","instance":"10.0.10.214:10250","job":"kubelet","metrics_path":"/metrics/cadvisor","name":"k8s_search-collector_search-collector-6d79bc4f9d-9fv66_open-cluster-management_775bfbaa-4ac6-40ce-a9a6-ec514d433aa6_0","namespace":"open-cluster-management","node":"ip-10-0-10-214.ec2.internal","pod":"search-collector-6d79bc4f9d-9fv66","prometheus":"openshift-monitoring/k8s","service":"kubelet"},"value":[1749825329.674,"178552832"]}],"analysis":{}}}
```

## Filesystem
```
curl -k -G -H "Authorization: Bearer sha256~..." \
--data-urlencode "query=sum(container_fs_usage_bytes{container='search-collector'}) by (pod)" \
https://thanos-querier-openshift-monitoring.apps.sno-4xlarge-418-bv2s4.dev07.red-chesterfield.com/api/v1/query

{"status":"success","data":{"resultType":"vector","result":[{"metric":{"pod":"search-collector-6d79bc4f9d-9fv66"},"value":[1749825915.951,"2101248"]}],"analysis":{}}}
```

## Network In
```

```

## Network Out
```

```

## Routes
Metrics for Search components need to be accessible to our service.
```
oc create route passthrough search-api --service=search-search-api -n open-cluster-management
SEARCH_API_ROUTE_HOST = "oc get route search-api -o jsonpath='{.spec.host}'"
SEARCH_API_METRICS_PATH = "https://$SEARCH_API_ROUTE_HOST/metrics"

oc create route passthrough search-indexer --service=search-indexer -n open-cluster-management
SEARCH_INDEXER_ROUTE_HOST = "oc get route search-indexer -o jsonpath='{.spec.host}'"
SEARCH_INDEXER_METRICS_PATH = "https://$SEARCH_INDEXER_ROUTE_HOST/metrics"

oc create route edge search-collector --service=search-collector -n open-cluster-management
SEARCH_COLLECTOR_ROUTE_HOST = "oc get route search-collector -o jsonpath='{.spec.host}'"
SEARCH_COLLECTOR_METRICS_PATH = "https://$SEARCH_COLLECTOR_ROUTE_HOST/metrics"

PROMETHEUS_ROUTE_HOST = "oc get route thanos-querier -n openshift-monitoring -ojsonpath='{.spec.host}'"
PROMETHEUS_ROUTE_PATH = "https://$PROMETHEUS_ROUTE_HOST/api/v1/query"
```

# Config
Copy "config.example.yaml" as config.yaml with appropriate values

# Python Service
```
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

# Example

When receiving a window with values and a low 1 z-score threshold to trigger some anomalies for testing:
```
[42206.669246, 42206.669246, 42206.669246, 42206.669246, 42210.416646]
[50270208.0, 50270208.0, 50270208.0, 50270208.0, 50270208.0]
[272556032.0, 272556032.0, 272556032.0, 272556032.0, 167780352.0]
[9245.082878, 9245.082878, 9245.082878, 9245.082878, 9245.438498]
[12128256.0, 12128256.0, 12128256.0, 12128256.0, 12128256.0]
[188194816.0, 188194816.0, 188194816.0, 188194816.0, 191299584.0]
[706.825662, 706.825662, 706.825662, 706.825662, 706.961794]
[61440.0, 61440.0, 61440.0, 61440.0, 61440.0]
[194064384.0, 194064384.0, 194064384.0, 194064384.0, 195178496.0]
[7291.666865, 7291.666865, 7291.666865, 7291.666865, 7292.320476]
[32768.0, 32768.0, 32768.0, 32768.0, 32768.0]
[374579200.0, 374579200.0, 374579200.0, 374579200.0, 376475648.0]
```
Some anomalies were detected and we ask for insight with input:

```
You are an expert in distributed systems observability and root cause analysis.
Your task is to interpret anomalies based on service relationships and suggest possible causes.

=== Detected Anomalies ===
- Service: search-api | Metric: cpu | Value: 42210.416646 | Z-Score: 1.79 | Timestamp: 2025-06-24T14:04:45.349098-04:00
- Service: search-api | Metric: memory | Value: 167780352.0 | Z-Score: -1.79 | Timestamp: 2025-06-24T14:04:45.349098-04:00
- Service: search-collector | Metric: cpu | Value: 9245.438498 | Z-Score: 1.79 | Timestamp: 2025-06-24T14:04:45.349098-04:00
- Service: search-collector | Metric: memory | Value: 191299584.0 | Z-Score: 1.79 | Timestamp: 2025-06-24T14:04:45.349098-04:00
- Service: search-indexer | Metric: cpu | Value: 706.961794 | Z-Score: 1.79 | Timestamp: 2025-06-24T14:04:45.349098-04:00
- Service: search-indexer | Metric: memory | Value: 195178496.0 | Z-Score: 1.79 | Timestamp: 2025-06-24T14:04:45.349098-04:00
- Service: search-postgres | Metric: cpu | Value: 7292.320476 | Z-Score: 1.79 | Timestamp: 2025-06-24T14:04:45.349098-04:00
- Service: search-postgres | Metric: memory | Value: 376475648.0 | Z-Score: 1.79 | Timestamp: 2025-06-24T14:04:45.349098-04:00

=== Service Context ===
- search-api: Handles user queries to fetch multi-cluster state. Reads from search-postgres. (Depends on: search-postgres)
- search-collector: Collects cluster state and forwards to search-indexer. (Depends on: search-indexer)
- search-indexer: Aggregates incoming cluster state from search-collector. Keeps search-postgres up to date with cluster state. (Depends on: search-postgres)
- search-postgres: Stores multi-cluster state. (Depends on: None)

Based on the anomalies and service relationships, what is the most likely root cause?
Provide insight, possible cascading effects, and debugging suggestions.
```

We received output:
```
A distributed system observability delight!

After analyzing the anomalies and service relationships, I'll take a stab at identifying the most likely root cause.

**Observations:**

1. All services (search-api, search-collector, search-indexer, and search-postgres) exhibit similar CPU and memory usage patterns, with high values and Z-scores around 1.79.
2. No single service has an unusual metric value compared to others. The anomalies are distributed across multiple services.

**Root Cause Hypothesis:**

Given the similarities in anomaly patterns across all services, I suspect that **search-postgres**, being the database that stores multi-cluster state, is experiencing a resource bottleneck or overload. This could be due to:

1. **High write load**: Search-api and search-indexer might be generating an excessive number of writes to search-postgres, causing the database to struggle with handling the load.
2. **Insufficient resources**: search-postgres might not have enough CPU, memory, or disk space to efficiently store and process cluster state updates.

**Cascading Effects:**

If search-postgres is experiencing issues, it's likely that other services will be affected:

1. **search-api**: As the primary consumer of search-postgres, search-api may start to experience errors or timeouts when attempting to fetch multi-cluster state.
2. **search-collector**: With search-indexer struggling to keep up with cluster state updates, search-collector might accumulate a backlog of data, leading to decreased performance and potential errors.

**Debugging Suggestions:**

1. **Monitor search-postgres metrics**: Verify if CPU, memory, disk I/O, or network utilization are indeed abnormally high.
2. **Check database query patterns**: Analyze the types and frequency of queries being executed by search-api and other services to identify potential performance bottlenecks.
3. **Investigate resource constraints**: Review the current resources allocated to search-postgres (e.g., CPU, memory, disk space) and consider scaling or upgrading as needed.
4. **Profile database operations**: Use tools like query logs, slow query logs, or database profiling to gain insight into the specific queries causing issues and optimize performance.

By focusing on search-postgres and its relationships with other services, we can likely identify the root cause of these anomalies and address the underlying issue to restore system stability and performance.
```

# Running
## LLM
We run ollama locally with model llama3 for simplicity.
## main.go
Run main.go to scrape metrics and send to anomaly detection service.
## zscore.py
Checks for anomalies from latest observation in window. If present, sends structured query with context about service dependency to local agent.
