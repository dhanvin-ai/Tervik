# Deploy: dashboard on Vercel, API on Azure

Tervik has two parts:

- **The dashboard** (`apps/web`) is static files. Vercel serves it.
- **The API** (`apps/api`) is a FastAPI service with a database. Azure Container Apps runs it, and Azure Database for PostgreSQL stores its data.

The dashboard calls the API at the address in `VITE_API_URL`, which is set when the dashboard is built.

This is how Tervik itself is hosted:

| Part | Address | Host |
| - | - | - |
| Dashboard | https://www.tervik.in (`tervik.in` redirects to it) | Vercel |
| API | https://api.tervik.in | Azure Container Apps |
| Database | Private to the Azure subscription | Azure Database for PostgreSQL |
| API image | `ghcr.io/dhanvin-ai/tervik-api` | GitHub Container Registry, built by GitHub Actions |
| DNS | Records for `tervik.in` | GoDaddy |

Follow the sections in order. Steps that name `tervik.in` use your own domain in its place. An earlier setup on Railway is kept at the end, under [Alternative: the API on Railway](#alternative-the-api-on-railway).

## 1. The API on Azure

[`scripts/deploy_azure.sh`](../scripts/deploy_azure.sh) creates everything with the Azure CLI, and [`.github/workflows/deploy-api.yml`](../.github/workflows/deploy-api.yml) builds and deploys the API on every push to `main` that changes it.

**What it costs.** On Azure for Students, this setup fits in the free allowances, so the credit lasts:

| Resource | Size | Cost |
| - | - | - |
| PostgreSQL Flexible Server | Burstable B1ms, 32 GB | Free for 12 months (750 hours a month) |
| Container Apps | 0.5 vCPU, 1 GiB, scales to zero when idle | Free up to 180,000 vCPU-seconds a month, then pay as you go |
| Container image | GitHub Container Registry | Free for a public image |
| Logs | Off | None |

Scaling to zero means the first request after a quiet spell takes a few seconds while the API starts. To keep it always warm, run `az containerapp update --name tervik-api --resource-group tervik --min-replicas 1`. That uses roughly $10–15 of credit a month.

**Steps.**

1. **Install the tools and sign in.**

   ```bash
   brew install azure-cli
   ```

   ```bash
   az login
   ```

   Choose your **Azure for Students** subscription when asked. The GitHub CLI (`gh`) also needs to be signed in, for step 4.

2. **Build the image.** Push to `main`, or open the repository's **Actions** tab, choose **Deploy API**, and click **Run workflow**. The workflow publishes `ghcr.io/dhanvin-ai/tervik-api`. Its Azure steps are skipped until step 4.

3. **Check the image is public.** It is by default, since the repository is public, and Azure then pulls it without a password. `setup` checks this. If it ever isn't, open https://github.com/users/dhanvin-ai/packages/container/package/tervik-api, then **Package settings → Change visibility → Public**.

4. **Create the database and the API.**

   ```bash
   cd ~/Projects/tervik && scripts/deploy_azure.sh setup
   ```

   This takes about 10 minutes, mostly for the database. It creates:
   - a resource group, `tervik`, in Central India;
   - a PostgreSQL server and a `tervik` database;
   - a Container Apps environment;
   - the `tervik-api` app, with `DATABASE_URL`, a new `TERVIK_ADMIN_TOKEN`, `TERVIK_CORS_ORIGINS`, and `TERVIK_DASHBOARD_URL` stored as Azure secrets.

   **Save the administrator token it prints.** You sign in to the dashboard with it, and it's shown only once. To keep an existing token, or to add optional keys at the same time, set them first:

   ```bash
   read -rs "TERVIK_ADMIN_TOKEN?Admin token: " && export TERVIK_ADMIN_TOKEN
   ```

   The script also passes on `ANTHROPIC_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GITHUB_CLIENT_ID`, and `GITHUB_CLIENT_SECRET` when they're set.

   If your subscription doesn't allow Central India, pick another region: `AZURE_LOCATION=southeastasia scripts/deploy_azure.sh setup`.

5. **Deploy on every push.**

   ```bash
   cd ~/Projects/tervik && scripts/deploy_azure.sh github
   ```

   This creates a managed identity that GitHub Actions signs in as. It can change only the `tervik` resource group, and only workflows on `main` can use it, through short-lived tokens; no password is stored in GitHub. The script then sets the repository variables the workflow reads.

6. **Check it.**

   ```bash
   cd ~/Projects/tervik && scripts/deploy_azure.sh status
   ```

   The health line shows `{"status":"ok","storage":"postgresql",…}`. If `storage` says `sqlite`, `DATABASE_URL` isn't set.

**Change a setting later.** Secrets and plain settings are set separately. For example, to add an Anthropic key without leaving it in your shell history:

```bash
read -rs "KEY?Anthropic API key: " && az containerapp secret set --name tervik-api --resource-group tervik --secrets anthropic-api-key="$KEY"
```

```bash
az containerapp update --name tervik-api --resource-group tervik --set-env-vars ANTHROPIC_API_KEY=secretref:anthropic-api-key
```

Plain settings, such as `TERVIK_DEMO_ENABLED=true` or `TERVIK_SIGNUP_ENABLED=false`, go straight into `--set-env-vars`. To read the administrator token again:

```bash
az containerapp secret show --name tervik-api --resource-group tervik --secret-name admin-token --query value -o tsv
```

**Background jobs (optional).** Alerts and scheduled classification can run as [Container Apps jobs](https://learn.microsoft.com/azure/container-apps/jobs) from the same image, with the commands `python -m app.jobs alerts` and `python -m app.jobs classify`.

**Chat on a hosted API.** The **Chat** page's free model, Ollama, runs on your own computer, not on Azure. On the hosted API, Chat needs `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.

**Moving data from Railway.** If the Railway database is still reachable, copy it across with `pg_dump "$RAILWAY_DATABASE_URL" -Fc -f tervik.dump`, then `pg_restore --no-owner -d "$AZURE_DATABASE_URL" tervik.dump`. Otherwise the Azure database starts empty, and Tervik creates its tables on first start.

## 2. The dashboard on Vercel

1. **Import the repository.** Skip this if the Vercel project already exists. Otherwise choose **Add New → Project**, import this repository, set **Root Directory** to `apps/web`, and keep the **Vite** framework preset. The dashboard builds on its own: the skill download in `apps/web/public` is committed.
2. **Production branch.** Under **Settings → Environments → Production → Branch Tracking**, choose `main`.
3. **API address.** Under **Settings → Environment Variables → Add New**:
   - **Type:** **Config**, not **Secret**. The dashboard runs in the browser, so the API address is public by design, and Vercel refuses a `VITE_` variable marked secret.
   - **Key:** `VITE_API_URL`. Keep the `VITE_` prefix; without it the dashboard never sees the value.
   - **Value:** the API address with no trailing slash: `https://api.tervik.in`, or the `azurecontainerapps.io` address `status` prints if you aren't using your own domain.
   - **Environments:** Production and Preview.
4. **Redeploy.** Open **Deployments**, open the **⋯** menu on the latest deployment of the production branch, and choose **Redeploy**. `VITE_API_URL` is read when the dashboard is built, so changing it always needs a redeploy.
5. **Check it.** Open the dashboard. The top right shows **API connected**.

## 3. Your own domain

This puts the dashboard on `www.tervik.in` and `tervik.in`, and the API on `api.tervik.in`, with the DNS records at GoDaddy. Other registrars have the same records under different menus.

1. **Dashboard domains (Vercel).** In the project, open **Settings → Domains** and add `tervik.in`. Accept Vercel's suggestion to add `www.tervik.in` too, with `tervik.in` redirecting to it; this is how Tervik is set up. Vercel then shows the records to create, such as:

   | Type | Name | Value |
   | - | - | - |
   | A | `@` | `216.198.79.1` |
   | CNAME | `www` | `42741f31064f7810.vercel-dns-017.com` |

   Use the values Vercel shows you; the CNAME target is different for each project.

2. **API domain (Azure).** Run:

   ```bash
   cd ~/Projects/tervik && scripts/deploy_azure.sh domain
   ```

   The first time, it prints the two records to create:

   | Type | Name | Value |
   | - | - | - |
   | CNAME | `api` | The app's address, such as `tervik-api.<random>.centralindia.azurecontainerapps.io` |
   | TXT | `asuid.api` | A long verification code |

3. **DNS records (GoDaddy).** Open **Domain → tervik.in → DNS → DNS Records**:
   - **Delete** the `A @ Parked` record with its trash icon, if it's there. GoDaddy won't let you edit it, and leaving it beside Vercel's record would send some visitors to the parking page.
   - **Add New Record:** `A`, name `@`, value Vercel's IP.
   - **Edit** the `CNAME www` record with its pencil icon, and change the value to Vercel's CNAME target.
   - **Edit** the `CNAME api` record (or add it), and set the value to the Azure address `domain` printed.
   - **Add New Record:** `TXT`, name `asuid.api` (GoDaddy adds `.tervik.in` itself), value the verification code.
   - **Delete** the old Railway record `TXT _railway-verify.api`, if it's there.
   - Leave the `NS`, `SOA`, `_domainconnect`, and `_dmarc` records alone.

   Changes usually apply within minutes, but can take a few hours.

4. **Attach the domain.** Run `scripts/deploy_azure.sh domain` again. Once it sees the records, it attaches `api.tervik.in` with a free managed HTTPS certificate.

5. **Check everything:**

   ```bash
   dig +short A tervik.in
   ```

   Only Vercel's IP, `216.198.79.1`. Two more addresses mean the parked record is still there.

   ```bash
   dig +short CNAME www.tervik.in && dig +short CNAME api.tervik.in
   ```

   Vercel's target, then the Azure address.

   ```bash
   curl https://api.tervik.in/api/health
   ```

   `"status":"ok"` and `"storage":"postgresql"`. The first request after a quiet spell can take a few seconds.

   ```bash
   curl -s -o /dev/null -D - -X OPTIONS -H "Origin: https://www.tervik.in" -H "Access-Control-Request-Method: GET" https://api.tervik.in/api/projects | grep -i access-control-allow-origin
   ```

   `access-control-allow-origin: https://www.tervik.in`. No output means the address is missing from `TERVIK_CORS_ORIGINS`.

## 4. Sign in

**With an account.** Open https://www.tervik.in and choose **Sign up** (or **Log in**). Each account gets its own private workspace. Sign-up is open to anyone unless `TERVIK_SIGNUP_ENABLED=false`.

**As the operator, seeing every project.** On the **Log in** page, choose **Use the administrator token** and paste the token `setup` printed into **Administrator token**. Leave **Account session** empty: a value there is used instead of the token. The token lasts for that browser tab only, and it's never stored in Vercel.

**With Google or GitHub (optional).** Each button signs people in once its client ID and secret are set on the API, as secrets, the way [Change a setting later](#1-the-api-on-azure) shows. Use your API's address in the callback URLs.

- **Google:**
  1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials), choose **Create credentials → OAuth client ID**, with application type **Web application**.
  2. Under **Authorized redirect URIs**, add `https://api.tervik.in/api/auth/oauth/google/callback`.
  3. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` to the values it shows. If it asks you to configure the consent screen first, choose **External** and add your app name and email.
- **GitHub:**
  1. In [GitHub Developer settings](https://github.com/settings/developers), choose **OAuth Apps → New OAuth App**.
  2. Set **Homepage URL** to `https://www.tervik.in` and **Authorization callback URL** to `https://api.tervik.in/api/auth/oauth/github/callback`.
  3. Choose **Generate a new client secret**, then set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`.

A Google or GitHub account signs in to the Tervik account with the same verified email, creating it on first sign-in.

## 5. Connect an agent to the hosted API

On **Connect agent**, the endpoint is `https://api.tervik.in`. Agents send events there with the project ID from step 03 of that page:

```bash
TERVIK_PROJECT_ID=PASTE_PROJECT_ID TERVIK_ENDPOINT=https://api.tervik.in python3 agent.py
```

Replace `PASTE_PROJECT_ID` with the real ID, without `<` `>`. [examples/starter-agent](../examples/starter-agent) walks through connecting an agent from start to finish.

The scripts in this repository take the endpoint and the token from the environment. To read the token at a prompt rather than leave it in your shell history:

```bash
read -rs "TERVIK_ADMIN_TOKEN?Admin token: " && export TERVIK_ADMIN_TOKEN TERVIK_ENDPOINT=https://api.tervik.in
```

```bash
cd ~/Projects/tervik && npm run demo:agent -- --persona general
```

## Troubleshooting

| You see | Cause and fix |
| - | - |
| The dashboard on Vercel is an old design | Vercel builds an old branch. Set the production branch to `main` and redeploy. |
| A push deploys to Vercel as **Preview** only | The production branch isn't `main`. Fix it under **Settings → Environments → Production → Branch Tracking**. |
| "API offline" | `VITE_API_URL` is missing or wrong, the dashboard wasn't redeployed after setting it, or the API is still starting up from zero. |
| A request to `/api/...` on `www.tervik.in` returns 404 | Without `VITE_API_URL`, the dashboard asks Vercel instead of the API. |
| "Access denied" after signing in | The token is in **Account session** instead of **Administrator token**, or it was cut short when copied. |
| The browser console shows a CORS error | Add the dashboard's exact address, with `https://` and no trailing slash, to `TERVIK_CORS_ORIGINS` with `az containerapp update --set-env-vars`. |
| `setup` says the image isn't publicly available | Run the **Deploy API** workflow, then make the package public (section 1, steps 2 and 3). |
| `setup` fails with a region or SKU error | Azure for Students allows only some regions. Try `AZURE_LOCATION=southeastasia` or another nearby region. |
| The **Deploy API** workflow fails at **Sign in to Azure** | Run `scripts/deploy_azure.sh github` again; it checks the identity, its role, and the repository variables. |
| `/api/health` says `sqlite` | `DATABASE_URL` isn't set, so data is lost on every restart. |

## Alternative: the API on Railway

Tervik ran on Railway before Azure. To host it there instead:

1. **Create the API service.** In a Railway project, choose **New → GitHub Repo** and pick this repository. In the service's **Settings**, set **Source → Branch** to `main`, **Source → Root Directory** to `/apps/api`, and **Config-as-code → Railway config file** to `/apps/api/railway.json`. That builds from the Dockerfile and health-checks `/api/health`.
2. **Add a database.** Choose **New → Database → PostgreSQL**.
3. **Set variables.** `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `PORT=8000`, `TERVIK_ADMIN_TOKEN` (from `openssl rand -hex 32`), `TERVIK_CORS_ORIGINS`, and `TERVIK_DASHBOARD_URL`, plus any optional keys from section 1.
4. **Domain.** Under **Settings → Networking → Custom Domain**, add `api.tervik.in` with port `8000`, and create the `CNAME api` and `TXT _railway-verify.api` records it shows. Copy the TXT value with its copy button, since Railway cuts it short on screen.
