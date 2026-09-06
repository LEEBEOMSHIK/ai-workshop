import type {
  CompatibilityLane,
  RuntimeNode,
  RuntimeTopology,
} from "./api";

const observationLabels: Record<RuntimeNode["observation"], string> = {
  responding: "응답 중",
  not_observed: "관찰 안 함",
};

const verificationLabels: Record<CompatibilityLane["verification_state"], string> = {
  verified: "검증됨",
  unverified: "미구현/미검증",
};

const kindLabels: Record<RuntimeNode["kind"], string> = {
  process: "애플리케이션 프로세스",
  service: "기반 서비스",
  job: "초기화 작업",
  tool: "온디맨드 도구",
};

export function RuntimeTopologyPage({ topology }: { topology: RuntimeTopology }) {
  const nodeNames = new Map(topology.nodes.map((node) => [node.id, node.display_name]));
  const imageGroups = groupNodesByTarget(topology.nodes);

  return (
    <main className="runtime-topology-shell">
      <header className="runtime-topology-header">
        <p className="eyebrow">PLATFORM RUNTIME</p>
        <h1>시스템 런타임</h1>
        <p>
          Docker Compose의 논리 구성과 검증 경계를 읽기 전용으로 확인합니다. 정적 healthcheck
          선언과 실제 관찰 상태는 서로 다르게 표시합니다.
        </p>
        <dl className="runtime-summary">
          <div><dt>환경</dt><dd>{topology.environment_kind}</dd></div>
          <div><dt>구성 버전</dt><dd>{topology.topology_version}</dd></div>
          <div><dt>스키마</dt><dd>v{topology.schema_version}</dd></div>
        </dl>
      </header>

      <RuntimeSection title="서비스 흐름" description="실행 프로세스와 기반 서비스의 의존 관계입니다.">
        <div className="runtime-card-grid">
          {topology.nodes.map((node) => (
            <article className="runtime-card" aria-label={node.display_name} key={node.id}>
              <div className="runtime-card-heading">
                <div>
                  <p>{kindLabels[node.kind]}</p>
                  <h3>{node.display_name}</h3>
                </div>
                <span className={`runtime-state runtime-state-${node.observation}`}>
                  {observationLabels[node.observation]}
                </span>
              </div>
              <dl className="runtime-detail-list">
                <div><dt>실행 대상</dt><dd>{node.runtime_target}</dd></div>
                <div><dt>역할</dt><dd>{node.process_role}</dd></div>
                <div>
                  <dt>의존</dt>
                  <dd>{displayReferences(node.dependencies, nodeNames)}</dd>
                </div>
                <div>
                  <dt>저장소</dt>
                  <dd>{node.storages.length > 0 ? node.storages.join(", ") : "없음"}</dd>
                </div>
                <div><dt>활성화</dt><dd>{node.activation}</dd></div>
                <div><dt>healthcheck</dt><dd>{node.healthcheck_declared ? "선언됨" : "없음"}</dd></div>
              </dl>
              <div className="runtime-capabilities" aria-label="기능">
                {node.capabilities.map((capability) => <span key={capability}>{capability}</span>)}
              </div>
            </article>
          ))}
        </div>
      </RuntimeSection>

      <RuntimeSection title="이미지 구성" description="같은 target을 사용하는 프로세스를 묶어 보여줍니다.">
        <div className="runtime-card-grid compact">
          {imageGroups.map(([target, nodes]) => (
            <article className="runtime-card" key={target}>
              <h3>{target}</h3>
              <p>{nodes.map((node) => node.display_name).join(", ")}</p>
              <p className="runtime-muted">
                {nodes.some((node) => node.capabilities.includes("pp-structure-v3"))
                  ? "PP-StructureV3 OCR 포함"
                  : "OCR 실행 엔진 미포함"}
              </p>
            </article>
          ))}
        </div>
      </RuntimeSection>

      <RuntimeSection title="데이터 보존" description="물리 경로 대신 저장소의 논리 목적만 표시합니다.">
        <div className="runtime-card-grid compact">
          {topology.storages.map((storage) => (
            <article className="runtime-card" key={storage.id}>
              <div className="runtime-card-heading">
                <h3>{storage.display_name}</h3>
                <span className="runtime-state">{storage.persistence === "persistent" ? "영속" : "임시"}</span>
              </div>
              <p>{storage.purpose}</p>
            </article>
          ))}
        </div>
      </RuntimeSection>

      <RuntimeSection title="실행 호환성" description="운영체제와 장치별 실제 검증 상태를 분리합니다.">
        <div className="runtime-card-grid compact">
          {topology.compatibility.map((lane) => (
            <article className="runtime-card" aria-label={lane.display_name} key={lane.id}>
              <div className="runtime-card-heading">
                <div><p>{lane.device.toUpperCase()}</p><h3>{lane.display_name}</h3></div>
                <span className={`runtime-state runtime-verification-${lane.verification_state}`}>
                  {verificationLabels[lane.verification_state]}
                </span>
              </div>
              <p>{lane.verification_note}</p>
              <p className="runtime-muted">{lane.runtime_target}</p>
            </article>
          ))}
        </div>
      </RuntimeSection>

      <section className="runtime-security" aria-labelledby="runtime-security-title">
        <h2 id="runtime-security-title">보안 경계</h2>
        <p>
          애플리케이션에는 Docker socket을 연결하지 않습니다. 비밀값, 내부 endpoint, host 경로,
          container ID와 raw Compose도 이 화면에 전달하지 않습니다.
        </p>
        <p>로컬 Next.js frontend는 Docker Compose가 아니라 호스트에서 실행합니다.</p>
      </section>
    </main>
  );
}

function RuntimeSection({
  title,
  description,
  children,
}: Readonly<{ title: string; description: string; children: React.ReactNode }>) {
  const id = `runtime-${title.replaceAll(" ", "-")}`;
  return (
    <section className="runtime-section" aria-labelledby={id}>
      <div className="runtime-section-heading">
        <h2 id={id}>{title}</h2>
        <p>{description}</p>
      </div>
      {children}
    </section>
  );
}

function displayReferences(ids: string[], names: Map<string, string>): string {
  if (ids.length === 0) return "없음";
  return ids.map((id) => names.get(id) ?? id).join(", ");
}

function groupNodesByTarget(nodes: RuntimeNode[]): [string, RuntimeNode[]][] {
  const groups = new Map<string, RuntimeNode[]>();
  for (const node of nodes) {
    groups.set(node.runtime_target, [...(groups.get(node.runtime_target) ?? []), node]);
  }
  return [...groups.entries()];
}
