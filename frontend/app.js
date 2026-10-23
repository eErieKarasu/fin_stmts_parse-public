const mcpUrlInput = document.querySelector("#mcpUrl");
const sessionInput = document.querySelector("#sessionId");
const fileInput = document.querySelector("#fileInput");
const selectedFilesEl = document.querySelector("#selectedFiles");
const useSdossInput = document.querySelector("#useSdoss");
const runBtn = document.querySelector("#runBtn");
const inspectBtn = document.querySelector("#inspectBtn");
const clearBtn = document.querySelector("#clearBtn");
const statusEl = document.querySelector("#status");
const progressLogEl = document.querySelector("#progressLog");
const summaryEl = document.querySelector("#summary");
const resultsEl = document.querySelector("#results");

let currentMapResults = null;
let currentInspectResult = null;
let currentParseResults = null;
let currentBatchError = "";
let currentActiveIndex = 0;
let hasPendingEdits = false;
let isBusy = false;

const statementOrder = { balance: 0, profit: 1, cashflow: 2 };
const statementTypeByName = {
  合并资产负债表: "balance",
  资产负债表: "balance",
  合并利润表: "profit",
  利润表: "profit",
  合并现金流量表: "cashflow",
  现金流量表: "cashflow",
};

const validationRules = {
  balance: [
    {
      names: ["流动资产合计"],
      codes: [
        "Z01010001",
        "Z01010100",
        "Z01010101",
        "Z01010104",
        "Z01010300",
        "Z01010610",
        "Z01010616",
        "Z01010611",
        "Z01011100",
        "Z01011210",
        "ZY2015082",
        "Z01011230",
        "Z01011510",
        "Z01011600",
      ],
    },
    {
      names: ["其他应收款"],
      codes: ["Z01011100", "Z01010500", "Z01010400"],
    },
    {
      names: ["非流动资产合计"],
      codes: [
        "ZY2015058",
        "ZY2015073",
        "ZY2015074",
        "Z01020240",
        "Z01020110",
        "ZY2015109",
        "ZY2015110",
        "Z01020121",
        "Z01030000",
        "Z01030300",
        "Z01020250",
        "Z01020260",
        "Z01020310",
        "Z01040100",
        "Z01020270",
        "Z01020280",
        "ZG1040110",
        "Z01044101",
        "Z01020290",
      ],
    },
    {
      names: [
        "资产总计",
        "资产总计 = 流动资产合计 + 非流动资产合计",
      ],
      codes: ["Z01000001", "Z01010001", "ZY2015058"],
    },
    {
      names: ["流动负债合计"],
      codes: [
        "Z02010001",
        "Z02010100",
        "Z02010101",
        "Z02010113",
        "Z02010200",
        "Z02010300",
        "Z02010410",
        "ZY2015093",
        "ZY2015006",
        "ZY2015008",
        "ZG2010800",
        "Z02010530",
        "Z02010540",
        "Z02011400",
      ],
    },
    {
      names: ["其他应付款"],
      codes: ["ZG2010800", "Z02010107", "Z02010700"],
    },
    {
      names: ["非流动负债合计"],
      codes: [
        "ZY2015061",
        "Z02020100",
        "Z02020200",
        "Z02020600",
        "Z02020300",
        "Z02011200",
        "L02060000",
        "Z01044104",
        "Z02011500",
      ],
    },
    {
      names: [
        "负债合计",
        "负债合计 = 流动负债合计 + 非流动负债合计",
      ],
      codes: ["Z02000001", "Z02010001", "ZY2015061"],
    },
    {
      names: ["归属于母公司所有者权益合计", "归属于母公司所有者权益（或股东权益）合计"],
      codes: [
        "Z04030400",
        "Z04020200",
        "Z04020300",
        "Z04020000",
        "Z04020600",
        "Z04020700",
        "Z04020800",
        "Z04030000",
        "Z04050000",
      ],
    },
    {
      names: ["其他权益工具"],
      codes: ["Z04020300", "Z04020400", "Z04020500"],
    },
    {
      names: [
        "所有者权益合计",
        "所有者权益（或股东权益）合计",
        "所有者权益（或股东权益）合计 = 归属于母公司所有者权益（或股东权益）合计 + 少数股东权益",
      ],
      codes: [
        "Z04020110",
        "Z04030400",
        "Z03000000",
        "Z04020200",
        "Z04020300",
        "Z04020000",
        "Z04020600",
        "Z04020700",
        "Z04020800",
        "Z04030000",
        "Z04050000",
      ],
    },
    {
      names: [
        "负债和所有者权益总计",
        "负债和所有者权益（或股东权益）总计",
        "负债和所有者权益总计 = 流动负债合计 + 非流动负债合计 + 所有者权益（或股东权益）合计",
        "负债和所有者权益（或股东权益）总计 = 流动负债合计 + 非流动负债合计 + 所有者权益（或股东权益）合计",
        "负债和所有者权益总计 = 负债合计 + 所有者权益（或股东权益）合计",
        "负债和所有者权益（或股东权益）总计 = 负债合计 + 所有者权益（或股东权益）合计",
      ],
      codes: ["Z05010000", "Z02000001", "Z04020110"],
    },
    {
      names: [
        "资产总计 = 负债和所有者权益总计",
        "资产总计 = 负债和所有者权益（或股东权益）总计",
        "负债和所有者权益总计 = 资产总计",
        "负债和所有者权益（或股东权益）总计 = 资产总计",
      ],
      codes: ["Z01000001", "Z05010000"],
    },
  ],
  profit: [
    {
      names: ["营业利润"],
      codes: [
        "L04010000",
        "L00000000",
        "L02010100",
        "L02010800",
        "L02010900",
        "L03040000",
        "L02011000",
        "L03050000",
        "L02011100",
        "L04020000",
        "SY1000006",
        "L02011200",
        "SY1000016",
        "SG5020000",
        "L02011300",
      ],
    },
    {
      names: ["利润总额"],
      codes: ["L05010000", "L04010000", "L04050000", "L04070000"],
    },
    {
      names: ["净利润 = 利润总额 - 所得税费用"],
      codes: ["L06010000", "L05010000", "L04010100"],
    },
    {
      names: ["净利润 = 持续经营净利润 + 终止经营净利润"],
      codes: ["L06010000", "L05010200", "L05010300"],
    },
    {
      names: ["综合收益总额"],
      codes: ["L07000000", "L06010000", "L06010100"],
    },
  ],
  cashflow: [
    {
      names: ["经营活动现金流入小计"],
      codes: ["X01040000", "X01010000", "X01020000", "X01030000"],
    },
    {
      names: ["经营活动现金流出小计"],
      codes: ["X01090000", "X01050000", "X01060000", "X01070000", "X01011800"],
    },
    {
      names: ["投资活动现金流入小计"],
      codes: ["X02050000", "X02010000", "X02020000", "X02030000", "X02030100", "X02040000"],
    },
    {
      names: ["投资活动现金流出小计"],
      codes: ["X02090000", "X02060000", "X02070000", "X02080200", "X02080300"],
    },
    {
      names: ["筹资活动现金流入小计"],
      codes: ["X03040000", "X03010000", "X02080500", "X03020100", "X03030000"],
    },
    {
      names: ["筹资活动现金流出小计"],
      codes: ["X03080000", "X03050000", "X03060000", "X03070000"],
    },
    {
      names: ["经营活动产生的现金流量净额 = 经营活动现金流入小计 - 经营活动现金流出小计"],
      codes: ["X01100000", "X01040000", "X01090000"],
    },
    {
      names: ["投资活动产生的现金流量净额 = 投资活动现金流入小计 - 投资活动现金流出小计"],
      codes: ["X02100000", "X02050000", "X02090000"],
    },
    {
      names: ["筹资活动产生的现金流量净额 = 筹资活动现金流入小计 - 筹资活动现金流出小计"],
      codes: ["X03090000", "X03040000", "X03080000"],
    },
  ],
};

