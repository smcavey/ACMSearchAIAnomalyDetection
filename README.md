# ACMSearchAIAnomalyDetection

# Process Flow

[services with /metrics]
->
[scraper service]
->
[convert to structured input: CSV, JSON]
->
[LlamaStack + LlamaIndex]
->
[LLM Response: anomalies? reason?]

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
