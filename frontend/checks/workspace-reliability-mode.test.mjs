import assert from "node:assert/strict";
import test from "node:test";
import { RELIABILITY_JOURNEYS, reliabilityFault, PUBLIC_ROUTE_CASES } from "./workspace-reliability-browser.mjs";
import { LOCAL_PATHS } from "../src/services/routes.js";

test("reliability faults are closed to fixed GET assets and exact collection paths", () => {
  assert.equal(reliabilityFault("optional-settings", "/assets/SettingsShell-Ab_12.js", "GET"), "chunk");
  assert.equal(reliabilityFault("optional-prompts", "/assets/PromptLibraryDialog-Ab_12.js", "GET"), "chunk");
  assert.equal(reliabilityFault("projects-initial-failure", "/api/v1/projects", "GET"), "list");
  assert.equal(reliabilityFault("prompts-initial-failure", "/api/v1/me/saved-prompts", "GET"), "list");
  for (const journey of RELIABILITY_JOURNEYS) {
    for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
      for (const pathname of ["/api/v1/projects", "/api/v1/me/saved-prompts", "/assets/SettingsShell-Ab_12.js"]) assert.equal(reliabilityFault(journey, pathname, method), null);
    }
    for (const pathname of ["/api/auth/logout", "/api/v1/projects/foreign", "/api/v1/me/saved-prompts/foreign", "/api/v1/me/data-deletions", "/assets/Other-Ab_12.js"]) assert.equal(reliabilityFault(journey, pathname, "GET"), null);
  }
});

test("the public route walkthrough covers the complete local allowlist without proof material", () => {
  assert.deepEqual(PUBLIC_ROUTE_CASES.map(route=>route.path).sort(), [...LOCAL_PATHS].sort());
  assert.equal(new Set(PUBLIC_ROUTE_CASES.map(route=>route.name)).size, 14);
  assert.ok(PUBLIC_ROUTE_CASES.every(route=>route.heading&&route.content&&!route.path.includes("#")&&!route.path.includes("?")));
  assert.equal(PUBLIC_ROUTE_CASES.filter(route=>route.account).length, 2);
  for (const mode of ["composer-layout", "public-routes"]) for (const path of ["/api/v1/projects", "/api/v1/me/saved-prompts", "/assets/SettingsShell-Ab_12.js"]) assert.equal(reliabilityFault(mode,path,"GET"),null);
});

test("default and retained notice journeys cannot receive reliability faults", () => {
  for (const journey of [null, "c-notices", "default", "https://outside.invalid", "__proto__"]) {
    for (const pathname of ["/api/v1/projects", "/api/v1/me/saved-prompts", "/assets/SettingsShell-Ab_12.js", "/assets/PromptLibraryDialog-Ab_12.js"]) assert.equal(reliabilityFault(journey, pathname, "GET"), null);
  }
  assert.equal(reliabilityFault("optional-settings", "/assets/../SettingsShell-Ab_12.js", "GET"), null);
});
