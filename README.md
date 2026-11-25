# Jenkins Build & Deploy UI

A local Flask UI for discovering Jenkins applications/branches, triggering builds,
extracting the generated SNAPSHOT version, and deploying that version.

## Pages
A navigation bar at the top switches between the two pages.

### Build & Deploy (`/`)

Step 1, **Select builds**:

| Option | What it does |
|---|---|
| Application filter + dropdown | Type to filter, then pick an application (`galaxy-fx` is preselected if present) |
| Branch filter + dropdown | Enabled after an application is chosen; type to filter, then pick a branch |
| `+ Add build` | Adds another application/branch row so several builds run in parallel |
| `× Remove` | Removes a row (hidden when only one row remains) |
| `Refresh applications / branches` | Reloads environments and the application list and resets the rows |
| `Build` | Enabled once every row has an application and branch; asks for confirmation, then triggers all builds and shows per-row status |

Two rows with the same application and branch are rejected. Rows are locked while builds run.

Step 2, **Deploy generated builds**:

| Option | What it does |
|---|---|
| Environment | One environment applied to every selected build |
| Build checklist | Each successful build with an extracted version appears as a checked entry (`application / branch - version`); uncheck to skip |
| Duplicate warning | Shown if several builds of the same application are checked, since they would overwrite each other in one environment |
| `Deploy selected` | Enabled when an environment and at least one entry are selected; asks for confirmation, then triggers a deployment per entry |

### Deploy only (`/deploy`)

Deploys the most recent successful build of a branch without triggering a new build.

| Option | What it does |
|---|---|
| Application filter + dropdown | Type to filter, then pick an application |
| Branch filter + dropdown | Type to filter, then pick a branch; the latest successful build number, time and version are then shown |
| Environment | Target environment |
| `Deploy latest build` | Enabled once a latest build is found and an environment is chosen; re-fetches the latest build, asks for confirmation (application, branch, build, version, environment), then triggers the deployment |

## Requirements
- Python 3.10+
- Jenkins API access
- Permission to read jobs and trigger builds/deployments

## Setup (Windows PowerShell)

```powershell
cd jenkins_automation
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Set `JENKINS_USERNAME` to the Jenkins user ID that worked for your API test, and
set `JENKINS_API_TOKEN` to your API token. Do not share `.env`.

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `JENKINS_URL` | `https://jenkins.finzly.net` | Jenkins base URL |
| `JENKINS_USERNAME` | (none, required) | Jenkins user ID |
| `JENKINS_API_TOKEN` | (none, required) | Jenkins API token |
| `BUILD_ROOT` | `job/BankOS/job/Builds` | Folder containing one sub-folder per application |
| `DEPLOY_JOB` | `job/BankOS/job/Deployments/job/Dev-Test/job/k8s-dev-test-deployment` | Shared deployment job |
| `REQUEST_TIMEOUT` | `30` | Seconds before a Jenkins request times out |

## Run

```powershell
py app.py
```

Open http://127.0.0.1:5000

## HTTP API (used by the UI)

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/applications` | List applications under the Builds folder |
| GET | `/api/branches?application=` | List branches of an application |
| GET | `/api/environments` | List allowed deployment environments |
| GET | `/api/latest-build?application=&branch=` | Latest successful build and its SNAPSHOT version |
| POST | `/api/build` | Trigger a build (requires `confirm: true`) |
| GET | `/api/build-status` | Poll queue/build state; returns the version on success |
| POST | `/api/deploy` | Trigger a deployment (requires `confirm: true`) |
| GET | `/api/deploy-status` | Poll deployment queue/build state |

Allowed environments: `dev`, `dev2`, `dev3`, `dev4`, `test`, `test2`, `test3`, `test4`.
The deployment job receives `ENVIRONMENT`, `APPLICATION_NAME` and `DEPLOY_VERSION`.

## Safety behavior
- The UI asks for confirmation before each build and each deployment.
- The backend requires an explicit `confirm: true` for trigger requests.
- `RELEASE_BUILD` is always forced to `false`.
- Other boolean build parameters are sent as `false`.
- The application and branch must be discovered from the configured Jenkins Builds folder.
- The deployment environment must be one of the allowed values above.
- Deployment is enabled only after a successful build and extraction of a version matching
  `<branch>.<build>.SNAPSHOT` (the docker image tag, e.g. `feature-BFX-SWAPS.18.SNAPSHOT`),
  or when using the Deploy-only page, a version found in the latest successful build.
- Queue and build URLs returned by or sent to the backend must belong to the configured Jenkins host.
- The web server binds to localhost only.

## Notes / limitations
- This version expects the Jenkins structure:
  `BankOS/Builds/<application>/<branch>`.
- It uses the existing shared deployment job:
  `BankOS/Deployments/Dev-Test/k8s-dev-test-deployment`.
- Build parameter definitions are read from each selected job's API.
- The version parser recognizes docker-tag style `<branch>.<build>.SNAPSHOT` versions
  (including `release-*.SNAPSHOT`), matching what galaxy-fx prints. Maven `-SNAPSHOT`
  artifact names are not matched. If other applications use a different version format,
  extend `VERSION_PATTERN` after inspecting their console output.
- The Jenkins API account needs Read and Build permissions on the relevant jobs.
- This is a local internal utility, not a hardened multi-user production service.
