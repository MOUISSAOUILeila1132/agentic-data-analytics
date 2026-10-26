# 🤖 Agentic AI Platform for Multi-Domain Data Analytics

> Ask questions in natural language: the AI agent turns them into SQL queries, analyzes your data, and automatically generates interactive dashboards.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688)
![DuckDB](https://img.shields.io/badge/DuckDB-SQL%20engine-yellow)
![LangGraph](https://img.shields.io/badge/LangGraph-agent-purple)
![MCP](https://img.shields.io/badge/MCP-tools-black)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED)

---

## 🎬 Demo

👉 **Demo link: [INSERT HERE](https://your-demo-link)**


---

## 📌 Table of Contents

1. [Overview](#-overview)
2. [Needs Addressed](#-needs-addressed)
3. [Key Strengths](#-key-strengths)
4. [Features](#-features)
5. [Architecture](#-architecture)
6. [Tech Stack](#-tech-stack)
7. [AI Models](#-ai-models)
8. [Business Benefits](#-business-benefits)
9. [Installation](#-installation)
10. [Usage](#-usage)
11. [Project Structure](#-project-structure)
12. [Testing](#-testing)
13. [Roadmap](#-roadmap)
14. [Author](#-author)

---

## 🧭 Overview

**Agentic AI Platform for Multi-Domain Data Analytics** is a data analysis platform driven by an AI agent. Users upload a dataset (CSV, etc.) and interact with the agent in natural language: the agent understands the question, explores the schema, generates and runs SQL, interprets the results, and produces interactive visualizations.

The platform is **multi-domain**: it is not tied to any industry (sales, finance, HR, real estate, healthcare, logistics…) and adapts to any tabular dataset.

---

## 🎯 Needs Addressed

| Need / Problem | How the project addresses it |
|---|---|
| Non-technical users don't know SQL | Query data in **natural language** (NL → SQL) |
| Data analysis is time-consuming | **Automated** profiling, querying, and dashboards |
| Data quality is unknown before analysis | Automatic **quality profile** (types, missing values, statistics) |
| Traditional BI dashboards require manual setup | **Agent-generated interactive dashboards** (Plotly) |
| Dependence on costly BI tools | **Open-source**, self-hostable stack |
| Confidentiality of sensitive data | LLM can run **locally / self-hosted** (Ollama) |
| Large files are hard to analyze | **DuckDB** processing and large-dataset segmentation |
| AI tooling is hard to integrate | Tools exposed through a standardized **MCP server** |

---

## 💪 Key Strengths

- 🗣️ **Natural language → SQL**: query your data without writing a line of code.
- 🧠 **Agentic architecture (LangGraph)**: the agent reasons in multiple steps (context → SQL → execution → interpretation).
- 🔌 **Built-in MCP server**: standardized, reusable tools that other AI clients can consume.
- ⚡ **DuckDB engine**: very fast analytical queries with no database server.
- 📊 **Automatic interactive dashboards** with Plotly.
- 🧪 **Built-in data quality profiling**.
- 🔀 **Modularity**: MCP can be toggled on/off (`AGENT_USE_MCP`, `DASHBOARD_USE_MCP`).
- 🔒 **Controlled SQL execution** through a dedicated engine.
- 🐳 **Easy deployment** with Docker / docker-compose.
- 🌍 **Multi-domain**: works with any tabular dataset.
- 🔁 **Swappable LLM**: the model is configured through environment variables.

---

## ✨ Features

### 📂 Dataset management
- Upload and list datasets
- Data and schema preview

### 🔍 Profiling & quality
- Column types, missing values, duplicates
- Descriptive statistics

### 🧮 SQL queries
- Direct SQL editor on your data (DuckDB)
- Safe execution and result display

### 🤖 AI agent
- Natural language questions
- SQL generation based on the schema
- Execution, interpretation, and explanation of results

### 📈 Automatic dashboard
- The agent selects the key indicators of the dataset
- Interactive Plotly charts displayed in Streamlit

### 🔌 MCP server
Exposed tools:

| Tool | Purpose |
|---|---|
| `list_datasets` | List available datasets |
| `get_dataset_schema` | Retrieve a dataset's schema |
| `preview_dataset` | Preview the first rows |
| `profile_dataset` | Generate the quality profile |
| `run_sql_query` | Execute a SQL query |
| `get_data_context` | Provide data context to the agent |
| `get_dashboard` | Generate dashboard data |

---

## 🏗️ Architecture

```
┌──────────────────────┐
│  Streamlit Frontend  │  Overview · Quality profile · SQL · Agent · Dashboard
└──────────┬───────────┘
           │ HTTP
┌──────────▼───────────┐
│   FastAPI Backend    │  api/datasets · api/query · ...
└──────────┬───────────┘
           │
   ┌───────┴────────┐
   │                │
┌──▼─────────┐  ┌───▼────────────┐
│ Agent      │  │ Services       │
│ LangGraph  │  │ dataset · SQL  │
│ (NL → SQL) │  │ profiling · LLM│
└──┬─────────┘  └───┬────────────┘
   │ MCP tools      │
┌──▼────────────────▼──┐        ┌──────────────────┐
│      MCP Server      │───────▶│   DuckDB         │
└──────────────────────┘        └──────────────────┘
           │
┌──────────▼───────────┐
│ LLM (Ollama)         │
└──────────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Language | Python |
| Backend / API | FastAPI |
| Analytical engine | DuckDB |
| Agent orchestration | LangGraph |
| Tool protocol | MCP (Model Context Protocol) |
| Visualization | Plotly |
| Frontend | Streamlit |
| LLM serving | Ollama |
| Containerization | Docker, docker-compose |
| Testing | Pytest |
| Python project management | `pyproject.toml`, `requirements.txt` |

---

## 🧠 AI Models

| Role | Model / Engine |
|---|---|
| Agent reasoning & NL → SQL | LLM served via **Ollama**: model `<MODEL_NAME>` *(configurable in `.env`)* |
| Analytical execution | **DuckDB** (columnar SQL engine) |
| Orchestration | **LangGraph** (agent state graph) |

> The LLM can run **locally**, on a self-hosted server, or on a GPU environment (e.g., Google Colab + tunnel) depending on available resources. Changing the model only requires editing an environment variable.

---

## 🏢 Business Benefits

- ⏱️ **Time savings**: from question to insight in seconds.
- 👥 **Data democratization**: business teams become autonomous without relying on data analysts for every query.
- 💰 **Lower costs**: 100% open-source stack, no BI licenses.
- 🔐 **Privacy & sovereignty**: data and LLM can stay in-house.
- 🔧 **Flexibility**: adaptable to any industry and any tabular dataset.
- 🔗 **Easy integration**: REST API (FastAPI) + reusable MCP server.
- 📈 **Faster decision-making** through on-demand dashboards.
- 🧱 **Scalable**: modular architecture (new tools, new models, new domains).
- 🚀 **Fast deployment** with Docker.

---

## ⚙️ Installation

### Prerequisites
- Python 3.11+
- Docker (optional)
- An accessible Ollama server (local or remote)

### 1. Clone the repository
```bash
git clone https://github.com/<your-account>/agentic-data-analytics.git
cd agentic-data-analytics
```

### 2. Virtual environment & dependencies
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configuration (`.env`)
```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=<model_name>
AGENT_USE_MCP=true
DASHBOARD_USE_MCP=true
```

### 4. Run the backend
```bash
uvicorn backend.app.main:app --reload
```

### 5. Run the frontend
```bash
streamlit run frontend/app.py
```

### 🐳 With Docker
```bash
docker-compose up --build
```

---

## ▶️ Usage

1. Open the Streamlit interface.
2. Upload a dataset (or use `ventes_demo.csv`).
3. Check the **Overview** and **Quality profile** tabs.
4. Try queries in the **SQL Query** tab.
5. Ask the **AI Agent** questions, for example:
   - *"What is the revenue per month?"*
   - *"What are the top 5 best-selling products?"*
6. Generate the interactive **dashboard**.

---


## 🧪 Testing

```bash
pytest
```

The MCP server includes a smoke test and a `/health/mcp` health endpoint.

---

## 🗺️ Roadmap

- [x] FastAPI backend + dataset management
- [x] Quality profiling
- [x] DuckDB SQL engine
- [x] Streamlit frontend
- [x] MCP server (tools)
- [x] MCP integration in the agent and dashboard
- [ ] Finalized NL → SQL agent
- [ ] Agent-generated interactive dashboard
- [ ] **Large dataset** analysis (segmentation at upload)
- [ ] Multi-source support (SQL databases, Excel, Parquet)
- [ ] Authentication & multi-user management

---

## 👩‍💻 Author

**Leila Mouissaoui**
Data & AI Engineer, ESPRIT Monastir

- GitHub: [github.com/MOUISSAOUILeila1132](https://github.com/MOUISSAOUILeila1132)
- LinkedIn: [linkedin.com/in/mouissaouilaila](https://linkedin.com/in/mouissaouilaila)

---

## 📄 License

This project is released under the **MIT** license *(adjust as needed)*.
