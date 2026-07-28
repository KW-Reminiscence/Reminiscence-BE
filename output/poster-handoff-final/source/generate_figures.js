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
fs.mkdirSync(FIGURE_DIR, { recursive: true });

const palette = {
  ink: "#2F2523",
  muted: "#6F625F",
  blue: "#8A1601",
  blueDark: "#651000",
  blueLight: "#F3D7D1",
  blueOpen: "#F8EDEA",
  gold: "#B64E38",
  goldLight: "#F3D7D1",
  line: "#C8B8B4",
  grid: "#E8DEDB",
  soft: "#F6F3F2",
  white: "#FFFFFF",
};

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function text(x, y, value, size = 24, options = {}) {
  const {
    fill = palette.ink,
    anchor = "start",
    weight = 400,
    family = "Apple SD Gothic Neo, Arial Unicode MS, sans-serif",
    letterSpacing = 0,
  } = options;
  return `<text x="${x}" y="${y}" fill="${fill}" font-family="${family}" font-size="${size}" font-weight="${weight}" text-anchor="${anchor}" letter-spacing="${letterSpacing}">${esc(value)}</text>`;
}

function multiline(x, y, lines, size = 24, options = {}) {
  const {
    fill = palette.ink,
    anchor = "start",
    weight = 400,
    lineHeight = Math.round(size * 1.35),
  } = options;
  const spans = lines
    .map(
      (line, index) =>
        `<tspan x="${x}" dy="${index === 0 ? 0 : lineHeight}">${esc(line)}</tspan>`,
    )
    .join("");
  return `<text x="${x}" y="${y}" fill="${fill}" font-family="Apple SD Gothic Neo, Arial Unicode MS, sans-serif" font-size="${size}" font-weight="${weight}" text-anchor="${anchor}">${spans}</text>`;
}

function rect(x, y, width, height, options = {}) {
  const {
    fill = palette.white,
    stroke = palette.line,
    strokeWidth = 2,
    radius = 18,
    dash = "",
  } = options;
  return `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"${dash ? ` stroke-dasharray="${dash}"` : ""}/>`;
}

