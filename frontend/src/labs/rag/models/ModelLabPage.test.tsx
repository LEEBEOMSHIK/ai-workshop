import { render, screen } from "@testing-library/react";

import { ModelLabPage } from "./ModelLabPage";

describe("ModelLabPage", () => {
  it("separates model and profile kinds without exposing execution controls", () => {
    render(
      <ModelLabPage
        initialModels={[
          {
            id: "embedding-1",
            kind: "embedding",
            name: "embedding-baseline",
            version: 1,
            config: { dimension: 768 },
          },
          {
            id: "llm-1",
            kind: "llm",
            name: "answer-model",
            version: 2,
            config: { endpoint_env: "LOCAL_LLM_ENDPOINT" },
          },
        ]}
        initialProfiles={[
          {
            id: "retrieval-1",
            kind: "retrieval",
            name: "hybrid-rrf",
            version: 1,
            config: { bm25: {}, dense: {}, rrf: {}, indexing_profile_id: "indexing-1" },
            bindings: [],
            evaluation_state: "passed",
            is_default: true,
          },
        ]}
      />,
    );

    expect(screen.getByRole("heading", { name: "임베딩 모델" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "리랭커 모델" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "LLM 모델" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "색인 프로파일" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "검색 프로파일" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "생성 프로파일" })).toBeVisible();
    expect(screen.getByText("embedding-baseline")).toBeVisible();
    expect(screen.getByText("hybrid-rrf")).toBeVisible();
    expect(screen.getByText("기본 사용")).toBeVisible();
    expect(screen.getByRole("button", { name: "모델 버전 등록" })).toBeVisible();
    expect(screen.getByRole("button", { name: "YAML 프로파일 등록" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /실행/ })).not.toBeInTheDocument();
  });
});
