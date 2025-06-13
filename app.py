from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import List, Dict
from datetime import datetime
import uvicorn
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, ServiceContext
from llama_index.core.schema import Document
from llama_index.core.node_parser import SimpleNodeParser
from llama_index.llms.ollama import Ollama
import asyncio

app = FastAPI()

# ----------- Data models -----------
class MetricSnapshot(BaseModel):
    timestamp: datetime
    metrics: Dict[str, Dict[str, float]]  # [service][metric] = value

# ----------- In-memory state -----------
sliding_window: List[MetricSnapshot] = []

# ----------- LLM + LlamaIndex setup -----------
# llm = Ollama(model="llama3")
# service_context = ServiceContext.from_defaults(llm=llm)

# ----------- Routes -----------
@app.post("/analyze")
async def analyze_metrics(payload: List[MetricSnapshot]):
    global sliding_window
    sliding_window = payload

    # Turn the payload into plain text for LLM ingestion
    lines = []
    for snapshot in payload:
        ts = snapshot.timestamp.isoformat()
        for service, metrics in snapshot.metrics.items():
            for metric, value in metrics.items():
                lines.append(f"{ts} - {service} - {metric}: {value}")
    joined = "\n".join(lines)

    print("joined" + joined)
    # doc = Document(text=joined)
    # parser = SimpleNodeParser()
    # nodes = parser.get_nodes_from_documents([doc])
    # index = VectorStoreIndex(nodes, service_context=service_context)
    #
    # query_engine = index.as_query_engine()
    # response = query_engine.query("What anomalies do you see in the service metrics over time?")
    return {"analysis": str("response")}

# ----------- Main -----------
if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8082)
