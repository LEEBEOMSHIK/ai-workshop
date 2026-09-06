import { render, screen, within } from "@testing-library/react";

import type { RuntimeTopology } from "./api";
import { RuntimeTopologyPage } from "./RuntimeTopologyPage";

const topology: RuntimeTopology = {
  schema_version: 1,
  topology_version: "local-compose-v1",
  environment_kind: "local-compose",
  nodes: [
    {
      id: "api",
      display_name: "FastAPI 애플리케이션",
      kind: "process",
      runtime_target: "runtime-core",
      process_role: "http-api",
      dependencies: ["postgres", "redis"],
      storages: ["object-data"],
      capabilities: ["http-api", "authentication"],
      activation: "default",
      healthcheck_declared: true,
      observation: "responding",
    },
    {
      id: "worker",
      display_name: "OCR 작업자",
      kind: "process",
      runtime_target: "runtime-ocr-cpu",
      process_role: "celery-worker",
      dependencies: ["postgres", "redis", "elasticsearch"],
      storages: ["object-data", "model-cache"],
      capabilities: ["pp-structure-v3"],
      activation: "default",
      healthcheck_declared: true,
      observation: "not_observed",
    },
    {
      id: "postgres",
      display_name: "PostgreSQL",
      kind: "service",
      runtime_target: "postgres:17-alpine",
      process_role: "relational-database",
      dependencies: [],
      storages: [],
      capabilities: ["metadata"],
      activation: "default",
      healthcheck_declared: true,
      observation: "not_observed",
    },
    {
      id: "redis",
      display_name: "Redis",
      kind: "service",
      runtime_target: "redis:8-alpine",
      process_role: "task-broker",
      dependencies: [],
      storages: [],
      capabilities: ["celery-broker"],
      activation: "default",
      healthcheck_declared: true,
      observation: "not_observed",
    },
    {
      id: "elasticsearch",
      display_name: "Elasticsearch",
      kind: "service",
      runtime_target: "docker.elastic.co/elasticsearch/elasticsearch:9.5.2",
      process_role: "hybrid-search-engine",
      dependencies: [],
      storages: [],
      capabilities: ["bm25", "dense-vector"],
      activation: "default",
      healthcheck_declared: true,
      observation: "not_observed",
    },
  ],
  storages: [
    {
      id: "object-data",
      display_name: "문서 객체 저장 볼륨",
      purpose: "별도 컨테이너가 아닌 영속 볼륨",
      persistence: "persistent",
    },
    {
      id: "model-cache",
      display_name: "모델 캐시 볼륨",
      purpose: "검증된 로컬 모델 artifact",
      persistence: "persistent",
    },
  ],
  compatibility: [
    {
      id: "windows-cpu",
      display_name: "Windows CPU",
      device: "cpu",
      runtime_target: "local-python-ocr-cpu",
      verification_state: "verified",
      verification_note: "한국어 실제 추론 통과",
    },
    {
      id: "linux-gpu",
      display_name: "Linux GPU",
      device: "gpu",
      runtime_target: "runtime-ocr-gpu",
      verification_state: "unverified",
      verification_note: "별도 GPU engine과 실제 NVIDIA 환경 필요",
    },
  ],
};

describe("RuntimeTopologyPage", () => {
  it("renders service relationships and honest observation states", () => {
    render(<RuntimeTopologyPage topology={topology} />);

    expect(screen.getByRole("heading", { name: "시스템 런타임" })).toBeInTheDocument();
    const worker = screen.getByRole("article", { name: "OCR 작업자" });
    expect(within(worker).getByText("runtime-ocr-cpu")).toBeInTheDocument();
    expect(within(worker).getByText("관찰 안 함")).toBeInTheDocument();
    expect(within(worker).getByText("PostgreSQL, Redis, Elasticsearch")).toBeInTheDocument();
    expect(screen.getByText("응답 중")).toBeInTheDocument();
  });

  it("distinguishes persistent volumes and unverified GPU compatibility", () => {
    render(<RuntimeTopologyPage topology={topology} />);

    expect(screen.getByText("별도 컨테이너가 아닌 영속 볼륨")).toBeInTheDocument();
    const gpu = screen.getByRole("article", { name: "Linux GPU" });
    expect(within(gpu).getByText("미구현/미검증")).toBeInTheDocument();
    expect(within(gpu).getByText(/별도 GPU engine/)).toBeInTheDocument();
  });

  it("shows the security boundary without implying Docker control", () => {
    render(<RuntimeTopologyPage topology={topology} />);

    expect(screen.getByText(/Docker socket을 연결하지 않습니다/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /시작|중지|재시작/ })).not.toBeInTheDocument();
  });
});