function init() {
  sessionInput.value = `frontend-${Date.now()}`;
  fileInput.addEventListener("change", updateFileStatus);
  runBtn.addEventListener("click", runPipeline);
  inspectBtn.addEventListener("click", runInspect);
  clearBtn.addEventListener("click", clearResults);
  renderSelectedFiles();
  updateActionState();
}

function updateFileStatus() {
  const count = fileInput.files?.length || 0;
  currentParseResults = null;
  currentBatchError = "";
  currentMapResults = null;
  currentInspectResult = null;
  currentActiveIndex = 0;
  hasPendingEdits = false;
  summaryEl.hidden = true;
  summaryEl.innerHTML = "";
  resultsEl.innerHTML = "";
  resetProgressLog();
  renderSelectedFiles();
  updateActionState();
  setStatus(count ? `已选择 ${count} 个文件` : "等待输入");
}

function removeSelectedFile(removeIndex) {
  if (isBusy) return;
  const transfer = new DataTransfer();
  Array.from(fileInput.files || []).forEach((file, index) => {
    if (index !== removeIndex) transfer.items.add(file);
  });
  fileInput.files = transfer.files;
  updateFileStatus();
}

function renderSelectedFiles() {
  const files = Array.from(fileInput.files || []);
  selectedFilesEl.innerHTML = "";

  if (!files.length) {
    selectedFilesEl.className = "selected-files empty-file-queue";
    const empty = document.createElement("p");
    empty.textContent = "尚未选择文件";
    selectedFilesEl.appendChild(empty);
    return;
  }

  selectedFilesEl.className = "selected-files";
  const header = document.createElement("div");
  header.className = "file-queue-head";
  const title = document.createElement("strong");
  title.textContent = `待处理文件 ${files.length} 个`;
  const total = document.createElement("span");
  total.textContent = formatFileSize(
    files.reduce((sum, file) => sum + Number(file.size || 0), 0),
  );
  header.append(title, total);
  selectedFilesEl.appendChild(header);

  const list = document.createElement("ul");
  list.className = "file-queue";
  files.forEach((file, index) => {
    const parseResult = currentParseResults?.[index];
    const item = document.createElement("li");
    item.className = "file-queue-item";

    const details = document.createElement("div");
    details.className = "file-details";
    const name = document.createElement("strong");
    name.textContent = file.name;
    name.title = file.name;
    const meta = document.createElement("span");
    meta.textContent = `${formatFileSize(file.size)} · ${getFileExtension(file.name)}`;
    details.append(name, meta);

    const state = document.createElement("span");
    const stateInfo = resolveFileState(parseResult, currentBatchError);
    state.className = `file-state ${stateInfo.kind}`;
    state.textContent = stateInfo.label;
    state.title = stateInfo.label;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "file-remove";
    remove.textContent = "移除";
    remove.disabled = isBusy;
    remove.setAttribute("aria-label", `移除 ${file.name}`);
    remove.addEventListener("click", () => removeSelectedFile(index));

    item.append(details, state, remove);
    list.appendChild(item);
  });
  selectedFilesEl.appendChild(list);
}

function resolveFileState(parseResult, batchError) {
  if (batchError) return { kind: "error", label: "批次失败" };
  if (parseResult) {
    const message = String(parseResult.message || "已完成");
    const warning = message.includes("未识别") || message.includes("成功但");
    const failed =
      !warning && (message.includes("失败") || message.includes("不支持"));
    return {
      kind: failed ? "error" : warning ? "warning" : "success",
      label: message,
    };
  }
  if (isBusy) return { kind: "processing", label: "解析中" };
  return { kind: "ready", label: "已就绪" };
}

