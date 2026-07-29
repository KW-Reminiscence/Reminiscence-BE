"use strict";

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
const FIXTURE_PATH = path.join(__dirname, "synthetic_anomaly_fixture.json");
const fixture = JSON.parse(fs.readFileSync(FIXTURE_PATH, "utf8"));

fs.mkdirSync(FIGURE_DIR, { recursive: true });
fs.mkdirSync(FIGMA_DIR, { recursive: true });

const palette = {
  ink: "#2F2523",
  muted: "#6B5B57",
  accent: "#8A1601",
  accentDark: "#5E0F00",
  accentMid: "#B34A36",
  accentSoft: "#D98D7E",
  accentLight: "#EFCBC4",
  accentPale: "#F8EAE7",
  accentOpen: "#FCF5F3",
  line: "#D5C0BB",
  grid: "#E9DEDB",
  soft: "#F8F5F4",
  white: "#FFFFFF",
};

let sequence = 0;

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function resetSequence() {
  sequence = 0;
}

function identity(kind, label) {
  sequence += 1;
  const id = `${kind}_${String(sequence).padStart(3, "0")}`;
  return `${`id="${id}"`} data-name="${esc(label)}"`;
}

function groupStart(id, label) {
  return `<g id="${id}" data-name="${esc(label)}">`;
}

function groupEnd() {
  return "</g>";
}

function rect(x, y, width, height, options = {}) {
  const {
    fill = palette.white,
    stroke = palette.line,
    strokeWidth = 2,
    radius = 18,
    dash = "",
    name = "Rectangle",
  } = options;
  return `<rect ${identity("rect", name)} x="${x}" y="${y}" width="${width}" height="${height}" rx="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"${dash ? ` stroke-dasharray="${dash}"` : ""}/>`;
}

function circle(cx, cy, radius, options = {}) {
  const {
    fill = palette.white,
    stroke = palette.accent,
    strokeWidth = 2,
    name = "Circle",
  } = options;
  return `<circle ${identity("circle", name)} cx="${cx}" cy="${cy}" r="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
}

function ellipse(cx, cy, rx, ry, options = {}) {
  const {
    fill = palette.white,
    stroke = palette.accent,
    strokeWidth = 2,
    name = "Ellipse",
  } = options;
  return `<ellipse ${identity("ellipse", name)} cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
}

function polygon(points, options = {}) {
  const {
    fill = palette.white,
    stroke = palette.accent,
    strokeWidth = 2,
    name = "Polygon",
  } = options;
  const encoded = points.map(([x, y]) => `${x},${y}`).join(" ");
  return `<polygon ${identity("polygon", name)} points="${encoded}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
}

function line(x1, y1, x2, y2, options = {}) {
  const {
    stroke = palette.line,
    strokeWidth = 3,
    dash = "",
    arrow = false,
    name = "Connector",
  } = options;
  const id = `connector_${String(++sequence).padStart(3, "0")}`;
  const parts = [
    `<line id="${id}_stroke" data-name="${esc(name)} · Stroke" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${strokeWidth}" stroke-linecap="round"${dash ? ` stroke-dasharray="${dash}"` : ""}/>`,
  ];
  if (arrow) {
    parts.push(arrowHead(id, x1, y1, x2, y2, stroke));
  }
  return `<g id="${id}" data-name="${esc(name)}">${parts.join("")}</g>`;
}

function polyline(points, options = {}) {
  const {
    stroke = palette.accent,
    strokeWidth = 3,
    dash = "",
    arrow = false,
    fill = "none",
    name = "Connector",
  } = options;
  const id = `connector_${String(++sequence).padStart(3, "0")}`;
  const encoded = points.map(([x, y]) => `${x},${y}`).join(" ");
  const parts = [
    `<polyline id="${id}_stroke" data-name="${esc(name)} · Stroke" points="${encoded}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}" stroke-linecap="round" stroke-linejoin="round"${dash ? ` stroke-dasharray="${dash}"` : ""}/>`,
  ];
  if (arrow && points.length > 1) {
    const [x1, y1] = points.at(-2);
    const [x2, y2] = points.at(-1);
    parts.push(arrowHead(id, x1, y1, x2, y2, stroke));
  }
  return `<g id="${id}" data-name="${esc(name)}">${parts.join("")}</g>`;
}

function arrowHead(parentId, x1, y1, x2, y2, fill) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const length = Math.hypot(dx, dy) || 1;
  const ux = dx / length;
  const uy = dy / length;
  const px = -uy;
  const py = ux;
  const depth = 14;
  const halfWidth = 7;
  const baseX = x2 - ux * depth;
  const baseY = y2 - uy * depth;
  const points = [
    `${x2},${y2}`,
    `${baseX + px * halfWidth},${baseY + py * halfWidth}`,
    `${baseX - px * halfWidth},${baseY - py * halfWidth}`,
  ].join(" ");
  return `<polygon id="${parentId}_arrowhead" data-name="Arrowhead" points="${points}" fill="${fill}" stroke="none"/>`;
}

function text(x, y, value, size = 24, options = {}) {
  const {
    fill = palette.ink,
    anchor = "start",
    weight = 400,
    family = "Apple SD Gothic Neo, Arial Unicode MS, sans-serif",
    letterSpacing = 0,
    name = `Text · ${String(value).slice(0, 44)}`,
  } = options;
  return `<text ${identity("text", name)} x="${x}" y="${y}" fill="${fill}" font-family="${family}" font-size="${size}" font-weight="${weight}" text-anchor="${anchor}" letter-spacing="${letterSpacing}">${esc(value)}</text>`;
}

function multiline(x, y, lines, size = 24, options = {}) {
  const {
    fill = palette.ink,
    anchor = "start",
    weight = 400,
    lineHeight = Math.round(size * 1.35),
    name = `Text block · ${String(lines[0] ?? "").slice(0, 38)}`,
  } = options;
  const spans = lines
    .map((value, index) => `<tspan x="${x}" dy="${index === 0 ? 0 : lineHeight}">${esc(value)}</tspan>`)
    .join("");
  return `<text ${identity("text_block", name)} x="${x}" y="${y}" fill="${fill}" font-family="Apple SD Gothic Neo, Arial Unicode MS, sans-serif" font-size="${size}" font-weight="${weight}" text-anchor="${anchor}">${spans}</text>`;
}

function header(body, titleValue, subtitleValue) {
  body.push(groupStart("01_header", "01 Header"));
  body.push(text(70, 72, titleValue, 46, { weight: 600 }));
  body.push(text(70, 112, subtitleValue, 23, { fill: palette.muted }));
  body.push(groupEnd());
}

function sectionBand(x, y, width, label) {
  return [
    rect(x, y, width, 44, {
      fill: palette.accentPale,
      stroke: "none",
      strokeWidth: 0,
      radius: 8,
      name: `Section band · ${label}`,
    }),
    text(x + 16, y + 30, label, 21, {
      fill: palette.accentDark,
      weight: 600,
      name: `Section title · ${label}`,
    }),
  ].join("");
}

