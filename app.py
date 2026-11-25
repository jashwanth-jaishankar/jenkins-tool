import os
import re
import time
from urllib.parse import urljoin, urlparse, quote

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)

JENKINS_URL = os.getenv("JENKINS_URL", "https://jenkins.finzly.net").rstrip("/")
JENKINS_USERNAME = os.getenv("JENKINS_USERNAME", "")
JENKINS_API_TOKEN = os.getenv("JENKINS_API_TOKEN", "")
BUILD_ROOT = os.getenv("BUILD_ROOT", "job/BankOS/job/Builds")
DEPLOY_JOB = os.getenv(
    "DEPLOY_JOB",
    "job/BankOS/job/Deployments/job/Dev-Test/job/k8s-dev-test-deployment"
)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
VERSION_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*\.SNAPSHOT")

ENVIRONMENT_CHOICES = ["dev", "dev2", "dev3", "dev4", "test", "test2", "test3", "test4"]


class JenkinsError(Exception):
    pass


def jenkins_session():
    if not JENKINS_USERNAME or not JENKINS_API_TOKEN:
        raise JenkinsError(
            "Jenkins credentials are missing. Configure JENKINS_USERNAME "
            "and JENKINS_API_TOKEN in the .env file."
        )
    session = requests.Session()
    session.auth = (JENKINS_USERNAME, JENKINS_API_TOKEN)
    session.headers.update({"Accept": "application/json"})
    return session


def job_url(*segments):
    encoded = "/".join("job/" + quote(str(s), safe="") for s in segments)
    return f"{JENKINS_URL}/{encoded}"


def api_get(session, url, accept_json=True):
    headers = {"Accept": "application/json"} if accept_json else {}
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    if response.status_code == 401:
        raise JenkinsError("Jenkins authentication failed (401). Check username and API token.")
    if response.status_code == 403:
        raise JenkinsError("Jenkins denied this request (403). Check your job permissions.")
    response.raise_for_status()
    return response


def get_json(session, url):
    return api_get(session, url).json()


def get_crumb(session):
    # Jenkins may have CSRF protection enabled. API-token authentication often
    # exempts crumb checks, but retrieve a crumb when the issuer is available.
    response = session.get(
        f"{JENKINS_URL}/crumbIssuer/api/json",
        timeout=REQUEST_TIMEOUT
    )
    if response.status_code == 200:
        data = response.json()
        return {data["crumbRequestField"]: data["crumb"]}
    if response.status_code in (403, 404):
        return {}
    response.raise_for_status()
    return {}


def post_build(session, url, parameters):
    headers = get_crumb(session)
    response = session.post(
        url,
        data=parameters,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
        allow_redirects=False
    )
    if response.status_code == 401:
        raise JenkinsError("Jenkins authentication failed while triggering the job (401).")
    if response.status_code == 403:
        raise JenkinsError("Jenkins rejected the trigger (403). Check Build permission.")
    if response.status_code not in (200, 201, 202, 302):
        raise JenkinsError(
            f"Jenkins trigger failed with HTTP {response.status_code}: {response.text[:300]}"
        )
    location = response.headers.get("Location")
    if not location:
        raise JenkinsError("Jenkins accepted the request but did not return a queue Location.")
    queue_url = urljoin(JENKINS_URL + "/", location)
    parsed = urlparse(queue_url)
    if parsed.netloc != urlparse(JENKINS_URL).netloc:
        raise JenkinsError("Jenkins returned an unexpected queue URL.")
    return queue_url.rstrip("/") + "/"


def discover_applications():
    session = jenkins_session()
    root_url = f"{JENKINS_URL}/{BUILD_ROOT}/api/json?tree=jobs[name,_class]"
    root = get_json(session, root_url)
    jobs = root.get("jobs", [])
    return sorted(
        [item["name"] for item in jobs if item.get("name")],
        key=str.casefold
    )


def discover_branches(application):
    if application not in discover_applications():
        raise JenkinsError("Unknown application. Refresh the application list.")
    session = jenkins_session()
    app_api = f"{job_url('BankOS', 'Builds', application)}/api/json?tree=jobs[name,_class]"
    data = get_json(session, app_api)
    branches = [
        item.get("name")
        for item in data.get("jobs", [])
        if item.get("name")
    ]
    return sorted(branches, key=str.casefold)


