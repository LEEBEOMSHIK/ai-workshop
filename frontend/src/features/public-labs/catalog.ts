import publicLabsManifest from "../../content/public-labs.json";

export type PublicLabStatus = "researching" | "service";

export interface PublicLabManager {
  name: string;
  role: string;
  intro: string;
  invitation: string;
  ctaLabel: string;
}

export interface PublicLab {
  slug: string;
  name: string;
  eyebrow: string;
  description: string;
  status: PublicLabStatus;
  statusLabel: string;
  href: string;
  manager: PublicLabManager;
}

export type PublicLabCatalogResult =
  | { status: "ready"; labs: readonly PublicLab[] }
  | { status: "error"; labs: readonly [] };

const labKeys = [
  "slug",
  "name",
  "eyebrow",
  "description",
  "status",
  "statusLabel",
  "href",
  "manager",
] as const;

const managerKeys = ["name", "role", "intro", "invitation", "ctaLabel"] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const valueKeys = Object.keys(value);
  return valueKeys.length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function requiredString(value: unknown, error: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(error);
  }

  return value;
}

function parseManager(input: unknown): PublicLabManager {
  if (!isRecord(input) || !hasExactKeys(input, managerKeys)) {
    throw new Error("public_lab_manager_invalid");
  }

  return {
    name: requiredString(input.name, "public_lab_string_invalid"),
    role: requiredString(input.role, "public_lab_string_invalid"),
    intro: requiredString(input.intro, "public_lab_string_invalid"),
    invitation: requiredString(input.invitation, "public_lab_string_invalid"),
    ctaLabel: requiredString(input.ctaLabel, "public_lab_string_invalid"),
  };
}

function parseLab(input: unknown): PublicLab {
  if (!isRecord(input) || !hasExactKeys(input, labKeys)) {
    throw new Error("public_lab_invalid");
  }

  const slug = requiredString(input.slug, "public_lab_slug_invalid");
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(slug)) {
    throw new Error("public_lab_slug_invalid");
  }

  const href = requiredString(input.href, "public_lab_href_invalid");
  if (href !== `/labs/${slug}`) {
    throw new Error("public_lab_href_invalid");
  }

  const status = requiredString(input.status, "public_lab_status_invalid");
  if (status !== "researching" && status !== "service") {
    throw new Error("public_lab_status_invalid");
  }

  return {
    slug,
    name: requiredString(input.name, "public_lab_string_invalid"),
    eyebrow: requiredString(input.eyebrow, "public_lab_string_invalid"),
    description: requiredString(input.description, "public_lab_string_invalid"),
    status,
    statusLabel: requiredString(input.statusLabel, "public_lab_string_invalid"),
    href,
    manager: parseManager(input.manager),
  };
}

export function parsePublicLabCatalog(input: unknown): readonly PublicLab[] {
  if (!isRecord(input)) {
    throw new Error("public_lab_catalog_invalid");
  }

  if (!Object.hasOwn(input, "labs") || !Array.isArray(input.labs)) {
    throw new Error("public_lab_labs_invalid");
  }

  if (!hasExactKeys(input, ["labs"])) {
    throw new Error("public_lab_catalog_invalid");
  }

  const labs = input.labs.map(parseLab);
  const slugs = new Set<string>();
  for (const lab of labs) {
    if (slugs.has(lab.slug)) {
      throw new Error("public_lab_slug_duplicate");
    }
    slugs.add(lab.slug);
  }

  return labs;
}

export function loadPublicLabCatalog(
  input: unknown = publicLabsManifest,
): PublicLabCatalogResult {
  try {
    return { status: "ready", labs: parsePublicLabCatalog(input) };
  } catch {
    return { status: "error", labs: [] };
  }
}

export function listPublicLabs(): readonly PublicLab[] {
  return parsePublicLabCatalog(publicLabsManifest);
}