function formatFileSize(bytes) {
  const size = Number(bytes || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 ** 2).toFixed(1)} MB`;
}

function getFileExtension(fileName) {
  const extension = String(fileName || "").split(".").pop();
  return extension && extension !== fileName ? extension.toUpperCase() : "FILE";
}

function clearResults() {
  fileInput.value = "";
  currentParseResults = null;
  currentBatchError = "";
  currentMapResults = null;
  currentInspectResult = null;
  currentActiveIndex = 0;
  hasPendingEdits = false;
  summaryEl.hidden = true;
  summaryEl.innerHTML = "";
  resultsEl.innerHTML = "";
  resetProgressLog();
  renderSelectedFiles();
  updateActionState();
  setStatus("结果已清空");
}

async function runPipeline() {
  const files = Array.from(fileInput.files || []);
  if (!files.length) {
    setStatus("请先选择财报文件", true);
    return;
  }

  setBusy(true);
  currentParseResults = null;
  currentBatchError = "";
  renderSelectedFiles();
  resetProgressLog();
  setStatus("正在上传文件并调用 parse_fin_stmts_markdown / fin_stmts_parse_map / 被动校验...");

  try {
    const form = new FormData();
    form.append("mcp_url", mcpUrlInput.value.trim());
    form.append("session_id", sessionInput.value.trim());
    form.append("report_status", "0");
    form.append("use_sdoss", useSdossInput.checked ? "1" : "0");
    for (const file of files) {
      form.append("files", file, file.name);
    }

    const payload = await fetchStreamedJson(
      "/api/upload-stream",
      {
        method: "POST",
        body: form,
      },
      appendProgressEvent,
    );

    currentParseResults = Array.isArray(payload.parse_results)
      ? payload.parse_results
      : [];
    currentBatchError = "";
    currentMapResults = payload.map_results;
    currentInspectResult = payload.inspect_result || null;
    currentActiveIndex = 0;
    hasPendingEdits = false;
    render(currentMapResults, currentInspectResult, 0);
    renderSelectedFiles();
    setStatus("上传解析和被动校验完成，可编辑期初/期末后点击 MCP 校验重新校验");
  } catch (error) {
    currentBatchError = error.message;
    renderSelectedFiles();
    setStatus(`调用失败：${error.message}`, true);
  } finally {
    setBusy(false);
  }
}

async function runInspect() {
  if (!isCompleteMapResults(currentMapResults)) {
    setStatus("请先上传解析得到映射结果", true);
    return;
  }

  setBusy(true);
  resetProgressLog();
  setStatus("正在单独调用 fin_stmts_parse_inspect...");

  try {
    const payload = await fetchStreamedJson(
      "/api/inspect-stream",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mcp_url: mcpUrlInput.value.trim(),
          session_id: sessionInput.value.trim(),
          report_status: "1",
          map_results: buildInspectableMapResults(currentMapResults),
        }),
      },
      appendProgressEvent,
    );

    currentInspectResult = payload.inspect_result;
    hasPendingEdits = false;
    render(currentMapResults, currentInspectResult, currentActiveIndex);
    setStatus("MCP 校验完成");
  } catch (error) {
    setStatus(`校验失败：${error.message}`, true);
  } finally {
    setBusy(false);
  }
}

function buildInspectableMapResults(mapResults) {
  return JSON.parse(JSON.stringify(mapResults || []));
}

function markValidationDirty() {
  const wasPending = hasPendingEdits;
  hasPendingEdits = true;
  if (!wasPending) {
    renderSummary(currentMapResults, currentInspectResult);
  }
  setStatus("数值已修改，原校验信息暂保留；点击 MCP 校验后刷新");
}

function setBusy(value) {
  isBusy = value;
  renderSelectedFiles();
  updateActionState();
}

async function fetchStreamedJson(url, options, onProgress) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await safeReadJson(response);
    throw new Error(payload?.error || `HTTP ${response.status}`);
  }

  if (!response.body) {
    return response.json();
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let resultPayload;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      const event = parseStreamEvent(line);
      if (!event) continue;
      if (event.type === "progress") {
        onProgress?.(event);
      } else if (event.type === "result") {
        resultPayload = event.payload;
      } else if (event.type === "error") {
        throw new Error(event.error || "流式调用失败");
      }
    }
  }

  const tailEvent = parseStreamEvent(buffer);
  if (tailEvent?.type === "result") {
    resultPayload = tailEvent.payload;
  } else if (tailEvent?.type === "error") {
    throw new Error(tailEvent.error || "流式调用失败");
  } else if (tailEvent?.type === "progress") {
    onProgress?.(tailEvent);
  }

  if (resultPayload === undefined) {
    throw new Error("流式响应缺少最终结果");
  }
  return resultPayload;
}

async function safeReadJson(response) {
  try {
    return await response.json();
  } catch (_) {
    return null;
  }
}

function parseStreamEvent(line) {
  const text = String(line || "").trim();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (_) {
    return null;
  }
}

function appendProgressEvent(event) {
  const message = formatProgressEvent(event);
  if (!message) return;
  setStatus(message);
  progressLogEl.hidden = false;
  const item = document.createElement("li");
  item.textContent = message;
  progressLogEl.appendChild(item);
  while (progressLogEl.children.length > 10) {
    progressLogEl.removeChild(progressLogEl.firstElementChild);
  }
}

function formatProgressEvent(event) {
  const message = String(event?.message || "").trim();
  if (!message) return "";
  const progress = Number(event.progress);
  const total = Number(event.total);
  if (Number.isFinite(progress) && Number.isFinite(total) && total > 0) {
    return `[${Math.round(progress)}/${Math.round(total)}] ${message}`;
  }
  return message;
}

function resetProgressLog() {
  progressLogEl.hidden = true;
  progressLogEl.innerHTML = "";
}

function updateActionState() {
  const selectedCount = fileInput.files?.length || 0;
  runBtn.disabled = isBusy || selectedCount === 0;
  runBtn.textContent = selectedCount
    ? `上传并解析 ${selectedCount} 个文件`
    : "上传解析";
  inspectBtn.disabled = isBusy || !isCompleteMapResults(currentMapResults);
  clearBtn.disabled = isBusy;
  fileInput.disabled = isBusy;
}

function isCompleteMapResults(value) {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every(
      (item) =>
        item &&
        typeof item === "object" &&
        Array.isArray(item.mapped_results),
    )
  );
}

function hasInspectResult(inspectResult) {
  if (Array.isArray(inspectResult)) return inspectResult.length > 0;
  return Boolean(
    inspectResult &&
      (Object.prototype.hasOwnProperty.call(inspectResult, "inspection_passed") ||
        inspectResult.details),
  );
}

function render(mapResults, inspectResult, activeIndex = 0) {
  const entries = collectStatements(mapResults, inspectResult);
  renderSummary(mapResults, inspectResult);
  resultsEl.innerHTML = "";

  if (!entries.length) {
    resultsEl.innerHTML = '<div class="empty-state">没有可展示的映射结果</div>';
    return;
  }

  const tabs = document.createElement("div");
  tabs.className = "statement-tabs";
  const stage = document.createElement("div");
  stage.className = "statement-stage";

  entries.forEach((entry, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "statement-tab";
    button.textContent = makeTabLabel(entry);
    button.addEventListener("click", () => showStatement(entries, inspectResult, index));
    tabs.appendChild(button);
  });

  resultsEl.appendChild(tabs);
  resultsEl.appendChild(stage);
  const nextActiveIndex = Math.min(Math.max(activeIndex, 0), entries.length - 1);
  showStatement(entries, inspectResult, nextActiveIndex);
}

function collectStatements(mapResults, inspectResult) {
  const entries = [];
  const normalizedInspectFiles = normalizeInspectFiles(inspectResult);
  for (const [fileIndex, fileResult] of (mapResults || []).entries()) {
    const inspectFile = findInspectFileResult(normalizedInspectFiles, fileResult, fileIndex);
    for (const [mappedIndex, mapped] of (fileResult.mapped_results || []).entries()) {
      const statementType = mapped.table_type || resolveStatementType(mapped.table_name);
      const inspected = findInspectedResult(inspectFile, mapped, mappedIndex, statementType);
      entries.push({ fileResult, mapped, statementType, inspected });
    }
  }
  return entries.sort((left, right) => {
    const byType =
      (statementOrder[left.statementType] ?? 99) -
      (statementOrder[right.statementType] ?? 99);
    if (byType !== 0) return byType;
    return String(left.mapped.table_name || "").localeCompare(
      String(right.mapped.table_name || ""),
      "zh-Hans-CN",
    );
  });
}

function showStatement(entries, inspectResult, activeIndex) {
  currentActiveIndex = activeIndex;
  const buttons = resultsEl.querySelectorAll(".statement-tab");
  buttons.forEach((button, index) => {
    button.classList.toggle("active", index === activeIndex);
  });

  const stage = resultsEl.querySelector(".statement-stage");
  stage.innerHTML = "";
  const entry = entries[activeIndex];
  const details = entry.inspected?.details || collectLegacyDetails(inspectResult, entry.statementType);
  stage.appendChild(renderStatement(entry.fileResult, entry.mapped, entry.statementType, details));
}

function makeTabLabel(entry) {
  const tableName = entry.mapped.table_name || "未命名报表";
  const fileName = entry.fileResult.file_name || "";
  return fileName ? `${tableName} · ${fileName}` : tableName;
}

function renderSummary(mapResults, inspectResult) {
  const files = mapResults?.length || 0;
  const tables = (mapResults || []).reduce(
    (total, file) => total + (file.mapped_results?.length || 0),
    0,
  );
  const hasInspection = hasInspectResult(inspectResult);
  const inspectFiles = normalizeInspectFiles(inspectResult);
  const detailItems = inspectFiles.length
    ? inspectFiles.flatMap((file) =>
        (file.inspected_results || []).flatMap((item) => item.details || []),
      )
    : Object.values(inspectResult?.details || {}).flat();
  const failed = hasInspection
    ? detailItems.filter((item) => normalizeStatus(getCheckStatus(item)) === "fail").length
    : "-";
  const inspectionPassed = inspectFiles.length
    ? inspectFiles.every((item) => item.inspection_passed)
    : Boolean(inspectResult?.inspection_passed);
  let statusText = "未校验";
  if (hasPendingEdits) {
    statusText = hasInspection ? "已修改待重新校验" : "已修改未校验";
  } else if (hasInspection) {
    statusText = inspectionPassed ? "通过" : "需关注";
  }

  summaryEl.hidden = false;
  summaryEl.innerHTML = [
    ["文件", files],
    ["报表", tables],
    ["校验状态", statusText],
    ["失败", failed],
  ]
    .map(
      ([label, value]) =>
        `<div class="summary-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`,
    )
    .join("");
}

