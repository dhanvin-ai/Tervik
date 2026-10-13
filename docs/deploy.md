# Deploy: dashboard on Vercel, API on Railway

Tervik has two parts:

- **The dashboard** (`apps/web`) is static files. Vercel serves it.
- **The API** (`apps/api`) is a FastAPI service with a database. Railway runs it, alongside a Postgres database.

The dashboard calls the API at the address in `VITE_API_URL`, which is set when the dashboard is built.

This is how Tervik itself is hosted:

| Part | Address | Host |
| - | - | - |
| Dashboard | https://www.tervik.in (`tervik.in` redirects to it) | Vercel |
| API | https://api.tervik.in | Railway |
| Database | Private to the Railway project | Railway Postgres |
| DNS | Records for `tervik.in` | GoDaddy |

Follow the sections in order. Steps that name `tervik.in` use your own domain in its place.

## 1. The API on Railway

1. **Create the API service.** In your Railway project, choose **New → GitHub Repo** and pick this repository.
2. **Point it at the API.** Click the new service's card to open its panel, then open **Settings**:
   - **Source → Branch:** the branch to deploy, `ui-maritime-theme` until it's merged into `main`.
   - **Source → Root Directory:** `/apps/api`.
   - **Config-as-code → Railway config file:** `/apps/api/railway.json`. This builds the service from the Dockerfile and health-checks `/api/health`.
3. **Add a database.** On the project canvas, choose **New → Database → PostgreSQL**. Tervik creates its tables on first start.
4. **Set variables.** In the API service's panel, open **Variables** (the tab next to **Settings**) and add these with **+ New Variable**:

   | Variable | Value |
   | - | - |
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}`, a reference to the database |
   | `PORT` | `8000` |
   | `TERVIK_ADMIN_TOKEN` | A long random secret. Create one with `openssl rand -hex 32`. Without it, anyone could read the data. |
   | `TERVIK_CORS_ORIGINS` | Every address the dashboard is opened at, separated by commas: `https://www.tervik.in,https://tervik.in,https://tervik-seven.vercel.app` |
   | `TERVIK_DASHBOARD_URL` | The dashboard's main address, `https://www.tervik.in`. Alert messages link to it. |
   | `TERVIK_DEMO_ENABLED` | Optional. `true` allows **Explore sample workspace**. |
   | `TERVIK_SIGNUP_ENABLED` | Optional. Sign-up is open by default: anyone can create an account, which gets its own private workspace. `false` closes it. |
   | `ANTHROPIC_API_KEY` | Optional. Turns on intent and policy checks, and Claude in **Chat**. |
   | `OPENAI_API_KEY` | Optional. Adds an OpenAI model to **Chat**. |

5. **Deploy.** Choose **Deploy** in the banner that lists the changes, and wait for the deployment to show **Success**.
6. **Give it a Railway address.** Under **Settings → Networking → Public networking**, choose **Generate Domain** and enter port `8000`. Railway creates an address such as `https://humorous-connection-production-917a.up.railway.app`.
7. **Check it:**

   ```bash
   curl https://YOUR-SERVICE.up.railway.app/api/health
   ```

   It returns `{"status":"ok","storage":"postgresql","analysis_mode":"rule_based"}`. If `storage` says `sqlite`, `DATABASE_URL` isn't set.

**Remove the old service.** A service built from the repository root, such as `@tervik/web`, builds the dashboard rather than the API. Delete it under its **Settings → Danger** so it stops using credits.

**Background jobs (optional).** Alerts and scheduled classification run as two more services from the same repository, each with the same root directory and variables. Set their start commands to `python -m app.jobs alerts` and `python -m app.jobs classify`.

**Chat on a hosted API.** The **Chat** page's free model, Ollama, runs on your own computer, not on Railway. On the hosted API, Chat needs `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.

## 2. The dashboard on Vercel

1. **Import the repository.** Skip this if the Vercel project already exists. Otherwise choose **Add New → Project**, import this repository, set **Root Directory** to `apps/web`, and keep the **Vite** framework preset. The dashboard builds on its own: the skill download in `apps/web/public` is committed.
2. **Production branch.** Under **Settings → Git → Production Branch**, choose `ui-maritime-theme` until it's merged into `main`.
3. **API address.** Under **Settings → Environment Variables → Add New**:
   - **Type:** **Config**, not **Secret**. The dashboard runs in the browser, so the API address is public by design, and Vercel refuses a `VITE_` variable marked secret.
   - **Key:** `VITE_API_URL`. Keep the `VITE_` prefix; without it the dashboard never sees the value.
   - **Value:** the API address with no trailing slash: `https://api.tervik.in`, or the Railway address from step 6 if you aren't using your own domain.
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

2. **API domain (Railway).** In the API service, open **Settings → Networking → Custom Domain**, enter `api.tervik.in` and port `8000`. It then shows **Waiting for DNS update**. Choose **Show DNS records** to see the two records to create:

   | Type | Name | Value |
   | - | - | - |
   | CNAME | `api` | A target such as `wss8eszy.up.railway.app` |
   | TXT | `_railway-verify.api` | `railway-verify=` followed by a long code |

   Railway cuts the TXT value short on screen. Copy it with the copy button instead of typing it.

