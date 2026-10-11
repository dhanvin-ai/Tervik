# Deploy: dashboard on Vercel, API on Railway

Tervik has two parts:

- **The dashboard** (`apps/web`) is static files. Vercel serves it.
- **The API** (`apps/api`) is a FastAPI service with a database. Railway runs it, alongside a Postgres database.

The dashboard calls the API at the address in `VITE_API_URL`, which is set when the dashboard is built.

## 1. The API on Railway

1. **Create the API service.** In your Railway project, choose **New → GitHub Repo** and pick this repository.
2. **Point it at the API.** In the new service's **Settings**:
   - **Source → Branch:** the branch to deploy, such as `ui-maritime-theme` until it is merged.
   - **Source → Root Directory:** `/apps/api`.
   - **Config-as-code:** `/apps/api/railway.json`. This builds the service from the Dockerfile and health-checks `/api/health`.
3. **Add a database.** Choose **New → Database → PostgreSQL**. Tervik creates its tables on first start.
4. **Set variables.** Under the API service's **Variables**, add:

   | Variable | Value |
   | - | - |
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}`, a reference to the database |
   | `TERVIK_ADMIN_TOKEN` | A long random secret, such as the output of `openssl rand -hex 32`. Without it, anyone could read the data. |
   | `TERVIK_CORS_ORIGINS` | Your dashboard's address, such as `https://tervik-seven.vercel.app` |
   | `TERVIK_DASHBOARD_URL` | The same address. Alert messages link to it. |
   | `TERVIK_DEMO_ENABLED` | `true` to allow **Load sample workspace** (optional) |
   | `ANTHROPIC_API_KEY` | Optional. Turns on intent and policy checks, and Claude in **Chat**. |

5. **Give it an address.** Under **Settings → Networking → Generate Domain**, create a domain, such as `https://tervik-api-production.up.railway.app`.
6. **Check it.** Opening `https://<that domain>/api/health` should return `{"status": "ok", "storage": "postgresql", ...}`.

**Remove the old service.** A service built from the repository root, such as `@tervik/web`, builds the dashboard rather than the API. Delete it so it stops using credits.

**Run the background jobs (optional).** Alerts and scheduled classification run as two more services from the same repository, each with the same root directory and variables. Set their start commands to `python -m app.jobs alerts` and `python -m app.jobs classify`.

**Chat on a hosted API.** The **Chat** page uses Ollama, which runs on your own computer, not on Railway. On a hosted API, Chat needs `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.

## 2. The dashboard on Vercel

1. **Production branch.** Under **Settings → Git → Production Branch**, choose the branch to deploy, such as `ui-maritime-theme`.
2. **API address.** Under **Settings → Environment Variables**, add `VITE_API_URL` with the Railway domain from step 5, such as `https://tervik-api-production.up.railway.app`, for **Production** and **Preview**.
3. **Redeploy.** Open **Deployments**, then **Redeploy** the latest deployment of that branch. `VITE_API_URL` is read when the dashboard is built, so changing it always needs a redeploy.
4. **Sign in.** Open the dashboard, choose **Connection settings**, and paste the `TERVIK_ADMIN_TOKEN` value.

## 3. Connect an agent to the hosted API

On **Connect your agent**, the endpoint is the Railway domain. Agents send events there with the project ID:

```bash
TERVIK_PROJECT_ID=<project ID> TERVIK_ENDPOINT=https://<railway domain> python3 agent.py
```