def parameter_definitions(session, url):
    data = get_json(session, f"{url}/api/json?tree=property[parameterDefinitions[name,type,defaultParameterValue[value]]]")
    definitions = []
    for prop in data.get("property", []):
        definitions.extend(prop.get("parameterDefinitions", []))
    return definitions


def find_version(session, build_url):
    # Stream the console and keep the last match without holding it all in memory.
    version = None
    url = f"{build_url.rstrip('/')}/consoleText"
    headers = {"Accept": "text/plain"}
    with session.get(url, headers=headers, timeout=REQUEST_TIMEOUT, stream=True) as response:
        if response.status_code == 401:
            raise JenkinsError("Jenkins authentication failed (401). Check username and API token.")
        if response.status_code == 403:
            raise JenkinsError("Jenkins denied this request (403). Check your job permissions.")
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            found = VERSION_PATTERN.findall(line)
            if found:
                version = found[-1]
    return version


def queue_and_build_status(session, queue_url, build_url=None):
    jenkins_netloc = urlparse(JENKINS_URL).netloc
    if urlparse(queue_url).netloc != jenkins_netloc:
        raise JenkinsError("Invalid queue URL.")
    if build_url and urlparse(build_url).netloc != jenkins_netloc:
        raise JenkinsError("Invalid build URL.")

    if not build_url:
        queue = get_json(session, f"{queue_url.rstrip('/')}/api/json")
        executable = queue.get("executable")
        if not executable:
            if queue.get("cancelled"):
                return {"state": "CANCELLED", "message": "Jenkins queue item was cancelled."}
            return {"state": "QUEUED", "message": "Waiting for a Jenkins executor..."}
        build_url = executable.get("url")
        if not build_url:
            raise JenkinsError("Jenkins queue item has no build URL yet.")

    build = get_json(session, f"{build_url.rstrip('/')}/api/json?tree=number,building,result")
    if build.get("building"):
        return {
            "state": "RUNNING",
            "number": build.get("number"),
            "url": build_url,
            "message": f"Build #{build.get('number')} is running."
        }

    result = build.get("result")
    # The version is only used after a successful build, so skip the console otherwise.
    version = find_version(session, build_url) if result == "SUCCESS" else None

    return {
        "state": result or "UNKNOWN",
        "number": build.get("number"),
        "url": build_url,
        "version": version,
        "message": f"Build #{build.get('number')} finished: {result or 'UNKNOWN'}.",
        "version_found": bool(version)
    }


@app.get("/")
def index():
    return render_template("build.html")


@app.get("/deploy")
def deploy_page():
    return render_template("deploy.html")


@app.get("/api/latest-build")
def latest_build():
    application = request.args.get("application", "").strip()
    branch = request.args.get("branch", "").strip()
    if not application or not branch:
        return jsonify({"error": "application and branch are required."}), 400
    try:
        if branch not in discover_branches(application):
            return jsonify({"error": "Unknown branch. Refresh the branch list."}), 400
        session = jenkins_session()
        url = job_url("BankOS", "Builds", application, branch)
        # Always read straight from Jenkins so the newest successful build is used.
        try:
            build = get_json(session, f"{url}/lastSuccessfulBuild/api/json?tree=number,url,timestamp,result")
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return jsonify({"error": f"No successful build exists yet for {application} / {branch}."}), 404
            raise
        if urlparse(build.get("url", "")).netloc != urlparse(JENKINS_URL).netloc:
            raise JenkinsError("Jenkins returned an unexpected build URL.")
        version = find_version(session, build["url"])
        if not version:
            return jsonify({
                "error": f"Latest successful build #{build.get('number')} has no SNAPSHOT version in its console."
            }), 404
        return jsonify({
            "application": application,
            "branch": branch,
            "build_number": build.get("number"),
            "build_url": build.get("url"),
            "timestamp": build.get("timestamp"),
            "version": version
        })
    except JenkinsError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("Failed to fetch latest build for %s/%s", application, branch)
        return jsonify({"error": str(exc)}), 500


@app.get("/api/applications")
def applications():
    try:
        return jsonify({"applications": discover_applications()})
    except Exception as exc:
        app.logger.exception("Failed to discover Jenkins applications")
        return jsonify({"error": str(exc)}), 500


