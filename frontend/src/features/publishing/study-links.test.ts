import { expect, it } from "vitest";

import { studySnapshot } from "./test-fixtures";
import { relatedStudiesForWorker } from "./study-links";

it("maps published studies to workers by topic data without a fixed article slug", () => {
  const retrieval = studySnapshot({ slug: "any-retrieval-study", topic_keys: ["retrieval"] });
  const parsing = studySnapshot({ slug: "any-parsing-study", topic_keys: ["parsing"] });

  expect(relatedStudiesForWorker("retrieval-fusion", [retrieval, parsing])).toEqual([retrieval]);
  expect(relatedStudiesForWorker("document-structure", [retrieval, parsing])).toEqual([parsing]);
});
