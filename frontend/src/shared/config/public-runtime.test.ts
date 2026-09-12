import {
  decideFrontendRuntime,
  resolveFrontendDistDir,
  resolvePublicApiTarget,
} from "./public-runtime";

describe("public frontend runtime", () => {
  it("keeps combined development mode compatible with root environment loading", () => {
    expect(decideFrontendRuntime(undefined)).toEqual({
      mode: "combined",
      loadRootEnvironment: true,
      allowPrivateRoutes: true,
    });
  });

  it("isolates public mode from root environment loading and private routes", () => {
    expect(decideFrontendRuntime("public")).toEqual({
      mode: "public",
      loadRootEnvironment: false,
      allowPrivateRoutes: false,
    });
  });

  it("resolves a configured public URL or a loopback public port", () => {
    expect(resolvePublicApiTarget({ AI_WORKSHOP_PUBLIC_API_TARGET: "https://public.example.test/" })).toBe(
      "https://public.example.test",
    );
    expect(resolvePublicApiTarget({ PUBLIC_API_PORT: "18001" })).toBe(
      "http://127.0.0.1:18001",
    );
  });

  it("keeps the default Next.js build directory when no instance is selected", () => {
    expect(resolveFrontendDistDir(undefined)).toBeUndefined();
  });

  it("isolates a valid frontend instance below the repository-local Next.js directory", () => {
    expect(resolveFrontendDistDir("test15173")).toBe(".next/instances/test15173");
    expect(resolveFrontendDistDir("public-18001_a")).toBe(
      ".next/instances/public-18001_a",
    );
  });

  it.each([
    "",
    ".",
    "..",
    "test/15173",
    "test\\15173",
    " instance",
    "instance ",
    "instance.name",
    "_instance",
    "-instance",
    "a".repeat(33),
  ])("rejects unsafe or invalid frontend instance name %j", (value) => {
    expect(() => resolveFrontendDistDir(value)).toThrow(
      "AI_WORKSHOP_FRONTEND_INSTANCE must start with an ASCII letter or digit and contain only 1-32 letters, digits, underscores, or hyphens",
    );
  });
});
