import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: ".", testMatch: "*.spec.mjs", workers: 1, retries: 0,
  timeout: 45000, expect: { timeout: 7000 },
  reporter: [["list"], ["json", { outputFile: "results/report.json" }]],
  outputDir: "results/artifacts",
  use: { screenshot: "only-on-failure", trace: "retain-on-failure" },
  projects: [
    { name: "chromium", use: { browserName: "chromium", viewport: { width: 1440, height: 900 } } },
    { name: "firefox", use: { browserName: "firefox", viewport: { width: 1440, height: 900 } } },
    { name: "webkit-iphone", use: { ...devices["iPhone 16"], browserName: "webkit" } }
  ]
});