function renderStatement(fileResult, mapped, statementType, details) {
  const section = document.createElement("article");
  section.className = "statement";

  const tableName = mapped.table_name || "未命名报表";
  const company = fileResult.company_name || "未识别公司";
  const fileName = fileResult.file_name || "未命名文件";
  const viewModel = buildViewModel(mapped.view_data);
  const annotations = buildRowAnnotations(statementType, viewModel, details);

  section.innerHTML = `
    <header class="statement-head">
      <div class="statement-title">
        <h2>${escapeHtml(company)} · ${escapeHtml(tableName)}</h2>
        <div class="meta">${escapeHtml(fileName)} · ${escapeHtml(mapped.date || "-")} · 第 ${escapeHtml(mapped.page ?? "-")} 页</div>
      </div>
      <span class="badge">${mapped.is_consolidated ? "合并" : "本部"}</span>
    </header>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>科目</th>
            <th>期初</th>
            <th>期初校验</th>
            <th>期末</th>
            <th>期末校验</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  `;

  const tbody = section.querySelector("tbody");
  for (const row of viewModel.rows) {
    tbody.appendChild(renderRow(row, annotations, statementType));
  }
  return section;
}

function renderRow(row, annotations, statementType) {
  const tr = document.createElement("tr");
  const rowChecks = annotations.byName.get(normalizeName(row.name)) || [];
  const propagatedBeginStatus = getPropagatedPeriodStatus(
    annotations.statusByName,
    row.name,
    "begin",
  );
  const propagatedEndStatus = getPropagatedPeriodStatus(
    annotations.statusByName,
    row.name,
    "end",
  );
  const displayChecks = filterDisplayChecks(dedupeChecks(rowChecks), {
    begin: propagatedBeginStatus,
    end: propagatedEndStatus,
  });
  const beginChecks = checksForPeriod(displayChecks, "begin");
  const endChecks = checksForPeriod(displayChecks, "end");
  const beginStatus = resolvePeriodStatus(beginChecks, propagatedBeginStatus);
  const endStatus = resolvePeriodStatus(endChecks, propagatedEndStatus);

  if (row.kind === "group") {
    const hasEditableValues =
      Boolean(row.code) || (Array.isArray(row.values) && row.values.length > 0);
    tr.className = [
      "group-row",
      `row-level-${Math.min(row.level || 0, 3)}`,
      hasEditableValues ? "group-with-values" : "",
    ]
      .filter(Boolean)
      .join(" ");
    tr.innerHTML = `
      <td class="account">${escapeHtml(row.name)}</td>
      ${renderPeriodCells(row, statementType, "begin", beginChecks, beginStatus, hasEditableValues)}
      ${renderPeriodCells(row, statementType, "end", endChecks, endStatus, hasEditableValues)}
    `;
    wireValueInputs(tr, row);
    return tr;
  }

  tr.className = `row-level-${Math.min(row.level || 0, 3)}`;
  tr.innerHTML = `
    <td class="account">${escapeHtml(row.name)}</td>
    ${renderPeriodCells(row, statementType, "begin", beginChecks, beginStatus, true)}
    ${renderPeriodCells(row, statementType, "end", endChecks, endStatus, true)}
  `;
  wireValueInputs(tr, row);
  return tr;
}

