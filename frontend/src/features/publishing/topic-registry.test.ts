import { publicTopicLabel } from "./topic-registry";

it.each([
  ["configuration", "구성 관리"],
  ["conversation", "대화"],
  ["future-topic", "future-topic"],
])("displays a public category label for %s", (key, label) => {
  expect(publicTopicLabel(key)).toBe(label);
});
