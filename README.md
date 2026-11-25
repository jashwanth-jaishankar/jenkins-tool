# Jenkins Build & Deploy UI

A local Flask UI for discovering Jenkins applications/branches, triggering builds,
extracting the generated SNAPSHOT version, and deploying that version.

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

## Run

```powershell
py app.py
```

Open http://127.0.0.1:5000

## Safety behavior
- The UI asks for confirmation before each build and each deployment.
- The backend requires an explicit `confirm: true` for trigger requests.
- `RELEASE_BUILD` is always forced to `false`.
- Other boolean build parameters are sent as `false`.
- The application and branch must be discovered from the configured Jenkins Builds folder.
- Deployment is enabled only after a successful build and extraction of a version matching
  `<branch>.<build>.SNAPSHOT` (the docker image tag, e.g. `feature-BFX-SWAPS.18.SNAPSHOT`).
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