function renderPeriodCells(row, statementType, slot, checks, status, hasEditableValues) {
  if (!hasEditableValues) {
    return '<td class="number"></td><td class="check"></td>';
  }

  const applicable = isPeriodApplicable(row, statementType, slot);
  const statusClass = applicable && status ? `period-${status}` : "";
  const valueClass = ["number", "period-value", statusClass].filter(Boolean).join(" ");
  const checkClass = ["check", "period-check", statusClass].filter(Boolean).join(" ");
  const checkHtml = applicable ? renderChecks(checks, slot) : '<span class="empty">不适用</span>';
  return `
    <td class="${valueClass}">${renderValueEditor(row, statementType, slot)}</td>
    <td class="${checkClass}">${checkHtml}</td>
  `;
}

function isPeriodApplicable(row, statementType, slot) {
  return getDisplayValueIndex(row.values, statementType, slot) !== null;
}

function renderValueEditor(row, statementType, slot) {
  const valueIndex = getDisplayValueIndex(row.values, statementType, slot);
  if (valueIndex === null) {
    return '<span class="empty">不适用</span>';
  }

  const rawValue = row.values?.[valueIndex];
  const placeholder =
    rawValue === null || rawValue === undefined ? "未抽取" : rawValue === "" ? "空值" : "";
  const label = `${row.name}${slot === "begin" ? "期初" : "期末"}`;
  return `
    <input
      class="value-input"
      data-value-index="${valueIndex}"
      value="${escapeHtml(toInputValue(rawValue))}"
      placeholder="${escapeHtml(placeholder)}"
      aria-label="${escapeHtml(label)}"
    />
  `;
}

function wireValueInputs(tr, row) {
  tr.querySelectorAll(".value-input").forEach((input) => {
    const updateValue = () => {
      const valueIndex = Number(input.dataset.valueIndex);
      while (row.values.length <= valueIndex) {
        row.values.push(null);
      }
      row.values[valueIndex] = input.value;
      input.classList.add("edited");
    };

    input.addEventListener("input", updateValue);
    input.addEventListener("change", () => {
      updateValue();
      markValidationDirty();
    });
  });
}

function getDisplayValueIndex(values, statementType, slot) {
  if (statementType === "balance") {
    return slot === "begin" ? 0 : 1;
  }
  if (Array.isArray(values) && values.length > 1) {
    return slot === "begin" ? 0 : 1;
  }
  return slot === "end" ? 0 : null;
}

function toInputValue(value) {
  if (value === null || value === undefined) return "";
  return String(value);
}

function getDisplayValues(values, statementType) {
  if (statementType === "balance") {
    return [values?.[0], values?.[1]];
  }
  if (!values || values.length <= 1) {
    return ["", values?.[0]];
  }
  return [values[0], values[1]];
}

