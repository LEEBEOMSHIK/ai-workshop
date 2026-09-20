"""Exercise synthetic TXT upload and experimental BM25/E5 hybrid in the local sandbox."""

import json
import time
from typing import Any

import httpx
import yaml
from prepare_rag_sandbox import REPOSITORY, ROOT, load_environment, write_json

SYNTHETIC_TEXT = (
    b"Synthetic RAG sandbox fixture. The quartz lighthouse stores blue lanterns. "
    b"Blue lanterns signal safe passage for synthetic ships. This is public test data only."
)


def checked(response: httpx.Response) -> Any:
    if response.status_code >= 400:
        try:
            code = response.json().get("error", {}).get("code", "http_error")
        except ValueError:
            code = "http_error"
        raise RuntimeError(f"sandbox_http_{response.status_code}:{code}")
    return response.json()


def profile(
    client: httpx.Client, kind: str, filename: str, **config_updates: str
) -> str:
    definition = yaml.safe_load(
        (REPOSITORY / "model-profiles/rag" / kind / filename).read_text()
    )
    definition["name"] = "sandbox-" + definition["name"]
    definition["config"].update(config_updates)
    if kind == "retrieval":
        # The extractive configuration contract accepts disabled-only metadata;
        # the committed catalog additionally carries an older optional flag.
        definition["name"] = "sandbox-extractive-" + definition["name"]
        definition["config"]["reranker"] = {"enabled": False}
    current = checked(client.get(f"/api/v1/rag/profiles/{kind}"))
    for item in current:
        if (
            item["name"] == definition["name"]
            and item["version"] == definition["version"]
        ):
            if item["config"] != definition["config"]:
                raise RuntimeError("sandbox_profile_conflict")
            return str(item["id"])
    response = checked(
        client.post(
            f"/api/v1/admin/rag/profiles/{kind}/yaml",
            json={"content": yaml.safe_dump(definition)},
        )
    )
    return str(response["id"])


def search(
    client: httpx.Client, state: dict[str, Any], configuration_id: str, label: str
) -> None:
    for _ in range(120):
        response = client.post(
            "/api/v1/rag/search",
            json={
                "query": "quartz lighthouse blue lanterns",
                "configuration_id": configuration_id,
                "workspace_ids": [state["workspace_id"]],
                "document_ids": [state["document_id"]],
                "experimental": True,
            },
        )
        if response.status_code == 409 and response.json().get("error", {}).get(
            "code"
        ) in {"configuration_not_ready", "selected_documents_not_ready"}:
            time.sleep(2)
            continue
        result = checked(response)
        answer = result.get("answer")
        if answer is None or answer["source"]["document_id"] != state["document_id"]:
            raise RuntimeError("sandbox_search_missing_exact_source")
        if answer["source"]["asset_version_id"] != state["asset_version_id"]:
            raise RuntimeError("sandbox_search_wrong_source_version")
        selected = result.get("selected_scope")
        if (
            not selected
            or len(selected["identities"]) != 1
            or selected["identities"][0]["document_id"] != state["document_id"]
            or selected["identities"][0]["asset_version_id"]
            != state["asset_version_id"]
            or selected["identities"][0]["projection_id"]
            != answer["source"]["projection_id"]
        ):
            raise RuntimeError("sandbox_selected_scope_mismatch")
        if result["generation"]["status"] != "not_requested":
            raise RuntimeError("sandbox_unexpected_generation")
        state[label] = {
            "http_status": response.status_code,
            "status": result["status"],
            "document_id": answer["source"]["document_id"],
            "asset_version_id": answer["source"]["asset_version_id"],
            "projection_id": answer["source"]["projection_id"],
            "generation": result["generation"]["status"],
            "selected_scope_verified": True,
        }
        write_json(ROOT / "smoke-state.json", state)
        print(label + "_exact_source_passed", flush=True)
        return
    raise RuntimeError("sandbox_search_readiness_timeout")


def main() -> None:
    load_environment()  # Refuse state aimed outside the exact sandbox before HTTP calls.
    credentials = json.loads((ROOT / "credentials.json").read_text())
    state_path = ROOT / "smoke-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    with httpx.Client(base_url="http://127.0.0.1:18000", timeout=180) as client:
        if checked(client.get("/api/v1/setup/status"))["setup_required"]:
            checked(
                client.post(
                    "/api/v1/setup/owner",
                    json={
                        **credentials,
                        "password_confirmation": credentials["password"],
                    },
                )
            )
        else:
            checked(
                client.post(
                    "/api/v1/auth/login",
                    json={key: credentials[key] for key in ("email", "password")},
                )
            )
        if "workspace_id" not in state:
            workspaces = checked(client.get("/api/v1/workspaces"))
            state["workspace_id"] = next(
                item["id"] for item in workspaces if item["kind"] == "personal"
            )
        configurations = checked(client.get("/api/v1/rag/configurations"))
        state["baseline_configuration_id"] = next(
            item["id"] for item in configurations if item["is_system"]
        )
        if "document_id" not in state:
            uploaded = checked(
                client.post(
                    f"/api/v1/workspaces/{state['workspace_id']}/documents",
                    files={
                        "file": (
                            "synthetic-rag-readiness.txt",
                            SYNTHETIC_TEXT,
                            "text/plain",
                        )
                    },
                )
            )
            state.update(
                document_id=uploaded["id"],
                asset_version_id=uploaded["latest_version_id"],
                job_id=uploaded["job_id"],
            )
            write_json(state_path, state)
            print("synthetic_txt_uploaded", flush=True)
        documents = checked(
            client.get(f"/api/v1/workspaces/{state['workspace_id']}/documents")
        )
        document = next(
            item for item in documents if item["id"] == state["document_id"]
        )
        state["asset_version_id"] = document["latest_version_id"]
        for _ in range(120):
            job = checked(client.get("/api/v1/jobs/" + state["job_id"]))
            if job["status"] == "succeeded":
                break
            if job["status"] == "failed":
                raise RuntimeError(
                    "sandbox_verification_failed:" + str(job["error_code"])
                )
            time.sleep(2)
        else:
            raise RuntimeError("sandbox_verification_timeout")
        search(client, state, state["baseline_configuration_id"], "bm25")
        indexing = profile(client, "indexing", "e5-structure-aware-v2.yaml")
        retrieval = profile(
            client, "retrieval", "hybrid-rrf.yaml", indexing_profile_id=indexing
        )
        if "hybrid_configuration_id" not in state:
            existing = next(
                (
                    item
                    for item in configurations
                    if item["name"] == "Sandbox E5 hybrid"
                ),
                None,
            )
            configuration = existing or checked(
                client.post(
                    "/api/v1/rag/configurations",
                    json={
                        "name": "Sandbox E5 hybrid",
                        "indexing_profile_id": indexing,
                        "retrieval_profile_id": retrieval,
                        "answer_policy": {
                            "mode": "extractive",
                            "min_semantic_score": 0.2,
                            "min_keyword_coverage": 0.2,
                        },
                        "workspace_ids": [state["workspace_id"]],
                    },
                )
            )
            state["hybrid_configuration_id"] = configuration["id"]
            write_json(state_path, state)
        search(client, state, state["hybrid_configuration_id"], "hybrid")
        print(
            "sandbox_search_smoke_passed; external_generation_not_requested", flush=True
        )


if __name__ == "__main__":
    main()