3. **DNS records (GoDaddy).** Open **Domain → tervik.in → DNS → DNS Records**:
   - **Delete** the `A @ Parked` record with its trash icon. GoDaddy won't let you edit it, and leaving it beside Vercel's record would send some visitors to the parking page.
   - **Add New Record:** `A`, name `@`, value Vercel's IP.
   - **Edit** the `CNAME www` record (its value is `tervik.in.`) with its pencil icon, and change the value to Vercel's CNAME target.
   - **Add New Record:** `CNAME`, name `api`, value Railway's target.
   - **Add New Record:** `TXT`, name `_railway-verify.api` (GoDaddy adds `.tervik.in` itself), value Railway's full `railway-verify=…` code.
   - Leave the `NS`, `SOA`, `_domainconnect`, and `_dmarc` records alone.

   Changes usually apply within minutes, but can take a few hours. Both hosts then issue HTTPS certificates on their own.

4. **Point the parts at each other.**
   - **Railway:** `TERVIK_CORS_ORIGINS` and `TERVIK_DASHBOARD_URL` as in section 1, step 4. Deploy.
   - **Vercel:** `VITE_API_URL=https://api.tervik.in`, then redeploy, as in section 2.

5. **Check everything:**

   ```bash
   dig +short A tervik.in
   ```

   Only Vercel's IP, `216.198.79.1`. Two more addresses mean the parked record is still there.

   ```bash
   dig +short CNAME www.tervik.in && dig +short CNAME api.tervik.in
   ```

   Vercel's and Railway's targets.

   ```bash
   curl https://api.tervik.in/api/health
   ```

   `"status":"ok"` and `"storage":"postgresql"`.

   ```bash
   curl -s -o /dev/null -D - -X OPTIONS -H "Origin: https://www.tervik.in" -H "Access-Control-Request-Method: GET" https://api.tervik.in/api/projects | grep -i access-control-allow-origin
   ```

   `access-control-allow-origin: https://www.tervik.in`. No output means the address is missing from `TERVIK_CORS_ORIGINS`.

## 4. Sign in

**With an account.** Open https://www.tervik.in and choose **Sign up** (or **Log in**). Each account gets its own private workspace. Sign-up is open to anyone unless `TERVIK_SIGNUP_ENABLED=false`.

**As the operator, seeing every project.** On the **Log in** page, choose **Use the administrator token** and paste the `TERVIK_ADMIN_TOKEN` value from Railway's **Variables** into **Administrator token**. Leave **Account session** empty: a value there is used instead of the token. The token lasts for that browser tab only, and it's never stored in Vercel.

**With Google or GitHub (optional).** Each button appears on the sign-in page once its client ID and secret are set on the Railway API service. Use your API's address in the callback URLs.

- **Google:**
  1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials), choose **Create credentials → OAuth client ID**, with application type **Web application**.
  2. Under **Authorized redirect URIs**, add `https://api.tervik.in/api/auth/oauth/google/callback`.
  3. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` to the values it shows. If it asks you to configure the consent screen first, choose **External** and add your app name and email.
- **GitHub:**
  1. In [GitHub Developer settings](https://github.com/settings/developers), choose **OAuth Apps → New OAuth App**.
  2. Set **Homepage URL** to `https://www.tervik.in` and **Authorization callback URL** to `https://api.tervik.in/api/auth/oauth/github/callback`.
  3. Choose **Generate a new client secret**, then set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`.

Deploy after setting them. A Google or GitHub account signs in to the Tervik account with the same verified email, creating it on first sign-in.

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
| The dashboard on Vercel is the old design | Vercel builds `main`. Set **Production Branch** to `ui-maritime-theme` and redeploy. |
| "API offline" | `VITE_API_URL` is missing or wrong, or the dashboard wasn't redeployed after setting it. |
| A request to `/api/...` on `www.tervik.in` returns 404 | Same cause: without `VITE_API_URL`, the dashboard asks Vercel instead of the API. |
| "Access denied" after signing in | The token is in **Account session** instead of **Administrator token**, or it was cut short when copied. |
| The browser console shows a CORS error | Add the dashboard's exact address, with `https://` and no trailing slash, to `TERVIK_CORS_ORIGINS`, then deploy on Railway. |
| Railway shows **Waiting for DNS update** for hours | Check `dig +short CNAME api.tervik.in` and `dig +short TXT _railway-verify.api.tervik.in` against the values Railway shows. |
| Railway says you hit the custom domain limit | Your Railway plan allows no more custom domains. The one you have is enough for `api.tervik.in`. |
| `/api/health` says `sqlite` | `DATABASE_URL` isn't set to `${{Postgres.DATABASE_URL}}`, so data is lost on every deploy. |