function buildViewModel(viewData) {
  const model = {
    rows: [],
    groups: new Map(),
    rowByCode: new Map(),
    rowByName: new Map(),
  };
  if (!viewData) return model;

  for (const node of viewData || []) {
    walkNode(node, 0, null, 0);
  }
  return model;

  function registerChildren(ownerKey, ownerNode, childLevel) {
    const meta = { group: ownerNode, items: [] };
    model.groups.set(ownerKey, meta);
    for (const child of ownerNode.children || []) {
      if (child?.type === "group") {
        const childKey = child.key || child.name;
        meta.items.push({ kind: "group", key: childKey });
        walkNode(child, childLevel, ownerKey, meta.items.length - 1);
      } else {
        const row = walkNode(child, childLevel, ownerKey, meta.items.length);
        if (row) meta.items.push({ kind: "row", row });
      }
    }
  }

  function walkNode(node, level, groupKey, indexInGroup) {
    if (!node) return null;
    if (node.type === "group") {
      const key = node.key || node.name;
      if (!Array.isArray(node.values)) {
        node.values = [];
      }
      const groupRow = {
        kind: "group",
        key,
        code: node.code || "",
        name: node.name || key,
        values: node.values,
        level,
        groupKey,
        indexInGroup,
      };
      model.rows.push(groupRow);
      if (groupRow.code) {
        model.rowByCode.set(groupRow.code, groupRow);
        model.rowByName.set(normalizeName(groupRow.name), groupRow);
      }
      registerChildren(key, node, level + 1);
      return null;
    }

    const row = normalizeRow(node.code, node, level, groupKey, indexInGroup);
    pushRow(row);
    if (Array.isArray(node.children) && node.children.length) {
      registerChildren(row.code || row.name, node, level + 1);
    }
    return row;
  }

  function pushRow(row) {
    model.rows.push(row);
    model.rowByCode.set(row.code, row);
    model.rowByName.set(normalizeName(row.name), row);
  }
}

function normalizeRow(code, raw, level, groupKey, indexInGroup) {
  if (Array.isArray(raw)) {
    return {
      kind: "row",
      code,
      name: raw[0] || code,
      values: raw.slice(1),
      level,
      groupKey,
      indexInGroup,
    };
  }
  if (raw && !Array.isArray(raw.values)) {
    raw.values = [];
  }
  return {
    kind: "row",
    code,
    name: raw?.name || raw?.[0] || code,
    values: raw?.values || [],
    level,
    groupKey,
    indexInGroup,
  };
}

function buildRowAnnotations(statementType, viewModel, details) {
  const byName = new Map();
  const statusByName = new Map();
  for (const detail of details || []) {
    const participants = collectParticipants(statementType, viewModel, detail);
    const targetNames = participants.size ? participants : new Set([normalizeCheckItem(getCheckItem(detail))]);
    for (const name of targetNames) {
      addCheckToName(byName, name, detail);
    }
    for (const name of collectPassedChildStatusNames(statementType, viewModel, detail)) {
      addStatusToName(statusByName, name, getCheckPeriod(detail), "pass");
    }
  }
  return { byName, statusByName };
}

function collectParticipants(statementType, viewModel, detail) {
  const names = new Set();
  const suspectNames = collectSuspectNames(viewModel, detail);
  const focused = isFocusedAttribution(detail, suspectNames);

  if (focused) {
    for (const name of suspectNames) {
      names.add(name);
    }
    return names;
  }

  for (const name of collectPrimaryCheckNames(statementType, viewModel, detail)) {
    names.add(name);
  }
  if (names.size) return names;

  for (const suspectName of suspectNames) {
    names.add(suspectName);
  }
  if (names.size) return names;

  for (const name of inferParticipantsFromView(viewModel, detail)) {
    names.add(name);
  }

  return names;
}

function collectPrimaryCheckNames(statementType, viewModel, detail) {
  const names = [];
  const checkName = normalizeCheckItem(getCheckItem(detail));
  const row = viewModel.rowByName.get(normalizeName(checkName));
  if (row) return [row.name];

  const leftName = getEquationLeftName(checkName);
  if (leftName && leftName !== checkName) {
    const leftRow = viewModel.rowByName.get(normalizeName(leftName));
    if (leftRow) return [leftRow.name];
  }

  const rule = findValidationRule(statementType, detail);
  const primaryCode = rule?.codes?.[0];
  const primaryRow = primaryCode ? viewModel.rowByCode.get(primaryCode) : null;
  if (primaryRow) names.push(primaryRow.name);
  return names;
}

function collectPassedChildStatusNames(statementType, viewModel, detail) {
  const names = [];
  if (normalizeStatus(getCheckStatus(detail)) !== "pass") return names;

  for (const name of collectValidatedComponentNames(viewModel, detail)) {
    names.push(name);
  }
  if (names.length) return names;

  const checkName = normalizeCheckItem(getCheckItem(detail));
  if (checkName.includes("=")) return names;

  const rule = findValidationRule(statementType, detail);
  if (!rule?.codes?.length) return names;

  const primaryCode = rule.codes[0];
  for (const code of rule.codes.slice(1)) {
    if (code === primaryCode) continue;
    const row = viewModel.rowByCode.get(code);
    if (row) names.push(row.name);
  }
  return names;
}

function collectValidatedComponentNames(viewModel, detail) {
  const names = [];
  for (const component of detail.validated_components || []) {
    const rowByCode = viewModel.rowByCode.get(component?.code);
    const componentName = rowByCode?.name || component?.name || "";
    if (!componentName) continue;
    const row = viewModel.rowByName.get(normalizeName(componentName));
    const resolvedName = row?.name || componentName;
    if (!names.some((name) => normalizeName(name) === normalizeName(resolvedName))) {
      names.push(resolvedName);
    }
  }
  return names;
}