function node(x, y, width, height, titleValue, lines, options = {}) {
  const {
    fill = palette.white,
    stroke = palette.line,
    titleFill = palette.accentDark,
    centered = false,
    titleSize = 22,
    bodySize = 17,
    radius = 14,
    name = `Node · ${titleValue}`,
  } = options;
  const titleX = centered ? x + width / 2 : x + 20;
  const bodyX = centered ? x + width / 2 : x + 20;
  return [
    groupStart(`node_${String(++sequence).padStart(3, "0")}`, name),
    rect(x, y, width, height, { fill, stroke, radius, name: `${name} · Card` }),
    text(titleX, y + 38, titleValue, titleSize, {
      fill: titleFill,
      weight: 600,
      anchor: centered ? "middle" : "start",
      name: `${name} · Title`,
    }),
    multiline(bodyX, y + 72, lines, bodySize, {
      fill: palette.muted,
      anchor: centered ? "middle" : "start",
      lineHeight: Math.round(bodySize * 1.45),
      name: `${name} · Body`,
    }),
    groupEnd(),
  ].join("");
}

function pill(x, y, width, label, options = {}) {
  const {
    fill = palette.accentPale,
    stroke = palette.accentSoft,
    textFill = palette.accentDark,
    name = `Pill · ${label}`,
  } = options;
  return [
    rect(x, y, width, 38, { fill, stroke, strokeWidth: 1.5, radius: 19, name }),
    text(x + width / 2, y + 26, label, 16, {
      anchor: "middle",
      fill: textFill,
      weight: 600,
      name: `${name} · Text`,
    }),
  ].join("");
}

function baseSvg(width, height, titleValue, description, body, name) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="${name}_title ${name}_desc">
  <title id="${name}_title">${esc(titleValue)}</title>
  <desc id="${name}_desc">${esc(description)}</desc>
  <rect id="canvas_background" data-name="Canvas background" width="${width}" height="${height}" fill="${palette.white}"/>
  <g id="${name}" data-name="${esc(titleValue)}">
    ${body}
  </g>
