import { selectUiShell } from "./shellConfig.js";

// These public build values are not permission or authentication controls.
// Live requests use this site's /api regardless of the selected shell.
// VITE_AQUA_USE_MOCK is the older name for the same switch.
const env = import.meta.env ?? {};
export const DEMO_MODE = env.VITE_AQUA_DEMO_MODE === "true" || env.VITE_AQUA_USE_MOCK === "true";
export const UI_SHELL = selectUiShell(env.VITE_AQUA_UI_SHELL);