function getEquationLeftName(value) {
  return String(value || "").split("=", 1)[0].trim();
}

function isFocusedAttribution(detail, suspectNames) {
  if (!suspectNames.length) return false;
  const reason = String(detail.reason || "");
  return (
    reason.includes("进一步校验发现") ||
    reason.includes("疑似") ||
    reason.includes("已定位") ||
    reason.includes("推测") ||
    reason.includes("推得")
  );
}

function collectSuspectNames(viewModel, detail) {
  const names = [];
  for (const suspect of detail.suspects || []) {
    const suspectName =
      typeof suspect === "string"
        ? suspect
        : suspect?.name || viewModel.rowByCode.get(suspect?.code)?.name || "";
    if (!suspectName) continue;
    const row = viewModel.rowByName.get(normalizeName(suspectName));
    const resolvedName = row?.name || suspectName;
    if (!names.some((name) => normalizeName(name) === normalizeName(resolvedName))) {
      names.push(resolvedName);
    }
  }
  return names;
}

function normalizeInspectFiles(inspectResult) {
  return Array.isArray(inspectResult) ? inspectResult : [];
}

function collectLegacyDetails(inspectResult, statementType) {
  return inspectResult?.details?.[statementType] || [];
}

function findInspectFileResult(inspectFiles, fileResult, fileIndex) {
  if (!inspectFiles.length) return null;
  const fileName = String(fileResult?.file_name || "");
  const companyName = String(fileResult?.company_name || "");
  const indexed = inspectFiles[fileIndex];
  if (
    indexed &&
    sameMaybe(fileName, indexed.file_name) &&
    sameMaybe(companyName, indexed.company_name)
  ) {
    return indexed;
  }
  return (
    inspectFiles.find(
      (item) =>
        sameMaybe(fileName, item?.file_name) &&
        sameMaybe(companyName, item?.company_name),
    ) || null
  );
}

function findInspectedResult(inspectFile, mapped, mappedIndex, statementType) {
  const candidates = inspectFile?.inspected_results;
  if (!Array.isArray(candidates) || !candidates.length) return null;
  const indexed = candidates[mappedIndex];
  if (indexed && sameMappedResult(indexed, mapped, statementType)) {
    return indexed;
  }
  return candidates.find((item) => sameMappedResult(item, mapped, statementType)) || null;
}

function sameMappedResult(inspected, mapped, statementType) {
  if (!inspected || !mapped) return false;
  return (
    sameMaybe(inspected.table_name, mapped.table_name) &&
    sameMaybe(inspected.table_type, mapped.table_type || statementType) &&
    sameMaybe(inspected.date, mapped.date) &&
    String(Boolean(inspected.is_consolidated)) === String(Boolean(mapped.is_consolidated))
  );
}

function sameMaybe(left, right) {
  if (left === undefined || left === null || left === "") return true;
  if (right === undefined || right === null || right === "") return true;
  return String(left) === String(right);
}

function findValidationRule(statementType, detail) {
  const checkName = normalizeName(normalizeCheckItem(getCheckItem(detail)));
  return (validationRules[statementType] || []).find((rule) =>
    rule.names.some((name) => normalizeName(name) === checkName),
  );
}

function inferParticipantsFromView(viewModel, detail) {
  const names = new Set();
  const checkName = normalizeCheckItem(getCheckItem(detail));
  const row = viewModel.rowByName.get(normalizeName(checkName));
  if (!row || !row.groupKey) {
    if (row) names.add(row.name);
    return names;
  }

  const group = viewModel.groups.get(row.groupKey);
  if (!group) {
    names.add(row.name);
    return names;
  }

  const before = group.items.slice(0, row.indexInGroup);
  const after = group.items.slice(row.indexInGroup + 1);
  const candidateItems = row.indexInGroup === 0 ? after : before;
  for (const item of candidateItems) {
    if (item.kind === "row") {
      names.add(item.row.name);
    } else if (item.kind === "group") {
      for (const terminalRow of findTerminalRows(viewModel, item.key)) {
        names.add(terminalRow.name);
      }
    }
  }
  names.add(row.name);
  return names;
}

function findTerminalRows(viewModel, groupKey) {
  const group = viewModel.groups.get(groupKey);
  if (!group) return [];
  const directRows = group.items
    .filter((item) => item.kind === "row")
    .map((item) => item.row);
  const totals = directRows.filter((row) => /合计|总计|净额|余额/.test(row.name));
  if (totals.length) return [totals[totals.length - 1]];
  if (directRows.length) return [directRows[directRows.length - 1]];

  for (let index = group.items.length - 1; index >= 0; index -= 1) {
    const item = group.items[index];
    if (item.kind === "group") {
      const nested = findTerminalRows(viewModel, item.key);
      if (nested.length) return nested;
    }
  }
  return [];
}

function addCheckToName(map, name, detail) {
  const key = normalizeName(name);
  if (!key) return;
  if (!map.has(key)) map.set(key, []);
  map.get(key).push(detail);
}

function addStatusToName(map, name, period, status) {
  const key = normalizeName(name);
  if (!key) return;
  const normalizedStatus = normalizeStatus(status);
  if (!normalizedStatus) return;
  if (!map.has(key)) {
    map.set(key, { begin: "", end: "", all: "" });
  }
  const statuses = map.get(key);
  const periodKey = normalizePeriod(period) || "all";
  if (statuses[periodKey] === "fail") return;
  if (normalizedStatus === "fail" || statuses[periodKey] !== "pass") {
    statuses[periodKey] = normalizedStatus;
  }
}

