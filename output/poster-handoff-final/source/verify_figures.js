"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const nodeModules = process.env.CODEX_NODE_MODULES;
if (!nodeModules) {
  throw new Error("CODEX_NODE_MODULES is required");
}
const sharp = require(path.join(nodeModules, "sharp"));

const ROOT = path.resolve(__dirname, "..");
const FIGURE_DIR = path.join(ROOT, "figures");
const FIGMA_DIR = path.join(FIGURE_DIR, "figma");
const EXPECTED = [
  "Figure_00_smart_care_frame_concept",
  "Figure_01_system_data_boundary",
  "Figure_02_user_scenario",
  "Figure_03_routine_timeline",
  "Figure_04_synthetic_anomaly_replay",
  "Figure_05_conversation_generation_loop",
  "Figure_06_anomaly_decision_policy",
  "Figure_07_problem_solution_map",
  "Figure_08_data_retention_lifecycle",
  "Figure_09_baseline_activation_timeline",
];

async function verify() {
  for (const name of EXPECTED) {
    const svgPath = path.join(FIGURE_DIR, `${name}.svg`);
    const figmaPath = path.join(FIGMA_DIR, `${name}.svg`);
    const pngPath = path.join(FIGURE_DIR, `${name}.png`);
    assert.ok(fs.existsSync(svgPath), `${name} SVG is missing`);
    assert.ok(fs.existsSync(figmaPath), `${name} Figma SVG is missing`);
    assert.ok(fs.existsSync(pngPath), `${name} PNG is missing`);

    const svg = fs.readFileSync(svgPath, "utf8");
    const figmaSvg = fs.readFileSync(figmaPath, "utf8");
    assert.strictEqual(figmaSvg, svg, `${name} Figma SVG differs from source SVG`);
    assert.match(svg, /<title id="[^"]+">/, `${name} has no SVG title`);
    assert.match(svg, /<desc id="[^"]+">/, `${name} has no SVG description`);
    assert.match(
      svg,
      /#(?:8A1601|5E0F00|B34A36|D98D7E|EFCBC4|F8EAE7|FCF5F3)/,
      `${name} does not use the required #8A1601 color family`,
    );
    assert.ok(!svg.includes("marker-end"), `${name} uses non-editable marker arrows`);

    const ids = [...svg.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
    assert.strictEqual(new Set(ids).size, ids.length, `${name} contains duplicate SVG ids`);

    const metadata = await sharp(pngPath).metadata();
    assert.strictEqual(metadata.width, 3200, `${name} PNG width is not 3200`);
    assert.strictEqual(metadata.height, 1800, `${name} PNG height is not 1800`);
  }

  const contactSheet = path.join(FIGURE_DIR, "Figure_contact_sheet.png");
  assert.ok(fs.existsSync(contactSheet), "Contact sheet is missing");
  process.stdout.write(`Verified ${EXPECTED.length} SVG, Figma SVG, and PNG figure sets.\n`);
}

verify().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