function line(x1, y1, x2, y2, options = {}) {
  const {
    stroke = palette.line,
    strokeWidth = 3,
    dash = "",
    arrow = false,
  } = options;
  const marker =
    stroke === palette.line || stroke === palette.muted
      ? "arrow-muted"
      : stroke === palette.gold
        ? "arrow-gold"
        : "arrow";
  return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${strokeWidth}"${dash ? ` stroke-dasharray="${dash}"` : ""}${arrow ? ` marker-end="url(#${marker})"` : ""}/>`;
}

function polyline(points, options = {}) {
  const {
    stroke = palette.blue,
    strokeWidth = 4,
    dash = "",
    arrow = false,
    fill = "none",
  } = options;
  const encoded = points.map(([x, y]) => `${x},${y}`).join(" ");
  const marker =
    stroke === palette.line || stroke === palette.muted
      ? "arrow-muted"
      : stroke === palette.gold
        ? "arrow-gold"
        : "arrow";
  return `<polyline points="${encoded}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}" stroke-linejoin="round" stroke-linecap="round"${dash ? ` stroke-dasharray="${dash}"` : ""}${arrow ? ` marker-end="url(#${marker})"` : ""}/>`;
}

function circle(cx, cy, radius, options = {}) {
  const {
    fill = palette.white,
    stroke = palette.blue,
    strokeWidth = 3,
  } = options;
  return `<circle cx="${cx}" cy="${cy}" r="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
}

function diamond(cx, cy, radius, options = {}) {
  const {
    fill = palette.gold,
    stroke = palette.blueDark,
    strokeWidth = 2,
  } = options;
  const points = [
    [cx, cy - radius],
    [cx + radius, cy],
    [cx, cy + radius],
    [cx - radius, cy],
  ]
    .map(([x, y]) => `${x},${y}`)
    .join(" ");
  return `<polygon points="${points}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
}

function baseSvg(width, height, body) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
  <defs>
    <marker id="arrow" viewBox="0 0 12 12" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0,1 L0,11 L10,6 z" fill="${palette.blueDark}"/>
    </marker>
    <marker id="arrow-muted" viewBox="0 0 12 12" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0,1 L0,11 L10,6 z" fill="${palette.line}"/>
    </marker>
    <marker id="arrow-gold" viewBox="0 0 12 12" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0,1 L0,11 L10,6 z" fill="${palette.gold}"/>
    </marker>
  </defs>
  <rect width="${width}" height="${height}" fill="${palette.white}"/>
  ${body}
</svg>`;
}

function sectionLabel(x, y, width, label) {
  return [
    rect(x, y, width, 44, {
      fill: palette.blueOpen,
      stroke: "none",
      strokeWidth: 0,
      radius: 8,
    }),
    text(x + 16, y + 30, label, 22, {
      fill: palette.blueDark,
      weight: 500,
    }),
  ].join("");
}

function figureSystemBoundary() {
  const body = [];
  body.push(text(70, 72, "시스템과 데이터 경계", 46, { weight: 500 }));
  body.push(
    text(
      70,
      112,
      "WAV는 OpenAI API에서 일시 처리하고, 축약 지표만 Raspberry Pi에 저장",
      24,
      { fill: palette.muted },
    ),
  );

  body.push(rect(55, 155, 335, 635, { fill: palette.soft, stroke: palette.line }));
  body.push(rect(450, 135, 720, 675, { fill: palette.blueOpen, stroke: palette.blue }));
  body.push(
    rect(1235, 155, 310, 635, {
      fill: palette.white,
      stroke: palette.line,
      dash: "10 8",
    }),
  );
  body.push(sectionLabel(75, 175, 295, "태블릿"));
  body.push(sectionLabel(470, 155, 680, "Raspberry Pi · Reminiscence API"));
  body.push(sectionLabel(1255, 175, 270, "외부 서비스"));

  body.push(polyline([[355, 315], [480, 315]], {
    stroke: palette.blueDark,
    dash: "10 8",
    arrow: true,
  }));
  body.push(polyline([[620, 245], [620, 215], [1270, 215], [1270, 285]], {
    stroke: palette.blueDark,
    dash: "10 8",
    arrow: true,
  }));
  body.push(polyline([[1270, 355], [1120, 355]], {
    stroke: palette.blueDark,
    dash: "10 8",
    arrow: true,
  }));
  body.push(polyline([[1120, 315], [1150, 315], [1150, 660], [1120, 660]], {
    stroke: palette.blue,
    arrow: true,
  }));
  body.push(polyline([[760, 500], [840, 500]], {
    stroke: palette.blue,
    arrow: true,
  }));
  body.push(polyline([[840, 545], [805, 545], [805, 580], [410, 580], [410, 500], [355, 500]], {
    stroke: palette.blue,
    arrow: true,
  }));
  body.push(polyline([[355, 685], [480, 685]], {
    stroke: palette.blue,
    arrow: true,
  }));
  body.push(polyline([[760, 685], [840, 685]], {
    stroke: palette.blue,
    arrow: true,
  }));
  body.push(polyline([[1120, 705], [1270, 705]], {
    stroke: palette.blue,
    arrow: true,
  }));

  const tabletBoxes = [
    [90, 250, 265, 130, "마이크 입력", ["WAV ≤ 10 MiB", "회상 대화 턴"]],
    [90, 435, 265, 130, "화면 · 스피커", ["가족사진과 안내", "합성 WAV 재생"]],
    [90, 620, 265, 130, "루틴 입력", ["큰 기록 버튼", "실제 수행 후 확인"]],
  ];
  for (const [x, y, w, h, heading, lines] of tabletBoxes) {
    body.push(rect(x, y, w, h, { fill: palette.white, stroke: palette.line, radius: 12 }));
    body.push(text(x + w / 2, y + 42, heading, 24, { anchor: "middle", weight: 500 }));
    body.push(multiline(x + w / 2, y + 79, lines, 18, {
      anchor: "middle",
      fill: palette.muted,
      lineHeight: 28,
    }));
  }

  const piBoxes = [
    [480, 245, 280, 130, "WAV 검증·정규화", ["16 kHz · mono", "PCM 16-bit · 메모리 처리"]],
    [840, 245, 280, 130, "대화 지표 축약", ["text → 글자 수·시간", "무응답·ASR 처리 지표"]],
    [480, 435, 280, 130, "안전한 고정형 질문", ["사진 사실을 단정하지 않는", "열린 질문 template"]],
    [840, 435, 280, 130, "Supertonic 3", ["한국어 · F1 · speed 0.9", "로컬 PCM 16-bit WAV"]],
    [480, 620, 280, 130, "루틴 상태 머신", ["REMINDING · CONFIRMED", "NOT_ANSWERED"]],
    [840, 600, 280, 170, "로컬 JSON·변화 평가", ["설정·활동 지표·최신 상태", "루틴·대화 영역별 후보", "연속 이상 평가 기본 3회"]],
  ];
  for (const [x, y, w, h, heading, lines] of piBoxes) {
    body.push(rect(x, y, w, h, { fill: palette.white, stroke: palette.line, radius: 12 }));
    body.push(text(x + 18, y + 37, heading, 22, { fill: palette.blueDark, weight: 500 }));
    body.push(multiline(x + 18, y + 75, lines, 18, { fill: palette.muted, lineHeight: 28 }));
  }

  body.push(rect(1270, 250, 240, 145, { fill: palette.goldLight, stroke: palette.gold, radius: 12 }));
  body.push(text(1390, 293, "OpenAI API", 26, { anchor: "middle", weight: 500 }));
  body.push(multiline(1390, 334, ["/v1/audio/transcriptions", "gpt-4o-transcribe"], 17, {
    anchor: "middle",
    fill: palette.ink,
    lineHeight: 28,
  }));
  body.push(rect(1270, 640, 240, 130, { fill: palette.white, stroke: palette.line, radius: 12 }));
  body.push(text(1390, 682, "SMTP", 26, { anchor: "middle" }));
  body.push(multiline(1390, 720, ["관찰 근거 이메일", "episode당 최대 1회 시도"], 18, {
    anchor: "middle",
    fill: palette.muted,
    lineHeight: 28,
  }));

  body.push(text(414, 300, "WAV", 17, { anchor: "middle", fill: palette.blueDark }));
  body.push(text(950, 203, "정규화 WAV · 일시 처리", 17, {
    anchor: "middle",
    fill: palette.blueDark,
  }));
  body.push(text(1195, 342, "전사 text", 17, { anchor: "middle", fill: palette.blueDark }));
  body.push(text(610, 570, "합성 WAV", 17, { anchor: "middle", fill: palette.blue }));

  body.push(line(70, 835, 165, 835, { stroke: palette.blue, strokeWidth: 4 }));
  body.push(text(180, 842, "실선 · 로컬 처리·저장", 19, { fill: palette.muted }));
  body.push(line(520, 835, 615, 835, { stroke: palette.blueDark, strokeWidth: 4, dash: "10 8" }));
  body.push(text(630, 842, "점선 · 네트워크 일시 처리", 19, { fill: palette.muted }));
  body.push(text(1530, 842, "로컬 보존 · 축약 지표만", 18, {
    anchor: "end",
    fill: palette.gold,
  }));

  return baseSvg(1600, 900, body.join("\n"));
}

function figureUserScenario() {
  const body = [];
  body.push(text(70, 72, "가족사진 화면을 중심으로 한 사용자 시나리오", 46, { weight: 500 }));
  body.push(
    text(
      70,
      112,
      "루틴·대화 종료 후 사진 화면으로 복귀 · 연속 이상 평가 기본 3회 후 상태 전환",
      23,
      { fill: palette.muted },
    ),
  );

  body.push(rect(585, 150, 430, 100, { fill: palette.blueLight, stroke: palette.blue, radius: 18 }));
  body.push(text(800, 191, "가족사진 기본 화면", 29, { anchor: "middle", weight: 500 }));
  body.push(text(800, 224, "날짜와 사진 표시 · 평상시 조작 요구 없음", 19, {
    anchor: "middle",
    fill: palette.muted,
  }));
  body.push(polyline([[720, 250], [720, 275], [395, 275], [395, 305]], {
    stroke: palette.line,
    strokeWidth: 2,
    dash: "6 6",
  }));
  body.push(polyline([[880, 250], [880, 275], [1205, 275], [1205, 305]], {
    stroke: palette.line,
    strokeWidth: 2,
    dash: "6 6",
  }));

  body.push(sectionLabel(70, 305, 650, "루틴 기록 흐름"));
  body.push(sectionLabel(880, 305, 650, "회상 대화 흐름"));

  const routine = [
    [75, 380, 175, 98, "예정 시각", ["안내 음성", "큰 기록 버튼"]],
    [290, 380, 175, 98, "응답 확인", ["버튼 입력", "기한 검사"]],
    [505, 360, 200, 78, "CONFIRMED", ["확인 지연 저장"]],
    [505, 465, 200, 92, "재알림", ["유예·간격 적용", "기한 종료 시 미응답"]],
  ];
  for (const [x, y, w, h, heading, lines] of routine) {
    body.push(rect(x, y, w, h, {
      fill: heading === "CONFIRMED" ? palette.blueLight : palette.white,
      stroke: heading === "CONFIRMED" ? palette.blue : palette.line,
      radius: 12,
    }));
    body.push(text(x + w / 2, y + 32, heading, 21, { anchor: "middle", weight: 500 }));
    body.push(multiline(x + w / 2, y + 60, lines, 17, {
      anchor: "middle",
      fill: palette.muted,
      lineHeight: 24,
    }));
  }
  body.push(line(250, 429, 290, 429, { stroke: palette.blueDark, arrow: true }));
  body.push(polyline([[465, 410], [485, 410], [485, 399], [505, 399]], {
    stroke: palette.blueDark,
    arrow: true,
  }));
  body.push(polyline([[465, 448], [485, 448], [485, 510], [505, 510]], {
    stroke: palette.line,
    arrow: true,
  }));
  body.push(text(480, 470, "미입력", 16, { anchor: "end", fill: palette.muted }));
  body.push(rect(290, 585, 415, 80, { fill: palette.soft, stroke: palette.line, radius: 12 }));
  body.push(text(497, 617, "종료 후 기본 화면 복귀", 22, { anchor: "middle" }));
  body.push(text(497, 648, "미응답도 사진 화면으로 복귀", 17, {
    anchor: "middle",
    fill: palette.muted,
  }));
  body.push(line(605, 438, 605, 585, { stroke: palette.blue, arrow: true }));
  body.push(line(605, 557, 605, 585, { stroke: palette.line, arrow: true }));

  const conversation = [
    [885, 380, 190, 98, "대화 시작", ["정시 권유", "또는 자발적 시작"]],
    [1110, 380, 190, 98, "열린 질문", ["안전 template", "Supertonic 3 WAV"]],
    [1335, 380, 190, 98, "사용자 응답", ["WAV 전사", "지표 축약"]],
  ];
  for (const [x, y, w, h, heading, lines] of conversation) {
    body.push(rect(x, y, w, h, { fill: palette.white, stroke: palette.line, radius: 12 }));
    body.push(text(x + w / 2, y + 32, heading, 21, { anchor: "middle", weight: 500 }));
    body.push(multiline(x + w / 2, y + 60, lines, 17, {
      anchor: "middle",
      fill: palette.muted,
      lineHeight: 24,
    }));
  }
  body.push(line(1075, 429, 1110, 429, { stroke: palette.blueDark, arrow: true }));
  body.push(line(1300, 429, 1335, 429, { stroke: palette.blueDark, arrow: true }));
  body.push(rect(1010, 585, 410, 80, { fill: palette.soft, stroke: palette.line, radius: 12 }));
  body.push(text(1215, 617, "세션 요약 후 기본 화면 복귀", 22, { anchor: "middle" }));
  body.push(text(1215, 648, "정시 권유 미참여는 기록하지 않음", 17, {
    anchor: "middle",
    fill: palette.muted,
  }));
  body.push(polyline([[1430, 478], [1430, 540], [1215, 540], [1215, 585]], {
    stroke: palette.blue,
    arrow: true,
  }));

  body.push(rect(230, 735, 1140, 92, { fill: palette.goldLight, stroke: palette.gold, radius: 14 }));
  body.push(text(260, 772, "완료 지표 누적", 20, { fill: palette.ink }));
  body.push(line(420, 765, 505, 765, { stroke: palette.blueDark, arrow: true }));
  body.push(text(530, 772, "domain별 평가·OR", 20));
  body.push(line(720, 765, 805, 765, { stroke: palette.blueDark, arrow: true }));
  body.push(text(830, 772, "연속 이상 count 3/3", 20));
  body.push(line(1050, 765, 1135, 765, { stroke: palette.blueDark, arrow: true }));
  body.push(text(1160, 772, "SMTP 1회 시도", 20));
  body.push(text(800, 812, "저장 상태 ANOMALOUS 전환 · episode당 최대 1회 시도 · 의료 진단·응급 신고 제외", 17, {
    anchor: "middle",
    fill: palette.gold,
  }));
  body.push(polyline([[497, 665], [497, 705], [430, 705], [430, 735]], {
    stroke: palette.line,
    dash: "6 6",
  }));
  body.push(polyline([[1215, 665], [1215, 705], [1170, 705], [1170, 735]], {
    stroke: palette.line,
    dash: "6 6",
  }));

  return baseSvg(1600, 900, body.join("\n"));
}

function figureRoutineTimeline() {
  const body = [];
  body.push(text(70, 72, "루틴 상태 타임라인", 46, { weight: 500 }));
  body.push(
    text(
      70,
      112,
      "시연 설정 · 09:00 시작 · 10분 간격 · 재알림 3회 · 09:40 마감",
      23,
      { fill: palette.muted },
    ),
  );

  const xs = [160, 470, 780, 1090, 1400];
  const labels = ["09:00", "09:10", "09:20", "09:30", "09:40"];
  body.push(rect(160, 332, 1240, 88, { fill: palette.blueOpen, stroke: "none", strokeWidth: 0, radius: 10 }));
  body.push(text(780, 322, "확인 가능 구간 [09:00, 09:40)", 21, {
    anchor: "middle",
    fill: palette.blueDark,
  }));
  body.push(line(160, 376, 1400, 376, { stroke: palette.blueDark, strokeWidth: 5 }));

  for (let index = 0; index < xs.length; index += 1) {
    const x = xs[index];
    const isDeadline = index === xs.length - 1;
    body.push(
      isDeadline
        ? diamond(x, 376, 14, { fill: palette.gold, stroke: palette.blueDark })
        : circle(x, 376, 11, { fill: palette.white, stroke: palette.blue, strokeWidth: 4 }),
    );
    body.push(text(x, 438, labels[index], 24, {
      anchor: "middle",
      weight: 500,
      fill: isDeadline ? palette.gold : palette.ink,
    }));
  }

  const cards = [
    [75, 175, 210, 105, "최초 안내", ["REMINDING 시작", "재알림 수 0"]],
    [365, 500, 210, 105, "재알림 1", ["버튼 미입력 시", "reminder count 1"]],
    [675, 175, 210, 105, "재알림 2", ["버튼 미입력 시", "reminder count 2"]],
    [985, 500, 210, 105, "재알림 3", ["버튼 미입력 시", "reminder count 3"]],
    [1295, 175, 230, 105, "응답 기한", ["09:40 도달", "NOT_ANSWERED"]],
  ];
  for (const [x, y, w, h, heading, lines] of cards) {
    const deadline = heading === "응답 기한";
    body.push(rect(x, y, w, h, {
      fill: deadline ? palette.goldLight : palette.white,
      stroke: deadline ? palette.gold : palette.line,
      radius: 12,
    }));
    body.push(text(x + w / 2, y + 35, heading, 22, {
      anchor: "middle",
      weight: 500,
      fill: deadline ? palette.gold : palette.blueDark,
    }));
    body.push(multiline(x + w / 2, y + 67, lines, 17, {
      anchor: "middle",
      fill: palette.muted,
      lineHeight: 24,
    }));
  }
  body.push(line(160, 280, 160, 360, { stroke: palette.line }));
  body.push(line(470, 392, 470, 500, { stroke: palette.line }));
  body.push(line(780, 280, 780, 360, { stroke: palette.line }));
  body.push(line(1090, 392, 1090, 500, { stroke: palette.line }));
  body.push(line(1400, 280, 1400, 360, { stroke: palette.gold }));

  body.push(rect(230, 690, 500, 105, { fill: palette.blueLight, stroke: palette.blue, radius: 14 }));
  body.push(text(480, 730, "응답 가능 시간에 버튼 입력", 23, { anchor: "middle", weight: 500 }));
  body.push(text(480, 768, "CONFIRMED · 재알림 중단 · 확인 지연 저장", 19, {
    anchor: "middle",
    fill: palette.muted,
  }));
  body.push(rect(870, 690, 500, 105, { fill: palette.goldLight, stroke: palette.gold, radius: 14 }));
  body.push(text(1120, 730, "09:40 도달 시 입력 없음", 23, {
    anchor: "middle",
    weight: 500,
    fill: palette.gold,
  }));
  body.push(text(1120, 768, "NOT_ANSWERED · 사진 화면 복귀", 19, {
    anchor: "middle",
    fill: palette.muted,
  }));
  body.push(polyline([[625, 420], [625, 645], [480, 645], [480, 690]], {
    stroke: palette.blue,
    arrow: true,
  }));
  body.push(polyline([[1400, 420], [1480, 420], [1480, 645], [1120, 645], [1120, 690]], {
    stroke: palette.gold,
    arrow: true,
  }));
  body.push(text(800, 860, "최초 안내는 재알림 횟수에서 제외 · 정책·표시 정보는 실행 시작 시 고정", 18, {
    anchor: "middle",
    fill: palette.muted,
  }));

  return baseSvg(1600, 900, body.join("\n"));
}

function panelPlot({
  x,
  y,
  width,
  height,
  title: panelTitle,
  unit,
  values,
  maxValue,
  ticks,
}) {
  const parts = [];
  const padLeft = 54;
  const padRight = 24;
  const padTop = 60;
  const padBottom = 54;
  const plotX = x + padLeft;
  const plotY = y + padTop;
  const plotWidth = width - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;
  const sx = (session) => plotX + ((session - 1) / 20) * plotWidth;
  const sy = (value) => plotY + plotHeight - (value / maxValue) * plotHeight;

  parts.push(rect(x, y, width, height, { fill: palette.white, stroke: palette.line, radius: 12 }));
  parts.push(text(x + 20, y + 34, panelTitle, 22, { fill: palette.blueDark, weight: 500 }));
  parts.push(text(x + width - 20, y + 34, unit, 17, { anchor: "end", fill: palette.muted }));
  parts.push(`<rect x="${plotX}" y="${plotY}" width="${sx(20) - plotX + 8}" height="${plotHeight}" fill="${palette.blueOpen}" stroke="none"/>`);
  parts.push(`<rect x="${sx(20) + 8}" y="${plotY}" width="${plotX + plotWidth - sx(20) - 8}" height="${plotHeight}" fill="${palette.goldLight}" stroke="none"/>`);

  for (const tick of ticks) {
    const yy = sy(tick);
    parts.push(line(plotX, yy, plotX + plotWidth, yy, { stroke: palette.grid, strokeWidth: 1 }));
    parts.push(text(plotX - 10, yy + 6, tick, 15, { anchor: "end", fill: palette.muted }));
  }
  parts.push(line(plotX, plotY, plotX, plotY + plotHeight, { stroke: palette.line, strokeWidth: 2 }));
  parts.push(line(plotX, plotY + plotHeight, plotX + plotWidth, plotY + plotHeight, { stroke: palette.line, strokeWidth: 2 }));
  for (const tick of [1, 5, 10, 15, 21]) {
    const xx = sx(tick);
    parts.push(line(xx, plotY + plotHeight, xx, plotY + plotHeight + 7, { stroke: palette.line, strokeWidth: 1 }));
    parts.push(text(xx, plotY + plotHeight + 27, `S${tick}`, 14, { anchor: "middle", fill: palette.muted }));
  }
  parts.push(line(sx(21), plotY, sx(21), plotY + plotHeight, {
    stroke: palette.gold,
    strokeWidth: 2,
    dash: "7 6",
  }));

  const points = values.map((value, index) => [sx(index + 1), sy(value)]);
  const baselinePoints = points.slice(0, -1);
  parts.push(polyline(baselinePoints, { stroke: palette.muted, strokeWidth: 4 }));
  for (let index = 0; index < baselinePoints.length; index += 1) {
    const [px, py] = points[index];
    parts.push(circle(px, py, 4.5, {
      fill: palette.white,
      stroke: palette.muted,
      strokeWidth: 2,
    }));
  }
  parts.push(polyline(points.slice(-2), {
    stroke: palette.blue,
    strokeWidth: 4,
    dash: "7 5",
  }));
  const [lastX, lastY] = points.at(-1);
  parts.push(diamond(lastX, lastY, 9, {
    fill: palette.blue,
    stroke: palette.blueDark,
    strokeWidth: 2,
  }));
  parts.push(text(lastX - 12, Math.max(plotY + 18, lastY - 15), `${values.at(-1)}`, 18, {
    anchor: "end",
    fill: palette.blue,
    weight: 500,
  }));
  parts.push(text(plotX + 12, plotY + 22, "기준 S1–S20", 15, { fill: palette.muted }));
  parts.push(text(plotX + plotWidth - 8, plotY + 22, "현재", 15, {
    anchor: "end",
    fill: palette.blue,
  }));

  return parts.join("\n");
}

function figureSyntheticReplay() {
  const body = [];
  const replayResult = JSON.parse(
    fs.readFileSync(
      path.join(ROOT, "evidence", "synthetic_anomaly_result.json"),
      "utf8",
    ),
  );
  const domainResult = replayResult.domain_result;
  const serviceReplay = replayResult.service_replay;
  body.push(text(70, 65, "합성 입력에 대한 이상 탐지 동작 예시", 44, { weight: 500 }));
  body.push(
    text(
      70,
      105,
      "대화 feature 5개 중 3개 표시 · 기준 완료 세션 20건 + 현재 세션 1건",
      22,
      { fill: palette.muted },
    ),
  );
  body.push(rect(70, 130, 1460, 54, { fill: palette.goldLight, stroke: "none", strokeWidth: 0, radius: 8 }));
  body.push(text(800, 165, "합성 데이터 · 동작 검증용 · 사용자·임상 자료 아님", 21, {
    anchor: "middle",
    fill: palette.gold,
    weight: 500,
  }));

  const fixture = JSON.parse(
    fs.readFileSync(
      path.join(ROOT, "source", "synthetic_anomaly_fixture.json"),
      "utf8",
    ),
  );
  const recentTurns = fixture.map((row, index) => {
    const currentDay = row.day_offset;
    return fixture
      .slice(0, index + 1)
      .filter((candidate) => candidate.day_offset > currentDay - 7)
      .reduce((sum, candidate) => sum + candidate.user_turn_count, 0);
  });
  const chars = fixture.map((row) => row.total_utterance_chars);
  const noResponse = fixture.map((row) => row.no_response_count);
  body.push(panelPlot({
    x: 60,
    y: 220,
    width: 465,
    height: 390,
    title: "최근 7일 사용자 턴 수",
    unit: "회",
    values: recentTurns,
    maxValue: 42,
    ticks: [0, 10, 20, 30, 40],
  }));
  body.push(panelPlot({
    x: 568,
    y: 220,
    width: 465,
    height: 390,
    title: "세션 총 발화 글자 수",
    unit: "공백 제외 글자",
    values: chars,
    maxValue: 180,
    ticks: [0, 50, 100, 150],
  }));
  body.push(panelPlot({
    x: 1076,
    y: 220,
    width: 465,
    height: 390,
    title: "세션 무응답 횟수",
    unit: "회",
    values: noResponse,
    maxValue: 4,
    ticks: [0, 1, 2, 3, 4],
  }));

  body.push(text(
    800,
    650,
    `동일 최신 지표의 service replay · ${serviceReplay.interval_seconds}초 간격 · 확인 횟수 ${serviceReplay.confirmation_count}`,
    18,
    { anchor: "middle", fill: palette.muted },
  ));

  const strip = serviceReplay.evaluations.map((evaluation, index) => [
    95 + index * 350,
    `주기 평가 ${evaluation.evaluation}`,
    `후보 ${evaluation.candidate_status}`,
    `count ${evaluation.consecutive_count}/${serviceReplay.confirmation_count} · ${evaluation.stored_status} · ${evaluation.notification_status}`,
    evaluation.stored_status === "ANOMALOUS",
  ]);
  for (let index = 0; index < strip.length; index += 1) {
    const [x, top, middle, bottom, confirmed] = strip[index];
    body.push(rect(x, 675, 260, 105, {
      fill: confirmed ? palette.goldLight : palette.soft,
      stroke: confirmed ? palette.gold : palette.line,
      radius: 12,
    }));
    body.push(text(x + 130, 706, top, 18, {
      anchor: "middle",
      fill: confirmed ? palette.gold : palette.muted,
    }));
    body.push(text(x + 130, 738, middle, 21, { anchor: "middle", weight: 500 }));
    body.push(text(x + 130, 766, bottom, 14, {
      anchor: "middle",
      fill: palette.muted,
    }));
    if (index < strip.length - 1) {
      body.push(line(x + 260, 728, x + 342, 728, { stroke: palette.blueDark, arrow: true }));
    }
  }

  body.push(text(
    70,
    850,
    `대화 domain 후보 ${domainResult.status} · decision function ${domainResult.decision_function.toFixed(6)}`,
    19,
    {
    fill: palette.blueDark,
    },
  ));
  body.push(text(1530, 850, "점수는 확률 아님 · SMTP는 episode당 최대 1회 시도", 19, {
    anchor: "end",
    fill: palette.gold,
  }));

  return baseSvg(1600, 900, body.join("\n"));
}

const figures = [
  ["Figure_01_system_data_boundary", figureSystemBoundary()],
  ["Figure_02_user_scenario", figureUserScenario()],
  ["Figure_03_routine_timeline", figureRoutineTimeline()],
  ["Figure_04_synthetic_anomaly_replay", figureSyntheticReplay()],
];

async function main() {
  for (const [name, svg] of figures) {
    const svgPath = path.join(FIGURE_DIR, `${name}.svg`);
    const pngPath = path.join(FIGURE_DIR, `${name}.png`);
    fs.writeFileSync(svgPath, svg, "utf8");
    await sharp(Buffer.from(svg), { density: 240 })
      .resize({ width: 3200 })
      .flatten({ background: palette.white })
      .png({ compressionLevel: 9, palette: false })
      .toFile(pngPath);
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