function getCheckItem(detail) {
  return detail?.check_item ?? detail?.check ?? "";
}

function getCheckStatus(detail) {
  return detail?.status ?? detail?.result ?? "";
}

function getCheckPeriod(detail) {
  return normalizePeriod(detail?.period, getCheckItem(detail));
}

function normalizeCheckItem(value) {
  return String(value || "")
    .replace(/\((年初|期初|期末|本期|上期)\)$/u, "")
    .trim();
}

function normalizeName(value) {
  return String(value || "")
    .replace(/\s+/g, "")
    .replace(/[：:]/g, "")
    .trim();
}

function normalizeStatus(status) {
  const value = String(status || "").trim().toLowerCase();
  if (["pass", "passed", "success", "ok"].includes(value)) return "pass";
  if (["fail", "failed", "error"].includes(value)) return "fail";
  return value;
}

function normalizePeriod(period, checkItem = "") {
  const value = String(period || "").trim().toLowerCase();
  if (["begin", "start", "opening", "年初", "期初"].includes(value)) return "begin";
  if (["end", "closing", "期末", "本期"].includes(value)) return "end";

  const item = String(checkItem || "");
  if (/(年初|期初)/u.test(item)) return "begin";
  if (/(期末|本期)/u.test(item)) return "end";
  return "";
}

function checksForPeriod(checks, period) {
  return checks.filter((item) => {
    const itemPeriod = getCheckPeriod(item);
    return itemPeriod ? itemPeriod === period : period === "end";
  });
}

function getPropagatedPeriodStatus(statusByName, name, period) {
  const statuses = statusByName.get(normalizeName(name));
  if (!statuses) return "";
  return statuses[period] || statuses.all || "";
}

function resolvePeriodStatus(checks, propagatedStatus = "") {
  if (checks.some((item) => normalizeStatus(getCheckStatus(item)) === "fail")) return "fail";
  if (checks.some((item) => normalizeStatus(getCheckStatus(item)) === "pass")) return "pass";
  return normalizeStatus(propagatedStatus);
}

function dedupeChecks(checks) {
  const seen = new Set();
  return checks.filter((item) => {
    const key = `${getCheckItem(item)}|${getCheckPeriod(item)}|${getCheckStatus(item)}|${item.reason}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function filterDisplayChecks(checks, propagatedStatuses = {}) {
  const visibleChecks = suppressRedundantBlockedDiagnostics(checks, propagatedStatuses);
  const inferredLiabilityEquityPeriods = new Set(
    visibleChecks
      .filter((item) => {
        const checkItem = normalizeName(getCheckItem(item));
        const reason = String(item.reason || "");
        return (
          checkItem.includes("负债和所有者权益") &&
          !checkItem.includes("=") &&
          reason.includes("使用推测的非流动负债合计值后")
        );
      })
      .map((item) => getCheckPeriod(item)),
  );

  if (!inferredLiabilityEquityPeriods.size) return visibleChecks;

  return visibleChecks.filter((item) => {
    const checkItem = normalizeName(getCheckItem(item));
    const isRedundantLiabilityEquitySplit =
      normalizeStatus(getCheckStatus(item)) === "pass" &&
      inferredLiabilityEquityPeriods.has(getCheckPeriod(item)) &&
      checkItem.includes("负债和所有者权益") &&
      checkItem.includes("=负债合计+所有者权益");
    return !isRedundantLiabilityEquitySplit;
  });
}

function suppressRedundantBlockedDiagnostics(checks, propagatedStatuses = {}) {
  const passedPeriodKeys = new Set(
    checks
      .filter((item) => normalizeStatus(getCheckStatus(item)) === "pass")
      .map((item) => getDisplayPeriodKey(item)),
  );
  for (const [period, status] of Object.entries(propagatedStatuses)) {
    if (normalizeStatus(status) === "pass") {
      passedPeriodKeys.add(period);
    }
  }
  if (!passedPeriodKeys.size) return checks;

  return checks.filter((item) => {
    if (!isBlockedDiagnosticCheck(item)) return true;
    return !passedPeriodKeys.has(getDisplayPeriodKey(item));
  });
}

function getDisplayPeriodKey(item) {
  return getCheckPeriod(item) || "end";
}

function isBlockedDiagnosticCheck(item) {
  if (normalizeStatus(getCheckStatus(item)) === "pass") return false;
  const reason = String(item.reason || "");
  return (
    reason.includes("无法校验") ||
    reason.includes("无法进行") ||
    reason.includes("缺少下级合计") ||
    reason.includes("缺少足够组成项")
  );
}

function renderChecks(checks, period) {
  if (!checks.length) {
    const label = period === "begin" ? "期初" : "期末";
    return `<span class="empty">${hasInspectResult(currentInspectResult) ? `无${label}校验` : "待校验"}</span>`;
  }
  return `<div class="check-list">${checks
    .map((item) => {
      const status = normalizeStatus(getCheckStatus(item));
      const klass = status === "pass" ? "ok" : status === "fail" ? "fail" : "warn";
      const title = normalizeCheckItem(getCheckItem(item));
      return `<span class="check-pill ${klass}"><strong>${escapeHtml(title)}</strong>${escapeHtml(item.reason || "")}</span>`;
    })
    .join("")}</div>`;
}

function resolveStatementType(tableName) {
  for (const [keyword, type] of Object.entries(statementTypeByName)) {
    if (String(tableName).includes(keyword)) return type;
  }
  return "balance";
}

function formatValue(value) {
  if (value === null || value === undefined) return '<span class="empty">未抽取</span>';
  if (value === "") return '<span class="empty">空值</span>';
  return escapeHtml(value);
}

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.style.color = isError ? "var(--danger)" : "var(--muted)";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

init();