</svg>`;
}

function figureSmartFrameConcept() {
  resetSequence();
  const body = [];
  header(body, "일상 속 AI 대화형 스마트 케어 액자", "가족사진을 중심으로 회상 대화·루틴 기록·보호자 연결을 하나의 장치에 통합");

  body.push(groupStart("02_device", "02 Smart frame device"));
  body.push(rect(85, 165, 825, 610, {
    fill: palette.accentDark,
    stroke: palette.accentDark,
    strokeWidth: 4,
    radius: 28,
    name: "Smart frame outer body",
  }));
  body.push(rect(118, 198, 759, 544, {
    fill: palette.accentOpen,
    stroke: palette.accentSoft,
    strokeWidth: 2,
    radius: 18,
    name: "Smart frame screen",
  }));
  body.push(text(155, 246, "2026년 7월 29일", 22, { fill: palette.muted }));
  body.push(text(840, 246, "오후 2:00", 22, { fill: palette.muted, anchor: "end" }));
  body.push(rect(155, 275, 685, 300, {
    fill: palette.accentLight,
    stroke: palette.accentSoft,
    strokeWidth: 2,
    radius: 18,
    name: "Family photo area",
  }));
  body.push(circle(385, 392, 48, { fill: palette.accentSoft, stroke: palette.accentMid, name: "Family person 1 head" }));
  body.push(ellipse(385, 510, 92, 105, { fill: palette.accentPale, stroke: palette.accentMid, name: "Family person 1 body" }));
  body.push(circle(510, 365, 55, { fill: palette.accentMid, stroke: palette.accentDark, name: "Family person 2 head" }));
  body.push(ellipse(510, 495, 105, 118, { fill: palette.white, stroke: palette.accentDark, name: "Family person 2 body" }));
  body.push(circle(645, 405, 44, { fill: palette.accentSoft, stroke: palette.accentMid, name: "Family person 3 head" }));
  body.push(ellipse(645, 515, 82, 96, { fill: palette.accentOpen, stroke: palette.accentMid, name: "Family person 3 body" }));
  body.push(text(498, 558, "가족사진", 20, { anchor: "middle", fill: palette.accentDark, weight: 600 }));
  body.push(rect(155, 600, 475, 102, {
    fill: palette.white,
    stroke: palette.accentSoft,
    strokeWidth: 2,
    radius: 18,
    name: "Conversation bubble",
  }));
  body.push(multiline(182, 638, ["“이 사진을 보니 어떤 이야기가", "떠오르시나요?”"], 20, {
    fill: palette.ink,
    lineHeight: 29,
    name: "Conversation sample",
  }));
  body.push(rect(655, 600, 185, 102, {
    fill: palette.accent,
    stroke: palette.accentDark,
    strokeWidth: 2,
    radius: 18,
    name: "Routine action button",
  }));
  body.push(text(748, 661, "기록하기", 25, {
    anchor: "middle",
    fill: palette.white,
    weight: 600,
  }));
  body.push(groupEnd());

  body.push(groupStart("03_capabilities", "03 Capability cards"));
  body.push(node(975, 175, 530, 165, "회상 대화", ["고정형 시작 문구", "사용자 응답 기반 LLM 후속 질문", "Supertonic 3 음성 출력"], {
    fill: palette.accentOpen,
    stroke: palette.accentSoft,
    bodySize: 18,
  }));
  body.push(node(975, 365, 530, 165, "식사·복약 루틴", ["예정 시각 음성 안내", "큰 버튼으로 수행 기록", "미응답 시 설정된 재알림"], {
    fill: palette.white,
    stroke: palette.line,
    bodySize: 18,
  }));
  body.push(node(975, 555, 530, 165, "개인별 변화 관찰", ["루틴과 대화 지표 분리", "개인 기준 이상 탐지", "관찰 근거를 보호자 이메일로 전달"], {
    fill: palette.accentPale,
    stroke: palette.accentMid,
    bodySize: 18,
  }));
  body.push(groupEnd());

  body.push(groupStart("04_footer", "04 Footer"));
  body.push(text(800, 835, "평상시에는 가족사진 · 필요한 순간에는 음성 안내와 큰 버튼", 22, {
    anchor: "middle",
    fill: palette.accentDark,
    weight: 600,
  }));
  body.push(groupEnd());

  return baseSvg(
    1600,
    900,
    "일상 속 AI 대화형 스마트 케어 액자",
    "가족사진 화면을 중심으로 회상 대화, 루틴 기록, 개인별 변화 관찰 기능을 배치한 스마트 액자 개념도.",
    body.join("\n"),
    "figure_00",
  );
}

function figureSystemBoundary() {
  resetSequence();
  const body = [];
  header(body, "시스템과 데이터 경계", "태블릿·Raspberry Pi·OpenAI API·SMTP 사이의 처리 위치와 보존 범위");

  body.push(groupStart("02_regions", "02 System regions"));
  body.push(rect(55, 155, 340, 615, { fill: palette.soft, stroke: palette.line, name: "Tablet region" }));
  body.push(rect(445, 135, 735, 655, { fill: palette.accentOpen, stroke: palette.accent, name: "Raspberry Pi region" }));
  body.push(rect(1230, 155, 315, 615, { fill: palette.white, stroke: palette.line, dash: "10 8", name: "External services region" }));
  body.push(sectionBand(75, 175, 300, "태블릿"));
  body.push(sectionBand(465, 155, 695, "Raspberry Pi · FastAPI"));
  body.push(sectionBand(1250, 175, 275, "외부 서비스"));
  body.push(groupEnd());

  body.push(groupStart("03_nodes", "03 System nodes"));
  body.push(node(90, 260, 270, 130, "마이크·화면", ["가족사진과 안내", "사용자 WAV 전송"], { centered: true }));
  body.push(node(90, 465, 270, 130, "스피커·버튼", ["Supertonic 3 WAV 재생", "루틴 수행 기록"], { centered: true }));

  body.push(node(485, 240, 300, 145, "회상 대화 조정", ["첫 질문은 고정형", "전사 text와 세션 맥락 처리", "후속 질문 반환"], { fill: palette.white, stroke: palette.accentSoft }));
  body.push(node(840, 240, 300, 145, "지표 축약", ["글자 수·응답 시간", "무응답·턴 수", "원문은 장기 저장하지 않음"], { fill: palette.white, stroke: palette.accentSoft }));
  body.push(node(485, 455, 300, 130, "Supertonic 3", ["한국어 F1 · speed 0.9", "로컬 PCM 16-bit WAV"], { fill: palette.white, stroke: palette.accentSoft }));
  body.push(node(840, 455, 300, 130, "루틴 상태 머신", ["REMINDING · CONFIRMED", "NOT_ANSWERED"], { fill: palette.white, stroke: palette.accentSoft }));
  body.push(node(665, 640, 300, 120, "로컬 JSON·이상 평가", ["축약 지표와 현재 상태", "설명 가능한 관찰 근거"], { fill: palette.accentPale, stroke: palette.accentMid, centered: true }));

  body.push(node(1265, 250, 245, 165, "OpenAI API", ["gpt-4o-transcribe", "LLM 후속 질문 생성", "WAV·text 일시 처리"], {
    fill: palette.accentPale,
    stroke: palette.accentMid,
    centered: true,
    bodySize: 16,
  }));
  body.push(node(1265, 585, 245, 145, "SMTP", ["관찰 근거 이메일", "이상 전환 시 1회"], {
    centered: true,
    bodySize: 17,
  }));
  body.push(groupEnd());

  body.push(groupStart("04_connectors", "04 Data flow connectors"));
  body.push(polyline([[360, 325], [485, 325]], { stroke: palette.accentDark, arrow: true, name: "Tablet WAV to conversation" }));
  body.push(polyline([[785, 290], [815, 290], [815, 200], [1265, 200], [1265, 300]], {
    stroke: palette.accentDark,
    dash: "9 7",
    arrow: true,
    name: "WAV and context to OpenAI",
  }));
  body.push(polyline([[1265, 365], [1188, 365], [1188, 410], [805, 410], [805, 350], [785, 350]], {
    stroke: palette.accentMid,
    dash: "9 7",
    arrow: true,
    name: "Transcript and question from OpenAI",
  }));
  body.push(line(785, 315, 840, 315, {
    stroke: palette.accent,
    arrow: true,
    name: "Transcript to metric reducer",
  }));
  body.push(line(635, 385, 635, 455, {
    stroke: palette.accent,
    arrow: true,
    name: "Question text to Supertonic",
  }));
  body.push(polyline([[485, 520], [420, 520], [420, 530], [360, 530]], {
    stroke: palette.accent,
    arrow: true,
    name: "WAV to tablet speaker",
  }));
  body.push(polyline([[1120, 385], [1160, 385], [1160, 615], [900, 615], [900, 640]], {
    stroke: palette.accent,
    arrow: true,
    name: "Conversation metrics to storage",
  }));
  body.push(polyline([[990, 585], [990, 615], [930, 615], [930, 640]], {
    stroke: palette.accent,
    arrow: true,
    name: "Routine metrics to storage",
  }));
  body.push(polyline([[965, 700], [1190, 700], [1190, 655], [1265, 655]], {
    stroke: palette.accent,
    arrow: true,
    name: "Observation evidence to SMTP",
  }));
  body.push(groupEnd());

  body.push(groupStart("05_labels", "05 Flow labels"));
  body.push(text(420, 312, "WAV", 16, { anchor: "middle", fill: palette.accentDark }));
  body.push(text(1025, 188, "정규화 WAV · 대화 맥락", 16, { anchor: "middle", fill: palette.accentDark }));
  body.push(text(1050, 397, "전사 text · 후속 질문", 16, { anchor: "middle", fill: palette.accentMid }));
  body.push(text(600, 505, "합성 WAV", 16, { anchor: "middle", fill: palette.accent }));
  body.push(groupEnd());

  body.push(groupStart("06_legend", "06 Legend"));
  body.push(line(75, 835, 170, 835, { stroke: palette.accent, strokeWidth: 4 }));
  body.push(text(185, 842, "실선 · 로컬 처리·저장", 18, { fill: palette.muted }));
  body.push(line(520, 835, 615, 835, { stroke: palette.accentDark, strokeWidth: 4, dash: "9 7" }));
  body.push(text(630, 842, "점선 · 네트워크 일시 처리", 18, { fill: palette.muted }));
  body.push(text(1525, 842, "로컬 보존 · 축약 지표와 현재 상태", 18, { anchor: "end", fill: palette.accentDark }));
  body.push(groupEnd());

  return baseSvg(
    1600,
    900,
    "시스템과 데이터 경계",
    "태블릿과 Raspberry Pi의 로컬 처리, OpenAI API의 일시 처리, SMTP 보호자 알림을 연결한 시스템 구조도.",
    body.join("\n"),
    "figure_01",
  );
}

function figureUserScenario() {
  resetSequence();
  const body = [];
  header(body, "가족사진 화면을 중심으로 한 사용자 시나리오", "루틴 또는 회상 대화가 끝나면 익숙한 사진 화면으로 복귀");

  body.push(node(585, 145, 430, 100, "가족사진 기본 화면", ["날짜와 사진 표시 · 평상시 조작 요구 없음"], {
    fill: palette.accentLight,
    stroke: palette.accent,
    centered: true,
    bodySize: 18,
  }));
  body.push(polyline([[700, 245], [700, 270], [395, 270], [395, 290]], {
    stroke: palette.line,
    strokeWidth: 2,
    dash: "6 6",
    name: "Home to routine branch",
  }));
  body.push(polyline([[900, 245], [900, 270], [1205, 270], [1205, 290]], {
    stroke: palette.line,
    strokeWidth: 2,
    dash: "6 6",
    name: "Home to conversation branch",
  }));
  body.push(sectionBand(70, 290, 650, "루틴 기록 흐름"));
  body.push(sectionBand(880, 290, 650, "회상 대화 흐름"));

  const routine = [
    [75, 365, 175, 105, "예정 시각", ["음성 안내", "큰 기록 버튼"]],
    [290, 365, 175, 105, "응답 확인", ["버튼 입력", "기한 검사"]],
    [505, 345, 200, 90, "CONFIRMED", ["확인 지연 저장"]],
    [505, 470, 200, 105, "재알림", ["유예·간격 적용", "기한 종료 시 미응답"]],
  ];
  for (const [x, y, width, height, titleValue, lines] of routine) {
    body.push(node(x, y, width, height, titleValue, lines, {
      centered: true,
      titleSize: 20,
      bodySize: 16,
      fill: titleValue === "CONFIRMED" ? palette.accentPale : palette.white,
      stroke: titleValue === "CONFIRMED" ? palette.accentMid : palette.line,
    }));
  }
  body.push(line(250, 418, 290, 418, { stroke: palette.accentDark, arrow: true }));
  body.push(polyline([[465, 395], [485, 395], [485, 390], [505, 390]], { stroke: palette.accentDark, arrow: true }));
  body.push(polyline([[465, 445], [485, 445], [485, 522], [505, 522]], { stroke: palette.line, arrow: true }));
  body.push(text(475, 465, "미입력", 15, { anchor: "end", fill: palette.muted }));

  const conversation = [
    [885, 365, 155, 105, "대화 시작", ["정시 권유", "자발적 시작"]],
    [1070, 365, 175, 105, "질문 제시", ["첫 문구 고정형", "이후 LLM·Supertonic 3"]],
    [1275, 365, 155, 105, "사용자 응답", ["WAV 전송", "text 전사"]],
    [1460, 365, 70, 105, "LLM", ["후속", "질문"]],
  ];
  for (const [x, y, width, height, titleValue, lines] of conversation) {
    body.push(node(x, y, width, height, titleValue, lines, {
      centered: true,
      titleSize: width < 100 ? 18 : 20,
      bodySize: width < 100 ? 14 : 16,
      fill: titleValue === "LLM" ? palette.accentPale : palette.white,
      stroke: titleValue === "LLM" ? palette.accentMid : palette.line,
    }));
  }
  body.push(line(1040, 418, 1070, 418, { stroke: palette.accentDark, arrow: true }));
  body.push(line(1245, 418, 1275, 418, { stroke: palette.accentDark, arrow: true }));
  body.push(line(1430, 418, 1460, 418, { stroke: palette.accentDark, arrow: true }));
  body.push(polyline([[1495, 470], [1495, 515], [1352, 515], [1352, 470]], {
    stroke: palette.accentMid,
    arrow: true,
    name: "LLM follow-up loop",
  }));
  body.push(text(1425, 540, "후속 질문을 음성으로 재생한 뒤 응답 반복", 15, {
    anchor: "middle",
    fill: palette.accentDark,
  }));

  body.push(node(250, 620, 455, 88, "사진 화면으로 복귀", ["CONFIRMED 또는 NOT_ANSWERED 종료"], {
    centered: true,
    titleSize: 21,
    bodySize: 16,
    fill: palette.soft,
  }));
  body.push(node(1000, 620, 430, 88, "세션 종료 후 복귀", ["정시 권유 미참여는 이상으로 기록하지 않음"], {
    centered: true,
    titleSize: 21,
    bodySize: 16,
    fill: palette.soft,
  }));
  body.push(polyline([[705, 390], [745, 390], [745, 600], [600, 600], [600, 620]], {
    stroke: palette.accent,
    arrow: true,
    name: "Confirmed to home",
  }));
  body.push(polyline([[605, 575], [605, 620]], { stroke: palette.line, arrow: true }));
  body.push(polyline([[1352, 545], [1352, 585], [1215, 585], [1215, 620]], { stroke: palette.accent, arrow: true }));
  body.push(polyline([[478, 708], [478, 750], [800, 750]], { stroke: palette.line, dash: "6 6" }));
  body.push(polyline([[1215, 708], [1215, 750], [800, 750]], { stroke: palette.line, dash: "6 6" }));

  body.push(rect(330, 760, 940, 65, { fill: palette.accentPale, stroke: palette.accentSoft, radius: 14 }));
  body.push(text(800, 800, "완료된 루틴·대화 지표 → 개인별 변화 평가 → 확정 시 보호자 이메일", 20, {
    anchor: "middle",
    fill: palette.accentDark,
    weight: 600,
  }));

  return baseSvg(
    1600,
    900,
    "가족사진 화면을 중심으로 한 사용자 시나리오",
    "가족사진 기본 화면에서 루틴 기록과 회상 대화로 분기하고 활동이 끝나면 다시 사진 화면으로 돌아오는 사용자 흐름.",
    body.join("\n"),
    "figure_02",
  );
}

function figureRoutineTimeline() {
  resetSequence();
  const body = [];
  header(body, "루틴 상태 타임라인", "시연 설정 · 09:00 시작 · 10분 간격 · 재알림 3회 · 09:40 마감");

  const xs = [160, 470, 780, 1090, 1400];
  const labels = ["09:00", "09:10", "09:20", "09:30", "09:40"];
  body.push(rect(160, 330, 1240, 92, { fill: palette.accentOpen, stroke: "none", strokeWidth: 0, radius: 10 }));
  body.push(text(780, 318, "확인 가능 구간 [09:00, 09:40)", 20, { anchor: "middle", fill: palette.accentDark }));
  body.push(line(160, 376, 1400, 376, { stroke: palette.accentDark, strokeWidth: 5 }));

  for (let index = 0; index < xs.length; index += 1) {
    const isDeadline = index === xs.length - 1;
    if (isDeadline) {
      body.push(polygon([[xs[index], 360], [xs[index] + 16, 376], [xs[index], 392], [xs[index] - 16, 376]], {
        fill: palette.accentMid,
        stroke: palette.accentDark,
        name: "Deadline marker",
      }));
    } else {
      body.push(circle(xs[index], 376, 11, { fill: palette.white, stroke: palette.accent, strokeWidth: 4, name: `Timeline marker ${labels[index]}` }));
    }
    body.push(text(xs[index], 440, labels[index], 24, {
      anchor: "middle",
      fill: isDeadline ? palette.accentDark : palette.ink,
      weight: 600,
    }));
  }

  const cards = [
    [70, 165, 220, 105, "최초 안내", ["REMINDING 시작", "재알림 수 0"]],
    [360, 500, 220, 105, "재알림 1", ["버튼 미입력", "reminder count 1"]],
    [670, 165, 220, 105, "재알림 2", ["버튼 미입력", "reminder count 2"]],
    [980, 500, 220, 105, "재알림 3", ["버튼 미입력", "reminder count 3"]],
    [1280, 165, 245, 105, "응답 기한", ["09:40 도달", "NOT_ANSWERED"]],
  ];
  for (const [x, y, width, height, titleValue, lines] of cards) {
    body.push(node(x, y, width, height, titleValue, lines, {
      centered: true,
      titleSize: 21,
      bodySize: 16,
      fill: titleValue === "응답 기한" ? palette.accentPale : palette.white,
      stroke: titleValue === "응답 기한" ? palette.accentMid : palette.line,
    }));
  }
  body.push(line(160, 270, 160, 360, { stroke: palette.line }));
  body.push(line(470, 392, 470, 500, { stroke: palette.line }));
  body.push(line(780, 270, 780, 360, { stroke: palette.line }));
  body.push(line(1090, 392, 1090, 500, { stroke: palette.line }));
  body.push(line(1400, 270, 1400, 360, { stroke: palette.accentMid }));

  body.push(node(225, 690, 510, 105, "구간 내 버튼 입력", ["CONFIRMED · 재알림 중단 · 확인 지연 저장"], {
    centered: true,
    titleSize: 22,
    bodySize: 17,
    fill: palette.accentPale,
    stroke: palette.accent,
  }));
  body.push(node(865, 690, 510, 105, "09:40까지 입력 없음", ["NOT_ANSWERED · 사진 화면 복귀"], {
    centered: true,
    titleSize: 22,
    bodySize: 17,
    fill: palette.white,
    stroke: palette.accentMid,
  }));
  body.push(polyline([[625, 422], [625, 650], [480, 650], [480, 690]], { stroke: palette.accent, arrow: true }));
  body.push(polyline([[1400, 422], [1480, 422], [1480, 650], [1120, 650], [1120, 690]], { stroke: palette.accentMid, arrow: true }));
  body.push(text(800, 855, "최초 안내는 재알림 횟수에서 제외 · 기한 이후 버튼 입력은 상태를 변경하지 않음", 18, {
    anchor: "middle",
    fill: palette.muted,
  }));

  return baseSvg(
    1600,
    900,
    "루틴 상태 타임라인",
    "09시 최초 안내부터 세 차례 재알림, 09시 40분 응답 기한까지의 루틴 상태 전이를 나타낸 타임라인.",
    body.join("\n"),
    "figure_03",
  );
}

function chartPanel(x, y, width, height, titleValue, unit, key, maxValue, ticks) {
  const body = [];
  const plotLeft = x + 62;
  const plotRight = x + width - 28;
  const plotTop = y + 70;
  const plotBottom = y + height - 58;
  const xScale = (session) => plotLeft + ((session - 1) / 20) * (plotRight - plotLeft);
  const yScale = (value) => plotBottom - (value / maxValue) * (plotBottom - plotTop);

  body.push(rect(x, y, width, height, { fill: palette.white, stroke: palette.line, radius: 14, name: `Chart panel · ${titleValue}` }));
  body.push(text(x + 22, y + 38, titleValue, 22, { weight: 600, fill: palette.ink }));
  body.push(text(x + width - 22, y + 38, unit, 16, { anchor: "end", fill: palette.muted }));

  for (const tick of ticks) {
    const py = yScale(tick);
    body.push(line(plotLeft, py, plotRight, py, { stroke: palette.grid, strokeWidth: 1, name: `Grid ${tick}` }));
    body.push(text(plotLeft - 10, py + 5, String(tick), 14, { anchor: "end", fill: palette.muted }));
  }
  body.push(line(plotLeft, plotBottom, plotRight, plotBottom, { stroke: palette.line, strokeWidth: 1.5 }));

  for (const row of fixture) {
    const px = xScale(row.session);
    const py = yScale(row[key]);
    if (row.role === "current") {
      body.push(polygon([[px, py - 10], [px + 10, py], [px, py + 10], [px - 10, py]], {
        fill: palette.accent,
        stroke: palette.accentDark,
        strokeWidth: 2,
        name: `Current session ${row.session}`,
      }));
      body.push(text(px - 4, py - 18, `현재 ${row[key]}`, 14, {
        anchor: "end",
        fill: palette.accentDark,
        weight: 600,
      }));
    } else {
      body.push(circle(px, py, 5.5, {
        fill: palette.accentLight,
        stroke: palette.accentMid,
        strokeWidth: 1.5,
        name: `Baseline session ${row.session}`,
      }));
    }
  }
  body.push(text(plotLeft, plotBottom + 30, "1", 14, { anchor: "middle", fill: palette.muted }));
  body.push(text(plotRight, plotBottom + 30, "21 세션", 14, { anchor: "middle", fill: palette.muted }));
  return body.join("");
}

function figureSyntheticCandidate() {
  resetSequence();
  const body = [];
  header(body, "합성 입력에 대한 대화 품질 이상 후보", "20개 기준 세션과 21번째 현재 세션 · 사용자·임상 자료와 분류 성능 평가가 아님");

  body.push(chartPanel(60, 175, 475, 430, "사용자 턴 수", "회", "user_turn_count", 8, [0, 2, 4, 6, 8]));
  body.push(chartPanel(563, 175, 475, 430, "총 발화 글자 수", "자", "total_utterance_chars", 180, [0, 50, 100, 150]));
  body.push(chartPanel(1066, 175, 475, 430, "세션 무응답 횟수", "회", "no_response_count", 3, [0, 1, 2, 3]));

  body.push(groupStart("03_interpretation", "03 Interpretation"));
  body.push(node(115, 660, 390, 115, "모델 출력", ["현재 세션 · 이상 후보", "decision function −0.048242"], {
    centered: true,
    fill: palette.accentPale,
    stroke: palette.accent,
    bodySize: 17,
  }));
  body.push(node(605, 660, 390, 115, "지속성 확인", ["최근 3세션 중 2세션 이상", "이 Figure에서는 평가하지 않음"], {
    centered: true,
    fill: palette.white,
    stroke: palette.line,
    bodySize: 17,
  }));
  body.push(node(1095, 660, 390, 115, "최종 판단", ["규칙·모델·지속성 중 2개", "이 Figure에서는 확정하지 않음"], {
    centered: true,
    fill: palette.white,
    stroke: palette.accentMid,
    bodySize: 17,
  }));
  body.push(line(505, 718, 605, 718, { stroke: palette.accentMid, arrow: true }));
  body.push(line(995, 718, 1095, 718, { stroke: palette.accentMid, arrow: true }));
  body.push(groupEnd());

  body.push(groupStart("04_legend", "04 Legend"));
  body.push(circle(90, 835, 6, { fill: palette.accentLight, stroke: palette.accentMid }));
  body.push(text(108, 841, "기준 세션", 17, { fill: palette.muted }));
  body.push(polygon([[245, 827], [253, 835], [245, 843], [237, 835]], { fill: palette.accent, stroke: palette.accentDark }));
  body.push(text(265, 841, "현재 세션", 17, { fill: palette.muted }));
  body.push(text(1530, 841, "점수는 확률·위험도·중증도가 아님", 18, { anchor: "end", fill: palette.accentDark }));
  body.push(groupEnd());

  return baseSvg(
    1600,
    900,
    "합성 입력에 대한 대화 품질 이상 후보",
    "스무 개 기준 세션과 현재 세션의 턴 수, 발화 글자 수, 무응답 횟수를 비교하며 현재 세션은 모델 후보일 뿐 최종 이상 확정이 아님을 명시한 소형 다중 차트.",
    body.join("\n"),
    "figure_04",
  );
}

function figureConversationLoop() {
  resetSequence();
  const body = [];
  header(body, "고정형 시작 문구와 LLM 후속 질문", "첫 진입은 일정하게, 이후 대화는 사용자의 직전 응답과 세션 맥락에 맞춰 진행");

  const steps = [
    [65, 250, 225, 170, "대화 시작", ["사진 표시", "고정형 첫 질문", "Supertonic 3 재생"]],
    [335, 250, 225, 170, "사용자 응답", ["마이크 입력", "WAV 전송", "턴 시간 측정"]],
    [605, 250, 225, 170, "OpenAI 전사", ["gpt-4o-transcribe", "전사 text 반환", "일시 처리"]],
    [875, 250, 225, 170, "LLM 후속 질문", ["직전 응답·세션 맥락", "짧은 열린 질문", "질문 정책 적용"]],
    [1145, 250, 225, 170, "음성 출력", ["Supertonic 3", "화면 text와 WAV", "Raspberry Pi 로컬"]],
  ];
  for (const [x, y, width, height, titleValue, lines] of steps) {
    body.push(node(x, y, width, height, titleValue, lines, {
      centered: true,
      fill: titleValue === "LLM 후속 질문" ? palette.accentPale : palette.white,
      stroke: titleValue === "LLM 후속 질문" ? palette.accentMid : palette.line,
      bodySize: 17,
    }));
  }
  for (let index = 0; index < steps.length - 1; index += 1) {
    body.push(line(steps[index][0] + steps[index][2], 335, steps[index + 1][0], 335, {
      stroke: palette.accentDark,
      arrow: true,
      name: `Conversation step ${index + 1}`,
    }));
  }
  body.push(polyline([[1370, 335], [1480, 335], [1480, 510], [447, 510], [447, 420]], {
    stroke: palette.accentMid,
    arrow: true,
    name: "Follow-up question loop",
  }));
  body.push(text(965, 495, "후속 질문 재생 후 사용자 응답 단계로 반복", 18, {
    anchor: "middle",
    fill: palette.accentDark,
    weight: 600,
  }));

  body.push(groupStart("03_guardrails", "03 Question policy"));
  body.push(sectionBand(85, 585, 1430, "질문 정책"));
  body.push(pill(115, 655, 300, "사진 속 사실을 단정하지 않음"));
  body.push(pill(450, 655, 300, "사용자의 기억을 교정하지 않음"));
  body.push(pill(785, 655, 300, "정답을 요구하지 않는 열린 질문"));
  body.push(pill(1120, 655, 300, "의료적 해석과 불안 표현 제외"));
  body.push(groupEnd());

  body.push(groupStart("04_data_policy", "04 Data policy"));
  body.push(rect(205, 750, 1190, 70, { fill: palette.soft, stroke: palette.line, radius: 14 }));
  body.push(text(800, 793, "전사 text·LLM 맥락·생성 문구는 턴 처리에 사용 · 활동 기록에는 축약 지표만 저장", 19, {
    anchor: "middle",
    fill: palette.muted,
  }));
  body.push(groupEnd());

  return baseSvg(
    1600,
    900,
    "고정형 시작 문구와 LLM 후속 질문",
    "고정형 첫 질문, 사용자 응답, OpenAI 전사, LLM 후속 질문, Supertonic 3 음성 출력이 반복되는 회상 대화 루프.",
    body.join("\n"),
    "figure_05",
  );
}

function figureAnomalyDecision() {
  resetSequence();
  const body = [];
  header(body, "개인별 이상 판단 구조", "규칙 기반·Isolation Forest·지속성 신호 가운데 두 신호 이상 충족 시 확정");

  body.push(groupStart("02_signal_cards", "02 Signal cards"));
  body.push(node(90, 175, 390, 145, "규칙 기반 신호", ["동일 루틴 연속 미응답", "최근 7일 대화 참여량 감소", "설명 가능한 명시 조건"], {
    centered: true,
    fill: palette.accentOpen,
    stroke: palette.accentSoft,
    bodySize: 17,
  }));
  body.push(node(605, 175, 390, 145, "Isolation Forest 신호", ["개인 기준 다변량 패턴", "루틴 하루 벡터", "대화 세션 벡터"], {
    centered: true,
    fill: palette.accentPale,
    stroke: palette.accentMid,
    bodySize: 17,
  }));
  body.push(node(1120, 175, 390, 145, "지속성 신호", ["일시적 흔들림 제외", "최근 세션·일 단위 반복 확인", "영역별 지속 조건"], {
    centered: true,
    fill: palette.accentOpen,
    stroke: palette.accentSoft,
    bodySize: 17,
  }));
  body.push(groupEnd());

  body.push(groupStart("03_decision", "03 Decision"));
  body.push(polyline([[285, 320], [285, 340], [800, 340], [800, 355]], {
    stroke: palette.accent,
    arrow: true,
    name: "Rule signal to decision",
  }));
  body.push(line(800, 320, 800, 355, {
    stroke: palette.accent,
    arrow: true,
    name: "Model signal to decision",
  }));
  body.push(polyline([[1315, 320], [1315, 340], [800, 340], [800, 355]], {
    stroke: palette.accent,
    arrow: true,
    name: "Persistence signal to decision",
  }));
  body.push(polygon([[800, 355], [930, 425], [800, 495], [670, 425]], {
    fill: palette.accent,
    stroke: palette.accentDark,
    strokeWidth: 3,
    name: "Two of three decision",
  }));
  body.push(multiline(800, 413, ["세 신호 중", "2개 이상?"], 22, {
    anchor: "middle",
    fill: palette.white,
    weight: 600,
    lineHeight: 28,
  }));
  body.push(node(1040, 370, 380, 110, "ANOMALOUS 확정", ["NORMAL → ANOMALOUS 전환 시", "관찰 근거 이메일 1회"], {
    centered: true,
    fill: palette.accentPale,
    stroke: palette.accentMid,
    bodySize: 17,
  }));
  body.push(line(930, 425, 1040, 425, { stroke: palette.accentDark, arrow: true }));
  body.push(text(980, 412, "예", 15, { anchor: "middle", fill: palette.accentDark }));
  body.push(node(180, 370, 380, 110, "현재 상태 유지", ["신호가 부족하면 확정하지 않음", "새 관측에서 다시 평가"], {
    centered: true,
    fill: palette.soft,
    stroke: palette.line,
    bodySize: 17,
  }));
  body.push(line(670, 425, 560, 425, { stroke: palette.line, arrow: true }));
  body.push(text(615, 412, "아니요", 15, { anchor: "middle", fill: palette.muted }));
  body.push(groupEnd());

  body.push(groupStart("04_domain_rules", "04 Domain rules"));
  body.push(sectionBand(70, 545, 710, "루틴"));
  body.push(sectionBand(820, 545, 710, "회상 대화"));
  body.push(node(70, 610, 335, 155, "초기 28일", ["동일 루틴 NOT_ANSWERED", "3회 연속이면 규칙·지속 충족", "CONFIRMED 발생 시 초기화"], {
    fill: palette.white,
    stroke: palette.line,
    bodySize: 16,
  }));
  body.push(node(445, 610, 335, 155, "28일 이후", ["미응답률·확인 지연", "완료율·최대 연속 미응답", "하루 벡터 Isolation Forest"], {
    fill: palette.white,
    stroke: palette.line,
    bodySize: 16,
  }));
  body.push(node(820, 610, 335, 155, "대화 품질", ["20세션 뒤 모델 활성화", "최근 3세션 중 2세션 이상", "비정상일 때 지속 신호"], {
    fill: palette.white,
    stroke: palette.line,
    bodySize: 16,
  }));
  body.push(node(1195, 610, 335, 155, "대화 참여량", ["개인 기준보다 50% 이상", "실제 10턴 이상 감소", "같은 조건 2일 연속"], {
    fill: palette.white,
    stroke: palette.line,
    bodySize: 16,
  }));
  body.push(groupEnd());

  body.push(text(800, 840, "모델 점수는 건강 위험의 확률이나 중증도가 아니며 보호자에게는 변화 근거를 설명", 18, {
    anchor: "middle",
    fill: palette.accentDark,
  }));

  return baseSvg(
    1600,
    900,
    "개인별 이상 판단 구조",
    "규칙 기반, Isolation Forest, 지속성 신호의 삼중 판단과 루틴 및 회상 대화의 영역별 조건을 나타낸 결정 도식.",
    body.join("\n"),
    "figure_06",
  );
}

function figureProblemSolution() {
  resetSequence();
  const body = [];
  header(body, "돌봄의 세 공백과 설계 대응", "치매 환자의 생활 공간에서 회상 참여와 일상 변화를 연결하는 스마트 액자");

  body.push(sectionBand(70, 165, 600, "문제"));
  body.push(sectionBand(930, 165, 600, "Reminiscence의 대응"));

  const rows = [
    {
      y: 235,
      problem: "지속하기 어려운 회상 대화",
      problemLines: ["가족·돌봄 인력이 매일 함께하기 어려움", "앱을 찾아 실행하는 방식의 지속성 저하"],
      response: "가족사진 기반 AI 음성 대화",
      responseLines: ["고정형 시작 문구로 진입", "LLM 후속 질문과 Supertonic 3 음성"],
    },
    {
      y: 430,
      problem: "보호자에게 보이지 않는 생활 변화",
      problemLines: ["루틴 미응답과 대화량 감소를 연속 관찰하기 어려움", "한 번의 변화만으로 의미를 판단하기 어려움"],
      response: "개인 기준 변화 관찰",
      responseLines: ["루틴·대화 지표를 분리해 축적", "규칙·모델·지속성 근거를 이메일로 전달"],
    },
    {
      y: 625,
      problem: "기존 디지털 기기의 높은 조작 부담",
      problemLines: ["복잡한 메뉴와 여러 단계 조작", "새로운 앱 사용 절차를 기억해야 하는 부담"],
      response: "액자 중심의 단순한 상호작용",
      responseLines: ["평상시 가족사진 표시", "음성 안내·큰 버튼·활동 후 자동 복귀"],
    },
  ];

  for (const row of rows) {
    body.push(node(70, row.y, 600, 145, row.problem, row.problemLines, {
      fill: palette.soft,
      stroke: palette.line,
      bodySize: 17,
    }));
    body.push(node(930, row.y, 600, 145, row.response, row.responseLines, {
      fill: palette.accentPale,
      stroke: palette.accentMid,
      bodySize: 17,
    }));
    body.push(polyline([[670, row.y + 72], [930, row.y + 72]], {
      stroke: palette.accent,
      arrow: true,
      name: `Problem response connector · ${row.problem}`,
    }));
  }

  body.push(text(800, 860, "익숙한 가족사진 화면을 대화·기록·관찰의 공통 접점으로 사용", 21, {
    anchor: "middle",
    fill: palette.accentDark,
    weight: 600,
  }));

  return baseSvg(
    1600,
    900,
    "돌봄의 세 공백과 설계 대응",
    "회상 대화 지속성, 보호자 관찰 공백, 디지털 조작 부담이라는 세 문제와 스마트 액자의 대응 기능을 일대일로 연결한 도식.",
    body.join("\n"),
    "figure_07",
  );
}

function figureDataRetention() {
  resetSequence();
  const body = [];
  header(body, "대화 데이터 처리와 보존 경계", "원본 음성과 대화 원문은 턴 처리에 사용하고 활동 기록에는 축약 지표만 저장");

  body.push(sectionBand(70, 165, 1460, "턴 처리 경로"));
  const steps = [
    [70, 245, 250, 145, "사용자 WAV", ["태블릿 → Raspberry Pi", "메모리에서 정규화"]],
    [375, 245, 250, 145, "OpenAI 전사", ["WAV 일시 처리", "전사 text 반환"]],
    [680, 245, 250, 145, "LLM 질문 생성", ["전사 text·세션 맥락", "후속 질문 text 반환"]],
    [985, 245, 250, 145, "Supertonic 3", ["Raspberry Pi 로컬 합성", "PCM 16-bit WAV"]],
    [1290, 245, 240, 145, "태블릿 재생", ["화면 text 표시", "합성 WAV 재생"]],
  ];
  for (const [x, y, width, height, titleValue, lines] of steps) {
    body.push(node(x, y, width, height, titleValue, lines, {
      centered: true,
      fill: titleValue.includes("OpenAI") || titleValue.includes("LLM") ? palette.accentPale : palette.white,
      stroke: titleValue.includes("OpenAI") || titleValue.includes("LLM") ? palette.accentMid : palette.line,
      bodySize: 16,
    }));
  }
  for (let index = 0; index < steps.length - 1; index += 1) {
    body.push(line(steps[index][0] + steps[index][2], 318, steps[index + 1][0], 318, {
      stroke: palette.accentDark,
      arrow: true,
      name: `Data lifecycle step ${index + 1}`,
    }));
  }

  body.push(sectionBand(70, 455, 710, "장기 저장하지 않음"));
  body.push(sectionBand(820, 455, 710, "로컬 JSON에 저장"));
  body.push(node(70, 520, 710, 205, "일시 처리 데이터", ["사용자 WAV", "전사 text와 OpenAI API 응답", "LLM 입력 맥락과 생성 text", "Supertonic 3 합성 WAV"], {
    fill: palette.soft,
    stroke: palette.line,
    bodySize: 18,
  }));
  body.push(node(820, 520, 710, 205, "축약된 활동·상태 데이터", ["대화 턴 수·글자 수·응답 시간·무응답", "루틴 상태·확인 지연", "최신 개인별 이상 상태와 관찰 근거", "알림 시도 표식"], {
    fill: palette.accentPale,
    stroke: palette.accentMid,
    bodySize: 18,
  }));
  body.push(polyline([[445, 390], [445, 430], [425, 430], [425, 455]], { stroke: palette.line, dash: "6 6" }));
  body.push(polyline([[805, 390], [805, 430], [1175, 430], [1175, 455]], { stroke: palette.accent, dash: "6 6" }));

  body.push(rect(190, 775, 1220, 58, { fill: palette.accentOpen, stroke: palette.accentSoft, radius: 14 }));
  body.push(text(800, 811, "OpenAI API의 서버 측 데이터 처리는 Raspberry Pi의 로컬 비보존 정책과 별도로 확인", 18, {
    anchor: "middle",
    fill: palette.accentDark,
  }));

  return baseSvg(
    1600,
    900,
    "대화 데이터 처리와 보존 경계",
    "WAV, 전사문, LLM 맥락과 합성 음성은 장기 저장하지 않고 축약 활동 지표와 현재 상태만 로컬 JSON에 저장하는 데이터 수명주기.",
    body.join("\n"),
    "figure_08",
  );
}

function figureBaselineActivation() {
  resetSequence();
  const body = [];
  header(body, "개인 기준선과 모델 활성화 시점", "루틴과 회상 대화의 관측 단위가 달라 기준선 형성 조건을 분리");

  body.push(sectionBand(70, 175, 1460, "루틴 · 일 단위"));
  body.push(rect(120, 270, 560, 92, { fill: palette.accentPale, stroke: palette.accentMid, radius: 12 }));
  body.push(text(400, 307, "초기 28일", 22, { anchor: "middle", weight: 600, fill: palette.accentDark }));
  body.push(text(400, 340, "동일 루틴 3회 연속 미응답 규칙", 17, { anchor: "middle", fill: palette.muted }));
  body.push(rect(680, 270, 800, 92, { fill: palette.accentOpen, stroke: palette.accent, radius: 12 }));
  body.push(text(1080, 307, "29번째 관측일부터", 22, { anchor: "middle", weight: 600, fill: palette.accentDark }));
  body.push(text(1080, 340, "하루 벡터 기반 개인별 루틴 Isolation Forest", 17, { anchor: "middle", fill: palette.muted }));
  body.push(line(120, 395, 1480, 395, { stroke: palette.accentDark, strokeWidth: 4 }));
  body.push(circle(120, 395, 9, { fill: palette.white, stroke: palette.accent, strokeWidth: 3 }));
  body.push(polygon([[680, 383], [692, 395], [680, 407], [668, 395]], { fill: palette.accent, stroke: palette.accentDark }));
  body.push(text(120, 430, "1일", 16, { anchor: "middle", fill: palette.muted }));
  body.push(text(680, 430, "28일 완료", 16, { anchor: "middle", fill: palette.accentDark }));

  body.push(sectionBand(70, 500, 1460, "회상 대화 · 세션과 최근 7일 참여량"));
  body.push(rect(120, 595, 560, 92, { fill: palette.accentPale, stroke: palette.accentMid, radius: 12 }));
  body.push(text(400, 632, "초기 20세션", 22, { anchor: "middle", weight: 600, fill: palette.accentDark }));
  body.push(text(400, 665, "대화 품질 기준 세션 축적", 17, { anchor: "middle", fill: palette.muted }));
  body.push(rect(680, 595, 800, 92, { fill: palette.accentOpen, stroke: palette.accent, radius: 12 }));
  body.push(text(1080, 632, "21번째 세션부터", 22, { anchor: "middle", weight: 600, fill: palette.accentDark }));
  body.push(text(1080, 665, "세션 품질 Isolation Forest · 최근 3세션 중 2세션 지속 확인", 17, { anchor: "middle", fill: palette.muted }));
  body.push(line(120, 720, 1480, 720, { stroke: palette.accentDark, strokeWidth: 4 }));
  body.push(circle(120, 720, 9, { fill: palette.white, stroke: palette.accent, strokeWidth: 3 }));
  body.push(polygon([[680, 708], [692, 720], [680, 732], [668, 720]], { fill: palette.accent, stroke: palette.accentDark }));
  body.push(text(120, 755, "1세션", 16, { anchor: "middle", fill: palette.muted }));
  body.push(text(680, 755, "20세션 완료", 16, { anchor: "middle", fill: palette.accentDark }));

  body.push(rect(250, 805, 1100, 48, { fill: palette.soft, stroke: palette.line, radius: 12 }));
  body.push(text(800, 837, "참여량 기준 · 초기 28일의 네 개 7일 구간 평균 → 최근 7일 턴 수와 비교", 18, {
    anchor: "middle",
    fill: palette.muted,
  }));

  return baseSvg(
    1600,
    900,
    "개인 기준선과 모델 활성화 시점",
    "루틴 모델은 초기 28일 후, 대화 품질 모델은 초기 20세션 후 활성화되며 참여량은 초기 28일의 7일 구간 평균과 비교하는 이중 타임라인.",
    body.join("\n"),
    "figure_09",
  );
}

const figures = [
  ["Figure_00_smart_care_frame_concept", figureSmartFrameConcept()],
  ["Figure_01_system_data_boundary", figureSystemBoundary()],
  ["Figure_02_user_scenario", figureUserScenario()],
  ["Figure_03_routine_timeline", figureRoutineTimeline()],
  ["Figure_04_synthetic_anomaly_replay", figureSyntheticCandidate()],
  ["Figure_05_conversation_generation_loop", figureConversationLoop()],
  ["Figure_06_anomaly_decision_policy", figureAnomalyDecision()],
  ["Figure_07_problem_solution_map", figureProblemSolution()],
  ["Figure_08_data_retention_lifecycle", figureDataRetention()],
  ["Figure_09_baseline_activation_timeline", figureBaselineActivation()],
];

async function writeFigure(name, svg) {
  const svgPath = path.join(FIGURE_DIR, `${name}.svg`);
  const figmaPath = path.join(FIGMA_DIR, `${name}.svg`);
  const pngPath = path.join(FIGURE_DIR, `${name}.png`);
  fs.writeFileSync(svgPath, svg, "utf8");
  fs.writeFileSync(figmaPath, svg, "utf8");
  await sharp(Buffer.from(svg), { density: 240 })
    .resize({ width: 3200 })
    .flatten({ background: palette.white })
    .png({ compressionLevel: 9, palette: false })
    .toFile(pngPath);
  return pngPath;
}

async function writeContactSheet(pngPaths) {
  const thumbWidth = 760;
  const thumbHeight = 428;
  const gap = 30;
  const labelHeight = 52;
  const columns = 2;
  const rows = Math.ceil(pngPaths.length / columns);
  const canvasWidth = columns * thumbWidth + (columns + 1) * gap;
  const canvasHeight = rows * (thumbHeight + labelHeight) + (rows + 1) * gap;
  const composites = [];

  for (let index = 0; index < pngPaths.length; index += 1) {
    const column = index % columns;
    const row = Math.floor(index / columns);
    const left = gap + column * (thumbWidth + gap);
    const top = gap + row * (thumbHeight + labelHeight + gap);
    const imageBuffer = await sharp(pngPaths[index]).resize(thumbWidth, thumbHeight).png().toBuffer();
    composites.push({ input: imageBuffer, left, top });
    const labelSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="${thumbWidth}" height="${labelHeight}">
      <rect width="${thumbWidth}" height="${labelHeight}" fill="${palette.white}"/>
      <text x="0" y="34" fill="${palette.ink}" font-family="Apple SD Gothic Neo, Arial Unicode MS, sans-serif" font-size="22" font-weight="600">${esc(path.basename(pngPaths[index], ".png"))}</text>
    </svg>`;
    composites.push({ input: Buffer.from(labelSvg), left, top: top + thumbHeight });
  }

  await sharp({
    create: {
      width: canvasWidth,
      height: canvasHeight,
      channels: 4,
      background: palette.white,
    },
  })
    .composite(composites)
    .png({ compressionLevel: 9 })
    .toFile(path.join(FIGURE_DIR, "Figure_contact_sheet.png"));
}

async function main() {
  const pngPaths = [];
  for (const [name, svg] of figures) {
    pngPaths.push(await writeFigure(name, svg));
  }
  await writeContactSheet(pngPaths);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
