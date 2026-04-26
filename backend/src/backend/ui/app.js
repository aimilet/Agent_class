async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      Accept: "application/json",
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || JSON.stringify(payload, null, 2);
    } catch (_) {
      detail = await response.text();
    }
    throw new Error(detail);
  }

  return response.json();
}

function byId(id) {
  return document.getElementById(id);
}

function textOrDash(value) {
  return value ? String(value) : "-";
}

function renderStudents(students) {
  const container = byId("studentList");
  byId("studentCount").textContent = String(students.length);
  if (!students.length) {
    container.innerHTML = '<p class="muted">当前还没有学生数据。</p>';
    return;
  }
  container.innerHTML = students
    .map(
      (student) => `
        <article class="student-item">
          <strong>${student.name}</strong>
          <span class="muted">学号：${textOrDash(student.student_no)} | 班级：${textOrDash(student.class_name)}</span>
        </article>
      `
    )
    .join("");
}

function renderRules(rules) {
  const list = byId("ruleList");
  const select = byId("ruleSelect");
  if (!rules.length) {
    list.innerHTML = '<p class="muted">还没有规则，请先创建。</p>';
    select.innerHTML = "";
    return;
  }

  list.innerHTML = rules
    .map(
      (rule) => `
        <article class="rule-item">
          <strong>${rule.name}</strong>
          <span class="muted">${rule.template}</span>
          <p class="muted">${rule.description || "无说明"}</p>
        </article>
      `
    )
    .join("");

  select.innerHTML = rules
    .map((rule) => `<option value="${rule.id}">${rule.name}</option>`)
    .join("");
}

function renderJobs(jobs) {
  const container = byId("jobList");
  byId("jobCount").textContent = String(jobs.length);
  if (!jobs.length) {
    container.innerHTML = '<p class="muted">还没有审阅任务。</p>';
    return;
  }

  container.innerHTML = jobs
    .map((job) => {
      const submissions = (job.submissions || [])
        .map(
          (submission) => `
            <tr>
              <td>${submission.original_filename}</td>
              <td>${submission.status}</td>
              <td><span class="score-pill">${submission.score ?? "-"}</span></td>
              <td>${submission.review_summary || "-"}</td>
            </tr>
          `
        )
        .join("");
      return `
        <article class="job-card">
          <strong>${job.title}</strong>
          <span class="muted">状态：${job.status}</span>
          <p>${job.question}</p>
          <div class="table-shell">
            <table>
              <thead>
                <tr>
                  <th>文件</th>
                  <th>状态</th>
                  <th>分数</th>
                  <th>总结</th>
                </tr>
              </thead>
              <tbody>${submissions}</tbody>
            </table>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderRenameTable(items) {
  const shell = byId("renameResult");
  if (!items.length) {
    shell.innerHTML = '<p class="muted">暂无改名结果。</p>';
    return;
  }
  shell.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>原文件</th>
          <th>目标文件</th>
          <th>匹配学生</th>
          <th>置信度</th>
          <th>状态</th>
          <th>说明</th>
        </tr>
      </thead>
      <tbody>
        ${items
          .map(
            (item) => `
              <tr>
                <td>${item.source_path}</td>
                <td>${item.target_path || "-"}</td>
                <td>${item.matched_student || "-"}</td>
                <td>${item.confidence}</td>
                <td>${item.status}</td>
                <td>${item.reason || "-"}</td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

async function refreshDashboard() {
  const [health, students, rules, jobs] = await Promise.all([
    api("/health"),
    api("/students"),
    api("/rename-rules"),
    api("/review-jobs"),
  ]);

  byId("healthStatus").textContent = "在线";
  byId("storageRoot").textContent = health.storage_root;
  byId("databaseUrl").textContent = health.database_url;
  byId("llmBadge").textContent = health.llm_enabled ? "LLM 已启用" : "LLM 未启用";

  renderStudents(students);
  renderRules(rules);
  renderJobs(jobs);
}

function getRenamePayload() {
  const form = new FormData(byId("renameForm"));
  return {
    ruleId: form.get("rule_id"),
    payload: {
      directory_path: String(form.get("directory_path") || "").trim(),
      assignment_label: String(form.get("assignment_label") || "").trim() || null,
    },
  };
}

byId("importForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);

  try {
    const result = await api("/students/import", {
      method: "POST",
      body: formData,
    });
    byId("importResult").textContent = JSON.stringify(result, null, 2);
    form.reset();
    await refreshDashboard();
  } catch (error) {
    byId("importResult").textContent = error.message;
  }
});

byId("ruleForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = {
    name: form.get("name"),
    template: form.get("template"),
    assignment_label_default: String(form.get("assignment_label_default") || "").trim() || null,
    description: String(form.get("description") || "").trim() || null,
    match_threshold: 76,
    enabled: true,
  };

  try {
    await api("/rename-rules", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    event.currentTarget.reset();
    await refreshDashboard();
  } catch (error) {
    alert(error.message);
  }
});

byId("previewButton").addEventListener("click", async () => {
  const { ruleId, payload } = getRenamePayload();
  try {
    const result = await api(`/rename-rules/${ruleId}/preview`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderRenameTable(result.items);
  } catch (error) {
    byId("renameResult").innerHTML = `<p class="muted">${error.message}</p>`;
  }
});

byId("applyButton").addEventListener("click", async () => {
  const { ruleId, payload } = getRenamePayload();
  try {
    const result = await api(`/rename-rules/${ruleId}/apply`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderRenameTable(result.items);
  } catch (error) {
    byId("renameResult").innerHTML = `<p class="muted">${error.message}</p>`;
  }
});

byId("reviewForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = {
    title: form.get("title"),
    question: form.get("question"),
    reference_answer: String(form.get("reference_answer") || "").trim() || null,
    rubric: String(form.get("rubric") || "").trim() || null,
    submission_paths: String(form.get("submission_paths") || "")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean),
    run_immediately: true,
  };

  try {
    await api("/review-jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    event.currentTarget.reset();
    await refreshDashboard();
  } catch (error) {
    alert(error.message);
  }
});

refreshDashboard().catch((error) => {
  byId("healthStatus").textContent = "连接失败";
  byId("storageRoot").textContent = error.message;
});
