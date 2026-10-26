from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Stockage des datasets
    data_dir: Path = Path("data/datasets")
    max_upload_mb: int = 2048           # CSV / Parquet : ingestion en streaming (DuckDB)
    max_excel_mb: int = 100             # Excel : chargé en mémoire par pandas, donc plafonné
    upload_chunk_mb: int = 8            # taille des blocs d'écriture lors de l'upload
    allowed_extensions: tuple[str, ...] = (".csv", ".xlsx", ".parquet")
    preview_rows: int = 20

    # Moteur SQL
    max_result_rows: int = 1000
    query_timeout_s: int = 30
    max_sql_length: int = 5000
    duckdb_memory_limit: str = "1GB"    # plafond mémoire par connexion DuckDB
    duckdb_threads: int = 2

    # Agent / LLM (API Ollama)
    ollama_base_url: str = "https://ollama.com"
    ollama_api_key: str = ""
    llm_model: str = "gpt-oss:120b"
    llm_timeout_s: int = 120
    llm_min_output_tokens: int = 2048   # marge pour les modèles qui "réfléchissent"
    llm_num_ctx: int = 0                # 0 = laissé au serveur (utile surtout en local)
    llm_think: bool | None = None       # None = comportement par défaut du modèle
    agent_max_attempts: int = 3

    # Serveur MCP (l'agent exécute ses requêtes SQL via MCP)
    agent_use_mcp: bool = True
    mcp_call_timeout_s: int = 120     # large : le 1er profil d'un très gros dataset peut durer
    mcp_start_timeout_s: int = 30
    dashboard_use_mcp: bool = True    # la route dashboard passe par l'outil MCP get_dashboard


settings = Settings()