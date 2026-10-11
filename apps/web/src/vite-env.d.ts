/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** The Tervik API's address when it is hosted apart from the dashboard. */
  readonly VITE_API_URL?: string;
  /** The ingestion address shown on Connect your agent, when it differs from the API's. */
  readonly VITE_INGEST_ENDPOINT?: string;
}