@app.get("/api/branches")
def branches():
    application = request.args.get("application", "").strip()
    if not application:
        return jsonify({"error": "application is required."}), 400
    try:
        return jsonify({"application": application, "branches": discover_branches(application)})
    except Exception as exc:
        app.logger.exception("Failed to discover branches for %s", application)
        return jsonify({"error": str(exc)}), 500


@app.get("/api/environments")
def environments():
    return jsonify({"environments": ENVIRONMENT_CHOICES})


@app.post("/api/build")
def trigger_build():
    payload = request.get_json(force=True)
    if payload.get("confirm") is not True:
        return jsonify({"error": "Build confirmation is required."}), 400

    application = payload.get("application", "")
    branch = payload.get("branch", "")
    try:
        allowed_branches = discover_branches(application)
    except JenkinsError as exc:
        return jsonify({"error": str(exc)}), 400
    if branch not in allowed_branches:
        return jsonify({"error": "Unknown branch. Refresh the branch list."}), 400

    session = jenkins_session()
    url = job_url("BankOS", "Builds", application, branch)
    try:
        definitions = parameter_definitions(session, url)

        params = {}
        for definition in definitions:
            name = definition.get("name")
            if definition.get("type") == "BooleanParameterDefinition":
                params[name] = "false"

        # Guardrail: never allow a release build from this automation.
        if any(d.get("name") == "RELEASE_BUILD" for d in definitions):
            params["RELEASE_BUILD"] = "false"

        # Jobs without parameters reject /buildWithParameters with HTTP 400.
        endpoint = "buildWithParameters" if definitions else "build"
        queue_url = post_build(session, f"{url}/{endpoint}", params)
    except JenkinsError as exc:
        return jsonify({"error": str(exc)}), 400
    except requests.Timeout:
        app.logger.exception("Jenkins timed out while triggering %s/%s", application, branch)
        return jsonify({"error": "Jenkins timed out. Check that the build was not queued, then retry."}), 504
    except requests.RequestException as exc:
        app.logger.exception("Jenkins request failed for %s/%s", application, branch)
        return jsonify({"error": f"Could not reach Jenkins: {exc}"}), 502
    return jsonify({"queue_url": queue_url, "application": application, "branch": branch})


@app.get("/api/build-status")
def build_status():
    queue_url = request.args.get("queue_url", "")
    build_url = request.args.get("build_url") or None
    if not queue_url:
        return jsonify({"error": "queue_url is required."}), 400
    try:
        return jsonify(queue_and_build_status(jenkins_session(), queue_url, build_url))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/deploy")
def trigger_deploy():
    payload = request.get_json(force=True)
    if payload.get("confirm") is not True:
        return jsonify({"error": "Deployment confirmation is required."}), 400

    application = payload.get("application", "")
    environment = payload.get("environment", "")
    version = payload.get("version", "")

    if not application or not version or not VERSION_PATTERN.fullmatch(version):
        return jsonify({"error": "A valid generated SNAPSHOT version is required."}), 400
    if environment not in ENVIRONMENT_CHOICES:
        return jsonify({"error": "Invalid deployment environment."}), 400

    # Validate the application against the Jenkins Builds folder.
    if application not in discover_applications():
        return jsonify({"error": "Unknown application. Refresh the application list."}), 400

    session = jenkins_session()
    deploy_url = f"{JENKINS_URL}/{DEPLOY_JOB}"
    params = {
        "ENVIRONMENT": environment,
        "APPLICATION_NAME": application,
        "DEPLOY_VERSION": version
    }
    queue_url = post_build(session, f"{deploy_url}/buildWithParameters", params)
    return jsonify({
        "queue_url": queue_url,
        "application": application,
        "environment": environment,
        "version": version
    })


@app.get("/api/deploy-status")
def deploy_status():
    queue_url = request.args.get("queue_url", "")
    build_url = request.args.get("build_url") or None
    if not queue_url:
        return jsonify({"error": "queue_url is required."}), 400
    try:
        return jsonify(queue_and_build_status(jenkins_session(), queue_url, build_url))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    # Local-only listener; do not expose this development server to a network.
    app.run(host="127.0.0.1", port=5000, debug=False)
